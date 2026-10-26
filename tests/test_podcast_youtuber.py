"""Unit tests for the podcast-youtuber-agent production layer.

Run with: uv run python -m unittest discover -s tests -v
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "podcast-youtuber-agent" / "scripts"
TECH_SCRIPTS = ROOT / "skills" / "tech-commentary-slideshow" / "scripts"
SHARED = ROOT / "skills" / "podcast-avatar-commentary" / "scripts"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_tech(name: str):
    spec = importlib.util.spec_from_file_location(f"tech_{name}", TECH_SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


slides = _load("slides")
voice_sample = _load("voice_sample")
youtube_upload = _load("youtube_upload")
fetch_popular = _load("fetch_popular")
trending = _load("trending")
bilingual = _load("bilingual")
pronunciation = _load("pronunciation")
narrate = _load("narrate")
autopilot = _load("autopilot")
plan_visuals = _load_tech("plan_visuals")
make_scenes = _load_tech("make_scenes")


class SlideValidationTests(unittest.TestCase):
    def _deck(self, kind: str = "chart", visual: str | None = None) -> dict:
        shot = {
            "id": "01",
            "kind": kind,
            "narration": "A short spoken beat.",
            "transition": "cut",
        }
        if kind == "chart":
            shot["heading"] = "The argument"
            shot["bullets"] = ["One", "Two"]
        if kind == "broll":
            shot["visual"] = visual
            shot["on_screen"] = "A b-roll title"
        return {
            "slug": "test",
            "title": "Test deck",
            "fps": 30,
            "format": "broll-slides",
            "shots": [shot],
        }

    def test_avatar_is_rejected(self):
        errors, _, _ = slides.validate(self._deck("avatar"), ROOT)
        self.assertTrue(any("avatar" in error for error in errors))

    def test_valid_card_deck(self):
        errors, _, summary = slides.validate(self._deck("chart"), ROOT)
        self.assertEqual(errors, [])
        self.assertEqual(summary["slides"], 1)

    def test_missing_broll_visual_is_rejected(self):
        errors, _, _ = slides.validate(self._deck("broll", "does-not-exist.png"), ROOT)
        self.assertTrue(any("visual not found" in error for error in errors))

    def test_existing_broll_visual_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "cover.png"
            Image.new("RGB", (16, 9), (20, 30, 40)).save(image)
            deck = self._deck("broll", str(image))
            errors, _, _ = slides.validate(deck, ROOT)
            self.assertEqual(errors, [])

    def test_long_narration_is_rejected(self):
        deck = self._deck("chart")
        deck["shots"][0]["narration"] = "x" * 341
        errors, _, _ = slides.validate(deck, ROOT)
        self.assertTrue(any("max is 340" in error for error in errors))

    def test_host_role_confusion_warns(self):
        deck = self._deck("chart")
        deck["shots"][0]["narration"] = "My guest explains why the trade is crowded."
        errors, warnings, _ = slides.validate(deck, ROOT)
        self.assertEqual(errors, [])
        self.assertTrue(
            any("independent commentator" in warning for warning in warnings)
        )


class VoiceSampleTests(unittest.TestCase):
    def test_trim_bounds_removes_edges_only(self):
        samples = np.zeros(48_000 * 4, dtype=np.float32)
        samples[48_000:144_000] = 0.4 * np.sin(
            np.linspace(0, 2 * np.pi * 220, 96_000)
        ).astype(np.float32)
        start, end = voice_sample.trim_bounds(samples)
        self.assertAlmostEqual(start, 0.85, places=1)
        self.assertAlmostEqual(end, 3.25, places=1)

    def test_trim_bounds_keeps_silent_input(self):
        samples = np.zeros(48_000, dtype=np.float32)
        start, end = voice_sample.trim_bounds(samples)
        self.assertEqual(start, 0.0)
        self.assertAlmostEqual(end, 1.0, places=2)


class PronunciationTests(unittest.TestCase):
    def test_finance_and_tech_heteronyms_get_tts_overrides(self):
        text = (
            "央行行长在行业会议上说，重定价、重定面值和重启是几回事。"
            "利差倒挂，杠杆率上升，看空情绪和跳空风险都在增加。"
            "调用模型时，应用层要处理供给链和下载量。"
        )
        tts_text, applied = pronunciation.prepare_tts_text(text)
        self.assertIn("央航航掌", tts_text)
        self.assertIn("航业", tts_text)
        self.assertIn("崇定价", tts_text)
        self.assertIn("崇定面值", tts_text)
        self.assertIn("崇启", tts_text)
        self.assertIn("利叉", tts_text)
        self.assertIn("到挂", tts_text)
        self.assertIn("杠敢绿", tts_text)
        self.assertIn("看跌", tts_text)
        self.assertIn("价格缺口", tts_text)
        self.assertIn("掉用", tts_text)
        self.assertIn("硬用层", tts_text)
        self.assertIn("楚理", tts_text)
        self.assertIn("供己链", tts_text)
        self.assertIn("下再量", tts_text)
        self.assertGreaterEqual(len(applied), 10)

    def test_non_chinese_text_is_untouched(self):
        text = "The Fed and the ECB are watching the long end of the curve."
        tts_text, applied = pronunciation.prepare_tts_text(text)
        self.assertEqual(tts_text, text)
        self.assertEqual(applied, [])

    def test_explicit_tts_text_wins_over_lexicon(self):
        shot = {
            "id": "01",
            "narration": "重定价和重启",
            "tts_text": "崇定价与重新启动",
        }
        report = narrate._apply_pronunciation([shot], None)
        self.assertEqual(shot["tts_text"], "崇定价与重新启动")
        self.assertEqual(report[0]["source"], "explicit")

    def test_qwen_jobs_use_tts_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            shot = {
                "id": "01",
                "narration": "重定价",
                "tts_text": "崇定价",
            }
            jobs = narrate._qwen3_jobs(
                [shot], Path(tmp), {}, {"01": "fingerprint"}, False
            )
        self.assertEqual(jobs[0]["text"], "崇定价")

    def test_lexicon_terms_are_unique_and_cover_current_finance_terms(self):
        terms = pronunciation.load_terms()
        matches = [term["match"] for term in terms]
        self.assertEqual(len(matches), len(set(matches)))
        for required in ("重定价", "重定", "行业", "利差", "杠杆率", "调用", "应用"):
            self.assertIn(required, matches)


class NarrationTailTests(unittest.TestCase):
    def _write(self, path: Path, samples: np.ndarray, sample_rate: int = 24000) -> None:
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(
                np.clip(samples * 32767.0, -32768, 32767).astype("<i2").tobytes()
            )

    def _duration(self, path: Path) -> float:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / handle.getframerate()

    def test_trim_long_low_level_tail(self):
        sample_rate = 24000
        speech = 0.30 * np.sin(2 * np.pi * 220 * np.arange(sample_rate) / sample_rate)
        silence = np.zeros(int(0.20 * sample_rate))
        noise = 0.004 * np.random.default_rng(7).standard_normal(int(3.0 * sample_rate))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tail.wav"
            self._write(path, np.concatenate([speech, silence, noise]))
            removed = narrate._trim_tail_artifact(path)
            self.assertGreater(removed, 2.5)
            self.assertLess(self._duration(path), 1.5)

    def test_keep_normal_short_tail(self):
        sample_rate = 24000
        speech = 0.30 * np.sin(2 * np.pi * 220 * np.arange(sample_rate) / sample_rate)
        silence = np.zeros(int(0.40 * sample_rate))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "normal.wav"
            self._write(path, np.concatenate([speech, silence]))
            self.assertEqual(narrate._trim_tail_artifact(path), 0.0)
            self.assertAlmostEqual(self._duration(path), 1.4, places=2)


class VisualLanguageTests(unittest.TestCase):
    def test_plan_language_defaults_to_chinese_for_cjk_decks(self):
        self.assertEqual(
            plan_visuals._language({"title": "柴油瓶颈", "shots": []}),
            "zh-Hans",
        )
        self.assertEqual(
            plan_visuals._language({"language": "en", "title": "Diesel"}),
            "en",
        )

    def test_scene_eyebrow_and_footer_follow_language(self):
        shot = {
            "id": "01",
            "kind": "markdown",
            "narration": "原油动了，成品油没动。",
            "heading": "原油动了，成品油没动",
            "visual": {
                "type": "markdown",
                "spec": {
                    "title": "原油动了，成品油没动",
                    "points": ["原油恢复八成到九成"],
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp)
            (module / "package.json").write_text("{}")
            scene = make_scenes._scene(
                "zh-test", shot, module, episode="评论", language="zh-Hans"
            )
            data = yaml.safe_load((module / scene["scene"]).read_text())
        self.assertEqual(data["eyebrow"], "评论 · 01")
        self.assertEqual(data["footer"], "评论 · 源音频")
        self.assertEqual(data["title"], "原油动了，成品油没动")


class LanguageDefaultTests(unittest.TestCase):
    def test_mandarin_is_the_default(self):
        args = SimpleNamespace(
            language="zh-Hans", english=False, bilingual=False,
            primary_language=None,
        )
        autopilot._resolve_language(argparse.ArgumentParser(), args)
        self.assertEqual(args.language, "zh-Hans")
        self.assertEqual(args.primary_language, "zh-Hans")

    def test_english_requires_an_explicit_flag(self):
        args = SimpleNamespace(
            language="en", english=True, bilingual=False,
            primary_language=None,
        )
        autopilot._resolve_language(argparse.ArgumentParser(), args)
        self.assertEqual(args.language, "en")
        self.assertEqual(args.primary_language, "en")

    def test_bilingual_is_opt_in(self):
        args = SimpleNamespace(
            language="zh-Hans", english=False, bilingual=True,
            primary_language=None,
        )
        autopilot._resolve_language(argparse.ArgumentParser(), args)
        self.assertEqual(args.language, "both")
        self.assertEqual(args.primary_language, "zh-Hans")


class YouTubeMetadataTests(unittest.TestCase):
    def _args(self, **overrides):
        values = dict(
            video="out/final.mp4",
            metadata=None,
            title="A specific title",
            description="A description with sources and disclosure.",
            description_file=None,
            tags="podcast, business",
            category_id="28",
            privacy="private",
            made_for_kids=False,
            no_synthetic_media=False,
            publish_at=None,
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_metadata_defaults_to_private(self):
        data = youtube_upload._load_metadata(
            self._args(
                privacy=None,
                title=None,
                description="A description with sources and disclosure.",
                tags=None,
            )
        )
        self.assertEqual(data["privacyStatus"], "private")
        self.assertTrue(data["containsSyntheticMedia"])
        self.assertFalse(data["selfDeclaredMadeForKids"])

    def test_synthetic_media_flag_can_be_disabled(self):
        data = youtube_upload._load_metadata(
            self._args(no_synthetic_media=True)
        )
        self.assertFalse(data["containsSyntheticMedia"])

    def test_schedule_forces_private_and_utc(self):
        when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        data = youtube_upload._load_metadata(
            self._args(publish_at=when, privacy="public")
        )
        self.assertEqual(data["privacyStatus"], "private")
        self.assertTrue(data["publishAt"].endswith("Z"))

    def test_empty_description_is_rejected(self):
        with self.assertRaises(ValueError):
            youtube_upload._load_metadata(self._args(description="  "))

    def test_metadata_chapters_are_appended_to_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "youtube.json"
            metadata.write_text(json.dumps({
                "chapters": [
                    {"start": "0:00", "title": "Intro"},
                    {"start": "1:00", "title": "Main idea"},
                ]
            }))
            data = youtube_upload._load_metadata(
                self._args(metadata=str(metadata), description="A description.")
            )
        self.assertIn("0:00 Intro", data["description"])
        self.assertIn("1:00 Main idea", data["description"])

    def test_metadata_chapters_replace_existing_description_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "youtube.json"
            metadata.write_text(json.dumps({
                "chapters": [
                    {"start": "0:00", "title": "Intro"},
                    {"start": "2:00", "title": "Main idea"},
                ]
            }))
            data = youtube_upload._load_metadata(
                self._args(
                    metadata=str(metadata),
                    description=(
                        "A description.\n\nChapters\n"
                        "0:00 Old intro\n1:00 Old middle\n\n#tag"
                    ),
                )
            )
        self.assertIn("0:00 Intro", data["description"])
        self.assertIn("2:00 Main idea", data["description"])
        self.assertNotIn("0:00 Old intro", data["description"])
        self.assertNotIn("1:00 Old middle", data["description"])
        self.assertTrue(data["description"].endswith("#tag\n"))

    def test_metadata_chapters_replace_mandarin_description_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "youtube.zh.json"
            metadata.write_text(json.dumps({
                "chapters": [
                    {"start": "0:00", "title": "新介绍"},
                    {"start": "2:00", "title": "新主体"},
                ]
            }, ensure_ascii=False))
            data = youtube_upload._load_metadata(
                self._args(
                    metadata=str(metadata),
                    description=(
                        "说明。\n\n章节：\n"
                        "0:00 旧介绍\n1:00 旧中间\n\nAI 语音披露"
                    ),
                )
            )
        self.assertIn("章节：\n0:00 新介绍\n2:00 新主体", data["description"])
        self.assertNotIn("0:00 旧介绍", data["description"])
        self.assertNotIn("1:00 旧中间", data["description"])
        self.assertTrue(data["description"].endswith("AI 语音披露\n"))

    def test_metadata_chapters_replace_headerless_timestamp_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "youtube.zh.json"
            metadata.write_text(json.dumps({
                "chapters": [
                    {"start": "0:00", "title": "新介绍"},
                    {"start": "2:00", "title": "新主体"},
                ]
            }, ensure_ascii=False))
            data = youtube_upload._load_metadata(
                self._args(
                    metadata=str(metadata),
                    description="说明。\n\n0:00 旧介绍\n1:00 旧中间\n\n尾注",
                )
            )
        self.assertIn("章节\n0:00 新介绍\n2:00 新主体", data["description"])
        self.assertNotIn("0:00 旧介绍", data["description"])
        self.assertNotIn("1:00 旧中间", data["description"])
        self.assertTrue(data["description"].endswith("尾注\n"))


class TrendingHelpersTests(unittest.TestCase):
    def test_parse_iso_duration(self):
        self.assertEqual(trending._parse_duration("PT1H2M3S"), 3723)
        self.assertEqual(trending._parse_duration("PT45M"), 2700)
        self.assertEqual(trending._parse_duration(None), 0)

    def test_topic_hits_do_not_match_substrings(self):
        self.assertIn("ai", trending._topic_hits("The AI capex cycle"))
        self.assertNotIn("ai", trending._topic_hits("The chair said nothing"))
        self.assertIn("stock", trending._topic_hits("A stock market interview"))

    def test_similar_titles(self):
        self.assertTrue(
            trending._similar_title(
                "jensen huang on ai",
                "jensen huang on ai",
            )
        )
        self.assertFalse(trending._similar_title("ai markets", "civil war history"))

    def test_merge_duplicates_keeps_source_ids(self):
        a = {"title": "Same Episode", "source_ids": ["a"], "score": 10, "transcript": True}
        b = {"title": "Same Episode", "source_ids": ["b"], "score": 12, "transcript": False}
        merged = trending._merge_duplicates([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(set(merged[0]["source_ids"]), {"a", "b"})


class BilingualChapterTests(unittest.TestCase):
    def test_chapters_follow_mandarin_shot_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en_meta = root / "youtube.json"
            zh_meta = root / "youtube.zh.json"
            en_meta.write_text(json.dumps({
                "chapters": [
                    {"start": "0:00", "title": "Who is who"},
                    {"start": "2:00", "title": "The AI arms race"},
                ]
            }))
            zh_meta.write_text(json.dumps({
                "chapters": [
                    {"start": "0:00", "title": "人物介绍"},
                    {"start": "2:00", "title": "AI军备竞赛"},
                ]
            }))
            en_timing = {"shots": [
                {"id": "01", "start": 0, "heading": None},
                {"id": "02", "start": 120, "heading": "The AI arms race"},
            ]}
            zh_timing = {"shots": [
                {"id": "01", "start": 0},
                {"id": "02", "start": 90},
            ]}
            bilingual._retime_chapters(en_meta, zh_meta, en_timing, zh_timing)
            chapters = json.loads(zh_meta.read_text())["chapters"]
            self.assertEqual([c["start"] for c in chapters], ["0:00", "1:30"])

    def test_english_localization_uses_mandarin_chapter_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en_meta = root / "youtube.json"
            zh_meta = root / "youtube.zh.json"
            en_meta.write_text(json.dumps({
                "title": "English title",
                "description": "English description.\n\nChapters\n0:00 Intro\n2:00 Main",
                "chapters": [
                    {"start": "0:00", "title": "Intro"},
                    {"start": "2:00", "title": "Main"},
                ],
            }))
            zh_meta.write_text(json.dumps({
                "title": "中文标题",
                "description": "中文说明。\n\n章节：\n0:00 介绍\n2:00 主体",
                "chapters": [
                    {"start": "0:00", "title": "介绍"},
                    {"start": "1:30", "title": "主体"},
                ],
            }, ensure_ascii=False))
            en_chapters = json.loads(en_meta.read_text())["chapters"]
            zh_chapters = json.loads(zh_meta.read_text())["chapters"]
            aligned = bilingual._align_chapter_starts(en_chapters, zh_chapters)
            data = bilingual._localizations(en_meta, "en", aligned)
        description = data["en"]["description"]
        self.assertIn("0:00 Intro", description)
        self.assertIn("1:30 Main", description)
        self.assertNotIn("2:00 Main", description)

    def test_mandarin_localization_uses_english_chapter_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            en_meta = root / "youtube.json"
            zh_meta = root / "youtube.zh.json"
            en_meta.write_text(json.dumps({
                "chapters": [
                    {"start": "0:00", "title": "Intro"},
                    {"start": "2:00", "title": "Main"},
                ],
            }))
            zh_meta.write_text(json.dumps({
                "title": "中文标题",
                "description": "中文说明。\n\n章节：\n0:00 介绍\n1:30 主体",
                "chapters": [
                    {"start": "0:00", "title": "介绍"},
                    {"start": "1:30", "title": "主体"},
                ],
            }, ensure_ascii=False))
            en_chapters = json.loads(en_meta.read_text())["chapters"]
            zh_chapters = json.loads(zh_meta.read_text())["chapters"]
            aligned = bilingual._align_chapter_starts(zh_chapters, en_chapters)
            data = bilingual._localizations(zh_meta, "zh-Hans", aligned)
        description = data["zh-Hans"]["description"]
        self.assertIn("章节：\n0:00 介绍\n2:00 主体", description)
        self.assertNotIn("1:30 主体", description)


class UsedEpisodeLedgerTests(unittest.TestCase):
    def test_ledger_round_trip_and_source_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "used.json"
            records = [
                {"source_ids": ["a", "b"], "title": "Combined"},
                {"source_ids": ["c"], "title": "Single"},
            ]
            fetch_popular.save_used(path, records)
            loaded = fetch_popular.load_used(path)
            self.assertEqual(loaded, records)
            self.assertEqual(fetch_popular.used_source_ids(loaded), {"a", "b", "c"})

    def test_missing_ledger_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(fetch_popular.load_used(Path(tmp) / "missing.json"), [])


class UploadProgressTests(unittest.TestCase):
    def test_progress_reporting_uses_media_upload_progress_fields(self):
        class Progress:
            total_size = 10
            resumable_progress = 5

            def progress(self):
                return 0.5

        class Request:
            def next_chunk(self):
                return Progress(), {"id": "video-id"}

        class Videos:
            def insert(self, **kwargs):
                return Request()

        class YouTube:
            def videos(self):
                return Videos()

        class MediaUpload:
            def __init__(self, *args, **kwargs):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "final.mp4"
            video.write_bytes(b"test")
            args = SimpleNamespace(video=str(video), no_notify=True)
            data = {
                "title": "Title",
                "description": "Description",
                "tags": [],
                "categoryId": "28",
                "privacyStatus": "private",
                "containsSyntheticMedia": True,
                "selfDeclaredMadeForKids": False,
            }
            response = youtube_upload._upload(
                YouTube(), args, data, RuntimeError, MediaUpload
            )
        self.assertEqual(response["id"], "video-id")


if __name__ == "__main__":
    unittest.main()
