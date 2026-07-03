"""
THE HANDS — Computer Controller
Cross-platform: macOS + Windows

macOS:   PyAutoGUI + AppleScript
Windows: PyAutoGUI + pywinauto + PowerShell

Platform auto-detected. Same API surface on both OS.
"""

import logging
import subprocess
import tempfile
import platform
import os

logger = logging.getLogger("SAM.Controller")

PLATFORM = platform.system()
IS_MAC = PLATFORM == "Darwin"
IS_WIN = PLATFORM == "Windows"


class ComputerController:
    def __init__(self):
        self._pyautogui = None
        self._winauto = None
        self._load_pyautogui()
        if IS_WIN:
            self._load_winauto()

    def _load_pyautogui(self):
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1
            self._pyautogui = pyautogui
            logger.info("PyAutoGUI loaded")
        except ImportError:
            logger.warning("PyAutoGUI not installed — pip install pyautogui")

    def _load_winauto(self):
        try:
            from pywinauto import Application
            self._winauto = Application
            logger.info("pywinauto loaded (Windows)")
        except ImportError:
            logger.warning("pywinauto not installed — pip install pywinauto")

    # ─── Mouse ────────────────────────────────────────────────────────────

    def click(self, x: int, y: int, button: str = "left"):
        if self._pyautogui:
            self._pyautogui.click(x, y, button=button)
            logger.info(f"Clicked ({x}, {y})")

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

    # ─── Screenshot ───────────────────────────────────────────────────────

    def screenshot(self, path: str = None) -> str:
        """Take screenshot cross-platform. Returns path to PNG."""
        if path is None:
            path = tempfile.mktemp(suffix=".png")

        if self._pyautogui:
            self._pyautogui.screenshot(path)
        elif IS_MAC:
            subprocess.run(["screencapture", "-x", path], check=True)
        elif IS_WIN:
            self._screenshot_windows(path)
        return path

    def _screenshot_windows(self, path: str):
        """Windows screenshot via PIL or PowerShell."""
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.save(path)
        except ImportError:
            ps_cmd = (
                f"Add-Type -AssemblyName System.Windows.Forms; "
                f"$s=[System.Windows.Forms.Screen]::PrimaryScreen; "
                f"$b=New-Object System.Drawing.Bitmap($s.Bounds.Width,$s.Bounds.Height); "
                f"$g=[System.Drawing.Graphics]::FromImage($b); "
                f"$g.CopyFromScreen($s.Bounds.Location,[System.Drawing.Point]::Empty,$s.Bounds.Size); "
                f"$b.Save('{path}')"
            )
            subprocess.run(["powershell", "-Command", ps_cmd], check=True, timeout=15)

    def get_screen_size(self) -> tuple:
        if self._pyautogui:
            return self._pyautogui.size()
        return (1920, 1080)

    def get_mouse_position(self) -> tuple:
        if self._pyautogui:
            return self._pyautogui.position()
        return (0, 0)

    # ─── App Control ──────────────────────────────────────────────────────

    def open_app(self, app_name: str):
        """Open an application — cross-platform."""
        if IS_MAC:
            self._applescript(f'tell application "{app_name}" to activate')
        elif IS_WIN:
            self._win_open_app(app_name)
        logger.info(f"Opened app: {app_name}")

    def close_app(self, app_name: str):
        """Close/quit an application — cross-platform."""
        if IS_MAC:
            self._applescript(f'tell application "{app_name}" to quit')
        elif IS_WIN:
            subprocess.run(["taskkill", "/IM", f"{app_name}.exe", "/F"],
                           capture_output=True)

    def _win_open_app(self, app_name: str):
        """Open app on Windows via start command."""
        # Map common app names to Windows executables
        win_app_map = {
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "explorer": "explorer.exe",
            "chrome": "chrome.exe",
            "firefox": "firefox.exe",
            "edge": "msedge.exe",
            "word": "winword.exe",
            "excel": "excel.exe",
            "terminal": "wt.exe",        # Windows Terminal
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
        }
        exe = win_app_map.get(app_name.lower(), f"{app_name}.exe")
        try:
            subprocess.Popen(["start", exe], shell=True)
        except Exception:
            # Try pywinauto
            if self._winauto:
                self._winauto(backend="uia").start(exe)

    # ─── System Actions ───────────────────────────────────────────────────

    def set_volume(self, level: int):
        """Set system volume (0-100) cross-platform."""
        if IS_MAC:
            self._applescript(f"set volume output volume {level}")
        elif IS_WIN:
            # PowerShell via nircmd or built-in
            ps_cmd = (
                f"$obj = New-Object -ComObject WScript.Shell; "
                f"$obj.SendKeys([char]174)"  # Volume key simulation is limited
            )
            # Better: use nircmd if available
            try:
                subprocess.run(
                    ["nircmd.exe", "setsysvolume", str(int(level / 100 * 65535))],
                    check=True, capture_output=True
                )
            except Exception:
                logger.warning("nircmd not found — volume control limited on Windows")

    def notify(self, title: str, message: str):
        """Show system notification cross-platform."""
        if IS_MAC:
            self._applescript(
                f'display notification "{message}" with title "{title}"'
            )
        elif IS_WIN:
            ps_cmd = (
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                f"ContentType = WindowsRuntime] | Out-Null; "
                f"$t = [Windows.UI.Notifications.ToastNotificationManager]"
                f"::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText01); "
                f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{title}: {message}')) | Out-Null; "
                f"$n = [Windows.UI.Notifications.ToastNotification]::new($t); "
                f"[Windows.UI.Notifications.ToastNotificationManager]"
                f"::CreateToastNotifier('SAM').Show($n)"
            )
            subprocess.run(["powershell", "-Command", ps_cmd],
                           capture_output=True, timeout=10)

    def open_url_in_browser(self, url: str):
        """Open URL in default browser — cross-platform."""
        if IS_MAC:
            subprocess.run(["open", url])
        elif IS_WIN:
            subprocess.run(["start", url], shell=True)

    # ─── Clipboard ────────────────────────────────────────────────────────

    def copy_to_clipboard(self, text: str):
        """Copy text to clipboard cross-platform."""
        if IS_MAC:
            subprocess.run(["pbcopy"], input=text.encode())
        elif IS_WIN:
            subprocess.run(["clip"], input=text.encode(), shell=True)

    def get_clipboard(self) -> str:
        """Get clipboard content cross-platform."""
        if IS_MAC:
            result = subprocess.run(["pbpaste"], capture_output=True, text=True)
            return result.stdout
        elif IS_WIN:
            ps_cmd = "Get-Clipboard"
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True
            )
            return result.stdout.strip()
        return ""

    # ─── Window Info ──────────────────────────────────────────────────────

    def get_frontmost_app(self) -> str:
        """Get currently active application name."""
        if IS_MAC:
            return self._applescript(
                'tell application "System Events" to get name of first '
                'application process whose frontmost is true'
            )
        elif IS_WIN:
            ps_cmd = (
                "Add-Type @'\n"
                "using System;\nusing System.Runtime.InteropServices;\n"
                "public class WinAPI { [DllImport(\"user32.dll\")] "
                "public static extern IntPtr GetForegroundWindow(); }\n'@\n"
                "$hwnd = [WinAPI]::GetForegroundWindow();\n"
                "(Get-Process | Where-Object { $_.MainWindowHandle -eq $hwnd }).ProcessName"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip()
        return ""

    def get_all_windows(self) -> list:
        """Get all visible windows."""
        if IS_MAC:
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
            result = self._applescript(script)
            return result.split(", ") if result else []
        elif IS_WIN:
            ps_cmd = (
                "Get-Process | Where-Object {$_.MainWindowTitle} | "
                "Select-Object ProcessName, MainWindowTitle | "
                "ForEach-Object { $_.ProcessName + ': ' + $_.MainWindowTitle }"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10
            )
            return [l for l in result.stdout.strip().split("\n") if l]
        return []

    # ─── AppleScript (macOS only) ─────────────────────────────────────────

    def _applescript(self, script: str) -> str:
        """Execute AppleScript. No-op on Windows."""
        if not IS_MAC:
            logger.debug("AppleScript called on non-Mac — skipped")
            return ""
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()

    # Keep public alias for any code that calls it directly
    def applescript(self, script: str) -> str:
        return self._applescript(script)

    def speak_text(self, text: str):
        """Emergency TTS via system — use mouth/tts.py instead."""
        if IS_MAC:
            subprocess.run(["say", text])
        elif IS_WIN:
            ps_cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{text}')"
            subprocess.run(["powershell", "-Command", ps_cmd], timeout=30)
