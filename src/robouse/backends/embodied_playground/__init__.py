"""Embodied Playground: its Launcher tasks on its own MuJoCo package (downloaded at run time), in its own virtualenv."""

from .backend import EmbodiedPlaygroundBackend, oracle_main

__all__ = ["EmbodiedPlaygroundBackend", "oracle_main"]
