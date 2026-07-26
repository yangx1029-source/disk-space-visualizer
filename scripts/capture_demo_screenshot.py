"""Capture the public demo report with a real Chromium browser."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "examples" / "sample-report.html"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "assets" / "report-screenshot.png"
COMPARISON_REPORT_PATH = PROJECT_ROOT / "examples" / "sample-comparison.html"
COMPARISON_OUTPUT_PATH = (
    PROJECT_ROOT / "docs" / "assets" / "comparison-screenshot.png"
)


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
        browser.close()
    print(f"Generated screenshots: {OUTPUT_PATH}, {COMPARISON_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
