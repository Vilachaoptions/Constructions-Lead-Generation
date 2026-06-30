from pathlib import Path

from skool_extractor.models import (Course, Lesson, Module, Transcript,
                                    TranscriptSegment, VideoRef)
from skool_extractor.output import markdown_writer
from skool_extractor.output.state import StateStore, notes_hash


def _course_with_lesson():
    lesson = Lesson(
        id="lesson-1", title="Welcome", order=0, module_path=["Getting Started"],
        notes_markdown="Hello **world**",
        video=VideoRef(provider="youtube", url="https://youtu.be/x", provider_id="x"),
        transcript=Transcript(source="captions", text="hi there", model="youtube",
                              segments=[TranscriptSegment(0.0, 1.0, "hi there")]),
    )
    module = Module(id="mod-1", title="Getting Started", lessons=[lesson])
    course = Course(id="c", community="comm", title="Course", slug="course",
                    modules=[module])
    return course, lesson


def test_write_lesson_creates_markdown(tmp_path: Path):
    course, lesson = _course_with_lesson()
    path = markdown_writer.write_lesson(tmp_path, course, lesson)
    assert path.exists()
    text = path.read_text()
    assert "# Welcome" in text
    assert "## Notes" in text
    assert "Hello **world**" in text
    assert "## Transcript" in text
    assert "hi there" in text
    # filename + module dir layout
    assert path.name == "01-welcome.md"
    assert "01-getting-started" in str(path)
    assert lesson.markdown_path is not None


def test_timestamps_rendering(tmp_path: Path):
    course, lesson = _course_with_lesson()
    path = markdown_writer.write_lesson(tmp_path, course, lesson, timestamps=True)
    assert "**[00:00]** hi there" in path.read_text()


def test_write_master_combines_lessons(tmp_path: Path):
    course, lesson = _course_with_lesson()
    markdown_writer.write_lesson(tmp_path, course, lesson)
    master = markdown_writer.write_master(tmp_path, course)
    assert master.exists()
    text = master.read_text()
    assert master.name.endswith("-MASTER.md")
    assert "# Course — Full Course" in text
    assert "## Contents" in text
    assert "Welcome" in text          # appears in TOC + body
    assert "hi there" in text         # the lesson transcript is included
    assert "---" in text              # separator between lessons


def test_state_skip_roundtrip(tmp_path: Path):
    from skool_extractor.models import STATUS_DONE
    course, lesson = _course_with_lesson()
    markdown_writer.write_lesson(tmp_path, course, lesson)
    lesson.status = STATUS_DONE
    lesson.notes_hash = notes_hash(lesson.notes_markdown)

    store = StateStore(tmp_path, course)
    assert store.should_skip(lesson, force=False) is False  # not marked yet
    store.mark(lesson)

    store2 = StateStore(tmp_path, course)
    assert store2.should_skip(lesson, force=False) is True
    assert store2.should_skip(lesson, force=True) is False
