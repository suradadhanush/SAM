"""
THE HANDS — Computer Controller
PyAutoGUI for mouse/keyboard control
AppleScript for macOS native system control
"""

import logging
import subprocess
import tempfile
import os
from pathlib import Path

logger = logging.getLogger("SAM.Controller")


class ComputerController:
    def __init__(self):
        self._pyautogui = None
        self._load_pyautogui()

    def _load_pyautogui(self):
        try:
            import pyautogui
            pyautogui.FAILSAFE = True  # Move mouse to corner to abort
            pyautogui.PAUSE = 0.1
            self._pyautogui = pyautogui
            logger.info("PyAutoGUI loaded")
        except ImportError:
            logger.warning("PyAutoGUI not installed")

    # ─── Mouse ────────────────────────────────────────────────────────────

    def click(self, x: int, y: int, button: str = "left"):
        if self._pyautogui:
            self._pyautogui.click(x, y, button=button)
            logger.info(f"Clicked at ({x}, {y})")

    def double_click(self, x: int, y: int):
        if self._pyautogui:
            self._pyautogui.doubleClick(x, y)

    def right_click(self, x: int, y: int):
        if self._pyautogui:
            self._pyautogui.click(x, y, button="right")

    def move_to(self, x: int, y: int, duration: float = 0.3):
        if self._pyautogui:
            self._pyautogui.moveTo(x, y, duration=duration)

    def scroll(self, x: int, y: int, clicks: int):
        if self._pyautogui:
            self._pyautogui.scroll(clicks, x=x, y=y)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5):
        if self._pyautogui:
            self._pyautogui.drag(x2 - x1, y2 - y1, duration=duration)

    # ─── Keyboard ─────────────────────────────────────────────────────────

    def type_text(self, text: str, interval: float = 0.02):
        if self._pyautogui:
            self._pyautogui.write(text, interval=interval)

    def hotkey(self, *keys):
        if self._pyautogui:
            self._pyautogui.hotkey(*keys)

    def press(self, key: str):
        if self._pyautogui:
            self._pyautogui.press(key)

    def key_down(self, key: str):
        if self._pyautogui:
            self._pyautogui.keyDown(key)

    def key_up(self, key: str):
        if self._pyautogui:
            self._pyautogui.keyUp(key)

    # ─── Screen ───────────────────────────────────────────────────────────

    def screenshot(self, path: str = None) -> str:
        """Take screenshot and return path."""
        if path is None:
            path = tempfile.mktemp(suffix=".png")
        if self._pyautogui:
            self._pyautogui.screenshot(path)
        else:
            subprocess.run(["screencapture", "-x", path])
        return path

    def get_screen_size(self) -> tuple:
        if self._pyautogui:
            return self._pyautogui.size()
        return (1440, 900)  # Default MacBook

    def get_mouse_position(self) -> tuple:
        if self._pyautogui:
            return self._pyautogui.position()
        return (0, 0)

    # ─── macOS AppleScript ────────────────────────────────────────────────

    def applescript(self, script: str) -> str:
        """Execute AppleScript and return output."""
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip()

    def open_app(self, app_name: str):
        """Open a macOS application."""
        self.applescript(f'tell application "{app_name}" to activate')
        logger.info(f"Opened app: {app_name}")

    def close_app(self, app_name: str):
        """Quit a macOS application."""
        self.applescript(f'tell application "{app_name}" to quit')

    def set_volume(self, level: int):
        """Set system volume (0-100)."""
        self.applescript(f"set volume output volume {level}")

    def get_frontmost_app(self) -> str:
        """Get name of the currently active application."""
        return self.applescript(
            'tell application "System Events" to get name of first application process whose frontmost is true'
        )

    def notify(self, title: str, message: str):
        """Show macOS notification."""
        self.applescript(
            f'display notification "{message}" with title "{title}"'
        )

    def open_url_in_browser(self, url: str):
        """Open URL in default browser."""
        subprocess.run(["open", url])

    def copy_to_clipboard(self, text: str):
        """Copy text to macOS clipboard."""
        subprocess.run(["pbcopy"], input=text.encode())

    def get_clipboard(self) -> str:
        """Get macOS clipboard content."""
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        return result.stdout

    def speak_text(self, text: str):
        """macOS native TTS (emergency fallback only)."""
        subprocess.run(["say", text])

    def get_all_windows(self) -> list:
        """Get list of all open windows via AppleScript."""
        script = """
tell application "System Events"
    set windowList to {}
    repeat with aProcess in (every application process whose visible is true)
        repeat with aWindow in (every window of aProcess)
            set end of windowList to (name of aProcess) & ": " & (name of aWindow)
        end repeat
    end repeat
    return windowList
end tell
"""
        result = self.applescript(script)
        return result.split(", ") if result else []
