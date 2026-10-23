#!/bin/bash
# Reference solution: replay this condition's reference shot (plan.json) through robo act; the generator found it in simulation (a scripted pull-and-release of the launcher).
set -euo pipefail
python -m robouse.oracle --backend embodied_playground --env "$(dirname "$0")/plan.json"
