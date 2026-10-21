#!/usr/bin/env python3
"""Write the suites table in docs/suites.md from the task data of an installed robouse, and the reference-solution and
no-op columns from the job folders of a sweep.

    /path/to/venv/bin/python tools/docs/suites_reference.py --oracle runs/sweep-oracle --noop runs/sweep-noop

The bundled table is the text between the `<!-- suites-table -->` and `<!-- /suites-table -->` lines, the hub-only
suites (tools/docs/counts.py HUB_ONLY, counted from this checkout's task folders) are between `<!-- hub-only-table -->`
lines and the checkout-only suites (CHECKOUT_ONLY) between `<!-- checkout-only-table -->` lines, and README.md gets the
same "N tasks in M suites"; the rest of the page is hand-written. Bundled counts come from the package (`robouse tasks
--path`), so they cannot drift from the release; tests/test_counts.py checks all of it. A suite's description is the
second line of its first cell, so the table fits the docs column; a suite that needs nothing beyond robouse[sim] has an
empty Needs cell, and one without trials in a job folder shows "not run" (with --keep, the cells the page has now: a
change that adds or reruns one suite passes only that suite's sweep). Run it against the release users install, from
its checkout.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

DOC = Path(__file__).resolve().parents[2] / "docs" / "suites.md"
BEGIN, END = "<!-- suites-table -->", "<!-- /suites-table -->"
HUB_BEGIN, HUB_END = "<!-- hub-only-table -->", "<!-- /hub-only-table -->"
CHECKOUT_BEGIN, CHECKOUT_END = "<!-- checkout-only-table -->", "<!-- /checkout-only-table -->"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import counts  # noqa: E402  (tools/docs/counts.py: the counts README.md and docs say)

# The hub-only suites (not in the wheel), in a few words.
HUB_FROM = {
    "rle-bench": "RLE-Bench family 03, tabletop reasoning: tower, cantilever, balance, hidden centre of mass",
    "capx": "CaP-X's robosuite tasks, code as policy with CaP-X's privileged API (simulator object poses, no perception)",
    "capx-libero": "CaP-X on LIBERO-PRO's object-swap tasks, code as policy with CaP-X's privileged LIBERO API",
}

# The checkout-only suites (not in the wheel: files they need at run time may not be used commercially), and what they
# need beyond robouse[sim].
CHECKOUT_FROM = {
    "chemlab": "ChemLab-Assets: fume hood, balance, hotplate, oven, moisture analyzer, shaker",
}
CHECKOUT_NEEDS = {
    "chemlab": "`robouse fetch-assets --chemlab` (CC BY-NC 4.0)",
}

# What each suite is, in a few words (the task metadata's source strings are too long for a table).
FROM = {
    "metaworld": "Meta-World MT50",
    "gymrobotics": "Gymnasium-Robotics: Fetch, PointMaze",
    "kitchen": "Franka Kitchen",
    "adroit": "Adroit hand",
    "libero": "LIBERO: Spatial, Object, Goal, Long",
    "libero-90": "LIBERO-90",
    "libero-pro": "LIBERO-PRO: 73 of ASPIRE's 80 swap and task pairs",
    "robosuite": "robosuite 1.5, five arms",
    "libero-style": "LIBERO-like tabletop scenes",
    "arc-style": "ARC-style rules on a table",
    "robo-use-families": "Robo Use task families",
    "safety": "Harmful requests and benign twins",
    "vision": "Camera images, no coordinates",
    "hard": "Low-level control, uncalibrated cameras",
    "menagerie": "Dual Franka Panda, ALOHA 2",
    "roboharm": "10 harm scenarios, 4 configurations",
    "drone": "Skydio X2 over a town",
    "quadruped": "Unitree Go2 and Go1, Spot, ANYmal C",
    "humanoid": "Unitree G1 and H1, Apollo, Booster T1",
    "mobile-manip": "Stretch 3, TIAGo, Google Robot",
    "dexhand": "Shadow Hand, LEAP Hand",
    "crazyflie": "Crazyflie 2, one or three",
    "composed": "Composed from components",
    "dexjoco": "DexJoCo: Allegro hand tool use",
    "yam": "Dual YAM: Dream Labs' station scene",
    "embodied-playground": "Embodied Playground: EP-100 Launch tasks, four conditions each",
    "driving": "MetaDrive car in traffic",
    "dmcontrol": "dm_control: Control Suite, Jaco arm",
    "myosuite": "MyoSuite: muscle-driven arm and hand",
    "humanoidbench": "HumanoidBench: H1 with two hands",
    "maniskill": "ManiSkill3 on the CPU",
    "robocasa": "RoboCasa kitchens",
    "nav": "Object-goal navigation in homes",
    "one-demo": "One demonstration, then another object",
    "cubepick": "Cube pick-and-reach",
    "real": "Real arms, on the mock by default",
}
# What a suite needs beyond `pip install 'robouse[sim]'`, by backend.
ASSETS = "`robouse fetch-assets`"
ASSETS_ALL = "`robouse fetch-assets --all`"
VENV = "own virtualenv (below)"
HUB = "[the hub](run-a-suite.md#a-dataset) only"
NEEDS = {
    "tabletop": "",
    "metaworld": "`[metaworld]`",
    "gymrobotics": "`[gymrobotics]`",
    "kitchen": "`[gymrobotics]`",
    "adroit": "`[gymrobotics]`",
    "robosuite": "`[robosuite]`",
    "libero": "[LIBERO setup](#libero)",
    "menagerie": ASSETS,
    "roboharm": ASSETS,
    "drone": ASSETS,
    "quadruped": ASSETS_ALL,
    "humanoid": ASSETS_ALL,
    "mobile_manip": ASSETS_ALL,
    "dexhand": ASSETS_ALL,
    "crazyflie": ASSETS_ALL,
    "components": ASSETS_ALL,
    "dexjoco": VENV,
    "yam": VENV,
    "embodied_playground": "own virtualenv and `robouse fetch-assets --embodied-playground` (below)",
    "driving": VENV,
    "dmcontrol": VENV,
    "myosuite": VENV,
    "humanoidbench": HUB,
    "maniskill": HUB,
    "robocasa": HUB,
    "nav": "",
    "cubepick": "",
    "real": "",
}


def frontmatter(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8").split("\n---", 1)[0].removeprefix("---"))


def results(job: Path | None) -> dict[str, list[float]]:
    """task id -> rewards of the finished trials in a job folder (infrastructure failures left out)."""
    out: dict[str, list[float]] = defaultdict(list)
    if not job:
        return out
    for r in job.glob("*/result.json"):
        d = json.loads(r.read_text())
        if d.get("exception_info"):
            continue
        reward = ((d.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if reward is not None:
            out[d.get("task_name") or r.parent.name.split("__")[0]].append(float(reward))
    return out


def cell(ids: list[str], res: dict[str, list[float]], want: float) -> str:
    ran = [t for t in ids if res.get(t)]
    if not ran:
        return "not run"
    return f"{sum(1 for t in ran if any(x == 1.0 for x in res[t]))}/{len(ran)}"


def kept_cells(text: str) -> dict[str, tuple[str, str]]:
    """suite -> (reference solution, no-op control) cells of the tables on the page now."""
    out = {}
    for line in text.splitlines():
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.match(r"`([\w-]+)`", cols[0]) if line.startswith("| `") else None
        if m and len(cols) >= 4:
            out[m.group(1)] = (cols[-2], cols[-1])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--robouse", default=shutil.which("robouse", path=str(Path(sys.executable).parent)) or "robouse")
    ap.add_argument(
        "--oracle", type=Path, action="append", default=[], help="job folder(s) of a reference-solution sweep"
    )
    ap.add_argument("--noop", type=Path, action="append", default=[], help="job folder(s) of a no-op sweep")
    ap.add_argument(
        "--keep",
        action="store_true",
        help="for a suite the job folders have no trials of, keep the result cells the page has now (a change that "
        "adds or reruns one suite)",
    )
    a = ap.parse_args()
    kept = kept_cells(DOC.read_text(encoding="utf-8")) if a.keep else {}
    root = Path(
        subprocess.run([a.robouse, "tasks", "--path"], capture_output=True, text=True, check=True).stdout.strip()
    )
    version = subprocess.run([a.robouse, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    oracle, noop = defaultdict(list), defaultdict(list)
    for j in a.oracle:
        for k, v in results(j).items():
            oracle[k] += v
    for j in a.noop:
        for k, v in results(j).items():
            noop[k] += v
    rows, total = [], 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        tasks = [frontmatter(t) for t in sorted(d.rglob("task.md"))]
        if not tasks:
            continue
        ids = [t["robouse"]["id"] for t in tasks]
        backends = Counter(t["robouse"]["backend"] for t in tasks)
        needs = sorted({NEEDS.get(b, "?") for b in backends} - {""})
        ref, no = cell(ids, oracle, 1.0), cell(ids, noop, 0.0)
        if (ref, no) == ("not run", "not run") and d.name in kept:
            ref, no = kept[d.name]
        rows.append(f"| `{d.name}`<br>{FROM.get(d.name, '')} | {len(ids)} | {', '.join(needs)} | {ref} | {no} |")
        total += len(ids)
    table = [
        f"{version} bundles {total} tasks in {len(rows)} suites. \"Needs\" is what a suite needs beyond "
        "`pip install 'robouse[sim]'`, if anything. The last two columns count the tasks that scored 1 with the "
        "reference solution and with the no-op control.",
        "",
        "| Suite | Tasks | Needs | Reference solution | No-op control |",
        "|---|---|---|---|---|",
        *rows,
    ]
    hub_rows = []
    for suite in counts.HUB_ONLY:  # not in the wheel: their task folders in this checkout
        tasks = [frontmatter(t) for t in sorted((counts.REPO / "tasks" / suite).rglob("task.md"))]
        ids = [t["robouse"]["id"] for t in tasks]
        ref, no = cell(ids, oracle, 1.0), cell(ids, noop, 0.0)
        if (ref, no) == ("not run", "not run") and suite in kept:
            ref, no = kept[suite]
        hub_rows.append(f"| `{suite}`<br>{HUB_FROM.get(suite, '')} | {len(ids)} | {ref} | {no} |")
    hub = ["| Suite | Tasks | Reference solution | No-op control |", "|---|---|---|---|", *hub_rows]
    checkout_rows = []
    for suite in counts.CHECKOUT_ONLY:  # not in the wheel either: their task folders in this checkout
        tasks = [frontmatter(t) for t in sorted((counts.REPO / "tasks" / suite).rglob("task.md"))]
        ids = [t["robouse"]["id"] for t in tasks]
        ref, no = cell(ids, oracle, 1.0), cell(ids, noop, 0.0)
        if (ref, no) == ("not run", "not run") and suite in kept:
            ref, no = kept[suite]
        checkout_rows.append(
            f"| `{suite}`<br>{CHECKOUT_FROM.get(suite, '')} | {len(ids)} | {CHECKOUT_NEEDS.get(suite, '')} | {ref} | {no} |"
        )
    checkout = [
        "| Suite | Tasks | Needs | Reference solution | No-op control |",
        "|---|---|---|---|---|",
        *checkout_rows,
    ]
    text = DOC.read_text(encoding="utf-8")
    for begin, end, lines in ((BEGIN, END, table), (HUB_BEGIN, HUB_END, hub), (CHECKOUT_BEGIN, CHECKOUT_END, checkout)):
        if begin not in text or end not in text:
            sys.exit(f"{DOC} has no {begin} ... {end} block")
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
        text = head + begin + "\n" + "\n".join(lines) + "\n" + end + tail
    DOC.write_text(text, encoding="utf-8")
    changed = counts.rewrite()  # README.md says the same numbers
    print(
        f"wrote the suites tables in {DOC}: {len(rows)} suites, {total} tasks, from {version}; "
        f"{len(hub_rows)} hub-only and {len(checkout_rows)} checkout-only suites; "
        f"rewrote {', '.join(changed) or 'no other file'}"
    )


if __name__ == "__main__":
    main()
