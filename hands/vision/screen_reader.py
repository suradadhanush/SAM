"""
THE HANDS — Vision
Takes screenshots and understands what's on screen.
Primary: Moondream (1.8B, fast)
Fallback: LLaVA (7B, more capable)
"""

import logging
import base64
import json
import tempfile
import requests
from pathlib import Path

logger = logging.getLogger("SAM.Vision")


class ScreenReader:
    def __init__(self, settings):
        self.settings = settings

    def _take_screenshot(self) -> str:
        """Take screenshot and return path."""
        import subprocess
        path = tempfile.mktemp(suffix=".png")
        subprocess.run(["screencapture", "-x", path], check=True)
        return path

    def _image_to_base64(self, path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    def read(self, task: str = "Describe what you see on the screen") -> str:
        """
        Take a screenshot and ask the vision model to interpret it.
        Returns text description.
        """
        try:
            screenshot_path = self._take_screenshot()
            image_b64 = self._image_to_base64(screenshot_path)

            model = (
                "moondream" if self.settings.vision_model == "moondream"
                else "llava"
            )

            response = requests.post(
                f"{self.settings.ollama_host}/api/generate",
                json={
                    "model": model,
                    "prompt": task,
                    "images": [image_b64],
                    "stream": False
                },
                timeout=60
            )

            import os
            os.unlink(screenshot_path)

            if response.status_code == 200:
                result = response.json().get("response", "")
                logger.info(f"Vision result: {result[:100]}")
                return result
            else:
                return f"Vision error: {response.status_code}"

        except Exception as e:
            logger.error(f"Vision error: {e}", exc_info=True)
            return f"Could not read screen: {e}"

    def find_element(self, description: str) -> tuple:
        """
        Find an element on screen by description.
        Returns (x, y) PIXEL coordinates ready to click, or None.

        Bug fixed here (found via real Mac testing): Moondream returns
        NORMALIZED coordinates (0.0-1.0 fractional) for pointing tasks, not
        pixel coordinates. This code used to do int(x), int(y) directly on
        those fractions — e.g. (0.17, 0.18) became (0, 0), the literal
        top-left corner of the screen. Every click was aiming at the
        corner, which is exactly why PyAutoGUI's own fail-safe kept firing
        ("mouse moving to a corner of the screen") — nothing was actually
        moving there accidentally, it was being told to, every time.
        """
        try:
            screenshot_path = self._take_screenshot()
            image_b64 = self._image_to_base64(screenshot_path)

            prompt = f"""Look at this screenshot and find: {description}
Return ONLY this JSON, nothing else — no explanation, no extra text:
{{"x": 0.0, "y": 0.0}}
Where x and y are the NORMALIZED position as a fraction of screen width/height,
each between 0.0 and 1.0 (e.g. center of screen is {{"x": 0.5, "y": 0.5}}).
If not found, return: {{"x": null, "y": null}}"""

            model = "moondream" if self.settings.vision_model == "moondream" else "llava"

            response = requests.post(
                f"{self.settings.ollama_host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_predict": 60}
                },
                timeout=60
            )

            import os
            os.unlink(screenshot_path)

            if response.status_code != 200:
                return None

            raw = response.json().get("response", "{}")
            x, y = self._parse_coordinates(raw)
            if x is None or y is None:
                return None

            # Bug fixed here (found via more real Mac testing, AFTER the
            # int()-truncation fix above already shipped): the scaling
            # math was correct, but Moondream itself was returning literal
            # (0.0, 0.0) as its ANSWER when it couldn't actually find the
            # element — a well-known degenerate-guess failure mode in
            # vision-language models asked for coordinates (collapsing to
            # the origin instead of honestly returning the null/not-found
            # case it was explicitly instructed to use). No real on-screen
            # element is ever at the literal top-left corner pixel in
            # practice, so treat that exact answer as "not found" rather
            # than proceeding to click it — converts a guaranteed
            # PyAutoGUI fail-safe crash into a clean, retryable
            # "could not find X" result instead.
            if abs(x) < 1e-6 and abs(y) < 1e-6:
                logger.warning(f"Vision returned (0,0) for '{description}' — "
                                f"treating as not-found rather than clicking the corner")
                return None

            pixel_x, pixel_y = self._to_pixel_coords(x, y)
            logger.info(f"Found '{description}' at normalized ({x:.3f}, {y:.3f}) "
                        f"-> pixel ({pixel_x}, {pixel_y})")
            return (pixel_x, pixel_y)

        except Exception as e:
            logger.error(f"Element finding error: {e}")
            return None

    @staticmethod
    def _parse_coordinates(raw: str):
        """
        Parses the vision model's response for x/y. Tries strict JSON
        first; falls back to a regex scan if the model added stray text
        around the JSON or truncated it (both seen in real testing —
        "Unterminated string...", "Expecting value..." errors were this).
        """
        try:
            parsed = json.loads(raw)
            x, y = parsed.get("x"), parsed.get("y")
            if x is not None and y is not None:
                return float(x), float(y)
            return None, None
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        import re
        x_match = re.search(r'"?x"?\s*:\s*(-?[\d.]+)', raw)
        y_match = re.search(r'"?y"?\s*:\s*(-?[\d.]+)', raw)
        if x_match and y_match:
            try:
                return float(x_match.group(1)), float(y_match.group(1))
            except ValueError:
                pass
        return None, None

    def _to_pixel_coords(self, x: float, y: float) -> tuple:
        """Scales normalized (0.0-1.0) coordinates to real screen pixels.
        Defensively handles a model returning raw pixels instead (values
        outside 0-1) by passing them through unchanged."""
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            width, height = self._get_screen_size()
            return int(x * width), int(y * height)
        return int(x), int(y)

    @staticmethod
    def _get_screen_size() -> tuple:
        try:
            import pyautogui
            return pyautogui.size()
        except Exception as e:
            logger.warning(f"Could not get screen size, defaulting to 1920x1080: {e}")
            return (1920, 1080)

    def read_text_on_screen(self) -> str:
        """Extract all text visible on screen."""
        return self.read("Read and transcribe all text visible on the screen. Be thorough.")

    def describe_current_state(self) -> str:
        """Get a full description of the current screen state."""
        return self.read(
            "Describe what application is open and what the user can see on screen. "
            "Include any important UI elements, text, or content."
        )
