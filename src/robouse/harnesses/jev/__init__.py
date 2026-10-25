"""`jev` harness: TypeSafe's Jev, a System One model, drives the robot with typed decisions.

`client.py` (copied into the trial workspace, standard library only) asks Jev a decision profile's questions about each
observation through TypeSafe's System One API and executes the answers through `robo`; its docstring describes the
loop. It runs inside the agent sandbox on the runner's base Python in isolated mode without site-packages (`-I -S`),
which the sandbox lets agents read but not change: on macOS the first `python3` on PATH can be the Command Line Tools'
/usr/bin/python3, whose output to the trial folder is lost under the sandbox. Jev answers typed questions and writes no code, so the harness runs
only tasks it has a profile for: `nav`, Robo Use's nav suite, in the protocol of Dimensional's "Can Jev Nav?" study.
Any other task stops before the client starts, and says why.

Models: typesafe/jev-latest (the default: TypeSafe's alias of its newest stable Jev, jev-1.13.0 on 2026-10-20),
typesafe/jev-preview (jev-1.14.0), or a version such as typesafe/jev-1.13.0. The part after `typesafe/` is the `model`
sent to TypeSafe; each answer names the version that gave it, and the trajectory records it.

Credentials: TYPESAFE_API_KEY, and TYPESAFE_BASE_URL when set (the two variables TypeSafe's own SDK reads). They go to
the client's environment only: the runner removes every TYPESAFE_ variable from the environment of every other agent,
of the episode server and of the verifier.

Cost: TypeSafe bills input tokens only; the prices are in runner/pricing.json, and the client records the cost of each
decision. There is no spend cap (the model gateway enforces it, and Jev does not go through the gateway): a nav episode
is at most one request per 0.5 s of its 120 s budget.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ...lib.python_runtime import stdlib_python

CLIENT = Path(__file__).with_name("client.py")
PREFIX = "typesafe/"
DEFAULT_MODEL = "typesafe/jev-latest"
# TypeSafe's models on 2026-10-20 (docs.typesafe.ai/models): two aliases and the versions they point to. Any other
# name the account may use is sent as given.
MODELS = ("typesafe/jev-latest", "typesafe/jev-preview", "typesafe/jev-1.13.0", "typesafe/jev-1.14.0")
# the backends a decision profile of the client drives, and the profile's name
PROFILES = {"nav": "nav"}


def model_id(model: str) -> str:
    """The provider-prefixed id: typesafe/jev-latest for an empty model, typesafe/<name> for a bare name. Raises
    ValueError for another provider's model: Jev is served by TypeSafe's own API."""
    m = (model or DEFAULT_MODEL).strip()
    if m.startswith(PREFIX):
        return m
    if "/" in m:
        raise ValueError(f"jev runs TypeSafe's models ({', '.join(MODELS)}), not {m!r}")
    return PREFIX + m


def api_model(model: str) -> str:
    """The name sent to TypeSafe's System One API, e.g. jev-latest."""
    return model_id(model)[len(PREFIX) :]


def credentials() -> dict[str, str]:
    """TYPESAFE_API_KEY and, when set, TYPESAFE_BASE_URL, from the environment. Raises RuntimeError without a key, and
    for a key with a space, line break or other character outside printable ASCII: it cannot go in an HTTP header, and
    the client's error for it would quote the key. The message never quotes the key."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("jev needs TYPESAFE_API_KEY (a TypeSafe API key, from console.typesafe.ai)")
    if not all(33 <= ord(c) <= 126 for c in key):  # the client's header_safe
        raise RuntimeError("TYPESAFE_API_KEY has a space, line break or other character no key has; set the key alone")
    out = {"TYPESAFE_API_KEY": key}
    if base := os.environ.get("TYPESAFE_BASE_URL", "").strip():
        out["TYPESAFE_BASE_URL"] = base
    return out


def profile(task: Any) -> str:
    """The client's decision profile for this task. Raises ValueError for a task no profile drives."""
    backend = str((getattr(task, "spec", None) or {}).get("backend") or "")
    if backend not in PROFILES:
        tid = getattr(task, "id", None) or "this task"
        raise ValueError(
            f"jev has decision profiles for the {', '.join(PROFILES)} backend only (the nav suite); {tid} runs on "
            f"the {backend or 'unknown'} backend"
        )
    return PROFILES[backend]


def prices(model: str) -> dict[str, dict]:
    """USD per 1M tokens for the model asked for and the versions TypeSafe lists, from runner/pricing.json (or
    ROBOUSE_PRICING): the client prices each answer by the version that gave it."""
    from ... import config
    from ...runner.cost import PRICING

    table = json.loads(config.path("ROBOUSE_PRICING", PRICING).read_text())
    names = [api_model(model), *(api_model(m) for m in MODELS)]
    return {n: table[n] for n in names if isinstance(table.get(n), dict)}


def build(model: str, prompt: str, workspace: Path, task: Any, env: dict) -> Any:
    from .. import Launch, _task_language

    prof = profile(task)  # before anything is written: a task without a profile stops here
    creds = credentials()
    client = workspace / ".robouse" / "jev_client.py"
    client.write_text(CLIENT.read_text())
    env.update(creds)
    m = api_model(model)
    env["ROBOUSE_JEV_CONFIG"] = json.dumps({"model": m, "profile": prof, "prices": prices(m)})
    env["ROBOUSE_TASK_LANGUAGE"] = _task_language(task)
    server = creds.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai")
    notes = {"model": m, "model_id": model_id(m), "provider": "typesafe", "server": server, "profile": prof}
    return Launch([*stdlib_python(), str(client)], env, notes=notes)
