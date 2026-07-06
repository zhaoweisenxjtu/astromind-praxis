"""AnySearch 结果解析测试（不依赖网络）"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.search.strategies.anysearch_api import AnySearchStrategy


def _make_strategy():
    return AnySearchStrategy(api_key="")


def test_parse_json_list():
    s = _make_strategy()
    items = [{"title": "R1", "url": "http://r1", "content": "c1"},
             {"title": "R2", "url": "http://r2", "content": "c2"}]
    parsed = s._parse_results(json.dumps(items))
    assert len(parsed) == 2
    assert parsed[0]["title"] == "R1"
    assert parsed[0]["source"] == "anysearch"


def test_parse_json_single():
    s = _make_strategy()
    item = {"title": "Result", "url": "http://r"}
    parsed = s._parse_results(json.dumps(item))
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Result"


def test_parse_json_with_results_key():
    s = _make_strategy()
    data = {"results": [{"title": "A", "url": "http://a"}, {"title": "B", "url": "http://b"}]}
    parsed = s._parse_results(json.dumps(data))
    assert len(parsed) == 2


def test_parse_empty():
    s = _make_strategy()
    assert s._parse_results("") == []
    assert s._parse_results("   ") == []


def test_parse_markdown_headers():
    s = _make_strategy()
    text = """### Result One
https://example.com/1
Description of result one

### Result Two
https://example.com/2
Description of result two
"""
    parsed = s._parse_results(text)
    assert len(parsed) == 2
    assert parsed[0]["title"] == "Result One"
    assert parsed[0]["url"] == "https://example.com/1"
    assert "Description of result one" in parsed[0]["content"]


def test_parse_markdown_bold():
    s = _make_strategy()
    text = """**Bold Title** - Some description
https://example.com/bold
More details here

**Another Title**
https://example.com/another
"""
    parsed = s._parse_results(text)
    assert len(parsed) >= 2
    assert any(r["title"] == "Bold Title" for r in parsed)


def test_parse_url_extraction():
    s = _make_strategy()
    text = """Some text with a link: https://example.com/page
and more content here
"""
    parsed = s._parse_results(text)
    assert len(parsed) >= 1
    assert parsed[0]["url"] == "https://example.com/page"


def test_normalize_item():
    s = _make_strategy()
    r = s._normalize_item({"title": "T", "url": "U", "content": "C"})
    assert r["title"] == "T" and r["url"] == "U" and r["content"] == "C"

    r = s._normalize_item({"name": "N", "link": "L", "snippet": "S"})
    assert r["title"] == "N" and r["url"] == "L" and r["content"] == "S"


def test_parse_markdown_numbered():
    s = _make_strategy()
    text = """1. **First Result** - Description of first
   https://example.com/1
2. Second Result - Description of second
   https://example.com/2
"""
    parsed = s._parse_results(text)
    assert len(parsed) >= 2


if __name__ == "__main__":
    failures = []
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        try:
            fn()
            print(f"  PASS {name}")
        except Exception as e:
            failures.append((name, e))
            print(f"  FAIL {name}: {e}")
    if failures:
        print(f"\n{len(failures)} test(s) FAILED")
        sys.exit(1)
    print("All AnySearch parse tests passed")
