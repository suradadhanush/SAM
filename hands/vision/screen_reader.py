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
        Returns (x, y) coordinates or None.
        """
        try:
            screenshot_path = self._take_screenshot()
            image_b64 = self._image_to_base64(screenshot_path)

            prompt = f"""Look at this screenshot and find: {description}
Return the coordinates as JSON: {{"x": number, "y": number}}
If not found, return: {{"x": null, "y": null}}
Return ONLY the JSON, nothing else."""

            model = "moondream" if self.settings.vision_model == "moondream" else "llava"

            response = requests.post(
                f"{self.settings.ollama_host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False,
                    "format": "json"
                },
                timeout=60
            )

            import os
            os.unlink(screenshot_path)

            if response.status_code == 200:
                result = json.loads(response.json().get("response", "{}"))
                x, y = result.get("x"), result.get("y")
                if x is not None and y is not None:
                    logger.info(f"Found '{description}' at ({x}, {y})")
                    return (int(x), int(y))
            return None

        except Exception as e:
            logger.error(f"Element finding error: {e}")
            return None

    def read_text_on_screen(self) -> str:
        """Extract all text visible on screen."""
        return self.read("Read and transcribe all text visible on the screen. Be thorough.")

    def describe_current_state(self) -> str:
        """Get a full description of the current screen state."""
        return self.read(
            "Describe what application is open and what the user can see on screen. "
            "Include any important UI elements, text, or content."
        )
