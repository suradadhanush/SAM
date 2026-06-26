"""
THE HANDS — Browser Agent
Playwright-powered autonomous browser control.
Opens URLs, fills forms, extracts data, navigates pages.
"""

import logging
import json
from typing import Optional

logger = logging.getLogger("SAM.Browser")


class BrowserAgent:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None
        self._started = False

    def _start(self):
        if self._started:
            return
        try:
            from playwright.sync_api import sync_playwright
            self._playwright_ctx = sync_playwright().__enter__()
            self._browser = self._playwright_ctx.chromium.launch(
                headless=False  # Visible so user can see what SAM is doing
            )
            self._page = self._browser.new_page()
            self._started = True
            logger.info("Playwright browser started")
        except ImportError:
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

    def execute(self, url: str = "", task: str = "") -> str:
        """
        Navigate to URL and complete the given task.
        Returns result as text.
        """
        self._start()

        try:
            if url:
                logger.info(f"Navigating to: {url}")
                self._page.goto(url, wait_until="networkidle", timeout=30000)

            if not task:
                return self._get_page_content()

            # Perform the task on the page
            return self._perform_task(task)

        except Exception as e:
            logger.error(f"Browser error: {e}", exc_info=True)
            return f"Browser error: {e}"

    def _perform_task(self, task: str) -> str:
        """Perform a specific task on the current page."""
        task_lower = task.lower()

        if "extract" in task_lower or "get" in task_lower or "find" in task_lower or "read" in task_lower:
            return self._extract_content(task)
        elif "click" in task_lower:
            return self._smart_click(task)
        elif "fill" in task_lower or "type" in task_lower or "enter" in task_lower:
            return self._smart_fill(task)
        elif "scroll" in task_lower:
            self._page.evaluate("window.scrollBy(0, 500)")
            return "Scrolled down"
        else:
            return self._extract_content(task)

    def _extract_content(self, task: str) -> str:
        """Extract text content from the page."""
        try:
            # Get all text from page
            content = self._page.evaluate("""() => {
                return document.body.innerText;
            }""")
            # Truncate to reasonable length
            return content[:3000] if content else "No content found"
        except Exception as e:
            return f"Could not extract content: {e}"

    def _smart_click(self, task: str) -> str:
        """Find and click an element based on task description."""
        try:
            # Try to find by text content
            words = task.lower().replace("click", "").strip().split()
            for word in words:
                if len(word) > 3:
                    try:
                        self._page.click(f"text={word}", timeout=5000)
                        return f"Clicked element containing '{word}'"
                    except Exception:
                        continue
            return "Could not find element to click"
        except Exception as e:
            return f"Click error: {e}"

    def _smart_fill(self, task: str) -> str:
        """Fill a form field."""
        try:
            # Try focused element first
            self._page.keyboard.type(task.split("type")[-1].strip())
            return f"Typed in focused field"
        except Exception as e:
            return f"Fill error: {e}"

    def _get_page_content(self) -> str:
        """Get current page title and brief content."""
        title = self._page.title()
        url = self._page.url
        content = self._page.evaluate("() => document.body.innerText")
        return f"Page: {title}\nURL: {url}\n\n{content[:1000]}"

    def screenshot(self, path: str = None) -> str:
        """Take screenshot of browser page."""
        if path is None:
            import tempfile
            path = tempfile.mktemp(suffix=".png")
        self._page.screenshot(path=path)
        return path

    def get_page_url(self) -> str:
        return self._page.url if self._page else ""

    def close(self):
        if self._started:
            try:
                self._browser.close()
                self._playwright_ctx.__exit__(None, None, None)
                self._started = False
            except Exception:
                pass
