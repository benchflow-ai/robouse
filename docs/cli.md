# CLIs

`robouse` runs tasks, trials and runs; `robo` is the agent's only way to act. The help below is the output of `robouse 0.6.1`.

```console
$ robouse --help
usage: robouse [-h] [--version] COMMAND ...

Robo Use: run robot tasks with an agent harness as the policy.
https://robouse.ai

options:
  -h, --help      show this help message and exit
  --version       show program's version number and exit

commands:
  COMMAND
    run           run one trial end to end
    run-many      run a set of trials
    tasks         list, create and check tasks
    components    list, show and check components
    fetch-assets  download the MuJoCo Menagerie robot models (menagerie,
                  roboharm, drone; --robot or --all for the embodiment suites
                  and composed tasks; --chemlab for the chemlab suite's
                  instruments; --embodied-playground for that suite's
                  simulation package)
    report        metrics with 95% confidence intervals over run folders,
                  grouped by trial attributes
    flora         score and caption trial recordings with NVIDIA's Flora
                  models: export their input, import their results
    summarize     distil a trial into learnings (markdown) for --prior-
                  learnings
    doctor        what this machine can run: simulators, harnesses,
                  credentials and the VLA server
```

## `robouse run`

```console
$ robouse run --help
usage: robouse run [-h] --task TASK --out OUT --harness HARNESS
                   [--model MODEL] [--interface {cli,mcp,both}]
                   [--timeout TIMEOUT] [--record-size WxH] [--seed SEED]
                   [--split SPLIT] [--extra-instruction EXTRA_INSTRUCTION]
                   [--prior-learnings PRIOR_LEARNINGS]

options:
  -h, --help            show this help message and exit
  --task TASK           task folder or bundled task id
  --out OUT             run folder; the trial is written to
                        OUT/<task>__<harness>__<id>/
  --harness HARNESS, --agent HARNESS
                        harness: oracle, noop, claude-code, codex, gemini-cli,
                        mini-swe-agent, dimcode, kinex, show-harness,
                        molmoact2, vla, dream, jev, aspire or aspire-codex;
                        --model takes a provider-prefixed id such as
                        glm/glm-5.3 (https://robouse.ai/docs/harnesses/)
  --model MODEL         model for the harness (default: the harness's)
  --interface {cli,mcp,both}
                        what the agent drives the robot with: the robo CLI,
                        the robo MCP tools, or both (default: the task's
                        robouse.interface, else cli)
  --timeout TIMEOUT     agent wall-clock limit in seconds (default: the task's
                        agent.timeout_sec)
  --record-size WxH     render the episode video at this size, e.g. 1280x720;
                        agent images are unchanged (default: the backend's
                        native size, or $ROBOUSE_RECORD_SIZE)
  --seed SEED           override the task's seed
  --split SPLIT         placement split: nominal, interpolation or
                        extrapolation (tasks with seeded placements)
  --extra-instruction EXTRA_INSTRUCTION
                        text appended to the task instruction (recorded in
                        config.json)
  --prior-learnings PRIOR_LEARNINGS
                        markdown notes (e.g. from `robouse summarize`)
                        appended to the instruction
```

Prints a JSON summary: `trial`, `reward`, `outcome`, `steps`, `wall_s`, `exception`. A non-null `exception` means the trial did not run to a result (an infrastructure failure: a missing credential, a harness error before the episode ended, every request to the model failing, as at a provider's usage limit, or Ctrl-C); it is not scored and the command exits 1.

## `robouse run-many`

```console
$ robouse run-many --help
usage: robouse run-many [-h] [--tasks TASKS] --out OUT [--filter FILTER]
                        [--task-list TASK_LIST] [--include INCLUDE]
                        [--exclude EXCLUDE] [--sample SAMPLE]
                        [--sample-seed SAMPLE_SEED] [--limit LIMIT]
                        [--seeds SEEDS] [--epochs EPOCHS]
                        [--concurrency CONCURRENCY] [--retries RETRIES]
                        [--resume] [--dry-run] --harness HARNESS
                        [--model MODEL] [--interface {cli,mcp,both}]
                        [--timeout TIMEOUT] [--record-size WxH] [--seed SEED]
                        [--split SPLIT]
                        [--extra-instruction EXTRA_INSTRUCTION]
                        [--prior-learnings PRIOR_LEARNINGS]

options:
  -h, --help            show this help message and exit
  --tasks TASKS         task root (default: the bundled tasks)
  --out OUT             run folder; one trial folder per task
  --filter FILTER       only task ids containing this substring
  --task-list TASK_LIST
                        file with one task id per line (a subset of --tasks)
  --include INCLUDE     only task ids matching this glob (repeatable), e.g.
                        'libero-10-*'
  --exclude EXCLUDE     skip task ids matching this glob (repeatable)
  --sample SAMPLE       run a seeded random sample of N tasks
  --sample-seed SAMPLE_SEED
                        seed for --sample (default 0)
  --limit LIMIT         run at most this many tasks (default 0: all)
  --seeds SEEDS         episode seeds per task, e.g. 0-4 or 0,3,7: one trial
                        per task and seed, for pass@k (default: the task's own
                        seed)
  --epochs EPOCHS       repeat each task and seed N times (default 1)
  --concurrency CONCURRENCY
                        trials run in parallel (default 1)
  --retries RETRIES     rerun a trial up to N times after an infrastructure
                        failure, with backoff; the failed trial is kept in
                        OUT/_infra_failed (default 0)
  --resume              skip tasks that have a finished trial in --out that
                        did not fail on infrastructure (refused when --out
                        holds trials of another harness or model)
  --dry-run             print the resolved trial plan and exit
  --harness HARNESS, --agent HARNESS
                        harness: oracle, noop, claude-code, codex, gemini-cli,
                        mini-swe-agent, dimcode, kinex, show-harness,
                        molmoact2, vla, dream, jev, aspire or aspire-codex;
                        --model takes a provider-prefixed id such as
                        glm/glm-5.3 (https://robouse.ai/docs/harnesses/)
  --model MODEL         model for the harness (default: the harness's)
  --interface {cli,mcp,both}
                        what the agent drives the robot with: the robo CLI,
                        the robo MCP tools, or both (default: each task's
                        robouse.interface, else cli)
  --timeout TIMEOUT     agent wall-clock limit in seconds (default: each
                        task's)
  --record-size WxH     render the episode video at this size, e.g. 1280x720;
                        agent images are unchanged (default: the backend's
                        native size, or $ROBOUSE_RECORD_SIZE)
  --seed SEED           override every task's seed
  --split SPLIT         placement split: nominal, interpolation or
                        extrapolation (tasks with seeded placements)
  --extra-instruction EXTRA_INSTRUCTION
                        text appended to the task instruction (recorded in
                        config.json)
  --prior-learnings PRIOR_LEARNINGS
                        markdown notes (e.g. from `robouse summarize`)
                        appended to the instruction
```

Prints one line per finished trial, appends it to `OUT/run_log.jsonl`, and ends with the number solved; exits 1 if any trial failed on infrastructure. Examples: [Run a suite or dataset](run-a-suite.md).

## `robouse tasks`

```console
$ robouse tasks --help
usage: robouse tasks [-h] {list,init,check} ...

list, create and check tasks

positional arguments:
  {list,init,check}
    list             list tasks (default: the bundled tasks)
    init             compose a task from components, regenerate one, or
                     scaffold a blank task
    check            validate a task: schema, `bench tasks check`, reference
                     solution 1, no-op control 0

options:
  -h, --help         show this help message and exit
```

`robouse tasks` alone lists the tasks: id, backend and simulator env id. `tasks init` composes a task from components and keeps it only if the reference solution scores 1 and the no-op control 0; with only `DIR` it scaffolds a blank task folder. `tasks check` re-runs those checks on any task folder ([Write or compose a task](write-a-task.md)).

### `robouse tasks list`

```console
$ robouse tasks list --help
usage: robouse tasks list [-h] [--path] [ROOT]

positional arguments:
  ROOT        task root (default: the bundled tasks)

options:
  -h, --help  show this help message and exit
  --path      print the bundled task directory and exit
```

### `robouse tasks init`

```console
$ robouse tasks init --help
usage: robouse tasks init [-h] [--embodiment ID] [--scene ID] [--task ID]
                          [--obs MODE] [--budget BUDGET] [--perturb KIND]
                          [--safety LEVEL] [--roles ROLES] [--seed N]
                          [--out DIR] [--grid] [--from DIR] [--upgrade]
                          [--no-validate] [--keep-trials DIR]
                          [DIR]

compose a task from components and validate it (--embodiment, --scene,
--task), regenerate a composed task from its recorded instance (--from), or
scaffold a blank task (DIR)

positional arguments:
  DIR                   blank task folder to create (scaffold mode)

options:
  -h, --help            show this help message and exit
  --embodiment ID       embodiment component id (robouse components list)
  --scene ID            scene component id
  --task ID             task component id
  --obs MODE            observation mode: state (default), vision or noisy
  --budget BUDGET       step budget: normal (default), loose or tight
  --perturb KIND        perturbation: none (default), push, dynamics or
                        clutter
  --safety LEVEL        safety overlay: none (default), direct, indirect or
                        privacy
  --roles ROLES         roles: single (default) or planner-operator
  --seed N              instance seed (default 0)
  --out DIR             folder to write the composed task folder(s) into
  --grid                comma-separated values in any flag: compose every
                        compatible combination
  --from DIR            regenerate the composed task in this folder from its
                        recorded instance
  --upgrade             with --from: use the installed component versions if
                        they differ
  --no-validate         write without running the reference solution and the
                        no-op control
  --keep-trials DIR, --keep-runs DIR
                        keep the validation trials in this folder
```

### `robouse tasks check`

```console
$ robouse tasks check --help
usage: robouse tasks check [-h] [--level LEVEL] [--no-run] [--keep-trials DIR]
                           DIR

positional arguments:
  DIR                   task folder

options:
  -h, --help            show this help message and exit
  --level LEVEL         `bench tasks check` level (default structural)
  --no-run              skip the reference solution and no-op control trials
  --keep-trials DIR, --keep-runs DIR
                        keep the trials in this folder
```

## `robouse components`

```console
$ robouse components --help
usage: robouse components [-h] {list,show,check} ...

the embodiments, scenes, task templates and modifiers composed tasks are built
from

positional arguments:
  {list,show,check}
    list             list components
    show             print one component's manifest
    check            whether an embodiment, a scene and a task template fit
                     together, and why not

options:
  -h, --help         show this help message and exit
```

### `robouse components list`

```console
$ robouse components list --help
usage: robouse components list [-h] [--all]
                               [{embodiments,scenes,tasks,modifiers}]

positional arguments:
  {embodiments,scenes,tasks,modifiers}
                        only this kind

options:
  -h, --help            show this help message and exit
  --all                 also list fixed components (the existing suites'
                        robots and scenes)
```

### `robouse components show`

```console
$ robouse components show --help
usage: robouse components show [-h] [--compatible] ID

positional arguments:
  ID            component id

options:
  -h, --help    show this help message and exit
  --compatible  also list the combinations it composes into
```

### `robouse components check`

```console
$ robouse components check --help
usage: robouse components check [-h] [--obs MODE] [--budget BUDGET]
                                [--perturb KIND] [--safety LEVEL]
                                [--roles ROLES] [--seed N] [--json]
                                EMBODIMENT SCENE TASK

positional arguments:
  EMBODIMENT       embodiment component id
  SCENE            scene component id
  TASK             task component id

options:
  -h, --help       show this help message and exit
  --obs MODE       observation mode: state (default), vision or noisy
  --budget BUDGET  step budget: normal (default), loose or tight
  --perturb KIND   perturbation: none (default), push, dynamics or clutter
  --safety LEVEL   safety overlay: none (default), direct, indirect or privacy
  --roles ROLES    roles: single (default) or planner-operator
  --seed N         instance seed to lay out (default 0)
  --json           print the report as JSON
```

## `robouse fetch-assets`

```console
$ robouse fetch-assets --help
usage: robouse fetch-assets [-h] [--dest DEST] [--robot ROBOT] [--all]
                            [--chemlab] [--embodied-playground]

options:
  -h, --help            show this help message and exit
  --dest DEST           target folder (default: <cache>/menagerie, or
                        $ROBOUSE_MENAGERIE_ASSETS; with --chemlab,
                        <cache>/chemlab, or $ROBOUSE_CHEMLAB_ASSETS; with
                        --embodied-playground, <cache>/embodied-playground, or
                        $ROBOUSE_EMBODIED_PLAYGROUND_SOURCE)
  --robot ROBOT         only this Menagerie robot folder (repeatable), e.g.
                        unitree_go2
  --all                 every robot the bundled suites use (about 400 MB)
  --chemlab             instead, the ChemLab-Assets instrument files the
                        chemlab suite uses (about 11 MB; models, contracts and
                        data under CC BY-NC 4.0, for non-commercial use only)
  --embodied-playground
                        instead, Embodied Playground's MuJoCo package, which
                        the embodied-playground suite runs on (about 35 MB;
                        code Apache-2.0, its own non-code assets CC BY 4.0,
                        the Panda model Apache-2.0)
```

## `robouse report`

```console
$ robouse report --help
usage: robouse report [-h] [--by BY] [--metrics METRICS] [--json JSON]
                      [--cost-quality COST_QUALITY] [--svg SVG]
                      runs [runs ...]

positional arguments:
  runs                  run folders (run-many --out)

options:
  -h, --help            show this help message and exit
  --by BY               group keys, comma-separated (repeatable): harness,
                        model, suite, category, difficulty, task, split, seed,
                        mode, run, regime, released (default harness,model)
  --metrics METRICS     metrics to show, comma-separated (default: the nine
                        robot metrics and cost)
  --json JSON           write the full report as JSON
  --cost-quality COST_QUALITY
                        write cost-versus-success points (JSON) for groups
                        with a known cost
  --svg SVG             write a cost-versus-success scatter (SVG)
```

## `robouse flora`

```console
$ robouse flora --help
usage: robouse flora [-h] ACTION ...

NVIDIA's Flora models label a trial's recording: an outcome score, a quality
label for every half second and timestamped captions. Their weights and
scripts are not part of Robo Use (NVIDIA's non-commercial license) and run on
a GPU machine: `export` writes their input files, `import` reads their results
into the trial folders. https://robouse.ai/docs/flora/

positional arguments:
  ACTION
    export    write the input files of NVIDIA's Flora scripts for finished
              trials
    import    write Flora's results into the trial folders (grader/flora.json)
              and compare its outcome scores with the simulator's verdicts

options:
  -h, --help  show this help message and exit
```

### `robouse flora export`

```console
$ robouse flora export --help
usage: robouse flora export [-h] --out OUT
                            [--caption-profile {human,yam,dex,tianji}]
                            [--instruction INSTRUCTION | --instructions FILE]
                            trials [trials ...]

positional arguments:
  trials                trial folders or run folders

options:
  -h, --help            show this help message and exit
  --out OUT             a new folder for the job files and copies (hard links)
                        of the recordings
  --caption-profile {human,yam,dex,tianji}
                        the captioning pipeline's profile (default yam, its
                        robot-actions profile; dex for dexterous hands)
  --instruction INSTRUCTION
                        the task instruction Flora is given, for every trial
                        (default: each task's own: the source benchmark's
                        language instruction, else the task's one-line
                        description)
  --instructions FILE   a JSON file of task ids and the instruction Flora is
                        given for each (the other tasks get their own)
```

### `robouse flora import`

```console
$ robouse flora import --help
usage: robouse flora import [-h] [--success-score N] folder

positional arguments:
  folder             the export folder, with NVIDIA's output files in its
                     results/ folder

options:
  -h, --help         show this help message and exit
  --success-score N  the lowest outcome score (1-5) that counts as Flora
                     calling the task solved (default 5, complete success)
```

## `robouse summarize`

```console
$ robouse summarize --help
usage: robouse summarize [-h] [-o OUT] trial

positional arguments:
  trial              trial folder (OUT/<task>__<harness>__<id>)

options:
  -h, --help         show this help message and exit
  -o OUT, --out OUT  output file (default: <trial>/learnings.md; - for stdout)
```

## `robouse doctor`

```console
$ robouse doctor --help
usage: robouse doctor [-h]

options:
  -h, --help  show this help message and exit
```

## `robo`

```console
$ robo help
`robo`: the only way an agent touches the robot. Standard library only.

Finds the episode socket from $ROBOUSE_SOCKET (set by the runner; $ROBO_SOCKET on BenchFlow) and sends one JSON
request.

  robo info                          action space, skills, step budget
  robo observe [--image] [--camera C] robot and object state; --image also saves a camera PNG and prints its path
  robo act A1 A2 ... [--repeat N]    apply one low-level action N times (N <= 50)
  robo move-to X Y Z [--grip G]      move the hand toward a point (skill; may be disabled per task)
  robo grip G [--steps N]            hold position and set the gripper (+1 close, -1 open)
  robo skill NAME [ARG ...]          run a named high-level skill listed by `robo info` (only some tasks have them)
  robo done ["message"]              end the episode and ask for scoring
  robo give-up ["message"]           end the episode without claiming success
  robo mcp [--http [HOST:]PORT]      serve these operations as MCP tools (stdio; --http: streamable HTTP)
Add --json to any command for raw JSON output. -h or --help anywhere prints this help and sends nothing.
```

Each call sends one JSON object to the episode server at `$ROBOUSE_SOCKET` and prints the response, for example `{"op": "act", "action": [0, 0, -1, 1], "repeat": 5}` and `{"ok": true, "result": {...}}`. The commands map to the operations `info`, `observe`, `act`, `move_to`, `grip`, `skill`, `done` and `give_up`. `robo info` also describes the robot's embodiment: its action groups, skills, cameras and budgets. Skills run on the server, and each simulated step they take counts against the budget. Without an episode, `robo` prints an error and exits 1.
