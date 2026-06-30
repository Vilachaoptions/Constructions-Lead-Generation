#!/usr/bin/env node
/**
 * Thin Node.js CLI wrapper around the Python Skool extractor core.
 *
 * It contains NO scraping logic: it resolves a Python interpreter (preferring a
 * local ./.venv), spawns `python -m skool_extractor` with the SAME args, renders
 * the newline-delimited JSON progress events the core emits on stdout, passes
 * stderr through, and exits with the child's exit code.
 *
 * Zero runtime dependencies — uses only Node built-ins.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createInterface } from "node:readline";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, "..");

/** Pick the Python interpreter: prefer the project venv, else PATH. */
export function resolvePython(root = projectRoot, platform = process.platform) {
  const candidates =
    platform === "win32"
      ? [join(root, ".venv", "Scripts", "python.exe")]
      : [join(root, ".venv", "bin", "python"), join(root, ".venv", "bin", "python3")];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return process.env.PYTHON || (platform === "win32" ? "python" : "python3");
}

/** Map a parsed JSON progress event to a human-readable line (or null to skip). */
export function renderEvent(evt) {
  switch (evt.event) {
    case "fetch_classroom":
      return `→ Fetching classroom…`;
    case "course_parsed":
      return `✓ Parsed "${evt.title}" — ${evt.lessons} lessons`;
    case "lesson_start":
      return `[${evt.index}/${evt.total}] ${evt.title}`;
    case "lesson_skip":
      return `    ↳ skipped (already extracted)`;
    case "lesson_done":
      return `    ↳ ${evt.status}` + (evt.transcript ? ` · transcript: ${evt.transcript}` : "");
    case "lesson_error":
      return `    ✗ error: ${evt.error}`;
    case "run_complete":
      return `\n✓ Complete — ${evt.done} extracted, ${evt.skipped} skipped, ${evt.errors} errors`;
    default:
      return null;
  }
}

function runChild(python, args) {
  const child = spawn(python, ["-m", "skool_extractor", ...args], {
    cwd: projectRoot,
    env: { ...process.env, PYTHONPATH: join(projectRoot, "python") },
    stdio: ["inherit", "pipe", "inherit"],
  });

  const rl = createInterface({ input: child.stdout });
  rl.on("line", (line) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
      try {
        const out = renderEvent(JSON.parse(trimmed));
        if (out !== null) process.stdout.write(out + "\n");
        return;
      } catch {
        /* not a progress event — fall through to passthrough */
      }
    }
    process.stdout.write(line + "\n");
  });

  child.on("error", (err) => {
    process.stderr.write(`Failed to start Python core: ${err.message}\n`);
    process.exit(1);
  });
  child.on("close", (code) => process.exit(code === null ? 1 : code));
}

function isMainModule() {
  return process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));
}

if (isMainModule()) {
  const args = process.argv.slice(2);
  runChild(resolvePython(), args);
}
