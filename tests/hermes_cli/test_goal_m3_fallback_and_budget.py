"""Tests for M3 of /goal long-horizon: judge fallback + per-goal token budget.

Judge fallback (auxiliary.goal_judge.fallback_provider/.fallback_model):
- On primary transport failure the fallback provider/model are tried before
  failing open to "continue".
- Without a configured fallback, behavior is unchanged (immediate fail-open).
- A fallback success yields a real verdict, not a transport failure.

Token budget (per-goal):
- Crossing token_budget auto-pauses with a usage_limited reason.
- Under budget keeps going; usage accumulates monotonically.
- No budget = unchanged behavior. Budget survives persistence round-trips.
"""

from __future__ import annotations

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


def _resp(content='{"done": true, "reason": "all good"}'):
    resp = MagicMock()
    resp.choices[0].message.content = content
    return resp


class TestJudgeFallback:
    def test_fallback_used_on_primary_transport_failure(self, hermes_home):
        """Primary raises → configured fallback is consulted and its verdict
        counts (no transport_failed flag)."""
        from hermes_cli.goals import judge_goal

        calls = []

        def fake_call_llm(*args, **kwargs):
            calls.append((kwargs.get("provider"), kwargs.get("model")))
            if kwargs.get("provider") == "deepseek":
                return _resp()
            raise RuntimeError("primary endpoint down")

        with (
            patch(
                "hermes_cli.goals._goal_judge_fallback",
                return_value=("deepseek", "deepseek-v4-flash"),
            ),
            patch(
                "agent.auxiliary_client.call_llm",
                side_effect=fake_call_llm,
            ),
        ):
            verdict, reason, parse_failed, wait, transport_failed = judge_goal(
                "write tests", "tests written and passing"
            )

        assert verdict == "done"
        assert transport_failed is False
        assert ("deepseek", "deepseek-v4-flash") in calls

    def test_no_fallback_keeps_fail_open(self, hermes_home):
        """No fallback configured → single failure fails open exactly as before."""
        from hermes_cli.goals import judge_goal

        with (
            patch("hermes_cli.goals._goal_judge_fallback", return_value=(None, None)),
            patch("agent.auxiliary_client.call_llm", side_effect=RuntimeError("boom")),
        ):
            verdict, reason, parse_failed, wait, transport_failed = judge_goal(
                "g", "r"
            )

        assert verdict == "continue"
        assert transport_failed is True
        assert parse_failed is False

    def test_fallback_failure_also_fails_open(self, hermes_home):
        """Primary AND fallback both fail → fail-open (never raises)."""
        from hermes_cli.goals import judge_goal

        with (
            patch(
                "hermes_cli.goals._goal_judge_fallback",
                return_value=("openrouter", "google/gemini-3-flash-preview"),
            ),
            patch("agent.auxiliary_client.call_llm", side_effect=RuntimeError("down")),
        ):
            verdict, reason, parse_failed, wait, transport_failed = judge_goal(
                "g", "r"
            )
        assert verdict == "continue" and transport_failed is True

    def test_fallback_resolver_reads_config(self, hermes_home):
        from hermes_cli import goals

        with patch("hermes_cli.config.load_config", return_value={
            "auxiliary": {"goal_judge": {
                "fallback_provider": "nous", "fallback_model": "Hermes-5"
            }}
        }):
            assert goals._goal_judge_fallback() == ("nous", "Hermes-5")
        with patch("hermes_cli.config.load_config", return_value={}):
            assert goals._goal_judge_fallback() == (None, None)


class TestTokenBudget:
    def _manager_with_budget(self, session_id, budget):
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id=session_id)
        state = mgr.set("long running work")
        state.token_budget = budget
        # Persist the mutation (mirrors set_token_budget's save_goal).
        from hermes_cli.goals import save_goal
        save_goal(session_id, state)
        return mgr

    def test_under_budget_continues(self, hermes_home):
        mgr = self._manager_with_budget("tb1", 100_000)
        mgr.agent = None  # no live usage source → tokens_used stays put
        decision = mgr.evaluate_after_turn("progress")
        assert decision["should_continue"] is True
        assert mgr.state.status == "active"

    def test_crossing_budget_pauses_with_usage_reason(self, hermes_home):
        mgr = self._manager_with_budget("tb2", 1_000)
        agent = MagicMock()
        agent.get_session_usage_snapshot = lambda: {"total": 1_500}
        mgr.agent = agent

        decision = mgr.evaluate_after_turn("progress")

        assert decision["should_continue"] is False
        assert mgr.state.status == "paused"
        assert "token budget exhausted" in mgr.state.paused_reason
        assert "1_500" in mgr.state.paused_reason or "1500" in mgr.state.paused_reason
        # The turn was still counted — spend happened.
        assert mgr.state.turns_used == 1

    def test_usage_accumulates_monotonically(self, hermes_home):
        mgr = self._manager_with_budget("tb3", 10_000)
        usage_total = 100
        mgr.agent = MagicMock()
        mgr.agent.get_session_usage_snapshot = lambda: {"total": usage_total}

        mgr.evaluate_after_turn("t1")
        # First turn: tokens_used takes the max(snapshot, current) → 100.
        assert mgr.state.tokens_used == 100
        usage_total = 250
        mgr.evaluate_after_turn("t2")
        assert mgr.state.tokens_used == 250

    def test_no_budget_is_unchanged(self, hermes_home):
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="tb4")
        mgr.set("no cap")
        mgr.agent = MagicMock()
        mgr.agent.get_session_usage_snapshot = lambda: {"total": 999_999}

        decision = mgr.evaluate_after_turn("progress")
        assert decision["should_continue"] is True
        assert mgr.state.status == "active"
        assert mgr.state.tokens_used == 0  # accounting skipped entirely

    def test_budget_survives_persistence(self, hermes_home):
        from hermes_cli.goals import GoalManager, load_goal

        mgr = self._manager_with_budget("tb5", 50_000)
        reloaded_mgr = GoalManager(session_id="tb5")
        state = load_goal("tb5")
        assert state.token_budget == 50_000
        assert state.tokens_used == 0

    def test_set_token_budget_api(self, hermes_home):
        from hermes_cli.goals import GoalManager, load_goal

        mgr = GoalManager(session_id="tb6")
        mgr.set("budgeted goal")
        mgr.set_token_budget(25_000)
        assert load_goal("tb6").token_budget == 25_000
        mgr.set_token_budget(None)  # clear
        assert load_goal("tb6").token_budget is None

    def test_set_token_budget_without_goal_raises_free(self, hermes_home):
        from hermes_cli.goals import GoalManager

        mgr = GoalManager(session_id="tb7")
        assert mgr.set_token_budget(100) is None  # clean no-op, no crash
