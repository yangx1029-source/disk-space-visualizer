"""Capture the public reports and Dashboard with a real Chromium browser."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import Browser, sync_playwright
from playwright.sync_api import Error as PlaywrightError

if TYPE_CHECKING:
    from diskvis.dashboard.server import DashboardServer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
REPORT_PATH = PROJECT_ROOT / "examples" / "sample-report.html"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "assets" / "report-screenshot.png"
COMPARISON_REPORT_PATH = PROJECT_ROOT / "examples" / "sample-comparison.html"
COMPARISON_OUTPUT_PATH = (
    PROJECT_ROOT / "docs" / "assets" / "comparison-screenshot.png"
)
DASHBOARD_OUTPUT_PATH = PROJECT_ROOT / "docs" / "assets" / "dashboard-screenshot.png"
DASHBOARD_MOBILE_OUTPUT_PATH = (
    PROJECT_ROOT / "docs" / "assets" / "dashboard-mobile-screenshot.png"
)


def _wait_for_dashboard(server: DashboardServer) -> None:
    deadline = time.monotonic() + 15
    while server.manager.status()["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    status = server.manager.status()
    if status["state"] != "completed":
        raise RuntimeError(f"Dashboard demo scan failed: {status}")


def _capture_dashboard(browser: Browser) -> None:
    from diskvis.dashboard.server import DashboardConfig, DashboardServer

    with tempfile.TemporaryDirectory(prefix="diskvis-dashboard-demo-") as temporary:
        root = Path(temporary) / "DiskVisDemo"
        files = {
            root / "Projects" / "release.zip": 5_400_000,
            root / "Media" / "Videos" / "product-demo.mp4": 8_200_000,
            root / "Media" / "Photos" / "cover.jpg": 2_100_000,
            root / "Documents" / "research.pdf": 1_700_000,
            root / "Backups" / "archive.7z": 3_400_000,
            root / "README.txt": 24_000,
        }
        for path, size in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"0" * size)
        server = DashboardServer(
            DashboardConfig(
                root=root,
                port=0,
                save_snapshot=False,
                top=10,
                log_dir=Path(temporary) / "logs",
            )
        )
        server.start_background()
        try:
            _wait_for_dashboard(server)
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            page.emulate_media(color_scheme="light", reduced_motion="reduce")
            page.goto(server.url, wait_until="load")
            page.locator("#metricGrid .metric").nth(5).wait_for()
            page.evaluate(
                """([actual, demo]) => {
                  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                  const nodes = [];
                  while (walker.nextNode()) nodes.push(walker.currentNode);
                  nodes.forEach(node => { node.textContent = node.textContent.replaceAll(actual, demo); });
                  document.querySelectorAll('[title]').forEach(element => {
                    element.title = element.title.replaceAll(actual, demo);
                  });
                }""",
                [str(root), r"C:\Users\Public\DiskVisDemo"],
            )
            page.screenshot(path=str(DASHBOARD_OUTPUT_PATH), full_page=True)
            page.close()

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.emulate_media(color_scheme="light", reduced_motion="reduce")
            mobile.goto(server.url, wait_until="load")
            mobile.locator("#metricGrid .metric").nth(5).wait_for()
            mobile.evaluate(
                """([actual, demo]) => {
                  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                  const nodes = [];
                  while (walker.nextNode()) nodes.push(walker.currentNode);
                  nodes.forEach(node => { node.textContent = node.textContent.replaceAll(actual, demo); });
                  document.querySelectorAll('[title]').forEach(element => {
                    element.title = element.title.replaceAll(actual, demo);
                  });
                }""",
                [str(root), r"C:\Users\Public\DiskVisDemo"],
            )
            mobile.screenshot(path=str(DASHBOARD_MOBILE_OUTPUT_PATH), full_page=True)
            mobile.close()
        finally:
            server.close()


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            raise SystemExit(f"Chromium is not installed: {exc}") from exc
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.emulate_media(color_scheme="dark")
        page.goto(REPORT_PATH.as_uri(), wait_until="load")
        page.wait_for_function("document.querySelectorAll('.chart svg').length === 5")
        page.screenshot(path=str(OUTPUT_PATH), full_page=True)

        page.goto(COMPARISON_REPORT_PATH.as_uri(), wait_until="load")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_function(
            """Array.from(document.querySelectorAll('.reveal'))
            .every(element => getComputedStyle(element).opacity === '1')"""
        )
        page.screenshot(path=str(COMPARISON_OUTPUT_PATH), full_page=True)
        _capture_dashboard(browser)
        browser.close()
    print(
        "Generated screenshots: "
        f"{OUTPUT_PATH}, {COMPARISON_OUTPUT_PATH}, "
        f"{DASHBOARD_OUTPUT_PATH}, {DASHBOARD_MOBILE_OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
