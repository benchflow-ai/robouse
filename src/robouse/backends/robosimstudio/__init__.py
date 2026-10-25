"""RoboSimStudio's scored material examples, on its unmodified CPU simulator."""

from .backend import RoboSimStudioBackend
from .oracle import oracle_main

__all__ = ["RoboSimStudioBackend", "oracle_main"]
