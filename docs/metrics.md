# Metrics

The episode server records the physical state at every control step in `episode/physics.jsonl` (end-effector or base position, simulation time, the largest contact force on the robot) and writes `metrics` into `episode/result.json` when the episode ends. Metrics never change the verdict.

## Episode metrics

| Metric | Definition |
|---|---|
| `success` | the verdict: 1 or 0 |
| `progress` | fraction of the task's stages reached in order; equal to `success` for tasks without stages |
| `execution_time_s` | control steps used × control period (solved episodes) |
| `execution_speed` | stages (or 1 task) completed per active minute (solved episodes) |
| `smoothness_sparc` | spectral arc length of the end-effector (or base) speed; at most 0, closer to 0 is smoother |
| `avg_jerk` | mean norm of the end-effector jerk after a 10 Hz low-pass, m/s³ |
| `path_length_m` | end-effector (or base) path length |
| `max_contact_force_n` | largest normal contact force on the robot (MuJoCo backends) |
| `safety_events`, `safe_failure` | falls, crashes, harm and stops; a failed episode with none is a safe failure |
| `excellent` | solved with no safety event and no vetoed motion |

Navigation tasks add `arrived`, `spl`, `soft_spl`, `collisions`, `time_to_target_s`, `path_ratio` and `excess_turning_rad_per_m`.

Each trial's `result.json` also has `cost`: prompt, completion and cached tokens from the trajectory, and US dollars from the harness (Claude Code) or from Robo Use's price table (override with `ROBOUSE_PRICING`).

## Splits

`--split` on `robouse run` and `run-many` moves the objects of the tabletop pick-and-place tasks to seeded placements, the same for every policy given the task, split and seed:

- `nominal`: the task's own placement, or one of four 2 cm diagonal shifts.
- `interpolation`: unseen placements inside that square.
- `extrapolation`: 3 to 6 cm from the task's own placement.

## Reports

`robouse report` aggregates run folders. To compare the four Meta-World reference solutions from [Run a suite or dataset](run-a-suite.md#a-suite) (`runs/mw-oracle`) with the no-op control on the same tasks:

```sh
robouse run-many --tasks "$(robouse tasks --path)/metaworld" --harness noop --out runs/mw-noop --concurrency 4 --limit 4
```

```console
$ robouse report runs/mw-oracle runs/mw-noop --metrics success,progress
| harness | model | n | success | progress |
|---|---|---|---|---|
| noop | none | 4 | 0.0 [0.0, 49.0] | 0.0 [0.0, 0.0] |
| oracle | scripted | 4 | 100.0 [51.0, 100.0] | 100.0 [100.0, 100.0] |

Proportions and progress in %; brackets are 95% intervals (Wilson for proportions, bootstrap for means).
```

Proportions and progress are in percent; brackets are 95% intervals (Wilson for proportions, bootstrap for means). Without `--metrics`, the table has the nine robot metrics and cost.

- `--by harness,model` (default) groups trials; other keys: `suite`, `category`, `difficulty`, `task`, `split`, `seed`, `mode` (sim, real or hil-mock), `run`, `regime`, `released`.
- When a task has several trials, pass@k is averaged over tasks.
- `--metrics` picks the columns, `--json FILE` writes everything, and `--cost-quality FILE` and `--svg FILE` write cost against solve rate.
- After `robouse flora import`, `flora_agree` is the share of trials where Flora's outcome score agrees with the simulator's verdict, and `flora_progress` the mean of Flora's progress estimate ([Annotate trials with Flora](flora.md)).
