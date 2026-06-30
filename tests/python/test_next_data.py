from pathlib import Path

from skool_extractor.parse import next_data as nd

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _html():
    return (FIXTURES / "sample_next_data.html").read_text()


def test_extract_next_data():
    data = nd.extract_next_data(_html())
    assert data["props"]["pageProps"]["course"]["id"] == "course-1"


def test_find_course_root_by_id():
    data = nd.extract_next_data(_html())
    root = nd.find_course_root(data, "course-1")
    assert root["id"] == "course-1"
    assert len(root["children"]) == 2


def test_find_course_root_without_id_picks_largest():
    data = nd.extract_next_data(_html())
    root = nd.find_course_root(data, None)
    assert root["id"] == "course-1"


def test_walk_finds_all_course_nodes():
    data = nd.extract_next_data(_html())
    nodes = list(nd.walk(data, nd._looks_like_course_node))
    ids = {n["id"] for n in nodes}
    assert {"course-1", "mod-1", "mod-2", "lesson-1", "lesson-2", "lesson-3"} <= ids
