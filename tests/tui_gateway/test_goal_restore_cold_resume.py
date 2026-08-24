"""Integration: session.resume cold path re-arms a persisted ACTIVE /goal.

The marker auto-continue path already has its own coverage; these pin the M2
addition in _maybe_schedule_auto_continue: when there is NO interrupted-turn
marker but the session carries a persisted active goal, the goal-restore
scheduler fires and dispatches the canonical continuation through
_run_prompt_submit. Paused goals and goal-less sessions stay no-ops.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


def _session(home):
    return {
        "profile_home": str(home),
        "history_lock": __import__("threading").Lock(),
        "running": False,
        "created_at": 12345.0,
    }


class TestGoalRestoreOnColdResume:
    def test_active_goal_schedules_goal_restore(self, hermes_home):
        """No turn marker + persisted active goal → goal_restore scheduled and
        the continuation prompt reaches _run_prompt_submit."""
        from hermes_cli.goals import GoalManager
        from tui_gateway import server as gw

        GoalManager(session_id="cold-sid").set("finish the port")

        # The real _run_prompt_submit runs the full turn + judge loop; we only
        # need to prove the goal-restore path DISPATCHED the continuation.
        # Patch at the dispatch boundary and inspect the prompt there.
        session = _session(hermes_home)
        session["agent"] = SimpleNamespace(
            last_activity_ts=0.0,
            model="test",
            context_compressor=None,
            interim_assistant_callback=None,
            clear_interrupt=lambda: None,
            run_conversation=lambda user_message, system_message=None, **kw: {
                "final_response": "ok", "messages": []
            },
        )
        session["session_key"] = "cold-sid"
        session["history"] = []
        # Run the kickoff thread INLINE (server.py itself captures _RealThread
        # for the same reason): deterministic, no daemon-loop races.
        submitted = []
        captured_thread = {}

        class InlineThread:
            def __init__(self, *, target, daemon=False):
                captured_thread["target"] = target
                self.daemon = daemon

            def start(self):
                captured_thread["target"]()

        with (
            patch.object(gw, "read_turn_marker", return_value=None),
            patch.object(gw, "_start_agent_build", return_value=None),
            patch.object(gw, "_wait_agent", return_value=None) as wait_mock,
            patch.object(
                gw, "_run_prompt_submit",
                side_effect=lambda rid, sid, sess, text, **kw: submitted.append(text),
            ),
            # Stop the turn after dispatch: the second _run_prompt_submit call
            # is the goal-judge continuation; raising ends the inline thread
            # cleanly (its exception is caught by our stub wrapper below? no —
            # it propagates but we already captured what we need).
            patch.object(gw.threading, "Thread", InlineThread),
        ):
            result = gw._maybe_schedule_auto_continue("s1", session, "cold-sid")
            assert wait_mock.called  # kickoff reached the build-wait step

        assert result is not None
        assert result.get("kind") == "goal_restore"
        assert any("finish the port" in t for t in submitted), submitted

    def test_paused_goal_is_a_noop(self, hermes_home):
        from hermes_cli.goals import GoalManager
        from tui_gateway import server as gw

        mgr = GoalManager(session_id="cold-paused")
        mgr.set("careful work")
        mgr.pause(reason="user-paused")

        session = _session(hermes_home)
        with (
            patch.object(gw, "read_turn_marker", return_value=None),
            patch.object(gw, "_run_prompt_submit", side_effect=AssertionError("must not fire")),
        ):
            result = gw._maybe_schedule_auto_continue("s2", session, "cold-paused")
        assert result is None

    def test_no_goal_is_a_noop(self, hermes_home):
        from tui_gateway import server as gw

        session = _session(hermes_home)
        with patch.object(gw, "read_turn_marker", return_value=None):
            result = gw._maybe_schedule_auto_continue("s3", session, "no-goal-sid")
        assert result is None

    def test_marker_still_wins_when_both_present(self, hermes_home):
        """Precedence guard: an interrupted-turn marker takes the classic path;
        the goal restore must NOT double-fire on top of it."""
        from hermes_cli.goals import GoalManager
        from tui_gateway import server as gw

        GoalManager(session_id="both-sid").set("also a live goal")

        session = _session(hermes_home)
        marker = {"started_at": __import__("time").time(), "attempts": 0, "prompt": "orig"}
        calls = []
        with (
            patch.object(gw, "read_turn_marker", return_value=marker),
            patch.object(gw, "_schedule_marker_auto_continue") as sched,
            patch.object(gw, "_maybe_schedule_goal_restore", side_effect=lambda *a: calls.append(1)),
        ):
            gw._maybe_schedule_auto_continue("s4", session, "both-sid")

        sched.assert_called_once()          # marker path taken…
        assert not calls                    # …goal restore never consulted.
