"""
ECOSYSTEM — Telegram Bridge (Phase 2, internet-relay bridge)

Lets you send SAM commands from your phone via Telegram, with zero native
app and zero port-forwarding — the laptop long-polls Telegram's servers
outbound, so no inbound network config is needed at all.

=== IMPORTANT: this is NOT the local-WiFi Phase 2 ecosystem ===
Command text you send here passes through Telegram's servers to reach this
bridge (TLS-encrypted in transit, but readable server-side by Telegram —
this is a regular bot chat, not a Secret Chat). Your actual SAM data —
Founder Mode, memories, conversation history — never leaves the laptop;
only the live command text for THIS bridge touches Telegram. This was an
explicit, informed trade-off (see docs/PHASE_2_TELEGRAM_BRIDGE.md) to get
working remote control before a native Android app exists. True same-WiFi,
zero-third-party pairing is still the long-term plan.

=== Standalone process, on purpose ===
This does NOT run inside main.py's voice/text loop. It's a separate script
you run alongside SAM (`python -m ecosystem.telegram_bridge`), constructing
its own Brain/ReactLoop/FounderMode instances the same way main.py does.
Kept fully separate so nothing about the existing voice/text pipeline is
touched or risked by adding this.

=== Setup ===
1. Message @BotFather on Telegram, /newbot, follow the prompts, get a token.
2. Put that token in settings.yaml as telegram_bot_token, or set the
   TELEGRAM_BOT_TOKEN environment variable.
3. Run `python -m ecosystem.pair_new_device` to generate a pairing QR code.
4. Scan it with your phone's camera — opens Telegram, sends /start <token>
   to the bot automatically.
5. Run this bridge: `python -m ecosystem.telegram_bridge`
6. Message the bot from your phone. Only paired (trusted) chats get a
   response — everyone else gets a polite "not paired" message.
"""

import asyncio
import logging
from dataclasses import replace

logger = logging.getLogger("SAM.Ecosystem.Telegram")

NOT_PAIRED_MESSAGE = (
    "This device isn't paired with SAM yet. Ask the owner to run "
    "`python -m ecosystem.pair_new_device` and scan the QR code with this phone."
)


class TelegramBridge:
    def __init__(self, settings, registry=None):
        self.settings = settings
        self._task_lock = asyncio.Lock()  # ReactLoop/hands aren't built for concurrent tasks

        from ecosystem.device_registry import DeviceRegistry
        self.registry = registry or DeviceRegistry()

        # Same construction pattern as main.py's SAM.__init__ — a fully
        # separate set of instances, not shared with the voice/text process.
        from memory.identity import Identity
        from memory.retrieve import MemoryRetriever
        from founder_mode.manager import FounderModeManager
        from core.brain import Brain
        from agent.react_loop import ReactLoop

        self.identity = Identity()
        self.memory = MemoryRetriever()
        self.founder_mode = FounderModeManager(settings=settings)
        self.brain = Brain(settings)
        self.react_loop = ReactLoop(settings, founder_mode=self.founder_mode)

    # ─── Handlers ────────────────────────────────────────────────────────

    async def handle_start(self, update, context):
        """Handles /start and /start <token> — the pairing entrypoint."""
        chat_id = str(update.effective_chat.id)
        args = context.args if context.args else []

        if not args:
            await update.message.reply_text(
                "Hi — this is SAM. If you have a pairing code, send it as "
                "/start <code>, or scan the pairing QR code again."
            )
            return

        token = args[0]
        device_name = update.effective_chat.first_name or update.effective_chat.username or "Phone"
        success = self.registry.redeem_token(token, chat_id, device_name=device_name)

        if success:
            await update.message.reply_text(
                f"Paired! This device ({device_name}) can now send SAM commands here."
            )
            logger.info(f"Paired new device via Telegram: {device_name} ({chat_id})")
        else:
            await update.message.reply_text(
                "That pairing code is invalid or expired. Ask the owner to generate a new one."
            )

    async def handle_message(self, update, context):
        """Handles ordinary text messages from paired devices — routes
        through the exact same turn pipeline main.py uses."""
        chat_id = str(update.effective_chat.id)
        user_input = update.message.text

        if not self.registry.is_trusted(chat_id):
            await update.message.reply_text(NOT_PAIRED_MESSAGE)
            return

        self.registry.touch_last_active(chat_id)

        async with self._task_lock:
            await update.message.chat.send_action("typing")
            try:
                # Blocking Brain/ReactLoop calls run in a thread so we don't
                # freeze the bot's event loop for the ~10-30s a real task
                # can take (per your own PDR's latency numbers).
                final_text = await asyncio.to_thread(self._process_turn, user_input)
            except Exception as e:
                logger.error(f"Telegram turn processing failed: {e}", exc_info=True)
                final_text = f"I hit an error: {e}"

        await update.message.reply_text(final_text)

    def _process_turn(self, user_input: str) -> str:
        """
        Exact same pipeline as main.py's _process() — Session construction,
        Brain call, real execution via ReactLoop if an action is needed,
        memory save, Founder Mode capture. Intentionally duplicated rather
        than imported from main.py, since main.py's SAM class isn't built
        to be reused headlessly and refactoring it wasn't worth the risk
        just to share ~20 lines. If this drifts out of sync with main.py in
        the future, that's the trade-off — noted in the phase doc.
        """
        from core.session import Session

        session = Session(
            user_input=user_input,
            identity=self.identity.load(),
            memories=self.memory.retrieve(user_input, self.settings),
            founder_context=self.founder_mode.get_context(),
            settings=self.settings
        )

        response = self.brain.process(session)
        final_response = response

        if response.action and response.action not in (None, "none"):
            try:
                real_result_text = self.react_loop.run_planned_task(
                    task=user_input, brain=self.brain, session=session,
                    founder_context=session.founder_context,
                    initial_response=response
                )
                final_response = replace(response, text=real_result_text)
            except Exception as e:
                logger.error(f"Task execution failed: {e}", exc_info=True)
                final_response = replace(response, text=f"I tried to do that but hit an error: {e}")

        if not self.settings.incognito:
            session.save(user_input=user_input, response=final_response)
        self.founder_mode.capture_if_relevant(user_input, final_response)

        return final_response.text

    async def handle_devices_command(self, update, context):
        """/devices — lets a paired owner see what's trusted, from their phone."""
        chat_id = str(update.effective_chat.id)
        if not self.registry.is_trusted(chat_id):
            await update.message.reply_text(NOT_PAIRED_MESSAGE)
            return

        devices = self.registry.list_devices()
        if not devices:
            await update.message.reply_text("No trusted devices.")
            return

        lines = [f"• {d['device_name']} (paired {d['paired_at'][:10]})" for d in devices]
        await update.message.reply_text("Trusted devices:\n" + "\n".join(lines))

    # ─── Run ─────────────────────────────────────────────────────────────

    def run(self):
        from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

        token = getattr(self.settings, "telegram_bot_token", "") or ""
        if not token:
            raise RuntimeError(
                "No Telegram bot token set. Add telegram_bot_token to settings.yaml "
                "or set the TELEGRAM_BOT_TOKEN environment variable."
            )

        self.registry.cleanup_expired_tokens()

        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", self.handle_start))
        app.add_handler(CommandHandler("devices", self.handle_devices_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        logger.info("Telegram bridge starting (long-polling)...")
        app.run_polling()


def main():
    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    from config.settings import Settings
    settings = Settings()
    bridge = TelegramBridge(settings)
    bridge.run()


if __name__ == "__main__":
    main()
