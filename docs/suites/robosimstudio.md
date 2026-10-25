# RoboSimStudio CPU tasks

Two scored examples from [RoboSimStudio](https://github.com/robosimstudio/robosimstudio), adapted to the Robouse episode interface: `rss-open-bag` and `rss-hook-band`. Both use the upstream YAM bimanual robot, native absolute Cartesian controls and native physical success predicates. These are fixed example layouts. Different seeds do not produce independent layouts or benchmark trials.

| Task | Upstream example | Success |
|---|---|---|
| `rss-open-bag` | `examples/06_tasks/06_bag_scored.py` | `mouth_opening bag >= 0.03` m |
| `rss-hook-band` | `examples/06_tasks/07_band_scored.py` | band `encircles` both peg spans |

The worker captures the environment that each unmodified scored example builds, without opening its browser studio or an HTTP server. The only override is the episode's 1200-step budget (20 simulated seconds at 60 Hz). Success is checked after each native control step, and Robouse ends at the first successful step, matching the examples' termination on success. The original scene geometry, staging, servos, contact physics and evaluator are retained.

`robo act` takes 16 values: left tool x/y/z, xyzw quaternion, grip, then right tool x/y/z, xyzw quaternion, grip. Positions are absolute world metres; grip is 0 open, 1 closed. Nonzero quaternions are normalized. The native IK and joint servos move the robot; the reference controllers do not assign material poses or attach objects. Each step and repeat counts against the episode budget. There are no prebuilt skills.

Agents see the robot's own tool poses, joints, measured gripper widths, previous action and clock, plus a 480x320 `overview` image from the native CPU tiled renderer. `robo info` reports the camera projection. Material geometry and evaluator metrics are hidden. The reference solution's per-episode token reveals grasp geometry; its movements use the same public action vector and step accounting.

## Setup

Use Python 3.12 in a separate simulator environment: RoboSimStudio's MuJoCo and NumPy pins conflict with Robouse's main simulator environment. [Upstream's CPU installation](https://github.com/robosimstudio/robosimstudio/blob/eb3d46a839bf8d9b8df6e9c3f0205e141f5b3f7f/examples/install.md) supports Linux x86_64. These two tasks also passed locally on macOS arm64; that is not a claim that every upstream scene supports macOS.

```sh
robouse fetch-assets --robosimstudio
RSS_CACHE="${ROBOUSE_CACHE_DIR:-$HOME/.cache/robouse}"
UV_PROJECT_ENVIRONMENT="$RSS_CACHE/robosimstudio-venv" uv sync \
  --project "$RSS_CACHE/robosimstudio" --locked --extra cpu --no-group rtx
robouse run --task rss-open-bag --harness oracle --out runs/rss
```

The download has 539 files, about 65.5 MB: the six upstream packages, robot assets, two scored examples, licence and release files, and the dependency lock. Every download is SHA-256 checked; Python sources are checked again before loading. The pin is commit `eb3d46a839bf8d9b8df6e9c3f0205e141f5b3f7f`, recorded in `assets/robosimstudio/provenance.json`. `tools/assets/pin_robosimstudio.py` rebuilds the manifest from a clean pinned checkout. The source and model files are downloaded at run time and are not bundled.

`ROBOUSE_ROBOSIMSTUDIO_SOURCE` selects a different source folder; `ROBOUSE_ROBOSIMSTUDIO_PYTHON` selects its interpreter. Moved source and virtualenv folders are denied to agents. The worker forces CPU execution, and keeps both bytecode and Warp's compiled kernels in Robouse's private cache. First use compiles CPU kernels and can take a few minutes; later starts use that cache. Set `ROBOUSE_ROBOSIMSTUDIO_QUIET=0` to see startup output.

Code is Apache-2.0, copyright 2026 Kaiyuan Chen. Robot assets and other third-party files retain their MIT, BSD and Apache terms, with licence files beside them and a top-level upstream `NOTICE`. Robouse's own `NOTICE` records the pin and attribution.

## Scope and validation

The CPU path uses MuJoCo for rigid bodies and robot arms, and SuperDex for the bag and band. CPU rod coupling is one-way: material contacts do not apply backreaction to the rigid solver. CPU and GPU material behavior differ. These tasks test control in this CPU simulation, not real-world success or equivalence with GPU results.

RoboSimStudio's brush, tape, paper, granular and water paths still need a GPU. Its other CPU scenes are not included here because they do not yet have Robouse reference controls and no-op checks. The research benchmark's task suites are not released. The [paper](https://arxiv.org/abs/2610.18835) reports a real-to-sim-to-real pilot on one sponge-wiping task, assessed mainly qualitatively; these two example tasks do not reproduce that study or automate video reconstruction.

Validation on 2026-10-25, macOS arm64 CPU, Python 3.12.15, Newton 1.7.0, MuJoCo 3.15.0 and SuperDex 1.0.0: normal `robouse tasks check` runs scored 1 for both reference controllers (594 bag steps, 404 band steps), and 0 for both no-op controls. `tests/test_robosimstudio.py` also checks the download pin and integrity, path safety, moved-folder sandbox rules, hidden observations, action validation, reset and camera calibration, and, when the worker is available, the native reference controls and full-budget hold controls.

Both 1200-step hold controls also scored 0. From a clean wheel install, downloading every pinned file and running the setup above produced:

```json
{
  "trial": "rss-open-bag__oracle__07b2fd",
  "reward": 1.0,
  "outcome": "success_reached",
  "steps": 594,
  "wall_s": 141.2,
  "exception": null
}
```

Regenerate the task folders with `python adapters/robosimstudio/generate.py`. To repeat the native checks from a checkout after the setup above, run `robouse tasks check tasks/robosimstudio/rss-open-bag` and `robouse tasks check tasks/robosimstudio/rss-hook-band`.
