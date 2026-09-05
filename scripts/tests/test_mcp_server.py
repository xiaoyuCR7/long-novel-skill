"""MCP argument adapters keep public tool calls aligned with positional CLIs."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.server import _entity_index_args, _rag_retriever_args, _story_graph_args


class TestMcpPositionalQueries(unittest.TestCase):
    def test_quality_trend_uses_book_positional_and_score_keeps_chapter(self):
        from mcp_server.server import _quality_score_args, QualityScoreInput
        self.assertEqual(QualityScoreInput(action="trend", book_dir="BOOK").book_dir, "BOOK")
        with self.assertRaises(ValueError):
            _quality_score_args("score", "BOOK", None, None)
        self.assertEqual(_quality_score_args("trend", "BOOK", "IGNORED", 4), ["trend", "BOOK"])
        self.assertEqual(_quality_score_args("score", "BOOK", "CHAPTER", 4),
                         ["score", "CHAPTER", "--chapter", "4", "--book-dir", "BOOK"])

    def test_chapter_impact_does_not_require_node(self):
        self.assertEqual(_story_graph_args("impact", "BOOK", chapter=4), ["impact", "BOOK", "--chapter", "4"])

    def test_query_arguments_are_positional(self):
        self.assertEqual(_entity_index_args("semantic", "BOOK", "QUERY"), ["semantic", "BOOK", "QUERY"])
        self.assertEqual(_story_graph_args("query", "BOOK", "NODE"), ["query", "BOOK", "NODE"])
        self.assertEqual(_rag_retriever_args("query", "BOOK", "QUERY", 3), ["query", "BOOK", "QUERY", "--top", "3"])

    def test_story_graph_all_public_actions_match_cli_contract(self):
        self.assertEqual(_story_graph_args("build", "BOOK", from_scratch=True),
                         ["build", "BOOK", "--from-scratch"])
        self.assertEqual(_story_graph_args("query", "BOOK", "NODE", depth=2),
                         ["query", "BOOK", "NODE", "--depth", "2"])
        self.assertEqual(_story_graph_args("impact", "BOOK", "NODE"),
                         ["impact", "BOOK", "NODE"])
        self.assertEqual(_story_graph_args("cascade", "BOOK", from_chapter=50,
                                           description="改主线"),
                         ["cascade", "BOOK", "--from-chapter", "50", "--desc", "改主线"])
        self.assertEqual(_story_graph_args("update", "BOOK", chapter=37),
                         ["update", "BOOK", "--chapter", "37"])
        self.assertEqual(_story_graph_args("export", "BOOK", output="graph.md"),
                         ["export", "BOOK", "--output", "graph.md"])
        self.assertEqual(_story_graph_args("status", "BOOK"), ["status", "BOOK"])

    def test_story_graph_required_action_fields_fail_before_subprocess(self):
        with self.assertRaisesRegex(ValueError, "requires node"):
            _story_graph_args("query", "BOOK")
        with self.assertRaisesRegex(ValueError, "requires from_chapter"):
            _story_graph_args("cascade", "BOOK")
        with self.assertRaisesRegex(ValueError, "requires chapter"):
            _story_graph_args("update", "BOOK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
