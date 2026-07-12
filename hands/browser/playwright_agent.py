"""
THE HANDS — Browser Agent
Playwright-powered autonomous browser control.
Opens URLs, fills forms, extracts data, navigates pages.
"""

import logging
import json
import threading
from typing import Optional

logger = logging.getLogger("SAM.Browser")


class BrowserAgent:
    def __init__(self):
        self._playwright_ctx = None
        self._browser = None
        self._page = None
        self._started = False
        # Bug fixed here (found via real Mac testing): Playwright's sync API
        # binds its dispatcher to whichever OS thread created it — it is
        # NOT safe to call from a different thread. main.py's input
        # handling spawns a fresh thread per message, so turn 2's browser
        # call could land on a completely different thread than turn 1's —
        # and turn 1's thread has since exited, permanently breaking every
        # future browser call for the rest of the session with
        # "cannot switch to a different thread (which happens to have
        # exited)". This was confirmed in testing: the FIRST turn's
        # multi-step browser use worked flawlessly (same thread throughout
        # that one turn), but the very next separate message's first
        # browser call failed immediately, and every one after that failed
        # identically for the rest of the session.
        self._owner_thread_id = None

    def _start(self):
        current_thread_id = threading.get_ident()

        if self._started and self._owner_thread_id != current_thread_id:
            logger.warning(
                f"Browser called from a different thread (was "
                f"{self._owner_thread_id}, now {current_thread_id}) — "
                f"recreating the browser session on this thread instead "
                f"of staying permanently broken."
            )
            self._force_close()

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
            self._owner_thread_id = current_thread_id
            logger.info("Playwright browser started")
        except ImportError:
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

    def _force_close(self):
        """
        Tears down a browser session that may already be broken (e.g.
        bound to a thread that has exited). Best-effort and swallows
        errors on purpose — closing a cross-thread-bound Playwright object
        can itself raise the exact same thread error we're recovering
        from, and the goal here is recovery, not a clean shutdown. Any
        resources that can't be closed cleanly are abandoned rather than
        left blocking a fresh, working browser from being created.
        """
        try:
            if self._browser:
                self._browser.close()
        except Exception as e:
            logger.debug(f"Old browser close failed (expected if cross-thread): {e}")
        try:
            if self._playwright_ctx:
                self._playwright_ctx.__exit__(None, None, None)
        except Exception as e:
            logger.debug(f"Old playwright context close failed (expected if cross-thread): {e}")

        self._browser = None
        self._page = None
        self._playwright_ctx = None
        self._started = False

    @staticmethod
    def _is_thread_affinity_error(e: Exception) -> bool:
        msg = str(e).lower()
        return "cannot switch to a different thread" in msg or "greenlet" in msg

    def execute(self, url: str = "", task: str = "") -> str:
        """
        Navigate to URL and complete the given task. Returns result as text.

        Second bug fixed here, found by testing the FIRST fix attempt
        before shipping it: the _owner_thread_id check in _start() above
        is a fast-path that catches a thread mismatch proactively WHEN it
        can — but it is NOT reliable on its own. When threads run
        sequentially and don't overlap (the normal case here — turn 1's
        thread fully exits before turn 2's thread is even created), the OS
        frequently reuses the exact same thread ID for the new thread, so
        a simple ID comparison can miss the staleness entirely. Confirmed
        this with a test mirroring the real sequential-thread scenario —
        the ID-only version silently kept using the dead page.

        The actual guarantee comes from here instead: if a call still
        fails with the thread-affinity error message (regardless of why
        the proactive check didn't catch it), tear down and recreate the
        browser and retry the SAME call once, transparently. This is
        correct regardless of thread ID reuse, because it reacts to the
        real failure instead of trying to predict it in advance.
        """
        self._start()

        try:
            return self._do_execute(url, task)
        except Exception as e:
            if self._is_thread_affinity_error(e):
                logger.warning(f"Stale cross-thread browser session ({e}) — "
                                f"recreating and retrying once.")
                self._force_close()
                self._start()
                try:
                    return self._do_execute(url, task)
                except Exception as e2:
                    logger.error(f"Browser error after recreation retry: {e2}", exc_info=True)
                    return f"Browser error: {e2}"
            logger.error(f"Browser error: {e}", exc_info=True)
            return f"Browser error: {e}"

    def _do_execute(self, url: str, task: str) -> str:
        if url:
            logger.info(f"Navigating to: {url}")
            self._page.goto(url, wait_until="networkidle", timeout=30000)

        if not task:
            return self._get_page_content()

        return self._perform_task(task)

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
