"""The MCP front end (`robo mcp`): protocol conformance, parity with the `robo` CLI, what it cannot do, and its wiring
into trials and harnesses."""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("imageio")

from fakes import FakeBackend

from robouse import agent_cli, mcp_server
from robouse.core import session as S

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    monkeypatch.setattr(S, "make_backend", FakeBackend)
    monkeypatch.delenv("ROBOUSE_RECORD_SIZE", raising=False)
    monkeypatch.delenv("ROBOUSE_ORACLE_TOKEN", raising=False)
    monkeypatch.delenv("ROBOUSE_SEND_VIA", raising=False)


@pytest.fixture(autouse=True)
def short_sockets(sock_dir, monkeypatch):
    monkeypatch.setattr(Server, "sock_dir", sock_dir)


class Server:
    """An episode server on a Unix socket in a thread (the fake backend)."""

    sock_dir: Path | None = None  # set by short_sockets

    def __init__(self, tmp: Path, name: str, secrets: dict | None = None, **spec):
        self.sock = str((self.sock_dir or tmp) / f"{name}.sock")
        self.run = tmp / name
        self.ws = tmp / f"{name}-ws"
        self.ws.mkdir()
        ready = tmp / f"{name}.ready"
        self.out: dict = {}
        self.th = threading.Thread(
            target=lambda: self.out.update(
                S.serve(
                    {"id": "t", "backend": "fake", "linger_s": 1, **spec},
                    self.run,
                    self.sock,
                    self.ws,
                    ready_file=ready,
                    secrets=secrets,
                )
            ),
            daemon=True,
        )
        self.th.start()
        for _ in range(500):
            if ready.exists():
                break
            time.sleep(0.01)

    def send(self, req: dict) -> dict:
        return agent_cli._send(req, path=self.sock)

    def trace(self) -> list[dict]:
        return [json.loads(line) for line in (self.run / "trace.jsonl").read_text().splitlines()]

    def finish(self) -> None:
        self.th.join(timeout=20)


def rpc(method: str, params: dict | None = None, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": method, **({"params": params} if params is not None else {})}


# ---- protocol conformance -------------------------------------------------------------------------------------------


def test_lifecycle_and_tool_listing() -> None:
    init = mcp_server.handle(rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}}))
    r = init["result"]
    assert r["protocolVersion"] == "2025-06-18" and r["capabilities"] == {"tools": {"listChanged": False}}
    assert r["serverInfo"]["name"] == "robo" and "done" in r["instructions"]
    # an unknown version gets the newest one the server speaks
    assert (
        mcp_server.handle(rpc("initialize", {"protocolVersion": "1999-01-01"}))["result"]["protocolVersion"]
        == (mcp_server.PROTOCOL_VERSIONS[0])
    )
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp_server.handle(rpc("ping"))["result"] == {}
    tools = mcp_server.handle(rpc("tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == ["info", "observe", "act", "move_to", "grip", "skill", "done", "give_up"]
    for t in tools:
        s = t["inputSchema"]
        assert s["type"] == "object" and s["additionalProperties"] is False and t["description"]
        assert set(s["required"]) <= set(s["properties"])


def test_json_rpc_errors() -> None:
    assert mcp_server.handle_payload(b"{not json")["error"]["code"] == -32700
    assert mcp_server.handle_payload(b'{"id": 1, "method": "ping"}')["error"]["code"] == -32600  # no jsonrpc
    assert mcp_server.handle_payload(b"[]")["error"]["code"] == -32600
    assert mcp_server.handle(rpc("resources/list"))["error"]["code"] == -32601
    assert mcp_server.handle(rpc("tools/call", {"name": "shutdown", "arguments": {}}))["error"]["code"] == -32602
    assert mcp_server.handle(rpc("tools/call", {"name": "status"}))["error"]["code"] == -32602
    batch = mcp_server.handle_payload(
        json.dumps([rpc("ping", id_=1), {"jsonrpc": "2.0", "method": "x"}, rpc("ping", id_=2)])
    )
    assert [m["id"] for m in batch] == [1, 2]
    assert mcp_server.handle({"jsonrpc": "2.0", "id": 5, "result": {}}) is None  # a response: nothing to answer


def test_bad_arguments_are_tool_errors_and_send_nothing() -> None:
    sent: list = []
    for name, args in [
        ("act", {}),
        ("act", {"action": "1 0 0"}),
        ("act", {"action": [1, 0, 0, 0], "repeat": 0}),
        ("act", {"action": [True, 0, 0, 0]}),
        ("observe", {"token": "x"}),
        ("move_to", {"x": 0, "y": 0}),
        ("move_to", {"x": 0, "y": 0, "z": 0, "tol": 0}),
        ("skill", {"name": "wiggle", "args": [1]}),
        ("done", {"message": "ok", "success": True}),
        ("info", "not an object"),
    ]:
        r = mcp_server.call_tool(name, args, send=sent.append)
        assert r["isError"] and r["content"][0]["text"].startswith("error: bad arguments"), (name, args, r)
    assert sent == []


def test_stdio_transport(tmp_path) -> None:
    srv = Server(tmp_path, "a")
    env = {**os.environ, "PYTHONPATH": str(SRC), "ROBOUSE_SOCKET": srv.sock}
    p = subprocess.run(
        [sys.executable, "-m", "robouse.agent_cli", "mcp"],
        input="\n".join(
            json.dumps(m)
            for m in [
                rpc(
                    "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}}, 1
                ),
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                rpc("tools/list", id_=2),
                rpc("tools/call", {"name": "act", "arguments": {"action": [1, 0, 0, -1], "repeat": 5}}, 3),
                rpc("tools/call", {"name": "done", "arguments": {"message": "there"}}, 4),
            ]
        )
        + "\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    lines = [json.loads(x) for x in p.stdout.splitlines()]
    assert [m["id"] for m in lines] == [1, 2, 3, 4]  # one line per request, nothing for the notification
    assert lines[0]["result"]["protocolVersion"] == "2025-03-26"
    assert "steps_used: 5" in lines[2]["result"]["content"][0]["text"] and not lines[2]["result"]["isError"]
    srv.finish()
    assert srv.out["success"] and srv.out["steps_used"] == 5


def _post(port: int, path: str, body, headers: dict | None = None, method: str = "POST"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = json.dumps(body).encode() if body is not None else None
    c.request(method, path, body=data, headers={"Content-Type": "application/json", **(headers or {})})
    r = c.getresponse()
    raw = r.read()
    return r.status, (json.loads(raw) if raw else None), r.getheader("Content-Type")


def test_streamable_http_transport(tmp_path, monkeypatch) -> None:
    srv = Server(tmp_path, "h")
    monkeypatch.setenv("ROBOUSE_SOCKET", srv.sock)
    http_srv = mcp_server.http_server("127.0.0.1", 0, "/secret/mcp")
    threading.Thread(target=http_srv.serve_forever, daemon=True).start()
    port = http_srv.server_address[1]
    hdr = {"Accept": "application/json, text/event-stream"}
    st, body, ctype = _post(port, "/secret/mcp", rpc("initialize", {"protocolVersion": "2025-06-18"}), hdr)
    assert st == 200 and ctype == "application/json" and body["result"]["serverInfo"]["name"] == "robo"
    assert _post(port, "/secret/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, hdr)[0] == 202
    assert _post(port, "/secret/mcp", None, hdr, method="GET")[0] == 405  # no server-sent event stream
    assert _post(port, "/other/mcp", rpc("ping"), hdr)[0] == 404  # the path is the per-trial secret
    assert _post(port, "/secret/mcp", rpc("ping"), {**hdr, "Origin": "https://evil.example"})[0] == 403
    assert _post(port, "/secret/mcp", rpc("ping"), {**hdr, "Origin": "http://localhost:3000"})[0] == 200
    st, body, _ = _post(port, "/secret/mcp", rpc("tools/call", {"name": "give_up", "arguments": {}}), hdr)
    assert st == 200 and body["result"]["_meta"]["robouse/reply"]["ok"]
    http_srv.shutdown()
    srv.finish()
    assert srv.out["outcome"] == "gave_up"


# ---- parity with the CLI --------------------------------------------------------------------------------------------

# the same operations as `robo` command lines and as tool calls
SCRIPT = [
    (["info"], ("info", {})),
    (["observe"], ("observe", {})),
    (["observe", "--image"], ("observe", {"image": True})),
    (["act", "1", "0", "0", "-1", "--repeat", "2"], ("act", {"action": [1, 0, 0, -1], "repeat": 2})),
    (["act", "0.5", "0", "0", "-1"], ("act", {"action": [0.5, 0, 0, -1]})),
    (["act", "1", "2"], ("act", {"action": [1, 2]})),  # an episode error, the same both ways
    (["move-to", "0.03", "0", "0", "--grip", "-1"], ("move_to", {"x": 0.03, "y": 0, "z": 0, "grip": -1})),
    (["grip", "1", "--steps", "3"], ("grip", {"value": 1, "steps": 3})),
    (["skill", "wiggle", "2"], ("skill", {"name": "wiggle", "args": ["2"]})),
    (["skill", "fly"], ("skill", {"name": "fly"})),
    (["move-to", "0.05", "0", "0"], ("move_to", {"x": 0.05, "y": 0, "z": 0})),
    (["done", "reached", "the", "goal"], ("done", {"message": "reached the goal"})),
    (["act", "0", "0", "0", "0"], ("act", {"action": [0, 0, 0, 0]})),  # after the end
]


def _norm_trace(entries: list[dict], ws: Path) -> list[dict]:
    out = []
    for e in entries:
        req = {k: v for k, v in e["req"].items() if k != "via"}
        resp = json.loads(json.dumps(e["resp"]).replace(str(ws), "WS"))
        out.append({"steps": e["steps"], "req": req, "resp": resp})
    return out


def test_parity_same_requests_outputs_and_episode(tmp_path, monkeypatch, capsys) -> None:
    cli, mcp = Server(tmp_path, "cli"), Server(tmp_path, "mcp")
    for argv, (tool, args) in SCRIPT:
        monkeypatch.setenv("ROBOUSE_SOCKET", cli.sock)
        rc = agent_cli.main(argv)
        printed = capsys.readouterr().out.rstrip("\n")
        monkeypatch.setenv("ROBOUSE_SOCKET", mcp.sock)
        r = mcp_server.handle(rpc("tools/call", {"name": tool, "arguments": args}))["result"]
        text = r["content"][0]["text"].replace(str(mcp.ws), str(cli.ws))
        assert text == printed, argv
        assert r["isError"] == (rc != 0), argv
        # the request itself is the CLI's, plus the via marker
        assert {**agent_cli.build_request(argv[0], argv[1:]), "via": "mcp"} == {
            **agent_cli.build_request(*mcp_server.tool_argv(tool, args)),
            "via": "mcp",
        }
    cli.finish()
    mcp.finish()
    a, b = cli.trace(), mcp.trace()
    assert all("via" not in e["req"] for e in a) and all(e["req"]["via"] == "mcp" for e in b)
    assert _norm_trace(a, cli.ws) == _norm_trace(b, mcp.ws)
    ra, rb = (json.loads((s.run / "result.json").read_text()) for s in (cli, mcp))
    for k in ("success", "success_ever", "outcome", "steps_used", "max_steps", "requests", "agent_text"):
        assert ra[k] == rb[k], k
    assert ra["success"] is True and ra["agent_text"] == "reached the goal"
    assert sorted(os.listdir(cli.run / "observations")) == sorted(os.listdir(mcp.run / "observations"))


def test_request_tool_is_the_inverse_of_the_tools(tmp_path) -> None:
    for req in [
        {"op": "info"},
        {"op": "observe", "image": True, "camera": "top"},
        {"op": "act", "action": [0.1, -0.2, 0.0, 1.0], "repeat": 7},
        {"op": "move_to", "pos": [0.1, 0.2, 0.3], "grip": 1.0, "max_steps": 40, "tol": 0.02},
        {"op": "grip", "value": -1.0, "steps": 4},
        {"op": "skill", "name": "pick", "args": ["cube", "0.5"]},
        {"op": "done", "text": "ok"},
        {"op": "give_up", "text": ""},
    ]:
        name, args = mcp_server.request_tool(req)
        built = agent_cli.build_request(*mcp_server.tool_argv(name, args))
        assert {k: v for k, v in built.items() if v is not None} == {k: v for k, v in req.items() if v is not None}
    with pytest.raises(ValueError):
        mcp_server.request_tool({"op": "shutdown"})


# ---- images follow the CLI ------------------------------------------------------------------------------------------


def test_images_exactly_when_the_cli_gives_a_path(tmp_path, monkeypatch) -> None:
    srv = Server(tmp_path, "v", obs_mode="vision", visible_fields=["hand_pos"])
    monkeypatch.setenv("ROBOUSE_SOCKET", srv.sock)
    r = mcp_server.call_tool("observe", {})
    path = r["_meta"]["robouse/reply"]["result"]["image_path"]
    imgs = [c for c in r["content"] if c["type"] == "image"]
    assert len(imgs) == 1 and base64.b64decode(imgs[0]["data"]) == Path(path).read_bytes()
    assert imgs[0]["mimeType"] == "image/png" and f"image_path: {path}" in r["content"][0]["text"]
    agent_cli._send({"op": "give_up"}, path=srv.sock)
    srv.finish()


def test_a_run_without_image_input_strips_mcp_images_in_the_gateway(tmp_path, monkeypatch) -> None:
    """Image input is the model gateway's job, for both interfaces: the MCP server attaches an image whenever the CLI
    would print a path, and a trial without image input has its gateway replace every image part, in the shapes the
    MCP clients send them (an Anthropic tool_result for Claude Code and dimcode, a Responses function_call_output for
    Codex). With image input on, Codex's tool-result images move into the next user message."""
    pytest.importorskip("litellm")
    import copy
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gateway_hook", SRC / "robouse" / "harnesses" / "providers" / "gateway_hook.py"
    )
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    srv = Server(tmp_path, "v", obs_mode="vision", visible_fields=["hand_pos"])
    monkeypatch.setenv("ROBOUSE_SOCKET", srv.sock)
    r = mcp_server.call_tool("observe", {})
    agent_cli._send({"op": "give_up"}, path=srv.sock)
    srv.finish()
    img = next(c for c in r["content"] if c["type"] == "image")
    text = r["content"][0]["text"]
    anthropic = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": [
                            {"type": "text", "text": text},
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": img["mimeType"], "data": img["data"]},
                            },
                        ],
                    }
                ],
            }
        ]
    }
    responses = {
        "input": [
            {"type": "function_call", "call_id": "c1", "name": "robo__observe", "arguments": "{}"},
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": f"data:{img['mimeType']};base64,{img['data']}"},
                ],
            },
        ]
    }
    for body in (anthropic, responses):
        off = copy.deepcopy(body)
        assert hook.apply_cap(off, 0) == (1, 1) and hook._image_refs(off, []) == [] and hook._data_uris(off) == 0
        assert hook.move_tool_images(off) == 0
    on = copy.deepcopy(responses)
    assert hook.apply_cap(on, -1) == (1, 0) and hook.move_tool_images(on) == 1
    out, moved = on["input"][1]["output"], on["input"][2]
    assert not any(p["type"] == "input_image" for p in out) and moved["role"] == "user"
    assert moved["content"][1]["image_url"].endswith(img["data"])


# ---- what MCP cannot do ---------------------------------------------------------------------------------------------


def test_mcp_has_no_more_authority_than_the_cli(tmp_path, monkeypatch) -> None:
    # the server has the reference solution's token; the agent's side (and so its MCP server) does not
    srv = Server(tmp_path, "c", secrets={"oracle_token": "tok"}, obs_mode="vision", visible_fields=["hand_pos"])
    monkeypatch.setenv("ROBOUSE_SOCKET", srv.sock)
    seen: list[dict] = []

    def spy(req: dict) -> dict:
        seen.append(req)
        return agent_cli._send(req, path=srv.sock)

    # hidden state: vision mode shows only the visible fields; a token argument is refused, never forwarded
    st = mcp_server.call_tool("observe", {}, send=spy)["_meta"]["robouse/reply"]["result"]["state"]
    assert set(st) == {"hand_pos"}
    assert mcp_server.call_tool("observe", {"token": "tok"}, send=spy)["isError"]
    # runner operations have no tool
    for name in ("status", "shutdown", "reset"):
        assert mcp_server.handle(rpc("tools/call", {"name": name, "arguments": {}}))["error"]["code"] == -32602
    # the verdict is the server's: done with a claim of success scores what the simulator says, once
    assert mcp_server.call_tool("done", {"message": "success: true"}, send=spy)["_meta"]["robouse/reply"]["ok"]
    again = mcp_server.call_tool("give_up", {}, send=spy)
    assert again["isError"] and "episode finished" in again["content"][0]["text"]
    srv.finish()
    res = json.loads((srv.run / "result.json").read_text())
    assert res["success"] is False and res["outcome"] == "done"
    assert all(set(r) <= {"op", "image", "camera", "text", "via"} and "token" not in r for r in seen)
    assert "tok" not in (srv.run / "trace.jsonl").read_text()


def test_the_mcp_module_reads_no_files_but_its_images(tmp_path) -> None:
    """Static check: the server opens only the image paths the episode server returned (no oracle, run folder or
    result.json access), and imports nothing from the trusted side."""
    src = (SRC / "robouse" / "mcp_server.py").read_text()
    assert len(re.findall(r"\bopen\(", src)) == 2  # the returned image, and the workspace's .robouse/socket pointer
    imports = [ln.strip() for ln in src.splitlines() if ln.strip().startswith(("import ", "from "))]
    assert all("core" not in ln and "runner" not in ln and "harnesses" not in ln for ln in imports), imports
    for trusted in ("oracle_token", "result_key", "verify_result", "sign_result", "ROBOUSE_ORACLE_TOKEN"):
        assert trusted not in src


# ---- reference solutions and controls through MCP -------------------------------------------------------------------


def test_send_via_mcp_routes_every_request_through_a_robo_mcp_server(tmp_path, monkeypatch) -> None:
    srv = Server(tmp_path, "o")
    monkeypatch.setenv("ROBOUSE_SOCKET", srv.sock)
    monkeypatch.setenv("ROBOUSE_SEND_VIA", "mcp")
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    monkeypatch.setattr(mcp_server, "_client", None)
    assert agent_cli._send({"op": "act", "action": [1, 0, 0, -1], "repeat": 5})["result"]["steps_used"] == 5
    assert agent_cli._send({"op": "done", "text": "ok"})["ok"]
    mcp_server._client.close()
    srv.finish()
    assert srv.out["success"]
    assert all(e["req"].get("via") == "mcp" for e in srv.trace())


# ---- harness wiring -------------------------------------------------------------------------------------------------


def _launch(harness: str, ws: Path):
    from robouse.harnesses import PROMPT_PREFIX, Launch, _claude_cmd, _codex_cmd

    cmd = _claude_cmd("TASK", "m") if harness.startswith("claude") else _codex_cmd("TASK", "m", ws)
    assert any(isinstance(a, str) and a.startswith(PROMPT_PREFIX) for a in cmd)
    return Launch(cmd, {"PATH": f"{ws / '.robouse' / 'bin'}:/usr/bin"})


def test_interface_wiring(tmp_path) -> None:
    from robouse.harnesses import interface as iface

    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    cc = _launch("claude-code", ws)
    iface.apply("claude-code", cc, "mcp", ws, "/tmp/x.sock")
    i = cc.cmd.index("--mcp-config")
    cfg = json.loads(Path(cc.cmd[i + 1]).read_text())["mcpServers"]["robo"]
    assert cc.cmd[i + 2] == "--strict-mcp-config" and cfg["args"][-1] == "mcp"
    assert cfg["env"] == {"ROBOUSE_SOCKET": "/tmp/x.sock"}
    assert str(ws / ".robouse" / "bin") not in cc.env["PATH"]  # mcp only: no robo on PATH
    assert any(a.startswith(iface.PROMPTS["mcp"]) and a.endswith("TASK") for a in cc.cmd)

    cx = _launch("codex", ws)
    iface.apply("codex", cx, "both", ws, "/tmp/x.sock")
    flags = cx.cmd[: cx.cmd.index("-m")]
    assert 'mcp_servers.robo.env={ROBOUSE_SOCKET="/tmp/x.sock"}' in flags
    assert str(ws / ".robouse" / "bin") in cx.env["PATH"]  # both: robo stays
    assert cx.cmd[-1].startswith(iface.PROMPTS["both"])

    cli = _launch("codex", ws)
    before = list(cli.cmd)
    iface.apply("codex", cli, "cli", ws, "/tmp/x.sock")
    assert cli.cmd == before
    with pytest.raises(ValueError):
        iface.check("mini-swe-agent", "mcp")


def test_interface_resolution() -> None:
    from robouse.harnesses import interface as iface
    from robouse.tasks import Task

    t = Task(Path("x"), {"robouse": {"id": "x", "interface": "both"}})
    assert iface.resolve(t, None) == "both" and iface.resolve(t, "cli") == "cli"
    assert iface.resolve(Task(Path("y"), {"robouse": {"id": "y"}}), None) == "cli"
    with pytest.raises(ValueError):
        iface.resolve(t, "grpc")


def test_dimcode_launch_is_isolated_and_holds_no_key(tmp_path, monkeypatch) -> None:
    pytest.importorskip("benchflow")  # the model registry
    from types import SimpleNamespace

    from robouse import harnesses
    from robouse.harnesses import build
    from robouse.tasks import Task

    gw = SimpleNamespace(
        url="http://127.0.0.1:4242", key="sk-robouse-gwkey", model="gw-alias", stats={}, stop=None, stop_file=None
    )
    seen: dict = {}

    def fake_gateway(ref, env, protocol):
        seen.update(ref=ref, protocol=protocol, image=env.get("_ROBOUSE_IMAGE_INPUT"))
        return gw

    monkeypatch.setattr(harnesses, "_gateway", fake_gateway)
    monkeypatch.setenv("GLM_API_KEY", "sk-SECRET")  # the runner's environment; never the agent's
    exe = tmp_path / "dimcode"
    exe.write_text("")
    monkeypatch.setenv("ROBOUSE_DIMCODE", str(exe))
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    task = Task(tmp_path, {"robouse": {"id": "t"}}, "do it")
    env = {
        "PATH": "/usr/bin",
        "ROBOUSE_INTERFACE": "mcp",
        "HOME": "/home/u",
        "_ROBOUSE_IMAGE_INPUT": "0",
        "_ROBOUSE_TRIAL_DIR": str(tmp_path),
        "_ROBOUSE_SPEND_CAP_USD": "5",
    }
    launch = build("dimcode", "", "do it", ws, task, env)  # the default model, glm/glm-5.3
    assert seen["ref"].id == "glm/glm-5.3" and seen["protocol"] == "anthropic-messages"
    root = ws / ".robouse" / "dimcode"
    cfg = json.loads((root / "config.json").read_text())
    assert cfg["mcp"][0]["name"] == "robo" and cfg["mcp"][0]["url"].startswith("http://127.0.0.1:")
    prov = json.loads((root / "models.json").read_text())["providers"]["robouse"]
    assert (
        prov["baseUrl"] == gw.url and prov["api"] == "anthropic-messages" and prov["apiKey"] == "$ROBOUSE_GATEWAY_KEY"
    )
    assert prov["models"][0]["id"] == "gw-alias" and prov["models"][0]["input"] == ["text"]  # no image input here
    assert json.loads((root / "settings.json").read_text())["defaultModel"] == "gw-alias"
    assert launch.env["DIMCODE_HOME"] == str(root) and launch.env["DIMCODE_INSTALL_DIMOS"] == "0"
    assert launch.env["ROBOUSE_GATEWAY_KEY"] == gw.key and launch.env["HOME"].startswith(str(root))
    assert not any(k.startswith("_ROBOUSE") for k in launch.env)  # the runner's private variables
    assert "sk-SECRET" not in json.dumps(launch.cmd) + json.dumps(launch.env)
    assert not any(s in f.read_text() for f in root.rglob("*") if f.is_file() for s in ("sk-SECRET", gw.key))
    url = cfg["mcp"][0]["url"]
    i = launch.cmd.index("--http")
    assert launch.cmd[i - 1] == "mcp" and url.endswith(launch.cmd[i + 3]) and "--run" in launch.cmd
    assert launch.cmd[-1].startswith(iface_prompt("mcp"))
    assert launch.notes["model_id"] == "glm/glm-5.3" and launch.notes["provider"] == "glm"


def iface_prompt(name: str) -> str:
    from robouse.harnesses import interface as iface

    return iface.PROMPTS[name]


# ---- trajectories ---------------------------------------------------------------------------------------------------


def test_atif_aligns_mcp_tool_calls_like_robo_commands(tmp_path) -> None:
    from robouse.runner import atif

    trial = tmp_path / "t"
    for d in ("agent", "episode"):
        (trial / d).mkdir(parents=True)
    srv = Server(tmp_path, "at")
    calls = [("info", {}), ("act", {"action": [1, 0, 0, -1], "repeat": 3}), ("done", {"message": "ok"})]
    events = [{"type": "system", "subtype": "init", "model": "m", "tools": ["mcp__robo__act"]}]
    for i, (tool, args) in enumerate(calls):
        r = mcp_server.call_tool(tool, args, send=srv.send)
        events.append(
            {
                "type": "assistant",
                "message": {
                    "id": f"m{i}",
                    "content": [{"type": "tool_use", "id": f"c{i}", "name": f"mcp__robo__{tool}", "input": args}],
                },
            }
        )
        events.append(
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": f"c{i}", "content": r["content"]}]},
            }
        )
    srv.finish()
    (trial / "agent" / "stdout.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    for f in ("trace.jsonl", "frames.jsonl", "result.json"):
        (trial / "episode" / f).write_text((srv.run / f).read_text())
    task_path = str(ROOT / "tasks" / "arc-style" / "arc-gravity")
    (trial / "config.json").write_text(
        json.dumps({"harness": "claude-code-glm", "interface": "mcp", "task": "t", "task_path": task_path})
    )
    traj, index = atif.build(trial)
    tool_steps = [s for s in traj["steps"] if s.get("tool_calls")]
    assert [s["observation"]["results"][0]["extra"]["robo_requests"] for s in tool_steps] == [1, 1, 1]
    assert "could not be matched" not in traj["notes"]
    assert traj["steps"][0]["message"].startswith(iface_prompt("mcp"))
    assert [r["action"] for r in index["steps"][1:4]] == [
        "robo info",
        "robo act 1.0 0.0 0.0 -1.0 --repeat 3",
        "robo done ok",
    ]


def test_atif_reads_a_pi_session(tmp_path) -> None:
    from robouse.runner import atif

    trial = tmp_path / "t"
    (trial / "agent").mkdir(parents=True)
    usage = {"input": 100, "output": 20, "cacheRead": 50, "cacheWrite": 0, "totalTokens": 170, "cost": {"total": 0}}
    tool = "dimos_robo_observe_0123456789"
    lines = [
        {"type": "session", "version": 3, "id": "sess", "cwd": "/ws"},
        {"type": "message", "message": {"role": "user", "content": "PROMPT", "timestamp": 1000}},
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "look first"},
                    {"type": "toolCall", "id": "a", "name": "bash", "arguments": {"command": "robo info"}},
                    {"type": "toolCall", "id": "b", "name": tool, "arguments": {"image": True}},
                ],
                "model": "zai-org/GLM-5.3",
                "usage": usage,
                "stopReason": "toolUse",
                "timestamp": 2000,
            },
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolCallId": "a",
                "toolName": "bash",
                "content": [{"type": "text", "text": "task: t"}],
                "isError": False,
            },
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolCallId": "b",
                "toolName": tool,
                "content": [{"type": "text", "text": "state:"}],
                "isError": False,
            },
        },
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
                "usage": usage,
                "timestamp": 3000,
            },
        },
    ]
    steps, meta = atif._parse_pi(lines, trial)
    atif._mcp_commands(steps)
    assert meta["session_id"] == "sess" and [s["source"] for s in steps] == ["user", "agent", "agent"]
    a = steps[1]
    assert a["reasoning"] == "look first" and a["calls"][0]["command"] == "robo info"
    assert a["calls"][1]["command"] == "robo observe --image" and a["calls"][1]["output"] == "state:"
    assert atif._pi_final(meta)["total_prompt_tokens"] == 300 and atif._pi_final(meta)["total_cached_tokens"] == 100


# ---- whole trials (MuJoCo) ------------------------------------------------------------------------------------------

ARC = ROOT / "tasks" / "arc-style" / "arc-gravity"


def _trial(job: Path, res: dict) -> tuple[dict, dict, list[dict]]:
    t = job / res["trial"]
    trace = [json.loads(x) for x in (t / "episode" / "trace.jsonl").read_text().splitlines()]
    return json.loads((t / "config.json").read_text()), json.loads((t / "result.json").read_text()), trace


def _agent_entries(trace: list[dict]) -> list[dict]:
    """The agent's requests in a canonical form (the tool call each one is), with their replies."""
    out = []
    for e in trace:
        if e["req"].get("op") == "status" or str(e["req"].get("text", "")).startswith("[runner]"):
            continue
        req = mcp_server.request_tool(e["req"])
        resp = json.loads(re.sub(r"/robouse-ws-[^/\"]+", "/WS", json.dumps(e["resp"])))
        out.append({"steps": e["steps"], "req": req, "resp": resp})
    return out


def test_reference_solution_through_mcp_is_the_same_episode(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    monkeypatch.undo()  # the real backends
    task = load_task(ARC)
    runs = {}
    for interface in ("cli", "mcp"):
        job = tmp_path / interface
        res = run_trial(task, "oracle", "", job, interface=interface)
        assert res["reward"] == 1.0 and res["exception"] is None, res
        runs[interface] = _trial(job, res)
    (cfg_c, res_c, tr_c), (cfg_m, res_m, tr_m) = runs["cli"], runs["mcp"]
    assert cfg_c["interface"] == "cli" and cfg_m["interface"] == "mcp"
    assert res_m["agent_info"]["interface"] == "mcp"
    mine = [
        e for e in tr_m if e["req"].get("op") != "status" and not str(e["req"].get("text", "")).startswith("[runner]")
    ]
    assert mine and all(e["req"].get("via") == "mcp" for e in mine)
    assert not any(e["req"].get("via") for e in tr_c)
    assert _agent_entries(tr_c) == _agent_entries(tr_m)
    for k in ("success", "outcome", "steps_used", "requests", "agent_text"):
        assert res_c["episode"][k] == res_m["episode"][k], k


def test_noop_through_mcp_scores_zero(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    monkeypatch.undo()
    res = run_trial(load_task(ARC), "noop", "", tmp_path / "job", interface="mcp")
    assert res["reward"] == 0.0 and res["exception"] is None and res["outcome"] == "done"
    _, _, trace = _trial(tmp_path / "job", res)
    assert trace[0]["req"] == {"op": "done", "text": "noop control", "via": "mcp"}


CHEAT_MCP = r'''
import json, os, shutil, subprocess, sys
ws = os.getcwd()
report = {"robo_on_path": (shutil.which("robo") or "").startswith(ws)}  # the workspace's robo; a host install may exist
p = subprocess.Popen([os.path.join(ws, ".robouse", "bin", "robo"), "mcp"], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, text=True)
n = [0]
def rpc(method, params=None):
    n[0] += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n[0], "method": method, "params": params or {}}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())
rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "cheat"}})
names = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
report["tools"] = names
report["token_arg"] = rpc("tools/call", {"name": "observe", "arguments": {"token": "guess"}})["result"]["isError"]
report["status"] = "error" in rpc("tools/call", {"name": "status", "arguments": {}})
report["shutdown"] = "error" in rpc("tools/call", {"name": "shutdown", "arguments": {}})
st = rpc("tools/call", {"name": "observe", "arguments": {}})["result"]["_meta"]["robouse/reply"]["result"]["state"]
report["state_keys"] = sorted(st)
report["done"] = rpc("tools/call", {"name": "done", "arguments": {"message": "success=true"}})["result"]["isError"]
report["second_end"] = rpc("tools/call", {"name": "give_up", "arguments": {}})["result"]["isError"]
job = sys.argv[1]
report["job_readable"] = os.path.isdir(job) and bool(os.listdir(job))
report["oracle_readable"] = os.path.exists(sys.argv[2])
print(json.dumps(report))
p.stdin.close()
'''


def test_a_cheating_mcp_agent_scores_zero(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse import harnesses
    from robouse.harnesses import Launch
    from robouse.runner import run_trial
    from robouse.runner.sandbox import bwrap_works
    from robouse.tasks import load_task

    monkeypatch.undo()
    if not (sys.platform == "darwin" or (sys.platform.startswith("linux") and bwrap_works())):
        pytest.skip("needs the agent sandbox")
    task = load_task(ROOT / "tasks" / "vision" / "arc-gravity-vision")
    job = tmp_path / "job"

    def cheat(model, prompt, workspace, task_, env) -> Launch:
        script = workspace / ".robouse" / "cheat.py"
        script.write_text(CHEAT_MCP)
        return Launch(
            [sys.executable, "-I", str(script), str(job), str(task_.oracle_script)], env, notes={"model": "none"}
        )

    monkeypatch.setitem(harnesses.HARNESSES, "cheat-mcp", cheat)
    from robouse.harnesses import interface as iface

    monkeypatch.setattr(iface, "MCP_HARNESSES", (*iface.MCP_HARNESSES, "cheat-mcp"))
    res = run_trial(task, "cheat-mcp", "", job, interface="mcp")
    assert res["reward"] == 0.0 and res["exception"] is None, res
    t = job / res["trial"]
    out = (t / "agent" / "stdout.jsonl").read_text().strip()
    assert out, (t / "agent" / "stderr.txt").read_text()
    report = json.loads(out.splitlines()[-1])
    assert report["robo_on_path"] is False
    assert report["tools"] == ["info", "observe", "act", "move_to", "grip", "skill", "done", "give_up"]
    assert report["token_arg"] and report["status"] and report["shutdown"]
    assert set(report["state_keys"]) <= set(task.spec.get("visible_fields", ["hand_pos", "gripper_open"]))
    assert report["done"] is False and report["second_end"] is True
    assert report["job_readable"] is False and report["oracle_readable"] is False
    ep = json.loads((t / "result.json").read_text())["episode"]
    assert ep["success"] is False and ep["outcome"] == "done"


# ---- the official MCP TypeScript SDK as the client ------------------------------------------------------------------

SDK = os.environ.get("MCP_SDK_CLIENT_DIR", "")  # a @modelcontextprotocol/client package folder (e.g. dimcode's)


@pytest.mark.skipif(not (SDK and Path(SDK, "dist", "stdio.mjs").is_file()), reason="set MCP_SDK_CLIENT_DIR")
@pytest.mark.parametrize("mode", ["stdio", "http"])
def test_the_official_sdk_client_works_over_both_transports(tmp_path, monkeypatch, mode) -> None:
    import shutil

    node = os.environ.get("MCP_SDK_NODE") or shutil.which("node")
    srv = Server(tmp_path, mode)
    monkeypatch.setenv("ROBOUSE_SOCKET", srv.sock)
    script = str(Path(__file__).with_name("mcp_sdk_client.mjs"))
    env = {**os.environ, "PYTHONPATH": str(SRC), "ROBOUSE_SOCKET": srv.sock}
    if mode == "stdio":
        args = ["stdio", sys.executable, str(SRC / "robouse" / "agent_cli.py")]
    else:
        http_srv = mcp_server.http_server("127.0.0.1", 0, "/k/mcp")
        threading.Thread(target=http_srv.serve_forever, daemon=True).start()
        args = ["http", f"http://127.0.0.1:{http_srv.server_address[1]}/k/mcp"]
    p = subprocess.run([node, script, SDK, *args], capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["server"]["name"] == "robo" and out["capabilities"]["tools"] and out["instructions"]
    assert out["tools"] == ["info", "observe", "act", "move_to", "grip", "skill", "done", "give_up"]
    assert out["info_text"] == "task: t" and out["observe_types"] == ["text", "image"]
    assert out["act_error"] is False and "steps_used: 3" in out["act_text"]
    assert out["bad_is_error"] is True and out["unknown_tool"] == "rejected"
    assert out["done_text"].startswith("outcome: done")
    srv.finish()
    assert srv.out["outcome"] == "done" and srv.out["agent_text"] == "sdk"
