"""
THE HANDS — Terminal Runner
Executes shell commands via Python subprocess.
Sandboxed — dangerous commands blocked.
"""

import logging
import subprocess
import shlex
from typing import Optional

logger = logging.getLogger("SAM.Terminal")

# Commands that are never executed regardless of context
BLOCKED_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "dd if=",
    "mkfs",
    ":(){ :|:& };:",  # Fork bomb
    "sudo rm",
    "chmod -R 777 /",
    "> /dev/sda",
    "format",
]

REQUIRES_CONFIRMATION = [
    "rm ", "rmdir", "mv ", "sudo", "pip uninstall",
    "brew uninstall", "kill", "killall"
]


class TerminalRunner:
    def __init__(self, working_dir: str = None, allow_risky: bool = False):
        import os
        self._working_dir = working_dir or os.path.expanduser("~")
        self._history = []
        # Phase: main.py execution wiring. REQUIRES_CONFIRMATION existed
        # before but was never actually checked anywhere — only
        # BLOCKED_COMMANDS was enforced. Now that SAM can execute terminal
        # actions autonomously from a conversation turn (not just when you
        # manually call run_task), this needs to be a real gate, not a
        # dormant list. Default is False — risky commands are refused with
        # a clear message rather than run silently. Opt in via
        # settings.allow_risky_terminal_commands if you want them enabled.
        self._allow_risky = allow_risky

    def run(self, command: str, description: str = "") -> str:
        """
        Execute a shell command and return output.
        Returns stdout + stderr as combined string.
        """
        if not command or not command.strip():
            return "No command provided"

        # Safety check
        safety_result = self._check_safety(command)
        if safety_result:
            return safety_result

        logger.info(f"Running command: {command}")
        if description:
            logger.info(f"Purpose: {description}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self._working_dir
            )

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"

            if result.returncode != 0:
                output += f"\nExit code: {result.returncode}"

            self._history.append({
                "command": command,
                "output": output[:500],
                "returncode": result.returncode
            })

            logger.info(f"Command output: {output[:200]}")
            return output.strip() or f"Command completed (exit code: {result.returncode})"

        except subprocess.TimeoutExpired:
            return "Command timed out after 60 seconds"
        except Exception as e:
            logger.error(f"Terminal error: {e}")
            return f"Error running command: {e}"

    def _check_safety(self, command: str) -> Optional[str]:
        """Check if command is safe to run. Returns error string if blocked."""
        cmd_lower = command.lower().strip()

        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                logger.warning(f"BLOCKED dangerous command: {command}")
                return f"Blocked: This command ({blocked}) is not allowed for safety reasons."

        if not self._allow_risky:
            for risky in REQUIRES_CONFIRMATION:
                if risky in cmd_lower:
                    logger.warning(f"Refused risky command (needs manual confirmation): {command}")
                    return (
                        f"I didn't run this automatically because it needs manual confirmation: "
                        f"'{command}'. Run it yourself, or enable allow_risky_terminal_commands "
                        f"in settings if you want SAM to run this class of command on its own."
                    )

        return None

    def get_current_directory(self) -> str:
        return self.run("pwd")

    def list_files(self, path: str = ".") -> str:
        return self.run(f"ls -la {path}")

    def read_file(self, path: str) -> str:
        return self.run(f"cat {path}")

    def get_history(self) -> list:
        return self._history

    def set_working_dir(self, path: str):
        self._working_dir = path
