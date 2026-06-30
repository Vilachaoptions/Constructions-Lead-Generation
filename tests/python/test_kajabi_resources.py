"""Tests for Kajabi lesson resource detection (downloads vs. links)."""

from bs4 import BeautifulSoup

from webcourse.kajabi import _download_url, _find_resources, parse_lesson

_HTML = """
<div class="post-body">
  <a class="product-outline-post" href="/categories/123/posts/456">Sidebar lesson</a>
  <a href="/categories/123/posts/789">Next lesson</a>
  <a href="https://docs.google.com/spreadsheets/d/1tBy_w9JlcQ/edit?usp=sharing">Ad Copy Sheet Access</a>
  <a href="https://drive.google.com/file/d/1ABCdef/view">Download Guide \U0001F448</a>
  <a href="https://kajabi-cdn.com/foo/checklist.pdf">Checklist</a>
  <a href="https://example.com/page">Read more</a>
  <a href="https://example.com/file.zip">Template pack</a>
</div>
"""


def _by_url(resources):
    return {r["url"]: r for r in resources}


def test_find_resources_classifies_files_and_links():
    soup = BeautifulSoup(_HTML, "lxml")
    res = _find_resources(soup, "https://defined.example.com/posts/1")
    by = _by_url(res)

    # Sidebar curriculum + in-course navigation are excluded.
    assert not any("/posts/456" in u for u in by)
    assert not any("/posts/789" in u for u in by)
    # A generic web page is not a resource.
    assert "https://example.com/page" not in by

    # Google Sheet/Doc viewers stay as links (not binary downloads).
    sheet = by["https://docs.google.com/spreadsheets/d/1tBy_w9JlcQ/edit?usp=sharing"]
    assert sheet["is_file"] is False
    assert sheet["title"] == "Ad Copy Sheet Access"

    # A single Drive file, a CDN PDF and a .zip are downloadable files.
    assert by["https://drive.google.com/file/d/1ABCdef/view"]["is_file"] is True
    assert by["https://kajabi-cdn.com/foo/checklist.pdf"]["is_file"] is True
    assert by["https://example.com/file.zip"]["is_file"] is True


def test_download_url_rewrites_drive_file():
    assert (_download_url("https://drive.google.com/file/d/1ABCdef/view")
            == "https://drive.google.com/uc?export=download&id=1ABCdef")
    # Non-Drive URLs pass through unchanged.
    assert (_download_url("https://kajabi-cdn.com/foo/checklist.pdf")
            == "https://kajabi-cdn.com/foo/checklist.pdf")


def test_parse_lesson_returns_resources():
    html = (
        '<h1 class="post-body-title">Ad Copy</h1>'
        '<div class="post-body"><p>Body text here.</p>'
        '<a href="https://docs.google.com/spreadsheets/d/X/edit">Sheet</a></div>'
    )
    title, notes_md, wid, resources = parse_lesson(html, "https://x.example.com/p/1")
    assert title == "Ad Copy"
    assert resources and resources[0]["url"].startswith("https://docs.google.com")
    assert resources[0]["is_file"] is False
