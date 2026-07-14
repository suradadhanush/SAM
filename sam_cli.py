#!/usr/bin/env python3
"""
SAM CLI — Control, management, and profile portability
Usage: python sam_cli.py [command]

Commands:
  status              Check SAM + Ollama status
  logs                Tail SAM logs
  memory              Show recent memories
  founder             Show Founder Mode decisions + taste (--all for superseded/rejected too)
  founder-review      Confirm or reject LLM auto-captured entries
  skills              List compiled skills
  decision            Add a decision to Founder Mode
  rejection           Add a rejection to Founder Mode
  export              Export Founder Mode to JSON
  export-profile      Package full SAM profile for moving to new system
  import-profile      Restore SAM profile on a new system
  sync-status         Show what's in your current profile
  reset-memory        Wipe memory only (keeps identity + founder mode)
  reset-all           Full reset (keeps nothing — fresh start)
"""

import sys
import json
import shutil
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

SAM_DATA_DIR = Path.home() / ".sam_data"


# ─── Status ───────────────────────────────────────────────────────────────

def cmd_status():
    import requests
    import subprocess

    print("\n── SAM STATUS ──────────────────────────────")

    # Ollama
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"✅ Ollama running")
        print(f"   Models: {', '.join(models)}")
    except Exception:
        print("❌ Ollama not running → start with: ollama serve")

    # SAM process
    result = subprocess.run(["pgrep", "-f", "main.py"], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ SAM running (PID: {result.stdout.strip()})")
    else:
        print("❌ SAM not running → python main.py")

    # Data dir
    if SAM_DATA_DIR.exists():
        print(f"✅ Profile at {SAM_DATA_DIR}")
    else:
        print(f"⚠️  No profile yet — will be created on first run")

    print("────────────────────────────────────────────\n")


# ─── Logs ─────────────────────────────────────────────────────────────────

def cmd_logs(lines: int = 50):
    import subprocess
    log_path = SAM_DATA_DIR / "logs" / "sam.log"
    if not log_path.exists():
        print("No logs yet.")
        return
    subprocess.run(["tail", f"-{lines}", str(log_path)])


# ─── Memory ───────────────────────────────────────────────────────────────

def cmd_memory(limit: int = 10):
    db_path = SAM_DATA_DIR / "memory" / "episodic.db"
    if not db_path.exists():
        print("No memory yet. Run SAM first.")
        return

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT timestamp, user_input, response FROM episodes ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()

    if not rows:
        print("No episodes yet.")
        return

    print(f"\n── RECENT MEMORY ({len(rows)} episodes) ──────────")
    for ts, user, resp in rows:
        print(f"\n[{ts[:19]}]")
        print(f"You: {user[:120]}")
        print(f"SAM: {resp[:120]}")
    print()


# ─── Founder Mode ─────────────────────────────────────────────────────────

def _conf_tag(conf) -> str:
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return ""
    if c >= 0.8:
        return "high"
    elif c >= 0.5:
        return "moderate"
    else:
        return "low/guess"


def cmd_founder(show_all: bool = False):
    db_path = SAM_DATA_DIR / "founder_mode" / "founder_mode.db"
    if not db_path.exists():
        print("No Founder Mode data yet.")
        return

    status_filter = "" if show_all else "WHERE (status IS NULL OR status = 'active')"

    with sqlite3.connect(db_path) as conn:
        decisions = conn.execute(
            f"SELECT timestamp, category, decision, reasoning, confidence, source, status FROM decisions "
            f"{status_filter} ORDER BY id DESC LIMIT 20"
        ).fetchall()
        taste = conn.execute(
            f"SELECT domain, preference, confidence, source, status FROM taste_profile "
            f"{status_filter} ORDER BY updated_at DESC"
        ).fetchall()
        rejections = conn.execute(
            f"SELECT timestamp, category, what_was_rejected, why, confidence, source, status FROM rejections "
            f"{status_filter} ORDER BY id DESC LIMIT 10"
        ).fetchall()

    print(f"\n── DECISIONS ({len(decisions)}) ───────────────────────")
    for ts, cat, dec, reason, conf, source, status in decisions:
        tag = f" [{_conf_tag(conf)} conf, {source or 'manual'}]" if source else ""
        status_note = f" ({status})" if status and status != "active" else ""
        print(f"\n[{ts[:19]}] [{cat}]{tag}{status_note}")
        print(f"  {dec}")
        print(f"  Because: {reason}")

    print(f"\n── TASTE PROFILE ({len(taste)}) ──────────────────────")
    for domain, pref, conf, source, status in taste:
        tag = f" [{_conf_tag(conf)} conf, {source or 'manual'}]" if source else ""
        status_note = f" ({status})" if status and status != "active" else ""
        print(f"  [{domain}] {pref}{tag}{status_note}")

    print(f"\n── REJECTIONS ({len(rejections)}) ────────────────────")
    for ts, cat, what, why, conf, source, status in rejections:
        tag = f" [{_conf_tag(conf)} conf, {source or 'manual'}]" if source else ""
        status_note = f" ({status})" if status and status != "active" else ""
        print(f"\n[{ts[:19]}] [{cat}]{tag}{status_note}")
        print(f"  Rejected: {what[:100]}")
        print(f"  Because: {why[:100]}")
    print(f"\n(Run 'founder --all' to include superseded/rejected entries)")
    print()


def cmd_devices():
    from ecosystem.device_registry import DeviceRegistry
    registry = DeviceRegistry()
    registry.cleanup_expired_tokens()
    devices = registry.list_devices()

    if not devices:
        print("No trusted devices. Run 'python -m ecosystem.pair_new_device' to pair one.")
        return

    print(f"\n── TRUSTED DEVICES ({len(devices)}) ──────────────────")
    for d in devices:
        last_active = d["last_active"][:19] if d["last_active"] else "never"
        print(f"  [{d['id']}] {d['device_name']} ({d['channel']}) — "
              f"paired {d['paired_at'][:10]}, last active {last_active}")
    print()


def cmd_revoke_device(device_id: int):
    from ecosystem.device_registry import DeviceRegistry
    registry = DeviceRegistry()
    if registry.revoke(device_id):
        print(f"Device {device_id} revoked — it can no longer send SAM commands.")
    else:
        print(f"No trusted device with id {device_id} found.")



def cmd_founder_review():
    """Walk through LLM-auto-captured entries below full confidence and
    let the user confirm (bump to 1.0) or reject (exclude from context)."""
    sys.path.insert(0, str(Path(__file__).parent))
    from founder_mode.manager import FounderModeManager
    mgr = FounderModeManager()

    captures = mgr.list_llm_captures()
    if not captures:
        print("Nothing to review — no unconfirmed LLM auto-captures.")
        return

    print(f"\n── FOUNDER MODE REVIEW ({len(captures)} to review) ──")
    print("For each: [y] confirm  [n] reject  [s] skip  [q] quit\n")

    for c in captures:
        conf_pct = f"{float(c['confidence']) * 100:.0f}%" if c["confidence"] is not None else "?"
        print(f"[{c['table']}] ({conf_pct} confidence)")
        print(f"  {c['label'][:150]}")
        choice = input("  y/n/s/q: ").strip().lower()

        if choice == "q":
            break
        elif choice == "y":
            mgr.confirm_capture(c["table"], c["id"])
            print("  ✅ Confirmed.\n")
        elif choice == "n":
            mgr.reject_capture(c["table"], c["id"])
            print("  ❌ Rejected — excluded from Founder Mode context.\n")
        else:
            print("  ⏭️  Skipped.\n")


# ─── Skills ───────────────────────────────────────────────────────────────

def cmd_license():
    from licensing.license_manager import LicenseManager, LicenseStatus
    mgr = LicenseManager()
    status, message, lic = mgr.check()

    print(f"\n── LICENSE STATUS ──────────────────────")
    print(f"  Status: {status}")
    print(f"  {message}")
    if lic:
        print(f"  Edition: {lic.product_edition}")
        print(f"  Issued: {lic.issue_date[:10]}")
        print(f"  {'Lifetime (never expires)' if lic.is_lifetime else f'Expires: {lic.expiry_date[:10]}'}")
    if status == LicenseStatus.NO_LICENSE:
        print(f"\n  Running unlicensed — this is fine for now (non-blocking, per current settings).")
        print(f"  Install one with: python sam_cli.py activate <license_file.json>")
    print()


def cmd_activate(license_file: str):
    from licensing.license_manager import LicenseManager
    mgr = LicenseManager()
    ok, message = mgr.install_license(license_file)
    print(f"\n{'✅' if ok else '❌'} {message}\n")



    db_path = SAM_DATA_DIR / "skills" / "skills.db"
    if not db_path.exists():
        print("No compiled skills yet.")
        return

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT skill_name, task_pattern, success_count FROM skill_candidates WHERE compiled=1"
        ).fetchall()

    if not rows:
        print("No compiled skills yet. Skills compile after 3 successful completions.")
        return

    print(f"\n── COMPILED SKILLS ({len(rows)}) ─────────────────────")
    for name, pattern, uses in rows:
        print(f"\n  {name}")
        print(f"  Pattern: {pattern}")
        print(f"  Uses: {uses}")
    print()


# ─── Founder Mode Actions ─────────────────────────────────────────────────

def cmd_decision(decision: str, reasoning: str, category: str = "general"):
    sys.path.insert(0, str(Path(__file__).parent))
    from founder_mode.manager import FounderModeManager
    FounderModeManager().capture_decision(decision, reasoning, category)
    print(f"✅ Decision saved: {decision[:80]}")


def cmd_rejection(what: str, why: str, category: str = "general"):
    sys.path.insert(0, str(Path(__file__).parent))
    from founder_mode.manager import FounderModeManager
    FounderModeManager().capture_rejection(what, why, category)
    print(f"✅ Rejection saved: {what[:80]}")


def cmd_export():
    sys.path.insert(0, str(Path(__file__).parent))
    from founder_mode.manager import FounderModeManager
    path = FounderModeManager().export()
    print(f"✅ Exported to: {path}")


# ─── Profile Portability ──────────────────────────────────────────────────

def cmd_export_profile():
    """Package full ~/.sam_data into a portable zip."""
    if not SAM_DATA_DIR.exists():
        print("No profile found. Run SAM first to create one.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_name = f"sam_profile_{timestamp}"
    export_path = Path.home() / f"{export_name}.zip"

    print(f"Packaging profile from {SAM_DATA_DIR}...")
    shutil.make_archive(str(Path.home() / export_name), "zip", SAM_DATA_DIR)

    size_mb = export_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ Profile exported: {export_path}")
    print(f"   Size: {size_mb:.1f} MB")
    print(f"\nTo move to a new system:")
    print(f"  1. Copy {export_path.name} to the new machine")
    print(f"  2. Run: python sam_cli.py import-profile {export_path.name}")


def cmd_import_profile(zip_path: str):
    """Restore a SAM profile from a zip on a new system."""
    zip_file = Path(zip_path)
    if not zip_file.exists():
        print(f"File not found: {zip_path}")
        return

    if SAM_DATA_DIR.exists():
        # Backup existing before overwriting
        backup = Path(str(SAM_DATA_DIR) + f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.move(str(SAM_DATA_DIR), str(backup))
        print(f"Existing profile backed up to: {backup}")

    SAM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(zip_path, str(SAM_DATA_DIR))

    print(f"\n✅ Profile imported from {zip_path}")
    print(f"   SAM now knows you. Run: python main.py")


def cmd_sync_status():
    """Show what's in the current profile."""
    if not SAM_DATA_DIR.exists():
        print("No profile yet.")
        return

    print(f"\n── PROFILE STATUS ──────────────────────────")
    print(f"Location: {SAM_DATA_DIR}")

    # Identity
    identity_path = SAM_DATA_DIR / "identity.json"
    if identity_path.exists():
        with open(identity_path) as f:
            identity = json.load(f)
        print(f"\n✅ Identity: {identity.get('name', 'Unknown')}")
        print(f"   Assistant name: {identity.get('assistant_name', 'SAM')}")
    else:
        print("\n❌ No identity file")

    # Memory
    db_path = SAM_DATA_DIR / "memory" / "episodic.db"
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        print(f"\n✅ Episodic memory: {count} conversations")
    else:
        print("\n❌ No episodic memory")

    # ChromaDB
    chroma_path = SAM_DATA_DIR / "memory" / "chroma"
    if chroma_path.exists():
        print(f"✅ Semantic memory: present")
    else:
        print("❌ No semantic memory")

    # Founder Mode
    fm_db = SAM_DATA_DIR / "founder_mode" / "founder_mode.db"
    if fm_db.exists():
        with sqlite3.connect(fm_db) as conn:
            d_count = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            r_count = conn.execute("SELECT COUNT(*) FROM rejections").fetchone()[0]
            t_count = conn.execute("SELECT COUNT(*) FROM taste_profile").fetchone()[0]
        print(f"\n✅ Founder Mode:")
        print(f"   {d_count} decisions | {r_count} rejections | {t_count} taste entries")
    else:
        print("\n❌ No Founder Mode data")

    # Skills
    skills_dir = SAM_DATA_DIR / "skills" / "compiled"
    if skills_dir.exists():
        skill_count = len(list(skills_dir.glob("*.json")))
        print(f"\n✅ Compiled skills: {skill_count}")
    else:
        print("\n❌ No compiled skills")

    # Size
    total_size = sum(f.stat().st_size for f in SAM_DATA_DIR.rglob("*") if f.is_file())
    print(f"\n   Total profile size: {total_size / (1024*1024):.1f} MB")
    print("────────────────────────────────────────────\n")


# ─── Reset ────────────────────────────────────────────────────────────────

def cmd_reset_memory():
    """Wipe memory only. Keeps identity and Founder Mode."""
    confirm = input("Wipe all memory? Identity and Founder Mode kept. (yes/no): ")
    if confirm.lower() != "yes":
        print("Cancelled.")
        return

    db_path = SAM_DATA_DIR / "memory" / "episodic.db"
    chroma_path = SAM_DATA_DIR / "memory" / "chroma"

    if db_path.exists():
        db_path.unlink()
        print("✅ Episodic memory wiped")

    if chroma_path.exists():
        shutil.rmtree(chroma_path)
        print("✅ Semantic memory wiped")

    print("Memory reset. Founder Mode and identity intact.")


def cmd_reset_all():
    """Full reset — wipes everything in ~/.sam_data."""
    confirm = input("⚠️  FULL RESET — wipes ALL data including Founder Mode. Type 'RESET' to confirm: ")
    if confirm != "RESET":
        print("Cancelled.")
        return

    backup = Path(str(SAM_DATA_DIR) + f"_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.move(str(SAM_DATA_DIR), str(backup))
    print(f"✅ Full reset done. Backup at: {backup}")
    print("SAM will start fresh on next run.")


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SAM CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status")
    founder_p = subparsers.add_parser("founder")
    founder_p.add_argument("--all", action="store_true", dest="show_all",
                            help="Include superseded/rejected entries")
    subparsers.add_parser("founder-review")
    subparsers.add_parser("devices")
    revoke_p = subparsers.add_parser("revoke-device")
    revoke_p.add_argument("device_id", type=int)
    subparsers.add_parser("skills")
    subparsers.add_parser("export")
    subparsers.add_parser("export-profile")
    subparsers.add_parser("sync-status")
    subparsers.add_parser("reset-memory")
    subparsers.add_parser("reset-all")

    subparsers.add_parser("license")
    activate_p = subparsers.add_parser("activate")
    activate_p.add_argument("license_file")

    logs_p = subparsers.add_parser("logs")
    logs_p.add_argument("--lines", type=int, default=50)

    mem_p = subparsers.add_parser("memory")
    mem_p.add_argument("--limit", type=int, default=10)

    dec_p = subparsers.add_parser("decision")
    dec_p.add_argument("decision")
    dec_p.add_argument("reasoning")
    dec_p.add_argument("--category", default="general")

    rej_p = subparsers.add_parser("rejection")
    rej_p.add_argument("what")
    rej_p.add_argument("why")
    rej_p.add_argument("--category", default="general")

    imp_p = subparsers.add_parser("import-profile")
    imp_p.add_argument("zip_path")

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "skills": cmd_skills,
        "export": cmd_export,
        "export-profile": cmd_export_profile,
        "sync-status": cmd_sync_status,
        "reset-memory": cmd_reset_memory,
        "reset-all": cmd_reset_all,
        "founder-review": cmd_founder_review,
        "devices": cmd_devices,
        "license": cmd_license,
    }

    if args.command in commands:
        commands[args.command]()
    elif args.command == "activate":
        cmd_activate(args.license_file)
    elif args.command == "revoke-device":
        cmd_revoke_device(args.device_id)
    elif args.command == "founder":
        cmd_founder(show_all=getattr(args, "show_all", False))
    elif args.command == "logs":
        cmd_logs(args.lines)
    elif args.command == "memory":
        cmd_memory(args.limit)
    elif args.command == "decision":
        cmd_decision(args.decision, args.reasoning, args.category)
    elif args.command == "rejection":
        cmd_rejection(args.what, args.why, args.category)
    elif args.command == "import-profile":
        cmd_import_profile(args.zip_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
