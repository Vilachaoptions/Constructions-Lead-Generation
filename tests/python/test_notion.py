"""Tests for the public-Notion extractor's id parsing, rendering, and DB export."""

import csv
import json

from webcourse.notion import (Ctx, dash_id, page_id_from_url, render_block,
                              render_rich)


def _ctx(tmp_path):
    # client is unused by the code paths under test (no network).
    return Ctx(client=None, base="https://x.notion.site",
               out_dir=tmp_path, log=__import__("logging").getLogger("t"),
               max_pages=100)


def test_dash_id_normalizes_hex_and_uuid():
    assert dash_id("7286d642932f45ce96fcc973bec468c4") == \
        "7286d642-932f-45ce-96fc-c973bec468c4"
    assert dash_id("7286D642-932F-45CE-96FC-C973BEC468C4") == \
        "7286d642-932f-45ce-96fc-c973bec468c4"


def test_page_id_from_url():
    url = ("https://gifted-icebreaker-59a.notion.site/"
           "The-Best-Stories-Ideas-7286d642932f45ce96fcc973bec468c4")
    assert page_id_from_url(url) == "7286d642-932f-45ce-96fc-c973bec468c4"


def test_render_rich_marks_and_links(tmp_path):
    ctx = _ctx(tmp_path)
    segs = [["Hello ", [["b"]]], ["world", [["a", "https://e.com"]]], [" plain"]]
    assert render_rich(segs, ctx) == "**Hello **[world](https://e.com) plain"
    # relative links resolve against the site base
    assert render_rich([["x", [["a", "/foo"]]]], ctx) == \
        "[x](https://x.notion.site/foo)"


def test_render_rich_page_mention_enqueues(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.titles["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"] = "Child"
    out = render_rich([["", [["p", "aaaaaaaabbbbccccddddeeeeeeeeeeee"]]]], ctx)
    assert "Child" in out
    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in ctx.queue


def test_render_block_headings_and_lists(tmp_path):
    ctx = _ctx(tmp_path)
    record = {"block": {
        "h": {"value": {"type": "sub_header", "properties": {"title": [["Section"]]}}},
        "b1": {"value": {"type": "bulleted_list", "properties": {"title": [["one"]]}}},
    }}
    assert render_block("h", record, ctx) == ["## Section"]
    assert render_block("b1", record, ctx) == ["- one"]


def test_export_database_writes_csv_and_json(tmp_path):
    ctx = _ctx(tmp_path)
    schema = {
        "title": {"name": "Story", "type": "title"},
        "cat": {"name": "Category", "type": "select"},
    }
    record = {"block": {
        "row1": {"value": {"type": "page", "properties": {
            "title": [["Founder origin"]], "cat": [["Authority"]]}}},
        "row2": {"value": {"type": "page", "properties": {
            "title": [["Failure lesson"]], "cat": [["Relatability"]]}}},
    }}
    ctx._current_record = record
    view_val = {"format": {"table_properties": [
        {"property": "title", "visible": True},
        {"property": "cat", "visible": True}]}}
    rows = ctx.export_database("Story Ideas", "coll1", schema,
                              ["row1", "row2"], view_val)
    assert len(rows) == 2
    assert rows[0]["Category"] == "Authority"

    csv_path = tmp_path / "databases" / "story-ideas.csv"
    json_path = tmp_path / "databases" / "story-ideas.json"
    assert csv_path.exists() and json_path.exists()
    with csv_path.open() as fh:
        read = list(csv.reader(fh))
    assert read[0] == ["__title__", "Story", "Category", "notion_page_id", "page_file"]
    assert read[1][0] == "Founder origin"
    data = json.loads(json_path.read_text())
    assert data[1]["__title__"] == "Failure lesson"
    assert data[1]["page_file"].startswith("pages/")
