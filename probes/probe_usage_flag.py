"""C2 probe: does `--usage-file` actually reach a `hermes chat --query-file` spawn?

The kill-test runner spawns cells as `hermes chat --query-file ... -Q`, NOT as
`hermes -z`. `--usage-file` is documented "one-shot mode only", so before I wire
cost columns into the ledger I must know which spawn shape actually produces a
usage report — asserting it would be exactly the vacuity Art 0.9 bans.

Run from the hermes-agent checkout: python3 probe_usage_flag.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hermes_cli._parser import build_top_level_parser  # noqa: E402

CASES = [
    ["chat", "--query-file", "/tmp/p.md", "--usage-file", "/tmp/u.json", "-Q"],
    ["-z", "hi", "--usage-file", "/tmp/u.json"],
    ["--usage-file", "/tmp/u.json", "chat", "--query-file", "/tmp/p.md", "-Q"],
    ["chat", "-q", "hi", "--usage-file", "/tmp/u.json"],
]

parser, _subparsers, _chat_parser = build_top_level_parser()
for argv in CASES:
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:
        print(f"REJECTED (exit {exc.code}): {' '.join(argv)}")
        continue
    print(f"parsed  : {' '.join(argv)}")
    print(f"          command={getattr(ns, 'command', None)!r} "
          f"usage_file={getattr(ns, 'usage_file', None)!r} "
          f"oneshot={getattr(ns, 'oneshot', None)!r} "
          f"query_file={getattr(ns, 'query_file', None)!r}")

# Where is usage_file consumed? Only _run_and_exit_oneshot, gated on args.oneshot.
print("\nconsumption sites for usage_file in hermes_cli/main.py:")
main_src = (Path(__file__).resolve().parent / "hermes_cli" / "main.py").read_text()
for i, line in enumerate(main_src.splitlines(), 1):
    if "usage_file" in line:
        print(f"  {i}: {line.strip()}")
