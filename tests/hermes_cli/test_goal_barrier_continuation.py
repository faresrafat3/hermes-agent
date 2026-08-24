"""M2 idle continuation: barrier-just-cleared goals re-fire without user input.

The stuck-state scenario this kills: `/goal wait 300` parks the loop → the
deadline passes while the session sits idle → nothing re-pokes the goal until
the user types. barrier_just_cleared_prompt() + the CLI idle hook fix that.

Contract:
- Fires exactly ONCE per clearing (waiting_since is the once-marker).
- Never fires for paused/done/no-goal, or while a barrier is still live.
- waiting_reason folds into last_reason as "resumed after wait: ...".
"""

from __future__ import annotations

import time

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


class TestBarrierJustClearedPrompt:
    def test_fires_once_after_deadline_clears(self, hermes_home):
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="bc1")
        mgr.set("continue after cooldown")
        # Park via the real API, then simulate the deadline passing during
        # downtime (waiting_since stays as the once-marker).
        state = mgr.wait_for_seconds(60, reason="rate-limit")
        state.waiting_until = time.time() - 1
        from hermes_cli.goals import save_goal
        save_goal("bc1", state)

        fresh = GoalManager(session_id="bc1")
        prompt = fresh.barrier_just_cleared_prompt()
        assert prompt is not None and "continue after cooldown" in prompt

        # Second probe: already fired — no duplicate.
        assert fresh.barrier_just_cleared_prompt() is None

    def test_live_barrier_never_fires(self, hermes_home):
        from hermes_cli.goals import GoalManager, save_goal

        mgr = GoalManager(session_id="bc2")
        state = mgr.set("wait for CI")
        state.waiting_until = time.time() + 3600
        save_goal("bc2", state)

        fresh = GoalManager(session_id="bc2")
        assert fresh.barrier_just_cleared_prompt() is None
        assert fresh.state.waiting_until > time.time()

    def test_paused_goal_never_fires(self, hermes_home):
        from hermes_cli.goals import GoalManager, save_goal

        mgr = GoalManager(session_id="bc3")
        state = mgr.set("careful")
        state.waiting_until = 1.0  # stale deadline
        mgr.pause(reason="user-paused")  # clears barriers AND pauses

        fresh = GoalManager(session_id="bc3")
        assert fresh.barrier_just_cleared_prompt() is None

    def test_waiting_reason_folds_into_last_reason(self, hermes_home):
        from hermes_cli.goals import GoalManager, load_goal, save_goal

        mgr = GoalManager(session_id="bc4")
        mgr.set("g")
        mgr.wait_on(2**22, reason="build proc")
        # Simulate the pid dying during downtime: fresh manager + liveness
        # says dead. barrier_just_cleared_prompt clears via _pid_alive.
        fresh = GoalManager(session_id="bc4")
        with patch_liveness(pid_alive=False):
            prompt = fresh.barrier_just_cleared_prompt()
        assert prompt is not None
        reloaded = load_goal("bc4")
        assert "resumed after wait" in (reloaded.last_reason or "")
        assert reloaded.waiting_reason is None
        assert reloaded.waiting_since == 0.0

    def test_no_prior_park_is_a_clean_none(self, hermes_home):
        """A goal that was never parked produces no spurious fire."""
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="bc5")
        mgr.set("never parked")
        assert mgr.barrier_just_cleared_prompt() is None

    def test_stop_waiting_preserves_the_once_marker(self, hermes_home):
        """Explicit stop_waiting (e.g. /goal unwait) keeps waiting_since so the
        idle hook still fires — same contract as auto-clears."""
        from hermes_cli.goals import GoalManager, load_goal

        mgr = GoalManager(session_id="bc6")
        mgr.set("g")
        mgr.wait_on(2**22, reason="watch")

        fresh = GoalManager(session_id="bc6")
        assert fresh.stop_waiting() is True
        reloaded = load_goal("bc6")
        assert reloaded.waiting_since > 0  # marker kept
        assert fresh.barrier_just_cleared_prompt() is not None


def patch_liveness(*, pid_alive: bool):
    from unittest.mock import patch

    return patch("hermes_cli.goals._pid_alive", return_value=pid_alive)
