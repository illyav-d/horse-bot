"""Small, source-labelled evaluation: prepare fixtures, then optionally call Groq.

Run from the repository root: python -m scripts.evaluate_reality_check --prepare
Then: python -m scripts.evaluate_reality_check --run --output data/reality_eval/results.json
"""

import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from PIL import Image, ImageSequence

from horsie.reality_check import CheckError, QuotaError, assess, gif_parts, MAX_IMAGE_BYTES


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "reality_eval"
SOURCES = {
    "horse": {
        "url": "https://upload.wikimedia.org/wikipedia/commons/d/dd/Muybridge_race_horse_animated.gif",
        "provenance": "https://commons.wikimedia.org/wiki/File:Muybridge_race_horse_animated.gif",
        "origin": "non_ai", "license": "Public domain (Eadweard Muybridge photographic sequence)",
    },
    "ai": {
        "url": "https://i.imgur.com/gqWcRs2.png",
        "provenance": "https://huggingface.co/datasets/poloclub/diffusiondb/blob/4de7acd1878f82cc474f4bc432e27f4b3e363ad7/README.md#data-instances",
        "origin": "ai", "license": "CC0 1.0 (DiffusionDB)",
    },
}


def prepare():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    raw = {}
    for name, source in SOURCES.items():
        cached = FIXTURES / ("horse.gif" if name == "horse" else "ai.png")
        if cached.exists():
            raw[name] = cached.read_bytes()
        else:
            request = Request(source["url"], headers={"User-Agent": "Horsie-Image-Evaluation/1.0"})
            with urlopen(request, timeout=20) as response:
                raw[name] = response.read(MAX_IMAGE_BYTES + 1)
        if len(raw[name]) > MAX_IMAGE_BYTES:
            raise ValueError(f"{name}: source exceeds 8 MB")
    (FIXTURES / "horse.gif").write_bytes(raw["horse"])
    (FIXTURES / "ai.png").write_bytes(raw["ai"])
    with Image.open(io.BytesIO(raw["horse"])) as source:
        frames = []
        durations = []
        for frame in ImageSequence.Iterator(source):
            small = frame.convert("RGB")
            small.info.clear()
            small.thumbnail((128, 128))
            frames.append(small.quantize(colors=16))
            durations.append(frame.info.get("duration", 100) or 100)
        frames[0].save(FIXTURES / "horse_compressed.gif", save_all=True,
                       append_images=frames[1:], duration=durations, loop=0)
        durations[0] = max(sum(durations) * 2, 1000)
        frames[0].save(FIXTURES / "horse_held_frame.gif", save_all=True,
                       append_images=frames[1:], duration=durations, loop=0)
    with Image.open(io.BytesIO(raw["ai"])) as source:
        source.convert("RGB").quantize(colors=32).save(FIXTURES / "ai_still.gif")
    cases = []
    for filename, source_name, variant in (
        ("horse.gif", "horse", "Photographic horse sequence"),
        ("horse_compressed.gif", "horse", "Same sequence at 128px and 16 colours"),
        ("horse_held_frame.gif", "horse", "Compressed sequence with a long first-frame hold"),
        ("ai.png", "ai", "Stable Diffusion example identified in the dataset card"),
        ("ai_still.gif", "ai", "Same AI still converted to GIF; not AI-generated motion"),
    ):
        cases.append(dict(SOURCES[source_name], file=filename, variant=variant,
                          sha256=hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest()))
    (FIXTURES / "manifest.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(cases)} labelled cases in {FIXTURES}")


def load_cases():
    cases = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    for case in cases:
        path = (FIXTURES / case["file"]).resolve()
        if path.parent != FIXTURES.resolve():
            raise ValueError("Fixture paths must stay in the evaluation directory")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != case["sha256"]:
            raise ValueError(f"Fixture changed: {path.name}")
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        if path.suffix == ".gif":
            gif_parts(data)
    return cases


def summarize(results):
    usable = [row for row in results if "verdict" in row]
    decisive = [row for row in usable if row["verdict"] != "Inconclusive"]
    correct = sum((row["verdict"] == "Likely AI-generated") == (row["origin"] == "ai") for row in decisive)
    return {
        "completed": len(usable), "errors": len(results) - len(usable),
        "decisive": len(decisive), "inconclusive": len(usable) - len(decisive),
        "correct_decisive": correct,
        "decisive_accuracy": correct / len(decisive) if decisive else None,
        "coverage": len(decisive) / len(usable) if usable else None,
        "false_ai": sum(row["origin"] == "non_ai" and row["verdict"] == "Likely AI-generated" for row in usable),
        "false_authentic": sum(row["origin"] == "ai" and row["verdict"] == "Likely authentic" for row in usable),
    }


async def evaluate(cases, interval, previous=None, quota_retry=True):
    results = [row for row in (previous or []) if "verdict" in row]
    done = {row["file"] for row in results}
    pending = [case for case in cases if case["file"] not in done]
    for index, case in enumerate(pending):
        # Labels, filenames and provenance are never supplied to the model.
        async def local_image(_session, _url):
            data = (FIXTURES / case["file"]).read_bytes()
            return ("image/gif" if case["file"].endswith(".gif") else "image/png"), data
        try:
            answer = await asyncio.wait_for(assess("Assess the supplied image(s) for signs of AI generation.",
                                                  ["https://evaluation.invalid/image"], image_loader=local_image), timeout=55)
            results.append(dict(case, **answer.assessment))
            print(f"{case['file']}: {answer.assessment['verdict']}", flush=True)
            if answer.quota_error:
                print("Stopped after a review hit the API quota; the first answer was retained.", flush=True)
                break
        except QuotaError as error:
            if quota_retry and not error.daily and error.seconds <= 60:
                print(f"Waiting {error.seconds}s for Groq's short quota cooldown, then retrying once.", flush=True)
                await asyncio.sleep(error.seconds)
                # Completed cases are carried forward; only unfinished cases are retried.
                return await evaluate(cases, interval, results, quota_retry=False)
            results.append(dict(case, error=str(error)))
            break
        except (CheckError, asyncio.TimeoutError) as error:
            results.append(dict(case, error=str(error) or "Timed out"))
            print(f"{case['file']}: {str(error) or 'Timed out'}", flush=True)
            if "admin" in str(error).lower():
                break
        if index < len(pending) - 1:
            await asyncio.sleep(interval)
    return {"timestamp": datetime.now(timezone.utc).isoformat(),
            "model": os.getenv("GROQ_REALITY_CHECK_MODEL", "qwen/qwen3.8-27b"),
            "planned_cases": len(cases), "summary": summarize(results), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Download public source images and create labelled variants")
    parser.add_argument("--run", action="store_true", help="Send fixtures to Groq (uses API quota)")
    parser.add_argument("--output", type=Path, default=FIXTURES / "results.json")
    parser.add_argument("--baseline", type=Path, help="Compare summary with a saved earlier run")
    parser.add_argument("--resume", action="store_true", help="Keep completed cases from the output report and retry the rest")
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args()
    if args.interval < 0:
        parser.error("--interval must be nonnegative")
    if args.prepare:
        prepare()
    cases = load_cases()
    print(f"Validated {len(cases)} fixtures and their hashes.")
    if args.run:
        if not os.getenv("GROQ_API_KEY", "").strip():
            parser.error("Set GROQ_API_KEY to run live evaluations")
        previous = json.loads(args.output.read_text(encoding="utf-8"))["results"] if args.resume and args.output.exists() else None
        report = asyncio.run(evaluate(cases, args.interval, previous))
        if args.baseline:
            report["baseline_summary"] = json.loads(args.baseline.read_text(encoding="utf-8"))["summary"]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2))
        print(f"Saved report to {args.output}")


if __name__ == "__main__":
    main()
