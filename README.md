# Robo Use

**Agent as a policy for embodied agents.** Robo Use turns robot benchmarks into tasks that a coding agent, such as Claude Code or Codex, solves by driving a simulated robot from its shell, one `robo` command at a time. An episode server owns the simulator, enforces the step budget, records a video and scores the final physical state; the agent acts only by sending `robo` requests to that server.

- 814 tasks in 35 suites ship in the package: rule puzzles on a table, Meta-World, LIBERO, robosuite, RoboCasa, Gymnasium-Robotics, dm_control, MyoSuite, HumanoidBench, quadrupeds, humanoids, drones and more.
- Harnesses for Claude Code, Codex, Gemini CLI, mini-swe-agent, dimcode, Kinex and Show-Harness, NVIDIA's ASPIRE workflow run by Claude Code or Codex, and a client for vision-language-action (VLA) policies served elsewhere.
- Every task is a BenchFlow task folder (`task.md`) with a reference solution that scores 1 and a no-op control that scores 0. Every trial is a folder with the video, the agent's trajectory and the reward.

Status: alpha. Interfaces can change between minor versions; see [CHANGELOG.md](https://github.com/benchflow-ai/robouse/blob/main/CHANGELOG.md).

## Install

Python 3.11 to 3.13, on macOS (Apple silicon) or Linux (tested on arm64):

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install 'robouse[sim]'
```

Other simulators are extras, for example `robouse[metaworld]`; [Suites](https://robouse.ai/docs/suites/) says which task needs which. Models from other providers (`--model provider/model`) go through a per-trial model gateway, which needs Python 3.12 or newer and the `llm` extra.

## Quickstart (about a minute, no account needed)

Check that MuJoCo can render offscreen. On Linux without a display, install OSMesa first if `robouse doctor` says it cannot (`sudo apt-get install -y libosmesa6`).

```sh
robouse doctor
```

Run the task's reference solution, a script that needs no model and no API key:

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

In `arc-gravity` the agent sees example grids of blocks before and after a rule is applied, works out the rule (blocks fall toward the front, like gravity) and moves the real blocks with a gripper. Every task also has a no-op control, which ends the episode without moving and must score 0:

```sh
robouse run --task arc-gravity --harness noop --out runs/quickstart
```

Each run writes a trial folder under `runs/quickstart/`:

- `artifacts/recording.mp4`: the video.
- `verifier/reward.txt`: the reward.
- `episode/result.json` and `episode/trace.jsonl`: the verdict and every `robo` request with its response.

## Put an agent in charge

With [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on your `PATH` and a token from `claude setup-token` (or an Anthropic API key in `ANTHROPIC_API_KEY`):

```sh
export CLAUDE_CODE_OAUTH_TOKEN=...
robouse run --task arc-gravity --harness claude-code --out runs/quickstart
```

The agent reads the task, observes the scene with `robo observe`, moves with `robo move-to` and ends with `robo done`. Model trials use your provider quota or credits. `mini-swe-agent`, `dimcode` and `kinex` default to GLM-5.3 on the Z.ai Coding Plan (`glm/glm-5.3`, with `GLM_API_KEY` and `GLM_BASE_URL` set). Other harnesses, models and VLA policies: [Run agents and VLAs](https://robouse.ai/docs/run-agents/).

## Isolation, and its limits

`robouse run` starts model harnesses under the operating system's sandbox (Seatbelt on macOS, bubblewrap on Linux). The sandbox hides the run folder, the task folder, the installed package, and credential and task-copy locations in your home folder (logins, package caches) from the agent, and the agent's environment carries no credential variables other than the harness's own login or gateway key. But it is a deny list, not a container: the agent runs as your user, can read the rest of your home folder and reach the internet, and public copies of every task, including reference solutions, exist online. Treat it as a guard against accidents, not as a security boundary. Run agents you do not trust in a disposable VM or container, and read [SECURITY.md](https://github.com/benchflow-ai/robouse/blob/main/SECURITY.md) before you publish scores.

## Documentation

- [Quickstart](https://robouse.ai/docs/quickstart/) and [Concepts](https://robouse.ai/docs/concepts/)
- [Write or compose a task](https://robouse.ai/docs/write-a-task/) and the [task.md reference](https://robouse.ai/docs/task-format/)
- [Run a suite or dataset](https://robouse.ai/docs/run-a-suite/) with BenchFlow's `bench`
- [Datasets and tasks](https://robouse.ai/hub/) and [published runs](https://robouse.ai/runs/)

## Community

- Questions and discussion: the BenchFlow [Discord](https://discord.gg/mZ9Rc8q8W3).
- Bugs, task issues and feature requests: [GitHub issues](https://github.com/benchflow-ai/robouse/issues).
- Contributing: [CONTRIBUTING.md](https://github.com/benchflow-ai/robouse/blob/main/CONTRIBUTING.md). Everyone taking part follows the [Code of Conduct](https://github.com/benchflow-ai/robouse/blob/main/CODE_OF_CONDUCT.md).
- Security issues: please report them privately, as [SECURITY.md](https://github.com/benchflow-ai/robouse/blob/main/SECURITY.md) describes, not in a public issue.

## Citing

If you use Robo Use in research, please cite it with the metadata in [CITATION.cff](https://github.com/benchflow-ai/robouse/blob/main/CITATION.cff) (GitHub's "Cite this repository" button gives BibTeX), and cite the benchmarks your tasks come from; each suite's page names its source.

## License

Robo Use is licensed under the [Apache License 2.0](https://github.com/benchflow-ai/robouse/blob/main/LICENSE). It includes third-party code and task data under their own licenses: MIT (the vendored CaP-X, PyRoKi and RLE-Bench code, LIBERO instructions, DexJoCo demonstrations and others) and CC BY 4.0 (the Adroit demonstrations from D4RL). [NOTICE](https://github.com/benchflow-ai/robouse/blob/main/NOTICE) lists every source, its license and the files. Robot models and benchmark assets that Robo Use downloads at run time keep their upstream licenses. Some suites outside the package need non-commercial or NVIDIA-licensed software or data to run, and the `llm` extra installs a proprietary LiteLLM component; [Suites](https://robouse.ai/docs/suites/#licences) has the details.
