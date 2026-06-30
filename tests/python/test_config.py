import argparse

import pytest

from skool_extractor.config import (ConfigError, build_settings,
                                    parse_classroom_url)


def test_parse_classroom_url():
    community, course = parse_classroom_url(
        "https://www.skool.com/my-community/classroom/abc123?md=lesson-9")
    assert community == "my-community"
    assert course == "abc123"


def test_parse_classroom_url_invalid():
    with pytest.raises(ConfigError):
        parse_classroom_url("https://example.com/not-skool")


def _args(**overrides):
    base = dict(
        classroom_url="https://www.skool.com/comm/classroom/c1",
        output_dir="./out", session_dir="./sess",
        transcription_backend="faster-whisper", whisper_model="base",
        no_captions=False, no_transcripts=False, timestamps=False, force=False,
        only=None, module=None, headful=False, keep_audio=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_build_settings_defaults():
    s = build_settings(_args(), env={})
    assert s.community == "comm"
    assert s.course_id == "c1"
    assert s.use_captions is True
    assert s.transcripts_enabled is True


def test_openai_backend_requires_key():
    with pytest.raises(ConfigError):
        build_settings(_args(transcription_backend="openai"), env={})
    s = build_settings(_args(transcription_backend="openai"),
                       env={"OPENAI_API_KEY": "sk-test"})
    assert s.openai_api_key == "sk-test"


def test_settings_summary_has_no_secrets():
    s = build_settings(_args(), env={"SKOOL_PASSWORD": "hunter2"})
    assert "hunter2" not in str(s.summary())
