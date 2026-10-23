# Embodied Playground suite (EP-100's Launch tasks)

Embodied Playground's Launcher tasks on its own MuJoCo package: `tasks/embodied-playground/` (suite `embodied-playground`, backend `embodied_playground`). Two Franka Pandas operate a passive spring launcher to clear targets down a lane, at Embodied Playground's Level 0. The suite has 6 of the 34 Launch tasks of EP-100, each in the benchmark's four conditions, so 24 task folders, `ep-launch-<case>-c<condition>` (`ep-launch-a007-c1` is `marble/dual-panda/A007`, Launch-02, condition 1). Added 2026-10-21.

- Backend: `src/robouse/backends/embodied_playground/`: the bridge (`backend.py`), the worker that runs in the simulator's virtualenv (`worker.py`), the pinned download (`source.py`) and the reference shots (`planner.py`).
- Generator: `python adapters/embodied-playground/generate.py` (needs the setup below). It reads Embodied Playground's task catalog at the pinned commit (`docs/evaluation/tasks.json` and `docs/ep_subsets/tasks.json`: goals, budgets, robots and the four conditions), searches each condition's reference shot in the simulator and writes the folders; `--tasks A007,A008` writes others.

## Source and licence

- Embodied Playground: Feng Chen, Pei Zhou, Lixuan He, Yunchao Yao, Li Sun, Shenghua Gao, Mingyu Ding, Kaifeng Zhang, Kaichen Zhou and Yi Ma (HKU, Sharpa, Tsinghua, Stanford, UNC Chapel Hill, MIT), "Embodied Playground: A Long-Horizon Agentic Robotics Benchmark for Physical, Strategic, and Spatial Reasoning", [arXiv 2610.27039](https://arxiv.org/abs/2610.27039). Project page: [winniechen2002.github.io/Agent-bench-website](https://winniechen2002.github.io/Agent-bench-website/). Code: [Winniechen2002/Embodied-Playground](https://github.com/Winniechen2002/Embodied-Playground).
- Licences (its LICENSING.md): original code Apache-2.0; original documentation and independently authored non-code assets CC BY 4.0; third-party material under its own terms. The Launcher's Panda model is MuJoCo Menagerie's `franka_emika_panda` (Apache-2.0, with its LICENSE and UPSTREAM.json in the package).
- Robo Use includes none of it. `robouse fetch-assets --embodied-playground` downloads the MuJoCo package the Launcher runs on (`source/agentbench/agentbench_mujoco`: its modules, the Panda model and its meshes, its textures) and the release's licence files, 107 files, about 35 MB, from commit `45993d432ae58a9f3dd05dc2ff3c6e16eb39198f` (main on 2026-10-19), and checks each file's SHA-256 (`assets/embodied-playground/provenance.json`; the meshes come from GitHub's LFS host, checked against their LFS object ids). The worker imports the package from there after checking every module's hash.
- The task folders quote each task's goal from Embodied Playground's catalog and carry its conditions' parameters; their reference plans are Robo Use's own. NOTICE has the entry.

## The tasks

| Task | EP-100 | Name (Embodied Playground's) | Type | Split | Reference draw by condition (cm) |
|---|---|---|---|---|---|
| `ep-launch-a007-c1..c4` | Launch-02 (EP-20) | Single-target warm-up | Launch-Aim | Easy | 7, 7, 7, 8 |
| `ep-launch-a008-c1..c4` | Launch-03 | Long-range energy budget | Launch-Aim | Easy | 7, 7, 8, 8 |
| `ep-launch-a010-c1..c4` | Launch-05 | Toppling timber gate | Launch-Aim | Easy | 10, 10, 10, 10 |
| `ep-launch-a044-c1..c4` | Launch-11 | Gravity-driven stone at a low fort | Launch-Causal | Easy | 10, 9, 10, 10 |
| `ep-launch-a055-c1..c4` | Launch-17 | Two-ball relay | Launch-Causal | Hard | 9, 8, 9, 9 |
| `ep-launch-a018-c1..c4` | Launch-21 | Rigid glass village | Launch-Glass | Easy | 10, 10, 10, 10 |

- Scene and physics: Embodied Playground's `FrankaCampaignEnv`, unmodified, in its own virtualenv with its pins (Python 3.11, MuJoCo 3.3.7, numpy 1.26.4, gymnasium 1.2.1): its scene builder, spring launcher, latch, damage, fracture and toppling models, rule checks and success rule. 1 ms physics steps, 20 ms control steps.
- Start: the benchmark's loaded start (the first projectile in the carriage's cup), reset seed 0, and the condition's parameters: spring stiffness 22, 24, 26 or 28 N/m with launcher and projectile offsets of up to 12 mm and four backgrounds (dusk, park, desert with drifting scenery, snow with pulsing scenery), as in Embodied Playground's four-trial protocol (`environment-four-trial-v2`).
- Instruction: the goal string of Embodied Playground's catalog, verbatim, the condition's spring stiffness (public at every level, as its rules say), the action layout, the end conditions and the budget. Like Embodied Playground's own agents, the agent is not told where the robots, the launcher or the targets are.
- Observation (`obs_mode: vision`, Level 0): the robots' joint positions and velocities, the finger positions, the previous action, the step index, the simulated time and the end flags (`terminated`, `truncated`), and the `front_left` camera (640x400, Embodied Playground's view), saved on every `robo observe`. `robo info` gives that camera's 3x4 projection matrix, computed the way Embodied Playground calibrates it (checked: the target projects onto its pixels).
- Action: Embodied Playground's 16 numbers: per arm seven absolute joint targets (rad) and a binary gripper command (+1 open, -1 closed), the power arm (`left`) first. No skills: Level 0 allows the agent's own kinematics and planning, not prebuilt ones.
- Success: Embodied Playground's own rule, checked at every physics step; the episode is scored solved the first time it holds (`success_mode: first`). The environment ends an episode at the first rule or physical violation (an arm penetrating an object by more than 5 mm, a joint above 110% of its speed limit, the slide or the wheels past their limits, an unstable simulation, a protected target hit, targets out of order), after 150 s of simulated time, and once every projectile has been fired and has settled; after that the agent's steps change nothing and it should call `robo done`.
- Budget: 7500 steps (150 s of simulated time) and 600 s of agent wall-clock time, Embodied Playground's Launcher budgets.

## Scoring like the paper

Embodied Playground scores a task as the mean of its four conditions, a suite as the mean of its tasks, and EP-100 as the mean of its five suites, at Pass@1 (one valid attempt per condition) or Pass@2. Each folder here is one condition: run the suite once (`robouse run-many --tasks .../embodied-playground`), average each task's four `-cN` trials, then average the tasks. This gives a score on these 6 Launch tasks at Level 0, not on EP-100's Launch suite (34 tasks); the paper's runs are at Level 3, with privileged observations.

## Reference solutions

Embodied Playground ships no reference solutions, so each condition's is a scripted shot (`planner.py`), found by simulation in the generator and replayed through `robo act` (`python -m robouse.oracle --backend embodied_playground --env oracle/plan.json`):

1. The power arm rises above and behind the carriage, comes down onto the line of the slide with its fingers open, and moves in until the carriage's handle is between its fingertips (inverse kinematics on the Panda model, joints moved no faster than 0.6 rad/s).
2. It closes its fingers, pulls the carriage back along the slide by the shot's draw over 1.6 s, holds for 0.3 s and opens its fingers. The spring sends the carriage forward and the latch releases the projectile.

The aiming arm stays at its start and the wheels are not touched. For each condition the generator tries draws of 4 to 11 cm and keeps the middle of the widest band of successful draws (at least two, so the shot does not hang on one value). The Panda gripper in Embodied Playground's model squeezes with a few newtons, so the handle slips out of the fingers from about 12 cm of draw: longer shots are out of reach of this solution. The stored plan is replayed from a fresh reset before it is written, expanded exactly as the reference solution expands it.

## Left out

Of EP-100's 34 Launch tasks, 6 are here; the others have no reference solution yet, so they could not be shown to be solvable as set up here. An agent may well solve them.

| EP-100 (task) | Why there is no reference solution yet |
|---|---|
| Launch-04 (A009), Launch-12 (A071) | the scripted shot clears them only at the 11 cm edge of the grip in two conditions and never in the other two; they need a faster shot or a higher elevation (the aiming arm's handwheel) |
| Launch-10 (A039), Launch-15 (A029) | no draw from 4 to 11 cm clears the target in any condition (structures topple, the target stays) |
| Launch-18 (A063), Launch-19 (A072), Launch-22 (A025), Launch-23 (A064), Launch-24 (A027), Launch-28 (A030) | no draw from 4 to 11 cm clears the target in condition 1 (the search stops at the first condition without a shot) |
| Launch-01 (A001), Launch-08 (A017), Launch-09 (A004), Launch-13 (A006), Launch-14 (A015), Launch-20 (A073), Launch-26 (A026) | not tried: two targets, which need a second shot and so a reload (picking a projectile up from the floor and seating it in the cup) |
| Launch-06 (A075), Launch-07 (A031), Launch-16 (A034), Launch-25 (A035), Launch-29 (A036), Launch-30 (A047), Launch-32 (A091), Launch-33 (A092), Launch-34 (A093) | not tried: aiming in azimuth with the turret's yaw wheel and brakes, and two or three targets |
| Launch-27 (A028), Launch-31 (A068) | not tried: the required target stands behind a protected one that must not be hit |

EP-100's other suites are not here:

- Tower (21 tasks), Lock (16), Cube (12) and Home's Bookshelf (5) run on Isaac Sim 5.1 and Isaac Lab, which need an NVIDIA RTX GPU (and NVIDIA's EULA); some load the Panda from NVIDIA's asset server at startup. They could run on Robo Use's remote GPU workers (the `gpu` backend) with an Isaac worker for Embodied Playground's environments.
- Home's ManiSkill tasks (12: long-horizon, geometry, dynamics) run on ManiSkill (SAPIEN, one CPU scene) in an environment of their own (NumPy 2), with a 444-file asset archive whose YCB, Google Scanned Objects and RoboCasa/Lightwheel assets keep their own terms, and render with Vulkan. They could run on the CPU with a software Vulkan driver, as Robo Use's `maniskill` suite does; not done yet.

## Setup

```sh
robouse fetch-assets --embodied-playground
uv venv -p 3.11 ~/.cache/robouse/embodied-playground-venv
uv pip install -p ~/.cache/robouse/embodied-playground-venv/bin/python \
  mujoco==3.3.7 gymnasium==1.2.1 numpy==1.26.4 scipy==1.15.3 Pillow==11.3.0
robouse run --task ep-launch-a007-c1 --harness oracle --out runs/ep
```

`ROBOUSE_EMBODIED_PLAYGROUND_PYTHON` points at another interpreter, `ROBOUSE_EMBODIED_PLAYGROUND_SOURCE` at another download folder (denied to agents, like the cache).

## Checks

Validation (2026-10-21, `robouse run-many` on a Linux x86_64 CPU without a GPU; MuJoCo 3.3.7 in the worker): reference solution 24/24, every episode ending `success_reached` after 468 to 557 steps, the step counts of the generator's replay; no-op control 0/24. The setup above, run as written on a clean home folder from a wheel of this branch, downloads the 107 files and runs `ep-launch-a007-c1`'s reference solution to reward 1.0 (475 steps). `tests/test_embodied_playground.py` checks the pinned file list, the download, the plan format and the task folders, and, with the virtualenv and the download, runs every reference solution and no-op control in process and projects the target through the camera matrix onto its pixels.
