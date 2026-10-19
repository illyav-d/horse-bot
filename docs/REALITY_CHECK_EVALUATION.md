# Image-check evaluation

Run from the repository root:

```powershell
python -m scripts.evaluate_reality_check --prepare
python -m scripts.evaluate_reality_check
python -m scripts.evaluate_reality_check --run --output data/reality_eval/current.json
```

Preparation downloads two public sources and creates five cases: a photographic
horse GIF, a compressed copy, a copy with a long held frame, a documented AI still,
and that AI still converted to GIF. Generated files, hashes, source labels and
results are under `data/reality_eval/` (ignored by Git). Preparation reuses existing
source downloads. The source URLs and transformation recipe are versioned in the
script so the set can be recreated.

The horse sequence is [Muybridge's photographic horse study](https://commons.wikimedia.org/wiki/File:Muybridge_race_horse_animated.gif),
in the public domain. The AI example is the geodesic landscape explicitly
identified in the [DiffusionDB dataset card](https://huggingface.co/datasets/poloclub/diffusiondb/blob/4de7acd1878f82cc474f4bc432e27f4b3e363ad7/README.md#data-instances)
(CC0). A GIF made from that still tests GIF encoding, not generated motion.
This is a small regression set with related variants, not a representative
accuracy benchmark. Add more independent real and AI examples with documented
provenance to the manifest before drawing broader conclusions.

Live runs require `GROQ_API_KEY` and optionally `GROQ_REALITY_CHECK_MODEL`.
They use the bot's actual assessment pipeline and API quota, with a default
30-second interval between cases. Source labels, filenames and provenance are
kept out of model input. Runs stop on quota exhaustion and retain partial results.
The runner waits once for a reported short cooldown of at most 60 seconds, then
stops if quota errors persist. Daily quota exhaustion stops immediately. Use
`--resume` to keep completed cases from the output report and retry unfinished ones.
Reports separate abstentions, errors, false AI calls and false authentic calls;
accuracy is calculated only among decisive answers, alongside coverage.

Save a report before changing the pipeline, then compare a later run:

```powershell
python -m scripts.evaluate_reality_check --run --baseline data/reality_eval/before.json --output data/reality_eval/after.json
```

To diagnose a particular Imgur link without calling Groq:

```powershell
python -m scripts.probe_imgur_links https://imgur.com/EXAMPLE
```

Imgur sharing links, direct images and GIFV links use different forms. Single
sharing links probe the media host; GIFV/MP4 forms try the corresponding GIF.
Album/gallery links require readable image metadata and select the advertised
cover rather than scanning the whole album. HTTP 429 from Imgur gets an explicit
rate-limit message; unavailable originals still require a direct upload.
