"""Tests for the daily readiness gate, strategy normalisation and WeChat clip."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


daily = _load("daily_ready", "skills/podcast-youtuber-agent/scripts/daily_ready.py")
qa = _load("qa_audio", "skills/tech-commentary-slideshow/scripts/qa_audio.py")
clip = _load("wechat_clip", "skills/podcast-marketing-agent/scripts/wechat_clip.py")
qw = _load("qwen3_worker", "skills/podcast-youtuber-agent/scripts/qwen3_worker.py")
avatar = _load("apply_avatar", "tools/gen/apply_avatar.py")


class BusinessDayTests(unittest.TestCase):
    def test_before_six_belongs_to_previous_day(self):
        self.assertEqual(daily.business_day(datetime(2026, 11, 2, 5, 59)), "2026-11-01")

    def test_after_six_is_same_day(self):
        self.assertEqual(daily.business_day(datetime(2026, 11, 2, 6, 0)), "2026-11-02")


class NumberNormalisationTests(unittest.TestCase):
    def test_spelled_numbers_match_asr_digits(self):
        expected = ("At a low-thirties multiple, with about seventy-five percent of "
                    "earnings still coming from the legacy business.")
        actual = ("At a low 30s multiple, with about 75% of earnings still coming "
                  "from the legacy business.")
        a = qa._normalise(expected, "en")
        b = qa._normalise(actual, "en")
        rate = qa._distance(a, b) / max(1, len(a))
        self.assertLess(rate, 0.10)

    def test_hundreds_and_compounds(self):
        tokens = qa._normalise("two hundred and twenty-five basis points", "en")
        self.assertIn("225", tokens)

    def test_decimal_billion_matches_asr(self):
        tokens = qa._normalise("three-point-four billion", "en")
        self.assertIn("3400000000", tokens)

    def test_hundred_and_compound_billion(self):
        tokens = qa._normalise("a hundred and eighty-four billion", "en")
        self.assertIn("184000000000", tokens)

    def test_adjacent_numbers_do_not_merge(self):
        tokens = qa._normalise("November 5, 2026", "en")
        self.assertIn("2026", tokens)
        self.assertIn("5", tokens)

    def test_century_decade_matches_asr(self):
        tokens = qa._normalise("in the nineteen-fifties", "en")
        self.assertIn("1950s", tokens)


class AvatarSizingTests(unittest.TestCase):
    def test_landscape_uses_one_third_height(self):
        self.assertEqual(avatar._avatar_edge(1920, 1080), 360)

    def test_portrait_uses_one_third_width(self):
        self.assertEqual(avatar._avatar_edge(1080, 1920), 360)


class ChunkingTests(unittest.TestCase):
    def test_short_sentences_before_a_long_one_are_kept(self):
        text = ("One short sentence. Another short sentence. " +
                "A much longer sentence that has to be split because it exceeds "
                "the chunk limit by a wide margin and would otherwise be dropped, "
                "which used to silently truncate the narration audio.")
        parts = qw._split_chunks(text, 90)
        self.assertEqual(" ".join(parts).strip(), text)
        self.assertTrue(all(len(part) <= 90 for part in parts))


class SrtShiftTests(unittest.TestCase):
    def test_keeps_only_overlapping_cues_and_shifts_clock(self):
        source = (
            "1\n00:00:00,000 --> 00:00:05,000\nfirst\n\n"
            "2\n00:01:00,000 --> 00:01:05,000\nsecond\n\n"
            "3\n00:01:10,000 --> 00:01:12,000\nthird\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.srt"
            out = Path(tmp) / "out.srt"
            src.write_text(source)
            self.assertTrue(clip._shift_srt(src, 60.0, 6.0, out))
            text = out.read_text()
            self.assertIn("second", text)
            self.assertNotIn("first", text)
            self.assertNotIn("third", text)
            self.assertIn("00:00:00,000 --> 00:00:05,000", text)


class EnsureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        daily.LEDGER = root / "ledger.json"
        daily.LOCK = root / "lock"
        daily.STOP = root / "STOP"
        self.calls = []

        def scan():
            self.calls.append("scan")
            return True, {"ok": 1}

        def pick():
            self.calls.append("pick")
            return True, {"title": "Example"}

        daily._scan = scan
        daily._pick = pick

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_run_is_idempotent(self):
        first = daily.ensure(["scan", "pick"], budget_min=5)
        second = daily.ensure(["scan", "pick"], budget_min=5)
        self.assertEqual(first["status"], "CATCH_UP")
        self.assertEqual(second["status"], "CATCH_UP")
        self.assertEqual(self.calls, ["scan", "pick"])

    def test_missed_day_is_skipped_once(self):
        record = {"days": {"2026-10-31": {"scan": {"status": "pending"},
                                          "pick": {"status": "pending"}}}}
        daily.LEDGER.write_text(json.dumps(record))
        report = daily.ensure(["scan"], budget_min=5)
        data = json.loads(daily.LEDGER.read_text())
        self.assertIn("skipped", json.dumps(data["days"]["2026-10-31"]))
        self.assertTrue(report["skipped_old_days"] or data["days"]["2026-10-31"]["scan"]["status"] == "skipped")


if __name__ == "__main__":
    unittest.main()
