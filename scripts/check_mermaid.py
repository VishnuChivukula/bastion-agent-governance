"""Parse every Mermaid diagram in the given Markdown files; exit 1 if any is invalid.

    python scripts/check_mermaid.py docs/design/*.md

Uses the same Mermaid build as `make design-pdf` (needs network access to load it).
"""

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"
BLOCK = re.compile(r"```mermaid\n(.*?)```", re.S)


def main() -> int:
    diagrams = []
    for name in sys.argv[1:]:
        text = Path(name).read_text(encoding="utf-8")
        for match in BLOCK.finditer(text):
            line = text[: match.start()].count("\n") + 2
            diagrams.append((name, line, match.group(1)))
    failures = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(f'<script src="{MERMAID}"></script>', wait_until="networkidle")
        page.evaluate("mermaid.initialize({ startOnLoad: false })")
        for name, line, source in diagrams:
            error = page.evaluate(
                """async (source) => {
                    try { await mermaid.parse(source); return null; }
                    catch (e) { return String(e.message || e); }
                }""",
                source,
            )
            if error:
                failures += 1
                print(f"INVALID {name}:{line}\n  " + error.replace("\n", "\n  ")[:600])
        browser.close()
    print(f"{len(diagrams)} diagrams checked, {failures} invalid")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
