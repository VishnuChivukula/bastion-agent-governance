"""Record the demo GIF (`make gif` → docs/assets/demo.gif).

Starts a throwaway Bastion (API + console, replay mode, temporary database), clicks through the
console with a headless browser, captures one frame per step with a caption, and assembles the
frames with Pillow. Nothing here needs an API key.
"""

import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "demo.gif"
VIEW = {"width": 1280, "height": 800}
FRAME_WIDTH = 960
FOOTER = "Bastion · Reference implementation"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(url: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 - local URL
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not come up")


class Stack:
    """API and console on free local ports, with their own temporary data directory."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="bastion-gif-")
        self.api_port, self.console_port = free_port(), free_port()
        self.url = f"http://127.0.0.1:{self.console_port}"
        env = {
            **os.environ,
            "BASTION_MODE": "replay",
            "BASTION_LOCAL_DEV": "1",
            "BASTION_LOW_MEMORY": "false",
            "BASTION_DB_PATH": str(Path(self.tmp.name) / "bastion.db"),
            "BASTION_API_URL": f"http://127.0.0.1:{self.api_port}",
        }
        env.pop("BASTION_PASSCODE", None)
        python = sys.executable
        self.procs = [
            subprocess.Popen(  # noqa: S603 - fixed command
                [
                    python,
                    "-m",
                    "uvicorn",
                    "bastion.api.main:app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.api_port),
                    "--log-level",
                    "warning",
                ],
                cwd=ROOT,
                env=env,
            ),  # fmt: skip
            subprocess.Popen(  # noqa: S603 - fixed command
                [
                    python,
                    "-m",
                    "streamlit",
                    "run",
                    "src/bastion/console/app.py",
                    "--server.port",
                    str(self.console_port),
                    "--server.address",
                    "127.0.0.1",
                    "--server.headless",
                    "true",
                    "--server.fileWatcherType",
                    "none",
                    "--client.toolbarMode",
                    "minimal",
                    "--browser.gatherUsageStats",
                    "false",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),  # fmt: skip
        ]

    def __enter__(self) -> "Stack":
        wait_for(f"http://127.0.0.1:{self.api_port}/healthz")
        wait_for(f"{self.url}/_stcore/health")
        return self

    def __exit__(self, *exc: object) -> None:
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.tmp.cleanup()


def settle(page: Page, text: str) -> None:
    page.get_by_text(text, exact=False).last.wait_for()


def open_page(page: Page, title: str) -> None:
    page.locator('[data-testid="stSidebarNav"] a', has_text=title).first.click()
    page.get_by_role("heading", name=title, exact=True).first.wait_for()
    settle(page, FOOTER)


def run_scenario(page: Page, use_case: str, done: str, approver_me: bool = False) -> None:
    open_page(page, "Run Scenario")
    page.locator('[data-testid="stRadio"] label', has_text=use_case).first.click()
    page.wait_for_timeout(600)
    if approver_me:
        page.locator('[data-testid="stRadio"] label', has_text="Me").last.click()
        page.wait_for_timeout(400)
    page.get_by_role("button", name="Run scenario").click()
    settle(page, done)
    page.wait_for_timeout(700)


class Recorder:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.frames: list[tuple[Image.Image, int]] = []
        try:
            self.font = ImageFont.load_default(size=22)
        except TypeError:  # older Pillow
            self.font = ImageFont.load_default()

    def shot(self, caption: str, seconds: float = 2.6, scroll_to: str | None = None) -> None:
        # Streamlit re-renders elements while a run is polled, so scroll the page container
        # itself rather than towards a particular element.
        self.page.evaluate(
            """(target) => {
                const main = document.querySelector('[data-testid="stMain"]')
                    || document.scrollingElement;
                if (target === null) { main.scrollTo(0, 0); return; }
                if (target === '@bottom') { main.scrollTo(0, main.scrollHeight); return; }
                const hit = [...main.querySelectorAll('p, h1, h2, h3, strong, summary')]
                    .find((el) => el.textContent.includes(target) && el.offsetParent !== null);
                if (hit) {
                    main.scrollTo(0, main.scrollTop + hit.getBoundingClientRect().top - 150);
                }
            }""",
            scroll_to,
        )
        self.page.wait_for_timeout(400)
        image = Image.open(io.BytesIO(self.page.screenshot())).convert("RGB")
        height = round(image.height * FRAME_WIDTH / image.width)
        image = image.resize((FRAME_WIDTH, height), Image.LANCZOS)
        bar = 46
        canvas = Image.new("RGB", (FRAME_WIDTH, height + bar), (20, 28, 44))
        canvas.paste(image, (0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.text((16, height + 10), caption, fill=(255, 255, 255), font=self.font)
        self.frames.append((canvas, int(seconds * 1000)))
        print(f"frame {len(self.frames):>2}: {caption}")

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        images = [
            frame.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
            for frame, _ in self.frames
        ]
        images[0].save(
            path, save_all=True, append_images=images[1:], loop=0, optimize=True,
            duration=[duration for _, duration in self.frames],
        )  # fmt: skip
        print(f"{path.relative_to(ROOT)}: {len(images)} frames, {path.stat().st_size // 1024} kB")


def record(page: Page, rec: Recorder) -> None:
    page.goto(page.url)
    settle(page, FOOTER)

    open_page(page, "Registry")
    page.get_by_text("Classification record").first.click()
    settle(page, "Assessor proposes")
    rec.shot("1 · Classify before deploy: two agents propose and challenge the risk tier, "
             "a human signs off", 3.4, scroll_to="Assessor proposes")  # fmt: skip

    run_scenario(page, "UC-02", "Completed")
    rec.shot("2 · Normal work goes through. PII is masked before the model sees it", 2.8,
             scroll_to="@bottom")  # fmt: skip

    run_scenario(page, "UC-03", "Halted by Bastion")
    rec.shot("3 · A poisoned note tries to export all customers: DENIED, incident opened, "
             "agent stopped", 3.6, scroll_to="@bottom")  # fmt: skip

    open_page(page, "Incidents")
    rec.shot("4 · The incident is on record, with a lifecycle and notes", 2.4)

    run_scenario(page, "UC-04", "The agent is waiting for you", approver_me=True)
    rec.shot("5 · A large credit-limit increase waits for a human. Nothing has executed", 3.2,
             scroll_to="@bottom")  # fmt: skip
    reason = page.get_by_label("Reason (required)").last
    reason.fill("Request ref 8812 checked against the income documents.")
    reason.press("Enter")
    page.wait_for_timeout(500)
    page.get_by_role("button", name="Approve").last.click()
    settle(page, "Completed")
    page.wait_for_timeout(700)
    rec.shot("6 · Approved: the identical call consumes a single-use grant and executes", 3.0,
             scroll_to="@bottom")  # fmt: skip

    run_scenario(page, "UC-05", "Completed")
    rec.shot("7 · Approve 60,000, then call with 600,000: new approval needed, nothing executes",
             3.4, scroll_to="@bottom")  # fmt: skip

    run_scenario(page, "UC-07", "Halted by Bastion")
    rec.shot("8 · Kill switch during a run: the next call is denied and the run halts", 3.0,
             scroll_to="@bottom")  # fmt: skip

    open_page(page, "Live Activity")
    page.wait_for_timeout(800)
    rec.shot("9 · Every decision is in a hash-chained audit log", 2.6)

    open_page(page, "Evidence")
    page.get_by_role("button", name="Generate evidence pack").click()
    settle(page, "Preview")
    page.wait_for_timeout(1200)
    rec.shot("10 · Evidence pack generated from the live records: HTML and PDF", 3.0,
             scroll_to="@bottom")  # fmt: skip

    open_page(page, "Red-Team")
    rec.shot("11 · 25 attacks blocked, 15 benign requests allowed: the gate on every commit",
             3.6)  # fmt: skip


def main() -> int:
    with Stack() as stack, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEW, device_scale_factor=1)
        page.set_default_timeout(120_000)
        page.goto(stack.url + "/")
        recorder = Recorder(page)
        record(page, recorder)
        browser.close()
    recorder.save(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
