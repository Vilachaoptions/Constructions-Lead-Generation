"""Generic course-page discovery.

Opens a visible browser, lets you log in by hand (works on any platform), saves
the session, then dumps the current page's HTML and a paste-friendly summary:
platform signatures, video embeds (iframes / <video> / Wistia / Vimeo / Mux),
candidate lesson links, and embedded JSON blobs. We use this to learn a new
platform's shape before writing a real parser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_PLATFORM_SIGNATURES = (
    "kajabi", "teachable", "thinkific", "podia", "wistia", "vimeo",
    "youtube", "youtu.be", "mux.com", "loom.com", "vooplayer", "spotlightr",
    "circle.so", "memberkit", "hotmart",
)

_LESSON_LINK_RE = re.compile(
    r"/(products|courses|lessons|categories|posts|library|modules|content)/",
    re.IGNORECASE,
)

# Common globals course platforms hydrate state into.
_JSON_GLOBALS = ("__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__",
                 "window.__INITIAL_STATE__", "__APOLLO_STATE__", "Kajabi")


def run_discover(args) -> int:
    from playwright.sync_api import sync_playwright

    url = args.url
    session_dir = Path(args.session_dir).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser().resolve()
    host = urlparse(url).netloc.replace("www.", "") or "site"
    dump_dir = out_dir / f"_discovery__{host}"
    dump_dir.mkdir(parents=True, exist_ok=True)
    state_path = session_dir / "storage_state.json"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx_kwargs = {"user_agent": _USER_AGENT}
        if state_path.exists():
            print(f"Reusing saved session at {state_path}")
            ctx_kwargs["storage_state"] = str(state_path)
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        print(f"\nOpening {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:  # noqa: BLE001
            print(f"(navigation warning: {exc})")

        print("\n" + "=" * 70)
        print("1) Log in if asked.")
        print("2) Open ONE actual LESSON/VIDEO page (so we can see the video host).")
        print("3) Come back here and press ENTER to capture it.")
        print("=" * 70)
        try:
            input(">>> Press ENTER once the lesson page is showing... ")
        except EOFError:
            pass

        session_dir.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))

        html = page.content()
        current = page.url
        (dump_dir / "page.html").write_text(html, encoding="utf-8")

        summary = summarize(html, current)
        (dump_dir / "summary.txt").write_text(summary, encoding="utf-8")
        print("\n" + summary)
        print(f"\nFull HTML  -> {dump_dir / 'page.html'}")
        print(f"Summary    -> {dump_dir / 'summary.txt'}")
        print(f"Session    -> {state_path}")

        context.close()
        browser.close()
    return 0


def summarize(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    lines: list[str] = [f"URL: {url}", ""]

    title = soup.title.string.strip() if soup.title and soup.title.string else "?"
    lines.append(f"TITLE: {title}")

    gen = soup.find("meta", attrs={"name": "generator"})
    if gen and gen.get("content"):
        lines.append(f"META generator: {gen['content']}")

    blob = html.lower()
    hits = sorted({s for s in _PLATFORM_SIGNATURES if s in blob})
    lines.append(f"PLATFORM SIGNATURES present: {hits or 'none found'}")
    lines.append("")

    # iframes (videos usually live here: wistia/vimeo/youtube)
    iframes = [i.get("src") for i in soup.find_all("iframe") if i.get("src")]
    lines.append(f"IFRAMES ({len(iframes)}):")
    for src in iframes[:25]:
        lines.append(f"  - {src}")
    lines.append("")

    # native video tags
    vids = []
    for v in soup.find_all("video"):
        if v.get("src"):
            vids.append(v["src"])
        for s in v.find_all("source"):
            if s.get("src"):
                vids.append(s["src"])
    lines.append(f"<video>/<source> ({len(vids)}):")
    for src in vids[:25]:
        lines.append(f"  - {src}")
    lines.append("")

    # Wistia media ids (Kajabi embeds these as classes / async ids)
    wistia = sorted(set(re.findall(r"wistia_async_([a-z0-9]+)", html)
                        + re.findall(r"wistia\.com/medias/([a-z0-9]+)", html)
                        + re.findall(r"fast\.wistia\.[a-z]+/embed/medias/([a-z0-9]+)", html)))
    if wistia:
        lines.append(f"WISTIA media ids: {wistia[:25]}")
        lines.append("")

    # script srcs (helps confirm platform/video host)
    scripts = sorted({s.get("src") for s in soup.find_all("script") if s.get("src")})
    interesting = [s for s in scripts
                   if any(k in s.lower() for k in _PLATFORM_SIGNATURES)]
    lines.append(f"NOTABLE SCRIPT srcs ({len(interesting)}):")
    for s in interesting[:25]:
        lines.append(f"  - {s}")
    lines.append("")

    # candidate lesson/module links
    links = sorted({a.get("href") for a in soup.find_all("a")
                    if a.get("href") and _LESSON_LINK_RE.search(a.get("href"))})
    lines.append(f"CANDIDATE lesson/module links ({len(links)}):")
    for href in links[:40]:
        lines.append(f"  - {href}")
    lines.append("")

    # embedded JSON globals
    found_json = []
    for marker in _JSON_GLOBALS:
        if marker in html:
            found_json.append(marker)
    lines.append(f"EMBEDDED JSON/STATE markers: {found_json or 'none'}")
    json_scripts = soup.find_all("script", attrs={"type": "application/json"})
    lines.append(f"<script type=application/json> blocks: {len(json_scripts)}"
                 + (f" (ids: {[s.get('id') for s in json_scripts][:10]})" if json_scripts else ""))

    return "\n".join(lines)
