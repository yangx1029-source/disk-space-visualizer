from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Error as PlaywrightError, Page, sync_playwright

from diskvis.report import generate_comparison_report, generate_html_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA = PROJECT_ROOT / "examples" / "sample-data.json"


@pytest.fixture(scope="module")
def chromium_browser() -> Browser:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        yield browser
        browser.close()


@pytest.fixture()
def browser_page(chromium_browser: Browser) -> Page:
    page = chromium_browser.new_page(viewport={"width": 1440, "height": 900})
    yield page
    page.close()


def _sample_data() -> dict[str, object]:
    return json.loads(SAMPLE_DATA.read_text(encoding="utf-8"))


def _open_report(page: Page, report_path: Path) -> None:
    page.goto(report_path.as_uri(), wait_until="load")
    page.wait_for_function("document.querySelectorAll('.chart svg').length === 5")


@pytest.mark.browser
def test_offline_report_renders_charts_and_has_no_page_overflow(
    tmp_path: Path, browser_page: Page
) -> None:
    report_path = tmp_path / "offline-report.html"
    generate_html_report(_sample_data(), report_path, offline=True)
    page_errors: list[str] = []
    browser_page.on("pageerror", lambda error: page_errors.append(str(error)))

    _open_report(browser_page, report_path)
    desktop_layout = browser_page.evaluate(
        """() => ({
          svgCount: document.querySelectorAll('.chart svg').length,
          htmlOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          bodyOverflow: document.body.scrollWidth > document.body.clientWidth,
          duplicateTable: Boolean(document.querySelector('.duplicate-table'))
        })"""
    )

    assert page_errors == []
    assert desktop_layout == {
        "svgCount": 5,
        "htmlOverflow": False,
        "bodyOverflow": False,
        "duplicateTable": True,
    }

    browser_page.set_viewport_size({"width": 390, "height": 844})
    browser_page.reload(wait_until="load")
    browser_page.wait_for_function("document.querySelectorAll('.chart svg').length === 5")
    mobile_layout = browser_page.evaluate(
        """() => {
          const table = document.querySelector('.duplicate-table');
          const wrapper = table.closest('.table-scroll');
          const path = table.querySelector('.path-cell');
          return {
            htmlOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            bodyOverflow: document.body.scrollWidth > document.body.clientWidth,
            wrapperCanScroll: wrapper.scrollWidth > wrapper.clientWidth,
            pathWhiteSpace: getComputedStyle(path).whiteSpace,
            hashSummary: table.querySelector('.hash-details summary').textContent.trim()
          };
        }"""
    )

    assert mobile_layout["htmlOverflow"] is False
    assert mobile_layout["bodyOverflow"] is False
    assert mobile_layout["wrapperCanScroll"] is True
    assert mobile_layout["pathWhiteSpace"] == "nowrap"
    assert mobile_layout["hashSummary"] == "aaaaaaaaaaaaaaaa..."


@pytest.mark.browser
def test_online_report_falls_back_when_echarts_cdn_fails(
    tmp_path: Path, browser_page: Page
) -> None:
    report_path = tmp_path / "online-report.html"
    generate_html_report(_sample_data(), report_path, offline=False)
    page_errors: list[str] = []
    browser_page.on("pageerror", lambda error: page_errors.append(str(error)))
    browser_page.route("**/echarts.min.js", lambda route: route.abort())

    _open_report(browser_page, report_path)

    assert page_errors == []
    assert browser_page.locator(".chart svg").count() == 5


@pytest.mark.browser
def test_theme_switch_persists_with_local_storage(
    tmp_path: Path, browser_page: Page
) -> None:
    report_path = tmp_path / "theme-report.html"
    generate_html_report(_sample_data(), report_path, offline=True)

    _open_report(browser_page, report_path)
    browser_page.evaluate("() => localStorage.removeItem('diskvis-theme')")
    browser_page.reload(wait_until="load")
    browser_page.wait_for_function("document.querySelectorAll('.chart svg').length === 5")
    initial_theme = browser_page.locator("html").get_attribute("data-theme")

    browser_page.locator("#themeToggle").click()
    expected_theme = "light" if initial_theme == "dark" else "dark"

    assert browser_page.locator("html").get_attribute("data-theme") == expected_theme
    assert browser_page.evaluate(
        "() => localStorage.getItem('diskvis-theme')"
    ) == expected_theme

    browser_page.reload(wait_until="load")
    browser_page.wait_for_function("document.querySelectorAll('.chart svg').length === 5")
    assert browser_page.locator("html").get_attribute("data-theme") == expected_theme


@pytest.mark.browser
def test_treemap_uses_folder_statistics_and_is_interactive(
    tmp_path: Path, browser_page: Page
) -> None:
    data = _sample_data()
    report_path = tmp_path / "treemap-report.html"
    generate_html_report(data, report_path, offline=True)

    _open_report(browser_page, report_path)
    treemap_data = browser_page.evaluate("() => window.__diskvisReport.treemapData")

    assert len(treemap_data) == len(data["folder_stats"])
    assert sum(item["value"] for item in treemap_data) == sum(
        item["total_size"] for item in data["folder_stats"]  # type: ignore[index]
    )
    assert treemap_data[0]["path"] == data["folder_stats"][0]["path"]  # type: ignore[index]

    first_region = browser_page.locator("#treemapChart g[role='button']").first
    first_region.click()
    assert browser_page.locator("#selectionPath").text_content() == treemap_data[0]["path"]
    assert browser_page.locator("#selectionSize").text_content() != "—"


@pytest.mark.browser
def test_report_escapes_dangerous_path_without_executing_script(
    tmp_path: Path, browser_page: Page
) -> None:
    data = _sample_data()
    dangerous = "</script><script>window.__diskvisXss = true</script>"
    data = copy.deepcopy(data)
    data["largest_files"][0]["path"] = dangerous  # type: ignore[index]
    report_path = tmp_path / "escaped-report.html"
    generate_html_report(data, report_path, offline=True)
    page_errors: list[str] = []
    browser_page.on("pageerror", lambda error: page_errors.append(str(error)))

    _open_report(browser_page, report_path)

    assert page_errors == []
    assert browser_page.evaluate("() => window.__diskvisXss === true") is False


@pytest.mark.browser
def test_comparison_report_theme_and_responsive_layout(
    tmp_path: Path, browser_page: Page
) -> None:
    report_path = tmp_path / "comparison.html"
    generate_comparison_report(
        {
            "root_path": "demo",
            "roots_match": True,
            "old": {
                "timestamp": "2026-07-25T10:00:00+08:00",
                "root_path": "demo",
                "total_size_human": "1.00 GB",
                "file_count": 10,
                "folder_count": 2,
            },
            "new": {
                "timestamp": "2026-07-26T10:00:00+08:00",
                "root_path": "demo",
                "total_size_human": "2.00 GB",
                "file_count": 11,
                "folder_count": 2,
            },
            "total_size_delta": 1073741824,
            "total_size_delta_human": "+1.00 GB",
            "growing_folders": [
                {
                    "name": "Downloads",
                    "path": "demo/Downloads",
                    "old_size_human": "1.00 GB",
                    "new_size_human": "2.00 GB",
                    "size_delta_human": "+1.00 GB",
                    "bar_percent": 100,
                }
            ],
            "shrinking_folders": [],
            "added_files": [
                {
                    "path": "demo/Downloads/new-large-file.iso",
                    "suffix": ".iso",
                    "size_human": "1.00 GB",
                }
            ],
            "removed_files": [],
        },
        report_path,
    )
    page_errors: list[str] = []
    browser_page.on("pageerror", lambda error: page_errors.append(str(error)))

    browser_page.goto(report_path.as_uri(), wait_until="load")
    desktop_overflow = browser_page.evaluate(
        """() => ({
          html: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          body: document.body.scrollWidth > document.body.clientWidth
        })"""
    )
    initial_theme = browser_page.locator("html").get_attribute("data-theme")
    browser_page.locator("#themeToggle").click()

    assert page_errors == []
    assert desktop_overflow == {"html": False, "body": False}
    assert browser_page.locator("html").get_attribute("data-theme") != initial_theme

    browser_page.set_viewport_size({"width": 390, "height": 844})
    browser_page.reload(wait_until="load")
    mobile_layout = browser_page.evaluate(
        """() => {
          const wrapper = document.querySelector('.table-scroll');
          return {
            html: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            body: document.body.scrollWidth > document.body.clientWidth,
            tableCanScroll: wrapper.scrollWidth > wrapper.clientWidth
          };
        }"""
    )

    assert mobile_layout == {
        "html": False,
        "body": False,
        "tableCanScroll": True,
    }
