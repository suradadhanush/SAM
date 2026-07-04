"""
THE EARS — Part 3: Text Input
For when the user can't speak out loud.
Runs in a separate thread alongside the wake word listener.
Type anything and press Enter — SAM processes it exactly like voice.
Type 'voice mode' to switch back to voice.
"""

import logging
import threading
from typing import Callable

logger = logging.getLogger("SAM.TextInput")


class TextInputListener:
    def __init__(self, callback: Callable, mode_switch_callback: Callable = None):
        self.callback = callback
        self.mode_switch_callback = mode_switch_callback
        self._running = False
        self._thread = None

    def _listen_loop(self):
        print("\n" + "="*50)
        print("SAM TEXT MODE")
        print("Type your message and press ENTER")
        print("Type 'voice mode' to switch to voice")
        print("Type 'quit' to exit SAM")
        print("="*50 + "\n")

        while self._running:
            try:
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                if user_input.lower() == "quit":
                    self._running = False
                    break

                if user_input.lower() in ["voice mode", "switch to voice", "use voice"]:
                    print("[SAM] Switching to voice mode...")
                    if self.mode_switch_callback:
                        self.mode_switch_callback("voice")
                    break

                # Fire callback with the text input
                threading.Thread(
                    target=self.callback,
                    args=(user_input,),
                    daemon=True
                ).start()

            except (EOFError, KeyboardInterrupt):
                break

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def join(self):
        if self._thread:
            self._thread.join()
