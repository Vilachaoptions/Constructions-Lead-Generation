from pathlib import Path

from skool_extractor.parse import next_data as nd
from skool_extractor.parse import notes as notes_mod
from skool_extractor.parse.tree_builder import build_course
from skool_extractor.video.resolver import detect_provider, resolve_video

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _lessons():
    data = nd.extract_next_data((FIXTURES / "sample_next_data.html").read_text())
    wrapper = nd.extract_course_wrapper(data)
    course = build_course(wrapper, "c", "course-1")
    return {l.id: l for l in course.iter_lessons()}


def test_notes_html_to_markdown():
    _, md = notes_mod.extract_notes(_lessons()["lesson-1"].raw)
    assert "**world**" in md
    assert "[link](https://x.test)" in md


def test_notes_plain_text():
    html, md = notes_mod.extract_notes(_lessons()["lesson-2"].raw)
    assert html is None
    assert md == "Plain text notes here."


def test_notes_includes_resources():
    _, md = notes_mod.extract_notes(_lessons()["lesson-3"].raw)
    assert "**Resources**" in md
    assert "[Template](https://ex.com/t)" in md


def test_skool_v2_richtext_desc():
    # Real Skool format: "[v2]" prefix + ProseMirror nodes with link marks.
    node = {"metadata": {"title": "/hook-generator", "resources": "[]", "desc":
        '[v2][{"type":"paragraph","content":[{"type":"text","text":"(VIDEO COMING SOON)"}]},'
        '{"type":"paragraph","content":[{"type":"text","marks":[{"type":"link","attrs":'
        '{"href":"https://drive.google.com/file/d/ABC/view"}}],"text":"Get the files"}]}]'}}
    _, md = notes_mod.extract_notes(node)
    assert "(VIDEO COMING SOON)" in md
    assert "[Get the files](https://drive.google.com/file/d/ABC/view)" in md
    assert "[v2]" not in md          # the version prefix must be stripped
    assert "{" not in md             # no raw JSON leaks through


def test_detect_provider():
    assert detect_provider("https://youtu.be/abc") == "youtube"
    assert detect_provider("https://vimeo.com/1") == "vimeo"
    assert detect_provider("https://stream.mux.com/x.m3u8") == "mux"
    assert detect_provider("https://www.loom.com/share/x") == "loom"
    assert detect_provider("https://example.com/v") == "unknown"


def test_resolve_youtube_video_id():
    video = resolve_video(_lessons()["lesson-1"].raw)
    assert video.provider == "youtube"
    assert video.provider_id == "abcdefghijk"


def test_resolve_video_from_json_list():
    video = resolve_video(_lessons()["lesson-2"].raw)
    assert video.provider == "vimeo"
    assert video.url == "https://vimeo.com/123456789"


def test_resolve_loom_video():
    video = resolve_video(_lessons()["lesson-3"].raw)
    assert video.provider == "loom"
