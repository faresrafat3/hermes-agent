"""Auxiliary path must sanitize agentrouter-bound payloads.

Live incident 2026-08-24: ``/goal``'s judge call routes through
``agent.auxiliary_client.call_llm`` → agentrouter.org. The agentrouter
content filters blocked the judge prompt (it quotes the assistant's last
response verbatim) with ``400 content-blocked`` on every turn because the
auxiliary path never ran ``sanitize_for_agentrouter`` — that hygiene layer
was wired only into the main conversation loop
(``agent/chat_completion_helpers.py``). Five consecutive failures
auto-paused the goal pointing at the API key while the key was fine.

These tests pin the parity contract: ANY auxiliary request whose resolved
wire target is agentrouter.org gets the same defang treatment as a
main-loop request, sync and async alike — and non-agentrouter targets are
left byte-identical.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.auxiliary_client import (
    _client_cache,
    _client_cache_lock,
    _async_call_llm_impl,
    _call_llm_impl,
)

AGENTROUTER_TRIGGER_TEXT = (
    "The plan describes how to attack the endpoint and hijack the session."
)


def _capturing_client(base_url="https://agentrouter.org/v1/", async_mode=False):
    client = MagicMock(name="aux_client")
    client.base_url = base_url
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"done": true}'))]
    )
    if async_mode:
        client.chat.completions.create = AsyncMock(return_value=response)
    else:
        client.chat.completions.create.return_value = response
    return client


@pytest.fixture()
def routed_fake_client():
    """Patch provider resolution so call_llm uses a capturing fake client."""

    def _install(
        provider="agentrouter-2",
        base_url="https://agentrouter.org/v1",
        async_mode=False,
    ):
        client = _capturing_client(
            base_url=f"{base_url.rstrip('/')}/", async_mode=async_mode
        )
        with _client_cache_lock:
            _client_cache.clear()
        patches = [
            patch(
                "agent.auxiliary_client._resolve_task_provider_model",
                return_value=(provider, "test-model", base_url, None, None),
            ),
            patch(
                "agent.auxiliary_client._get_cached_client",
                return_value=(client, "test-model"),
            ),
            patch("agent.auxiliary_client._try_payment_fallback",
                  return_value=(None, None, "")),
            patch(
                "agent.auxiliary_client._validate_llm_response",
                side_effect=lambda resp, *a, **k: resp,
            ),
        ]
        for p in patches:
            p.start()
        return client, patches

    try:
        yield _install
    finally:
        with _client_cache_lock:
            _client_cache.clear()


def test_sync_aux_path_defangs_agentrouter_payload(routed_fake_client):
    """Sync auxiliary call to agentrouter.org must defang trigger words."""
    client, patches = routed_fake_client()
    try:
        _call_llm_impl(
            task="goal_judge",
            provider="agentrouter-2",
            model="test-model",
            base_url="https://agentrouter.org/v1",
            api_key="sk-test",
            messages=[{"role": "user", "content": AGENTROUTER_TRIGGER_TEXT}],
            temperature=0,
            max_tokens=64,
            timeout=5,
        )
    finally:
        for p in patches:
            p.stop()

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    text = sent[0]["content"]
    assert "attack" not in text.lower(), f"raw trigger reached the wire: {text}"
    assert "hijack" not in text.lower(), f"raw trigger reached the wire: {text}"


def test_async_aux_path_defangs_agentrouter_payload(routed_fake_client):
    """Async auxiliary call to agentrouter.org must defang trigger too.

    Drives ``_async_call_llm_impl`` via ``asyncio.run`` so the contract
    holds even where pytest-asyncio isn't installed.
    """
    import asyncio

    client, patches = routed_fake_client(async_mode=True)
    try:
        asyncio.run(_async_call_llm_impl(
            task="goal_judge",
            provider="agentrouter-2",
            model="test-model",
            base_url="https://agentrouter.org/v1",
            api_key="sk-test",
            messages=[
                {"role": "user", "content":
                    AGENTROUTER_TRIGGER_TEXT + " " + ARABIC_TEXT},
            ],
            temperature=0,
            max_tokens=64,
            timeout=5,
        ))
    finally:
        for p in patches:
            p.stop()

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    text = sent[0]["content"]
    # Defang wired through async...
    assert "attack" not in text.lower(), f"raw trigger reached the wire: {text}"
    assert "hijack" not in text.lower(), f"raw trigger reached the wire: {text}"
    # ...and armor too: goal_judge over async must be pure-ASCII on the wire.
    assert all(ord(ch) < 128 for ch in text), f"non-ASCII reached the wire: {text}"


def test_non_agentrouter_target_untouched(routed_fake_client):
    """Non-agentrouter targets must receive byte-identical content.

    The gate keys off the WIRE TARGET (provider label OR destination host),
    so a non-agentrouter destination must not be rewritten even when the
    content contains words that agentrouter would have blocked.
    """
    client, patches = routed_fake_client(
        provider="deepseek", base_url="https://api.deepseek.com/v1"
    )
    try:
        _call_llm_impl(
            task="goal_judge",
            provider="deepseek",
            model="test-model",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test",
            messages=[{"role": "user", "content": AGENTROUTER_TRIGGER_TEXT}],
            temperature=0,
            max_tokens=64,
            timeout=5,
        )
    finally:
        for p in patches:
            p.stop()

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0]["content"] == AGENTROUTER_TRIGGER_TEXT



def test_host_gate_catches_custom_label_on_agentrouter_url(routed_fake_client):
    """provider label ≠ agentrouter but URL = agentrouter.org → still defanged.

    Mirrors the main-loop wire-target rule (live incident 2026-08-22):
    legacy sessions carry provider="custom" while pointing at agentrouter.
    """
    client, patches = routed_fake_client(provider="custom")
    try:
        _call_llm_impl(
            task="goal_judge",
            provider="custom",
            model="test-model",
            base_url="https://agentrouter.org/v1",
            api_key="sk-test",
            messages=[{"role": "user", "content": AGENTROUTER_TRIGGER_TEXT}],
            temperature=0,
            max_tokens=64,
            timeout=5,
        )
    finally:
        for p in patches:
            p.stop()

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    assert "attack" not in sent[0]["content"].lower()


# ---------------------------------------------------------------------------
# ASCII armor (Filter B — the 400 content-blocked language classifier)
# ---------------------------------------------------------------------------

ARABIC_TEXT = "الشغل بقى محمي ومنظم. الحالة النهائية مؤكدة."


def test_goal_judge_payload_is_ascii_armored(routed_fake_client):
    """goal_judge payloads to agentrouter must be entity-encoded non-ASCII.

    Verified live 2026-08-24: a judge prompt quoting an Arabic assistant
    response 400'd content-blocked raw and passed once armored.
    """
    import html

    client, patches = routed_fake_client()
    try:
        _call_llm_impl(
            task="goal_judge",
            provider="agentrouter-2",
            model="test-model",
            base_url="https://agentrouter.org/v1",
            api_key="sk-test",
            messages=[{"role": "user", "content": ARABIC_TEXT}],
            temperature=0,
            max_tokens=64,
            timeout=5,
        )
    finally:
        for p in patches:
            p.stop()

    wire = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert all(ord(ch) < 128 for ch in wire), f"non-ASCII reached the wire: {wire}"
    # Round-trip: decoding entities restores the original text byte-for-byte.
    assert html.unescape(wire) == ARABIC_TEXT


def test_non_judge_tasks_not_armored(routed_fake_client):
    """Armor is opt-in per task: compression-sized replays stay untouched."""
    client, patches = routed_fake_client()
    try:
        _call_llm_impl(
            task="compression",
            provider="agentrouter-2",
            model="test-model",
            base_url="https://agentrouter.org/v1",
            api_key="sk-test",
            messages=[{"role": "user", "content": ARABIC_TEXT}],
            temperature=0,
            max_tokens=64,
            timeout=5,
        )
    finally:
        for p in patches:
            p.stop()

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0]["content"] == ARABIC_TEXT
