"""
Offline smoke test for Phase 2 (Telegram bridge) — no live bot token or
network required. Tests the device registry's full pairing lifecycle and
all Telegram handlers using mocked Update/Context objects.

Usage:
    HOME=/tmp/sam_smoke_test_phase2 python3 tests/test_phase2_telegram_offline.py
"""

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings  # noqa: E402
from ecosystem.device_registry import DeviceRegistry  # noqa: E402
from ecosystem.telegram_bridge import TelegramBridge, NOT_PAIRED_MESSAGE  # noqa: E402

results = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    results.append(condition)
    print(f"[{status}] {label}")


def make_update(chat_id, text=None, args=None):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_chat.first_name = "TestUser"
    update.effective_chat.username = "testuser"
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    context = MagicMock()
    context.args = args or []
    return update, context


def test_device_registry():
    reg = DeviceRegistry()

    token = reg.create_pairing_token()
    check("Wrong token rejected", reg.redeem_token("wrong-token", "chat123", "Test Phone") is False)
    check("Correct token accepted", reg.redeem_token(token, "chat123", "Test Phone") is True)
    check("Reused token rejected", reg.redeem_token(token, "chat456", "Another Phone") is False)
    check("Trust check: paired device", reg.is_trusted("chat123") is True)
    check("Trust check: unknown device", reg.is_trusted("chat999") is False)

    devices = reg.list_devices()
    check("Device listed correctly", len(devices) == 1 and devices[0]["device_name"] == "Test Phone")

    dev_id = devices[0]["id"]
    check("Revoke succeeds", reg.revoke(dev_id) is True)
    check("Revoked device no longer trusted", reg.is_trusted("chat123") is False)

    import ecosystem.device_registry as dr_module
    old_ttl = dr_module.PAIRING_TOKEN_TTL_MINUTES
    dr_module.PAIRING_TOKEN_TTL_MINUTES = -1
    short_token = reg.create_pairing_token()
    check("Expired token rejected", reg.redeem_token(short_token, "chat789", "Slow Phone") is False)
    dr_module.PAIRING_TOKEN_TTL_MINUTES = old_ttl


async def test_bridge_handlers():
    settings = Settings()
    registry = DeviceRegistry()
    bridge = TelegramBridge(settings, registry=registry)

    update, context = make_update("111", args=[])
    await bridge.handle_start(update, context)
    check("/start with no args asks for a code",
          "pairing code" in update.message.reply_text.call_args[0][0].lower())

    update, context = make_update("111", args=["bogus-token"])
    await bridge.handle_start(update, context)
    check("/start with bad token rejected",
          "invalid or expired" in update.message.reply_text.call_args[0][0].lower())
    check("Bad token did not trust the device", not registry.is_trusted("111"))

    real_token = registry.create_pairing_token()
    update, context = make_update("222", args=[real_token])
    await bridge.handle_start(update, context)
    check("/start with real token succeeds",
          "paired" in update.message.reply_text.call_args[0][0].lower())
    check("Device now trusted", registry.is_trusted("222"))

    update, context = make_update("999", text="do something")
    await bridge.handle_message(update, context)
    check("Untrusted chat refused", update.message.reply_text.call_args[0][0] == NOT_PAIRED_MESSAGE)

    update, context = make_update("222", text="what time is it")
    with patch.object(bridge, "_process_turn", return_value="It's some time."):
        await bridge.handle_message(update, context)
    check("Trusted chat gets real response",
          update.message.reply_text.call_args[0][0] == "It's some time.")
    check("Typing indicator sent", update.message.chat.send_action.called)

    update, context = make_update("222", text="crash please")
    with patch.object(bridge, "_process_turn", side_effect=RuntimeError("boom")):
        await bridge.handle_message(update, context)
    check("Exception in turn processing reported gracefully",
          "hit an error" in update.message.reply_text.call_args[0][0].lower())

    update, context = make_update("222", args=[])
    await bridge.handle_devices_command(update, context)
    check("/devices lists trusted devices", "TestUser" in update.message.reply_text.call_args[0][0])

    update, context = make_update("888", args=[])
    await bridge.handle_devices_command(update, context)
    check("/devices refused for untrusted chat",
          update.message.reply_text.call_args[0][0] == NOT_PAIRED_MESSAGE)


def main():
    test_device_registry()
    asyncio.run(test_bridge_handlers())

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)
    print("Phase 2 (Telegram bridge) offline logic verified.")


if __name__ == "__main__":
    main()
