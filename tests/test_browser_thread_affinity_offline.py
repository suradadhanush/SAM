"""
Offline smoke test for the browser thread-affinity fix — the deeper bug
behind "cannot switch to a different thread (which happens to have
exited)" that survived the previous round's concurrency lock fix.

Root cause: Playwright's sync API is bound to whichever OS thread created
it. ears/text_input.py spawns a fresh thread per message, so turn 2's
browser call can land on a thread different from turn 1's — and once
turn 1's thread has exited, every future browser call fails identically
for the rest of the session.

This test also documents a real flaw found in the FIRST fix attempt,
caught by testing before shipping: comparing threading.get_ident() values
is NOT reliable when threads run sequentially (non-overlapping) rather
than concurrently, because the OS frequently reuses the exact same thread
ID once the previous thread has fully exited — which is the NORMAL case
for this bug, not an edge case. The shipped fix instead reactively catches
the actual error signature and recovers, which works correctly regardless
of thread ID reuse.

Usage:
    python3 tests/test_browser_thread_affinity_offline.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from hands.browser.playwright_agent import BrowserAgent  # noqa: E402

results = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    results.append(condition)
    print(f"[{status}] {label}")


def test_error_signature_detection():
    agent = BrowserAgent()
    real_msg = "cannot switch to a different thread (which happens to have exited)"
    check("Real thread-affinity error is correctly identified",
          agent._is_thread_affinity_error(Exception(real_msg)) is True)
    check("Unrelated error is correctly NOT identified as thread-affinity",
          agent._is_thread_affinity_error(Exception("some other browser error")) is False)


def test_reactive_recovery_on_real_error():
    """The core fix: a stale cross-thread page raising the exact real
    error gets caught, the browser recreated, and the SAME call retried
    successfully — exactly once each, not a retry loop."""
    agent = BrowserAgent()

    mock_ctx_1 = MagicMock()
    mock_browser_1 = MagicMock()
    mock_page_1 = MagicMock()
    mock_ctx_1.chromium.launch.return_value = mock_browser_1
    mock_browser_1.new_page.return_value = mock_page_1
    mock_page_1.goto.side_effect = Exception(
        "cannot switch to a different thread (which happens to have exited)"
    )

    mock_ctx_2 = MagicMock()
    mock_browser_2 = MagicMock()
    mock_page_2 = MagicMock()
    mock_ctx_2.chromium.launch.return_value = mock_browser_2
    mock_browser_2.new_page.return_value = mock_page_2
    mock_page_2.goto.return_value = None

    call_count = {"n": 0}

    def fake_sync_playwright():
        call_count["n"] += 1
        m = MagicMock()
        m.__enter__.return_value = mock_ctx_1 if call_count["n"] == 1 else mock_ctx_2
        return m

    with patch("playwright.sync_api.sync_playwright", side_effect=fake_sync_playwright):
        result = agent.execute(url="https://example.com", task="")

    check("Result does not contain an unrecovered error", "Browser error" not in result)
    check("Browser session was recreated (using the fresh page)", agent._page is mock_page_2)
    check("Stale page's goto() was tried exactly once before recovery",
          mock_page_1.goto.call_count == 1)
    check("Fresh page's goto() was tried exactly once on retry",
          mock_page_2.goto.call_count == 1)


def test_non_thread_errors_are_not_retried():
    """A genuine navigation error (bad domain, timeout, etc.) should fail
    normally without triggering an unnecessary recreate-and-retry cycle."""
    agent = BrowserAgent()
    mock_ctx = MagicMock()
    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_ctx.chromium.launch.return_value = mock_browser
    mock_browser.new_page.return_value = mock_page
    mock_page.goto.side_effect = Exception("net::ERR_NAME_NOT_RESOLVED")

    with patch("playwright.sync_api.sync_playwright") as mock_sp:
        mock_sp.return_value.__enter__.return_value = mock_ctx
        result = agent.execute(url="https://doesnotexist.invalid", task="")

    check("Genuine navigation error is reported, not swallowed",
          "Browser error" in result and "ERR_NAME_NOT_RESOLVED" in result)
    check("Non-thread error does NOT trigger a retry", mock_page.goto.call_count == 1)


def test_second_recovery_attempt_also_fails_reports_cleanly():
    """If even the recreated browser hits the same error twice in a row
    (a genuinely broken environment, not just one stale thread), it should
    report the error rather than retry forever."""
    agent = BrowserAgent()
    mock_ctx = MagicMock()
    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_ctx.chromium.launch.return_value = mock_browser
    mock_browser.new_page.return_value = mock_page
    mock_page.goto.side_effect = Exception(
        "cannot switch to a different thread (which happens to have exited)"
    )

    with patch("playwright.sync_api.sync_playwright") as mock_sp:
        mock_sp.return_value.__enter__.return_value = mock_ctx
        result = agent.execute(url="https://example.com", task="")

    check("Persistent thread error after retry is reported, not infinite-looped",
          "Browser error" in result)
    check("Exactly 2 attempts made (original + 1 retry), not more",
          mock_page.goto.call_count == 2)


def main():
    test_error_signature_detection()
    test_reactive_recovery_on_real_error()
    test_non_thread_errors_are_not_retried()
    test_second_recovery_attempt_also_fails_reports_cleanly()

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)
    print("Browser thread-affinity self-healing fix verified.")


if __name__ == "__main__":
    main()
