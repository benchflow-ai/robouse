"""Gemini 4 Argon, Elorian Glimpse and the gemini-cli harness: the model ids and their metadata, prices (with the end of
Gemini 4 Argon's introductory price), which harness and model pairs run and which are refused before a trial, the
model gateway's Gemini route (thought signatures kept for every client, images in tool results sent as images), the
OpenRouter route's tool-result images, the gemini-cli launch (its own home and settings, its key, no web tools), its
stream-json trajectory, and a whole gemini-cli trial with a stand-in `gemini` program. No request leaves this machine:
the end-to-end checks use the scripted stand-ins in tests/model_standin.py."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from datetime import date
from pathlib import Path

import pytest

from robouse import harnesses
from robouse.harnesses import credentials, gemini_cli, models

ROOT = Path(__file__).resolve().parents[1]
ARC = ROOT / "tasks" / "arc-style" / "arc-gravity"
VISION = ROOT / "tasks" / "vision" / "arc-gravity-vision"
# a 1x1 PNG, base64
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
GEMINI_VARS = ("GEMINI_API_KEY", "GEMINI_API_BASE", "GOOGLE_GEMINI_BASE_URL", "OPENROUTER_API_KEY")


@pytest.fixture
def clean_env(monkeypatch):
    for var in (*GEMINI_VARS, "ROBOUSE_AGENT_IMAGES", "ROBOUSE_SPEND_CAP_USD", "ROBOUSE_PRICING"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("BENCHFLOW_PROVIDER_BASE_URL", raising=False)


# ---- models, prices and pairs ---------------------------------------------------------------------------------------


def test_gemini_and_openrouter_models_resolve_with_their_image_metadata() -> None:
    pytest.importorskip("benchflow")
    from robouse.harnesses.gateway import image_cap

    ref = models.resolve("claude-code", "gemini/gemini-4-argon")
    assert (ref.provider, ref.bare, models.accepts_images(ref), models.max_images(ref)) == (
        "gemini",
        "gemini-4-argon",
        True,
        3600,
    )
    assert image_cap(ref, True) == 3600 and image_cap(ref, False) == 0
    bare = models.resolve("gemini-cli", "gemini-4-argon")  # a bare id is Gemini CLI's own vendor's
    assert bare.id == "gemini/gemini-4-argon" and bare.meta == ref.meta
    assert models.canonical("gemini-cli", "gemini/gemini-4-argon") == ("gemini-cli", "gemini-4-argon")
    assert models.accepts_images(models.resolve("gemini-cli", "gemini-3.5-flash")) is True  # any Gemini model
    for model, cap in (("openrouter/google/gemini-4-argon", 3600), ("openrouter/elorian/glimpse", 0)):
        r = models.resolve("dimcode", model)
        assert (r.provider, models.accepts_images(r), models.max_images(r)) == ("openrouter", True, cap), model
    assert models.accepts_images(models.resolve("codex", "openrouter/some/unknown")) is None
    assert "GEMINI_API_KEY" in models.secret_env_names()


def test_prices_follow_gemini_4_argon_s_introductory_period(monkeypatch, tmp_path) -> None:
    from robouse.runner.cost import price_of

    monkeypatch.delenv("ROBOUSE_PRICING", raising=False)
    for model in ("gemini-4-argon", "google/gemini-4-argon"):
        intro, later = price_of(model, date(2026, 11, 30)), price_of(model, date(2026, 12, 1))
        assert intro and later, model
        assert (intro["input"], intro["output"], intro["cached_input"]) == (2.0, 10.0, 0.1)
        assert (later["input"], later["output"], later["cached_input"]) == (4.0, 20.0, 0.2)
    glimpse = price_of("elorian/glimpse")
    assert glimpse and (glimpse["input"], glimpse["output"], glimpse["cached_input"]) == (0.6, 3.0, 0.06)
    table = tmp_path / "pricing.json"  # a price table of one's own keeps plain entries
    table.write_text(json.dumps({"gemini-4-argon": {"input": 1.0, "output": 2.0}}))
    monkeypatch.setenv("ROBOUSE_PRICING", str(table))
    assert price_of("gemini-4-argon") == {"input": 1.0, "output": 2.0}
    table.write_text(json.dumps({"m": [{"input": 1.0, "output": 2.0, "until": "2026-01-31"}]}))
    assert price_of("m", date(2026, 2, 1)) is None  # every period has passed: no price, so no spend cap either


def test_pairs_that_cannot_run_are_refused_before_a_trial(monkeypatch, clean_env) -> None:
    pytest.importorskip("benchflow")
    from robouse.harnesses import interface as iface
    from robouse.runner.trial import check_model, image_input_plan

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    plan = check_model("gemini-cli", "")  # its own vendor: no gateway, so no provider settings to check
    assert (plan["harness"], plan["model"], plan["image_input"]) == ("gemini-cli", "gemini-4-argon", True)
    assert check_model("gemini-cli", "gemini/gemini-4-argon")["model"] == "gemini/gemini-4-argon"
    for model in ("openrouter/google/gemini-4-argon", "openrouter/elorian/glimpse", "glm/glm-5.3"):
        with pytest.raises(ValueError, match="gemini-cli runs only Gemini API models"):
            check_model("gemini-cli", model)
    with pytest.raises(RuntimeError, match=r"gemini does not \(gemini/gemini-4-argon runs on gemini-cli, claude-code"):
        check_model("codex", "gemini/gemini-4-argon")
    for model in ("openrouter/google/gemini-4-argon", "openrouter/elorian/glimpse"):
        with pytest.raises(RuntimeError, match="Codex needs a provider that serves the Responses API; openrouter"):
            check_model("codex", model)
    for harness in ("claude-code", "dimcode", "mini-swe-agent", "show-harness"):
        for model in ("gemini/gemini-4-argon", "openrouter/google/gemini-4-argon", "openrouter/elorian/glimpse"):
            plan = check_model(harness, model)  # priced, so the default $5 spend cap applies
            assert plan["model"] == model and plan["image_input"] is (harness != "mini-swe-agent"), (harness, model)
    with pytest.raises(ValueError, match="does not give gemini-cli the robo MCP server"):
        iface.check("gemini-cli", "mcp")
    monkeypatch.setenv("ROBOUSE_AGENT_IMAGES", "0")  # no gateway to remove the images: refused
    with pytest.raises(ValueError, match="gemini-cli with gemini/gemini-4-argon cannot run without image input"):
        image_input_plan("gemini-cli", "")
    monkeypatch.delenv("ROBOUSE_AGENT_IMAGES")
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(RuntimeError, match="needs GEMINI_API_KEY in the environment.*Google AI Studio"):
        check_model("claude-code", "gemini/gemini-4-argon")


# ---- the gateway's routes -------------------------------------------------------------------------------------------


def test_the_gemini_provider_takes_litellm_s_gemini_route_and_openrouter_the_openai_one() -> None:
    pytest.importorskip("benchflow")
    from benchflow.providers.litellm_config import resolve_litellm_route

    from robouse.harnesses import gateway

    reg = models.provider_registry()
    route = gateway.gemini_route(resolve_litellm_route("gemini/gemini-4-argon", {"GEMINI_API_KEY": "k"}), reg["gemini"])
    assert route.litellm_params == {"model": "gemini/gemini-4-argon", "api_key": "os.environ/GEMINI_API_KEY"}
    assert gateway.keeps_signatures(route, "anthropic-messages") and gateway.drops_thinking(
        route, reg["gemini"], "anthropic-messages"
    )
    assert not gateway.keeps_signatures(route, "openai-completions")
    assert not gateway.moves_tool_result_images(route, "anthropic-messages")  # LiteLLM sends them as images
    other = resolve_litellm_route("openrouter/elorian/glimpse", {"OPENROUTER_API_KEY": "k"})
    assert gateway.gemini_route(other, reg["openrouter"]) is other and other.upstream_model == "openai/elorian/glimpse"
    assert gateway.moves_tool_result_images(other, "anthropic-messages")
    assert not gateway.moves_tool_result_images(other, "openai-completions")
    assert not gateway.keeps_signatures(other, "anthropic-messages")


def test_tool_result_images_move_into_the_user_message() -> None:
    pytest.importorskip("litellm")
    from robouse.harnesses.providers import gateway_hook as H

    image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}
    content = [
        {"type": "tool_result", "tool_use_id": "a", "content": [image]},  # Claude Code's Read of a picture
        {"type": "tool_result", "tool_use_id": "b", "content": [{"type": "text", "text": "Read image"}, image]},
        {"type": "tool_result", "tool_use_id": "c", "content": "plain text"},
    ]
    body = {"messages": [{"role": "user", "content": "go"}, {"role": "user", "content": content}]}
    alias = body["messages"][1]["content"]  # LiteLLM can hold the same list twice
    assert H.move_tool_result_images(body) == 2 and body["messages"][1]["content"] is alias
    blocks = body["messages"][1]["content"]
    assert [b["type"] for b in blocks] == ["tool_result"] * 3 + ["text", "image", "text", "image"]
    assert all(c["type"] == "text" for b in blocks[:2] for c in b["content"]) and blocks[2]["content"] == "plain text"
    assert H.NOTE_MOVED in json.dumps(blocks[0]) and "tool call a:" in blocks[3]["text"]
    assert H.move_tool_result_images({"input": []}) == 0


def test_the_hook_keeps_thought_signatures_for_messages_clients() -> None:
    pytest.importorskip("litellm")
    from robouse.harnesses.providers import gateway_hook as H

    block = {
        "type": "tool_use",
        "id": "call_1",
        "name": "Bash",
        "input": {},
        "provider_specific_fields": {"signature": "s1"},
    }
    start = {"type": "content_block_start", "index": 1, "content_block": block}
    sse = f"event: content_block_start\ndata: {json.dumps(start)}\n\n"
    for chunk in (start, sse, sse.encode()):  # LiteLLM may pass an event, SSE text or bytes
        assert H.signed_tool_uses(H.stream_events(chunk)) == {"call_1": "s1"}
    whole = {"type": "message", "content": [{"type": "text", "text": "x"}, block]}
    assert H.signed_tool_uses([whole]) == {"call_1": "s1"}
    sent = {"type": "tool_use", "id": "call_1", "name": "Bash", "input": {}}  # the client dropped the field
    own = {
        "type": "tool_use",
        "id": "call_2",
        "name": "Bash",
        "input": {},
        "provider_specific_fields": {"signature": "s2"},
    }
    unknown = {"type": "tool_use", "id": "call_3", "name": "Bash", "input": {}}
    body = {"messages": [{"role": "assistant", "content": [sent, own, unknown]}]}
    assert H.restore_signatures(body, {"call_1": "s1", "call_2": "other"}) == 1
    assert (
        sent["provider_specific_fields"] == {"signature": "s1"} and own["provider_specific_fields"]["signature"] == "s2"
    )
    assert "provider_specific_fields" not in unknown
    hook = H.RobouseGateway()
    hook.keep_signatures = True

    async def stream():
        yield sse.encode()

    async def drain():
        return [c async for c in hook.async_post_call_streaming_iterator_hook(None, stream(), {})]

    assert asyncio.run(drain()) == [sse.encode()] and hook.signatures == {"call_1": "s1"}  # passed on unchanged
    assert H._data_uris({"inline_data": {"mime_type": "image/png", "data": PNG}}) == 1  # Gemini's image parts count


def _gateway_env(tmp_path: Path) -> dict:
    return {
        "_ROBOUSE_TRIAL_DIR": str(tmp_path / "trial"),
        "_ROBOUSE_IMAGE_INPUT": "1",
        "_ROBOUSE_SPEND_CAP_USD": "0",
        "PATH": "/usr/bin:/bin",
    }


def _messages(gw, messages: list, tools: list) -> list[dict]:
    """One streamed Anthropic Messages request through the gateway, with extended thinking as Claude Code asks for it;
    its content blocks, inputs filled in."""
    body = {"model": gw.model, "max_tokens": 2048, "stream": True, "tools": tools, "messages": messages}
    body["thinking"] = {"type": "enabled", "budget_tokens": 1024}
    headers = {"Content-Type": "application/json", "x-api-key": gw.key, "anthropic-version": "2023-06-01"}
    req = urllib.request.Request(gw.url + "/v1/messages", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        events = [json.loads(line[5:]) for line in r.read().decode().splitlines() if line.startswith("data:")]
    blocks = [e["content_block"] for e in events if e.get("type") == "content_block_start"]
    args = "".join(e["delta"].get("partial_json", "") for e in events if e.get("type") == "content_block_delta")
    for b in blocks:
        if b["type"] == "tool_use":
            b["input"] = json.loads(args or "{}")
    return blocks


TOOLS = [
    {"name": name, "description": name, "input_schema": {"type": "object", "properties": {arg: {"type": "string"}}}}
    for name, arg in (("Bash", "command"), ("Read", "file_path"))
]


def _episode(gw, image_result: dict) -> None:
    """A Messages client's three requests: observe, read the picture, end; it sends back only the tool_use fields it
    knows, as dimcode does."""
    messages: list = [{"role": "user", "content": "Solve the task."}]
    results = [
        "state: ok\n/tmp/ws/observations/obs_001_front.png",
        image_result,
    ]
    for result in results:
        use = next(b for b in _messages(gw, messages, TOOLS) if b["type"] == "tool_use")
        messages += [
            {"role": "assistant", "content": [{k: use[k] for k in ("type", "id", "name", "input")}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use["id"], "content": result}]},
        ]
    _messages(gw, messages, TOOLS)


@pytest.fixture
def gemini_standin(monkeypatch, clean_env):
    """The Gemini API stand-in, strict about thought signatures, as LiteLLM's Gemini route's endpoint."""
    import model_standin

    srv = model_standin.serve("gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("GEMINI_API_BASE", f"http://127.0.0.1:{srv.server_address[1]}/v1beta")
    yield model_standin.Handler.records
    srv.shutdown()


def test_a_messages_client_s_requests_reach_gemini_signed_with_their_images(gemini_standin, tmp_path) -> None:
    """dimcode rebuilds each tool_use block from what it knows, so the thought signature LiteLLM put on the block was
    lost and its second request failed (HTTP 400). The gateway keeps the signatures for it; and the lone image of a
    tool_result (Claude Code's Read of a picture) reaches Gemini as an image inside the function response."""
    pytest.importorskip("litellm")
    image = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}]
    gw = harnesses._gateway(
        models.resolve("claude-code", "gemini/gemini-4-argon"), _gateway_env(tmp_path), "anthropic-messages"
    )
    try:
        _episode(gw, image)
    finally:
        gw.stop()
    calls = [r for r in gemini_standin if r.get("call") == "streamGenerateContent"]
    assert [r["signatures"] for r in calls] == ["ok", "ok", "ok"] and [r["answer"] for r in calls] == [
        "Bash",
        "Read",
        "Bash",
    ]
    assert calls[-1]["images"] == {"function_response": 1, "inline": 0, "as_text": 0}
    # the thinking budget is removed, not sent as Gemini 2.5's thinkingBudget: the model thinks at its default level
    assert all(r["thinking_config"] is None for r in calls)
    stats = gw.stats
    assert (stats["route"], stats["successes"], stats["failures"]) == ("gemini/gemini-4-argon", 3, 0)
    assert (stats["signatures_restored"], stats["thinking_dropped"]) == (3, 3) and stats["upstream_data_uris"] >= 1


def test_a_chat_client_keeps_signatures_in_its_tool_call_ids(gemini_standin, tmp_path) -> None:
    """mini-swe-agent speaks chat completions: on the Gemini route LiteLLM puts the signature in the tool call id, which
    the client sends back."""
    pytest.importorskip("litellm")
    gw = harnesses._gateway(
        models.resolve("mini-swe-agent", "gemini/gemini-4-argon"), _gateway_env(tmp_path), "openai-completions"
    )
    tools = [{"type": "function", "function": {"name": "bash", "parameters": {"type": "object", "properties": {}}}}]

    def ask(messages: list) -> dict:
        body = json.dumps({"model": gw.model, "messages": messages, "tools": tools}).encode()
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + gw.key}
        with urllib.request.urlopen(
            urllib.request.Request(gw.url + "/v1/chat/completions", body, headers), timeout=60
        ) as r:
            return json.loads(r.read())["choices"][0]["message"]

    try:
        messages: list = [{"role": "user", "content": "Solve the task."}]
        for _ in range(2):
            m = ask(messages)
            call = m["tool_calls"][0]
            messages += [
                {"role": "assistant", "content": None, "tool_calls": [call]},
                {"role": "tool", "tool_call_id": call["id"], "content": "ok"},
            ]
        assert "__thought__" in call["id"]
    finally:
        gw.stop()
    calls = [r for r in gemini_standin if r.get("call") == "generateContent"]
    assert [r["signatures"] for r in calls] == ["ok", "ok"] and gw.stats["signatures_restored"] == 0


def test_the_trial_key_opens_only_the_model_routes(gemini_standin, tmp_path, monkeypatch) -> None:
    """LiteLLM's proxy also serves provider pass-through routes, such as /gemini/... (the key in ?key= or
    x-goog-api-key), which forward any request to the provider with the runner's own key: another model, a search tool,
    images the trial does not allow, none of it under the spend cap. With the trial's key, those and the other
    non-model routes are refused and nothing reaches the provider; the trial's model still answers. (The other
    providers' keys are unset and their endpoints a closed local port, so even a regression sends nothing out.)"""
    import urllib.error

    pytest.importorskip("litellm")
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for var in ("ANTHROPIC_API_BASE", "OPENAI_API_BASE", "OPENAI_BASE_URL"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    gw = harnesses._gateway(
        models.resolve("mini-swe-agent", "gemini/gemini-4-argon"), _gateway_env(tmp_path), "openai-completions"
    )

    def status(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> int:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(gw.url + path, data, {"Content-Type": "application/json", **(headers or {})})
        req.method = method
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    bearer = {"Authorization": "Bearer " + gw.key}
    search = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}], "tools": [{"googleSearch": {}}]}
    try:
        refused = {
            "query key": status("POST", f"/gemini/v1beta/models/gemini-other:generateContent?key={gw.key}", search),
            "header key": status(
                "POST", "/gemini/v1beta/models/gemini-other:generateContent", search, {"x-goog-api-key": gw.key}
            ),
            "gemini get": status("GET", f"/gemini/v1beta/models?key={gw.key}"),
            "anthropic": status("POST", "/anthropic/v1/messages", {"model": "claude-x", "messages": []}, bearer),
            "openai": status("POST", "/openai/v1/chat/completions", {"model": "gpt-x", "messages": []}, bearer),
            "embeddings": status("POST", "/v1/embeddings", {"model": "gemini/text-embedding", "input": "x"}, bearer),
            "files": status("GET", "/v1/files", None, bearer),
        }
        assert all(code == 403 for code in refused.values()), refused
        assert gemini_standin == []  # nothing reached the provider
        tools = [{"type": "function", "function": {"name": "bash", "parameters": {"type": "object", "properties": {}}}}]
        chat = {"model": gw.model, "messages": [{"role": "user", "content": "Solve the task."}], "tools": tools}
        assert status("POST", "/v1/chat/completions", chat, bearer) == 200
        assert status("GET", "/v1/models", None, bearer) == 200
    finally:
        gw.stop()
    assert [r.get("call") for r in gemini_standin] == ["generateContent"]
    assert "allowed_routes" in (tmp_path / "trial" / "gateway" / "config.yaml").read_text()


def test_the_gateway_uses_litellm_s_bundled_price_list(gemini_standin, tmp_path, monkeypatch) -> None:
    """LiteLLM downloads its newest model price list from GitHub each time it starts, unless told to use the one it
    ships with. The gateway's proxy is told to (the spend cap and the trial's cost come from Robo Use's own price
    table), and the trial's model still answers on LiteLLM's Gemini route, which LiteLLM's bundled list does not know."""
    import subprocess
    from types import SimpleNamespace

    from robouse.harnesses import gateway

    assert gateway.PROXY_ENV["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
    pytest.importorskip("litellm")
    envs: list[dict] = []

    def popen(*args, **kwargs):
        envs.append(kwargs["env"])
        return subprocess.Popen(*args, **kwargs)

    shim = SimpleNamespace(Popen=popen, STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired)
    monkeypatch.setattr(gateway, "subprocess", shim)
    gw = harnesses._gateway(
        models.resolve("mini-swe-agent", "gemini/gemini-4-argon"), _gateway_env(tmp_path), "openai-completions"
    )
    try:
        body = {"model": gw.model, "messages": [{"role": "user", "content": "Solve the task."}]}
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + gw.key}
        req = urllib.request.Request(gw.url + "/v1/chat/completions", json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            assert r.status == 200
    finally:
        gw.stop()
    assert len(envs) == 1 and envs[0]["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
    assert [r.get("call") for r in gemini_standin] == ["generateContent"]


def test_a_lone_tool_result_image_reaches_an_openai_compatible_provider_as_an_image(
    monkeypatch, clean_env, tmp_path
) -> None:
    """openrouter/ models are reached over chat completions. LiteLLM sent the lone image of a tool_result as its data
    URI in a text tool message, so Glimpse would have read it as characters; the gateway moves it into a user message."""
    pytest.importorskip("litellm")
    pytest.importorskip("benchflow")
    import model_standin

    srv = model_standin.serve("chat")
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}/api/v1")
    image = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}]
    gw = harnesses._gateway(
        models.resolve("claude-code", "openrouter/elorian/glimpse"), _gateway_env(tmp_path), "anthropic-messages"
    )
    try:
        _episode(gw, image)
    finally:
        gw.stop()
        srv.shutdown()
    recs = model_standin.Handler.records
    assert [r["answer"] for r in recs] == ["Bash", "Read", "Bash"] and recs[0]["model"] == "elorian/glimpse"
    assert recs[-1]["images"] == {"user_parts": 1, "tool_parts": 0, "as_text": 0}
    assert gw.stats["images_moved"] == 1 and gw.stats["route"] == "openai/elorian/glimpse"


# ---- the gemini-cli harness -----------------------------------------------------------------------------------------


@pytest.fixture
def fake_gemini(tmp_path, monkeypatch) -> Path:
    """A `gemini` program on PATH (the real one is an npm package); see test_a_whole_gemini_cli_trial for what it does."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "gemini"
    exe.write_text(FAKE_GEMINI)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return exe


def test_gemini_cli_launch_gets_its_own_home_settings_and_key(fake_gemini, monkeypatch, clean_env, tmp_path) -> None:
    from robouse.harnesses import PROMPT_PREFIX

    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="no Gemini credentials: set GEMINI_API_KEY"):
        harnesses.build("gemini-cli", "", "TASK", ws, None, {"PATH": os.environ["PATH"]})
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    with pytest.raises(ValueError, match="gemini-cli runs only Gemini API models"):
        harnesses.build("gemini-cli", "anthropic/claude-opus-5-5", "TASK", ws, None, {"PATH": "/usr/bin"})
    base = {"PATH": os.environ["PATH"], "_ROBOUSE_TRIAL_DIR": str(tmp_path), "_ROBOUSE_IMAGE_INPUT": "1"}
    launch = harnesses.build("gemini-cli", "gemini/gemini-4-argon", "TASK", ws, None, base)
    assert launch.cmd == [
        str(fake_gemini),
        "--prompt",
        PROMPT_PREFIX + "TASK",
        "--model",
        "gemini-4-argon",
        "--output-format",
        "stream-json",
        "--approval-mode",
        "yolo",
    ]
    home = ws / ".robouse" / "gemini-home"
    env = launch.env
    assert env["GEMINI_API_KEY"] == "not-a-real-key" and env["GEMINI_CLI_HOME"] == env["HOME"] == str(home)
    assert not Path(env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"]).exists()  # the machine's system settings are not read
    assert not Path(env["GEMINI_CLI_SYSTEM_DEFAULTS_PATH"]).exists()
    assert env["GEMINI_CLI_TRUST_WORKSPACE"] == "true" and not any(k.startswith("_ROBOUSE") for k in env)
    settings = json.loads((home / ".gemini" / "settings.json").read_text())
    assert settings == gemini_cli.SETTINGS and settings["tools"]["core"] == gemini_cli.TOOLS
    assert not {"google_web_search", "web_fetch"} & set(settings["tools"]["core"])
    assert settings["security"]["environmentVariableRedaction"]["enabled"] is True
    assert settings["security"]["auth"]["selectedType"] == "gemini-api-key" and settings["mcpServers"] == {}
    assert launch.notes == {"model": "gemini-4-argon"} and launch.stop is None  # its own vendor: no gateway
    assert not any("not-a-real-key" in f.read_text() for f in ws.rglob("*") if f.is_file())
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(RuntimeError, match="gemini-cli is not installed"):
        harnesses.build("gemini-cli", "", "TASK", ws, None, {"PATH": "/nonexistent"})


def test_gemini_settings_and_keys_stay_out_of_other_processes(monkeypatch, tmp_path) -> None:
    from robouse.runner import sandbox, trial

    environ = {
        "GEMINI_API_KEY": "k",
        "GOOGLE_API_KEY": "k",
        "GEMINI_API_BASE": "http://127.0.0.1:9/v1beta",
        "GOOGLE_GEMINI_BASE_URL": "http://127.0.0.1:9",
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "GEMINI_CLI_HOME": str(tmp_path / "gh"),
        "PATH": "/bin",
    }
    assert trial.agent_env(environ) == {"PATH": "/bin"}  # gemini-cli adds back its key itself
    assert trial.without_provider_keys(environ) == {"PATH": "/bin"}  # the episode server and the verifier
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "gh"))
    assert str(tmp_path / "gh" / ".gemini") in sandbox.home_denied()  # the runner's Gemini CLI settings and logins
    assert str(tmp_path / "gh") not in sandbox.home_denied()


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_gemini_cli_stream_json_becomes_a_trajectory(tmp_path) -> None:
    from robouse.runner import atif
    from robouse.runner.cost import price_of, trial_cost

    trial = tmp_path / "t"
    ts = lambda s: f"2026-10-20T19:00:{s:02d}.000Z"
    events = [
        {"type": "init", "timestamp": ts(0), "session_id": "sess", "model": "gemini-4-argon"},
        {"type": "message", "timestamp": ts(0), "role": "user", "content": "PROMPT"},
        {"type": "message", "timestamp": ts(1), "role": "assistant", "content": "Let me ", "delta": True},
        {"type": "message", "timestamp": ts(1), "role": "assistant", "content": "look.", "delta": True},
        {
            "type": "tool_use",
            "timestamp": ts(2),
            "tool_name": "run_shell_command",
            "tool_id": "s1",
            "parameters": {"command": "robo info"},
        },
        {
            "type": "tool_use",
            "timestamp": ts(2),
            "tool_name": "read_file",
            "tool_id": "r1",
            "parameters": {"file_path": "/ws/observations/obs_001_front.png"},
        },
        {"type": "tool_result", "timestamp": ts(3), "tool_id": "s1", "status": "success", "output": "task: arc"},
        {"type": "tool_result", "timestamp": ts(3), "tool_id": "r1", "status": "success", "output": "Read image file"},
        {
            "type": "tool_use",
            "timestamp": ts(4),
            "tool_name": "run_shell_command",
            "tool_id": "s2",
            "parameters": {"command": "rm x"},
        },
        {
            "type": "tool_result",
            "timestamp": ts(5),
            "tool_id": "s2",
            "status": "error",
            "error": {"type": "x", "message": "no such file"},
        },
        {"type": "error", "timestamp": ts(5), "severity": "warning", "message": "slow down"},
        {"type": "message", "timestamp": ts(6), "role": "assistant", "content": "Done.", "delta": True},
        {
            "type": "result",
            "timestamp": ts(6),
            "status": "success",
            "stats": {
                "total_tokens": 1600,
                "input_tokens": 1000,
                "output_tokens": 100,
                "cached": 400,
                "input": 600,
                "duration_ms": 6000,
                "tool_calls": 3,
                "models": {},
            },
        },
    ]
    _write(trial / "agent" / "stdout.jsonl", events)
    (trial / "artifacts" / "observations").mkdir(parents=True)
    (trial / "artifacts" / "observations" / "obs_001_front.png").write_bytes(b"png")
    _write(
        trial / "episode" / "trace.jsonl",
        [{"t": 0.5, "steps": 0, "req": {"op": "info"}, "resp": {"ok": True, "result": {"task": "arc"}}}],
    )
    (trial / "config.json").write_text(json.dumps({"harness": "gemini-cli", "model": "gemini-4-argon", "task": "arc"}))
    traj, _ = atif.build(trial)
    steps = traj["steps"]
    assert [s["source"] for s in steps] == ["user", "agent", "agent", "system", "agent"]
    assert steps[0]["message"] == "PROMPT" and steps[1]["message"] == "Let me look."
    assert [c["function_name"] for c in steps[1]["tool_calls"]] == ["run_shell_command", "read_file"]
    shell, image = steps[1]["observation"]["results"]
    assert shell["extra"]["robo_requests"] == 1 and shell["content"] == "task: arc"
    assert image["content"][-1]["source"]["path"] == "../artifacts/observations/obs_001_front.png"
    assert steps[2]["observation"]["results"][0]["extra"]["is_error"] is True and "no such file" in json.dumps(steps[2])
    assert steps[3]["message"] == "[warning] slow down" and steps[4]["message"] == "Done."
    fm = traj["final_metrics"]  # the stream's output_tokens leave out the 500 thinking tokens
    assert (fm["total_prompt_tokens"], fm["total_completion_tokens"], fm["total_cached_tokens"]) == (1000, 600, 400)
    assert fm["extra"]["thinking_tokens"] == 500 and "Gemini CLI stream-json" in traj["notes"]
    (trial / "agent" / "trajectory.json").write_text(json.dumps(traj))
    cost, price = trial_cost(trial, "gemini-4-argon", None), price_of("gemini-4-argon")
    assert price and cost["cost_usd"] == round(
        (600 * price["input"] + 400 * price["cached_input"] + 600 * price["output"]) / 1e6, 5
    )


def test_a_gemini_cli_error_result_is_a_harness_failure(tmp_path) -> None:
    from robouse.core.protocol import RUNNER_PREFIX
    from robouse.runner.trial import _harness_error

    error = {"type": "result", "status": "error", "error": {"type": "Error", "message": "quota exceeded"}}
    _write(tmp_path / "agent" / "stdout.jsonl", [{"type": "init", "model": "gemini-4-argon"}, error])
    episode = {"outcome": "gave_up", "agent_text": f"{RUNNER_PREFIX} agent exited without robo done"}
    assert _harness_error(tmp_path, "gemini-cli", 0, episode) == (
        "AgentError: the gemini-cli harness reported an error without ending the episode (quota exceeded)"
    )
    # another harness's stdout carries what its agent's commands print: the same line there is no harness failure, so
    # an agent cannot turn its own unfinished, scored trial into an unscored one that --retries reruns
    assert _harness_error(tmp_path, "mini-swe-agent", 0, episode) is None
    # nor does one written after Gemini CLI's own final result (into its output directly), or a stream without its init
    ok = {"type": "result", "status": "success", "stats": {}}
    _write(tmp_path / "agent" / "stdout.jsonl", [{"type": "init", "model": "gemini-4-argon"}, ok, error])
    assert _harness_error(tmp_path, "gemini-cli", 0, episode) is None
    _write(tmp_path / "agent" / "stdout.jsonl", [error])
    assert _harness_error(tmp_path, "gemini-cli", 0, episode) is None


# A stand-in for Gemini CLI: it checks what the harness gave it, ends the episode with `robo done` as a model's shell
# call would, and prints stream-json as Gemini CLI does
FAKE_GEMINI = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
home = os.environ["GEMINI_CLI_HOME"]
settings = json.load(open(os.path.join(home, ".gemini", "settings.json")))
facts = {
    "model": args[args.index("--model") + 1],
    "key": bool(os.environ.get("GEMINI_API_KEY")),
    "home": os.environ.get("HOME") == home and home.endswith(os.path.join(".robouse", "gemini-home")),
    "tools": settings["tools"]["core"],
}
def emit(ev):
    print(json.dumps(dict(timestamp="2026-10-20T19:00:00.000Z", **ev)), flush=True)
emit({"type": "init", "session_id": "s", "model": facts["model"]})
emit({"type": "message", "role": "user", "content": args[args.index("--prompt") + 1]})
emit({"type": "tool_use", "tool_name": "run_shell_command", "tool_id": "t1", "parameters": {"command": "robo done stub"}})
out = subprocess.run(["robo", "done", "stub"], capture_output=True, text=True).stdout
emit({"type": "tool_result", "tool_id": "t1", "status": "success", "output": out})
emit({"type": "message", "role": "assistant", "content": json.dumps(facts), "delta": True})
stats = {"total_tokens": 1500, "input_tokens": 1000, "output_tokens": 200, "cached": 0, "input": 1000, "duration_ms": 10, "tool_calls": 1, "models": {}}
emit({"type": "result", "status": "success", "stats": stats})
'''


def test_a_whole_gemini_cli_trial(fake_gemini, monkeypatch, clean_env, tmp_path) -> None:
    """robouse run's whole path for gemini-cli with a stand-in program: the launch, the episode, the trajectory and the
    cost from pricing.json (no gateway: Gemini CLI is on its own vendor)."""
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.runner.cost import price_of
    from robouse.tasks import load_task

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")  # the stand-in lives in tmp_path; the sandbox has its own tests
    job = tmp_path / "job"
    res = run_trial(load_task(VISION), "gemini-cli", "", job, timeout=120)
    assert res["exception"] is None and res["outcome"] == "done", res
    d = job / res["trial"]
    cfg, result = (json.loads((d / f).read_text()) for f in ("config.json", "result.json"))
    assert (cfg["harness"], cfg["model"], cfg["image_input"], cfg["spend_cap_usd"]) == (
        "gemini-cli",
        "gemini-4-argon",
        True,
        None,
    )
    assert (
        result["agent_info"]["model_info"] == {"name": "gemini-4-argon", "provider": None}
        and "proxy_stats" not in result
    )
    traj = json.loads((d / "agent" / "trajectory.json").read_text())
    facts = json.loads(traj["steps"][2]["message"])
    assert facts == {"model": "gemini-4-argon", "key": True, "home": True, "tools": gemini_cli.TOOLS}
    assert traj["steps"][1]["observation"]["results"][0]["extra"]["robo_requests"] == 1
    price = price_of("gemini-4-argon")
    assert result["cost"]["cost_usd"] == round((1000 * price["input"] + 500 * price["output"]) / 1e6, 5)
    assert "not-a-real-key" not in json.dumps(cfg) + json.dumps(result) + (d / "agent" / "stdout.jsonl").read_text()


def test_credentials_report_gemini(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert credentials.have_gemini() is False
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert credentials.have_gemini() is True and credentials.gemini_auth() == {"GEMINI_API_KEY": "k"}
