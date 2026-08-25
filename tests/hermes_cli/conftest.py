"""Fixtures shared across hermes_cli kanban tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def all_assignees_spawnable(monkeypatch):
    """Pretend every assignee maps to a real Hermes profile.

    Most dispatcher tests use synthetic assignees ("alice", "bob") that
    don't correspond to actual profile directories on disk. Without this
    patch, the dispatcher's profile-exists guard (PR #20105) routes
    those tasks into ``skipped_nonspawnable`` instead of spawning, which
    would break tests that assert spawn behavior.
    """
    from hermes_cli import profiles
    monkeypatch.setattr(profiles, "profile_exists", lambda name: True)


@pytest.fixture(autouse=True)
def _suppress_concurrent_hermes_gate(request, monkeypatch):
    """Default ``_detect_concurrent_hermes_instances`` to ``[]`` for every test.

    The Windows update path now refuses to proceed when another
    ``hermes.exe`` is detected (issue #26670). On a developer's Windows
    machine running the test suite via ``hermes`` itself, this would
    flag the running agent as a concurrent instance and abort every
    ``cmd_update`` test. Tests that want to exercise the gate explicitly
    re-patch ``_detect_concurrent_hermes_instances`` with their own
    return value — autouse here gives a clean default without touching
    the rest of the suite.

    Tests that need to call the REAL function (e.g. unit tests for the
    helper itself) opt out with ``@pytest.mark.real_concurrent_gate``.
    """
    if request.node.get_closest_marker("real_concurrent_gate"):
        return
    try:
        from hermes_cli import main as _cli_main
    except Exception:
        return
    # raising=False: under pytest's per-test spawn isolation, a concurrent
    # xdist worker importing a module that transitively touches hermes_cli.main
    # can briefly expose a partially-initialized module object here — one where
    # _detect_concurrent_hermes_instances isn't defined yet. A bare setattr
    # would raise AttributeError and error the (unrelated) test. The attribute
    # always exists once main.py finishes importing, so a no-op when it's
    # transiently absent is the correct, race-free default.
    monkeypatch.setattr(
        _cli_main,
        "_detect_concurrent_hermes_instances",
        lambda *_a, **_k: [],
        raising=False,
    )


_UPDATE_PIPELINE_TEST_MODULES = (
    "test_cmd_update",
    "test_update_yes_flag",
    "test_update_autostash",
    "test_update_head_moved_gate",
)


@pytest.fixture(autouse=True)
def _update_pipeline_gateway_inert(request, monkeypatch):
    """Make the update pipeline's gateway-kill surface inert — scoped to the
    update-family test modules ONLY.

    Measured live 2026-08-24 on fares/local-patches (a box running the real
    fleet): these tests drive the REAL ``hermes update`` pipeline against the
    LIVE checkout. After the simulated pull,
    ``_purge_stale_hermes_modules()`` drops every cached hermes_cli/gateway
    module from sys.modules — killing both module-level mocks and any mock a
    plain fixture set earlier. The restart phase's function-level imports then
    re-execute the real hermes_cli.gateway, whose systemd discovery finds the
    machine's actual hermes-gateway.service MainPID and attempts a real
    SIGTERM on it (blocked by the conftest live-system guard → spurious exit
    1; green in CI only because CI runs no fleet).

    The purge is neutered because no pull actually happens under pytest —
    there is nothing stale to evict — which keeps per-test monkeypatches
    alive for the whole run. Scoped to the update-family modules because the
    purge-neutering breaks tests that assert the purge itself
    (test_update_stale_module_purge) and would silently change behavior for
    unrelated suites in this directory.
    """
    node_module = request.module.__name__.rsplit(".", 1)[-1]
    if node_module not in _UPDATE_PIPELINE_TEST_MODULES:
        yield
        return

    import hermes_cli.gateway as hermes_gateway

    def _no_purge() -> None:
        return None

    monkeypatch.setattr(
        "hermes_cli.update_cmd._purge_stale_hermes_modules", _no_purge
    )
    monkeypatch.setattr(hermes_gateway, "find_gateway_pids", lambda *a, **k: [])
    monkeypatch.setattr(
        hermes_gateway, "supports_systemd_services", lambda: False
    )
    monkeypatch.setattr(
        hermes_gateway, "find_profile_gateway_processes", lambda *a, **k: []
    )
    monkeypatch.setattr(
        hermes_gateway, "_get_service_pids", lambda *a, **k: set()
    )
    monkeypatch.setattr(
        hermes_gateway, "_escalate_wedged_gateway", lambda pid, **k: True
    )
    monkeypatch.setattr(
        hermes_gateway, "_graceful_restart_via_sigusr1", lambda pid, **k: True
    )
    try:
        import gateway.status as gw_status

        monkeypatch.setattr(
            gw_status, "terminate_pid", lambda pid, **k: None, raising=False
        )
    except Exception:
        pass
    yield

