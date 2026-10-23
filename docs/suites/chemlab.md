# chemlab suite: ChemLab-Assets laboratory instruments

7 tasks on 6 chemistry laboratory instruments from [ChemLab-Assets](https://github.com/mbzuai-nlp/ChemLab-Assets) (Zirui Song, Jiadong Zhang, Jiahao Zhang, Xiaosong Ma, Xiaojun Chang and Xiuying Chen, MBZUAI; release 1.3.0, 2026-10-17). Each task operates one part of an instrument to a target state from the instrument's contract: raise a fume hood's sash to its working stop, close an analytical balance's draft shield until the balance reads STABLE, set a hotplate's temperature and its stirring speed with its knobs, close a drying oven's door so that it heats again, open a moisture analyzer's lid and an incubated shaker's hood. A floating two-finger gripper does the work in MuJoCo, and the instrument's own behaviour runtime from the release runs alongside, driven by the scene.

- Backend: `src/robouse/backends/chemlab/`: `scene.py` (URDF to MJCF, the bench, the gripper), `runtime.py` (the behaviour runtimes), `instruments.py` (the six instruments), `tasks.py` (the seven tasks and their checks), `backend.py`, `oracle.py` (reference solutions), `assets.py` (the download).
- Generator: `python adapters/chemlab/generate.py` writes `tasks/chemlab/<task>/` from `tasks.py`.
- Pinned files: `assets/chemlab/provenance.json`, written by `python tools/assets/pin_chemlab.py`.
- Not in the package and not on the hub: it runs from a checkout (see [Package or hub](#package-or-hub)).

## Source and licence

ChemLab-Assets is 203 commercial instruments, each with a GLB, a URDF with primitive collision proxies, per-part OBJ meshes, Blender sources, a machine-readable contract (components, typed state slots, capabilities with JSON-Schema arguments, readouts, interface points, scene bindings) and a Python behaviour runtime (`describe` / `read` / `invoke` / `poll`, with agent and evaluator views). The code (scripts/, tests/, examples/, tools/) is MIT; the 3D models, contracts and data are CC BY-NC 4.0 (`LICENSE-ASSETS.md`): they may be shared and adapted for non-commercial purposes only, with credit.

Robo Use includes none of it. `robouse fetch-assets --chemlab` downloads the 493 files the tasks use (10.6 MB: each instrument's URDF, OBJ and MTL meshes and contract, the data its runtime reads, the runtimes themselves, and the release's `LICENSE`, `LICENSE-ASSETS.md` and `CITATION.cff`) from revision `4ca4a42dab2ca0a884e449d202e9ad96625d5648` of the Hugging Face dataset [MBZUAI/ChemLab-Assets](https://huggingface.co/datasets/MBZUAI/ChemLab-Assets) into `~/.cache/robouse/chemlab` (`ROBOUSE_CHEMLAB_ASSETS` moves it; the agent sandbox denies it in either place), checking each file's SHA-256 against the manifest. It prints the licence before it downloads. The episode server checks the runtime modules' hashes again before it imports them. The GLB, Blender, texture and preview files are not downloaded.

The task folders hold only Robo Use's own text and the facts the tasks need: instrument and part names, positions, travel and target values taken from the contracts. Renders of the instruments are not committed, since they would be copies of CC BY-NC models in an Apache-2.0 repository; this page has none either.

Running the suite uses the CC BY-NC models, so it is for non-commercial use only. Cite the release (its `CITATION.cff`) in work that uses it.

## Package or hub

The suite is not in the package, and not on the hub yet. It runs from a checkout of the repository, in the main environment (`robouse[sim]`, MuJoCo 3.3.0), after `robouse fetch-assets --chemlab`.

- Not in the package: Robo Use's package carries only suites that anyone can run for any purpose. `robodojo` and `behavior` stay out of the package for the same reason (they need non-commercial software or data). With chemlab in the wheel, `robouse run-many` without `--tasks`, which runs every task in the package, would run CC BY-NC models for users who never chose to. Kept out, running it is a deliberate step: a checkout and the fetch command, which states the licence. The backend, the fetch command and the pinned manifest are in the package, since they contain nothing of ChemLab-Assets; so the tasks also run from a checkout's task folders with an installed `robouse`.
- Not on the hub yet: a hub dataset runs in a simulator image, and that image would have to download the instrument files when it is built, as the HumanoidBench image fetches its walking policy. That fits the licence (each user's machine downloads the files), but it is a separate change to the hub repository, and the hub's datasets are meant for everyone to run, including companies.

```sh
git clone https://github.com/benchflow-ai/robouse.git && cd robouse
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[sim]'
robouse fetch-assets --chemlab
robouse tasks check tasks/chemlab/chemlab-fume-hood-sash
robouse run-many --tasks tasks/chemlab --harness oracle --out runs/chemlab-oracle
```

## Tasks

| Task | Instrument | Part, start | Target (from the contract) | Also checked | Budget | Reference solution |
|---|---|---|---|---|---|---|
| `chemlab-fume-hood-sash` | CHEM-199 Esco Frontier Acela EFA-5UDUVW-9 fume hood | sash, 150 mm open | opening 447 to 467 mm: the 457 mm sash stop (`sash_stop_m`) | the airflow monitor raises no alarm (runtime `monitor.alarm`) | 900 | 278 steps |
| `chemlab-balance-draft-shield` | CHEM-001 METTLER TOLEDO XPR204E analytical balance | right door 80 mm open | all three doors open no more than 1.1 mm (the runtime counts a door as open above 1 % of its 109 mm) | the balance reads STABLE (runtime `balance.status`) | 600 | 234 steps |
| `chemlab-hotplate-temperature` | CHEM-008 IKA Plate RCT digital hotplate stirrer | temperature knob at its stop (0 degC) | set temperature 97.5 to 102.5 degC (runtime `heating.set_k`, from the knob through the contract's binding) | | 600 | 203 steps |
| `chemlab-hotplate-stirring` | the same | speed knob at its stop (0 rpm) | set speed 490 to 510 rpm (runtime `stirring.set_rad_s`) | | 600 | 203 steps |
| `chemlab-drying-oven-door` | CHEM-011 BINDER FD 56 drying oven at 105 degC | door open 100 degrees | door within 0.05 rad of shut: the door switch angle (`door_switch_rad`) | the fan runs again (runtime `fan.running`) | 900 | 450 steps |
| `chemlab-moisture-analyzer-lid` | CHEM-002 METTLER TOLEDO HX204 halogen moisture analyzer | lid closed | lid lifted at least 100 mm of 108.5 mm: the runtime loads a sample only from 100 mm (`sample.configure`) | | 500 | 174 steps |
| `chemlab-shaker-hood` | CHEM-009 IKA KS 4000 i control incubated shaker | hood closed | hood open at least 1.4 rad: the runtime lets the platform be loaded only from 1.4 rad (`load.configure`) | | 900 | 538 steps |

In every task the gripper must also have let go: it touches none of the operated parts when the episode is judged, 10 still steps after `robo done`. The episode server judges from the joint state and, in the tasks that say so, from the runtime's evaluator view; the agent never sees the evaluator view.

How the runtime gives the tasks their meaning:
- Fume hood: the sash's height sets the face velocity, which the Sentinel XL airflow monitor shows and alarms on. The exhaust is the release's building exhaust with the damper fully open (the release's example has it half open, and then the uncalibrated monitor alarms at the stop already), so the monitor reads SAFE at the 457 mm stop (0.38 m/s) and alarms LOW AIRFLOW after 5 s with the sash held well above it (0.26 m/s at 610 mm). Let go above the stop, the sash creeps back down to it at 2 cm/s (the hood's Creep Down feature): the runtime moves the sash and the scene follows, and the alarm clears on the way down.
- Balance: any movement of a door restarts the stability check, and the balance reads STABLE only after the reading has held for 1.5 s with every door shut, so the agent has to close the door and then wait, watching the status.
- Hotplate: the knobs set the runtime's setpoints through the contract's bindings (one turn per 100 K from 0 degC at the stop; one turn per 500 rpm), and the display shows them. Both targets are one turn of the knob.
- Drying oven: the door switch stops the heater and the fan while the door is open more than 0.05 rad; a door left a few degrees ajar keeps the oven cold.
- Moisture analyzer and shaker: the targets are the runtimes' own preconditions for loading a sample.

## The robot

The tabletop suites' floating two-finger gripper (a free body welded to a mocap target, 10 cm maximum gap), with two changes:

- It also turns about its own tool axis ("twist", up to two turns either way), so it can turn knobs: the action is `[dx, dy, dz, dtwist, grip]`, with dtwist at 5 degrees per unit per step. `robo move-to` and `robo grip` work as in the tabletop suites and do not turn it.
- Its palm is as narrow as its fingers (2.4 cm across the closing direction, where the tabletop gripper's is 4.4 cm). The wider palm reached past the fingers and hit the balance's glass door when the fingers pushed the door's grip, and the oven door when they pushed its face.

Its tool axis is fixed per task: straight down (balance, hotplate, oven, moisture analyzer), or horizontally into the instrument (fume hood, shaker), so that its fingers close one above the other around a horizontal handle bar. Steps are 20 ms (10 physics steps of 2 ms), as in the tabletop suites.

`robo observe` reports the tool point, the twist, the gripper opening, which parts the gripper touches, and per operated part its state (opening in metres, angle in degrees or lift in metres), the positions of its handle or knob, and fixed geometry such as hinge axes and knob sizes; `readouts` adds what the instrument displays, from the runtime's agent view (the airflow monitor, the balance's status and reading, the hotplate's display, the oven's display, heating light and fan). The instruction says where the target is, in the instrument's terms; nothing in the observation is the target.

## What was adapted

URDF to MuJoCo, done in memory at every episode start from the downloaded files:
- Links become bodies and joints MuJoCo joints with the URDF's limits; the instrument's root is fixed to the world.
- The primitive collision proxies collide with the gripper only, not with each other: several overlap at rest, and the joint limits already bound the parts. Proxies thinner than 1.5 mm are left out: they are labels, prints, icons, display glass and flat keys laid over larger proxies, and some stand clear of the surface beneath (the FD 56's panel print floats 16 mm in front of the door beyond its panel), where a finger caught on one and pulled the shut door open again.
- Each OBJ is split by material, since MuJoCo would merge an OBJ's materials into one mesh, and coloured with the MTL's diffuse colour. Textures are not used.
- The URDFs have no joint dynamics. Every operated joint gets damping, friction and armature (instruments.py), joints no task operates get more friction so they stay put, push keys get a return spring, and every link is gravity-compensated: the sash is counterweighted, and lids and doors are held by gas springs or their hinges' friction, so a part stays where it is let go.
- The fume hood's sash proxy is one box that leaves out the handle; a 24 mm capsule along the sash's bottom edge adds the handle bar the contract's `sash_handle` port describes.

Scene and runtime:
- The instrument stands on a bench (or base cabinet) in its own frame; cameras `front` and `side` are placed per instrument.
- The runtime is driven as the contract's scene bindings (`extensions["matterix.bindings"]`, `model_bindings`) say: joint position to state slot with the binding's scale and offset, set through the bound capability (`sash.set`, `scene.set_door`, `heating.set_temperature`, `stirring.set_speed`, `door.set`, `lid.set_position`, `hood.set_angle`), whenever the joint moves by more than a small tolerance, and whenever the gripper takes hold of the part or lets go. Values are clamped to the range the capability accepts, since a joint pressed slightly past its limit would otherwise be refused. Where the runtime moves a part on its own (the creeping sash), the runtime leads it until the gripper holds it again or it comes to rest: the backend drives the joint after it with a PD force and sends no calls for that part meanwhile, since setting the lagging joint back each step held the creep to 0.6 mm/s. The runtime's clock advances by each control step.
- Setup per runtime: the release's example plant (22 degC, sea level), power on, and for the FD 56 a 105 degC setpoint; the balance's filter warms up for 10 s before the episode starts, the fume hood's airflow for 30 s and the oven for 120 s.
- The balance's runtime (`basic40_runtime_measure.py`) is loaded as a member of a package made of the release's `scripts/` folder, so its relative import of `balance_runtime.py` resolves there, and it gets an empty scene callback, since the scene leads the doors. Some runtimes import their helpers as `asset_runtime`, which is pointed at the same download.

Start states and parts chosen:
- The sash starts 150 mm open: closed, its handle bar sits 5 mm above the airfoil sill, too close for a finger to pass under it.
- The oven door task closes the door, a push along its arc. Opening it would mean holding its handle while the door turns about a vertical axis, which a parallel gripper with a fixed tool axis does only as long as the handle can turn between its fingers: a round bar along the hinge (the shaker's handle) can, the FD 56's block handle cannot.
- The balance task closes the open door by pushing the back of its grip toward the front, with the closed fingers beside the glass.

## Instruments considered and left out

- Eppendorf 5910 Ri centrifuge (the lid) and Nabertherm L 9 muffle furnace (the door): their URDFs have no proxy for a handle or a lip to lift them by.
- BINDER VD 56 vacuum oven: the 16 mm gap behind its D-shaped door handle is closed above and below by the bar's standoffs, and a finger reaching in from the side brings the palm against the top standoff, so the gripper cannot pull the door open; only closing it would work, as for the FD 56.
- JULABO CORIO CD-200F circulator, Tuttnauer 3870ELV-D autoclave, Genevac miVac and THINKY ARE-310 lids: hinged at the back or the side with square handles or none; a square handle cannot turn between parallel fingers as the lid swings up.
- The fume hood's water and gas valves: the post's collision proxy encloses the valve handles, so the gripper cannot reach them.

## Validation

2026-10-20 on a Linux x86_64 machine with 32 cores (Ubuntu 24.04, Python 3.12, MuJoCo 3.3.0, OSMesa): a fresh clone at commit 54ac912, a fresh virtualenv (`pip install -e '.[sim]'`) and a fresh home folder, so the download started from nothing. `robouse fetch-assets --chemlab` printed the licence and downloaded the 493 files with their hashes checked (`493 file(s) downloaded; ChemLab-Assets 1.3.0 (revision 4ca4a42dab2c)`), and `robouse run --task tasks/chemlab/chemlab-fume-hood-sash --harness oracle --out runs/chemlab` returned reward 1.0 (done, 278 steps, 13.6 s). Then `robouse tasks check` on every task:

| Task | Reference solution | No-op control |
|---|---|---|
| `chemlab-balance-draft-shield` | 1.0 (done, 234 steps) | 0.0 (done) |
| `chemlab-drying-oven-door` | 1.0 (done, 450 steps) | 0.0 (done) |
| `chemlab-fume-hood-sash` | 1.0 (done, 278 steps) | 0.0 (done) |
| `chemlab-hotplate-stirring` | 1.0 (done, 203 steps) | 0.0 (done) |
| `chemlab-hotplate-temperature` | 1.0 (done, 203 steps) | 0.0 (done) |
| `chemlab-moisture-analyzer-lid` | 1.0 (done, 174 steps) | 0.0 (done) |
| `chemlab-shaker-hood` | 1.0 (done, 538 steps) | 0.0 (done) |

Each check ended `valid`. The suites page's table is generated from these runs (`tools/docs/suites_reference.py --keep`, against the built wheel).

`tests/test_chemlab.py` runs every reference solution and no-op control in process when the files are there, and skips those tests without them.

## Runs with a model

2026-10-21: Claude Code 2.1.304 with `claude-opus-5-5` (`--harness claude-code --model claude-opus-5-5`) ran each of the 7 tasks once, with Robo Use 0.6.0 (a clean clone at the release's commit) and ChemLab-Assets 1.3.0 from `robouse fetch-assets --chemlab`, on Linux x86_64 without the sandbox (`ROBOUSE_SANDBOX=0`), with each task's default budget, after each task's reference solution had scored 1 and its no-op control 0 on the same commit. All 7 scored 1:

| Task | Reward | Steps | Wall time |
|---|---|---|---|
| `chemlab-balance-draft-shield` | 1.0 (done) | 257 of 600 | 37.8 s |
| `chemlab-drying-oven-door` | 1.0 (done) | 307 of 900 | 40.2 s |
| `chemlab-fume-hood-sash` | 1.0 (done) | 399 of 900 | 58.0 s |
| `chemlab-hotplate-stirring` | 1.0 (done) | 189 of 600 | 44.7 s |
| `chemlab-hotplate-temperature` | 1.0 (done) | 159 of 600 | 34.6 s |
| `chemlab-moisture-analyzer-lid` | 1.0 (done) | 77 of 500 | 40.0 s |
| `chemlab-shaker-hood` | 1.0 (done) | 530 of 900 | 85.2 s |

Claude Code reported $1.14 for the 7 sessions at list prices. Since the sandbox was off, every tool call was read. The agents ran `robo` and read their own camera images; in two trials they drove a door or a hood along its arc with a loop that computed the points with `python3 -c`, which the shaker trial wrote as a script in `/tmp`. Apart from that script, no trial read or wrote a file outside its workspace, none used the network, and every request in each episode's trace matched a `robo` command of the Bash call that was running when the server got it. One try per task is not a measured success rate.

## Not done yet

- No hub dataset (see above).
- State observations only: there is no vision variant of these tasks yet.
- Only joints the tasks operate are bridged. Push keys and buttons (the hotplate's knob push, the fume hood's light and fan switches, the panels' keys) move and spring back, but the scene does not yet send their presses to the runtime.
- No randomized start states or instrument placements: every task has one layout.
