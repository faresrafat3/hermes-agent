"""Bot handoff ledger — work-item identity for agent-to-agent DMs.

Every ``message_agent`` delivery appends one line here: who asked whom for
what, over which transport, and which background process owns the reply.
Before this, a DM left behind only a deleted temp file and a dangling
``process_id`` — "who owes whom what" was not queryable by any tool.

Design constraints (each traces to an existing pattern in the tree):

- **Append-only JSONL** under ``<root>/bot_handoffs/handoffs.jsonl`` — same
  shape as ``a2a_audit.jsonl``, one root-level dir like ``bot_relay/``. The
  ledger holds no plaintext: target names and transport metadata only, so a
  longer retention than the DM tempfiles is harmless.
- **Swept on the relay clock** (``bot_relay.STALE_AFTER_SECONDS``) via the
  same opportunistic-sweep contract as every other ``cleanup_*_cache``
  helper, so the gateway housekeeping loop can call it hourly. A handoff
  record's useful life is exactly its reply window; beyond that it is noise.
- **Never raises.** The ledger is observability, not delivery state — any
  failure to record must not break a send.

The relay path links ``envelope_id`` so cross-machine handoffs join the
relay's own reply plumbing instead of duplicating it.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

LEDGER_DIR_NAME = "bot_handoffs"
LEDGER_FILE = "handoffs.jsonl"

__all__ = [
    "LEDGER_DIR_NAME",
    "LEDGER_FILE",
    "ledger_dir",
    "record_handoff",
    "read_handoffs",
    "sweep_handoffs",
]


def ledger_dir(root: Path | str) -> Path:
    return Path(root) / LEDGER_DIR_NAME


def _ledger_path(root: Path | str) -> Path:
    return ledger_dir(root) / LEDGER_FILE


def record_handoff(
    root: Path | str,
    *,
    sender: str,
    target: str,
    transport: str,
    process_id: str = "",
    envelope_id: str = "",
    now: Optional[float] = None,
) -> str:
    """Append one handoff record. Returns its id ("" on failure — never raises).

    ``sender``/``target`` are profile names as the roster spells them;
    ``transport`` is one of ``local`` / ``peer`` / ``relay``.
    """
    hid = uuid.uuid4().hex[:16]
    record = {
        "id": hid,
        "at": int(now if now is not None else time.time()),
        "from": str(sender or ""),
        "to": str(target or ""),
        "transport": str(transport or ""),
        **({"process_id": str(process_id)} if process_id else {}),
        **({"envelope_id": str(envelope_id)} if envelope_id else {}),
    }
    try:
        base = ledger_dir(root)
        base.mkdir(parents=True, exist_ok=True)
        with open(_ledger_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logger.debug("handoff ledger append failed", exc_info=True)
        return ""
    return hid


def read_handoffs(root: Path | str) -> list[dict]:
    """All live records, oldest first. Missing/corrupt ledger → []. Never raises."""
    try:
        raw = _ledger_path(root).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    out.sort(key=lambda r: int(r.get("at") or 0))
    return out


def sweep_handoffs(root: Path | str, *, now: Optional[float] = None) -> int:
    """Drop records older than the relay staleness clock. Returns removed count.

    Rewrite-on-sweep keeps the JSONL bounded; callers already run this cadence
    for the relay artifacts that share the same lifetime.
    """
    from tools.bot_relay import STALE_AFTER_SECONDS

    cutoff = (time.time() if now is None else now) - STALE_AFTER_SECONDS
    try:
        path = _ledger_path(root)
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    kept: list[str] = []
    removed = 0
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except ValueError:
            kept.append(stripped)  # preserve unknown lines verbatim
            continue
        if isinstance(rec, dict) and int(rec.get("at") or 0) < cutoff:
            removed += 1
            continue
        kept.append(stripped)
    if removed:
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            logger.debug("handoff ledger rewrite failed", exc_info=True)
            return 0
    return removed


def cleanup_bot_handoff_ledger(max_age_hours: float | None = None) -> int:
    """Housekeeping hook — same contract as cleanup_bot_relay_artifacts."""
    del max_age_hours  # the relay's STALE_AFTER_SECONDS governs, as in bot_relay
    try:
        home = Path(os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes"))
        root = home.parent.parent if home.parent.name == "profiles" else home
        if not ledger_dir(root).is_dir():
            return 0
        return sweep_handoffs(root)
    except Exception:
        logger.debug("handoff ledger sweep failed", exc_info=True)
        return 0
