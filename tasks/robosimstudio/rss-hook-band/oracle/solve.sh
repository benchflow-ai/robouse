#!/bin/bash
# Reference solution: native Cartesian poses; privileged grasp geometry. It drives the robot only through the episode socket, like an agent.
set -euo pipefail
python -m robouse.oracle --backend robosimstudio --env hook-band
