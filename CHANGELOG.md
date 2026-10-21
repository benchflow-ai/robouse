# Changelog

Notable changes to the `robouse` package, newest first. Versions follow [semantic versioning](https://semver.org/); while the version is below 1.0, a minor version can change interfaces. Dates are PyPI release dates (UTC).

## Unreleased

### Added

- `robouse flora export` and `robouse flora import`: NVIDIA's Flora models label trial recordings. Flora-Rewarder gives an outcome score from 1 to 5 and a failure, suboptimal or normal label for every half second, with reasons; Flora-TempSeg and Flora-Captioner give timestamped captions. The models and NVIDIA's inference scripts are under the NVIDIA License (research or evaluation use only), so Robo Use neither includes nor downloads them: `export` writes the input files of NVIDIA's scripts for finished trials (each trial's recording, the Rewarder's jobs with the task's instruction, and the captioning pipeline's jobs), the scripts run unmodified on a GPU machine with 80 GB, and `import` writes each trial's `grader/flora.json`, with the agent's steps during each labelled stretch, and prints how often Flora's outcome agrees with the simulator's verdict ([Annotate trials with Flora](docs/flora.md)). `--instructions FILE` gives named tasks the instruction Flora sees (for descriptions that also describe the agent's setup), and `grader/flora.json` keeps each dense clip's own labels beside the stitched ones. On an H100, over 21 trials of claude-opus-5-5, Flora's outcome agreed with the simulator on 11 (the simulator solved 19, Flora gave 9 of those a 5); the docs page has the scores, Flora's reasons, the dense labels and captions, and what to set without a CUDA toolkit (`VLLM_USE_FLASHINFER_SAMPLER=0`).
- `robouse report` metrics `flora_agree` (the share of trials where Flora's outcome agrees with the simulator) and `flora_progress` (Flora's progress estimate), from `grader/flora.json`.

## 0.6.0 (2026-10-21)

New content: the `libero-pro` and `one-demo` suites, the `chemlab` suite (from a checkout), the `jev`, `gemini-cli`, `kinex`, `aspire` and `aspire-codex` harnesses, and Gemini 4 Argon and Elorian's Glimpse as models. Isolation and scoring fixes: the model gateway's key opens only its model routes; the sandbox denies LIBERO's task data, `.env` files and the asset folders later trials load; and only a harness's own final error event makes a trial a harness failure.

### Security

- The sandbox denies LIBERO's task data, on macOS and Linux: the scene files, saved start states and demonstrations (`bddl_files`, `init_files`, `datasets`) of the hf-libero package in the runner's Python, found at run time, and the folders LIBERO's config names. They gave a LIBERO task's object layout away, which its vision tasks show only as camera images. The episode server and the verifier, outside the sandbox, still read them.
- The sandbox denies the chemlab suite's instrument files where `ROBOUSE_CHEMLAB_ASSETS` puts them, as it denies Robo Use's cache, their default place: the episode server imports their behaviour runtimes.
- The sandbox denies a source checkout's `assets/` folder and the files that `ROBOUSE_MENAGERIE_ASSETS`, `ROBOUSE_ROBOHARM_TEX` and `ROBOUSE_HUMANOIDBENCH_POLICY` move out of Robo Use's cache, on macOS and Linux. The episode server loads those robot models, textures and the walking policy in later trials, so an agent that could write them could change another trial's robot or run code in a later episode server.
- A trial is a harness failure on account of an error result only when the result is Claude Code's or Gemini CLI's own final event: the last line of its stream-json output, its only result event, after its init event (for Claude Code, of the session it started). Before, any `{"type": "result", "is_error": true}` line ending any harness's output counted, so an agent that wrote one to the harness's output directly (on Linux, through `/proc/<pid>/fd/1`) could turn its unfinished, scored trial into an unscored one that `--retries` and `--resume` run again. An agent's command output could not, since Claude Code quotes it inside JSON strings.
- SECURITY.md, Concepts and Run a suite say that an agent can end its own harness process, which makes its trial an unscored infrastructure failure that `--retries` and `--resume` run again: look at every trial that ended with an exception or was retried before you publish scores.
- No `TYPESAFE_*` variable reaches an agent, the episode server or the verifier; the `jev` harness gives its client TypeSafe's key.
- The model gateway's per-trial key opens only its model routes (Anthropic Messages, chat completions, Responses and the model list). LiteLLM's provider pass-through routes, such as `/gemini/...`, forwarded any request to the provider with your key, outside the spend cap and the trial's image setting; they are refused now, as are its file, batch and other routes.
- No `GEMINI_*`, `GOOGLE_API_KEY`, `GOOGLE_GEMINI_*` or `GOOGLE_GENAI_*` variable reaches an agent, the episode server or the verifier; `gemini-cli` adds back its own key. The sandbox also denies `$GEMINI_CLI_HOME/.gemini` when the runner's environment sets that variable (`~/.gemini` was denied already).
- The sandbox denies `~/.env`, and a `.env` file in any folder above the trial's run folder, its task folder or the Robo Use install (a project's `.env` next to its virtualenv), on macOS and Linux: Gemini CLI and other programs read keys from them.
- The sandbox lets agents read, not change, the Python environment that Kinex's tools and drivers share across trials (`~/.cache/robouse/kinex-venv`). The bridge answers only requests carrying its trial's session.
- The `aspire` harnesses' scored episode is locked: the episode server serves only requests that carry a token which the runner gives the server and the harness's top process on their standard input (a new `unlock_token` secret and `unlock` request). Before the harness's Stage 2 unlocks it, only the runner's status check and give-up are served, with the token. The server records every request it refused in its signed verdict (`lock`), and the runner does not score a trial with any refusal, or with steps on an episode never unlocked (`IntegrityError`).

### Added

- The `libero-pro` suite (73 tasks): LIBERO-PRO's position-swap and new-goal tasks for LIBERO-Goal, -Object, -Spatial and -Long, from LIBERO-PRO at the commit ASPIRE pins, on the LIBERO backend. They are 73 of the 80 (suite, task) pairs NVIDIA's ASPIRE reports its LIBERO-Pro results on; the suite page lists the other seven, which the scripted reference solution does not solve, with the reasons. Each task carries LIBERO-PRO's BDDL file and the first state of its init file; the seed picks a saved state as ASPIRE's `--init-mode saved` does (seed n starts from state n - 1), downloading the init file at first use. Agents see only the cameras and the robot's own state; success is LIBERO's check of the BDDL goal; the budget is ASPIRE's 1000 steps at 20 Hz. The reference solutions are a scripted controller on the privileged scene state ([LIBERO-PRO](docs/suites/libero-pro.md)).
- The LIBERO backend takes a task's own BDDL file (`bddl`), an init file to pick start states from (`init_states`, with `init_mode` `saved` or `seeded`), and gives the reference solution the goal predicates, the geometry of every object, fixture, region and joint, and the arm's joint angles (`privileged_state`). LIBERO init files load without torch, and only as a numpy array.
- The `one-demo` suite: 16 tasks of in-context imitation from one demonstration, after DemoMimic ("One Demonstration, Many Objects", Sharma et al.), whose code and data it does not use. Each task shows one demonstration of a skill on one object, as its `robo` commands and replies in the instruction and as frames the episode server writes into the agent's workspace (`observations/demo_N.png`), and asks for the same skill on a different object whose contact part matches: open a hinged box, take a lid off a container, stand a full bottle up, pull a drawer open. Reference solution 16/16, no-op 0/16; the demonstration's commands replayed on a task, verbatim or shifted to the task object's contact point, score 0 on all 16.
- Tabletop scenes have hinged boxes (`hinged_box`), one-drawer cabinets facing the front, left or right (`cabinet`), lift-off lids (`lid`) and bottles (`bottle`), with the goals `lid_open` and `standing`, and `released` on a cabinet's `drawer` goal (the gripper must have let go of the drawer; the older `drawer` fixture refuses it). A box and a cabinet report `gripper_touching`, since `holding` lists free objects only.
- The `chemlab` suite: 7 tasks on 6 chemistry laboratory instruments from ChemLab-Assets 1.3.0 (MBZUAI), operated by a floating two-finger gripper that also turns about its tool axis: raise a fume hood's sash to its 457 mm stop, close an analytical balance's draft shield until it reads STABLE, set a hotplate's temperature and stirring speed with its knobs, close a drying oven's door so that it heats again, open a moisture analyzer's lid and an incubated shaker's hood. Each instrument's URDF is converted to MuJoCo, and its own behaviour runtime runs alongside, driven by the scene through the contract's bindings; tasks are scored on the joints and, where the runtime adds meaning, on its state. Reference solution 7/7, no-op 0/7. The instrument files are CC BY-NC 4.0 (non-commercial use only), so the suite is not in the package: it runs from a checkout, after `robouse fetch-assets --chemlab` downloads the 493 pinned files (about 11 MB) into `~/.cache/robouse/chemlab` (`ROBOUSE_CHEMLAB_ASSETS`).
- `robouse doctor` says whether the chemlab instrument files are there.
- The `jev` harness: TypeSafe's Jev, a System One model that answers typed questions instead of writing text, drives the `nav` suite in the protocol of Dimensional's "Can Jev Nav?" study. Its client observes through `robo`, asks Jev four Choice questions per 0.5 s of simulated time (the three axes of the task's `drive` skill, and whether the task is finished) and executes the answers as the `drive` skill or `robo done`. Models `typesafe/jev-latest` (the default), `typesafe/jev-preview` or a version; the key in `TYPESAFE_API_KEY`. Every decision is a step of the trajectory, with the state Jev saw, its answers with their probabilities and confidence, the tokens and the cost. Run so far only against a local stand-in for TypeSafe's endpoint.
- Jev's prices in the price table: TypeSafe charges for input tokens only.
- `robouse doctor` checks the `jev` harness's key.
- The `gemini-cli` harness: Google's Gemini CLI, headless, on Gemini API models (default `gemini-4-argon`) with `GEMINI_API_KEY`. Each trial gets a Gemini CLI home of its own in its workspace; your settings, MCP servers, extensions and `~/.env` and the machine's system settings are not read. It is offered only its shell, file and search tools, with no web search or fetch, its shell commands run without credential variables, and its stream-json output becomes the trial's trajectory. It runs only Gemini API models and the `cli` interface.
- The `gemini` provider: Gemini API models through the model gateway with `GEMINI_API_KEY`, such as `gemini/gemini-4-argon` on Claude Code, mini-swe-agent and dimcode, through LiteLLM's own Gemini integration. The gateway keeps the signature Gemini puts on each tool call for harnesses that drop it (dimcode), counted as `signatures_restored` in `proxy_stats`.
- Model metadata (image input) and prices for `gemini/gemini-4-argon`, `openrouter/google/gemini-4-argon` and `openrouter/elorian/glimpse`.
- A price in the price table can change on a known date: Gemini 4 Argon's introductory price ($2 and $10 per million input and output tokens) applies through 2026-11-30, then $4 and $20.
- `robouse doctor` checks for Gemini CLI and `GEMINI_API_KEY`.
- The `kinex` harness: [Kinex](https://github.com/stacx-lab/kinex) 1.0.0, a robotics coding agent on the Pi SDK, headless (`kinex run`), with the robot connected as Kinex devices. A bridge in Robo Use serves them as RoboEnv does (its `roboenv/1` protocol, and the device profiles and drivers in the workspace's `.kinex/`), from inside the agent's sandbox as a client of the episode socket, so every device call becomes `robo` requests: the world clock, an arm whose joints are the hand's position, the gripper and the task's cameras, with camera calibration only where `robo info` gives it. The model goes through the trial's gateway (default `glm/glm-5.3`); each trial gets its own Kinex config and home, with Kinex's web search off.
- `robouse doctor` reports Kinex and its Python environment (`ROBOUSE_KINEX`, `ROBOUSE_KINEX_NODE`, `ROBOUSE_KINEX_VENV`).
- Trajectories of Kinex trials come from its Pi session, and each tool call gets the `robo` requests made while it ran.
- The `aspire` and `aspire-codex` harnesses: NVIDIA's ASPIRE (NVlabs/ASPIRE, Apache-2.0) run by Claude Code or Codex. The agent follows ASPIRE's own `iterative-debugging` or `evosearch` skill (commit `fa00f0e`, shipped unchanged) as the coordinator of a one-task campaign: it runs its programs with a `cap-harness` command on practice episodes, the task's own episode server on ASPIRE's development and unseen-check seeds, never the scored scene, and when it exits Robo Use runs the program it selected once on the scored episode. They run the `capx` and `capx-libero` suites and LIBERO tasks with several saved start states, such as the `libero-pro` suite's. They ran whole trials on `capx` tasks with Claude Code and a scripted stand-in model, and a pilot of five trials with Claude Code and `claude-opus-5-5` on three `capx` tasks and one `libero-pro` task.
- An opt-in skill library that persists across trials (`ROBOUSE_ASPIRE_LIBRARY`): each trial starts from it, what the trial's coordinator promoted goes back into it, and a task whose selected program it holds is evaluated on its other scenes without a new practice phase. A trial whose scored scene the library has practised on is refused.
- `config.json` records a harness's own settings (`harness_config`) and `result.json` what it did (`harness_record`).

### Changed

- The MakerMods Metal arm's kinematic chain is no longer in the package (`robouse/real/data/metal_chain.json`, shipped since 0.2.0): MakerMods' repository states no license. The first use of the Metal profile downloads the arm's URDF from MakerMods' repository at a pinned commit into `<cache>/real/`; every load checks the file against its SHA-256 (a changed or partial file is downloaded again) and builds the chain from it. The chain is the same arm (forward kinematics unchanged), without the gripper's joints, which no check used. Without network access, the error says where to put the URDF by hand.
- The trajectory names a skill request with its arguments (`robo skill drive forward none turn_left 0.5`), not `robo skill` alone.
- A harness can name paths its agent may neither read nor write, and the runner gives harness builders the trial's seed, split and agent time.
- Claude Code trials' token totals (the trajectory's `final_metrics`) come from Claude Code's own `modelUsage`, which counts the subagents it runs; before, they counted its main thread only.

### Fixed

- Through the model gateway to a provider reached over chat completions, an image in a Claude Code tool result reached the model as base64 text, and one in a dimcode tool result as an image in a tool message; both now move into a user message (`images_moved`).

## 0.5.0 (2026-10-20)

Day-one support for Dream Labs' Dream-1 (the `dream` harness and the `yam` suite on Dream's bimanual YAM station), agent isolation fixes, and changes for the open-source release of the repository.

### Security

- `robo` and `robo mcp` print help for `-h` or `--help` anywhere in the arguments and send nothing; `robo give-up --help` and `robo done --help` used to end the episode.
- Claude Code is offered only the Bash, Read, Write, Edit, Glob and Grep tools, plus the `robo` MCP tools with `--interface mcp` or `both`, instead of every tool but WebFetch, WebSearch and Task. Codex runs with its web search turned off.
- Each trial's Claude Code and Codex get a config folder of their own, removed when the trial ends (a Codex account pool keeps one folder per account).
- The sandbox, on macOS and Linux, denies credential and task-copy locations in the home folder: other programs' logins (`~/.ssh`, `~/.aws`, `~/.config/gh`, `~/.netrc` and others), your own Claude Code, Codex and mini-swe-agent settings, BenchFlow's settings and task cache, the uv and pip caches, and Robo Use's cache apart from the agent's own harness folder. On Linux a denied file is hidden too, not only a folder.
- The sandbox denies a source checkout's `tasks/`, `runs/` and `adapters/` folders, makes the runner's Python read-only, and refuses connections to other trials' episode sockets, to the Docker, Podman and LXD sockets and to the SSH agent. On macOS it refuses `open`, `osascript`, `shortcuts`, `security` and Apple events.
- No variable whose name marks a credential (such as `GITHUB_TOKEN`, `HF_TOKEN`, `AWS_SECRET_ACCESS_KEY` or `SSH_AUTH_SOCK`) reaches an agent; each harness adds back what its own program needs. The episode server and the verifier get no model provider key.
- The sandbox denies Dream Labs' credentials file (`~/.dreamlabs`), and no `DREAM_*` variable reaches an agent, the episode server or the verifier; the `dream` harness gives its client the key.

### Added

- The `yam` suite: 9 tasks on Dream Labs' bimanual YAM station, in Dream's own MuJoCo scene from the `dreamlabs` wheel (in a virtualenv of its own, since it needs MuJoCo 3.3.5 or later): the apple or the orange into the bowl, the banana onto the plate, each on Dream's layout and two shuffled ones. Agents see the joints and the three cameras, not the objects, and have `reach`, `set_gripper` and `home` skills. Reference solution 9/9, no-op 0/9.
- The `dream` harness: Dream Labs' Dream-1 (`dreamlabs/dream-1-beta`, `dreamlabs/dream-1-beta-flash`) through DreamAPI, with Dream's own client library and simulation loop. It runs the `yam` suite and stops at 0 steps on any other robot.
- `observe` takes `inline` (cameras, format, size, quality) and returns the camera frames encoded in the reply instead of writing image files, for policy clients that read every frame.
- `robouse doctor` checks the `yam` suite's virtualenv and the `dream` harness's client and key.

### Changed

- Credential pools are opt-in: `ROBOUSE_CLAUDE_TOKEN_FILE` (a file of Claude Code OAuth tokens) and `ROBOUSE_CODEX_AUTH_DIR` (a folder of Codex logins). Nothing is read from fixed maintainer locations any more, and no model provider's key is read from a file.
- Remote worker endpoints are read only from `~/.config/robouse/remote/<name>.json` or the file `ROBOUSE_<NAME>_REMOTE` names, never from a checkout's `runs/` folder, which agents can read.
- The local sandbox no longer denies fixed maintainer folders. List private folders in `ROBOUSE_SANDBOX_DENY`.
- The license expression is `Apache-2.0 AND MIT AND CC-BY-4.0`. NOTICE lists every third-party source of code, data and assets, and `licenses/` holds their license texts.
- The RoboHarm suite is described as a suite after Robocurve's RoboHarm, written independently, rather than a reproduction.
- Fixture metadata and docstrings no longer name local paths of the recording machine.

### Removed

- `[tool.uv.sources]`, which pinned BenchFlow to a branch that is not public, so `uv sync` and `uv run` work from a fresh clone.

### Documentation

- A README for a public audience, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY (how to report, and the sandbox's limits), MAINTAINERS, CITATION.cff, and issue and pull request templates.
- The isolation sections of Run agents and Supported, and four suite pages, say what the sandbox does not hide. The suites page lists suites with non-commercial or NVIDIA-licensed requirements.
- The CI workflow runs on pull requests from forks with a read-only token and no secrets, on Python 3.11 to 3.13, and scans the history for secrets with gitleaks.

## 0.4.1 (2026-10-14)

### Changed

- The default model of `mini-swe-agent` and `dimcode` is `glm/glm-5.3`: GLM-5.3 on the Z.ai Coding Plan through BenchFlow's `glm` provider, set up with `GLM_API_KEY` and `GLM_BASE_URL`. No provider key is loaded unless you set it.
- `ROBOUSE_PRICING` replaces the packaged price table for the spend cap. A model with no price runs only with `ROBOUSE_SPEND_CAP_USD=0` or a price you give.
- The legacy `claude-code-glm`, `codex-glm` and `mini-swe-agent-glm` harness names still read old trial folders, but a new run refuses them, and so does an explicit `baseten/` model id.
- `show-harness` and `robouse grade` have no default model: give `--model`. `show-harness` through the gateway needs a model the registry lists as reading images. The VLM grader needs its own endpoint and key (`ROBOUSE_GRADER_URL`, `ROBOUSE_GRADER_API_KEY`).
- `--resume` refuses a run folder of another harness or model.

### Fixed

- A trial in which every model request failed is an infrastructure failure, not a scored failure, so `--retries` and `--resume` rerun it.
- `mini-swe-agent` is found where `pip install mini-swe-agent` puts it, and named in the error when it is not installed.
- Provider errors say how many of the agent's requests failed and how many calls went to the provider.

### Security

- `GLM_*` and `ZAI_*` variables and the VLM grader's key are kept out of agent environments, like other provider keys. No Baseten key is read, from a file or the environment.

## 0.4.0 (2026-10-04)

### Added

- The `show-harness` harness: NUS Show Lab's Show-Harness, in which a vision-language model picks one action unit at a time and an interpreter moves the hand. It runs zero-shot through the model gateway, or against a model you serve at `ROBOUSE_SHOW_HARNESS_URL`.
- Real-robot safety: a loop watchdog and stale telemetry stop the episode, a contact watch, nothing moves on its own after a stop, parking only with a calibrated park watch, soft limits inside the mechanical stops, and a physical e-stop confirmed before arming. Verified on mocks and replays of recorded sessions, not on live hardware; the real-robot suite is not in the package.

### Security

- The model gateway's per-trial master key is no longer written to the trial folder.

## 0.3.1 (2026-10-01)

### Fixed

- Offscreen rendering: on Linux without a display, the error names the fix (install OSMesa or EGL and run `robouse doctor`); `MUJOCO_GL` is only an override.
- The backend smoke test runs each backend's check in a child interpreter where MuJoCo cannot render offscreen, so backends that render another way still pass.
- `robouse tasks check` says when the installed BenchFlow cannot read robouse task folders.

## 0.3.0 (2026-10-01)

### Added

- Provider-prefixed models (`provider/model`, from BenchFlow's provider registry) for every LLM harness, through a per-trial LiteLLM model gateway with a spend cap. Needs Python 3.12 or newer and the `llm` extra.
- The `robo mcp` front end (the `robo` operations as MCP tools) and the `dimcode` harness.
- The rle-bench, capx and capx-libero suites from RLE-Bench and CaP-X, published as hub datasets rather than bundled tasks. Their code is vendored under the MIT License (NOTICE).

### Changed

- The task is the `task.md` body, given to the agent as its prompt. Only `task.md` folders are read; older layouts get a message that names `bench tasks migrate`.
- The `benchflow` and `llm` extras pin the BenchFlow and LiteLLM builds this release was tested with.

## 0.2.0 (2026-10-01)

### Added

- 692 tasks in 31 suites in the package, each checked by the release gate: reference solution 1 and no-op control 0.
- Compose tasks from components with `robouse tasks init` (embodiment, scene and task template, with modifiers), and `robouse components`.
- The `vla` harness: one client for policies served over the openpi, OpenVLA, GR00T, XPolicyLab and HTTP-JSON protocols, with presets.
- `robouse doctor` (rendering, simulators and harnesses on this machine) and `robouse report`.
- Linux support for model harnesses under bubblewrap.

### Changed

- One package layout (`core`, `cli`, `runner`, `analysis`, backends and simulator workers) and a settings layer that declares every `ROBOUSE_*` variable.
- `result.json` records a status (completed, error or cancelled); Ctrl-C during `run-many` records running trials as cancelled, and `--resume` reruns them.

### Security

- The episode server signs its verdict with a per-trial key, and gets that key and the reference solution's token on its standard input instead of the environment.
- The macOS sandbox blocks TCP connections to localhost (except a harness's own proxy), any robouse source or install, and other trials' workspaces.

## 0.1.1 (2026-09-27)

### Changed

- Agent harnesses use your own credentials: `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` for Claude Code (default model `claude-sonnet-5`), `OPENAI_API_KEY` or an existing Codex login for Codex.
- MuJoCo is pinned to 3.3.0. The DexJoCo tasks are in the package.
- `config.json` in each trial records whether the sandbox was on.

## 0.1.0 (2026-09-27)

First release of the current package: the episode server, the `robo` command, the runner and harness launchers, tasks bundled in the wheel (`robouse tasks`), simulators as extras, and `robouse fetch-assets` for the MuJoCo Menagerie meshes.

Versions 0.0.1 (2026-09-21) and 0.0.2 (2026-09-26) were published before this repository's history begins.
