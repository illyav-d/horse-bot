import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts.evaluate_reality_check import summarize, evaluate
from horsie.reality_check import AssessmentReply, QuotaError


class EvaluationTests(unittest.TestCase):
    def test_abstentions_do_not_count_as_correct_and_false_calls_are_separate(self):
        report = summarize([
            {"origin": "ai", "verdict": "Likely AI-generated"},
            {"origin": "ai", "verdict": "Inconclusive"},
            {"origin": "non_ai", "verdict": "Likely AI-generated"},
            {"origin": "ai", "verdict": "Likely authentic"},
            {"origin": "non_ai", "error": "Quota reached"},
        ])
        self.assertEqual(report["completed"], 4)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["decisive_accuracy"], 1 / 3)
        self.assertEqual(report["coverage"], 3 / 4)
        self.assertEqual(report["false_ai"], 1)
        self.assertEqual(report["false_authentic"], 1)

    def test_no_accuracy_claim_when_all_checks_abstain_or_fail(self):
        for rows in ([], [{"origin": "ai", "verdict": "Inconclusive"}], [{"error": "Quota"}]):
            self.assertIsNone(summarize(rows)["decisive_accuracy"])


class EvaluationRunTests(unittest.IsolatedAsyncioTestCase):
    def answer(self):
        return AssessmentReply("**Inconclusive**\nUnclear.", assessment={
            "verdict": "Inconclusive", "observations": ["A shape is visible."],
            "needs_review": False, "reasons": "Unclear.",
        })

    async def test_known_origin_and_filename_are_not_sent_to_model(self):
        case = {"file": "confirmed_ai.png", "origin": "ai", "provenance": "private label"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / case["file"]).write_bytes(b"fixture image")

            async def check(text, images, *, image_loader):
                self.assertNotIn(case["file"], text)
                self.assertNotIn(case["provenance"], text)
                self.assertEqual(images, ["https://evaluation.invalid/image"])
                self.assertEqual(await image_loader(None, images[0]), ("image/png", b"fixture image"))
                return self.answer()

            with patch("scripts.evaluate_reality_check.FIXTURES", root), patch("scripts.evaluate_reality_check.assess", side_effect=check):
                report = await evaluate([case], 0)
            self.assertEqual(report["summary"]["inconclusive"], 1)

    async def test_short_quota_wait_is_bounded_and_completed_cases_are_not_repeated(self):
        cases = [{"file": "one.png", "origin": "ai"}, {"file": "two.png", "origin": "non_ai"}]
        with patch("scripts.evaluate_reality_check.assess", AsyncMock(side_effect=[self.answer(), QuotaError(2), self.answer()])) as check, \
                patch("scripts.evaluate_reality_check.asyncio.sleep", AsyncMock()) as sleep:
            report = await evaluate(cases, 0)
        self.assertEqual(check.await_count, 3)
        self.assertEqual(report["summary"]["completed"], 2)
        self.assertTrue(all(call.args[0] <= 60 for call in sleep.await_args_list))

    async def test_daily_quota_stops_without_waiting_or_retrying(self):
        with patch("scripts.evaluate_reality_check.assess", AsyncMock(side_effect=QuotaError(daily=True))) as check, \
                patch("scripts.evaluate_reality_check.asyncio.sleep", AsyncMock()) as sleep:
            report = await evaluate([{"file": "one.png", "origin": "ai"}], 0)
        check.assert_awaited_once()
        sleep.assert_not_awaited()
        self.assertEqual(report["summary"]["errors"], 1)
