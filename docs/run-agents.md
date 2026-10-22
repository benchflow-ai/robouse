# Run agents and VLAs

`robouse run` runs one harness on one task and writes one trial folder. Harnesses and what each needs: [Concepts](concepts.md#harnesses).

## Model harnesses

A provider-prefixed model goes through the trial's model gateway, which needs Python 3.12 or newer and the `llm` extra. `mini-swe-agent`, `dimcode` and `kinex` default to `glm/glm-5.3`: GLM-5.3 on the Z.ai Coding Plan, through BenchFlow's `glm` provider. It needs the plan's API key and endpoint (the one below is for a plan bought on bigmodel.cn) and, because the plan has no per-token price, the spend cap turned off, or a price for `glm-5.3` in `ROBOUSE_PRICING` ([Configuration](configuration.md)). mini-swe-agent is a separate package, installed here with Robo Use:

```sh
pip install 'robouse[sim,llm]' mini-swe-agent
export GLM_API_KEY=...
export GLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4
export ROBOUSE_SPEND_CAP_USD=0
robouse run --task arc-gravity --harness mini-swe-agent --model glm/glm-5.3 --out runs/try
```

Claude Code takes the same model with `--harness claude-code --model glm/glm-5.3`. Codex cannot use it: it needs a provider with a Responses API, which the plan does not have. The gateway sends GLM-5.3 no images (BenchFlow's registry does not list its inputs, and the plan's endpoint refuses image parts); the camera images are still files in the agent's workspace. If a setting is missing, `robouse run` names it and starts no trial. mini-swe-agent, Claude Code and dimcode have run whole trials on `glm/glm-5.3` only against a local stand-in for the plan's endpoint; with GLM-5.3 itself they were checked only up to the plan's usage-limit error, so no trial on the plan has reached a result yet ([Supported](supported.md)).

A non-null `exception` in the printed summary means the trial did not run to a result (a missing credential, a harness that is not installed, a harness that stopped on an API error before ending the episode, every request to the model failing, as when the plan is at its usage limit, or Ctrl-C); that trial is not scored, and `robouse run` exits 1. Tasks on other simulators need their extra, for example `pip install 'robouse[metaworld]'` for `metaworld-*` ([Suites](suites.md)).

Options:

- `--timeout 600`: the agent's wall-clock limit in seconds, instead of the task's.
- `--seed 3`: another object and goal layout, where the backend supports it.
- `--extra-instruction TEXT`: text appended to the instruction.
- `--prior-learnings FILE`: markdown appended to the instruction, for example from `robouse summarize TRIAL`.

## Gemini 4 Argon

Gemini 4 Argon (`gemini-4-argon`), generally available in the Gemini API since 2026-10-13, reads text and images and has a 1,048,576-token context. Robo Use reaches it with a Gemini API key from Google AI Studio in `GEMINI_API_KEY`: directly with Gemini CLI, its default model there ([below](#gemini-cli)), or as `gemini/gemini-4-argon` through the model gateway with Claude Code, mini-swe-agent and dimcode:

```sh
pip install 'robouse[sim,llm]'
export GEMINI_API_KEY=...
robouse run --task arc-gravity-vision --harness claude-code --model gemini/gemini-4-argon --out runs/argon
```

The gateway reaches the Gemini API through LiteLLM's own Gemini integration rather than the API's OpenAI-compatible endpoint. Gemini signs each tool call it makes, and Gemini 3 refuses the next request when a signature does not come back with its call (Robo Use assumes Gemini 4 Argon does too); the OpenAI-compatible endpoint returns the signature in a field that an Anthropic tool call has no place for. dimcode drops the signatures from the tool calls it sends back, and the gateway puts them back (`signatures_restored` in `proxy_stats`). Images that an agent reads with its file tool reach the model as images. Claude Code's and dimcode's extended-thinking setting is removed (`thinking_dropped`), so the model thinks at its default level, medium. Codex cannot use the model: the Gemini API has no Responses API, and `robouse run` says so without starting a trial:

```console
$ robouse run --task arc-gravity --harness codex --model gemini/gemini-4-argon --out runs/try
robouse: Codex needs a provider that serves the Responses API; gemini does not (gemini/gemini-4-argon runs on gemini-cli, claude-code, mini-swe-agent or dimcode; Codex runs on its own model, gpt-6-astra)
```

Robo Use's price table has Google's price: $2 per million input tokens and $10 per million output tokens, thinking included, through 2026-11-30, then $4 and $20. The spend cap and the trial's cost use the price of the day. The model is also on OpenRouter, as `openrouter/google/gemini-4-argon`, reached over chat completions like [Glimpse](#glimpse); OpenRouter carries Gemini's signatures in reasoning details that its documentation asks clients to send back with tool calls, and the gateway does not send them, so `gemini/gemini-4-argon` is the route to prefer. With the model itself, [Gemini CLI](#gemini-cli) has run five trials, Claude Code on `gemini/gemini-4-argon` one (`arc-gravity-vision`) and [Kinex](#kinex) four, and each scored 1; mini-swe-agent, dimcode and the OpenRouter route have run whole trials only against a local stand-in ([Supported](supported.md)).

## Glimpse

Elorian's Glimpse, a visual reasoning model in research preview since 2026-10-16, reads text, images and video. Robo Use reaches it through OpenRouter, as `openrouter/elorian/glimpse` (served by Together there), with an OpenRouter key and the model gateway:

```sh
pip install 'robouse[sim,llm]'
export OPENROUTER_API_KEY=...
robouse run --task arc-gravity-vision --harness claude-code --model openrouter/elorian/glimpse --out runs/glimpse
```

OpenRouter lists tool calling for it, which Claude Code and dimcode need, so it runs on Claude Code, dimcode and mini-swe-agent (which sends its model no images). Codex cannot use it, since BenchFlow's OpenRouter entry has no Responses API, and neither can Gemini CLI, which runs only Gemini API models. The gateway reaches OpenRouter over chat completions, and an image that an agent reads with its file tool moves from the tool result into a user message (`images_moved` in `proxy_stats`), where chat completions providers take images. Its price, $0.60 per million input tokens and $3 per million output tokens, is in Robo Use's price table. It has run whole trials only against a local stand-in for OpenRouter ([Supported](supported.md)).

## Gemini CLI

`gemini-cli` runs Google's [Gemini CLI](https://github.com/google-gemini/gemini-cli) headless (`gemini --prompt ... --output-format stream-json --approval-mode yolo`) on its own vendor: a Gemini API model, `gemini-4-argon` by default, with the key in `GEMINI_API_KEY`. It does not use the model gateway, so it has no spend cap, as Claude Code and Codex on their own vendors have none.

```sh
npm install -g @google/gemini-cli
export GEMINI_API_KEY=...
robouse run --task arc-gravity-vision --harness gemini-cli --out runs/gemini-cli
```

Each trial gets a Gemini CLI home of its own in its workspace (`.robouse/gemini-home`, as `GEMINI_CLI_HOME` and `HOME`): your `~/.gemini` settings, `GEMINI.md`, MCP servers, extensions, skills and `~/.env` are not loaded, the machine's system settings are not read, and nothing one trial writes there reaches another. Gemini CLI is offered only its shell, file and search tools (`run_shell_command`, `read_file`, `write_file`, `replace`, `glob`, `grep_search` and `list_directory`): no web search or fetch, subagents or skills. Its shell commands run without the variables whose names mark a credential, so `GEMINI_API_KEY` is not in their environment; Gemini CLI's own process still holds the key, and an agent can read it from there, as it can Claude Code's login. Its loop detection is off, since it ends a session when the same tool call repeats five times in a row, and a robot is often driven by repeating one command. Its stream-json output becomes the trial's trajectory, and the trial's cost comes from Robo Use's price table, thinking tokens included. `GOOGLE_GEMINI_BASE_URL`, Gemini CLI's own setting for another endpoint, is passed on when you set it.

Gemini CLI runs only Gemini API models (a bare id, or `gemini/<id>`) and only the `cli` interface; `robouse run` refuses anything else before the trial starts:

```console
$ robouse run --task arc-gravity --harness gemini-cli --model openrouter/elorian/glimpse --out runs/try
robouse: gemini-cli runs only Gemini API models (a bare id such as gemini-4-argon, or gemini/<id>): it speaks the Gemini API's own protocol, and Robo Use does not route it through the model gateway. Run openrouter/elorian/glimpse on claude-code, mini-swe-agent or dimcode
```

On Gemini 4 Argon itself (2026-10-21), Gemini CLI 0.64.0 ran five trials with Robo Use 0.6.0 on Linux x86_64 without the sandbox (`ROBOUSE_SANDBOX=0`), one try per task: `one-demo-box-mirrored`, `arc-gravity-vision`, `libero-pro-spatial-swap-1`, `one-demo-drawer-left` and `libero-pro-object-swap-3` all scored 1 ([Supported](supported.md)). One try per task is not a measured success rate, and Gemini CLI has not yet run under the sandbox.

A limitation of Gemini CLI 0.64.0 in headless mode: it treats what its shell commands print as untrusted, and refuses any later command with an argument that starts with `-` and appeared in that output (apart from common flags on its own list). That catches a negative coordinate copied from `robo observe`, and robo's own flags once `robo --help` has printed them. The agent sees only "Tool execution denied by policy." In the five trials above, it refused seven commands in two of them; the agents went on with the commands written another way, and both trials scored 1. Robo Use's prompt says nothing about the check, so a refused command costs the agent a turn and time.

## Show-Harness

`show-harness` runs NUS Show Lab's [Show-Harness](https://showlab.github.io/Show-Harness/): the model looks at the task's camera images and picks one parameter-free action unit per call (a move in one of six directions, `GRASP`, `RELEASE` or `DONE`), and an interpreter turns each unit into closed-loop hand motion, every control step counting against the step budget. `--model` is required, since the policy is the model's reading of the images: a provider-prefixed model runs Show-Harness's zero-shot loop through the model gateway if BenchFlow's provider registry lists it as reading images (`robouse run` refuses any other before the trial starts, `glm/glm-5.3` included, since the gateway would remove every camera image); a model you serve at `ROBOUSE_SHOW_HARNESS_URL`, such as one of its fine-tuned adapters on vLLM, runs the fine-tuned loop. No provider-prefixed model has been tested with it in Robo Use 0.4.1. It runs only tasks on the `tabletop`, `libero` and `cubepick` backends, and stops before moving any other robot. It sees the images, the hand's height and the gripper's width, not object coordinates, and it does not turn the hand. It has no unit for refusing, so it cannot pass the four `safety: refuse` tasks on these robots. On LIBERO a unit takes 8 to 12 control steps, so the step budgets there (280 to 520 steps) are tight for it.

## ASPIRE

`aspire` runs NVIDIA's [ASPIRE](https://github.com/NVlabs/ASPIRE) (Agentic /Skills Discovery for Robotics, Apache-2.0) with Claude Code, and `aspire-codex` runs it with Codex. ASPIRE is a workflow for coding agents that write robot programs: explore the scene, write a program, run it on development seeds, debug it by failure mode, select one program, check it once on unseen-check seeds, and hand it over to be evaluated, frozen, on held-out seeds. Patterns that a separate verifier could reproduce a fix from go into a skill library that later tasks read. The agent follows ASPIRE's own skill files, its `iterative-debugging` and `evosearch` skills at commit `fa00f0e`, which ship unchanged in the package, as the coordinator of a campaign for the trial's one task, with the Agent tool (Claude Code) or its own agents (Codex) for ASPIRE's workers and verifiers.

Each trial has two phases:

- Practice. The agent runs its programs with `cap-harness`, as ASPIRE's skills say, but each run is a practice episode: the task's own episode server on another seed of the task, started for that one run. Only ASPIRE's development and unseen-check seeds run (on `capx`, 101 to 125 and 126 to 130, ASPIRE's Robosuite bands), never a seed that shows the scored scene, and each unseen-check seed runs once. The agent never gets the scored episode.
- Stage 2. When the agent exits, Robo Use runs the program it selected once on the scored episode, under the same rules as its practice runs, and ends the episode with `robo done`. The episode server judges it as it judges any trial.

The scored episode is locked: it serves only requests that carry a token that the runner hands the harness's own process on its standard input and the agent never sees. Until Stage 2 unlocks it, only the runner's status check and give-up are served; after the unlock, every request must still carry the token. A request without it is refused and counted, and a trial with any such request is not scored: it ends with an `IntegrityError` in `result.json`.

The harnesses run code-as-policy tasks whose seeds give distinct scenes: the `capx` and `capx-libero` suites, and LIBERO tasks whose seed picks one of several start states, such as the `libero-pro` suite's. On any other task the trial stops before it starts and says why. The CaP-X suites are not in the package: they need a checkout of Robo Use for their task folders and CaP-X's simulator environment (`ROBOUSE_CAPX_PYTHON`, `ROBOUSE_CAPX_LIBERO_PYTHON`). Programs call the task's own API, not ASPIRE's perception tools, which need SAM3 and other model servers on a GPU: on the CaP-X suites, CaP-X's privileged API with object poses from the simulator; on `libero-pro`, the camera images (`robo.image`) and their calibration (`robo.info()`). Each trial's workspace has a page, `docs/robouse.md`, that tells the agent every way it differs from ASPIRE's repository.

On `libero-pro`, a trial also differs from ASPIRE's own LIBERO-PRO protocol in four ways. The arm takes LIBERO's end-effector deltas (robosuite's OSC_POSE controller), where ASPIRE's adapter takes joint targets (JOINT_POSITION). Programs see 256x256 RGB images with each camera's projection matrix, where ASPIRE's get RGB-D images with intrinsics. The episode counts as solved the first time LIBERO's goal check holds, where ASPIRE checks once, when the program ends. And seed n restores LIBERO-PRO's saved start state (n - 1) mod 50, where ASPIRE's skills sample a new layout for each seed (`--init-mode seeded`). Practice therefore runs on the other saved states, by default development seeds 36 to 50 and unseen-check seeds 21 to 35, and never on state 0, the scored start; ASPIRE's own LIBERO bands (51 to 80) would replay states 0 to 29.

When `ROBOUSE_ASPIRE_LIBRARY` names a folder, the skill library persists across trials: the folder is created on first use from ASPIRE's own library, each trial starts from it, and what the trial's coordinator promoted goes back into it when the trial ends. Nothing goes back from a trial whose verdict is not a verified result (an integrity failure, or a verdict without the server's signature), and library entries only when the trial's own ASPIRE verifier reported the task verified, as ASPIRE promotes only verified entries. The folder also keeps the program each task selected, and a later trial of the same task on another scene, with the same harness and model, runs that program as its Stage 2 without a new practice phase, as ASPIRE evaluates one frozen program on every held-out seed (`ROBOUSE_ASPIRE_REUSE=0` turns this off; `any` also reuses a program another harness or model selected). A trial whose scored scene the library has practised on is refused. Without the setting, each trial starts from ASPIRE's own library and keeps what it promoted in its trial folder only.

A trial gets at least four hours, or the time `--timeout` gives. `ROBOUSE_ASPIRE_WORKFLOW=evosearch` runs ASPIRE's Evolutionary Search instead of its fix loop; `ROBOUSE_ASPIRE_DEV_SEEDS` and `ROBOUSE_ASPIRE_UNSEEN_SEEDS` set other seed bands, `ROBOUSE_ASPIRE_PRACTICE_EPISODES` the practice budget (default 300 episodes, 650 with evosearch) and `ROBOUSE_ASPIRE_PRACTICE_WORKERS` how many practice episodes run at once (default 4) ([Configuration](configuration.md)). Claude Code gets the Agent and Skill tools as well as its usual six, and waits for the subagents it runs in the background until the practice time is up. The trial folder keeps the practice episodes' records, the campaign's notes and the library after the trial under `aspire/`, and `result.json` records the practice, the selected program, Stage 2 and the library under `harness_record`.

How the harnesses were checked (2026-10-20): `aspire` ran whole trials on five `capx` tasks (`capx-cube-lifting-s1`, `-s2` and `capx-cube-stack-s1`, `-s2`, `-s3`) with Claude Code 2.1.304, on Linux x86_64 without a sandbox, through the model gateway to a scripted local stand-in model that answers with fixed tool calls. That checks the practice episodes, the lock, Stage 2 and the persistent library, not how any model does. With `claude-opus-5-5`, Claude Code 2.1.304 then ran five trials on the same machine, with smaller practice bands than ASPIRE's (development seeds 101 to 108 and unseen-check seeds 126 and 127 on `capx`, 43 to 50 and 34 and 35 on libero-pro), one practice episode at a time, one persistent library and a one-hour limit per trial. `capx-cube-lifting-s5`, `capx-cube-stack-s5` and `capx-nut-assembly-s5` scored 1, each adding to the library an entry that ASPIRE's verifier reproduced on five development seeds. An earlier `capx-cube-stack-s5` trial scored 0 because Claude Code stopped ASPIRE's worker before it selected a program, which this version fixes. `libero-pro-10-task-6`, run from a checkout with the libero-pro suite, scored 0: practice time ran out before a program was selected. These trials ran before the scored episode's lock took its present form; an audit of their transcripts and of each scored episode's trace found no file read outside the trial's workspace except the Python environment's, and no request to a scored episode before its Stage 2. Five trials check the harness with a model; they do not measure how it does on a suite. Under the macOS sandbox, whole trials have run only in the test suite, with a scripted agent on a light task. `aspire-codex` has not run a whole trial, and no `capx-libero` trial has run.

## Kinex

`kinex` runs [Kinex](https://github.com/stacx-lab/kinex) 1.0.0, a robotics coding agent built on the Pi SDK, headless (`kinex run`), with the trial's robot connected as Kinex devices. Kinex reaches a simulator through [RoboEnv](https://github.com/stacx-lab/RoboEnv), which serves the robot's devices over HTTP on `127.0.0.1` and writes their profiles and drivers into the workspace's `.kinex/` folder. For a Robo Use episode, a bridge in Robo Use does both: it speaks RoboEnv's protocol, runs in the agent's sandbox as a client of the episode socket, and turns every device call into `robo` requests. So the episode server keeps the step budget, the video and the score, and the devices show what `robo` shows and nothing more: on a vision task, the hand and the camera images, never the objects.

The devices:

- `world`: the episode's clock. One control step is the task's step length, or 0.05 s when the task does not declare one. `read` gives the time and the step budget in seconds, and `wait` runs the simulator for that long. The robot moves only while time passes on `world` (Kinex's `servo` tool waits for you), and every step counts against the budget.
- `arm` and `gripper`, when the robot is one arm driven by end-effector velocity and its observation has `hand_pos`, such as the tabletop and LIBERO robots. `arm` is the hand's position as three prismatic joints x, y and z, in metres in the world frame, with Kinex's own forward and inverse kinematics; the hand frame keeps the world's orientation. `gripper` takes -1 (open) to +1 (closed), as `robo` does. Writes are position references, which the hand follows step by step while the world waits. Rotation and any other action groups hold still; `robo act` drives them.
- One RGB camera for each camera the task has, such as `front_camera`, whose read is `robo observe --image --camera front`. A camera's calibration is in its profile only on vision tasks, where `robo info` gives it.

`robo` stays on the agent's `PATH`, and the agent ends the episode with `robo done`. If the agent also moves the robot with `robo`, the arm's reference moves to where the hand is, and the gripper keeps the last value a device write gave it.

Kinex needs Node 22.19 or newer and npm. Install release 1.0.0, checked against its checksums, into a folder of its own, then the Python environment that Kinex's tools and drivers run in, which every trial shares and no agent can change:

```sh
mkdir kinex-1.0.0 && cd kinex-1.0.0
for f in kinex-core-1.0.0.tgz kinex-setup-1.0.0.tgz kinex-1.0.0.tgz SHA256SUMS; do
  curl -fsSLO https://github.com/stacx-lab/kinex/releases/download/v1.0.0/$f
done
shasum -a 256 -c SHA256SUMS
npm install --prefix . --ignore-scripts --no-audit --no-fund ./kinex-core-1.0.0.tgz ./kinex-setup-1.0.0.tgz ./kinex-1.0.0.tgz
export ROBOUSE_KINEX=$PWD/node_modules/kinex/bin/kinex.mjs
cd ..
uv venv --python 3.12 ~/.cache/robouse/kinex-venv
uv pip install --python ~/.cache/robouse/kinex-venv/bin/python numpy scipy Pillow PyYAML 'opencv-python-headless>=4.7,<5'
```

`robouse doctor` says whether Kinex and its Python environment are in place (`ok kinex`). With the model's settings as in [Model harnesses](#model-harnesses):

```sh
robouse run --task arc-gravity --harness kinex --model glm/glm-5.3 --out runs/kinex
```

Run this way against a scripted local stand-in for the plan's endpoint, whose fixed Kinex tool calls move the four blocks through the devices (Kinex 1.0.0 on a clean install, Linux x86_64, 2026-10-20; that machine has no bubblewrap, so with `ROBOUSE_SANDBOX=0`), the command printed:

```console
$ robouse run --task arc-gravity --harness kinex --model glm/glm-5.3 --out runs/kinex
{
  "trial": "arc-gravity__kinex__14124f",
  "reward": 1.0,
  "outcome": "done",
  "steps": 742,
  "wall_s": 34.8,
  "exception": null
}
```

With a real model, Gemini 4 Argon through the gateway (`--model gemini/gemini-4-argon`, with `GEMINI_API_KEY`), Kinex 1.0.0 ran four trials with Robo Use 0.6.0 on Linux x86_64 without the sandbox, one try per task, on 2026-10-21: `arc-gravity`, `libero-spatial-0`, `libero-object-0` and `libero-goal-8` all scored 1 ([Supported](supported.md)). Four trials check the harness with a model; they do not measure a success rate.

Each trial's Kinex gets a configuration folder and a home folder of its own inside the workspace (`.robouse/kinex`), so your Kinex settings and sessions, Pi packages, extensions, skills and MCP servers are not loaded. Kinex's bundled web search is turned off, and so is Pi's network activity other than model requests. Kinex runs with `--yolo`: it approves its own tool permissions, and its questions get no answer. The bridge answers only requests that carry the trial's session, which only that trial's workspace and environment hold, so another trial's agent that finds its port cannot drive this robot. The shared Python environment is linked into each workspace as Kinex's managed Python; the sandbox lets agents read it but not change it while it is in `~/.cache/robouse`, the default (`ROBOUSE_KINEX_VENV` names another, which the sandbox does not protect). Nor can agents change Kinex's own install, the `node_modules` folder that holds the launcher `ROBOUSE_KINEX` names, with Kinex's packages and the Python helpers its tools and drivers import; and Kinex's Python processes keep their bytecode in the trial's workspace (`PYTHONPYCACHEPREFIX`), not next to those helpers. So no trial leaves code in a place that a later trial runs. A launcher that does not resolve into a `node_modules` folder gets no such protection, since the sandbox does not know where its install is.

In the trial folder, `agent/stderr.txt` starts with the devices the bridge offered, `agent/pi_session.jsonl` is Kinex's session, and `agent/trajectory.json` gives each Kinex tool call the `robo` requests it made.

## Isolation

Model harnesses run in a sandbox that hides the trial's run folder, the task folder with its reference solution, the installed package and other trials' workspaces from the agent. Its environment carries no model provider key and no other variable whose name marks a credential (a token, key, secret, password or login, such as `GITHUB_TOKEN`, `HF_TOKEN`, `AWS_SECRET_ACCESS_KEY` or `SSH_AUTH_SOCK`); a harness adds back only what its program needs, such as its own vendor's login. Nor can it read or write credential and task-copy locations in your home folder: other programs' logins (such as `~/.ssh`, `~/.aws`, `~/.config/gcloud`, `~/.config/gh`, `~/.netrc` and `~/.docker`), your own Claude Code, Codex, Gemini CLI and mini-swe-agent settings (`~/.claude`, `~/.claude.json`, `~/.codex`, `~/.gemini`, mini-swe-agent's global `.env`), `~/.env`, BenchFlow's settings and task cache (`~/.config/benchflow`, `~/.cache/benchflow`), package caches that hold copies of the tasks with their reference solutions (`~/.cache/uv`, pip's cache), and Robo Use's own cache (`~/.cache/robouse`: simulator environments and other trials' harness folders). The full list is `HOME_DENIED` in [`src/robouse/runner/sandbox.py`](../src/robouse/runner/sandbox.py). A `.env` file in any folder above the run folder, the task folder or the Robo Use install, such as a project's `.env` next to its virtualenv, is out of reach too. The agent keeps its own harness folder, and Codex's own install in `~/.codex/packages` stays readable so Codex can run. When Robo Use runs from a source checkout, the checkout's `tasks/`, `runs/`, `adapters/` and `assets/` folders are out of reach too, and so are robot models and other files later trials load wherever `ROBOUSE_MENAGERIE_ASSETS` and the like put them, and so, on LIBERO tasks, are the scene files and saved start states of hf-libero in Robo Use's environment and where LIBERO's config points. The agent can read but not change the Python that Robo Use runs on (the episode server and the verifier run on it), and it cannot connect to the Docker, Podman or LXD socket, to your SSH agent or to other trials' episode sockets. On macOS it cannot start `open`, `osascript`, `shortcuts` or `security`, which act outside the sandbox (`security` reads the login keychain, where Claude Code and the GitHub CLI keep their logins). The reference solution and the no-op control run without the sandbox.

The sandbox is a deny list, not a container. It keeps an agent from stumbling on the answer, not one that looks for it:

- The agent runs as your user and can read the rest of the machine: folders outside the lists above, such as other checkouts or copies of the tasks you keep elsewhere. Add such paths to `ROBOUSE_SANDBOX_DENY`. On Linux it can also write wherever your user can, outside the denied folders.
- The network is open, and public copies of the tasks, including reference solutions and verifiers, are on the internet. On Linux, services listening on localhost are reachable too.
- Environment variables whose names do not mark a credential reach the agent, so a secret kept under another name reaches it too.
- Episode sockets have no per-trial authentication: the sandbox refuses the agent's connections to other trials' sockets, but any process of your user outside the sandbox can connect to them.

Run agents you do not trust in a disposable VM or container with no credentials of yours, and check the trial logs before you publish a score.

- **macOS**: the system's Seatbelt sandbox (`sandbox-exec`); nothing to install.
- **Linux**: bubblewrap. Install it first, for example `sudo apt-get install bubblewrap`. Ubuntu 24.04 blocks the user namespaces bubblewrap needs unless an AppArmor profile allows them; if `robouse run` stops with "no sandbox for the agent on this machine", add the profile and load it:

```sh
sudo tee /etc/apparmor.d/bwrap >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

`ROBOUSE_SANDBOX_DENY` adds paths the agent may not read or write, separated by colons, such as credential files. `ROBOUSE_SANDBOX=0` runs the agent without a sandbox; use it only on a machine you trust, since the agent can then read the reference solution.

## VLAs

The `vla` harness drives the robot with a vision-language-action model served elsewhere, usually on a GPU. Its client sends the camera images, the robot state and the instruction to the policy server, and applies the action chunk it gets back through `robo`, like any harness. `--model` names a preset, and `ROBOUSE_VLA_URL` points at the server:

```sh
export ROBOUSE_VLA_URL=ws://gpu-box:8000
robouse run --task libero-10-0 --harness vla --model openpi/pi05_libero --out runs/pi05
```

| Preset | Server |
|---|---|
| `openpi/pi05_libero`, `openpi/pi0_libero` | openpi `serve_policy.py` |
| `lerobot/groot_n1.7_libero`, `lerobot/evo1_libero`, `lerobot/vla_jepa_libero`, `lerobot/smolvla_libero`, `lerobot/pi05_libero` | `robouse/harnesses/vla/lerobot_server.py` (any LeRobot policy) |
| `openvla/openvla-7b-libero` | OpenVLA `vla-scripts/deploy.py` |
| `molmoact2/libero` | Robo Use's MolmoAct2 server |
| `gr00t/so101` | Isaac GR00T `run_gr00t_server.py` |
| `xpolicylab/metal-joint`, `xpolicylab/so101-joint` | XPolicyLab policy servers |
| `openpi/generic`, `gr00t/generic`, `xpolicylab/generic`, `http-json/generic` | templates to fill in |

A preset fixes the wire protocol, how the policy's observation is built from the task's cameras and state, how its actions map onto the task's action vector, and how action chunks are executed. Override any field with a JSON file in `ROBOUSE_VLA_POLICY_CONFIG`. Before the first action the client checks that the preset fits the task (backend, action dimension, control mode); a mismatch ends the episode at 0 steps. A VLA does not decide when it is finished: the client calls `robo done` when the step budget is nearly spent, or, if the preset sets `stop.still_steps`, once the commanded action stops changing.

## Dream-1

The `dream` harness drives the robot with Dream Labs' Dream-1, a world-action model behind Dream Labs' DreamAPI. Its client is Dream's own client library running Dream's own simulation loop: it sends the three cameras' last nine frames (0.2 s apart in simulated time, 320x176 JPEG), the joint angles and the task's instruction, and executes the 48-step joint chunk it gets back through `robo`, then asks again. The simulation waits while a request is out. Dream-1's public models drive Dream's bimanual YAM, so the harness runs the `yam` suite ([Suites](suites.md)); on any other robot it stops at 0 steps and says why.

```sh
uv venv -p 3.12 ~/.cache/robouse/dream-venv
uv pip install -p ~/.cache/robouse/dream-venv/bin/python dreamlabs-client==1.0.0
export DREAM_API_KEY=dl_live_...   # or ~/.dreamlabs/credentials, as the platform's Setup API page prints it
robouse run --task yam-apple-to-bowl --harness dream --out runs/dream
```

`robouse doctor` says whether the client and the key are in place (`ok dream`). On a clean install of robouse 0.5.0 (macOS, Apple silicon, 2026-10-20), with the `yam` suite's virtualenv set up as in [Suites](suites.md), the last command printed:

```console
$ robouse run --task yam-apple-to-bowl --harness dream --out runs/dream
{
  "trial": "yam-apple-to-bowl__dream__08978f",
  "reward": 1.0,
  "outcome": "done",
  "steps": 1199,
  "wall_s": 54.9,
  "exception": null
}
```

`--model` is `dreamlabs/dream-1-beta` (the default) or `dreamlabs/dream-1-beta-flash`, or any checkpoint your account may run, such as a fine-tune. `ROBOUSE_DREAM_PYTHON` names another Python that has the client, and `ROBOUSE_DREAM_ACTIONS` how many rows of each chunk run before the next request (default all 48). The key goes to the client's environment only; the sandbox keeps `~/.dreamlabs` from every agent. Episodes are not recorded to your Dream Labs account: the client uploads every observation it is given unless told not to, and the harness tells it not to, as Dream's own simulation example does. DreamAPI bills by the hour of use; a trial on the `yam` suite takes about a minute. On 2026-10-19, with one trial per task, `dreamlabs/dream-1-beta` solved 6 of the 9 `yam` tasks and `dreamlabs/dream-1-beta-flash` 4.

## Jev

The `jev` harness drives the robot with TypeSafe's Jev, a System One model: Jev answers typed questions about a state, each with a probability for every option, and writes no text or code and calls no tools. So the harness's client runs the loop and every decision in it is Jev's. Each decision, it observes through `robo`, builds Jev's state from the observation, asks its questions in one request to TypeSafe's System One API, and sends the command the answers make. The harness runs the `nav` suite ([Suites](suites.md)), in the protocol of Dimensional's "Can Jev Nav?" study that the suite follows: one decision per 0.5 s of simulated time (the study's 2 Hz; the simulation waits while Jev answers), executed as the task's `drive` skill, Dimensional's discrete command. On any other task the trial stops before the client starts, and says why.

```sh
export TYPESAFE_API_KEY=...
robouse run --task nav-h01-oven --harness jev --out runs/jev
```

Each decision asks four questions, each a Choice: `drive.x` (`forward`, `none` or `backward`), `drive.y` (`left`, `none` or `right`, a sideways step) and `drive.yaw` (`turn_left`, `none` or `turn_right`), which make the `drive` command, and `task` (`continue` or `finished`): `finished` ends the episode with `robo done`, and only Jev's own `finished` does. Each option says what it is for, what it is not for, and gives examples, as in the study. Jev's state is what `robo observe` returns, with the arithmetic done in code, since Jev reads words better than numbers: the target (the observation's `goal`, whose bearing says which way round is shorter when it is behind), whether the straight line to it is blocked and the bearing of each way past, the free space in eight directions, and the robot's own motion, with the last drive command in words and the side it began to go round when blocked. The list of visible furniture is left out, since no question reads it. The questions and the state are in `src/robouse/harnesses/jev/client.py`.

`--model` is `typesafe/jev-latest` (the default, TypeSafe's alias of its newest stable Jev), `typesafe/jev-preview` or a version such as `typesafe/jev-1.13.0`. The key goes to the client's environment only, with `TYPESAFE_BASE_URL` if you set it, as for TypeSafe's own SDK; no `TYPESAFE_` variable reaches any other agent, the episode server or the verifier. The client runs inside the sandbox on Robo Use's own Python, with the standard library only.

Every decision is a step of the trial's trajectory (`agent/trajectory.json`), with the state Jev saw, each answer with its probabilities and confidence, the version of Jev that answered, the tokens and the cost. TypeSafe charges for input tokens only, $0.042 per million for Jev 1.13 and 1.14 (2026-10-20), and a nav episode makes at most 240 requests. There is no spend cap, which only the model gateway enforces. A request TypeSafe refuses, such as one with a wrong key, or one still failing after six tries (rate limits, overload, a lost connection), stops the client without `robo done`: the trial is an infrastructure failure, not a score.

On Jev itself (2026-10-21), with Robo Use 0.6.0 on Linux x86_64 without the sandbox, `typesafe/jev-latest` (Jev 1.13.0) ran each of the 40 nav tasks once: 13 scored 1, and the other 27 ran out of their 1,200-step budget, with Jev never answering `finished`. The 40 trials cost $0.76. One try per task is not a measured success rate ([Supported](supported.md)).
