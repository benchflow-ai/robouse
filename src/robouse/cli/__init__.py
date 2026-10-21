"""`robouse`: the trusted-side commands.

  robouse run --task TASK --harness NAME [--model M] --out JOBDIR          run one trial end to end
  robouse run-many [--tasks ROOT] --harness NAME ... --out JOBDIR         run a set of trials
  robouse tasks [list|init|check] ...                                     list, create and check tasks
  robouse components list|show|check ...                                  the component registry
  robouse fetch-assets [--robot NAME | --all | --chemlab]                 download robot models or instrument files
  robouse report | summarize | doctor                                     results, learnings, what this machine can run
  robouse flora export RUNS... --out DIR | flora import DIR               NVIDIA's Flora models on trial recordings

`run` and `run-many` run on this machine (the agent under a Seatbelt profile on macOS, bubblewrap on Linux).

Not listed, but callable: `serve` (the episode server `run` starts), `grade`, the real-robot commands `estop`,
`operator`, `hil-check` and `robots` (the live-hardware path has not run through Robo Use yet), and `export` and
`--engine benchflow` (they need a BenchFlow release with the task-format hook).

TASK is a task folder or the id of a bundled task (e.g. `arc-gravity`); ROOT defaults to the bundled tasks.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from .. import __version__
from . import real, run

DESCRIPTION = "Robo Use: run robot tasks with an agent harness as the policy. https://robouse.ai"


def _analysis(sub: argparse._SubParsersAction) -> None:
    rp = sub.add_parser(
        "report", help="metrics with 95%% confidence intervals over run folders, grouped by trial attributes"
    )
    rp.add_argument("runs", nargs="+", help="run folders (run-many --out)")
    rp.add_argument(
        "--by",
        action="append",
        help="group keys, comma-separated (repeatable): harness, model, suite, "
        "category, difficulty, task, split, seed, mode, run, regime, released (default harness,model)",
    )
    rp.add_argument(
        "--metrics", action="append", help="metrics to show, comma-separated (default: the nine robot metrics and cost)"
    )
    rp.add_argument("--json", help="write the full report as JSON")
    rp.add_argument("--cost-quality", help="write cost-versus-success points (JSON) for groups with a known cost")
    rp.add_argument("--svg", help="write a cost-versus-success scatter (SVG)")
    rp.set_defaults(
        func=lambda a: _call("..analysis.report", "main", a.runs, a.by, a.metrics, a.json, a.cost_quality, a.svg)
    )

    gr = sub.add_parser("grade")  # listed once it has run on this release (it needs a vision-language model API)
    gr.add_argument("trials", nargs="+", help="trial folders or run folders")
    gr.add_argument(
        "--model",
        required=True,
        help="vision-language model at ROBOUSE_GRADER_URL (an OpenAI-compatible endpoint; key in "
        "ROBOUSE_GRADER_API_KEY); it must read images",
    )
    gr.add_argument("--rubric", help="extra rubric text appended to the task's success rule")
    gr.set_defaults(func=lambda a: _call("..analysis.grader", "main", a.trials, a.model, a.rubric))

    from ..analysis.flora import PROFILES

    fl = sub.add_parser(
        "flora",
        help="score and caption trial recordings with NVIDIA's Flora models: export their input, import their results",
        description="NVIDIA's Flora models label a trial's recording: an outcome score, a quality label for every half "
        "second and timestamped captions. Their weights and scripts are not part of Robo Use (NVIDIA's non-commercial "
        "license) and run on a GPU machine: `export` writes their input files, `import` reads their results into the "
        "trial folders. https://robouse.ai/docs/flora/",
    )
    fsub = fl.add_subparsers(dest="flora_cmd", required=True, metavar="ACTION")
    fe = fsub.add_parser("export", help="write the input files of NVIDIA's Flora scripts for finished trials")
    fe.add_argument("trials", nargs="+", help="trial folders or run folders")
    fe.add_argument(
        "--out", required=True, help="a new folder for the job files and copies (hard links) of the recordings"
    )
    fe.add_argument(
        "--caption-profile",
        choices=PROFILES,
        default="yam",
        help="the captioning pipeline's profile (default yam, its robot-actions profile; dex for dexterous hands)",
    )
    given = fe.add_mutually_exclusive_group()
    given.add_argument(
        "--instruction",
        help="the task instruction Flora is given, for every trial (default: each task's own: the source benchmark's "
        "language instruction, else the task's one-line description)",
    )
    given.add_argument(
        "--instructions",
        metavar="FILE",
        help="a JSON file of task ids and the instruction Flora is given for each (the other tasks get their own)",
    )
    fe.set_defaults(
        func=lambda a: _call(
            "..analysis.flora", "export_main", a.trials, a.out, a.caption_profile, a.instruction, a.instructions
        )
    )
    fi = fsub.add_parser(
        "import",
        help="write Flora's results into the trial folders (grader/flora.json) and compare its outcome scores with "
        "the simulator's verdicts",
    )
    fi.add_argument("folder", help="the export folder, with NVIDIA's output files in its results/ folder")
    fi.add_argument(
        "--success-score",
        type=int,
        choices=range(1, 6),
        default=5,
        metavar="N",
        help="the lowest outcome score (1-5) that counts as Flora calling the task solved (default 5, complete success)",
    )
    fi.set_defaults(func=lambda a: _call("..analysis.flora", "import_main", a.folder, a.success_score))

    su = sub.add_parser("summarize", help="distil a trial into learnings (markdown) for --prior-learnings")
    su.add_argument("trial", help="trial folder (OUT/<task>__<harness>__<id>)")
    su.add_argument("-o", "--out", help="output file (default: <trial>/learnings.md; - for stdout)")
    su.set_defaults(func=_summarize)

    d = sub.add_parser(
        "doctor", help="what this machine can run: simulators, harnesses, credentials and the VLA server"
    )
    d.set_defaults(func=lambda a: _call(".doctor", "run"))


def _call(module: str, fn: str, *args: object) -> int:
    import importlib

    return int(getattr(importlib.import_module(module, __name__), fn)(*args) or 0)


def _summarize(a: argparse.Namespace) -> int:
    from ..analysis.summarize import summarize

    text = summarize(Path(a.trial))
    if a.out == "-":
        print(text)
        return 0
    out = Path(a.out) if a.out else Path(a.trial) / "learnings.md"
    out.write_text(text)
    print(out)
    return 0


def _fetch_assets(a: argparse.Namespace) -> int:
    from ..assets import fetch

    if a.chemlab:
        if a.robot or a.all:
            print("robouse: --chemlab cannot be combined with --robot or --all", file=sys.stderr)
            return 2
        from ..backends.chemlab.assets import fetch as fetch_chemlab

        fetch_chemlab(Path(a.dest) if a.dest else None)
        return 0
    try:
        fetch(Path(a.dest) if a.dest else None, robots=a.robot, everything=a.all)
    except ValueError as e:
        print(f"robouse: {e}", file=sys.stderr)
        return 2
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="robouse", description=DESCRIPTION)
    ap.add_argument("--version", action="version", version=f"robouse {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="COMMAND", title="commands")
    run.register(sub)
    sub.add_parser("tasks", help="list, create and check tasks")
    sub.add_parser("components", help="list, show and check components")
    f = sub.add_parser(
        "fetch-assets",
        help="download the MuJoCo Menagerie robot models (menagerie, roboharm, drone; "
        "--robot or --all for the embodiment suites and composed tasks; --chemlab for the chemlab suite's instruments)",
    )
    f.add_argument(
        "--dest",
        help="target folder (default: <cache>/menagerie, or $ROBOUSE_MENAGERIE_ASSETS; with --chemlab, "
        "<cache>/chemlab, or $ROBOUSE_CHEMLAB_ASSETS)",
    )
    f.add_argument("--robot", action="append", help="only this Menagerie robot folder (repeatable), e.g. unitree_go2")
    from ..assets import about_mb, download_bytes

    f.add_argument(
        "--all",
        action="store_true",
        help=f"every robot the bundled suites use ({about_mb(download_bytes(everything=True))})",
    )
    from ..backends.chemlab.assets import download_bytes as chemlab_bytes

    f.add_argument(
        "--chemlab",
        action="store_true",
        help=f"instead, the ChemLab-Assets instrument files the chemlab suite uses ({about_mb(chemlab_bytes())}; "
        "models, contracts and data under CC BY-NC 4.0, for non-commercial use only)",
    )
    f.set_defaults(func=_fetch_assets)
    _analysis(sub)
    real.register(sub)
    return ap


def main(argv: list[str] | None = None) -> int:
    from ..tasks import TaskFormatError

    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("\nrobouse: interrupted", file=sys.stderr)
        return 130
    except TaskFormatError as e:  # e.g. a folder in the older task.toml + instruction.md layout
        print(f"robouse: {e}", file=sys.stderr)
        return 2


def _main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("tasks", "components", "remix"):  # these parse their own arguments (nested subcommands)
        from . import tasks

        commands: dict[str, Callable[[list[str]], int]] = {
            "tasks": tasks.tasks_main,
            "components": tasks.components_main,
            "remix": tasks.remix_alias,
        }
        return commands[args[0]](args[1:])
    a = parser().parse_args(args)
    func: Callable[[argparse.Namespace], int] = a.func
    return int(func(a))
