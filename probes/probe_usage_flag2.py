"""C2 probe 2: what spawn shape can a kill-test cell actually use for cost?

Probe 1 established: `hermes chat --query-file ... --usage-file ...` — the shape
in kill-test-protocol.md's own bash block AND in runner.py — is REJECTED by the
parser (`--usage-file` is top-level, and is consumed only on the args.oneshot
branch). So "the fix is free, the spawn already supports it" is false as stated.

This probe checks the candidate replacement shape end to end: top-level `-z`
with the prompt read from disk by the runner, carrying the isolation flags the
protocol requires, plus every other flag the protocol's block asks for.

Run from the hermes-agent checkout: python3 probe_usage_flag2.py
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hermes_cli._parser import build_top_level_parser  # noqa: E402

parser, _subparsers, _chat = build_top_level_parser()

CANDIDATE = [
    "-z", "PROMPT-TEXT",
    "--model", "claude-opus-4-8",
    "--provider", "agentrouter-1",
    "--reasoning", "medium",
    "--usage-file", "/tmp/u.json",
    "--ignore-user-config",
    "--ignore-rules",
]
print("candidate cell spawn (protocol flags, -z shape):")
try:
    ns = parser.parse_args(CANDIDATE)
    print(f"  PARSES. usage_file={ns.usage_file!r} oneshot={ns.oneshot!r} "
          f"ignore_user_config={getattr(ns, 'ignore_user_config', None)!r} "
          f"ignore_rules={getattr(ns, 'ignore_rules', None)!r} "
          f"reasoning={getattr(ns, 'reasoning', None)!r}")
except SystemExit as exc:
    print(f"  REJECTED (exit {exc.code})")

# The protocol also asks for --run-budget. Does it exist at top level?
for flag in ["--run-budget", "--no-restore-cwd", "--pass-session-id"]:
    try:
        parser.parse_args(["-z", "x", flag, "180"] if flag == "--run-budget"
                          else ["-z", "x", flag])
        print(f"  {flag}: accepted")
    except SystemExit:
        print(f"  {flag}: NOT a top-level flag")

# What does the usage report actually contain? Read the writer, not a guess.
from hermes_cli.oneshot import _write_usage_file  # noqa: E402

src = inspect.getsource(_write_usage_file)
keys = sorted({ln.split('"')[1] for ln in src.splitlines()
               if ln.strip().startswith('"') and '":' in ln})
print(f"\nusage-report keys actually written ({len(keys)}):")
print("  " + ", ".join(keys))

WANT = ["input_tokens", "output_tokens", "estimated_cost_usd", "api_calls",
        "cache_read_tokens", "cost_status"]
print("\ncolumns the cost gates (H3.11/H3.12/H2.3) need:")
for w in WANT:
    print(f"  {w:<22} present={w in keys}")

# Cost math needs to survive a failed cell too — verify the CALL SITES, not the
# writer's own text (the writer takes `failure`; only run_oneshot decides when).
from hermes_cli.oneshot import run_oneshot  # noqa: E402

caller = inspect.getsource(run_oneshot)
call_sites = [ln.strip() for ln in caller.splitlines() if "_write_usage_file(" in ln]
print(f"\n_write_usage_file call sites inside run_oneshot ({len(call_sites)}):")
for ln in call_sites:
    print(f"  {ln}")
print(f"  -> written on failure paths too: "
      f"{sum('failure' in ln for ln in call_sites)} of {len(call_sites)}")
print(f"never raises            : {'except Exception' in src}")
