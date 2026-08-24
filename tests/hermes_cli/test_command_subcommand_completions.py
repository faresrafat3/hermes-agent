"""Slash-command subcommand completion must not depend on args_hint punctuation.

Behavioural regression guard for a real, measured defect (2026-08-23).

THE DEFECT
    ``hermes_cli/commands.py`` derives tab-completable subcommands two ways:
    the explicit ``CommandDef.subcommands`` field, or — when that is empty — a
    fallback regex over ``args_hint``. That regex is ``[a-z]+(?:\\|[a-z]+)+``,
    which only matches pipes with NO surrounding spaces (``"[on|off|status]"``).

    ``/goal``'s hint is spaced prose:
        "[text | draft <text> | show | gate add <cmd> | pause | ... ]"
    so it matched nothing, and ``SUBCOMMANDS["/goal"]`` was absent entirely —
    zero of its nine documented verbs were completable, including ``gate``, the
    only deterministic refusal mechanism in the goal loop. The failure was
    silent: nothing errored, the verbs simply never appeared in any surface fed
    by ``SUBCOMMANDS`` (CLI completer, and ``tui_gateway/methods_tools.py``,
    which ships it to the TUI and desktop as ``sub``).

WHAT THESE TESTS ASSERT
    Behaviour, via the real registry: that commands advertising verbs actually
    expose them, and that every exposed verb is one the handler dispatches.
    They never read source text (repo rule: tests must not assert on the shape
    of source), and they avoid freezing the full verb list, which would be a
    change-detector. Adding a new ``/goal`` verb must not break these; removing
    ``gate`` from completion must.
"""

from __future__ import annotations

import re

import pytest

from hermes_cli.commands import COMMAND_REGISTRY, SUBCOMMANDS

# Commands whose verbs matter enough that losing completion is a real defect.
# Kept deliberately small — this is a guard, not an inventory.
_VERB_CRITICAL = ("goal", "subgoal")


def _cmd(name: str):
    for cmd in COMMAND_REGISTRY:
        if cmd.name == name:
            return cmd
    pytest.fail(f"/{name} missing from COMMAND_REGISTRY")


def test_goal_exposes_gate_for_completion():
    """`gate` is the goal loop's only deterministic refusal verb.

    It must be reachable by completion, or the mechanism is undiscoverable in
    every surface that renders SUBCOMMANDS.
    """
    verbs = SUBCOMMANDS.get("/goal")
    assert verbs, "/goal exposes no completable subcommands at all"
    assert "gate" in verbs, f"/goal completions missing 'gate': {verbs}"


@pytest.mark.parametrize("name", _VERB_CRITICAL)
def test_verb_critical_commands_expose_their_verbs(name: str):
    """A command that advertises verbs in its hint must complete some of them.

    This is the invariant the fallback regex silently violated: the hint said
    the verbs existed while completion offered nothing.
    """
    cmd = _cmd(name)
    assert cmd.args_hint, f"/{name} has no args_hint to advertise verbs"
    verbs = SUBCOMMANDS.get(f"/{name}")
    assert verbs, (
        f"/{name} advertises verbs in args_hint {cmd.args_hint!r} but exposes "
        "no completions — the args_hint fallback regex only matches pipes with "
        "no surrounding spaces, so spaced prose needs explicit subcommands"
    )


@pytest.mark.parametrize("name", _VERB_CRITICAL)
def test_exposed_verbs_are_mentioned_in_the_hint(name: str):
    """Every completable verb must be one the command actually documents.

    Guards the opposite failure from the one above: inventing a verb that no
    handler dispatches. (An earlier draft of the /goal fix added ``contract``,
    which the handler does not accept; the hint is the contract of record.)

    Scoped to the goal-loop commands on purpose. A registry-wide version of
    this assertion was written and DELETED: it flagged /reasoning
    (``[level|show|hide]`` completing the level *values*), /fast
    (``[normal|fast|status]`` also accepting on/off), /pet and /suggestions —
    all legitimate designs where the hint names a category and completion
    offers members of it. Trying to narrow around them (only enumerating
    hints, only hand-declared lists) failed both times, because those
    commands are hand-declared and enumerating too. The honest conclusion is
    that "verb appears verbatim in the hint" is not a registry-wide invariant
    at all; it holds for /goal and /subgoal, where the hint IS the verb list.
    """
    cmd = _cmd(name)
    hint_words = set(re.findall(r"[a-z][a-z-]+", (cmd.args_hint or "").lower()))
    for verb in SUBCOMMANDS.get(f"/{name}") or ():
        assert verb in hint_words, (
            f"/{name} completes {verb!r} but its args_hint never mentions it: "
            f"{cmd.args_hint!r}"
        )


def test_spaced_prose_hints_do_not_silently_lose_completions():
    """No command may advertise pipe-separated verbs and complete nothing.

    The bug class, stated once. A command is only allowed to expose no
    completions if its hint does not offer a verb menu in the first place.
    """
    offenders = []
    for cmd in COMMAND_REGISTRY:
        hint = cmd.args_hint or ""
        # Only judge hints that present a genuine verb menu: 2+ alternatives
        # made of bare words. "<prompt>" or "[N]" advertise nothing.
        alternatives = [
            part.strip() for part in hint.strip("[]").split("|") if part.strip()
        ]
        bare_verbs = [
            part for part in alternatives if re.fullmatch(r"[a-z][a-z-]+", part)
        ]
        if len(alternatives) < 2 or len(bare_verbs) < 2:
            continue
        if not SUBCOMMANDS.get(f"/{cmd.name}"):
            offenders.append((cmd.name, hint))

    assert not offenders, (
        "these commands advertise a verb menu but complete nothing — declare "
        "CommandDef.subcommands explicitly (the args_hint fallback regex needs "
        f"unspaced pipes): {offenders}"
    )


def test_subcommands_map_only_contains_known_commands():
    """SUBCOMMANDS keys must all resolve to real registry entries.

    Cheap consistency check on the derivation itself: a stale or typo'd key
    would ship completions for a command that cannot be dispatched.
    """
    known = {f"/{cmd.name}" for cmd in COMMAND_REGISTRY}
    unknown = sorted(set(SUBCOMMANDS) - known)
    assert not unknown, f"SUBCOMMANDS has keys with no CommandDef: {unknown}"
