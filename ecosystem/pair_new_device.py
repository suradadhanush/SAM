"""
ECOSYSTEM — Pair a New Device (Phase 2, Telegram bridge)

Run this on the laptop to generate a one-time pairing QR code. Scanning it
opens Telegram directly to your SAM bot with the pairing token pre-filled
(via a t.me deep link), so pairing is a single scan-and-tap on the phone
side — no manual code typing needed.

Usage:
    python -m ecosystem.pair_new_device
"""

import sys
import logging

logging.basicConfig(level=logging.WARNING)  # keep terminal output clean for the QR


def main():
    from config.settings import Settings
    from ecosystem.device_registry import DeviceRegistry

    settings = Settings()
    bot_username = getattr(settings, "telegram_bot_username", "") or ""

    if not bot_username:
        print(
            "\nsettings.telegram_bot_username isn't set. Add it to settings.yaml "
            "(the @username of the bot you created with @BotFather, without the @).\n"
        )
        sys.exit(1)

    registry = DeviceRegistry()
    token = registry.create_pairing_token(channel="telegram")
    deep_link = f"https://t.me/{bot_username}?start={token}"

    print(f"\nPairing link (valid 10 minutes):\n  {deep_link}\n")

    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(deep_link)
        qr.make()

        # ASCII in the terminal — no image viewer needed, works over SSH/Termux too
        qr.print_ascii(invert=True)

        # Also save a PNG for anyone who'd rather scan from a screen/photo
        img = qr.make_image(fill_color="black", back_color="white")
        out_path = "sam_pairing_qr.png"
        img.save(out_path)
        print(f"\nAlso saved as {out_path} — open it and scan with your phone's camera.")
        print("Scanning opens Telegram and sends the pairing code automatically.\n")

    except ImportError:
        print("qrcode package not installed — run: pip install qrcode[pil]")
        print(f"You can still pair manually: open Telegram, message @{bot_username}, "
              f"and send:\n  /start {token}\n")


if __name__ == "__main__":
    main()
