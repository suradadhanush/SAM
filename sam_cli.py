#!/usr/bin/env python3
"""
SAM CLI — Control and management tool
Run: python sam_cli.py [command]

Commands:
  start         Start SAM
  status        Check SAM status
  stop          Stop SAM
  logs          Tail SAM logs
  memory        List recent memories
  founder       Show Founder Mode decisions
  skill list    List compiled skills
  decision      Add a manual decision to Founder Mode
  rejection     Add a manual rejection to Founder Mode
  export        Export Founder Mode decisions
"""

import sys
import json
import argparse
from pathlib import Path


def cmd_start():
    """Start SAM."""
    import subprocess
    subprocess.Popen(["python3", "main.py"])
    print("SAM starting...")


def cmd_status():
    """Check if SAM/Ollama is running."""
    import requests
    import subprocess

    # Check Ollama
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"✅ Ollama running. Models: {', '.join(models)}")
    except Exception:
        print("❌ Ollama not running. Start with: ollama serve")

    # Check SAM process
    result = subprocess.run(["pgrep", "-f", "main.py"], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ SAM running (PID: {result.stdout.strip()})")
    else:
        print("❌ SAM not running. Start with: python main.py")


def cmd_logs(lines: int = 50):
    """Show recent SAM logs."""
    import subprocess
    subprocess.run(["tail", f"-{lines}", "logs/sam.log"])


def cmd_memory(limit: int = 10):
    """Show recent memories."""
    import sqlite3
    db_path = Path("memory/store/episodic.db")
    if not db_path.exists():
        print("No memory database found. Run SAM first.")
        return

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT timestamp, user_input, response FROM episodes ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()

    if not rows:
        print("No memories yet.")
        return

    print(f"\n{'='*60}")
    print(f"RECENT MEMORIES ({len(rows)} episodes)")
    print(f"{'='*60}")
    for ts, user, resp in rows:
        print(f"\n[{ts[:19]}]")
        print(f"You: {user[:100]}")
        print(f"SAM: {resp[:100]}")


def cmd_founder(limit: int = 20):
    """Show Founder Mode decisions and taste profile."""
    import sqlite3
    db_path = Path("founder_mode/store/founder_mode.db")
    if not db_path.exists():
        print("No Founder Mode data yet.")
        return

    with sqlite3.connect(db_path) as conn:
        decisions = conn.execute(
            "SELECT timestamp, category, decision, reasoning FROM decisions ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()

        taste = conn.execute(
            "SELECT domain, preference FROM taste_profile ORDER BY updated_at DESC"
        ).fetchall()

        rejections = conn.execute(
            "SELECT timestamp, category, what_was_rejected, why FROM rejections ORDER BY id DESC LIMIT 10"
        ).fetchall()

    print(f"\n{'='*60}")
    print("FOUNDER MODE — DECISIONS")
    print(f"{'='*60}")
    for ts, cat, dec, reason in decisions:
        print(f"\n[{ts[:19]}] [{cat}]")
        print(f"Decision: {dec}")
        print(f"Because: {reason}")

    print(f"\n{'='*60}")
    print("TASTE PROFILE")
    print(f"{'='*60}")
    for domain, pref in taste:
        print(f"  [{domain}] {pref}")

    print(f"\n{'='*60}")
    print("REJECTIONS")
    print(f"{'='*60}")
    for ts, cat, what, why in rejections:
        print(f"\n[{ts[:19]}] [{cat}]")
        print(f"Rejected: {what}")
        print(f"Because: {why}")


def cmd_skills():
    """List compiled skills."""
    import sqlite3
    db_path = Path("skills/skills.db")
    if not db_path.exists():
        print("No skills compiled yet.")
        return

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT skill_name, task_pattern, success_count FROM skill_candidates WHERE compiled=1"
        ).fetchall()

    if not rows:
        print("No compiled skills yet. Skills compile after 3 successful completions.")
        return

    print(f"\n{'='*60}")
    print(f"COMPILED SKILLS ({len(rows)} total)")
    print(f"{'='*60}")
    for name, pattern, uses in rows:
        print(f"\n  {name}")
        print(f"  Pattern: {pattern}")
        print(f"  Uses: {uses}")


def cmd_decision(decision: str, reasoning: str, category: str = "general"):
    """Manually add a decision to Founder Mode."""
    sys.path.insert(0, str(Path(__file__).parent))
    from founder_mode.manager import FounderModeManager
    fm = FounderModeManager()
    fm.capture_decision(decision, reasoning, category)
    print(f"✅ Decision saved: {decision[:60]}")


def cmd_rejection(what: str, why: str, category: str = "general"):
    """Manually add a rejection to Founder Mode."""
    sys.path.insert(0, str(Path(__file__).parent))
    from founder_mode.manager import FounderModeManager
    fm = FounderModeManager()
    fm.capture_rejection(what, why, category)
    print(f"✅ Rejection saved: {what[:60]}")


def cmd_export():
    """Export Founder Mode to JSON."""
    sys.path.insert(0, str(Path(__file__).parent))
    from founder_mode.manager import FounderModeManager
    fm = FounderModeManager()
    path = fm.export()
    print(f"✅ Exported to: {path}")


def main():
    parser = argparse.ArgumentParser(description="SAM CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("start")
    subparsers.add_parser("status")

    logs_p = subparsers.add_parser("logs")
    logs_p.add_argument("--lines", type=int, default=50)

    mem_p = subparsers.add_parser("memory")
    mem_p.add_parser("memory")
    mem_p.add_argument("--limit", type=int, default=10)

    subparsers.add_parser("founder")
    subparsers.add_parser("skills")
    subparsers.add_parser("export")

    dec_p = subparsers.add_parser("decision")
    dec_p.add_argument("decision")
    dec_p.add_argument("reasoning")
    dec_p.add_argument("--category", default="general")

    rej_p = subparsers.add_parser("rejection")
    rej_p.add_argument("what")
    rej_p.add_argument("why")
    rej_p.add_argument("--category", default="general")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start()
    elif args.command == "status":
        cmd_status()
    elif args.command == "logs":
        cmd_logs(args.lines)
    elif args.command == "memory":
        cmd_memory(args.limit if hasattr(args, 'limit') else 10)
    elif args.command == "founder":
        cmd_founder()
    elif args.command == "skills":
        cmd_skills()
    elif args.command == "export":
        cmd_export()
    elif args.command == "decision":
        cmd_decision(args.decision, args.reasoning, args.category)
    elif args.command == "rejection":
        cmd_rejection(args.what, args.why, args.category)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
