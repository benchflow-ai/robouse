"""Python commands for clients copied into an agent's workspace."""

from __future__ import annotations

import sys
from pathlib import Path


def stdlib_python() -> list[str]:
    """The runner's base Python, with no site-packages, user site or PYTHON* settings.

    These clients need only the standard library. The base interpreter also works when the runner's virtualenv
    lives in a denied package cache (uvx); resolving its path avoids following a virtualenv symlink through that
    cache. Choosing it explicitly avoids macOS's /usr/bin/python3 launcher, whose output can disappear in Seatbelt.
    """
    executable = getattr(sys, "_base_executable", None) or sys.executable
    return [str(Path(executable).resolve()), "-I", "-S"]
