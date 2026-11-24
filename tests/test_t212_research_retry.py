"""Retry/backoff tests for the research extraction step (mocked backend)."""
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "t212_research.py"
sys.path.insert(0, "/opt/hermes")
spec = importlib.util.spec_from_file_location("t212_research", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules["t212_research"] = module
spec.loader.exec_module(module)


def run(coro):
    return asyncio.run(coro)


def test_transient_429_is_retried_then_succeeds():
    calls = []
    sleeps = []

    async def fake_extract(urls, char_limit=None):
        calls.append(list(urls))
        if len(calls) == 1:
            return json.dumps({"results": [
                {"url": urls[0], "content": "", "error": "HTTP 429: rate limited"},
                {"url": urls[1], "content": "ok content"},
            ]})
        return json.dumps({"results": [{"url": u, "content": "recovered"} for u in urls]})

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    original_extract, original_sleep = module.web_extract_tool, module.asyncio.sleep
    module.web_extract_tool = fake_extract
    module.asyncio.sleep = fake_sleep
    try:
        results = run(module.extract(["https://a", "https://b"]))
    finally:
        module.web_extract_tool, module.asyncio.sleep = original_extract, original_sleep

    assert calls == [["https://a", "https://b"], ["https://a"]]  # only failed URL retried
    assert sleeps == [2.0]
    assert results[0]["content"] == "recovered"
    assert results[1]["content"] == "ok content"


def test_permanent_404_is_not_retried():
    calls = []

    async def fake_extract(urls, char_limit=None):
        calls.append(list(urls))
        return json.dumps({"results": [{"url": u, "content": "", "error": "HTTP 404: not found"} for u in urls]})

    original = module.web_extract_tool
    module.web_extract_tool = fake_extract
    try:
        results = run(module.extract(["https://a"]))
    finally:
        module.web_extract_tool = original

    assert len(calls) == 1
    assert "404" in results[0]["error"]


def test_backoff_is_bounded_and_exhausts():
    calls = []
    sleeps = []

    async def fake_extract(urls, char_limit=None):
        calls.append(list(urls))
        return json.dumps({"results": [{"url": u, "content": "", "error": "HTTP 503: unavailable"} for u in urls]})

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    original_extract, original_sleep = module.web_extract_tool, module.asyncio.sleep
    module.web_extract_tool = fake_extract
    module.asyncio.sleep = fake_sleep
    try:
        results = run(module.extract(["https://a"]))
    finally:
        module.web_extract_tool, module.asyncio.sleep = original_extract, original_sleep

    assert len(calls) == 4          # 1 initial + 3 retries
    assert sleeps == [2.0, 4.0, 8.0]
    assert results[0]["content"] == ""
    assert "503" in results[0]["error"]


def test_batch_exception_is_retried_when_transient():
    calls = []

    async def fake_extract(urls, char_limit=None):
        calls.append(list(urls))
        if len(calls) == 1:
            raise RuntimeError("connection reset by peer")
        return json.dumps({"results": [{"url": u, "content": "ok"} for u in urls]})

    async def fake_sleep(seconds):
        pass

    original_extract, original_sleep = module.web_extract_tool, module.asyncio.sleep
    module.web_extract_tool = fake_extract
    module.asyncio.sleep = fake_sleep
    try:
        results = run(module.extract(["https://a"]))
    finally:
        module.web_extract_tool, module.asyncio.sleep = original_extract, original_sleep

    assert len(calls) == 2
    assert results[0]["content"] == "ok"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
