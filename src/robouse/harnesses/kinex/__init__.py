"""The `kinex` harness: Kinex (github.com/stacx-lab/kinex, Apache-2.0), a robotics coding agent on the Pi SDK, headless
through `kinex run --yolo`, with the trial's robot connected as Kinex devices.

Kinex reaches a simulator through RoboEnv: `roboenv launch` serves the robot's devices over loopback HTTP and
`roboenv setup` writes their profiles and drivers into the workspace's `.kinex/`. Here bridge.py does both for the
episode: it runs inside the agent's sandbox as a client of the episode socket, writes `.kinex/` when it starts (from
`robo info` and the first observation), serves the devices on ROBOENV_ENDPOINT while Kinex runs, and turns each device
call into `robo` requests. The episode server keeps the step budget, the recording and the verdict, and the devices
show only what `robo` shows. driver.py is the device driver Kinex runs for each device. `robo` stays on PATH: the task
text describes it, and the agent ends the episode with `robo done`.

Isolation: every Kinex and Pi path is per trial, inside the workspace's `.robouse/kinex/` (KINEX_CONFIG_DIR with Pi's
settings and models, KINEX_DATA_DIR with its sessions, HOME and the XDG folders), so no user settings, credentials,
sessions, extensions, skills or MCP servers load. Kinex's bundled web search (pi-web-search) is turned off; Pi's network
activity other than model requests is off (PI_OFFLINE). The model is a provider-prefixed id (default glm/glm-5.3),
always reached through the trial's model gateway over Anthropic Messages (gateway.py): Pi gets the gateway's URL and the
per-trial gateway key from $ROBOUSE_GATEWAY_KEY (no key is written to a file).

Kinex's tools and drivers run in its managed Python (`.kinex/python/.venv`). Each trial's is a link to one shared,
read-only environment with Kinex's runtime packages (ROBOUSE_KINEX_VENV), which the sandbox lets agents read and not
write, so no trial installs packages. The bridge runs on its Python too: the first python3 on PATH may be older than the
3.11 it needs (macOS's own is 3.9). Kinex's own install, which every Kinex trial runs (`install`: the node_modules folder
of an npm install, with Kinex's packages and the Python helpers its tools and drivers import), is read-only to the agent
as well (`Launch.read_only`). Kinex's Python processes keep their bytecode in the trial's workspace (PYTHONPYCACHEPREFIX)
and ignore any in __pycache__ folders next to the sources, so no trial leaves code there that a later trial runs.

The trajectory is Pi's session file, copied to agent/pi_session.jsonl and converted by runner/atif.py.

  ROBOUSE_KINEX        the Kinex launcher (default: `kinex` on PATH): the installer's ~/.local/bin/kinex, or bin/kinex.mjs
                       of an npm install
  ROBOUSE_KINEX_NODE   Node 22.19 or newer for a bin/kinex.mjs launcher (default: `node` on PATH)
  ROBOUSE_KINEX_VENV   the Python environment Kinex's tools and drivers run in (default <cache>/kinex-venv)
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
from pathlib import Path
from typing import Any

from ... import config

BRIDGE = Path(__file__).with_name("bridge.py")
DRIVER = Path(__file__).with_name("driver.py")
VENV = "kinex-venv"  # under robouse's cache; listed in runner/sandbox.py CACHE_PROGRAMS (readable, never writable)
# Kinex's own runtime dependencies (packages/core/src/python/project.txt in Kinex 1.0.0), as the setup docs install them
RUNTIME_PACKAGES = ("numpy", "scipy", "Pillow", "PyYAML", "opencv-python-headless>=4.7,<5")
PROMPT_PREFIX = (
    "You are controlling a simulated robot. Read the task below, then solve it. The task text describes the `robo` "
    "command; in this session the same robot is also connected to Kinex as devices, served from the same episode: each "
    "device call becomes `robo` requests with the same step budget. `world` is the episode's clock: every simulated step "
    "counts against the budget, and the robot moves only while time passes on `world` (wait on it; `servo` waits for "
    "you). On an arm task, `arm` holds the hand's position as three prismatic joints x, y and z, in metres in the world "
    "frame, and `gripper` takes -1 (open) to +1 (closed). The camera devices return the task's camera images. Use the "
    "Kinex devices and tools, `robo` in your shell, or both; they drive the same robot. Keep going until the task is "
    "done, then run `robo done` once in your shell. Do not stop to ask questions; there is no human to answer.\n\n"
)


def setup_hint(path: Path) -> str:
    """The commands that create Kinex's Python environment at `path`."""
    packages = " ".join(f"'{p}'" for p in RUNTIME_PACKAGES)
    return f"uv venv --python 3.12 {path} && uv pip install --python {path}/bin/python {packages}"


def venv() -> Path:
    """The shared Python environment of Kinex's runtime: ROBOUSE_KINEX_VENV, else <cache>/kinex-venv."""
    return Path(config.env("ROBOUSE_KINEX_VENV") or config.cache_dir() / VENV).expanduser()


def launcher() -> list[str]:
    """The command that starts Kinex. A JavaScript entry point (bin/kinex.mjs) runs with ROBOUSE_KINEX_NODE or `node`;
    the installer's launcher, a shell script, runs as it is."""
    exe = config.env("ROBOUSE_KINEX") or shutil.which("kinex")
    if not exe:
        raise RuntimeError(
            "Kinex is not installed: install Kinex 1.0.0 (Node 22.19 or newer) and put `kinex` on PATH, or set "
            "ROBOUSE_KINEX to its launcher"
        )
    real = os.path.realpath(exe)
    if real.endswith((".mjs", ".js", ".cjs")):
        return [config.env("ROBOUSE_KINEX_NODE") or shutil.which("node") or "node", real]
    return [real]


def install(exe: list[str]) -> Path | None:
    """The Kinex install every Kinex trial runs from: the node_modules folder that holds the launcher (`launcher()`'s
    resolved bin/kinex.mjs of an npm install), with Kinex's own packages, the Python helpers its tools and drivers
    import (@kinex/core's assets/python) and its dependencies. None for a launcher outside a node_modules folder."""
    return next((p for p in Path(exe[-1]).parents if p.name == "node_modules"), None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def settings(model: str) -> dict:
    """Pi's agent settings for the trial. The bundled pi-web-search is configured as an npm package that loads nothing,
    which keeps Kinex from loading its bundled copy; with PI_OFFLINE set, Pi never installs it either."""
    return {
        "defaultProvider": "robouse",
        "defaultModel": model,
        "defaultThinkingLevel": "medium",
        "quietStartup": True,
        "enableInstallTelemetry": False,
        "enableAnalytics": False,
        "packages": [{"source": "npm:pi-web-search", "extensions": [], "skills": [], "prompts": [], "themes": []}],
    }


def models_json(gw: Any, ref: Any, images: bool) -> dict:
    """Pi's models.json: one provider, the trial's model gateway, keyed from $ROBOUSE_GATEWAY_KEY."""
    return {
        "providers": {
            "robouse": {
                "baseUrl": gw.url,
                "api": "anthropic-messages",
                "apiKey": "$ROBOUSE_GATEWAY_KEY",
                "authHeader": True,
                "models": [
                    {
                        "id": gw.model,
                        "name": ref.id,
                        "reasoning": True,
                        "input": ["text", "image"] if images else ["text"],
                        "contextWindow": 200000,
                        "maxTokens": 32000,
                    }
                ],
            }
        }
    }


def build(model: str, prompt: str, workspace: Path, task: Any, env: dict) -> Any:
    from .. import GATEWAY_PROTOCOLS, _gateway, _gateway_launch, models

    ref = models.resolve("kinex", model or models.DEFAULT_MODELS["kinex"])
    exe = launcher()
    py_env = venv()
    if not (py_env / "bin" / "python3").exists():
        raise RuntimeError(f"Kinex's Python environment is missing ({py_env}); create it once: {setup_hint(py_env)}")
    images = env.get("_ROBOUSE_IMAGE_INPUT", "1") == "1"  # read before _gateway removes the private variables
    gw = _gateway(ref, env, GATEWAY_PROTOCOLS["kinex"])

    root = workspace / ".robouse" / "kinex"
    home, conf, data, state, cache = (root / d for d in ("home", "config", "data", "state", "cache"))
    for d in (root, home, conf / "agent", data, state, cache):
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (conf / "agent" / "settings.json").write_text(json.dumps(settings(gw.model), indent=2))
    (conf / "agent" / "models.json").write_text(json.dumps(models_json(gw, ref, images), indent=2))
    # Kinex's managed Python: a link to the shared environment, so Kinex finds an interpreter and syncs nothing
    kinex_py = workspace / ".kinex" / "python"
    kinex_py.mkdir(parents=True, exist_ok=True)
    (kinex_py / ".venv").symlink_to(py_env, target_is_directory=True)
    bin_dir = workspace / ".robouse" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "roboenv_bridge.py").write_text(BRIDGE.read_text())
    (bin_dir / "kinex_driver.py").write_text(DRIVER.read_text())

    env.update(
        {
            "KINEX_CONFIG_DIR": str(conf),
            "KINEX_DATA_DIR": str(data),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(state),
            "XDG_CACHE_HOME": str(cache),
            "PI_OFFLINE": "1",
            "PI_SKIP_VERSION_CHECK": "1",
            "PI_TELEMETRY": "0",
            # Kinex passes its environment on to its Python tools and drivers: their bytecode stays in this trial, and
            # __pycache__ folders in the shared install are not read
            "PYTHONPYCACHEPREFIX": str(root / "pycache"),
            "ROBOUSE_GATEWAY_KEY": gw.key,
            "ROBOUSE_GATEWAY_URL": gw.url,  # also lets the macOS sandbox allow this local port
            "ROBOENV_ENDPOINT": f"http://127.0.0.1:{_free_port()}",  # the bridge's port, allowed the same way
            "ROBOENV_SESSION": "robouse-" + secrets.token_hex(16),
        }
    )
    cmd = [
        str(py_env / "bin" / "python3"),
        str(bin_dir / "roboenv_bridge.py"),
        "--kinex-dir",
        str(workspace / ".kinex"),
        "--run",
        *exe,
        "run",
        "--yolo",
        "--mode",
        "json",
        "--provider",
        "robouse",
        "--model",
        gw.model,
        "--",
        PROMPT_PREFIX + prompt,
    ]
    launch = _gateway_launch(gw, ref, cmd, env)
    launch.notes["collect"] = [["kinex/data/agent/sessions", "agent/pi_session.jsonl"]]
    launch.read_only = [p] if (p := install(exe)) else []
    return launch
