from pathlib import Path

from skool_extractor.parse import next_data as nd
from skool_extractor.parse.tree_builder import build_course, slugify

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _course():
    data = nd.extract_next_data((FIXTURES / "sample_next_data.html").read_text())
    root = nd.find_course_root(data, "course-1")
    return build_course(root, "my-community", "course-1", "https://skool.com/x")


def test_build_course_structure():
    course = _course()
    assert course.title == "Intro Course"
    assert course.community == "my-community"
    assert len(course.modules) == 2
    assert [m.title for m in course.modules] == ["Getting Started", "Advanced"]


def test_lesson_ordering_and_paths():
    course = _course()
    lessons = list(course.iter_lessons())
    assert [l.id for l in lessons] == ["lesson-1", "lesson-2", "lesson-3"]
    assert lessons[0].module_path == ["Getting Started"]
    assert lessons[2].module_path == ["Advanced"]


def test_lesson_count():
    assert _course().lesson_count() == 3


def test_slugify():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("") == "untitled"
