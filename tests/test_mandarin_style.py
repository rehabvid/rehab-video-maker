import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "podcast-youtuber-agent" / "scripts"))
import mandarin_style  # noqa: E402


GOOD = (
    "钱从哪来？这个问题，市场问了一年。说白了，不是AI不行，是流动性先扛不住。"
    "你看，CoreWeave的无担保债，成交在百分之十五。想卖，卖不掉。谁来兜底？"
    "问题是，政策能护住建设，护不住利润。刻舟求剑，等不到旧周期回来。"
    "越拖越贵。说到底，大家赌的是同一件事：政府不会让它倒。"
) * 3


class MandarinStyleTest(unittest.TestCase):
    def test_clean_copy_has_no_hard_issues(self):
        report = mandarin_style.analyze_text(GOOD)
        self.assertEqual(report["hard"], [])
        self.assertIn(report["grade"], {"A", "B"})
        self.assertGreaterEqual(report["idiom_count"], 2)
        self.assertGreaterEqual(report["questions"], 2)

    def test_taiwan_forms_are_hard(self):
        report = mandarin_style.analyze_text(GOOD + "这段影片讲了晶片和资料中心。")
        self.assertIn("taiwan-forms", report["hard"])
        self.assertIn("影片", report["taiwan_hits"])

    def test_single_char_quote_is_hard(self):
        report = mandarin_style.analyze_text(GOOD + "这件事值得“查”。")
        self.assertIn("single-char-quotes", report["hard"])

    def test_coverage_calque_is_hard(self):
        report = mandarin_style.analyze_text(GOOD + "Casado 在a16z做合伙人，看基础设施。")
        self.assertIn("coverage-calque", report["hard"])
        self.assertTrue(report["coverage_hits"])

    def test_clear_coverage_phrase_is_not_hard(self):
        report = mandarin_style.analyze_text(
            GOOD + "Casado 是a16z的合伙人，负责基础设施领域的投资。"
        )
        self.assertNotIn("coverage-calque", report["hard"])

    def test_very_long_sentence_is_hard(self):
        long_sentence = "这是一个非常长的句子" + "，而且还在继续补充细节" * 5 + "。"
        report = mandarin_style.analyze_text(GOOD + long_sentence)
        self.assertIn("very-long-sentences", report["hard"])

    def test_written_style_gets_warnings(self):
        written = ("首先，我们对于这个问题进行了讨论。其次，通过分析可以发现，"
                   "该现象在很大程度上是由于流动性造成的。最后，综上所述，"
                   "我们认为这是一个值得注意的问题。") * 6
        report = mandarin_style.analyze_text(written, min_chars=300)
        codes = {i["code"] for i in report["issues"]}
        self.assertIn("formal-calques", codes)
        self.assertLess(report["score"], 85)

    def test_feedback_names_the_problem(self):
        report = mandarin_style.analyze_text(GOOD + "这段影片很好。")
        note = mandarin_style.feedback(report)
        self.assertIn("台湾", note)
        self.assertIn("影片", note)


if __name__ == "__main__":
    unittest.main()
