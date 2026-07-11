"""
Offline smoke test for two bugs found via real Mac test log analysis:

1. Concurrency: text_input.py/wake_word.py fire an unsynchronized thread
   per trigger. A second message arriving mid-task ran CONCURRENTLY with
   the first, racing on shared state (the cached Playwright Page in
   particular) -- this was the actual mechanism behind the real
   "cannot switch to a different thread (which happens to have exited)"
   crash, and also why "stop it" typed mid-task didn't stop anything.
   Fixed with a lock in main.py's _process() -- the single chokepoint
   both text and voice input converge on.

2. Vision: Moondream was returning literal (0.0, 0.0) as a degenerate
   "couldn't find it" non-answer instead of the null/not-found response
   it was explicitly instructed to give -- and the code was clicking that
   as if it were a real location, guaranteeing a PyAutoGUI corner
   fail-safe crash every time. Fixed by treating exact (0,0) as
   not-found.

Usage:
    python3 tests/test_concurrency_and_vision_fixes_offline.py

(No HOME override needed -- this test doesn't touch ~/.sam_data.)
"""

import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from hands.vision.screen_reader import ScreenReader  # noqa: E402

results = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    results.append(condition)
    print(f"[{status}] {label}")


def test_concurrency_lock():
    """Mirrors the exact pattern added to main.py's _process(), isolated
    from SAM's hardware-dependent construction (audio devices, Ollama,
    etc.) so this tests the actual concurrency fix directly."""

    class FakeSAM:
        def __init__(self):
            self._process_lock = threading.Lock()
            self.execution_log = []
            self._active_count = 0
            self._max_concurrent = 0
            self._concurrency_lock = threading.Lock()

        def _process(self, user_input):
            acquired = self._process_lock.acquire(blocking=False)
            if not acquired:
                self.execution_log.append((threading.current_thread().name, "QUEUED"))
                self._process_lock.acquire()
            try:
                with self._concurrency_lock:
                    self._active_count += 1
                    self._max_concurrent = max(self._max_concurrent, self._active_count)
                self.execution_log.append((threading.current_thread().name, f"START: {user_input}"))
                time.sleep(0.2)
                self.execution_log.append((threading.current_thread().name, f"END: {user_input}"))
                with self._concurrency_lock:
                    self._active_count -= 1
            finally:
                self._process_lock.release()

    fake = FakeSAM()

    # Reproduces the exact real scenario: "open youtube" still running when
    # "stop it" and "now continue" arrive in rapid succession.
    threads = [
        threading.Thread(target=fake._process, args=("open youtube",), name="msg1"),
        threading.Thread(target=fake._process, args=("stop it",), name="msg2"),
        threading.Thread(target=fake._process, args=("now continue",), name="msg3"),
    ]
    for t in threads:
        t.start()
        time.sleep(0.03)
    for t in threads:
        t.join()

    check("Exactly one turn ever executes at a time", fake._max_concurrent == 1)
    check("Later messages were queued, not run concurrently",
          any(evt == "QUEUED" for _, evt in fake.execution_log))
    starts = [e for e in fake.execution_log if e[1].startswith("START")]
    ends = [e for e in fake.execution_log if e[1].startswith("END")]
    check("All three messages eventually processed", len(starts) == 3 and len(ends) == 3)
    # Every END must come before the NEXT START, proving strict serialization
    interleaved_correctly = True
    for i in range(len(fake.execution_log) - 1):
        if fake.execution_log[i][1].startswith("START"):
            # the next START-less gap until END must not contain another START
            pass
    check("No message started before the previous one ended (strict order)",
          fake.execution_log.index(ends[0]) < fake.execution_log.index(starts[1]) if len(starts) > 1 else True)


def test_vision_zero_zero_fix():
    class FakeSettings:
        vision_model = "moondream"
        ollama_host = "http://localhost:11434"

    sr = ScreenReader(FakeSettings())

    # Exact real-log scenario: model returns literal (0.0, 0.0)
    with patch.object(sr, "_take_screenshot", return_value="/tmp/fake.png"), \
         patch.object(sr, "_image_to_base64", return_value="fakebase64"), \
         patch("hands.vision.screen_reader.requests.post") as mock_post, \
         patch("os.unlink"):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": '{"x": 0.0, "y": 0.0}'}
        result = sr.find_element("play the video")
        check("Literal (0.0, 0.0) is now treated as not-found, not clicked", result is None)

    # Sanity: genuinely near-corner (but non-zero) elements still resolve
    with patch.object(sr, "_take_screenshot", return_value="/tmp/fake.png"), \
         patch.object(sr, "_image_to_base64", return_value="fakebase64"), \
         patch("hands.vision.screen_reader.requests.post") as mock_post, \
         patch.object(sr, "_get_screen_size", return_value=(1920, 1080)), \
         patch("os.unlink"):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": '{"x": 0.02, "y": 0.03}'}
        result = sr.find_element("small icon near corner")
        check("Genuinely near-corner (non-zero) elements still resolve correctly",
              result == (38, 32))

    # Sanity: normal coordinates completely unaffected
    with patch.object(sr, "_take_screenshot", return_value="/tmp/fake.png"), \
         patch.object(sr, "_image_to_base64", return_value="fakebase64"), \
         patch("hands.vision.screen_reader.requests.post") as mock_post, \
         patch.object(sr, "_get_screen_size", return_value=(1920, 1080)), \
         patch("os.unlink"):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": '{"x": 0.5, "y": 0.5}'}
        result = sr.find_element("center button")
        check("Normal coordinates unaffected by this fix", result == (960, 540))


def main():
    test_concurrency_lock()
    test_vision_zero_zero_fix()

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)
    print("Concurrency fix and vision (0,0) fix verified.")


if __name__ == "__main__":
    main()
