"""Unit tests for the clinical guards and the timing math.

Run with: uv run python -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from rehab_slideshow import captions, storyboard
from rehab_slideshow.exercises import Exercise, load_exercise, validate_exercise

ROOT = Path(__file__).resolve().parent.parent


def _exercise() -> Exercise:
    return load_exercise(ROOT, "wall-climb")


def _storyboard() -> dict:
    return json.loads((ROOT / "storyboards" / "wall-climb.json").read_text())


class ExerciseValidationTests(unittest.TestCase):
    def test_shipped_exercise_is_valid(self):
        errors, _ = validate_exercise(_exercise())
        self.assertEqual(errors, [])

    def test_missing_precautions_blocks_build(self):
        raw = copy.deepcopy(_exercise().raw)
        raw["precautions"] = []
        errors, _ = validate_exercise(Exercise(raw=raw, path=Path("x.yaml")))
        self.assertTrue(any("precautions" in e for e in errors))

    def test_missing_source_blocks_build(self):
        raw = copy.deepcopy(_exercise().raw)
        del raw["source"]
        errors, _ = validate_exercise(Exercise(raw=raw, path=Path("x.yaml")))
        self.assertTrue(any("source" in e for e in errors))

    def test_dynamic_exercise_may_have_no_hold(self):
        raw = copy.deepcopy(_exercise().raw)
        raw["hold_seconds"] = None
        raw["hold_note"] = "No hold"
        errors, _ = validate_exercise(Exercise(raw=raw, path=Path("x.yaml")))
        self.assertFalse(any("hold" in e for e in errors))


class StoryboardValidationTests(unittest.TestCase):
    def test_shipped_storyboard_is_valid(self):
        errors, _ = storyboard.validate_storyboard(_storyboard(), _exercise())
        self.assertEqual(errors, [])

    def test_unsupported_claim_is_rejected(self):
        sb = copy.deepcopy(_storyboard())
        sb["frames"][2]["narration"] += " This exercise prevents lymphoedema."
        errors, _ = storyboard.validate_storyboard(sb, _exercise())
        self.assertTrue(any("unsupported claim" in e for e in errors))

    def test_range_of_motion_jump_is_rejected(self):
        sb = copy.deepcopy(_storyboard())
        sb["frames"][2]["pose"] = "hold"  # jump from reach 0.03 to 0.90
        errors, _ = storyboard.validate_storyboard(sb, _exercise())
        self.assertTrue(any("jumps" in e for e in errors))

    def test_missing_repetition_count_is_rejected(self):
        sb = copy.deepcopy(_storyboard())
        for frame in sb["frames"]:
            frame["narration"] = frame["narration"].replace("five", "several").replace(" 5", "")
            frame["bullets"] = []
        errors, _ = storyboard.validate_storyboard(sb, _exercise())
        self.assertTrue(any("repetition" in e for e in errors))

    def test_missing_precaution_frame_is_rejected(self):
        sb = copy.deepcopy(_storyboard())
        sb["frames"][-1]["kind"] = "action"
        errors, _ = storyboard.validate_storyboard(sb, _exercise())
        self.assertTrue(any("precaution" in e for e in errors))


class CaptionTests(unittest.TestCase):
    def test_captions_respect_two_lines_of_42_characters(self):
        sb = _storyboard()
        cues = [
            {"id": f"cue-{f['id']}", "frame": f["id"], "text": f["narration"]}
            for f in sb["frames"]
        ]
        timeline = captions.build_timeline(
            [{**c, "file": "x.mp3", "duration": 5.0} for c in cues], Path(".")
        )
        entries = captions.caption_entries(timeline)
        self.assertTrue(entries)
        for start, end, text in entries:
            lines = text.split("\n")
            self.assertLessEqual(len(lines), 2, text)
            for line in lines:
                self.assertLessEqual(len(line), 42, line)
            self.assertGreater(end, start)

    def test_quantize_keeps_everything_on_the_frame_grid(self):
        cues = [
            {"id": "cue-01", "frame": "01", "text": "a", "file": "a.mp3", "duration": 3.31},
            {"id": "cue-02", "frame": "02", "text": "b", "file": "b.mp3", "duration": 2.17},
        ]
        timeline = captions.quantize(captions.build_timeline(cues, Path(".")), 30)
        for cue in timeline:
            self.assertAlmostEqual(cue.frame_duration * 30, round(cue.frame_duration * 30), 6)
        self.assertAlmostEqual(
            captions.video_duration(timeline), sum(c.frame_duration for c in timeline), 6
        )


if __name__ == "__main__":
    unittest.main()
