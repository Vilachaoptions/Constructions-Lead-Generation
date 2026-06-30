from pathlib import Path

from skool_extractor.parse import next_data as nd

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _html():
    return (FIXTURES / "sample_next_data.html").read_text()


def test_extract_next_data():
    data = nd.extract_next_data(_html())
    assert "props" in data and "pageProps" in data["props"]


def test_extract_course_wrapper():
    data = nd.extract_next_data(_html())
    wrapper = nd.extract_course_wrapper(data)
    assert wrapper["course"]["id"] == "course-1"
    assert wrapper["course"]["unitType"] == "course"
    assert len(wrapper["children"]) == 2


def test_extract_course_wrapper_fallback_by_unittype():
    # Even if not at the canonical path, a course-unitType wrapper is found.
    data = {"props": {"pageProps": {"other": {
        "course": {"id": "c9", "unitType": "course", "metadata": {"title": "X"}},
        "children": [],
    }}}}
    wrapper = nd.extract_course_wrapper(data)
    assert wrapper["course"]["id"] == "c9"
