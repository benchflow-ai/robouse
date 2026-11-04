# robo-use on BenchFlow

A robo-use run is a BenchFlow run. robouse task folders are a BenchFlow task format: BenchFlow loads them directly from `tasks/` and runs them with its own runner, agents, sandboxes, verifier, trial layout and job tooling. There is no export step and no second runner.

```sh
# the same trial, two ways (both are one BenchFlow job)
bench eval run --tasks-dir tasks/metaworld/metaworld-push --agent codex --model gpt-6-astra --sandbox docker
robouse run --task metaworld-push --agent codex --model gpt-6-astra --out jobs
```

What robouse keeps: the simulator backends (each declares its robot as an embodiment), the tasks, the reference solutions and the adapters. What comes from BenchFlow (`benchflow.embodied`, see BenchFlow's `docs/embodied.md`): the embodiment spec, the agent-facing `robo` command and its protocol, the trusted episode server, the simulator-sidecar wiring, the physical verifier, the per-step trace and training export, seeded rollouts, and everything else that runs a trial. The agent and model matrix is BenchFlow's (`bench agent list`: `claude`, `codex`, `gemini`, `openhands`, `oracle`, ...).

| Piece | Where it lives now |
|---|---|
| Episode server (budgets, recording, judge, oracle token, vision mode, skills) | BenchFlow `benchflow/embodied/server.py` (+ `skills.py`); robouse `session.py` and `embodied.py` adapt the backends to it |
| `robo` command | BenchFlow `benchflow/embodied/robo.py` (stdlib only); robouse `agent_cli.py` re-exports it for the `robo` script and the oracles' `_send` |
| Compose topology, agent image, sim entry point, verifier | BenchFlow `benchflow/embodied/templates/`, `sidecar.py`, `verifier.py` |
| Simulator image | robouse `src/robouse/engine/templates/sim/` (Dockerfile + requirements; meshes fetched at build time) |
| Task format | robouse `engine/format.py`: `RobouseTaskFormat(EmbodiedTaskFormat)` |

The `robo` command is generic now: `robo info` prints the embodiment (action groups, skills, sensors, budgets), `robo act GROUP=V1,V2,... [GROUP=...]` commands one or more named action groups in one step (e.g. `robo act arm.ee_delta=0.2,0,-0.1 gripper=1`, or `left.ee_delta=... right.gripper=...` on ALOHA), and `robo skill arm.move_to X Y Z`. Every older command still works (`robo act DX DY DZ GRIP`, `robo move-to`, `robo grip`, `robo skill NAME ARGS`), so published task instructions are unchanged.

## How it fits together

BenchFlow (an unreleased build; see its `docs/task-formats.md`) has a task-format hook. A package registers a format through the `benchflow.task_formats` entry point. robouse registers `robouse.engine.format:RobouseTaskFormat` in `pyproject.toml`. When BenchFlow loads a folder whose `task.md` has a top-level `robouse:` block, it asks robouse to materialize it as a native BenchFlow package and runs that package. The same hook serves `bench eval run --tasks-dir`, `bench tasks check`, and `RolloutConfig` / `Evaluation` in the Python API.

The materialized package is written once, content-addressed by the task, the robouse package and the options, under `~/.cache/benchflow/task-formats/robouse/` (`BENCHFLOW_TASK_FORMAT_CACHE` moves it):

```
runtime-<hash>/                        simulator image build context, shared by every task:
  Dockerfile  requirements.txt  robouse/src/robouse/   (robouse's)
  benchflow_embodied/  embodied-sim-entry              (BenchFlow's embodied layer, vendored)
tasks/<key>/<task-id>[--seed-<n>]/
  task.md                              schema 1.3; the robouse block moves to metadata.robouse; verifier.service: simulator
  environment/Dockerfile               agent (`main`) image: python + numpy + the `robo` client, nothing else
  environment/robo                     copy of benchflow/embodied/robo.py (standard library only)
  environment/docker-compose.yaml      `main` + the trusted `simulator` service; embeds the task definition
  verifier/{verifier.md,test.sh}       BenchFlow's physical verifier; runs in `simulator`
  oracle/solve.sh + oracle/vendor/     reference solution (robouse oracle code, BenchFlow's socket client; Meta-World's scripted policies)
```

Sources: [`src/robouse/engine/format.py`](../src/robouse/engine/format.py), [`src/robouse/engine/templates/sim/`](../src/robouse/engine/templates/sim/) and BenchFlow's `benchflow/embodied/sidecar.py`. `robouse export --tasks ... --out DIR` writes the same packages as a movable bundle (`DIR/tasks/<id>/`, `DIR/runtime-<hash>/`, relative build context), for publishing or for a machine without robouse installed.

## Trust model

```
 main (agent container)                            simulator (trusted container)
 ┌──────────────────────────────────┐             ┌───────────────────────────────────────────┐
 │ BenchFlow agent / oracle         │  JSON over  │ benchflow.embodied.serve + robouse backend│
 │ /usr/local/bin/robo  (stdlib)    │ Unix socket │ MuJoCo + Meta-World / Gymnasium-Robotics  │
 │ ROBOUSE_SOCKET=/rpc/episode.sock │────────────►│ step + wall budgets, video, success judge │
 │ /rpc  (read-only volume)         │             │ /episode (record; not mounted in main)    │
 │ network: yes (model API)         │             │ network: none                             │
 └──────────────────────────────────┘             │ verifier: test.sh → /logs/verifier/reward │
                                                  └───────────────────────────────────────────┘
```

- **Agent container (`main`).** The `robo` client and numpy only: no simulator, no MuJoCo, no robouse source, no task definition, no episode record. The shared `rpc` volume is mounted read-only; it holds the socket and the camera images `robo observe --image` saves (`/rpc/ws/observations/obs_NNN.png`). BenchFlow runs the agent as its unprivileged sandbox user.
- **Simulator container (`simulator`).** Runs BenchFlow's episode server with the robouse backend (`python -m benchflow.embodied.serve --factory robouse.embodied:episode_from_task`) with `network_mode: none`. The episode record (`result.json`, `episode.json`, `steps.jsonl`, `trace.jsonl`, `frames.jsonl`, `video_index.json`, `recording.mp4`) is written to the `episode` volume, which only this container mounts. The image is built from the shared runtime; compose names it per trial, so BenchFlow's per-trial cleanup (`compose down --rmi all`) never removes an image another trial is using, and rebuilds come from the Docker build cache in seconds.
- **Verifier.** `verifier.service: simulator`: BenchFlow runs `verifier/test.sh` in the simulator and downloads `/logs/verifier` from there. The compose file drops BenchFlow's default host mount of `/logs/verifier` into `main`, so reward files the agent writes never reach the host. If the agent stopped without `robo done`, the verifier sends `shutdown`; the server closes the episode as `agent_exited` and judges the physical state after the usual settle period, as a local run does. The verifier then copies the episode record to `verifier/episode/`, the video and the agent's camera images to `artifacts/`, and writes `reward.txt` (1 if the server judged success), `reward.json` (`reward`, `success_ever`, `budget_used`) and `reward-details.json`. BenchFlow then writes `trainer/embodied_steps.jsonl` (one state/action/reward row per simulator step) and `trainer/embodied_episode.json` (embodiment, video index) next to `trainer/atif.json`. A missing result is an infrastructure error, not a zero.
- **Oracle.** `oracle/solve.sh` runs in `main` like an agent and drives the robot only through the socket. BenchFlow uploads `/oracle` for every rollout and locks it away from agents. For vision tasks the oracle needs a token that unlocks privileged state. No package stores one: the simulator reads `$ROBOUSE_ORACLE_TOKEN` from the host through compose, and the reference solution gets the same variable through `oracle.env` in `task.md`, which BenchFlow passes to the oracle only. `robouse run` sets a fresh random value for each oracle job; with `bench eval run --agent oracle`, set it yourself (`ROBOUSE_ORACLE_TOKEN=$(openssl rand -hex 16) bench eval run ...`). Unset, the simulator has no token and nothing is privileged, so vision tasks' reference solutions fail.
- **Prompt.** The task body with the same preamble a local run used (`harnesses.PROMPT_PREFIX`).
- **Wall clock.** The episode clock starts when the simulator is up, before BenchFlow installs the harness, so the episode's wall budget is the agent timeout plus 900 s. The step budget (`max_steps`) is the real limit.

## Commands

Requirements: Docker with Compose v2.24.4 or newer (the compose file uses `!override`), and robouse installed with a BenchFlow build that has the embodied layer (`benchflow.embodied`) and the task-format hook. No BenchFlow release on PyPI has them yet (0.7.9.dev2354, the version the `benchflow` extra pins, does not), so this page describes the maintainers' setup until one does. The host needs no simulator: MuJoCo runs in the container. Meta-World oracles vendor Meta-World's scripted policies, taken from the installed `metaworld` package or, without one, from the pinned wheel on PyPI.

```sh
git clone https://github.com/benchflow-ai/robouse.git && cd robouse
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[metaworld,gymrobotics]"

# check a task (materializes it, then BenchFlow's own checks)
.venv/bin/bench tasks check tasks/metaworld/metaworld-reach --level runtime-capability --sandbox docker

# BenchFlow directly: a task, a suite, or any folder of robouse tasks
.venv/bin/bench eval run --tasks-dir tasks/metaworld/metaworld-reach --agent oracle --sandbox docker
.venv/bin/bench eval run --tasks-dir tasks/arc-style --agent codex --model gpt-6-astra --sandbox docker --concurrency 4

# robouse's wrapper: bundled task ids, --filter / --task-list / --limit, plus --seed, --timeout and the noop control
.venv/bin/robouse run --task metaworld-push --agent claude --model claude-opus-5 --out jobs
.venv/bin/robouse run-many --tasks tasks --task-list my-tasks.txt --agent oracle --out jobs --concurrency 3
.venv/bin/robouse run-many --tasks tasks/metaworld --agent noop --out jobs --limit 5      # must score 0

# seeded rollouts: one trial per task and seed; summary.json gets pass@k, mean, std per task
.venv/bin/bench eval run --tasks-dir tasks/metaworld --seeds 0-4 --agent oracle --sandbox docker
.venv/bin/robouse run-many --tasks tasks/metaworld --seeds 0-4 --agent codex --model gpt-6-astra --out jobs
.venv/bin/bench embodied report jobs/<job>                       # the same table for any job
.venv/bin/bench embodied export jobs/<job> --out dataset/        # steps.jsonl + episodes.jsonl for training

# a movable bundle of native packages
.venv/bin/robouse export --tasks tasks/metaworld --out dist/robouse-metaworld [--noop]
# BenchFlow 0.10 runs the exported packages with no robouse installed, on Docker or Daytona, and checks each
# trial's episode record against its verdict
bench run dist/robouse-metaworld/tasks --agent oracle --sandbox docker --jobs-dir jobs/oracle
bench embodied verify jobs/oracle

# two roles on one robot (a BenchFlow scene): a planner that may only look, an operator that acts
.venv/bin/python tools/benchflow/scene_planner_operator.py --task tasks/arc-style/arc-gravity --agent codex --model gpt-6-astra
```

Seeds: Meta-World picks one of its 50 goal and object variations per seed; LIBERO, robosuite and Gymnasium-Robotics seed their resets; the tabletop, drone, RoboHarm and menagerie scenes are fixed by the task, so every seed starts from the same state (the report's `distinct_initial_states` and `reset_reproducible` show which).

`robouse run` / `run-many` call `benchflow.Evaluation` ([`src/robouse/engine/run.py`](../src/robouse/engine/run.py)) and print one line per trial. `--agent` takes any BenchFlow agent; `claude-code` is an alias of `claude`, and `noop` runs BenchFlow's `oracle` agent on a package whose oracle only looks (`robo info`, `robo observe`) and exits without `robo done`. For Claude agents without `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` in the environment, the wrapper takes a token from the optional pool in `ROBOUSE_CLAUDE_TOKEN_FILE`, as the local harness does. For Codex agents without `OPENAI_API_KEY` or `CODEX_AUTH_JSON`, when a Codex account pool is configured (`ROBOUSE_CODEX_AUTH_DIR`), the wrapper passes `CODEX_AUTH_JSON` from that account's persistent home (`~/.cache/robouse/codex-home-<account>/auth.json`, the local harness's home), and BenchFlow writes it into the agent container; the host's own `~/.codex/auth.json` is not read. Without the pool, Codex falls back to BenchFlow's subscription auth, which uploads the host login.

Trials use BenchFlow's job layout:

```
<out>/<job>/summary.json  results.jsonl
<out>/<job>/<task>__<id>/config.json  result.json  timing.json  prompts.json
    agent/          harness log (codex_acp.txt, oracle.txt, ...), install log
    trajectory/     acp_trajectory.jsonl (and llm_trajectory.jsonl when the LiteLLM proxy is used)
    trainer/        atif.json, verifiers.jsonl, adp.jsonl, embodied_steps.jsonl, embodied_episode.json
    verifier/       reward.txt  reward.json  reward-details.json  test-stdout.txt
                    episode/  result.json episode.json steps.jsonl trace.jsonl frames.jsonl video_index.json
                              recording.mp4 serve.log observations/
    artifacts/      recording.mp4  observations/
```

## The local engine

`robouse run --engine local` keeps the older in-process runner ([`src/robouse/runner/`](../src/robouse/runner/)). It runs the episode server and the harness as host processes, with the harness in the agent sandbox (macOS Seatbelt, Linux bubblewrap). Use it on a machine without Docker, and for `molmoact2`, which BenchFlow does not have. The September runs' `claude-code-glm`, `codex-glm` and `mini-swe-agent-glm` (GLM-5.3 on Baseten) ran on it too; `robouse run` now refuses those names and names the harness to use instead.

BenchFlow has no host-process sandbox. Its providers are Docker, Daytona, Modal, AgentCore and Apple Container, and all of them run Linux containers. The sandbox contract assumes Linux paths (`/logs/...`, `/oracle`, `/app`), root for agent installs (Node.js into `/opt/benchflow`), and a separate agent user. Apple Container (`--sandbox apple-container`, macOS 26 `container` CLI) is Docker-free, but it runs a single container, so it cannot host the simulator sidecar; `verifier.service` is Docker-only as well. A local mode would therefore need either a new BenchFlow provider that maps those paths onto a host directory (a large change that touches agent install, lockdown and the verifier) or sidecar support in Apple Container. Until one of them exists, a Mac needs Docker for the BenchFlow engine: Colima (`colima start --vm-type vz`) with the Compose plugin works.

## Validation on the embodied layer (2026-09-28)

Same Mac and Colima setup; an unreleased BenchFlow build at the `benchflow.embodied` commit, robouse at the commit that added the embodied engine. Every Docker run below is `bench eval run --sandbox docker`.

| Run | Result |
|---|---|
| Oracle, 7 tasks over 4 suites (arc-gravity, arc-colour-to-pad, metaworld-reach, metaworld-push, drone-waypoint, drone-land-helipad, menagerie-aloha-opening-four, bimanual ALOHA) | 7/7, errors 0, rerun on the final code 7/7. Step counts equal the protocol-1 baseline (reach 51, push 63, arc-colour-to-pad 779, arc-gravity 999) |
| Noop control (`robouse export --noop`, then `bench eval run --agent oracle`), same 7 | 0/7, errors 0, every episode `agent_exited` with 0 steps, closed by the verifier; rerun on the final code 0/7 |
| Seeded oracle, `--seeds 0-2` on metaworld-reach and metaworld-push | 6/6; `summary.json` `seeded`: pass@1..3 = 1.0, 3 distinct initial states per task |
| DexJoCo (local engine; the DexJoCo virtualenv is not in the simulator image) | water-plant (hand) and microwave-cook (bimanual hands): oracle 1.0 (steps 306 and 693), noop 0.0 |
| Real model: Claude Code on GLM-5.3 (Baseten, BenchFlow `vllm/` provider), a substitute, see below | metaworld-push `--seeds 0-2`: 3/3 (pass@1 = 1.0); metaworld-reach 1/1; drone-waypoint 1/1; arc-gravity 0/1 (wrong arrangement, `robo done` at step 1192); menagerie-aloha-opening-four 0/1 (agent timeout at step 477 of 2000). Errors 0 |
| Reset reproducibility | metaworld-push seeds 0, 1, 2 start from identical `initial_state_sha256` in the oracle job and the GLM job |
| Scene: planner + operator on metaworld-push (`tools/benchflow/scene_planner_operator.py`, both roles GLM-5.3) | reward 1.0; the planner made only `info`/`observe` requests, all 65 simulator steps are attributed to the operator in `steps.jsonl` |

The prescribed real agents could not run: the Codex accounts available for the check returned "You've hit your usage limit" until Oct 3-4, and the Claude Code OAuth tokens returned "weekly limit" until Oct 2 (checked with one-line CLI calls; a Codex job started before the check failed with ACP "Internal error" on the first prompt and was stopped). Rerun `robouse run-many --agent codex --model gpt-6-astra` or `--agent claude-code --model claude-sonnet-5` on the same sample once the quotas reset.

## Validation on the protocol-1 engine (2026-09-27)

Mac (Apple Silicon), Colima 0.10.3 with the vz VM (6 CPUs, 12 GiB), Docker 29.5.2, Compose 5.5.1, an unreleased BenchFlow 0.7.9.dev0 build with the task-format hook, robouse at the commit that added the BenchFlow engine.

| Run | Command | Result |
|---|---|---|
| Structure | `bench tasks check tasks/metaworld/metaworld-reach --level runtime-capability --sandbox docker`, `bench tasks check tasks/arc-style/arc-gravity` | valid |
| Oracle, direct | `bench eval run --tasks-dir tasks/metaworld/metaworld-reach --agent oracle --sandbox docker` | 1/1, reward 1.0, `success_reached` at step 51, 1.9 min including the first simulator image build |
| Oracle, 3 suites | `robouse run-many --tasks tasks --task-list … --agent oracle --concurrency 3` on metaworld-reach, metaworld-push, arc-gravity, arc-colour-to-pad, gymrobotics-fetch-push-s0, gymrobotics-pointmaze-umaze-s3 | 4/6 reward 1.0; 2 infrastructure errors in the first, cold-cache batch (`main` container removed between create and start, `No such container`), recorded as errors, not zeros. Rerun of those 2 plus arc-swap and arc-mirror: 4/4 reward 1.0. In total, 8 distinct tasks at 1.0 |
| Exported bundle | `robouse export --tasks tasks/arc-style --filter arc-gravity --out A`, copy `A` elsewhere, then the released `bench` 0.7.4 (no task-format hook): `bench eval run --tasks-dir <copy>/tasks --agent oracle --sandbox docker` | 1/1, reward 1.0, 0.9 min |
| Noop control | same 6 tasks, `--agent noop` | 0/6, errors 0; every episode closed by the verifier (`closed_by: verifier_shutdown`, outcome `agent_exited`, 0 steps) |
| Claude Code, claude-opus-5 | `robouse run-many --tasks tasks --task-list … --agent claude-code --model claude-opus-5 --concurrency 3` on metaworld-push, arc-gravity, gymrobotics-fetch-push-s0 (BenchFlow's `claude` agent, with a Claude Code OAuth token) | **3/3 reward 1.0**, errors 0, about 2.3 min per trial including the harness install. metaworld-push `success_reached` at step 94 (7 shell calls: info, observe, 4 move-to, grip, done); arc-gravity `done` at step 769 (25 move-to, 8 grip); gymrobotics-fetch-push-s0 `done` at step 138 (5 move-to, 11 act). Every trace in `verifier/episode/trace.jsonl` has only public `robo` requests. Token counts are not in `result.json` on this native-auth path (usage source `agent_native_acp`) |
| Codex, gpt-6-astra | `robouse run-many … --agent codex --model gpt-6-astra` on metaworld-push, arc-gravity, gymrobotics-fetch-push-s0 | not a model result: the host Codex login (`~/.codex/auth.json`) had been replaced by a placeholder API key during the session, so every model call returned 401 and the agent made 0 robot requests. BenchFlow scored these as reward 0 with `error: null`; see "Open issues" |

Against the local runner (`runs/oracle-*`, `runs/final-*-astra`): all 8 oracle episodes match exactly, same outcome and same step count (metaworld-reach `success_reached` 51, metaworld-push `success_reached` 63, gymrobotics-pointmaze-umaze-s3 `success_reached` 189, gymrobotics-fetch-push-s0 `done` 65, arc-colour-to-pad `done` 779, arc-swap 797, arc-mirror 814, arc-gravity 999). On the local runner, codex + gpt-6-astra solved metaworld-push (83 steps), gymrobotics-fetch-push-s0 (46) and arc-gravity (679).

## Open issues

- **Auth failures score as zeros.** A Codex 401 on every call ends the ACP turn normally, so BenchFlow records reward 0 with no error. A robouse trial with 0 episode requests and a provider error in the agent log should be an infrastructure error.
- **Viewer timeline.** A local trial has `agent/trajectory.json` (ATIF converted from the harness output) and `artifacts/recording_index.json` (video time per step). A BenchFlow trial has `trajectory/acp_trajectory.jsonl` and `trainer/atif.json`, but no `recording_index.json` yet: `robouse.atif` needs a parser for BenchFlow's ACP trajectory.
- **Cold-cache start race.** Two of the first ten trials failed at container start with `No such container` while several trials built the simulator image concurrently for the first time. Reruns did not reproduce it. BenchFlow did not retry them.
- **Claude harness version.** BenchFlow pins its Claude Code harness (on 0.10, `claude-agent-acp@0.81.2` with Claude Code 2.1.280); models that need a newer Claude Code are rejected by the API until the pin moves.
