"""Open the console in a real (headless) browser and click through it, like a visitor would.

    python scripts/console_walk.py --url http://localhost:8501

Used by CI to put a realistic load on a memory-limited container: a browser session makes
the console load its data-frame stack, a scenario makes the API load the PII engine and the
agent, and the evidence page renders a pack. Exits non-zero if a page shows an error.
"""

import argparse
import sys

from playwright.sync_api import sync_playwright

PAGES = ["Overview", "Live Activity", "Approvals", "Incidents", "Registry", "Policies",
         "Red-Team"]  # fmt: skip
FOOTER = "Bastion · Reference implementation"


def settle(page, text: str, timeout: int = 120_000) -> None:
    page.get_by_text(text, exact=False).last.wait_for(timeout=timeout)


def open_page(page, title: str) -> None:
    """Navigate like a visitor: through the sidebar."""
    page.locator('[data-testid="stSidebarNav"] a', has_text=title).first.click()
    page.get_by_role("heading", name=title, exact=True).first.wait_for()
    settle(page, FOOTER)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8501")
    args = parser.parse_args()
    problems: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(180_000)
        page.goto(args.url.rstrip("/") + "/")
        settle(page, FOOTER)

        open_page(page, "Run Scenario")
        page.locator('[data-testid="stRadio"] label', has_text="UC-03").first.click()
        settle(page, "A poisoned note")
        page.get_by_role("button", name="Run scenario").click()
        settle(page, "Halted by Bastion")
        print("Run Scenario: UC-03 halted by Bastion")

        for title in PAGES:
            open_page(page, title)
            if page.locator('[data-testid="stException"]').count():
                problems.append(f"{title}: exception shown")
            print(f"{title}: ok")

        open_page(page, "Evidence")
        page.get_by_role("button", name="Generate evidence pack").click()
        settle(page, "Preview")
        print("Evidence: pack generated")
        browser.close()
    for problem in problems:
        print(f"PROBLEM {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
