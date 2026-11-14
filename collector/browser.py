"""Playwright 浏览器统一封装（无头 Chromium）。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


@contextmanager
def browser_page(width: int = 1280, height: int = 900) -> Iterator[Page]:
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=True)
        context: BrowserContext = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=2,
        )
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


@contextmanager
def browser_context() -> Iterator[tuple[Browser, BrowserContext]]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        try:
            yield browser, context
        finally:
            context.close()
            browser.close()
