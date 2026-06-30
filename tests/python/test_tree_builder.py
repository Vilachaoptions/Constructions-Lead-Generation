from pathlib import Path

from skool_extractor.parse import next_data as nd
from skool_extractor.parse.tree_builder import build_course, slugify

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _course():
    data = nd.extract_next_data((FIXTURES / "sample_next_data.html").read_text())
    wrapper = nd.extract_course_wrapper(data)
    return build_course(wrapper, "my-community", "course-1", "https://skool.com/x/classroom/c1")


def test_build_course_structure():
    course = _course()
    assert course.title == "Intro Course"
    assert course.community == "my-community"
    # implicit top-level section (for "Welcome") + the "Advanced" set
    section_titles = [m.title for m in course.modules]
    assert "Advanced" in section_titles


def test_all_lessons_discovered():
    course = _course()
    ids = [l.id for l in course.iter_lessons()]
    assert set(ids) == {"lesson-1", "lesson-2", "lesson-3"}
    assert course.lesson_count() == 3


def test_lesson_module_paths():
    course = _course()
    by_id = {l.id: l for l in course.iter_lessons()}
    # top-level lesson is written at the course root (empty module_path)
    assert by_id["lesson-1"].module_path == []
    # lessons inside the "Advanced" set carry that section in their path
    assert by_id["lesson-2"].module_path == ["Advanced"]
    assert by_id["lesson-3"].module_path == ["Advanced"]


def test_lesson_deep_link_url():
    course = _course()
    by_id = {l.id: l for l in course.iter_lessons()}
    assert "md=lesson-2" in by_id["lesson-2"].url


def test_slugify():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("Viral Content OS ⚙️") == "viral-content-os"
    assert slugify("") == "untitled"
