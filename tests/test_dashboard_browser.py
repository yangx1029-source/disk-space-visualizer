from __future__ import annotations

import time
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Error as PlaywrightError, Page, sync_playwright

from diskvis.dashboard.server import DashboardConfig, DashboardServer


@pytest.fixture(scope="module")
def dashboard_browser() -> Browser:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        yield browser
        browser.close()


@pytest.fixture()
def dashboard_page(
    tmp_path: Path, dashboard_browser: Browser
) -> tuple[Page, DashboardServer]:
    root = tmp_path / "dashboard-root"
    (root / "Media" / "Video").mkdir(parents=True)
    (root / "Media" / "photo.jpg").write_bytes(b"image")
    (root / "Media" / "Video" / "clip.mp4").write_bytes(b"video-content")
    (root / "notes.txt").write_text("notes", encoding="utf-8")
    batch = root / "Batch"
    batch.mkdir()
    for index in range(105):
        (batch / f"batch-{index:03}.log").write_text("x", encoding="utf-8")
    server = DashboardServer(
        DashboardConfig(
            root=root,
            port=0,
            snapshot_dir=tmp_path / "snapshots",
            save_snapshot=True,
        )
    )
    server.start_background()
    deadline = time.monotonic() + 10
    while server.manager.status()["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    page = dashboard_browser.new_page(viewport={"width": 1440, "height": 900})
    yield page, server
    page.close()
    server.close()


@pytest.mark.browser
def test_dashboard_renders_navigates_and_has_no_overflow(
    dashboard_page: tuple[Page, DashboardServer],
) -> None:
    page, server = dashboard_page
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server.url, wait_until="load")
    page.wait_for_selector("#view-overview.active")

    assert errors == []
    assert page.locator("#metricGrid .metric").count() == 6
    assert page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    ) is False

    page.locator(".tab[data-view='browser']").click()
    page.wait_for_selector("#view-browser.active")
    page.locator("#treemap .tree-cell", has_text="Media").click()
    page.locator("#breadcrumbs button").nth(1).wait_for()
    assert "Media" in page.locator("#breadcrumbs").text_content()

    initial_theme = page.locator("html").get_attribute("data-theme")
    page.locator("#themeToggle").click()
    assert page.locator("html").get_attribute("data-theme") != initial_theme
    assert page.evaluate("() => localStorage.getItem('diskvis-dashboard-theme')") is not None

    page.set_viewport_size({"width": 390, "height": 844})
    page.reload(wait_until="load")
    page.wait_for_selector("#view-overview.active")
    mobile = page.evaluate(
        """() => ({
          html: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          body: document.body.scrollWidth > document.body.clientWidth
        })"""
    )
    assert mobile == {"html": False, "body": False}


@pytest.mark.browser
def test_dashboard_search_and_history_views(
    dashboard_page: tuple[Page, DashboardServer],
) -> None:
    page, server = dashboard_page
    page.goto(server.url, wait_until="load")
    page.wait_for_selector("#view-overview.active")
    page.locator(".tab[data-view='analysis']").click()
    page.locator("#searchInput").fill("clip")
    page.locator("#searchButton").click()
    page.locator("#searchRows tr").wait_for()
    assert page.locator("#searchRows tr").count() == 1
    assert page.locator("#searchRows tr td").first.text_content() == "clip.mp4"

    page.locator("#searchInput").fill("batch-")
    page.locator("#searchButton").click()
    page.wait_for_function("() => document.querySelectorAll('#searchRows tr').length === 100")
    assert page.locator("#searchNext").is_enabled()
    page.locator("#searchNext").click()
    page.wait_for_function("() => document.querySelectorAll('#searchRows tr').length === 5")
    assert "101-105 / 105" in page.locator("#searchPage").text_content()

    page.locator(".tab[data-view='history']").click()
    page.wait_for_selector("#view-history.active")
    page.locator("#historyRows tr").first.wait_for()
    assert "1 次" in page.locator("#historyCount").text_content()

    page.locator(".tab[data-view='system']").click()
    page.wait_for_selector("#view-system.active")
    page.wait_for_function("() => document.querySelectorAll('#diagnosticGrid .diagnostic-item').length === 9")
    assert "API v1" in page.locator("#diagnosticGrid").text_content()
