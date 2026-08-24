"""``hermes handoffs`` — read the bot handoff ledger from a shell.

The ledger (``tools/bot_handoffs.py``) records every ``message_agent``
delivery as an addressable work item: who asked whom, over which transport,
and which background process owns the reply. This command is the read side —
"who owes whom what" as one command instead of hand-reading JSONL.

    hermes handoffs list            # oldest first, human-readable
    hermes handoffs list --json     # machine-readable
    hermes handoffs list --to dixie # filter by target
    hermes handoffs sweep           # drop records past the relay staleness clock

Read-only by default; the only mutating action is ``sweep``, which applies the
same staleness rule the gateway housekeeping loop already runs hourly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_LEDGER_HELP = (
    "Bot handoff ledger — addressable work items for agent-to-agent DMs"
)


def _resolve_root(args) -> Path:
    """Explicit --root wins; else HERMES_HOME's install root."""
    explicit = getattr(args, "root", None)
    if explicit:
        p = Path(explicit)
        return p.parent.parent if p.parent.name == "profiles" else p
    import os

    home = Path(os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes"))
    return home.parent.parent if home.parent.name == "profiles" else home


def _fmt_age(at: int, now: float) -> str:
    delta = max(0, int(now - at))
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def cmd_handoffs(args) -> int:
    """Entry point for ``hermes handoffs <action>``."""
    from tools.bot_handoffs import read_handoffs, sweep_handoffs

    action = getattr(args, "handoffs_action", None) or "list"
    root = _resolve_root(args)

    if action == "sweep":
        removed = sweep_handoffs(root)
        print(f"Swept {removed} stale handoff record(s).")
        return 0

    if action != "list":
        print(f"Unknown handoffs action: {action!r}", file=sys.stderr)
        return 2

    records = read_handoffs(root)
    target_filter = (getattr(args, "to", None) or "").strip().lstrip("@").lower()
    if target_filter:
        records = [r for r in records if r.get("to", "").lower() == target_filter]

    import time

    now = time.time()

    if getattr(args, "json", False):
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0

    if not records:
        where = f" to '{target_filter}'" if target_filter else ""
        print(f"No handoffs{where}. Send one with message_agent and it lands here.")
        return 0

    print(f"{'id':18s} {'age':>5s}  {'from':16s} {'to':20s} {'transport':9s} process")
    print("-" * 88)
    for rec in records:
        hid = str(rec.get("id") or "?")
        age = _fmt_age(int(rec.get("at") or 0), now)
        # Truncate so wide profile names cannot push the columns apart.
        sender = str(rec.get("from") or "?")[:16]
        to = str(rec.get("to") or "?")[:20]
        transport = str(rec.get("transport") or "?")[:9]
        proc = str(rec.get("process_id") or "-")
        extra = ""
        if rec.get("envelope_id"):
            extra = f" envelope:{str(rec['envelope_id'])[:12]}"
        print(f"{hid:18s} {age:>5s}  {sender:16s} {to:20s} {transport:9s} {proc}{extra}")
    print(f"\n{len(records)} record(s)" + (f" → '{target_filter}'" if target_filter else ""))
    return 0


def build_handoffs_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "handoffs",
        help=_LEDGER_HELP,
        description=(
            "Inspect the bot handoff ledger: every message_agent delivery as an "
            "addressable work item (who asked whom, over which transport, which "
            "background process owns the reply). Read-only except 'sweep', "
            "which drops records past the relay staleness clock."
        ),
        epilog=(
            "Examples:\n"
            "  hermes handoffs list\n"
            "  hermes handoffs list --to dixie\n"
            "  hermes handoffs list --json\n"
            "  hermes handoffs sweep\n"
            "\n"
            "Exit codes: 0 ok, 2 usage error."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        default="",
        help="Install root override (default: HERMES_HOME's install root)",
    )
    handoffs_sub = parser.add_subparsers(dest="handoffs_action")

    list_p = handoffs_sub.add_parser("list", aliases=["ls"], help="List handoff records (oldest first)")
    # SUPPRESS on the subparser side: argparse subparser defaults would
    # otherwise CLOBBER values the user set before the action word
    # (`hermes handoffs --json list` silently ran non-JSON). With SUPPRESS the
    # subparser only writes these attrs when actually given; the parent's
    # defaults below still apply when neither form sets them.
    list_p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit records as JSON")
    list_p.add_argument("--to", default=argparse.SUPPRESS, help="Filter by target agent name")

    handoffs_sub.add_parser("sweep", help="Drop records older than the relay staleness clock")

    # Top-level flags when no action is given.
    parser.add_argument("--json", dest="json", action="store_true", default=False, help=argparse.SUPPRESS)
    parser.add_argument("--to", dest="to", default="", help=argparse.SUPPRESS)

    parser.set_defaults(func=cmd_handoffs)
