"""Tests for tools/bot_mode_probe.py — the Bot Mode teammate-protocol section."""

import textwrap

import pytest

from tools import bot_mode_probe


@pytest.fixture(autouse=True)
def _fresh_cache():
    bot_mode_probe._reset_cache_for_tests()
    yield
    bot_mode_probe._reset_cache_for_tests()


def _make_bot_profile(root, name, *, managed=True, soul=None):
    d = root / "profiles" / name
    d.mkdir(parents=True, exist_ok=True)
    if managed:
        (d / "profile.yaml").write_text(
            textwrap.dedent(
                """\
                ui_meta:
                  hermes-bots:
                    shape: cloud
                    color: '#8b5cf6'
                """
            ),
            encoding="utf-8",
        )
    if soul is not None:
        (d / "SOUL.md").write_text(soul, encoding="utf-8")
    return d


def test_silent_when_no_profile_is_bot_managed(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=False)
    assert bot_mode_probe.get_bot_mode_protocol_section(home) == ""


def test_emits_for_default_when_any_profile_is_managed(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)

    section = bot_mode_probe.get_bot_mode_protocol_section(home)
    assert section.startswith("## Messaging other agents")
    # default's callable alias is @hermes, never @default
    assert "@hermes" in section
    assert "@default" not in section
    assert "@researcher" in section
    assert "message_agent" in section


def test_emits_for_named_profile_with_own_handle(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    profile_dir = _make_bot_profile(home, "coder", managed=True)

    section = bot_mode_probe.get_bot_mode_protocol_section(profile_dir)
    assert "@coder" in section
    # teammate roster excludes self, includes default (as @hermes)
    roster_block = section.split("Your teammates")[1]
    assert "`@hermes`" in roster_block
    assert "`@coder`" not in roster_block


def test_roster_lines_carry_roles(tmp_path):
    """Bots must know WHO to message: the roster carries title/description."""
    import textwrap as _tw

    home = tmp_path / ".hermes"
    home.mkdir()
    d = home / "profiles" / "researcher"
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(
        _tw.dedent(
            """\
            description: Deep research and literature review
            ui_meta:
              hermes-bots:
                title: Research Buddy
            """
        ),
        encoding="utf-8",
    )

    section = bot_mode_probe.get_bot_mode_protocol_section(home)
    assert "`@researcher`" in section
    assert "Research Buddy" in section
    assert "Deep research and literature review" in section


def test_silent_when_soul_already_carries_protocol(tmp_path):
    """Legacy plugin-side append — never double the section."""
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "coder", managed=True)
    (home / "SOUL.md").write_text(
        "# Me\n\n## Messaging other agents\nold plugin text\n", encoding="utf-8"
    )
    assert bot_mode_probe.get_bot_mode_protocol_section(home) == ""


def test_deterministic_across_calls(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)
    first = bot_mode_probe.get_bot_mode_protocol_section(home)
    # Even if the filesystem changes, the cached result must be byte-stable
    # for the life of the process (prompt-cache invariant).
    _make_bot_profile(home, "newbot", managed=True)
    second = bot_mode_probe.get_bot_mode_protocol_section(home)
    assert first == second


def test_never_raises_on_garbage(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    profiles = home / "profiles" / "bad"
    profiles.mkdir(parents=True)
    (profiles / "profile.yaml").write_text("ui_meta: [unclosed", encoding="utf-8")
    assert isinstance(bot_mode_probe.get_bot_mode_protocol_section(home), str)

    monkeypatch.setattr(bot_mode_probe, "_roster", lambda root: (_ for _ in ()).throw(OSError("boom")))
    bot_mode_probe._reset_cache_for_tests()
    assert bot_mode_probe.get_bot_mode_protocol_section(home) == ""


# ── capability epoch ─────────────────────────────────────────────────────────


def test_fingerprint_stable_when_nothing_changes(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)
    assert bot_mode_probe.capability_fingerprint(home) == bot_mode_probe.capability_fingerprint(home)


def test_fingerprint_changes_on_each_capability_axis(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)
    base = bot_mode_probe.capability_fingerprint(home)

    # new skill installed
    skill = home / "skills" / "web" / "scraping"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: scraping\n---\n", encoding="utf-8")
    after_skill = bot_mode_probe.capability_fingerprint(home)
    assert after_skill != base

    # toolset pin changed
    (home / "config.yaml").write_text("tools:\n  enabled_toolsets: [web]\n", encoding="utf-8")
    after_tools = bot_mode_probe.capability_fingerprint(home)
    assert after_tools != after_skill

    # MCP server added
    (home / "config.yaml").write_text(
        "tools:\n  enabled_toolsets: [web]\nmcp_servers:\n  github:\n    preset: github\n",
        encoding="utf-8",
    )
    after_mcp = bot_mode_probe.capability_fingerprint(home)
    assert after_mcp != after_tools

    # SOUL edited
    (home / "SOUL.md").write_text("# New identity\n", encoding="utf-8")
    after_soul = bot_mode_probe.capability_fingerprint(home)
    assert after_soul != after_mcp

    # teammate added to the roster
    _make_bot_profile(home, "coder", managed=True)
    assert bot_mode_probe.capability_fingerprint(home) != after_soul


def test_stored_prompt_staleness(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)

    stamped = "system stuff\n\n" + bot_mode_probe.epoch_line(home)
    # unchanged surface → not stale (cache preserved)
    assert not bot_mode_probe.stored_prompt_capability_stale(stamped, home)

    # capability change → stale exactly once
    skill = home / "skills" / "new-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: new-skill\n---\n", encoding="utf-8")
    assert bot_mode_probe.stored_prompt_capability_stale(stamped, home)
    restamped = "system stuff\n\n" + bot_mode_probe.epoch_line(home)
    assert not bot_mode_probe.stored_prompt_capability_stale(restamped, home)

    # prompts without a stamp (every non-Bot-Chat session) are never stale
    assert not bot_mode_probe.stored_prompt_capability_stale("ordinary prompt", home)
    assert not bot_mode_probe.stored_prompt_capability_stale("", home)


def test_legacy_bot_chat_upgrade(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)

    legacy = "old prompt with no protocol and no stamp"
    # legacy Bot Chat on a managed install → upgrade once
    assert bot_mode_probe.stored_bot_chat_prompt_needs_upgrade(legacy, home)

    # a rebuilt prompt (stamped) never re-fires
    upgraded = legacy + "\n\n" + bot_mode_probe.get_bot_mode_protocol_section(home) + "\n\n" + bot_mode_probe.epoch_line(home)
    assert not bot_mode_probe.stored_bot_chat_prompt_needs_upgrade(upgraded, home)

    # SOUL already carries the legacy plugin-side append → probe silent →
    # no upgrade (rebuilding would loop: the new prompt would be unstamped too)
    bot_mode_probe._reset_cache_for_tests()
    (home / "SOUL.md").write_text("# Me\n\n## Messaging other agents\nlegacy\n", encoding="utf-8")
    assert not bot_mode_probe.stored_bot_chat_prompt_needs_upgrade(legacy, home)

    # prompt whose SOUL section rode into it → protocol heading present → no upgrade
    assert not bot_mode_probe.stored_bot_chat_prompt_needs_upgrade(
        "prompt containing\n## Messaging other agents\nfrom SOUL", home
    )

    # unmanaged install → probe silent → never upgrades
    bot_mode_probe._reset_cache_for_tests()
    home2 = tmp_path / ".hermes2"
    home2.mkdir()
    assert not bot_mode_probe.stored_bot_chat_prompt_needs_upgrade(legacy, home2)


# ── peer gateways (cross-machine DMs) ────────────────────────────────────────


def test_peer_paragraph_absent_without_peers(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)

    section = bot_mode_probe.get_bot_mode_protocol_section(home)
    assert "hermes peer dm" not in section
    assert "OTHER machines" not in section


def test_peer_paragraph_lists_registered_peers(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)
    (home / "config.yaml").write_text(
        textwrap.dedent(
            """\
            bot_peers:
              spark:
                url: http://spark.lan:8377
              homelab:
                url: http://homelab.lan:8377
            """
        ),
        encoding="utf-8",
    )

    section = bot_mode_probe.get_bot_mode_protocol_section(home)
    assert "message_agent" in section
    assert '"<peer>/<agent-name>"' in section
    assert "`homelab`" in section and "`spark`" in section
    assert "hermes peer list" in section


def test_fingerprint_changes_when_a_peer_is_registered(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)

    before = bot_mode_probe.capability_fingerprint(home)
    (home / "config.yaml").write_text(
        "bot_peers:\n  spark:\n    url: http://spark.lan:8377\n",
        encoding="utf-8",
    )
    after = bot_mode_probe.capability_fingerprint(home)
    assert before != after


# ── capability tags on the roster (handoff routing) ──────────────────────────
#
# The roster block is the ONLY thing a bot reads to pick a handoff recipient.
# Name + free-text role alone force the model to guess from a description, so a
# teammate's actual installed skill domains are surfaced as bounded tags.


def _give_skills(profile_dir, *categories):
    """Install skill categories the way the real skills/ tree is laid out."""
    for category in categories:
        d = profile_dir / "skills" / category / f"{category}-helper"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"# {category}\n", encoding="utf-8")


def test_roster_line_carries_teammate_capability_tags(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    researcher = _make_bot_profile(home, "researcher", managed=True)
    _give_skills(researcher, "research", "github")

    section = bot_mode_probe.get_bot_mode_protocol_section(home)
    assert "`@researcher`" in section
    # Tags let a handoff be routed by capability, not just by @name.
    assert "research" in section
    assert "github" in section


def test_capability_tags_are_bounded_not_a_full_dump(tmp_path):
    """A 30-category teammate must not blow up every teammate's prompt.

    Shaped like the real fleet: a long role AND many long category names. An
    earlier version of this test used a role-less profile and therefore missed
    that the role text is the dominant term.
    """
    home = tmp_path / ".hermes"
    home.mkdir()
    big = _make_bot_profile(home, "generalist", managed=True)
    (big / "profile.yaml").write_text(
        textwrap.dedent(
            """\
            description: >-
              Broad generalist spanning software development, debugging, code review,
              GitHub PR and issue workflows, research and paper writing with citations,
              and document processing across many formats
            ui_meta:
              hermes-bots:
                title: generalist
            """
        ),
        encoding="utf-8",
    )
    _give_skills(
        big,
        *[f"context-verification-and-prompt-untrusted-input-defense-{i:02d}" for i in range(30)],
    )

    line = next(
        ln for ln in bot_mode_probe._roster_lines(home, "default") if "generalist" in ln
    )
    # The bound is structural, not a guessed number: handle + role cap (160)
    # + tag budget (96) + separators. Verified against the real 12-profile
    # fleet, whose widest line lands at 263.
    budget = len("- `@generalist` — ") + 160 + len(" []") + 96
    assert len(line) <= budget, f"roster line unbounded: {len(line)} > {budget}"


def test_role_does_not_repeat_a_title_already_in_the_description(tmp_path):
    """Real-fleet bug: the role read 'X — X — X'.

    _profile_role joins the Bot Mode title and the profile description, but
    users routinely set the description to text that already opens with the
    title (the Bots UI seeds it that way). Joining blindly triples the words in
    a block that lives in EVERY teammate's eternal prompt.
    """
    home = tmp_path / ".hermes"
    home.mkdir()
    d = _make_bot_profile(home, "plugin-manager", managed=True)
    (d / "profile.yaml").write_text(
        textwrap.dedent(
            """\
            description: plugin manager — plugin manager
            ui_meta:
              hermes-bots:
                title: plugin manager
            """
        ),
        encoding="utf-8",
    )

    role = bot_mode_probe._profile_role(d)
    assert role.lower().count("plugin manager") == 1, f"duplicated role text: {role!r}"


def test_role_still_joins_a_title_and_a_distinct_description(tmp_path):
    """The dedupe must not swallow a description that adds real information."""
    home = tmp_path / ".hermes"
    home.mkdir()
    d = _make_bot_profile(home, "researcher", managed=True)
    (d / "profile.yaml").write_text(
        textwrap.dedent(
            """\
            description: reads papers and verifies citations
            ui_meta:
              hermes-bots:
                title: Research Lead
            """
        ),
        encoding="utf-8",
    )

    role = bot_mode_probe._profile_role(d)
    assert "Research Lead" in role
    assert "verifies citations" in role


def test_roster_line_has_no_tag_suffix_for_skill_less_teammate(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "bare", managed=True)

    line = next(ln for ln in bot_mode_probe._roster_lines(home, "default") if "bare" in ln)
    assert line.strip() == "- `@bare`"


def test_fingerprint_covers_a_TEAMMATES_capability_change(tmp_path):
    """The load-bearing invariant.

    capability_fingerprint() is what decides whether an eternal Bot Chat prompt
    gets rebuilt. If teammate tags render into the roster block but the
    fingerprint only hashes the agent's OWN surface, then installing a skill on
    `researcher` never refreshes `default`'s prompt — every other bot keeps
    routing handoffs off a stale capability list forever.
    """
    home = tmp_path / ".hermes"
    home.mkdir()
    researcher = _make_bot_profile(home, "researcher", managed=True)
    _give_skills(researcher, "research")

    before = bot_mode_probe.capability_fingerprint(home)
    _give_skills(researcher, "security")  # teammate gains a capability
    after = bot_mode_probe.capability_fingerprint(home)

    assert before != after, "a teammate's capability change did not refresh the prompt"


def test_fingerprint_is_stable_when_nothing_changed(tmp_path):
    """Cache safety: an unchanged surface must hash identically.

    A fingerprint that drifts on its own rebuilds the system prompt every turn
    and destroys per-conversation prompt caching.
    """
    home = tmp_path / ".hermes"
    home.mkdir()
    researcher = _make_bot_profile(home, "researcher", managed=True)
    _give_skills(researcher, "research", "github")

    first = bot_mode_probe.capability_fingerprint(home)
    for _ in range(4):
        assert bot_mode_probe.capability_fingerprint(home) == first


def test_probe_never_imports_user_plugin_modules(tmp_path, monkeypatch):
    """The core probe must never reach into ~/.hermes/plugins to build text.

    Fleet awareness belongs to the fleet-registry plugin via the generic
    register_system_prompt_section() surface. If the probe ever imports
    plugin code directly (sys.path insertion + ``from skill import ...``),
    then: named profiles break (the path hardcodes Path.home()/".hermes"),
    a generic top-level module name like ``skill`` can be shadowed by any
    user plugin, and this suite would render REAL fleet state on a live
    host instead of the fixture's.
    """
    import sys

    home = tmp_path / ".hermes"
    home.mkdir()
    _make_bot_profile(home, "researcher", managed=True)

    banned = ("skill", "core", "index", "self_update")
    stashed = {name: sys.modules.pop(name) for name in banned if name in sys.modules}
    path_before = list(sys.path)
    # Even a hijacked/explicit Path.home() must not give the probe a plugin
    # directory to load: the fixture home is under tmp_path, not the real one.
    monkeypatch.setattr(bot_mode_probe.Path, "home", lambda: tmp_path)
    try:
        bot_mode_probe.get_bot_mode_protocol_section(home)
        leaked = [name for name in banned if name in sys.modules]
        assert not leaked, f"probe imported user-plugin modules: {leaked}"
        assert sys.path == path_before, "probe mutated sys.path"
    finally:
        for name, mod in stashed.items():
            sys.modules.setdefault(name, mod)
