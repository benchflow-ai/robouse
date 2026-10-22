"""Harness launchers: the command, environment and helper process for one trial's agent.

The agent process gets: its prompt (PROMPT_PREFIX + the task.md body), cwd = an isolated workspace (observations/),
PATH with a standard-library `robo` shim first, and ROBOUSE_SOCKET. Credentials come from the environment
(`credentials.py`).

Harnesses
  oracle                 the task's reference solution (oracle/solve.sh)
  noop                   calls `robo done` immediately (negative control)
  claude-code            Claude Code CLI; model: a bare Claude id (Anthropic, own credentials) or any provider-prefixed
                         id, e.g. glm/glm-5.3, reached through the trial's model gateway (gateway.py)
  codex                  Codex CLI; model: a bare OpenAI id (own credentials or the account pool) or a provider-prefixed
                         id through the gateway (a provider with a Responses endpoint)
  gemini-cli             Gemini CLI; model: a Gemini API model, bare or gemini/<id> (default gemini-4-argon), on its own
                         vendor with GEMINI_API_KEY, never through the gateway; see gemini_cli.py
  mini-swe-agent         mini-swe-agent; model: a provider-prefixed id, always through the gateway (default
                         glm/glm-5.3: GLM-5.3 on the Z.ai Coding Plan)
  dimcode                Dimensional's dimcode (built on Pi); model: a provider-prefixed id, always through the
                         gateway (default glm/glm-5.3); see dimcode.py
  kinex                  Kinex (built on Pi), with the robot as Kinex devices served by a RoboEnv-compatible bridge;
                         model: a provider-prefixed id, always through the gateway (default glm/glm-5.3); see kinex/
  show-harness           NUS Show Lab's Show-Harness: a VLM picks one parameter-free action unit at a time
                         (MV_FWD, GRASP, ...) and an interpreter grounds it; model (required): a provider-prefixed id
                         through the gateway (zero-shot mode) or a self-hosted fine-tuned model at
                         $ROBOUSE_SHOW_HARNESS_URL; see show_harness/
  (claude-code-glm, codex-glm and mini-swe-agent-glm: the September 2026 runs' names for the first three with a
  Baseten model; read in their trial folders, refused for a new run)
  molmoact2              MolmoAct2 VLA policy: molmoact2/client.py drives `robo` with action chunks from a policy
                         server at $ROBOUSE_MOLMOACT2_URL; model e.g. allenai/MolmoAct2-LIBERO-LeRobot
  vla                    any served VLA (vla/client.py): --model is a preset from vla/presets.json; server at
                         $ROBOUSE_VLA_URL; overrides from $ROBOUSE_VLA_POLICY_CONFIG (JSON file)
  dream                  Dream Labs' Dream-1 through DreamAPI (dream/client.py, Dream's own client library); model
                         dreamlabs/dream-1-beta (default) or dreamlabs/dream-1-beta-flash; drives the `yam` suite
  jev                    TypeSafe's Jev, a System One model: typed decisions over each observation, executed through
                         `robo` (jev/client.py, standard library only, on the runner's Python); model typesafe/jev-latest
                         (default) or another Jev; key in $TYPESAFE_API_KEY; drives the `nav` suite (Dimensional's "Can
                         Jev Nav?" protocol)
  aspire                 NVIDIA's ASPIRE workflow (its iterative-debugging and evosearch skills, vendored) run by
                         Claude Code: practice episodes on other seeds, then the selected program on the scored
                         episode; model as for claude-code; see aspire/
  aspire-codex           the same, run by Codex; model as for codex
Third-party harnesses register a callable with `build`'s signature under the `robouse.harnesses` entry point group.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config
from . import credentials

# the only built-in tools Claude Code offers its model (`--tools`); the robo MCP tools come on top with --interface
# mcp or both. Without an allowlist it also offered web, scheduling, messaging, worktree and workflow tools
CLAUDE_TOOLS = "Bash,Read,Write,Edit,Glob,Grep"
# Codex offers its model a web search tool unless told not to (0.155 and later: on by default)
CODEX_WEB_SEARCH = 'web_search="disabled"'

PROMPT_PREFIX = (
    "You are controlling a simulated robot. Read the task below, then solve it by running the `robo` command "
    "in your shell (start with `robo info` and `robo observe`). Keep going until the task is done, then call "
    "`robo done` once. Do not stop to ask questions; there is no human to answer.\n\n"
)


@dataclass
class Launch:
    cmd: list[str]
    env: dict[str, str]
    helper: object | None = None  # e.g. a proxy's statistics, recorded in result.json
    stop: Callable[[], None] | None = None  # stops a helper process (the model gateway) after the agent exits
    stop_file: Path | None = None  # written by the model gateway when the trial's spend cap is reached
    notes: dict[str, Any] = field(default_factory=dict)
    deny: list[Path] = field(default_factory=list)  # more paths the agent may neither read nor write (sandbox)
    read_only: list[Path] = field(default_factory=list)  # paths the agent may read but not write (sandbox)
    config: dict[str, Any] = field(default_factory=dict)  # the harness's settings, recorded in config.json
    # what the harness did, recorded in result.json once it has stopped; it is told whether the trial's verdict is a
    # verified result (signed by the episode server, no integrity failure)
    record: Callable[[bool], dict] | None = None


Builder = Callable[[str, str, Path, Any, dict], Launch]  # (model, prompt, workspace, task, env) -> Launch


def _claude_cmd(
    prompt: str, model: str, prefix: str = PROMPT_PREFIX, tools: str = CLAUDE_TOOLS, max_turns: int = 400
) -> list[str]:
    return [
        "claude",
        "-p",
        prefix + prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--max-turns",
        str(max_turns),
        "--tools",
        tools,
    ]


def _codex_cmd(
    prompt: str,
    model: str,
    workspace: Path,
    extra: tuple[str, ...] | list[str] = (),
    prefix: str = PROMPT_PREFIX,
) -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "-c",
        CODEX_WEB_SEARCH,
        *extra,
        "-m",
        model,
        "-C",
        str(workspace),
        prefix + prompt,
    ]


def _oracle(model, prompt, workspace, task, env) -> Launch:
    return Launch(["bash", str(task.oracle_script)], env, notes={"model": "scripted"})


def _noop(model, prompt, workspace, task, env) -> Launch:
    return Launch(["robo", "done", "noop control"], env, notes={"model": "none"})


# runner to builder only: the trial folder, the image-input decision, the spend cap, and the trial's seed, split and
# agent time (JSON), which a harness that runs more than one episode needs
PRIVATE_ENV = ("_ROBOUSE_TRIAL_DIR", "_ROBOUSE_IMAGE_INPUT", "_ROBOUSE_SPEND_CAP_USD", "_ROBOUSE_TRIAL")
# the protocol each harness speaks to its model gateway (claude-code and codex only for a model not of their own vendor)
GATEWAY_PROTOCOLS = {
    "claude-code": "anthropic-messages",
    "codex": "openai-responses",
    "mini-swe-agent": "openai-completions",
    "dimcode": "anthropic-messages",
    "kinex": "anthropic-messages",
    "show-harness": "openai-completions",
    "aspire": "anthropic-messages",  # Claude Code
    "aspire-codex": "openai-responses",  # Codex
}


def _gateway(ref, env: dict, protocol: str):
    """Start this trial's model gateway (harnesses/gateway.py). The runner passes the trial folder, the image-input
    decision and the spend cap in private variables, removed here so the agent never sees them."""
    from . import gateway

    run_dir = Path(env.pop("_ROBOUSE_TRIAL_DIR"))
    images = env.pop("_ROBOUSE_IMAGE_INPUT", "1") == "1"
    cap = float(env.pop("_ROBOUSE_SPEND_CAP_USD", "0") or 0)
    return gateway.start(ref, run_dir, images=images, protocol=protocol, spend_cap_usd=cap)


def _gateway_launch(gw, ref, cmd: list[str], env: dict) -> Launch:
    return Launch(
        cmd,
        env,
        helper=gw.stats,
        stop=gw.stop,
        stop_file=gw.stop_file,
        notes={"model": ref.bare, "model_id": ref.id, "provider": ref.provider},
    )


def _via_gateway(harness: str, model: str) -> object | None:
    """The resolved model when `harness` should reach it through the gateway, else None (the harness's own vendor)."""
    from . import models

    ref = models.resolve(harness, model)
    return None if models.NATIVE_VENDORS.get(harness) == ref.provider else ref


def _claude_code(
    model, prompt, workspace, task, env, prefix: str = PROMPT_PREFIX, tools: str = CLAUDE_TOOLS, max_turns: int = 400
) -> Launch:
    if model and (ref := _via_gateway("claude-code", model)) is not None:
        home = credentials.clean_claude_home(workspace)
        gw = _gateway(ref, env, GATEWAY_PROTOCOLS["claude-code"])
        env.update(
            {
                "ANTHROPIC_BASE_URL": gw.url,
                "ANTHROPIC_AUTH_TOKEN": gw.key,
                "ANTHROPIC_MODEL": gw.model,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": gw.model,
                "ANTHROPIC_DEFAULT_SONNET_MODEL": gw.model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": gw.model,
                "ANTHROPIC_SMALL_FAST_MODEL": gw.model,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "CLAUDE_CONFIG_DIR": home,
            }
        )
        return _gateway_launch(gw, ref, _claude_cmd(prompt, gw.model, prefix, tools, max_turns), env)
    m = (model or "claude-sonnet-5").removeprefix("anthropic/")
    env.update(credentials.claude_auth())
    env["CLAUDE_CONFIG_DIR"] = credentials.clean_claude_home(workspace)
    return Launch(_claude_cmd(prompt, m, prefix, tools, max_turns), env, notes={"model": m})


def _codex(model, prompt, workspace, task, env, prefix: str = PROMPT_PREFIX) -> Launch:
    import os

    if model and (ref := _via_gateway("codex", model)) is not None:
        home = credentials.clean_codex_home("# model provider: the trial's gateway, set on the command line\n")
        try:
            gw = _gateway(ref, env, GATEWAY_PROTOCOLS["codex"])
        except BaseException:
            credentials.remove_trial_home(home)
            raise
        env["ROBOUSE_GATEWAY_KEY"] = gw.key
        env["ROBOUSE_GATEWAY_URL"] = gw.url  # also lets the macOS sandbox allow this local port
        env["CODEX_HOME"] = home
        cfg = [
            "-c",
            'model_providers.robouse.name="Robo Use gateway"',
            "-c",
            f'model_providers.robouse.base_url="{gw.url}/v1"',
            "-c",
            'model_providers.robouse.env_key="ROBOUSE_GATEWAY_KEY"',
            "-c",
            'model_providers.robouse.wire_api="responses"',
            "-c",
            'model_provider="robouse"',
        ]
        # the provider's own Responses endpoint, the request passed through unchanged (reasoning effort and earlier
        # reasoning kept); the gateway moves any image out of a tool result into the next user message
        launch = _gateway_launch(gw, ref, _codex_cmd(prompt, gw.model, workspace, cfg, prefix), env)
        launch.stop = _removing(home, launch.stop)
        return launch
    m = (model or "gpt-6-astra").removeprefix("openai/")
    key = os.environ.get("OPENAI_API_KEY", "")
    env["CODEX_HOME"] = home = credentials.clean_codex_home(api_key=key)
    if key:
        env["CODEX_API_KEY"] = key
    return Launch(_codex_cmd(prompt, m, workspace, prefix=prefix), env, stop=_removing(home), notes={"model": m})


def _removing(home: str, stop: Callable[[], None] | None = None) -> Callable[[], None]:
    """`stop`, then the removal of the trial's own Codex home (`remove_trial_home` leaves a pool home alone)."""

    def run() -> None:
        try:
            if stop is not None:
                stop()
        finally:
            credentials.remove_trial_home(home)

    return run


def mini_exe() -> str | None:
    """mini-swe-agent's `mini`: on PATH, else next to this Python (`pip install mini-swe-agent` into Robo Use's own
    environment, not activated), else in ~/.local/bin (a `uv tool` or `pipx` install). None when it is not installed:
    mini-swe-agent is not a dependency of robouse."""
    import os
    import sys

    here = os.pathsep.join([str(Path(sys.executable).parent), str(Path.home() / ".local" / "bin")])
    return shutil.which("mini") or shutil.which("mini", path=here)


def _mini_swe_agent(model, prompt, workspace, task, env) -> Launch:
    from . import models

    ref = models.resolve("mini-swe-agent", model or models.DEFAULT_MODELS["mini-swe-agent"])
    exe = mini_exe()
    if exe is None:  # before the gateway starts: nothing to stop
        raise RuntimeError(
            "mini-swe-agent is not installed: no `mini` on PATH, next to this Python or in ~/.local/bin "
            "(pip install mini-swe-agent)"
        )
    gw = _gateway(ref, env, GATEWAY_PROTOCOLS["mini-swe-agent"])
    env.update(
        {
            "OPENAI_API_KEY": gw.key,
            "OPENAI_API_BASE": f"{gw.url}/v1",
            "MSWEA_CONFIGURED": "true",
            "MSWEA_COST_TRACKING": "ignore_errors",
            # its global .env (which may hold provider keys) is per trial: the user's is never loaded
            "MSWEA_GLOBAL_CONFIG_DIR": str(workspace / ".robouse" / "mini-config"),
        }
    )
    cmd = [
        exe,
        "-y",
        "--exit-immediately",
        "-l",
        "0",
        "-m",
        f"openai/{gw.model}",
        "-t",
        PROMPT_PREFIX + prompt,
        "-o",
        str(workspace / ".robouse" / "mini_traj.json"),
    ]
    return _gateway_launch(gw, ref, cmd, env)


def _task_language(task) -> str:
    """The instruction a VLA gets: the source benchmark's own language instruction, else the task description."""
    return str(
        task.metadata.get("language_instruction")
        or task.meta.get("real", {}).get("goal_text")
        or task.spec.get("real", {}).get("goal_text")
        or task.meta.get("task", {}).get("description", "")
    )


def _molmoact2(model, prompt, workspace, task, env) -> Launch:
    url = config.env("ROBOUSE_MOLMOACT2_URL")
    if not url:
        raise RuntimeError("molmoact2 needs ROBOUSE_MOLMOACT2_URL (the URL of a MolmoAct2 policy server)")
    client = workspace / ".robouse" / "molmoact2_client.py"
    client.write_text((Path(__file__).parent / "molmoact2" / "client.py").read_text())
    if config.env("ROBOUSE_MOLMOACT2_TOKEN"):  # the runner passes no credential on its own
        env["ROBOUSE_MOLMOACT2_TOKEN"] = config.env("ROBOUSE_MOLMOACT2_TOKEN")
    env["ROBOUSE_TASK_LANGUAGE"] = _task_language(task)
    m = model or "allenai/MolmoAct2-LIBERO-LeRobot"
    return Launch(["python3", str(client)], env, notes={"model": m, "server": url})


def _vla(model, prompt, workspace, task, env) -> Launch:
    from . import vla

    url = config.env("ROBOUSE_VLA_URL")
    over_file = config.env("ROBOUSE_VLA_POLICY_CONFIG")
    cfg = vla.resolve(model or "openpi/pi05_libero", json.loads(Path(over_file).read_text()) if over_file else {})
    if not url and not cfg.get("url"):
        raise RuntimeError("vla needs ROBOUSE_VLA_URL (the policy server, e.g. ws://gpu-box:8000 for openpi)")
    client = workspace / ".robouse" / "vla_client.py"
    client.write_text(vla.CLIENT.read_text())
    env["ROBOUSE_VLA_CONFIG"] = json.dumps(cfg)
    env["ROBOUSE_VLA_URL"] = url or cfg["url"]
    if config.env("ROBOUSE_VLA_TOKEN"):
        env["ROBOUSE_VLA_TOKEN"] = config.env("ROBOUSE_VLA_TOKEN")
    env["ROBOUSE_TASK_LANGUAGE"] = _task_language(task)
    return Launch(
        [config.env("ROBOUSE_VLA_PYTHON", "python3"), str(client)],
        env,
        notes={"model": cfg["preset"], "wire": cfg["wire"], "server": env["ROBOUSE_VLA_URL"], "provider": "vla"},
    )


def _dream(model, prompt, workspace, task, env) -> Launch:
    from . import dream

    return dream.build(model, prompt, workspace, task, env)


def _jev(model, prompt, workspace, task, env) -> Launch:
    from . import jev

    return jev.build(model, prompt, workspace, task, env)


def _dimcode(model, prompt, workspace, task, env) -> Launch:
    from . import dimcode

    return dimcode.build(model, prompt, workspace, task, env)


def _gemini_cli(model, prompt, workspace, task, env) -> Launch:
    from . import gemini_cli

    return gemini_cli.build(model, prompt, workspace, task, env)


def _kinex(model, prompt, workspace, task, env) -> Launch:
    from . import kinex

    return kinex.build(model, prompt, workspace, task, env)


def _show_harness(model, prompt, workspace, task, env) -> Launch:
    from . import show_harness

    return show_harness.build(model, prompt, workspace, task, env)


def _aspire(model, prompt, workspace, task, env) -> Launch:
    from . import aspire

    return aspire.build("aspire", model, prompt, workspace, task, env)


def _aspire_codex(model, prompt, workspace, task, env) -> Launch:
    from . import aspire

    return aspire.build("aspire-codex", model, prompt, workspace, task, env)


# harnesses whose trial needs more agent time than a task's own limit when --timeout is not given: an ASPIRE campaign
# for one task (practice episodes, a verifier, then Stage 2)
MIN_TIMEOUT_S = {"aspire": 4 * 3600.0, "aspire-codex": 4 * 3600.0}
# harnesses whose scored episode stays locked until their own last phase unlocks it: they practise on other episodes
# first, and their top process (aspire's driver) gets the unlock token on its stdin before it starts the agent
LOCKED_HARNESSES = ("aspire", "aspire-codex")


HARNESSES: dict[str, Builder] = {
    "oracle": _oracle,
    "noop": _noop,
    "claude-code": _claude_code,
    "codex": _codex,
    "gemini-cli": _gemini_cli,
    "mini-swe-agent": _mini_swe_agent,
    "molmoact2": _molmoact2,
    "vla": _vla,
    "dream": _dream,
    "jev": _jev,
    "dimcode": _dimcode,
    "kinex": _kinex,
    "show-harness": _show_harness,
    "aspire": _aspire,
    "aspire-codex": _aspire_codex,
}


def build(harness: str, model: str, prompt: str, workspace: Path, task, base_env: dict) -> Launch:
    """The launch for one trial. Raises KeyError for an unknown harness, ValueError for a legacy name or a missing
    model, and RuntimeError for missing credentials."""
    from . import models

    if why := models.legacy_refusal(harness):  # claude-code-glm etc.: names of recorded trials only
        raise ValueError(why)
    env = dict(base_env)
    fn = HARNESSES.get(harness)
    if fn is None:
        from importlib.metadata import entry_points

        fn = next((ep.load() for ep in entry_points(group="robouse.harnesses") if ep.name == harness), None)
        if fn is None:
            raise KeyError(f"unknown harness {harness!r}; harnesses: {', '.join(HARNESSES)}")
        for k in PRIVATE_ENV:
            env.pop(k, None)
        return fn(harness, model, prompt, workspace, task, env)
    launch = fn(model, prompt, workspace, task, env)
    for k in PRIVATE_ENV:  # never in the agent's environment
        launch.env.pop(k, None)
    return launch
