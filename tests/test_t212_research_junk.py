"""Regression tests for t212_research quality gates."""
import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "t212_research.py"
spec = importlib.util.spec_from_file_location("t212_research_under_test", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ResearchQualityTests(unittest.TestCase):
    def test_junk_and_short_pages_are_rejected(self):
        self.assertTrue(module._looks_like_junk("Connecting: 1.2.3.4\nForwarded: x"))
        self.assertTrue(module._looks_like_junk("Relevance Inspector IgnoreOpen"))
        self.assertTrue(module._looks_like_junk("Javascript is required"))
        self.assertFalse(module._looks_like_junk("Fund objective: track the index"))
        self.assertTrue(module._usable_content("real readable research " * 40))
        self.assertFalse(module._usable_content("too short"))

    def test_query_title_is_rejected(self):
        item = {"query": "ETF outlook 2026", "title": " ETF outlook 2026 ", "description": ""}
        self.assertFalse(module._usable_search_result(item))

    def test_dedupe_removes_duplicate_urls_and_normalized_duplicates(self):
        items = [
            {"url": "https://a", "title": "T1", "description": "D1"},
            {"url": "https://a", "title": "different", "description": "different"},
            {"url": "https://b", "title": "T2", "description": "D2"},
            {"url": "https://c", "title": " t2 ", "description": "  d2  "},
        ]
        out = module._dedupe_results(items)
        self.assertEqual([x["url"] for x in out], ["https://a", "https://b"])

    def test_junk_extraction_is_not_retried(self):
        async def fake_extract(urls, char_limit=None):
            return json.dumps({"results": [
                {"url": urls[0], "content": "Connecting: 1.2.3.4", "error": ""},
                {"url": urls[1], "content": "real fund factsheet " * 50, "error": ""},
            ]})

        with patch.object(module, "web_extract_tool", new=AsyncMock(side_effect=fake_extract)) as mocked:
            result = asyncio.run(module.extract(["https://a", "https://b"]))
        self.assertEqual(mocked.await_count, 1)
        self.assertEqual(result[0]["content"], "")
        self.assertIn("junk or interstitial", result[0]["error"])
        self.assertGreater(len(result[1]["content"]), 200)

    def test_transient_429_retries_only_failed_url(self):
        calls = []

        async def fake_extract(urls, char_limit=None):
            calls.append(list(urls))
            if len(calls) == 1:
                return json.dumps({"results": [
                    {"url": urls[0], "content": "", "error": "HTTP 429 rate limited"},
                    {"url": urls[1], "content": "real content", "error": ""},
                ]})
            return json.dumps({"results": [{"url": urls[0], "content": "recovered content", "error": ""}]})

        async def no_wait(_seconds):
            return None

        with patch.object(module, "web_extract_tool", new=AsyncMock(side_effect=fake_extract)), \
             patch.object(module.asyncio, "sleep", new=no_wait):
            result = asyncio.run(module.extract(["https://a", "https://b"]))
        self.assertEqual(calls, [["https://a", "https://b"], ["https://a"]])
        self.assertEqual(result[0]["content"], "recovered content")
        self.assertEqual(result[1]["content"], "real content")


if __name__ == "__main__":
    unittest.main(verbosity=2)
