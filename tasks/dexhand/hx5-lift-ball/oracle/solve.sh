#!/bin/bash
# Reference solution: scripted with the hand's skills (grasp, move, rotate), reading only the public observation. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend dexhand --env hx5-lift-ball
