import { test } from "node:test";
import assert from "node:assert/strict";
import { resolvePython, renderEvent } from "../../bin/skool-extract.js";

test("resolvePython falls back to python3 on non-win when no venv", () => {
  // Use a path with no .venv so it falls back.
  const py = resolvePython("/nonexistent-root", "linux");
  assert.equal(py, process.env.PYTHON || "python3");
});

test("resolvePython uses python on win32 fallback", () => {
  const py = resolvePython("/nonexistent-root", "win32");
  assert.equal(py, process.env.PYTHON || "python");
});

test("renderEvent formats known events", () => {
  assert.match(renderEvent({ event: "course_parsed", title: "T", lessons: 5 }), /Parsed "T" — 5 lessons/);
  assert.match(
    renderEvent({ event: "lesson_start", index: 2, total: 10, title: "Welcome" }),
    /\[2\/10\] Welcome/
  );
  assert.match(
    renderEvent({ event: "lesson_done", index: 1, total: 3, status: "done", transcript: "captions" }),
    /done · transcript: captions/
  );
});

test("renderEvent returns null for unknown events", () => {
  assert.equal(renderEvent({ event: "totally_unknown" }), null);
});
