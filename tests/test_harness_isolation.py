"""What a model harness offers its model and what its sandbox lets the agent reach (deep audit, 2026-10-14)."""

from __future__ import annotations

import os
import re
import shutil
import socket
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

from robouse import _maintainer, harnesses
from robouse.harnesses import interface as iface
from robouse.runner import sandbox

ROOT = Path(__file__).resolve().parents[1]


def _flags(cmd: list[str]) -> list[str]:
    """The `-c` overrides of a Codex command."""
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == "-c"]


def test_codex_turns_web_search_off(tmp_path) -> None:
    """Codex offers its model a web_search tool by default (0.155 and later); every Codex launch turns it off, on its
    own vendor and through the gateway (extra provider flags), and the MCP interface keeps it."""
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    native = harnesses._codex_cmd("TASK", "gpt-6-astra", ws)
    via_gateway = harnesses._codex_cmd("TASK", "m", ws, ["-c", 'model_provider="robouse"'])
    for cmd in (native, via_gateway):
        assert 'web_search="disabled"' in _flags(cmd)
        assert cmd.index('web_search="disabled"') < cmd.index("-m")
    launch = harnesses.Launch(list(native), {"PATH": f"{ws / '.robouse' / 'bin'}:/usr/bin"})
    iface.apply("codex", launch, "mcp", ws, "/tmp/x.sock")
    flags = _flags(launch.cmd)
    assert 'web_search="disabled"' in flags and any(f.startswith("mcp_servers.robo") for f in flags)


def test_codex_web_search_setting_is_valid_toml() -> None:
    """Codex parses each `-c` value as TOML: an unquoted value would be a different setting or an error."""
    assert tomllib.loads(harnesses.CODEX_WEB_SEARCH) == {"web_search": "disabled"}


def test_claude_code_gets_an_allowlist_of_tools(tmp_path) -> None:
    """Claude Code is offered only Bash, Read, Write, Edit, Glob and Grep (`--tools`), not a short deny list that left
    Workflow, Skill, SendMessage, CronCreate, EnterWorktree and others available. With the MCP interface the robo
    tools come from --mcp-config on top: `--tools` names built-in tools only (Claude Code 2.1.285 against a local
    stub offered exactly these six plus the eight mcp__robo__ tools)."""
    cmd = harnesses._claude_cmd("TASK", "claude-opus-5-5")
    assert "--disallowedTools" not in cmd and "--allowedTools" not in cmd
    assert cmd[cmd.index("--tools") + 1].split(",") == ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    launch = harnesses.Launch(cmd, {"PATH": f"{ws / '.robouse' / 'bin'}:/usr/bin"})
    iface.apply("claude-code", launch, "both", ws, "/tmp/x.sock")
    assert launch.cmd[launch.cmd.index("--tools") + 1] == harnesses.CLAUDE_TOOLS
    assert launch.cmd[launch.cmd.index("--mcp-config") + 2] == "--strict-mcp-config"


# ---- the sandbox: credential and task-copy locations --------------------------------------------------------------

SECRET = "SECRET-not-a-real-credential"
# a home folder's credential and task-copy locations, each holding SECRET (folders get a file inside)
PLANTED = [
    ".cache/uv/archive-v0/abc/robouse/bundled_tasks/arc-gravity/oracle/solve.sh",
    ".cache/pip/http-v2/a/robouse.whl",
    ".cache/benchflow/task-formats/robouse/tasks/arc-gravity/oracle/solve.sh",
    ".config/benchflow/provider.env",
    ".claude/.credentials.json",
    ".claude.json",
    ".claude-second/.credentials.json",
    ".codex/auth.json",
    ".codex/sessions/rollout.jsonl",
    ".config/mini-swe-agent/.env",
    ".env",
    ".config/gh/hosts.yml",
    ".ssh/id_ed25519",
    ".netrc",
    ".cache/huggingface/token",
    ".cache/robouse/claude-home/projects/other-trial.jsonl",
    ".cache/robouse/codex-home-other/auth.json",
    ".cache/robouse/dexjoco-venv/lib/site.py",
]


def _home(base: Path) -> dict[str, Path]:
    """A home folder with SECRET in every planted location, a program folder inside ~/.codex, the agent's own Codex
    home inside robouse's cache and a Claude Code home of the runner's own."""
    home = base / "home"
    for rel in PLANTED:
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(SECRET)
    tool = home / ".codex" / "packages" / "bin" / "tool"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\necho program-ok\n")
    tool.chmod(0o755)
    own = home / ".cache" / "robouse" / "codex-home-mine"
    own.mkdir(parents=True)
    (own / "auth.json").write_text("OWN")
    runner = base / "runner-claude-home"
    runner.mkdir()
    (runner / ".credentials.json").write_text(SECRET)
    return {"home": home, "tool": tool, "own": own, "runner": runner}


@pytest.fixture
def outside_tmp():
    """A folder outside /tmp, which bubblewrap replaces with an empty one (and Unix socket paths must be short)."""
    base = Path(tempfile.mkdtemp(dir="/var/tmp"))
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _isolate(monkeypatch, paths: dict[str, Path]) -> None:
    monkeypatch.setenv("HOME", str(paths["home"]))
    monkeypatch.delenv("ROBOUSE_CACHE_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(paths["runner"]))
    monkeypatch.setattr(_maintainer, "private_dirs", lambda: [])


def test_the_profile_and_bwrap_deny_credential_and_task_copy_locations(outside_tmp, monkeypatch) -> None:
    tmp_path = outside_tmp
    p = _home(tmp_path)
    _isolate(monkeypatch, p)
    real = {k: os.path.realpath(v) for k, v in p.items()}
    home = real["home"]
    denied = [f"{home}/{d}" for d in (".cache/uv", ".cache/benchflow", ".config/benchflow", ".claude", ".codex")]
    denied += [
        f"{home}/.claude-second",
        f"{home}/.claude.json",
        f"{home}/.env",
        f"{home}/.cache/robouse",
        real["runner"],
    ]
    own = sandbox.own_homes({"CODEX_HOME": str(p["own"]), "PATH": "/usr/bin"})
    assert own == [real["own"]]

    prof = sandbox.sandbox_profile(tmp_path / "ws", (), [], own)
    for d in denied:
        assert f'(deny file-read* file-write* (subpath "{d}"))' in prof, d
    programs = f"{home}/.codex/packages"
    assert f'(allow file-read* (subpath "{programs}"))' in prof  # the program folder: read only
    assert f'(allow file-read* file-write* (subpath "{programs}"))' not in prof
    own_rule = f'(allow file-read* file-write* (subpath "{real["own"]}"))'
    assert prof.index(own_rule) > prof.index(f'"{home}/.cache/robouse"')  # later rules win

    args = sandbox.bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [], own)
    pairs = list(zip(args, args[1:], strict=False))
    for d in denied:
        if os.path.isdir(d):
            assert ("--tmpfs", d) in pairs, d
    assert args[args.index(f"{home}/.claude.json") - 1] == "/dev/null"  # a file: /dev/null over it
    assert args[args.index(f"{home}/.netrc") - 2 : args.index(f"{home}/.netrc")] == ["--ro-bind", "/dev/null"]
    assert args[args.index(f"{home}/.env") - 2 : args.index(f"{home}/.env")] == ["--ro-bind", "/dev/null"]
    assert args.index(programs) > args.index(f"{home}/.codex") and ("--ro-bind", programs) in pairs
    assert ("--bind", real["own"]) in pairs and args.index(real["own"]) > args.index(f"{home}/.cache/robouse")


def test_a_dotenv_file_above_the_trial_s_folders_is_denied(outside_tmp, monkeypatch) -> None:
    """A project keeps its keys in a .env, and dotenv loaders (Gemini CLI's among them) look for one in every folder
    above the current one. A .env above the trial's run folder, its task folder or robouse's install (a project's .env
    next to its virtualenv) is denied on macOS and Linux; one anywhere else is not this list's business."""
    base = outside_tmp
    _isolate(monkeypatch, _home(base))
    project = base / "project"
    job, task = project / "runs" / "job", project / "tasks" / "suite" / "task"
    for d in (job, task, base / "elsewhere"):
        d.mkdir(parents=True)
    for d in (project, project / "runs", base / "elsewhere"):
        (d / ".env").write_text(SECRET)
    near, runs, far = (os.path.realpath(d / ".env") for d in (project, project / "runs", base / "elsewhere"))
    monkeypatch.setattr(sandbox, "PKG", base / "venv" / "lib" / "site-packages" / "robouse")
    denied = sandbox._denied([job, task])
    assert near in denied and runs in denied and far not in denied
    prof = sandbox.sandbox_profile(base / "ws", (), [job, task], [])
    assert f'(deny file-read* file-write* (subpath "{near}"))' in prof and far not in prof
    args = sandbox.bwrap_args(base / "ws", str(base / "sock"), [job, task], [])
    assert args[args.index(near) - 2 : args.index(near)] == ["--ro-bind", "/dev/null"] and far not in args
    monkeypatch.setattr(sandbox, "PKG", project / ".venv" / "lib" / "python3.12" / "site-packages" / "robouse")
    assert near in sandbox._denied([])  # robouse installed in the project's virtualenv


def _libero(base: Path, monkeypatch) -> list[Path]:
    """A stand-in for hf-libero on the runner's sys.path, and a LIBERO config naming another environment's copy of its
    task data, as ~/.libero/config.yaml can (LIBERO writes it once, for the environment that first imports it). The
    task data files, each holding SECRET."""
    site, other = base / "site", base / "other-env" / "libero" / "libero"
    (site / "libero").mkdir(parents=True)
    (site / "libero" / "__init__.py").write_text("")
    files = []
    for pkg in (site / "libero" / "libero", other):
        for rel in ("bddl_files/libero_spatial/task.bddl", "init_files/libero_spatial/task.pruned_init"):
            (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
            (pkg / rel).write_text(SECRET)
            files.append(pkg / rel)
    (site / "libero" / "libero" / "envs").mkdir()
    cfg = base / "libero-config"
    cfg.mkdir()
    (cfg / "config.yaml").write_text(f"bddl_files: {other / 'bddl_files'}\ninit_states: {other / 'init_files'}\n")
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.setenv("LIBERO_CONFIG_PATH", str(cfg))
    return files


def test_libero_s_task_data_is_denied_where_the_runner_finds_it(outside_tmp, monkeypatch) -> None:
    """hf-libero's scene files (bddl_files) and saved start states (init_files) give a LIBERO task's object layout away,
    which its vision tasks show only as camera images. They are denied in the hf-libero the runner's Python finds, without
    importing it, and where LIBERO's config points; the rest of the package is not."""
    base = outside_tmp
    _libero(base, monkeypatch)
    pkg, other = base / "site" / "libero" / "libero", base / "other-env" / "libero" / "libero"
    want = [os.path.realpath(p / d) for p in (pkg, other) for d in ("bddl_files", "init_files")]
    assert sorted(sandbox.libero_data()) == sorted(want)
    assert not [m for m in list(sys.modules.values()) if str(getattr(m, "__file__", "")).startswith(str(base))]
    prof = sandbox.sandbox_profile(base / "ws", (), [], [])
    for d in want:
        assert f'(deny file-read* file-write* (subpath "{d}"))' in prof, d
    assert os.path.realpath(pkg / "envs") not in prof
    args = sandbox.bwrap_args(base / "ws", str(base / "sock"), [], [])
    for d in want:
        assert args[args.index(d) - 1] == "--tmpfs", d


def test_a_source_checkout_s_tasks_runs_and_generators_are_denied(tmp_path, monkeypatch) -> None:
    """Run from a checkout, the agent could read every other task's reference solution in tasks/ (the Oct 13 Linux
    sandbox exposed 1,943 oracle files in /opt/robouse; deep audit, security item 3), other trials in runs/ and the
    generators in adapters/, and change the robot models in assets/ that later trials load. An installed package is
    denied whole."""
    repo = tmp_path / "repo"
    (repo / "src" / "robouse").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("")
    monkeypatch.setattr(sandbox, "PKG", repo / "src" / "robouse")
    assert sandbox.checkout_denied() == [str(repo / d) for d in ("tasks", "runs", "adapters", "assets")]
    for d in ("tasks", "runs", "adapters", "assets"):
        assert os.path.realpath(repo / d) in sandbox._denied([])
    monkeypatch.setattr(sandbox, "PKG", tmp_path / "venv" / "lib" / "site-packages" / "robouse")
    assert sandbox.checkout_denied() == []


def test_macos_agents_cannot_start_programs_that_act_outside_the_sandbox(tmp_path) -> None:
    """`open` hands a file or URL to LaunchServices, outside Seatbelt (108 calls in the Mac runs; deep audit, security
    item 8); `osascript` and `shortcuts` drive other applications. Checked on macOS 26 with sandbox-exec: both exit
    126 (Operation not permitted), and a copy of `open` elsewhere is killed by code signing.

    `security` looked up the Claude Code and GitHub CLI login items in the login keychain from inside the profile
    (macOS 26.5, sandbox-exec; file rules do not cover the keychain). Refused, it exits 126 from a shell; a symlink to it
    is refused and a copy is killed by code signing. Refusing securityd's Mach service instead broke Codex's TLS."""
    prof = sandbox.sandbox_profile(tmp_path / "ws")
    programs = " ".join(f'(literal "/usr/bin/{p}")' for p in ("open", "osascript", "shortcuts", "security"))
    assert f"(deny process-exec {programs})" in prof
    assert "(deny appleevent-send)" in prof
    assert "SecurityServer" not in prof


def test_macos_agents_can_resolve_their_own_home_inside_a_denied_folder(tmp_path, monkeypatch) -> None:
    """Codex canonicalizes CODEX_HOME, which needs the metadata of every folder above it. Inside robouse's cache
    (denied) that failed on macOS ("failed to canonicalize CODEX_HOME: Operation not permitted"; sandbox-exec, Codex
    0.162.1), so Codex ran without its PATH aliases. The profile now allows the metadata of those folders, never their
    contents."""
    p = _home(tmp_path)
    _isolate(monkeypatch, p)
    own = sandbox.own_homes({"CODEX_HOME": str(p["own"])})
    prof = sandbox.sandbox_profile(tmp_path / "ws", (), [], own)
    cache, codex = (os.path.realpath(p["home"] / rel) for rel in (".cache/robouse", ".codex"))
    rule = prof[prof.index("(allow file-read-metadata ") :]
    rule = rule[: rule.index("))") + 2]
    assert f'(literal "{cache}")' in rule and f'(literal "{codex}")' in rule  # above the own home and ~/.codex/packages
    assert f'(literal "{own[0]}")' not in rule and prof.index(rule) > prof.index(f'(subpath "{cache}")')
    assert f'(allow file-read* (literal "{cache}"))' not in prof
    assert f'(allow file-read* (subpath "{cache}"))' not in prof


def test_the_runner_s_python_is_read_only_to_agents(tmp_path) -> None:
    """The episode server and the verifier run on the runner's Python, so an agent must not change it (deep audit,
    security item 10). bubblewrap binds it read-only before the denied folders, so a robouse install inside it stays
    hidden."""
    prefix = os.path.realpath(sys.prefix)
    assert prefix in sandbox.interpreters()
    assert f'(deny file-write* (subpath "{prefix}"))' in sandbox.sandbox_profile(tmp_path / "ws")
    args = sandbox.bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [])
    if not prefix.startswith("/tmp/"):
        i = args.index(prefix)
        assert args[i - 1 : i + 2] == ["--ro-bind", prefix, prefix] and i < args.index(os.path.realpath(sandbox.PKG))


def test_the_profile_refuses_sockets_of_denied_folders_other_trials_and_the_machine(tmp_path, monkeypatch) -> None:
    """Seatbelt's file rules do not stop a connection to a Unix socket (checked on macOS 26 with nc -U): every denied
    path also gets a network rule. Other trials' episode sockets are refused, the agent's own is not, and the SSH agent
    and container engine sockets are denied on both platforms."""
    p = _home(tmp_path)
    _isolate(monkeypatch, p)
    agent = tmp_path / "ssh-agent.sock"
    agent.write_text("")  # stands in for the socket: bubblewrap puts /dev/null over any denied file
    monkeypatch.setenv("SSH_AUTH_SOCK", str(agent))
    real_agent = os.path.realpath(agent)
    assert real_agent in sandbox._denied([]) and "/var/run/docker.sock" in sandbox.SOCKETS
    sock = "/tmp/robouse-0123456789.sock"
    prof = sandbox.sandbox_profile(tmp_path / "ws", (), [], [], sock)
    home = os.path.realpath(p["home"])
    for d in (f"{home}/.docker", f"{home}/.cache/robouse", real_agent, os.path.realpath("/var/run/docker.sock")):
        assert f'(deny network-outbound (remote unix-socket (subpath "{d}")))' in prof, d
    tmp = re.escape(os.path.realpath("/tmp"))
    deny_others = f'(deny network-outbound (remote unix-socket (path-regex #"^{tmp}/robouse-[0-9a-f]+\\.sock$")))'
    allow_own = f'(allow network-outbound (remote unix-socket (path-literal "{os.path.realpath(sock)}")))'
    assert prof.index(deny_others) < prof.index(allow_own)


def test_path_entries_the_agent_cannot_reach_are_dropped(tmp_path, monkeypatch) -> None:
    """`uvx` puts its environment, in the uv cache, first on PATH; inside the sandbox nothing there can run."""
    p = _home(tmp_path)
    _isolate(monkeypatch, p)
    uvx = p["home"] / ".cache" / "uv" / "archive-v0" / "abc" / "bin"
    uvx.mkdir(parents=True)
    path = os.pathsep.join([str(uvx), str(p["tool"].parent), "/usr/bin", "", str(p["own"])])
    kept = sandbox.reachable_path(path, [], [str(p["own"])]).split(os.pathsep)
    assert kept == [str(p["tool"].parent), "/usr/bin", "", str(p["own"])]


def test_the_robo_mcp_server_runs_on_a_python_the_agent_can_run(tmp_path, monkeypatch) -> None:
    """A runner in uvx's denied cache and a silent python3 on PATH do not affect the stdlib MCP server."""
    p = _home(tmp_path)
    _isolate(monkeypatch, p)
    uvx, system = p["home"] / ".cache" / "uv" / "archive-v0" / "abc" / "bin", tmp_path / "usr" / "bin"
    for d in (uvx, system):
        d.mkdir(parents=True)
    (uvx / "python3").symlink_to(sys.executable)
    (system / "python3").write_text("#!/bin/sh\nexit 0\n")
    (system / "python3").chmod(0o755)
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    path = os.pathsep.join([str(ws / ".robouse" / "bin"), str(uvx), str(system)])
    monkeypatch.setattr(sys, "executable", str(uvx / "python3"))
    monkeypatch.setenv("PATH", path)
    import json
    import subprocess

    from robouse.runner.trial import AGENT_CLI, MCP_SERVER

    (ws / ".robouse" / "bin" / "robo_cli.py").write_text(AGENT_CLI.read_text())
    (ws / ".robouse" / "bin" / "robo_mcp.py").write_text(MCP_SERVER.read_text())
    for setting in ("1", "0"):
        monkeypatch.setenv("ROBOUSE_SANDBOX", setting)
        cfg = iface.stdio_config(ws, "/tmp/x.sock", {"PATH": path})
        assert ".cache/uv" not in cfg["command"] and cfg["command"] != str(system / "python3")
        result = subprocess.run(
            [cfg["command"], *cfg["args"]],
            input='{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"jsonrpc": "2.0", "id": 1, "result": {}}


PEEK = r"""robo done peek >/dev/null
for f in {planted} {runner}/.credentials.json; do
  cat "$f" 2>/dev/null | grep -q {secret} && echo "LEAK $f"
done
grep -q OWN "$CODEX_HOME/auth.json" && echo own-readable
touch "$CODEX_HOME/new" && echo own-writable
{tool}
touch {tool_dir}/x 2>/dev/null && echo program-writable
touch {prefix}/.robouse-write-probe 2>/dev/null && echo prefix-writable
cat {other_oracle} >/dev/null 2>&1 && echo other-oracle-readable
if [ "$(uname)" = Darwin ]; then
  /usr/bin/osascript -e 'return "osascript-ran"' 2>/dev/null
  /usr/bin/open -h >/dev/null 2>&1; echo "open-rc=$?"
  /usr/bin/security list-keychains >/dev/null 2>&1; echo "security-rc=$?"
fi
echo "runner-home=${{CLAUDE_CONFIG_DIR:-unset}} ssh-agent=${{SSH_AUTH_SOCK:-unset}}"
for s in {sockets}; do
  python3 -c 'import socket, sys; s = socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect(sys.argv[1]); print("CONNECTED", sys.argv[1])' "$s" 2>/dev/null
done
exit 0
"""


def _listen(path: Path) -> socket.socket:
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.listen(8)
    return s


def test_a_sandboxed_agent_reads_no_credential_or_task_copy(tmp_path, outside_tmp, monkeypatch) -> None:
    """A whole trial under this platform's sandbox: a scripted agent tries every planted location and the runner's own
    Claude Code home, and connects to a Docker socket inside ~/.docker, a container engine socket, the SSH agent and
    another trial's episode socket. It can use only its own Codex home, run (not change) a program inside ~/.codex,
    and reach a socket nobody denied (the control). Everything sits in /var/tmp: bubblewrap replaces /tmp anyway, and
    a Unix socket path must be short."""
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    if not (sys.platform == "darwin" or (sys.platform.startswith("linux") and sandbox.bwrap_works())):
        pytest.skip("needs the macOS Seatbelt sandbox or working bubblewrap on Linux")
    base = outside_tmp
    other = Path(f"/tmp/robouse-{os.urandom(5).hex()}.sock")  # another trial's episode socket
    listening = []
    try:
        p = _home(base)
        _isolate(monkeypatch, p)
        monkeypatch.delenv("ROBOUSE_SANDBOX", raising=False)
        sockets = {
            "docker-desktop": p["home"] / ".docker" / "run" / "docker.sock",
            "engine": base / "run" / "docker.sock",
            "ssh-agent": base / "ssh" / "agent.sock",
            "other-trial": other,
            "control": base / "free" / "free.sock",
        }
        listening = [_listen(s) for s in sockets.values()]
        monkeypatch.setattr(sandbox, "SOCKETS", (str(sockets["engine"]),))
        monkeypatch.setenv("SSH_AUTH_SOCK", str(sockets["ssh-agent"]))
        (tmp_path / ".env").write_text(SECRET)  # a .env above the trial's run folder (tmp_path / "job")
        libero = _libero(base, monkeypatch)  # LIBERO's task data, as the runner's Python finds it
        assert all(f.read_text() == SECRET for f in libero)  # outside the sandbox (the episode server), readable
        script = PEEK.format(
            planted=" ".join([*(str(p["home"] / rel) for rel in PLANTED), str(tmp_path / ".env"), *map(str, libero)]),
            runner=p["runner"],
            secret=SECRET,
            tool=p["tool"],
            tool_dir=p["tool"].parent,
            sockets=" ".join(str(s) for s in sockets.values()),
            prefix=sys.prefix,
            other_oracle=ROOT / "tasks" / "arc-style" / "arc-mirror" / "oracle" / "solve.sh",
        )

        def peek(model, prompt, workspace, task, env) -> harnesses.Launch:
            (workspace / ".robouse" / "peek.sh").write_text(script)
            env["CODEX_HOME"] = str(p["own"])
            return harnesses.Launch(["bash", str(workspace / ".robouse" / "peek.sh")], env, notes={"model": "none"})

        monkeypatch.setitem(harnesses.HARNESSES, "peek", peek)
        res = run_trial(load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"), "peek", "", tmp_path / "job")
        out = (tmp_path / "job" / res["trial"] / "agent" / "stdout.jsonl").read_text()
        cfg = (tmp_path / "job" / res["trial"] / "config.json").read_text()
        assert '"sandbox": "none"' not in cfg
        assert "LEAK" not in out, out
        assert "own-readable" in out and "own-writable" in out, out
        assert "program-ok" in out and "program-writable" not in out, out
        assert "prefix-writable" not in out, out  # the runner's Python, which the next episode server runs on
        if sys.platform == "darwin":  # LaunchServices, Apple events and the login keychain are outside the sandbox
            assert "osascript-ran" not in out and "open-rc=126" in out and "security-rc=126" in out, out
        if sandbox.checkout_denied():  # robouse runs from this checkout: the other tasks' oracles are out of reach
            assert "other-oracle-readable" not in out, out
        assert "runner-home=unset ssh-agent=unset" in out, out
        assert [line.split()[1] for line in out.splitlines() if line.startswith("CONNECTED")] == [
            str(sockets["control"])
        ], out
        assert res["exception"] is None, res
    finally:
        for s in listening:
            s.close()
        other.unlink(missing_ok=True)
        Path(sys.prefix, ".robouse-write-probe").unlink(missing_ok=True)


def test_an_agent_cannot_change_a_robot_model_a_later_trial_loads(tmp_path, outside_tmp, monkeypatch) -> None:
    """The episode server loads robot models from the checkout's assets/ or $ROBOUSE_MENAGERIE_ASSETS, outside the
    sandbox, in every later trial, so an agent that changed one would change later trials' robots. A sandboxed agent
    tries to break the Panda's model where $ROBOUSE_MENAGERIE_ASSETS puts it, and to read the checkout's copy (only read,
    so that a failure cannot damage this checkout). Neither works, the model is unchanged, and the next trial on a task
    with that robot loads it and runs."""
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    if not (sys.platform == "darwin" or (sys.platform.startswith("linux") and sandbox.bwrap_works())):
        pytest.skip("needs the macOS Seatbelt sandbox or working bubblewrap on Linux")
    panda = ROOT / "assets" / "menagerie" / "franka_emika_panda"
    if not (panda / "panda.xml").is_file():
        pytest.skip("this checkout has no MuJoCo Menagerie Panda (assets/menagerie)")
    models = outside_tmp / "menagerie"
    shutil.copytree(panda, models / "franka_emika_panda")
    xml = models / "franka_emika_panda" / "panda.xml"
    original = xml.read_bytes()
    monkeypatch.setenv("ROBOUSE_MENAGERIE_ASSETS", str(models))
    monkeypatch.delenv("ROBOUSE_SANDBOX", raising=False)
    script = (
        f'printf "not a model" >> "{xml}" 2>/dev/null && echo "CHANGED {xml}"\n'
        f'cat "{panda / "panda.xml"}" >/dev/null 2>&1 && echo "READ {panda}"\n'
        "robo done tamper\n"
    )

    def tamper(model, prompt, workspace, task, env) -> harnesses.Launch:
        (workspace / ".robouse" / "tamper.sh").write_text(script)
        return harnesses.Launch(["bash", str(workspace / ".robouse" / "tamper.sh")], env, notes={"model": "none"})

    monkeypatch.setitem(harnesses.HARNESSES, "tamper", tamper)
    res = run_trial(load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"), "tamper", "", tmp_path / "job")
    trial = tmp_path / "job" / res["trial"]
    out = (trial / "agent" / "stdout.jsonl").read_text()
    assert '"sandbox": "none"' not in (trial / "config.json").read_text()
    assert "CHANGED" not in out and xml.read_bytes() == original, out
    if sandbox.checkout_denied():  # robouse runs from this checkout: its assets/ is out of reach too
        assert "READ" not in out, out
    nxt = run_trial(
        load_task(ROOT / "tasks" / "menagerie" / "menagerie-panda-precise-landing"), "noop", "", tmp_path / "n"
    )
    assert nxt["exception"] is None and nxt["reward"] == 0.0, nxt


def test_mini_swe_agent_loads_no_global_env_of_the_user(tmp_path, monkeypatch) -> None:
    """mini-swe-agent loads `<global config dir>/.env` into its own environment, which the agent's shell inherits: a
    user's provider key there would reach the agent (and the sandbox now denies the folder). Each trial gets an empty
    one in its workspace."""
    from types import SimpleNamespace

    from robouse.harnesses import models

    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    gw = SimpleNamespace(url="http://127.0.0.1:1", key="k", model="m", stats={}, stop=lambda: None, stop_file=None)
    monkeypatch.setattr(harnesses, "_gateway", lambda ref, env, protocol: gw)
    monkeypatch.setattr(models, "resolve", lambda h, m: SimpleNamespace(bare="m", id="p/m", provider="p"))
    monkeypatch.setattr(harnesses.shutil, "which", lambda name, path=None: f"/opt/bin/{name}")
    launch = harnesses.HARNESSES["mini-swe-agent"]("p/m", "TASK", ws, None, {"PATH": "/usr/bin"})
    assert launch.env["MSWEA_GLOBAL_CONFIG_DIR"] == str(ws / ".robouse" / "mini-config")


def test_each_claude_code_trial_gets_its_own_config_home(tmp_path, monkeypatch) -> None:
    """Claude Code's config folder was one shared ~/.cache/robouse/claude-home, so a trial's auto-memory could reach the
    next (deep audit, security item 11). Each trial now gets an empty one inside its own workspace, on its own vendor
    and through the gateway."""
    from types import SimpleNamespace

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-key")
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: None)
    homes = []
    for name in ("a", "b"):
        ws = tmp_path / name
        (ws / ".robouse").mkdir(parents=True)
        launch = harnesses.HARNESSES["claude-code"]("claude-opus-5-5", "TASK", ws, None, {"PATH": "/usr/bin"})
        homes.append(Path(launch.env["CLAUDE_CONFIG_DIR"]))
        assert homes[-1] == ws / ".robouse" / "claude-home" and homes[-1].is_dir() and not any(homes[-1].iterdir())
    assert homes[0] != homes[1]

    gw = SimpleNamespace(url="http://127.0.0.1:1", key="k", model="m", stats={}, stop=lambda: None, stop_file=None)
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: SimpleNamespace(bare="m", id="p/m", provider="p"))
    monkeypatch.setattr(harnesses, "_gateway", lambda ref, env, protocol: gw)
    ws = tmp_path / "c"
    (ws / ".robouse").mkdir(parents=True)
    launch = harnesses.HARNESSES["claude-code"]("p/m", "TASK", ws, None, {"PATH": "/usr/bin"})
    assert launch.env["CLAUDE_CONFIG_DIR"] == str(ws / ".robouse" / "claude-home")


def test_each_codex_trial_gets_its_own_home(tmp_path, monkeypatch) -> None:
    """Codex trials shared one CODEX_HOME in robouse's cache (codex-home, or codex-home-gateway), with the sessions and
    memories Codex keeps there, so a trial could read what an earlier one left (as with Claude Code; deep audit,
    security item 11). Each trial now gets a new private home, on its own vendor and through the gateway, removed when
    the trial ends. A failed login or gateway leaves nothing behind, and an account pool's home is never removed."""
    from types import SimpleNamespace

    from robouse.harnesses import credentials

    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "auth.json").write_text("LOGIN")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(_maintainer, "codex_accounts", lambda: [])
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: None)
    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    launches = [harnesses.HARNESSES["codex"]("gpt-6-astra", "TASK", ws, None, {"PATH": "/usr/bin"}) for _ in "ab"]
    homes = [Path(launch.env["CODEX_HOME"]) for launch in launches]
    assert homes[0] != homes[1]
    for h in homes:
        assert h.parent == credentials.trial_homes() and h.stat().st_mode & 0o777 == 0o700
        auth = h / "auth.json"
        assert not auth.is_symlink() and auth.read_text() == "LOGIN" and auth.stat().st_mode & 0o777 == 0o600
    (homes[0] / "sessions").mkdir()
    (homes[0] / "sessions" / "rollout.jsonl").write_text("{}")
    launches[0].stop()
    assert not homes[0].exists() and homes[1].exists()
    assert (home / ".codex" / "auth.json").read_text() == "LOGIN"  # the user's login is a source, never touched

    # through the gateway: no login in the home, and the gateway stops before the home goes
    stopped = []
    gw = SimpleNamespace(
        url="http://127.0.0.1:1", key="k", model="m", stats={}, stop=lambda: stopped.append(1), stop_file=None
    )
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: SimpleNamespace(bare="m", id="p/m", provider="p"))
    monkeypatch.setattr(harnesses, "_gateway", lambda ref, env, protocol: gw)
    launch = harnesses.HARNESSES["codex"]("p/m", "TASK", ws, None, {"PATH": "/usr/bin"})
    via = Path(launch.env["CODEX_HOME"])
    assert via.parent == credentials.trial_homes() and not (via / "auth.json").exists() and via != homes[1]
    launch.stop()
    assert stopped == [1] and not via.exists()

    def no_gateway(ref, env, protocol):
        raise RuntimeError("model p/m needs P_KEY in the environment")

    monkeypatch.setattr(harnesses, "_gateway", no_gateway)
    with pytest.raises(RuntimeError, match="P_KEY"):
        harnesses.HARNESSES["codex"]("p/m", "TASK", ws, None, {"PATH": "/usr/bin"})
    (home / ".codex" / "auth.json").unlink()
    monkeypatch.setattr(harnesses, "_via_gateway", lambda h, m: None)
    with pytest.raises(RuntimeError, match="no Codex credentials"):
        harnesses.HARNESSES["codex"]("gpt-6-astra", "TASK", ws, None, {"PATH": "/usr/bin"})
    assert list(credentials.trial_homes().iterdir()) == [homes[1]]

    pool_home = tmp_path / "cache" / "codex-home-account"
    pool_home.mkdir()
    credentials.remove_trial_home(str(pool_home))
    assert pool_home.is_dir()


# ---- the agent's environment -------------------------------------------------------------------------------------

CREDENTIAL_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_MESSAGING_TOKEN",  # the launching Claude Code session's (audit, security item 1)
    "CODEX_AUTH_JSON",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "DAYTONA_API_KEY",
    "WANDB_API_KEY",
    "PGPASSWORD",
    "NPM_CONFIG__AUTH",
    "SSH_AUTH_SOCK",
    "ROBOUSE_GRADER_API_KEY",
    "ROBOUSE_BEHAVIOR_SECRET",
    "ROBOUSE_MOLMOACT2_TOKEN",
    "ZAI_API_KEY",
)
HARMLESS_VARS = ("PATH", "HOME", "LANG", "MUJOCO_GL", "TOKENIZERS_PARALLELISM", "GIT_AUTHOR_NAME", "HTTPS_PROXY")


def test_no_credential_variable_reaches_an_agent(monkeypatch) -> None:
    """A Mac agent ran `env` and printed a provider key and CLAUDE_CODE_MESSAGING_TOKEN, both inherited from the session
    that launched the runner (audit, security item 1). Only provider keys were filtered, by name: now every variable
    whose name marks a credential is dropped, and the rest of the environment stays."""
    from robouse.runner import trial

    monkeypatch.setattr(trial, "_secret_env_names", lambda: {"ZAI_API_KEY"})
    environ = {k: "not-a-real-credential" for k in (*CREDENTIAL_VARS, *HARMLESS_VARS)}
    env = trial.agent_env(environ)
    assert sorted(env) == sorted(HARMLESS_VARS)


def test_z_ai_settings_count_as_provider_settings(monkeypatch) -> None:
    """A Z.ai key kept under another name (GLM_CODING_API_KEY) and its endpoint (GLM_BASE_URL) reach neither the agent
    nor the episode server and verifier, as on the no-baseten branch."""
    from robouse.runner import trial

    monkeypatch.setattr(trial, "_secret_env_names", lambda: set())
    environ = {"GLM_CODING_API_KEY": "k", "GLM_BASE_URL": "http://127.0.0.1:9/v1", "ZAI_REGION": "x", "PATH": "/bin"}
    assert trial.agent_env(environ) == {"PATH": "/bin"}
    assert trial.without_provider_keys(environ) == {"PATH": "/bin"}


def test_a_trial_s_agent_inherits_no_credential(tmp_path, monkeypatch) -> None:
    """The whole runner: a scripted agent prints its environment. Credentials set in the runner's environment are
    absent; the episode socket and the runner's harmless settings are there."""
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")  # the variables, not the sandbox, are under test
    for k in CREDENTIAL_VARS:
        monkeypatch.setenv(k, f"LEAK-{k}")
    # a harmless setting that must stay (not MUJOCO_GL: the session already chose the OpenGL platform, and the
    # episode server renders with it)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "kept")

    def dump(model, prompt, workspace, task, env) -> harnesses.Launch:
        return harnesses.Launch(["sh", "-c", "robo done ok >/dev/null; env"], env, notes={"model": "none"})

    monkeypatch.setitem(harnesses.HARNESSES, "dump", dump)
    res = run_trial(load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"), "dump", "", tmp_path / "job")
    assert res["exception"] is None, res
    out = (tmp_path / "job" / res["trial"] / "agent" / "stdout.jsonl").read_text()
    assert "LEAK-" not in out, [line for line in out.splitlines() if "LEAK-" in line]
    assert "ROBOUSE_SOCKET=" in out and "GIT_AUTHOR_NAME=kept" in out


def test_molmoact2_gets_its_server_token_from_the_harness(tmp_path, monkeypatch) -> None:
    """The MolmoAct2 client relied on the runner passing ROBOUSE_MOLMOACT2_TOKEN through; the harness now adds it."""
    from types import SimpleNamespace

    monkeypatch.setenv("ROBOUSE_MOLMOACT2_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ROBOUSE_MOLMOACT2_TOKEN", "preview-token")
    (tmp_path / ".robouse").mkdir()
    task = SimpleNamespace(metadata={"language_instruction": "stack"}, meta={}, spec={})
    launch = harnesses.HARNESSES["molmoact2"]("", "TASK", tmp_path, task, {"PATH": "/usr/bin"})
    assert launch.env["ROBOUSE_MOLMOACT2_TOKEN"] == "preview-token"


def test_the_episode_server_and_verifier_get_no_provider_key(tmp_path, monkeypatch) -> None:
    """The episode server and the verifier never call a model, yet inherited the runner's provider keys, where other
    processes of this user could read them (audit, security item 4). Their other settings stay."""
    pytest.importorskip("mujoco")
    import subprocess

    from robouse.runner import run_trial
    from robouse.tasks import load_task

    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "BASETEN_API_KEY"):
        monkeypatch.setenv(k, "LEAK")
    monkeypatch.setenv("HF_TOKEN", "kept")  # not a model provider key: a simulator may need it to download assets
    seen: dict[str, dict] = {}
    popen, run = subprocess.Popen, subprocess.run

    def spy_popen(cmd, *args, **kw):
        if "serve" in cmd:
            seen["server"] = dict(kw.get("env") or os.environ)
        return popen(cmd, *args, **kw)

    def spy_run(cmd, *args, **kw):
        if cmd[:1] == ["bash"] and str(cmd[-1]).endswith("test.sh"):
            seen["verifier"] = dict(kw.get("env") or os.environ)
        return run(cmd, *args, **kw)

    def done(model, prompt, workspace, task, env) -> harnesses.Launch:
        return harnesses.Launch(["robo", "done", "ok"], env, notes={"model": "none"})

    monkeypatch.setattr(subprocess, "Popen", spy_popen)
    monkeypatch.setattr(subprocess, "run", spy_run)
    monkeypatch.setitem(harnesses.HARNESSES, "done", done)
    res = run_trial(load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"), "done", "", tmp_path / "job")
    assert res["exception"] is None, res
    assert sorted(seen) == ["server", "verifier"]
    for name, env in seen.items():
        assert not [k for k, v in env.items() if v == "LEAK"], name
        assert env["HF_TOKEN"] == "kept" and env["PATH"], name
