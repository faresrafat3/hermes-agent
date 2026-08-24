"""Tests for GoalManager.restore_after_resume() — M2 of the /goal long-horizon project.

A goal that was mid-flight when the process died / tab closed / session was
compressed must re-arm when the SESSION is resumed, without the user knowing
goals exist. Contract under test:

- Only ``active`` goals fire; paused/done/cleared never do.
- Stale wait barriers (dead pid, expired deadline, dead registry session)
  clear instead of parking forever across downtime.
- Genuinely live barriers keep the goal parked (no turn burned).
- The returned prompt is the canonical continuation text carrying the goal.
"""

from __future__ import annotations

import contextlib
import time
from unittest.mock import patch

import pytest


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME so state_meta writes don't clobber the real one."""
    from pathlib import Path

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_cli import goals

    goals._DB_CACHE.clear()
    yield home
    goals._DB_CACHE.clear()


def _live_barriers(pid_alive: bool, session_waiting: bool):
    """Patch both liveness lookups goals.py consults for wait barriers."""
    return (
        patch("hermes_cli.goals._pid_alive", return_value=pid_alive),
        patch("hermes_cli.goals._session_waiting", return_value=session_waiting),
    )


class TestRestoreAfterResume:
    def test_active_goal_restores_with_prompt(self, hermes_home):
        """The headline M2 behavior: active goal + session resume → loop re-arms."""
        from hermes_cli.goals import GoalManager

        # Simulate a goal persisted before a crash/restart.
        GoalManager(session_id="resume-sid").set("finish the migration")
        assert GoalManager(session_id="resume-sid").is_active()

        # ...the process died; a fresh manager loads the same persisted state.
        mgr = GoalManager(session_id="resume-sid")
        restored, prompt, note = mgr.restore_after_resume()

        assert restored is True
        assert prompt is not None and "finish the migration" in prompt
        assert "Goal restored" in note

    def test_paused_goal_stays_paused(self, hermes_home):
        """A user-paused goal must not auto-fire on session resume."""
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="paused-sid")
        mgr.set("careful work")
        mgr.pause(reason="user-paused")

        restored, prompt, _note = mgr.restore_after_resume()
        assert restored is False
        assert prompt is None
        assert mgr.state is not None and mgr.state.status == "paused"

    def test_done_goal_never_fires(self, hermes_home):
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="done-sid")
        mgr.set("already finished")
        mgr.mark_done("judge said done")

        restored, prompt, _note = mgr.restore_after_resume()
        assert restored is False
        assert prompt is None

    def test_no_goal_is_a_clean_noop(self, hermes_home):
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="empty-sid")
        restored, prompt, note = mgr.restore_after_resume()
        assert restored is False
        assert prompt is None
        assert note == ""

    def test_dead_pid_barrier_clears_across_downtime(self, hermes_home):
        """Parked on pid N → process restarted → pid is gone → barrier clears,
        the goal fires instead of parking on a ghost forever."""
        from hermes_cli.goals import GoalManager, save_goal

        mgr = GoalManager(session_id="pid-sid")
        state = mgr.set("deploy after build")
        state.waiting_on_pid = 2**22  # effectively never alive
        state.waiting_reason = "build proc"
        save_goal(mgr.session_id, state)

        # Fresh manager = post-restart load; liveness says the pid is dead.
        mgr2 = GoalManager(session_id="pid-sid")
        p1, p2 = _live_barriers(pid_alive=False, session_waiting=False)
        with p1, p2:
            restored, prompt, _note = mgr2.restore_after_resume()

        assert restored is True
        assert prompt is not None
        assert mgr2.state is not None and mgr2.state.waiting_on_pid is None

    def test_expired_deadline_barrier_clears(self, hermes_home):
        """waiting_until in the past (downtime outlasted the backoff) clears."""
        from hermes_cli.goals import GoalManager, save_goal

        mgr = GoalManager(session_id="until-sid")
        state = mgr.set("retry after cooldown")
        state.waiting_until = 1.0  # epoch — long past
        state.waiting_reason = "rate-limit"
        save_goal(mgr.session_id, state)

        mgr2 = GoalManager(session_id="until-sid")
        restored, prompt, _note = mgr2.restore_after_resume()
        assert restored is True
        assert mgr2.state is not None and mgr2.state.waiting_until == 0.0

    def test_live_barrier_stays_parked_without_burning_turn(self, hermes_home):
        """A still-live wait stays parked: restore returns False and no judge
        call happens (turns_used unchanged)."""
        from hermes_cli.goals import GoalManager, save_goal

        mgr = GoalManager(session_id="live-sid")
        state = mgr.set("wait for CI then continue")
        state.waiting_on_pid = 2**22
        state.waiting_reason = "CI poller"
        save_goal(mgr.session_id, state)

        mgr2 = GoalManager(session_id="live-sid")
        p1, p2 = _live_barriers(pid_alive=True, session_waiting=True)
        with p1, p2:
            restored, prompt, note = mgr2.restore_after_resume()

        assert restored is False
        assert prompt is None
        assert "parked" in note.lower() or "⏳" in note
        assert mgr2.state is not None
        assert mgr2.state.waiting_on_pid == 2**22  # untouched
        assert mgr2.state.turns_used == 0

    def test_future_deadline_stays_parked_then_fires_later(self, hermes_home):
        """A future waiting_until keeps the goal parked now; once it passes,
        the same restore path fires. (Time moved across downtime.)"""
        from hermes_cli.goals import GoalManager, load_goal, save_goal

        sid = "future-sid"
        mgr = GoalManager(session_id=sid)
        state = mgr.set("backoff then continue")
        state.waiting_until = time.time() + 3600
        state.waiting_reason = "cooling down"
        save_goal(sid, state)

        mgr2 = GoalManager(session_id=sid)
        restored, prompt, note = mgr2.restore_after_resume()
        assert restored is False and prompt is None
        assert "⏳" in note or "parked" in note.lower()

        # Time passes (simulated downtime longer than the barrier)...
        reloaded = load_goal(sid)
        assert reloaded is not None
        reloaded.waiting_until = time.time() - 1
        save_goal(sid, reloaded)

        mgr3 = GoalManager(session_id=sid)
        restored3, prompt3, _n = mgr3.restore_after_resume()
        assert restored3 is True and prompt3 is not None

    def test_restore_persists_cleared_barriers(self, hermes_home):
        """Barrier clearing must be SAVED — a second manager must not see the
        stale barrier again (regression guard for write-through)."""
        from hermes_cli.goals import GoalManager, load_goal, save_goal

        sid = "persist-sid"
        mgr = GoalManager(session_id=sid)
        state = mgr.set("one shot")
        state.waiting_until = 1.0
        save_goal(sid, state)

        mgr2 = GoalManager(session_id=sid)
        mgr2.restore_after_resume()

        reloaded = load_goal(sid)
        assert reloaded is not None
        assert reloaded.waiting_until == 0.0
        assert reloaded.waiting_reason is None

    def test_restored_prompt_is_user_role_safe(self, hermes_home):
        """Prompt-caching invariant: the continuation text is plain user-role
        prose — no system markers, non-empty, carries the goal verbatim."""
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="safe-sid")
        mgr.set("port the exporter")
        restored, prompt, _note = mgr.restore_after_resume()
        assert restored and prompt
        assert "port the exporter" in prompt
        assert not prompt.lstrip().lower().startswith(("system:", "<system"))

    def test_context_manager_helper_is_not_used_as_with_target(self, hermes_home):
        """Guard against a footgun: _live_barriers returns two independent
        patchers (a tuple), NOT one composite context manager."""
        p1, p2 = _live_barriers(True, True)
        assert hasattr(p1, "__enter__") and hasattr(p2, "__enter__")
        with contextlib.ExitStack() as stack:
            stack.enter_context(p1)
            stack.enter_context(p2)
