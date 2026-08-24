"""Tests for ``hermes handoffs`` — the bot handoff ledger CLI.

The ledger (tools/bot_handoffs.py) records every message_agent delivery as an
addressable work item. This command makes "who owes whom what" answerable from
a shell instead of reading the JSONL by hand.
"""

import json
import time
from types import SimpleNamespace

from hermes_cli.subcommands import handoffs as handoffs_cmd
from tools import bot_handoffs


def _args(**kw):
    base = {"handoffs_action": "list", "json": False, "watch": False}
    base.update(kw)
    return SimpleNamespace(**base)


def test_list_prints_records_newest_last(tmp_path, capsys):
    first = bot_handoffs.record_handoff(
        tmp_path, sender="default", target="c3-economist", transport="local",
        process_id="proc_a", now=time.time() - 60,
    )
    second = bot_handoffs.record_handoff(
        tmp_path, sender="leader", target="dixie", transport="relay",
        envelope_id="e" * 32, now=time.time(),
    )

    rc = handoffs_cmd.cmd_handoffs(_args(root=str(tmp_path)))
    out = capsys.readouterr().out

    assert rc == 0
    assert first in out and second in out
    # oldest first — a log reads top-down
    assert out.index(first) < out.index(second)
    assert "c3-economist" in out and "dixie" in out
    assert "relay" in out and "local" in out


def test_list_empty_ledger_says_so(tmp_path, capsys):
    rc = handoffs_cmd.cmd_handoffs(_args(root=str(tmp_path)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "No handoffs" in out or "no handoffs" in out


def test_json_output_is_machine_readable(tmp_path, capsys):
    hid = bot_handoffs.record_handoff(
        tmp_path, sender="default", target="researcher", transport="peer",
        process_id="proc_x",
    )
    rc = handoffs_cmd.cmd_handoffs(_args(root=str(tmp_path), json=True))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert isinstance(payload, list) and len(payload) == 1
    assert payload[0]["id"] == hid
    assert payload[0]["transport"] == "peer"


def test_filter_by_target(tmp_path, capsys):
    bot_handoffs.record_handoff(tmp_path, sender="default", target="researcher", transport="local")
    kept = bot_handoffs.record_handoff(tmp_path, sender="default", target="dixie", transport="local")

    rc = handoffs_cmd.cmd_handoffs(_args(root=str(tmp_path), to="dixie"))
    out = capsys.readouterr().out

    assert rc == 0
    assert kept in out
    assert "researcher" not in out


def test_sweep_subcommand_reports_removed_count(tmp_path, capsys):
    old_at = time.time() - 7 * 3600  # older than the relay's stale clock
    bot_handoffs.record_handoff(
        tmp_path, sender="a", target="b", transport="local", now=old_at,
    )
    fresh = bot_handoffs.record_handoff(
        tmp_path, sender="a", target="c", transport="local",
    )

    rc = handoffs_cmd.cmd_handoffs(_args(root=str(tmp_path), handoffs_action="sweep"))
    out = capsys.readouterr().out

    assert rc == 0
    assert "1" in out  # removed count
    remaining = [r["id"] for r in bot_handoffs.read_handoffs(tmp_path)]
    assert remaining == [fresh]


def test_unknown_action_is_a_usage_error(tmp_path):
    rc = handoffs_cmd.cmd_handoffs(_args(root=str(tmp_path), handoffs_action="bogus"))
    assert rc == 2
