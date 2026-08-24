"""Bot Mode roster probe — canonical Bot Chat system prompt section.

When the desktop's Bot Mode manages this install (any profile carries a
``ui_meta['hermes-bots']`` block in its profile.yaml), a bot's canonical
"Bot Chat" session — and ONLY that session — gets a short "Messaging other
agents" section so the bot can receive teammate DMs, reply with attribution,
and hand off @mentions.  Regular sessions never carry the section; the
desktop's composer middleware owns the @mention send path there.

The caller (agent/system_prompt.py) enforces the session-title gate against
``BOT_CHAT_TITLE``; this module answers "is this install Bot-Mode-managed,
and what should the section say for this profile".

This replaces the plugin-side SOUL.md backfill: the protocol is injected by
the core at prompt-build time instead of appended to user-authored SOUL
files.  If the profile's SOUL.md already carries the section (created by an
older plugin version), the probe stays silent so the text never doubles up.

Silent (returns ``""``) when:
- no profile on this install is Bot-Mode-managed (the dominant case),
- the current profile's SOUL.md already contains the protocol heading,
- anything at all goes wrong (never crash a prompt build).

Deterministic within a process: the result is computed once and cached, so
compression-triggered prompt rebuilds produce identical bytes.

Toggle via ``agent.bot_mode_protocol`` in config.yaml (default True).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

_PROTOCOL_HEADING = "## Messaging other agents"

# The canonical per-bot conversation title — the only session shape that
# receives the protocol section. Must match the desktop plugin's
# createCanonicalChat title and the `-c "Bot Chat"` resume target.
BOT_CHAT_TITLE = "Bot Chat"

# Capability tags per teammate on the roster line. Bounded because the roster
# block is rendered into EVERY teammate's eternal Bot Chat prompt: a generalist
# with 30 skill categories would otherwise cost every other bot those tokens
# forever. Eight is enough to route a handoff; the char budget is the real
# bound, since category names vary from "security" to
# "context-verification-and-prompt-untrusted-input-defense".
_MAX_CAPABILITY_TAGS = 8
_MAX_CAPABILITY_CHARS = 96

_lock = threading.Lock()
_cached: dict[str, str] = {}


def _hermes_root(home: Path) -> Path:
    """Root ~/.hermes for both the default profile and named profiles."""
    if home.parent.name == "profiles":
        return home.parent.parent
    return home


def _profile_name(home: Path) -> str:
    if home.parent.name == "profiles":
        return home.name
    return "default"


def _is_bot_managed(profile_dir: Path) -> bool:
    """True when profile.yaml carries a ui_meta['hermes-bots'] block.

    Cheap substring check before the YAML parse keeps the silent path fast.
    """
    meta = profile_dir / "profile.yaml"
    try:
        if not meta.is_file():
            return False
        raw = meta.read_text(encoding="utf-8", errors="replace")
        if "hermes-bots" not in raw:
            return False
        import yaml

        data = yaml.safe_load(raw)
        ui_meta = data.get("ui_meta") if isinstance(data, dict) else None
        return isinstance(ui_meta, dict) and isinstance(ui_meta.get("hermes-bots"), dict)
    except Exception:
        return False


def _roster(root: Path) -> list[tuple[str, Path]]:
    """(name, dir) for the default profile + every named profile."""
    entries: list[tuple[str, Path]] = [("default", root)]
    try:
        profiles = root / "profiles"
        if profiles.is_dir():
            for child in sorted(profiles.iterdir()):
                if child.is_dir():
                    entries.append((child.name, child))
    except Exception:
        pass
    return entries


def is_bot_mode_managed(home: str | os.PathLike | None = None) -> bool:
    """True when ANY profile on this install is Bot-Mode-managed.

    The tool-injection gate for ``message_agent`` — deliberately independent
    of :func:`get_bot_mode_protocol_section`'s emptiness: a profile whose
    SOUL.md carries the legacy plugin-appended protocol gets an empty
    section (text dedupe) but must still get the tool. Never raises.
    """
    try:
        resolved = Path(
            str(home) if home else (os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes"))
        )
        root = _hermes_root(resolved)
        return any(_is_bot_managed(d) for _n, d in _roster(root))
    except Exception:
        return False


def _soul_has_protocol(profile_dir: Path) -> bool:
    try:
        soul = profile_dir / "SOUL.md"
        return soul.is_file() and _PROTOCOL_HEADING in soul.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def _handle(name: str) -> str:
    # The mention middleware aliases the default profile as @hermes.
    return "hermes" if name == "default" else name


def _strip_title_echo(description: str, title: str) -> str:
    """Remove the bot title where the description merely repeats it.

    Handles the two shapes the Bots UI actually produces: a description that
    IS the title (possibly repeated with the same em-dash separator the role
    join uses), and one that opens with the title before adding real detail.
    Returns "" when nothing but echoes remain.
    """
    remainder = description
    title_l = title.casefold()
    # Peel repeated leading "title — " / "title - " / "title: " prefixes.
    while True:
        stripped = remainder.lstrip()
        if not stripped.casefold().startswith(title_l):
            break
        rest = stripped[len(title):].lstrip()
        rest_no_sep = rest.lstrip("—-:,·|").lstrip()
        if rest_no_sep == rest and rest:
            # Title is a prefix of a longer word (e.g. "leader" in
            # "leadership") — not an echo; keep the description intact.
            break
        remainder = rest_no_sep
        if not remainder:
            break
    return remainder.strip()


def _profile_role(profile_dir: Path) -> str:
    """A teammate's role line: Bot Mode title, else profile description.

    The ui_meta['hermes-bots'].title is the name the user gave the bot in
    Bot Mode; profile.yaml's description is the profile's stated purpose.
    Either one tells a teammate WHO to message for a given job. Bounded and
    single-line; empty when neither exists. Never raises.
    """
    meta = profile_dir / "profile.yaml"
    try:
        if not meta.is_file():
            return ""
        raw = meta.read_text(encoding="utf-8", errors="replace")
        import yaml

        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            return ""
        parts = []
        ui_meta = data.get("ui_meta")
        if isinstance(ui_meta, dict) and isinstance(ui_meta.get("hermes-bots"), dict):
            title = str(ui_meta["hermes-bots"].get("title") or "").strip()
            if title:
                parts.append(title)
        description = str(data.get("description") or "").strip()
        # The Bots UI seeds a new bot's description FROM its title, so joining
        # both blindly renders "X — X — X" in a block that lives in every
        # teammate's eternal prompt (observed on 5 of 12 profiles on a real
        # fleet). Drop the description when the title already covers it, and
        # strip a leading title echo when the rest still adds information.
        if description and parts:
            title_l = parts[0].casefold()
            desc_l = description.casefold()
            if title_l and title_l in desc_l:
                remainder = _strip_title_echo(description, parts[0])
                description = remainder
        if description:
            parts.append(description)
        line = " — ".join(parts)
        return " ".join(line.split())[:160]
    except Exception:
        return ""


def _profile_capabilities(profile_dir: Path) -> list[str]:
    """Capability tags for a teammate: its installed skill CATEGORIES.

    The skills tree is ``skills/<category>/<skill>/SKILL.md``, and the
    category directories are already the semantic domains a handoff wants to
    route on (``security``, ``research``, ``devops``, ``governance``). Reading
    only the top level is a deliberate cost decision: this runs inside
    :func:`capability_fingerprint`, which is intentionally uncached and
    therefore executes on EVERY Bot Chat turn, for every profile on the
    install. On a 12-profile / 875-skill fleet a recursive ``**/SKILL.md``
    walk measures ~20.7ms per call versus ~0.6ms for the top level — same
    routing signal, ~37x cheaper.

    Sorted (stable hashing) and capped, so one generalist teammate with 30
    categories cannot inflate every other teammate's eternal prompt. Never
    raises.
    """
    try:
        skills_root = profile_dir / "skills"
        if not skills_root.is_dir():
            return []
        names = sorted(
            child.name
            for child in skills_root.iterdir()
            if child.is_dir() and not child.name.startswith(".")
        )
        return names[:_MAX_CAPABILITY_TAGS]
    except OSError:
        return []


def _roster_lines(root: Path, me: str) -> list[str]:
    """One '- `@handle` — role [tags]' line per teammate (excluding ``me``)."""
    lines = []
    for name, profile_dir in _roster(root):
        if name == me:
            continue
        role = _profile_role(profile_dir)
        handle = _handle(name)
        tags = _profile_capabilities(profile_dir)
        line = f"- `@{handle}`" + (f" — {role}" if role else "")
        if tags:
            # Budget, not just a count: category names range from "security"
            # to "context-verification-and-prompt-untrusted-input-defense", so
            # a fixed tag count is not a bound on tokens. Keep whole tags.
            kept: list[str] = []
            used = 0
            for tag in tags:
                cost = len(tag) + 2  # ", "
                if kept and used + cost > _MAX_CAPABILITY_CHARS:
                    break
                kept.append(tag)
                used += cost
            line += f" [{', '.join(kept)}]"
        lines.append(line)
    return lines


def _peers(root: Path) -> list[str]:
    """Registered peer gateway names (``hermes peer``), for the protocol text.

    Reads config.yaml directly (cheap, no config-loader import) — the section
    is optional and absent on most installs. Never raises.
    """
    try:
        cfg_path = root / "config.yaml"
        if not cfg_path.is_file():
            return []
        raw = cfg_path.read_text(encoding="utf-8", errors="replace")
        if "bot_peers" not in raw:
            return []
        import yaml

        data = yaml.safe_load(raw)
        peers = data.get("bot_peers") if isinstance(data, dict) else None
        if not isinstance(peers, dict):
            return []
        return sorted(str(name) for name in peers if str(name).strip())
    except Exception:
        return []


def _remote_paragraph(root: Path) -> str:
    """Protocol addendum for agents on OTHER connected machines.

    Fed by the Desktop relay roster (``tools/bot_relay.py``) — every gateway
    connected to the user's Desktop (local, remote URL, SSH, Hermes Cloud,
    docker) syncs its agents here, so bots can DM across machines with the
    same message_agent tool. Only rendered when the relay roster is
    non-empty.
    """
    try:
        from tools.bot_relay import read_remote_roster, remote_target_forms

        roster = read_remote_roster(root)
    except Exception:
        return ""
    if not roster:
        return ""
    lines = []
    for row, form in zip(roster, remote_target_forms(roster)):
        where = row["connection_label"] or row["connection_id"]
        role = " — ".join(p for p in (row["title"], row["description"]) if p)
        lines.append(
            f"- `@{form}` — on {where}" + (f" — {role}" if role else "")
        )
    return (
        "\n\nTeammates on OTHER connected machines (reachable through the "
        "Desktop relay — message them with message_agent exactly like local "
        "teammates; replies arrive as completion notifications the same "
        "way):\n" + "\n".join(lines)
    )


def _peer_paragraph(root: Path) -> str:
    """Protocol addendum for cross-machine DMs — only when peers exist."""
    peers = _peers(root)
    if not peers:
        return ""
    listed = ", ".join(f"`{p}`" for p in peers)
    return (
        "\n\nTeammates on OTHER machines: this install also has peer gateways "
        f"registered ({listed}). Message an agent on a peer the same way — "
        'message_agent with target "<peer>/<agent-name>" (or "<peer>" alone '
        "for the peer's main agent). Run `hermes peer list` for the live "
        "peer list."
    )


def _build_section(home: Path) -> str:
    root = _hermes_root(home)
    me = _profile_name(home)

    roster = _roster(root)
    if not any(_is_bot_managed(d) for _n, d in roster):
        return ""

    # An older plugin build may have appended the protocol to SOUL.md
    # already — never double it up.
    my_dir = home if me == "default" else root / "profiles" / me
    if _soul_has_protocol(my_dir):
        return ""

    handle = _handle(me)
    roster_block = "\n".join(_roster_lines(root, me)) or "- (no teammates yet)"

    return (
        f"{_PROTOCOL_HEADING}\n"
        "This install runs Bot Mode: each Hermes profile is an agent teammate with "
        'one canonical "Bot Chat" conversation, and you have the `message_agent` '
        "tool to DM any of them. It is FIRE-AND-FORGET: it delivers your message "
        "with your attribution prefixed automatically and returns an acknowledgement "
        "immediately — it never returns the reply. Send it, finish your turn, and "
        "the reply arrives later as a background-process completion notification "
        "that wakes you; relay it to the user then, attributed to that agent. "
        "COMPOSE every message yourself — say what YOU need from that agent; never "
        "forward the user's words verbatim, and never reveal private 1:1 chat "
        "content. When the user says \"ask <name>\" or \"tell <name> ...\", that is "
        "a handoff: pick the right teammate from the roster below, message them "
        "with message_agent, and report back naming which agent replied. Message "
        "ONE clearly relevant teammate; don't fan out to several unless the user "
        "explicitly asked.\n"
        f'When YOU receive a "Message from 🤖 <name> (@<handle>):" message, a '
        "teammate agent is talking to you (not the user): address them, reply "
        "concisely via message_agent to their handle, and if it is a pure FYI "
        "with nothing to add, staying silent is fine — never ping-pong "
        "acknowledgements.\n"
        f"You are `@{handle}`. Your teammates (live roster; roles from their "
        "profiles, and in [brackets] the skill domains they actually have "
        "installed — route a handoff to the teammate whose domains match the "
        "work, not just whoever was named):\n"
        f"{roster_block}"
        + _remote_paragraph(root)
        + _peer_paragraph(root)
    )


def get_bot_mode_protocol_section(home: str | os.PathLike | None = None, *, force_refresh: bool = False) -> str:
    """Cached probe entry point — one filesystem pass per (process, home).

    ``home`` should be the AGENT'S OWN resolved home (session-db derived),
    not the ambient HERMES_HOME — build threads can lose the ContextVar
    override and the env var would then name the wrong profile.
    """
    resolved = str(home) if home else (os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes"))
    with _lock:
        if force_refresh or resolved not in _cached:
            try:
                _cached[resolved] = _build_section(Path(resolved))
            except Exception:
                _cached[resolved] = ""
        return _cached[resolved]


# ── capability epoch ─────────────────────────────────────────────────────────
#
# Bot Chat sessions are effectively eternal — the "new sessions come along
# often" assumption behind build-once system prompts does not hold. When the
# user changes a bot's capabilities (skills, toolsets, MCP servers, SOUL) or
# the teammate roster changes, they expect the change to work on the NEXT
# message. The fingerprint below hashes exactly that capability surface; the
# built Bot Chat prompt embeds it, and the restore path in
# agent/conversation_loop.py rebuilds the prompt when the stored epoch no
# longer matches the disk state. This is the /model exception applied to
# capabilities: a LOUD, USER-INITIATED, once-per-change cache break — never
# a per-turn drift (unchanged state hashes identically and the stored bytes
# are reused verbatim).

_EPOCH_PREFIX = "Capability epoch: "
_EPOCH_RE_TEXT = r"Capability epoch: ([0-9a-f]{12})"


def capability_fingerprint(home: str | os.PathLike | None = None) -> str:
    """12-hex digest of the capability surface for ``home``'s profile.

    Sources: the profile's disabled skills + enabled toolsets + MCP server
    config (config.yaml), SOUL.md bytes, installed skill names, and the
    Bot-Mode roster (managed profile names). Deliberately NOT cached — the
    whole point is detecting on-disk drift; callers compare it against the
    epoch embedded in a stored prompt. Never raises.
    """
    import hashlib
    import json

    resolved = Path(str(home) if home else (os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes")))
    surface: dict = {}
    try:
        # Canonical loader (managed overlay + env expansion + normalization),
        # scoped to the bot's home via the override the loaders already honor.
        from hermes_cli.config import load_config_readonly
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        token = set_hermes_home_override(str(resolved))
        try:
            cfg = load_config_readonly() or {}
        finally:
            reset_hermes_home_override(token)
        skills_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
        tools_cfg = cfg.get("tools") if isinstance(cfg.get("tools"), dict) else {}
        skills_cfg = skills_cfg or {}
        tools_cfg = tools_cfg or {}
        surface["disabled_skills"] = sorted(str(s).lower() for s in (skills_cfg.get("disabled") or []))
        surface["enabled_toolsets"] = sorted(str(t) for t in (tools_cfg.get("enabled_toolsets") or []))
        mcp = cfg.get("mcp_servers")
        surface["mcp"] = json.dumps(mcp, sort_keys=True, default=str) if isinstance(mcp, dict) else ""
    except Exception:
        pass
    try:
        soul = resolved / "SOUL.md"
        surface["soul"] = hashlib.sha256(soul.read_bytes()).hexdigest() if soul.is_file() else ""
    except Exception:
        surface["soul"] = ""
    try:
        names = []
        skills_root = resolved / "skills"
        if skills_root.is_dir():
            for skill_md in skills_root.glob("**/SKILL.md"):
                names.append(str(skill_md.parent.relative_to(skills_root)))
        surface["skills"] = sorted(names)
    except Exception:
        surface["skills"] = []
    try:
        root = _hermes_root(resolved)
        surface["roster"] = sorted(n for n, d in _roster(root) if _is_bot_managed(d))
        # Roles are part of the messaging surface: renaming a bot or editing
        # a profile description must refresh eternal Bot Chat prompts so the
        # roster block teammates pick recipients from stays current.
        surface["roster_roles"] = sorted(
            f"{n}:{_profile_role(d)}" for n, d in _roster(root)
        )
        # Teammate CAPABILITY tags are rendered into the roster block too, so
        # they must be hashed here or they would never refresh: installing a
        # skill on `researcher` has to invalidate every OTHER bot's eternal
        # prompt, not just researcher's own (the `skills` key above only
        # covers this agent's home). Without this, every teammate would route
        # handoffs off a capability list frozen at prompt-build time.
        surface["roster_capabilities"] = sorted(
            f"{n}:{','.join(_profile_capabilities(d))}" for n, d in _roster(root)
        )
    except Exception:
        surface["roster"] = []
    # Protocol​-text version salt: bumping this refreshes every eternal Bot
    # Chat prompt ONCE so existing bots adopt a new protocol section (e.g.
    # the v2 message_agent tool replacing the shellout instructions).
    # v3: roster lines carry capability tags + the routing instruction.
    surface["protocol_version"] = 3
    try:
        # Peer gateways are part of the messaging surface: registering one
        # must refresh eternal Bot Chat prompts so the cross-machine DM
        # paragraph appears on the next message.
        surface["peers"] = _peers(_hermes_root(resolved))
    except Exception:
        surface["peers"] = []
    try:
        # The Desktop relay roster is part of the messaging surface too:
        # connecting/disconnecting a machine, or agents appearing on one,
        # must refresh eternal Bot Chat prompts the same way.
        from tools.bot_relay import read_remote_roster

        surface["remote_roster"] = sorted(
            f"{r['connection_id']}:{r['profile']}:{r['title']}"
            for r in read_remote_roster(_hermes_root(resolved))
        )
    except Exception:
        surface["remote_roster"] = []
    try:
        blob = json.dumps(surface, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:12]
    except Exception:
        return "unavailable"


def epoch_line(home: str | os.PathLike | None = None) -> str:
    """The epoch stamp appended to a Bot Chat prompt."""
    return f"{_EPOCH_PREFIX}{capability_fingerprint(home)}"


def stored_prompt_capability_stale(stored_prompt: str, home: str | os.PathLike | None = None) -> bool:
    """True when ``stored_prompt`` is a Bot Chat prompt whose embedded
    capability epoch no longer matches the current disk state.

    Non-Bot-Chat prompts (no epoch stamp) are never stale by this check.
    Fails closed to "not stale" — a broken probe must never turn into a
    rebuild-every-turn cache burner.
    """
    import re

    try:
        m = re.search(_EPOCH_RE_TEXT, stored_prompt or "")
        if not m:
            return False
        current = capability_fingerprint(home)
        if current == "unavailable":
            return False
        return m.group(1) != current
    except Exception:
        return False


def stored_bot_chat_prompt_needs_upgrade(stored_prompt: str, home: str | os.PathLike | None = None) -> bool:
    """True when a Bot Chat session's stored prompt PREDATES this feature.

    Legacy Bot Chats (created before bundling / this epoch mechanism)
    persisted prompts with no protocol section and no epoch stamp; without
    an explicit upgrade they would be stranded forever — the staleness check
    above only fires on stamped prompts. This is a one-time migration per
    legacy session: the caller must only invoke it for sessions titled
    "Bot Chat", and only rebuilds when the probe would actually emit a
    section (a profile whose SOUL.md already carries the legacy plugin-side
    append keeps its protocol-free prompt — rebuilding those would loop,
    since the probe stays silent and the rebuilt prompt would be unstamped
    again). Fails closed to "no upgrade".
    """
    try:
        if _EPOCH_PREFIX in (stored_prompt or ""):
            return False
        if _PROTOCOL_HEADING in (stored_prompt or ""):
            return False
        # Only upgrade when the rebuild would actually add the section —
        # this is what guarantees the rebuilt prompt carries a stamp and
        # the upgrade can never re-fire.
        return bool(get_bot_mode_protocol_section(home))
    except Exception:
        return False


def _reset_cache_for_tests() -> None:
    with _lock:
        _cached.clear()
