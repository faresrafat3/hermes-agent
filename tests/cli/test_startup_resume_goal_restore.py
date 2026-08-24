"""Startup --resume must re-arm a persisted ACTIVE /goal (M2 completion).

`hermes --resume <id>` goes through _preload_resumed_session, not the
mid-chat /resume handler — both paths must behave identically with respect
to goals: an active goal re-fires (queued into _pending_input), paused
goals stay paused, and the banner note is deferred so it renders after the
welcome text.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    from pathlib import Path

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_cli import goals

    goals._DB_CACHE.clear()
    yield home
    goals._DB_CACHE.clear()


def _make_cli(session_id: str) -> SimpleNamespace:
    """A minimal HermesCLI stand-in carrying every attribute
    _preload_resumed_session touches before reaching the goal-restore block."""
    from queue import Queue

    from unittest.mock import MagicMock

    return SimpleNamespace(
        session_id=session_id,
        _resumed=True,
        _session_db=MagicMock(),
        conversation_history=[],
        _resume_display_history=[],
        agent=None,
        _pending_input=Queue(),
        _goal_restore_pending_note=None,
        # _restore_* live on the concrete HermesCLI class (cli.py), not on
        # this mixin — stub them on directly.
        _restore_session_cwd=lambda meta, quiet=False: None,
        _restore_session_yolo=lambda meta, quiet=False: None,
        _restore_session_model=lambda meta, quiet=False: None,
        _resume_history_limit_error=lambda tip_only=False: None,
        _get_goal_manager=lambda: None,
        _console_print=lambda *a, **k: None,
    )


def _run_preload(cli):
    from hermes_cli.cli_agent_setup_mixin import CLIAgentSetupMixin

    CLIAgentSetupMixin._preload_resumed_session(cli)


class TestStartupResumeGoalRestore:
    def test_preload_restores_active_goal_and_queues_prompt(self, hermes_home):
        """Active goal + startup resume → prompt queued + deferred note set."""
        from hermes_cli.goals import GoalManager

        GoalManager(session_id="startup-sid").set("finish the port")

        cli = _make_cli("startup-sid")

        def real_goal_manager():
            return GoalManager(session_id=cli.session_id)

        cli._get_goal_manager = real_goal_manager
        # get_resume_conversations returns history so the restore branch runs.
        cli._session_db.resolve_resume_session_id = lambda sid: sid
        cli._session_db.get_resume_conversations = lambda sid: (
            [{"role": "user", "content": "hi"}], []
        )
        cli._session_db.reopen_session = lambda sid: None

        _run_preload(cli)

        assert cli._pending_input.qsize() == 1
        queued = cli._pending_input.get_nowait()
        assert "finish the port" in queued
        assert "Goal restored" in cli._goal_restore_pending_note

    def test_paused_goal_does_not_queue(self, hermes_home):
        from queue import Queue

        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="startup-paused")
        mgr.set("careful work")
        mgr.pause(reason="user-paused")

        cli = _make_cli("startup-paused")
        cli._pending_input = Queue()
        cli._get_goal_manager = lambda: GoalManager(session_id="startup-paused")
        cli._session_db.resolve_resume_session_id = lambda sid: sid
        cli._session_db.get_resume_conversations = lambda sid: (
            [{"role": "user", "content": "hi"}], []
        )
        cli._session_db.reopen_session = lambda sid: None

        _run_preload(cli)

        assert cli._pending_input.qsize() == 0
        assert cli._goal_restore_pending_note is None
