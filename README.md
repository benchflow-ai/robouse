<p align="center">
  <a href="https://robouse.ai"><img src="https://robouse.ai/demo/robouse-hero.webp" width="100%" alt="Six agent runs that the simulator scored 1.0: Spot with its arm presses a reset button, a Unitree G1 stows soap in a drawer, a Shadow hand turns a valve wheel, a Franka Panda reaches four kitchen goals, two Pandas set chess pieces on a board, and two Pandas hand over a hammer"></a>
</p>

<h1 align="center">Robo Use</h1>

<p align="center">
  <strong>Agent as a policy for embodied agents.</strong><br>
  A coding agent drives a simulated robot from its shell, one <code>robo</code> command at a time,<br>
  and the simulator scores what physically happened.
</p>

<p align="center">
  <a href="https://pypi.org/project/robouse/"><img src="https://img.shields.io/pypi/v/robouse?color=3552f2" alt="PyPI version"></a>
  <a href="https://pypi.org/project/robouse/"><img src="https://img.shields.io/pypi/pyversions/robouse?color=3552f2" alt="Python 3.11 to 3.13"></a>
  <a href="https://github.com/benchflow-ai/robouse/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-3552f2" alt="Apache License 2.0"></a>
  <a href="https://robouse.ai/docs/"><img src="https://img.shields.io/badge/docs-robouse.ai-3552f2" alt="Documentation"></a>
  <a href="https://discord.gg/mZ9Rc8q8W3"><img src="https://img.shields.io/badge/chat-Discord-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://robouse.ai/docs/quickstart/">Quickstart</a> ·
  <a href="https://robouse.ai/docs/">Docs</a> ·
  <a href="https://robouse.ai/docs/suites/">Suites</a> ·
  <a href="https://robouse.ai/docs/run-agents/">Agents and VLAs</a> ·
  <a href="https://robouse.ai/runs/">Published runs</a> ·
  <a href="https://github.com/benchflow-ai/robouse/blob/main/CHANGELOG.md">Changelog</a>
</p>

Robo Use turns robot benchmarks into tasks for coding agents. The agent gets the task as its prompt, a fresh workspace and a robot it can reach only through the `robo` command. An episode server owns the simulator: it applies each action, counts every step against the task's budget, records the video and, after `robo done`, judges the final physical state. What the agent says it did does not count.

- **814 tasks in 35 suites** ship in the package: rule puzzles on a table, Meta-World, LIBERO and LIBERO-PRO, robosuite, RoboCasa, Gymnasium-Robotics, dm_control, MyoSuite, HumanoidBench, and mobile manipulators, quadrupeds, humanoids, dexterous hands and drones built on MuJoCo Menagerie robots.
- **Any program that runs shell commands can be the policy.** Harnesses ship for Claude Code, Codex, Gemini CLI, mini-swe-agent, dimcode, Kinex, Show-Harness and NVIDIA's ASPIRE, with clients for VLA policies, Dream Labs' Dream-1 and TypeSafe's Jev.
- **Every task is checked both ways:** its reference solution scores 1 and a no-op control scores 0.
- **Every trial is a folder** with the video, the agent's trajectory, every `robo` request with its response, and the reward. The server signs its verdict with a key the agent never sees.

Status: alpha. Interfaces can change between minor versions.

## Quickstart

Python 3.11 to 3.13, on macOS (Apple silicon) or Linux:

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install 'robouse[sim]'
robouse doctor
```

`robouse doctor` checks that MuJoCo can render offscreen and lists the simulators and harnesses this machine can run. On Linux without a display, it says what to install (usually `sudo apt-get install -y libosmesa6`).

Run a task's reference solution. It needs no model, no account and no API key, and takes about a minute:

```console
$ robouse run --task arc-gravity --harness oracle --out runs/quickstart
{
  "trial": "arc-gravity__oracle__8d1bb0",
  "reward": 1.0,
  "outcome": "done",
  "steps": 999,
  "wall_s": 20.0,
  "exception": null
}
```

In `arc-gravity` the agent sees example grids of blocks before and after a rule is applied, works out the rule (blocks fall toward the front, like gravity) and moves the real blocks with a gripper. `--harness noop` runs the no-op control, which ends the episode without moving and scores 0.

### Put an agent in charge

With [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on your `PATH` and a token from `claude setup-token` (or an Anthropic API key in `ANTHROPIC_API_KEY`):

```sh
export CLAUDE_CODE_OAUTH_TOKEN=...
robouse run --task arc-gravity --harness claude-code --out runs/quickstart
```

The agent reads the task, looks with `robo observe`, moves with `robo move-to` and ends with `robo done`. Model trials use your own provider quota or credits.

## How a trial runs

```text
  agent: Claude Code, Codex, Gemini CLI, a VLA client, ...
     │   robo observe · robo act · robo move-to · robo skill · robo done
     ▼
  episode server ◄────► simulator: MuJoCo, robosuite, LIBERO, ...
     │   holds the robot still for about 10 steps, judges the final state, signs the verdict
     ▼
  runs/<trial>/   the video, the trajectory, every request, the verdict and the reward
```

| In the trial folder | What it holds |
|---|---|
| `artifacts/recording.mp4` | the video |
| `agent/trajectory.json` | the agent's trajectory |
| `episode/trace.jsonl` | every `robo` request with its response |
| `episode/result.json` | the server's verdict |
| `verifier/reward.txt` | the reward |

## Harnesses

| `--harness` | What runs | Needs |
|---|---|---|
| `claude-code` | Claude Code | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` |
| `codex` | Codex | `OPENAI_API_KEY` or a `codex login` |
| `gemini-cli` | Gemini CLI, with Gemini 4 Argon by default | `GEMINI_API_KEY` |
| `mini-swe-agent`, `dimcode` | mini-swe-agent; Dimensional's dimcode | the model provider's settings |
| `kinex` | Kinex, with the robot connected as Kinex devices | Kinex 1.0.0, Node 22.19 or newer |
| `show-harness` | NUS Show Lab's Show-Harness | a model that reads images |
| `aspire`, `aspire-codex` | NVIDIA's ASPIRE workflow, run by Claude Code or Codex | the `capx` suites |
| `jev` | TypeSafe's Jev: typed decisions over each observation | `TYPESAFE_API_KEY`, the `nav` suite |
| `dream` | Dream Labs' Dream-1 | `DREAM_API_KEY`, the `yam` suite |
| `vla`, `molmoact2` | VLA policies served elsewhere | the policy server's URL |

Models from other providers (`--model provider/model`, such as `glm/glm-5.3`, `gemini/gemini-4-argon` or `openrouter/elorian/glimpse`) go through a per-trial model gateway with a spend cap. It needs Python 3.12 or newer and `pip install 'robouse[llm]'`. [Run agents and VLAs](https://robouse.ai/docs/run-agents/) covers every harness and model.

## New in 0.6.1

- **NVIDIA's Flora** on trial recordings: `robouse flora export` writes the input files of NVIDIA's Flora scripts for finished trials, and `robouse flora import` reads back an outcome score, a label for every half second and captions ([Annotate trials with Flora](https://robouse.ai/docs/flora/)). The models are under NVIDIA's license and run on your own GPU machine; Robo Use neither includes nor downloads them.
- **Kinex's install is read-only to the agent**, and Kinex's Python keeps its bytecode in the trial's own folder, so no trial can leave code that a later trial runs.

## New in 0.6.0

- **NVIDIA's [ASPIRE](https://research.nvidia.com/labs/gear/aspire/)** as a harness. The agent practises on other seeds of its task and keeps verified skills in a library. Then one frozen program runs on the scored episode, which stays locked until then.
- **libero-pro** (73 tasks): LIBERO-PRO's position-swap and new-goal tasks. The agent gets camera images, not object positions.
- **one-demo** (16 tasks): one demonstration of a skill on one object, then the same skill on a different object. Replaying the demonstration scores 0.
- **chemlab** (7 tasks, run from a checkout): six laboratory instruments from MBZUAI's ChemLab-Assets.
- Harnesses for **Gemini CLI**, **Kinex** and TypeSafe's **Jev**, and **Gemini 4 Argon** and Elorian's **Glimpse** as models.
- Fixes that stop an agent from changing its own score or a later trial's.

The [CHANGELOG](https://github.com/benchflow-ai/robouse/blob/main/CHANGELOG.md) has the full list.

## Isolation, and its limits

`robouse run` starts model harnesses under the operating system's sandbox: Seatbelt on macOS, bubblewrap on Linux. It hides the run folder, the task folder, the installed package, and the logins and package caches in your home folder from the agent. But it is a deny list, not a container. The agent runs as your user, can read the rest of your home folder and reach the internet, and public copies of every task, reference solutions included, exist online. Run agents you do not trust in a disposable VM or container, and read [SECURITY.md](https://github.com/benchflow-ai/robouse/blob/main/SECURITY.md) before you publish scores.

## Documentation

- [Quickstart](https://robouse.ai/docs/quickstart/), [Concepts](https://robouse.ai/docs/concepts/) and [what is supported](https://robouse.ai/docs/supported/)
- [Suites](https://robouse.ai/docs/suites/): every suite, and what it needs beyond the install
- [Run agents and VLAs](https://robouse.ai/docs/run-agents/), and [run a suite or dataset](https://robouse.ai/docs/run-a-suite/) with BenchFlow's `bench`
- [Write or compose a task](https://robouse.ai/docs/write-a-task/) and the [task.md reference](https://robouse.ai/docs/task-format/)
- [Published runs](https://robouse.ai/runs/)

## Community

- Questions and discussion: the BenchFlow [Discord](https://discord.gg/mZ9Rc8q8W3).
- Bugs, task issues and feature requests: [GitHub issues](https://github.com/benchflow-ai/robouse/issues).
- Contributing: [CONTRIBUTING.md](https://github.com/benchflow-ai/robouse/blob/main/CONTRIBUTING.md). Everyone taking part follows the [Code of Conduct](https://github.com/benchflow-ai/robouse/blob/main/CODE_OF_CONDUCT.md).
- Security issues: please report them privately, as [SECURITY.md](https://github.com/benchflow-ai/robouse/blob/main/SECURITY.md) describes, not in a public issue.

## Citing

If you use Robo Use in research, please cite it with the metadata in [CITATION.cff](https://github.com/benchflow-ai/robouse/blob/main/CITATION.cff) (GitHub's "Cite this repository" button gives BibTeX), and cite the benchmarks your tasks come from; each suite's page names its source.

## License

Robo Use is licensed under the [Apache License 2.0](https://github.com/benchflow-ai/robouse/blob/main/LICENSE). It includes third-party code and task data under their own licenses: MIT (the vendored CaP-X, PyRoKi and RLE-Bench code, LIBERO instructions, DexJoCo demonstrations and others) and CC BY 4.0 (the Adroit demonstrations from D4RL). [NOTICE](https://github.com/benchflow-ai/robouse/blob/main/NOTICE) lists every source, its license and the files. Robot models and benchmark assets that Robo Use downloads at run time keep their upstream licenses. Some suites outside the package need non-commercial or NVIDIA-licensed software or data to run, and the `llm` extra installs a proprietary LiteLLM component; [Suites](https://robouse.ai/docs/suites/#licences) has the details.

<p align="center"><sub>Made by <a href="https://benchflow.ai">BenchFlow</a>.</sub></p>
