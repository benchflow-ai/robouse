# Suites

A suite is a folder of tasks in the package: a subfolder of `robouse tasks --path`. Run one with `robouse run-many --tasks "$(robouse tasks --path)/SUITE"`.

```gallery
img/suites/metaworld.webp | `metaworld`
img/suites/gymrobotics.webp | `gymrobotics`
img/suites/libero.webp | `libero`
img/suites/robosuite.webp | `robosuite`
img/suites/libero-style.webp | `libero-style`
img/suites/arc-style.webp | `arc-style`
img/suites/robo-use-families.webp | `robo-use-families`
img/suites/safety.webp | `safety`
img/suites/vision.webp | `vision` (a camera image the agent gets)
img/suites/hard.webp | `hard`
img/suites/menagerie.webp | `menagerie`
img/suites/roboharm.webp | `roboharm`
img/suites/drone.webp | `drone`
img/suites/dexjoco.webp | `dexjoco`
img/suites/quadruped.webp | `quadruped`
img/suites/humanoid.webp | `humanoid`
img/suites/mobile-manip.webp | `mobile-manip`
img/suites/dexhand.webp | `dexhand`
img/suites/crazyflie.webp | `crazyflie`
img/suites/driving.webp | `driving`
img/suites/libero-90.webp | `libero-90`
img/suites/kitchen.webp | `kitchen`
img/suites/adroit.webp | `adroit`
img/suites/dmcontrol.webp | `dmcontrol`
img/suites/myosuite.webp | `myosuite`
img/suites/humanoidbench.webp | `humanoidbench`
img/suites/maniskill.webp | `maniskill`
img/suites/robocasa.webp | `robocasa`
img/suites/yam.webp | `yam`
img/suites/one-demo.webp | `one-demo` (a demonstration frame)
```

<!-- suites-table -->
robouse 0.6.1 bundles 790 tasks in 34 suites. "Needs" is what a suite needs beyond `pip install 'robouse[sim]'`, if anything. The last two columns count the tasks that scored 1 with the reference solution and with the no-op control.

| Suite | Tasks | Needs | Reference solution | No-op control |
|---|---|---|---|---|
| `adroit`<br>Adroit hand | 12 | `[gymrobotics]` | 12/12 | 0/12 |
| `arc-style`<br>ARC-style rules on a table | 11 |  | 11/11 | 0/11 |
| `composed`<br>Composed from components | 48 | `robouse fetch-assets --all` | 48/48 | 0/48 |
| `crazyflie`<br>Crazyflie 2, one or three | 7 | `robouse fetch-assets --all` | 7/7 | 0/7 |
| `cubepick`<br>Cube pick-and-reach | 5 |  | 5/5 | 0/5 |
| `dexhand`<br>Shadow Hand, LEAP Hand | 7 | `robouse fetch-assets --all` | 7/7 | 0/7 |
| `dexjoco`<br>DexJoCo: Allegro hand tool use | 14 | own virtualenv (below) | 14/14 | 0/14 |
| `dmcontrol`<br>dm_control: Control Suite, Jaco arm | 17 | own virtualenv (below) | 17/17 | 0/17 |
| `driving`<br>MetaDrive car in traffic | 7 | own virtualenv (below) | 7/7 | 0/7 |
| `drone`<br>Skydio X2 over a town | 10 | `robouse fetch-assets` | 10/10 | 0/10 |
| `gymrobotics`<br>Gymnasium-Robotics: Fetch, PointMaze | 12 | `[gymrobotics]` | 12/12 | 0/12 |
| `hard`<br>Low-level control, uncalibrated cameras | 25 |  | 25/25 | 0/25 |
| `humanoid`<br>Unitree G1 and H1, Apollo, Booster T1 | 9 | `robouse fetch-assets --all` | 9/9 | 0/9 |
| `humanoidbench`<br>HumanoidBench: H1 with two hands | 7 | [the hub](run-a-suite.md#a-dataset) only | 7/7 | 0/7 |
| `kitchen`<br>Franka Kitchen | 10 | `[gymrobotics]` | 10/10 | 0/10 |
| `libero`<br>LIBERO: Spatial, Object, Goal, Long | 40 | [LIBERO setup](#libero) | 40/40 | 0/40 |
| `libero-90`<br>LIBERO-90 | 90 | [LIBERO setup](#libero) | 90/90 | 0/90 |
| `libero-pro`<br>LIBERO-PRO: 73 of ASPIRE's 80 swap and task pairs | 73 | [LIBERO setup](#libero) | 73/73 | 0/73 |
| `libero-style`<br>LIBERO-like tabletop scenes | 12 |  | 12/12 | 0/12 |
| `maniskill`<br>ManiSkill3 on the CPU | 12 | [the hub](run-a-suite.md#a-dataset) only | 12/12 | 0/12 |
| `menagerie`<br>Dual Franka Panda, ALOHA 2 | 15 | `robouse fetch-assets` | 15/15 | 0/15 |
| `metaworld`<br>Meta-World MT50 | 50 | `[metaworld]` | 50/50 | 0/50 |
| `mobile-manip`<br>Stretch 3, TIAGo, Google Robot | 10 | `robouse fetch-assets --all` | 10/10 | 0/10 |
| `myosuite`<br>MyoSuite: muscle-driven arm and hand | 15 | own virtualenv (below) | 15/15 | 0/15 |
| `nav`<br>Object-goal navigation in homes | 40 |  | 40/40 | 0/40 |
| `one-demo`<br>One demonstration, then another object | 16 |  | 16/16 | 0/16 |
| `quadruped`<br>Unitree Go2 and Go1, Spot, ANYmal C | 11 | `robouse fetch-assets --all` | 11/11 | 0/11 |
| `robo-use-families`<br>Robo Use task families | 8 |  | 8/8 | 0/8 |
| `robocasa`<br>RoboCasa kitchens | 24 | [the hub](run-a-suite.md#a-dataset) only | 24/24 | 0/24 |
| `roboharm`<br>10 harm scenarios, 4 configurations | 80 | `robouse fetch-assets` | 80/80 | 0/80 |
| `robosuite`<br>robosuite 1.5, five arms | 21 | `[robosuite]` | 21/21 | 0/21 |
| `safety`<br>Harmful requests and benign twins | 8 |  | 8/8 | 0/8 |
| `vision`<br>Camera images, no coordinates | 55 | `[metaworld]` | 55/55 | 0/55 |
| `yam`<br>Dual YAM: Dream Labs' station scene | 9 | own virtualenv (below) | 9/9 | 0/9 |
<!-- /suites-table -->

`robouse fetch-assets` downloads the MuJoCo Menagerie robot models for `menagerie`, `roboharm`, `drone` and `chemlab` (its Franka Hand); `robouse fetch-assets --all` adds every robot the other suites and composed tasks use (about 390 MB). Each file is checked by SHA-256. Results of models on these suites: [Runs](https://robouse.ai/runs/).

## LIBERO

LIBERO pins robosuite 1.4, so it needs a virtual environment of its own:

```sh
python3.12 -m venv .venv-libero && source .venv-libero/bin/activate
pip install 'robouse[sim]' 'mujoco==3.3.0'
pip install --no-deps hf-libero==0.1.4 robosuite==1.4.0 bddl==1.0.1
pip install numba scipy opencv-python-headless termcolor easydict \
  huggingface_hub h5py fsspec tqdm matplotlib future cloudpickle gymnasium
pip install torch --index-url https://download.pytorch.org/whl/cpu
robouse run --task libero-object-0 --harness oracle --out runs/try
```

The first episode downloads LIBERO's scene assets (about 400 MB) into `~/.cache/libero/assets`. In a new environment the first start can take more than two minutes, and `robouse run` may stop with `TimeoutError: episode server did not start`; run it again.

The `libero-pro` suite runs in the same environment. Its tasks carry LIBERO-PRO's scene files; a seed other than a task's own (1) downloads LIBERO-PRO's init file for that task (a few kB) at first use.

## Suites with their own virtualenv

These simulators pin versions that conflict with the main environment. The episode server runs each in a virtualenv of its own, started as a subprocess; set the environment variable to use another interpreter.

```sh
# dexjoco (ROBOUSE_DEXJOCO_PYTHON); also pip install 'robouse[dexjoco]'
git init -q ~/.cache/robouse/dexjoco
git -C ~/.cache/robouse/dexjoco fetch --depth 1 \
  https://github.com/brave-eai/dexjoco.git \
  8d23b0fab23b17a58c4b55f3942e17013aaf8267
git -C ~/.cache/robouse/dexjoco checkout -q FETCH_HEAD
uv venv -p 3.11 ~/.cache/robouse/dexjoco-venv
VIRTUAL_ENV=~/.cache/robouse/dexjoco-venv uv pip install \
  -e ~/.cache/robouse/dexjoco/dexjoco \
  "numcodecs<0.16"

# driving (ROBOUSE_METADRIVE_PYTHON)
uv venv -p 3.11 ~/.cache/robouse/metadrive-venv
uv pip install \
  -p ~/.cache/robouse/metadrive-venv/bin/python \
  metadrive-simulator==0.4.3 gymnasium==1.3.0

# dmcontrol (ROBOUSE_DMCONTROL_PYTHON)
uv venv -p 3.12 ~/.cache/robouse/dmcontrol-venv
uv pip install \
  -p ~/.cache/robouse/dmcontrol-venv/bin/python \
  dm-control==1.0.47 mujoco==3.14.0

# myosuite (ROBOUSE_MYOSUITE_PYTHON)
uv venv -p 3.11 ~/.cache/robouse/myosuite-venv
uv pip install \
  -p ~/.cache/robouse/myosuite-venv/bin/python \
  myosuite==2.12.2 scipy==1.16.2

# yam (ROBOUSE_YAM_PYTHON): Dream Labs' scene, from their wheel, without its other dependencies
uv venv -p 3.12 ~/.cache/robouse/yam-venv
uv pip install \
  -p ~/.cache/robouse/yam-venv/bin/python \
  mujoco==3.16.0 numpy pillow
uv pip install \
  -p ~/.cache/robouse/yam-venv/bin/python \
  --no-deps dreamlabs==1.0.0
```

`humanoidbench`, `maniskill` and `robocasa` run from the hub, with `bench eval run -d`.

## Robot models

The Menagerie-based suites use MuJoCo Menagerie commit `8161bba2`; the models are downloaded, not bundled.

| Robot | Licence | Suite |
|---|---|---|
| Unitree Go2, Go1, G1, H1 | BSD-3-Clause | quadruped, humanoid |
| Boston Dynamics Spot, ANYbotics ANYmal C | BSD-3-Clause | quadruped |
| Apptronik Apollo, Booster T1 | Apache-2.0 | humanoid |
| Hello Robot Stretch 3, PAL TIAGo, Google Robot | Apache-2.0 | mobile-manip |
| Shadow Hand E3M5 | Apache-2.0 | dexhand |
| LEAP Hand, Bitcraze Crazyflie 2 | MIT | dexhand, crazyflie |

The driving suite uses MetaDrive 0.4.3 (Apache-2.0).

## Not in the package

These suites run their simulators in environments built from the upstream projects' own pinned stacks (RLE-Bench's robosuite and RoboCasa commits; CaP-X's robosuite forks, LIBERO-PRO and PyRoKi), so they are not in the package: they run in those simulator images.

<!-- hub-only-table -->
| Suite | Tasks | Reference solution | No-op control |
|---|---|---|---|
| `rle-bench`<br>RLE-Bench family 03, tabletop reasoning: tower, cantilever, balance, hidden centre of mass | 6 | 6/6 | 0/6 |
| `capx`<br>CaP-X's robosuite tasks, code as policy with CaP-X's privileged API (simulator object poses, no perception) | 35 | 35/35 | 0/35 |
| `capx-libero`<br>CaP-X on LIBERO-PRO's object-swap tasks, code as policy with CaP-X's privileged LIBERO API | 8 | 8/8 | 0/8 |
<!-- /hub-only-table -->

`chemlab` is not in the package either: it runs on MuJoCo in the main environment, but the instrument models, contracts and data it downloads may not be used commercially ([Licences](#licences)). It runs from a checkout of the repository.

<!-- checkout-only-table -->
| Suite | Tasks | Needs | Reference solution | No-op control |
|---|---|---|---|---|
| `chemlab`<br>ChemLab-Assets: fume hood, balance, hotplate, oven, moisture analyzer, shaker | 7 | `robouse fetch-assets --chemlab` (CC BY-NC 4.0) | 7/7 | 0/7 |
<!-- /checkout-only-table -->

```sh
git clone https://github.com/benchflow-ai/robouse.git && cd robouse
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[sim]'
robouse fetch-assets --chemlab
robouse run --task tasks/chemlab/chemlab-fume-hood-sash --harness oracle --out runs/chemlab
```

`robouse fetch-assets --chemlab` states the licence, then downloads the 493 files the tasks use (about 11 MB: each instrument's URDF, meshes and contract, and its behaviour runtime with its data) from a pinned revision of ChemLab-Assets on Hugging Face into `~/.cache/robouse/chemlab`, checking each file's SHA-256.

## Licences

Robo Use is licensed under Apache 2.0, and the [NOTICE](https://github.com/benchflow-ai/robouse/blob/main/NOTICE) file lists the third-party code, data and assets in the package, each with its license: MIT for the vendored CaP-X, PyRoKi and RLE-Bench code, the LIBERO instructions, LIBERO-PRO's scene files and the DexJoCo demonstrations, and CC BY 4.0 for the Adroit demonstrations from D4RL. Robot models and assets downloaded at run time keep their own licenses (the robot models table above).

Some suites need software or data with stricter terms, which Robo Use does not include:

- `robodojo` (not in the package): cuRobo (non-commercial research license) and NVIDIA Isaac Sim (NVIDIA EULA).
- `behavior` (not in the package): the BEHAVIOR Data Bundle (non-commercial academic research only, no redistribution) and NVIDIA Isaac Sim.
- `gpu-isaaclab` (not in the package): NVIDIA Isaac Sim.
- `chemlab` (not in the package): ChemLab-Assets' instrument models, contracts and data (CC BY-NC 4.0), which `robouse fetch-assets --chemlab` downloads together with the release's behaviour runtimes (MIT).

`robouse flora` writes input files for NVIDIA's Flora models and reads their results; the models and NVIDIA's inference scripts are under the NVIDIA License (research or evaluation use only), and Robo Use neither includes nor downloads them ([Annotate trials with Flora](flora.md#licence)).

`robodojo`, `behavior` and `chemlab` cannot be run for commercial purposes, and `robodojo`, `behavior` and `gpu-isaaclab` need you to accept NVIDIA's Isaac Sim EULA. The `llm` and `benchflow` extras install `litellm[proxy]`, which pulls in `litellm-enterprise` under a proprietary license. The `robosuite` extra pulls in GPL and LGPL packages (quadprog, qpsolvers, pynput, python-xlib), and the `sim` extra's `imageio-ffmpeg` wheel bundles a GPL build of ffmpeg; Robo Use does not redistribute them, but an image built with them must carry their licenses.

The suite images on this page are renders of each simulator's own scenes. The RoboCasa image shows RoboCasa's kitchen assets ([robocasa/robocasa](https://github.com/robocasa/robocasa), CC BY 4.0).
