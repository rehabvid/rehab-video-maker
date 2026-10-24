"""Unit tests for the technical slideshow planner and scene factory."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "tech-commentary-slideshow" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


planner = _load("plan_visuals")
scenes = _load("make_scenes")

POLICY = {
    "animate_after_seconds": 7,
    "max_custom_visuals": 12,
    "min_visual_duration": 7,
    "max_points": 3,
    "petrinet_keywords": ["concurrent", "transition", "token", "queue"],
    "dag_keywords": ["pipeline", "workflow", "agent", "loop", "depends"],
    "diagram_keywords": ["framework", "stack", "versus"],
    "svg_keywords": ["timeline", "before and after", "funnel"],
}


def _slide(*, sid="01", kind="chart", narration="A plain claim.", **extra):
    shot = {"id": sid, "kind": kind, "narration": narration}
    shot.update(extra)
    return shot


class PlannerTests(unittest.TestCase):
    def test_explicit_chart_uses_real_data(self):
        slides = {
            "slug": "test",
            "title": "Test",
            "fps": 30,
            "shots": [
                _slide(
                    narration="Revenue is up.",
                    visual={
                        "type": "chart",
                        "chart_type": "bar",
                        "data": {
                            "categories": ["2024", "2025"],
                            "series": [{"name": "Revenue", "data": [12, 19]}],
                        },
                    },
                )
            ],
        }
        result = planner.plan(slides, {"shots": []}, POLICY)
        self.assertEqual(result["shots"][0]["visual"]["type"], "chart")
        self.assertTrue(result["shots"][0]["visual"]["spec"]["data"]["series"])

    def test_chart_without_data_falls_back_to_text(self):
        slides = {"slug": "t", "title": "T", "fps": 30, "shots": [_slide(kind="chart")]}
        result = planner.plan(slides, {"shots": []}, POLICY)
        self.assertEqual(result["shots"][0]["visual"]["type"], "none")

    def test_petrinet_and_dag_detection(self):
        slides = {
            "slug": "t",
            "title": "T",
            "fps": 30,
            "shots": [
                _slide(sid="01", narration="The queue has a transition for every token."),
                _slide(sid="02", narration="The agent pipeline depends on a verification loop."),
            ],
        }
        result = planner.plan(slides, {"shots": []}, POLICY)
        self.assertEqual(result["shots"][0]["visual"]["type"], "petrinet")
        self.assertEqual(result["shots"][1]["visual"]["type"], "dag")

    def test_max_custom_visuals_cap(self):
        policy = dict(POLICY, max_custom_visuals=1)
        slides = {
            "slug": "t",
            "title": "T",
            "fps": 30,
            "shots": [
                _slide(sid="01", narration="A workflow with a depends edge."),
                _slide(sid="02", narration="Another workflow with an agent loop."),
            ],
        }
        result = planner.plan(slides, {"shots": []}, policy)
        custom = [s for s in result["shots"] if s["visual"]["type"] != "none"]
        self.assertEqual(len(custom), 1)


class SceneFactoryTests(unittest.TestCase):
    def test_chart_option(self):
        option = scenes._chart_option({
            "chart_type": "line",
            "data": {
                "categories": ["Q1", "Q2"],
                "series": [{"name": "ARR", "data": [3, 7]}],
            },
        })
        self.assertIsNotNone(option)
        self.assertEqual(option["series"][0]["type"], "line")
        self.assertEqual(option["series"][0]["data"], [3, 7])

    def test_petrinet_alternates_places_and_transitions(self):
        nodes, edges = scenes._nodes_edges(
            {"points": ["ready", "process", "done"]}, "petrinet"
        )
        self.assertTrue(any(node["label"].startswith("●") for node in nodes))
        self.assertTrue(any(node["label"].startswith("▢") for node in nodes))
        self.assertEqual(len(edges), 4)

    def test_make_scene_writes_yaml_and_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / "linkzag"
            (module / "content").mkdir(parents=True)
            (module / "package.json").write_text('{"name":"test"}\n')
            plan = {
                "slug": "unit-test",
                "title": "Unit test",
                "shots": [{
                    "id": "01",
                    "duration": 8,
                    "narration": "Revenue is up.",
                    "visual": {
                        "type": "chart",
                        "animated": False,
                        "spec": {
                            "title": "Revenue",
                            "points": ["Revenue is up"],
                            "data": {
                                "categories": ["2024", "2025"],
                                "series": [{"name": "Revenue", "data": [12, 19]}],
                            },
                        },
                    },
                }],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan))
            manifest_path = Path(tmp) / "scenes.json"
            code = scenes.main([
                "--plan", str(plan_path),
                "--module", str(module),
                "--out", str(manifest_path),
            ])
            self.assertEqual(code, 0)
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(len(manifest["scenes"]), 1)
            scene_path = module / manifest["scenes"][0]["scene"]
            scene = yaml.safe_load(scene_path.read_text())
            self.assertEqual(scene["width"], 1920)
            self.assertTrue(any(item["type"] == "echarts" for item in scene["items"]))
            asset = module / "content" / "assets" / "generated" / "unit-test" / "01-chart.json"
            self.assertTrue(asset.exists())


if __name__ == "__main__":
    unittest.main()
