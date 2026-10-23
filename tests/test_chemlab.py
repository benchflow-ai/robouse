"""The chemlab suite: the URDF-to-MuJoCo conversion, the behaviour-runtime bridge, the pinned file list and the task
folders. The tests at the bottom need the instrument files (`robouse fetch-assets --chemlab`) and skip without them:
they check the task targets against the downloaded contracts and run every reference solution and no-op control in
process."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from robouse.backends.chemlab import assets
from robouse.backends.chemlab.instruments import INSTRUMENTS, RELEASE_FILES, REVISION
from robouse.backends.chemlab.runtime import Bridge, Runtime, RuntimeSpec
from robouse.backends.chemlab.tasks import TASKS

ROOT = Path(__file__).resolve().parents[1]
HAVE_MUJOCO = importlib.util.find_spec("mujoco") is not None

URDF = """<?xml version="1.0"?>
<robot name="cabinet">
  <link name="base_link"/>
  <link name="body">
    <inertial><origin xyz="0 0 0.2"/><mass value="5"/><inertia ixx="0.1" iyy="0.1" izz="0.1" ixy="0" ixz="0" iyz="0"/></inertial>
    <visual><geometry><mesh filename="meshes/body.obj"/></geometry></visual>
    <collision><origin xyz="0 0 0.2"/><geometry><box size="0.4 0.3 0.4"/></geometry></collision>
    <collision><origin xyz="0 -0.151 0.2"/><geometry><box size="0.3 0.001 0.2"/></geometry></collision>
  </link>
  <joint name="body_joint" type="fixed"><parent link="base_link"/><child link="body"/></joint>
  <link name="door">
    <inertial><mass value="1"/><inertia ixx="0.01" iyy="0.01" izz="0.01" ixy="0" ixz="0" iyz="0"/></inertial>
    <collision><origin xyz="-0.2 -0.01 0.2"/><geometry><box size="0.4 0.02 0.4"/></geometry></collision>
  </link>
  <joint name="door_joint" type="revolute"><parent link="body"/><child link="door"/>
    <origin xyz="0.2 -0.15 0" rpy="0 0 0"/><axis xyz="0 0 1"/><limit lower="0" upper="1.6" effort="1" velocity="1"/></joint>
  <link name="drawer"><collision><geometry><cylinder radius="0.02" length="0.05"/></geometry></collision></link>
  <joint name="drawer_joint" type="prismatic"><parent link="body"/><child link="drawer"/>
    <origin xyz="0 0 0.3" rpy="0 0 1.5707963"/><axis xyz="1 0 0"/><limit lower="0" upper="0.2" effort="1" velocity="1"/></joint>
  <link name="knob"><collision><geometry><sphere radius="0.01"/></geometry></collision></link>
  <joint name="knob_joint" type="continuous"><parent link="body"/><child link="knob"/><axis xyz="0 1 0"/></joint>
</robot>
"""
OBJ = """mtllib body.mtl
v 0 0 0
v 1 0 0
v 0 1 0
v 0 0 1
v 1 1 1
usemtl white
f 1 2 3
f 1 3 4
f 2 3 4 5
usemtl red
f 1/1/1 2/2/2 5/3/3
f 2 4 5
f 1 4 5
"""
MTL = "newmtl white\nKd 0.9 0.9 0.9\nnewmtl red\nKd 0.8 0.1 0.1\nd 0.5\n"


def _cabinet(tmp_path: Path) -> Path:
    (tmp_path / "meshes").mkdir()
    (tmp_path / "meshes" / "body.obj").write_text(OBJ)
    (tmp_path / "meshes" / "body.mtl").write_text(MTL)
    (tmp_path / "model.urdf").write_text(URDF)
    return tmp_path / "model.urdf"


@pytest.mark.skipif(not HAVE_MUJOCO, reason="needs MuJoCo")
def test_urdf_becomes_a_scene_with_its_joints_proxies_and_coloured_meshes(tmp_path) -> None:
    import mujoco

    from robouse.backends.chemlab import scene

    u = scene.read_urdf(_cabinet(tmp_path))
    assert u.root == "base_link" and [j.type for j in u.joints] == ["fixed", "revolute", "prismatic", "continuous"]
    cfg = {
        "joints": {"door_joint": {"damping": 3.0, "frictionloss": 0.6, "armature": 0.05}},
        "default_joint": {"damping": 5.0, "frictionloss": 5.0, "armature": 0.01},
        "colliders": [
            {"link": "door", "type": "capsule", "fromto": (-0.3, -0.05, 0.1, -0.3, -0.05, 0.3), "size": 0.01}
        ],
        "cameras": {"front": ((0, -1.5, 1.0), (0, 0, 0.2), 45)},
    }
    m = mujoco.MjModel.from_xml_string(scene.scene_xml(u, cfg))
    door, drawer, knob = (m.joint(n) for n in ("door_joint", "drawer_joint", "knob_joint"))
    assert door.type[0] == mujoco.mjtJoint.mjJNT_HINGE and list(door.range) == pytest.approx([0, 1.6])
    assert drawer.type[0] == mujoco.mjtJoint.mjJNT_SLIDE and list(drawer.range) == pytest.approx([0, 0.2])
    assert knob.type[0] == mujoco.mjtJoint.mjJNT_HINGE and not m.jnt_limited[knob.id]
    assert m.dof_damping[door.dofadr[0]] == pytest.approx(3.0) and m.dof_frictionloss[drawer.dofadr[0]] == 5.0
    # the 1 mm decal proxy is left out; the added capsule is in; collision proxies are not drawn (group 3)
    names = [m.geom(g).name for g in range(m.ngeom)]
    assert "i_body_c0" in names and "i_body_c1" not in names and "i_door_x0" in names
    assert m.geom_group[m.geom("i_door_c0").id] == 3 and m.geom_contype[m.geom("i_door_c0").id] == 2
    # the OBJ's two materials are two meshes with their colours
    meshes = [g for g in range(m.ngeom) if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH]
    assert m.nmesh == 2 and sorted(tuple(m.geom_rgba[g].round(2)) for g in meshes) == [
        (0.8, 0.1, 0.1, 0.5),
        (0.9, 0.9, 0.9, 1.0),
    ]
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    # the prismatic joint's frame keeps the URDF origin's rpy (90 degrees about z): its axis is world y
    assert list(d.xaxis[drawer.id]) == pytest.approx([0, 1, 0], abs=1e-6)
    assert list(d.xpos[m.body("i_door").id]) == pytest.approx([0.2, -0.15, 0.0])


SCENE_CFG = {"cameras": {"front": ((0, -1.5, 1.0), (0, 0, 0.2), 45)}}


def _hand_frame(m, d, points):
    """Points (world) in the floating hand's frame: its origin is the tool point, its -z the tool axis."""
    import numpy as np

    b = m.body("hand").id
    return (np.asarray(points) - d.xpos[b]) @ d.xmat[b].reshape(3, 3)


def _geom_points(m, d, g):
    """A geom's mesh vertices or box corners, in world coordinates."""
    import mujoco
    import numpy as np

    if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
        k = m.geom_dataid[g]
        local = m.mesh_vert[m.mesh_vertadr[k] : m.mesh_vertadr[k] + m.mesh_vertnum[k]]
    else:
        local = np.array([[a, b, c] for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)]) * m.geom_size[g]
    return local @ d.geom_xmat[g].reshape(3, 3).T + d.geom_xpos[g]


@pytest.mark.skipif(not HAVE_MUJOCO, reason="needs MuJoCo")
def test_the_gripper_is_menageries_franka_hand(tmp_path) -> None:
    """The floating gripper is MuJoCo Menagerie's Franka Hand, from the pinned Menagerie files robouse uses for the
    Panda: the hand and both fingers with their inertias, meshes, materials and collision geometry (the hand's mesh,
    and each finger's mesh and five fingertip pads), all of it colliding with the instrument and the bench."""
    import mujoco
    import numpy as np

    from robouse.assets import asset_root
    from robouse.backends.chemlab import scene

    m = scene.scene_model(scene.read_urdf(_cabinet(tmp_path)), SCENE_CFG)
    panda = mujoco.MjModel.from_xml_path(str(asset_root() / scene.HAND_MODEL))
    for name in ("hand", "left_finger", "right_finger"):
        ours, theirs = m.body(scene.HAND + name), panda.body(name)
        assert ours.mass[0] == pytest.approx(theirs.mass[0]) and list(ours.inertia) == pytest.approx(theirs.inertia)
        mine = [g for g in range(m.ngeom) if m.geom_bodyid[g] == ours.id]
        orig = [g for g in range(panda.ngeom) if panda.geom_bodyid[g] == theirs.id]
        assert len(mine) == len(orig)
        for g, h in zip(mine, orig, strict=True):
            assert m.geom_type[g] == panda.geom_type[h] and list(m.geom_size[g]) == pytest.approx(panda.geom_size[h])
            assert (m.geom_contype[g] == 0) == (panda.geom_contype[h] == 0)  # visual or collision, as Menagerie's
            if m.geom_matid[g] >= 0 or panda.geom_matid[h] >= 0:
                assert list(m.mat_rgba[m.geom_matid[g]]) == pytest.approx(panda.mat_rgba[panda.geom_matid[h]])
            if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH:
                a, b = m.geom_dataid[g], panda.geom_dataid[h]
                va = m.mesh_vert[m.mesh_vertadr[a] : m.mesh_vertadr[a] + m.mesh_vertnum[a]]
                vb = panda.mesh_vert[panda.mesh_vertadr[b] : panda.mesh_vertadr[b] + panda.mesh_vertnum[b]]
                assert va.shape == vb.shape and np.allclose(va, vb)
        colliders = [g for g in mine if m.geom_contype[g]]
        boxes = [g for g in colliders if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX]
        assert len(colliders) == (1 if name == "hand" else 6) and len(boxes) == (0 if name == "hand" else 5)
        assert all(m.geom_contype[g] == 1 and m.geom_conaffinity[g] == 6 for g in colliders)
    # only the hand's eight meshes are loaded, not the arm's
    assert sorted(m.mesh(k).name for k in range(m.nmesh) if m.mesh(k).name.startswith(scene.HAND)) == [
        scene.HAND + n for n in ("finger_0", "finger_1", "hand_0", "hand_1", "hand_2", "hand_3", "hand_4", "hand_c")
    ]


@pytest.mark.skipif(not HAVE_MUJOCO, reason="needs MuJoCo")
def test_the_fingers_open_and_close_over_the_pandas_travel(tmp_path) -> None:
    """Each finger slides 0 to 0.04 m, the Panda's travel, and the two move together; open, the fingertip pads are 8 cm
    apart, centred on the tool point (the floating body's origin) across the tool axis and along it."""
    import mujoco
    import numpy as np

    from robouse.backends.chemlab import scene

    m = scene.scene_model(scene.read_urdf(_cabinet(tmp_path)), SCENE_CFG)
    d = mujoco.MjData(m)
    j1, j2 = (m.joint(scene.HAND + n) for n in ("finger_joint1", "finger_joint2"))
    assert list(m.jnt_range[j1.id]) == pytest.approx([0, scene.FINGER_OPEN]) == list(m.jnt_range[j2.id])
    assert scene.FINGER_OPEN == 0.04
    act = m.actuator(scene.HAND + "actuator8").id
    pads = [
        g
        for g in range(m.ngeom)
        if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX
        and m.geom_contype[g]
        and m.body(m.geom_bodyid[g]).name.startswith(scene.HAND)
    ]
    for ctrl, q in (
        (scene.GRIP_OPEN_CTRL, 0.04),
        (0.0, 0.0),
        (scene.GRIP_OPEN_CTRL / 2, 0.02),
        (scene.GRIP_OPEN_CTRL, 0.04),
    ):
        d.ctrl[act] = ctrl
        for _ in range(400):
            mujoco.mj_step(m, d)
        q1, q2 = d.qpos[m.jnt_qposadr[j1.id]], d.qpos[m.jnt_qposadr[j2.id]]
        assert q1 == pytest.approx(q, abs=1e-3) and q2 == pytest.approx(q, abs=1e-3), (ctrl, q1, q2)
        local = np.vstack([_hand_frame(m, d, _geom_points(m, d, g)) for g in pads])
        inner = np.abs(local[:, 1]).min()  # the pads' faces nearest the tool point, across the closing direction
        assert 2 * inner == pytest.approx(2 * q, abs=1.5e-3)
        assert local[:, 0].mean() == pytest.approx(0, abs=1e-3) and local[:, 1].mean() == pytest.approx(0, abs=1e-3)
        big = [g for g in pads if m.geom_size[g][0] > 0.008]  # each finger's large pad is centred on the tool point
        assert [_hand_frame(m, d, d.geom_xpos[g])[2] for g in big] == pytest.approx([0, 0], abs=1e-3)


@pytest.mark.skipif(not HAVE_MUJOCO, reason="needs MuJoCo")
def test_the_hand_is_the_size_the_tasks_give(tmp_path) -> None:
    """scene.HAND_SIZE, which the task instructions state, measured on the model (to 1 mm)."""
    import mujoco
    import numpy as np

    from robouse.backends.chemlab import scene

    m = scene.scene_model(scene.read_urdf(_cabinet(tmp_path)), SCENE_CFG)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)  # the fingers at 0, closed

    def collider(body: str, kind) -> np.ndarray:
        b = m.body(scene.HAND + body).id
        gs = [g for g in range(m.ngeom) if m.geom_bodyid[g] == b and m.geom_contype[g] and m.geom_type[g] == kind]
        return np.vstack([_hand_frame(m, d, _geom_points(m, d, g)) for g in gs])

    hand = collider("hand", mujoco.mjtGeom.mjGEOM_MESH)
    finger = collider("left_finger", mujoco.mjtGeom.mjGEOM_MESH)
    near = hand[hand[:, 2] < hand[:, 2].min() + 0.018]  # the hand's body where the fingers leave it
    root = finger[finger[:, 2] > hand[:, 2].min() - 0.004]
    got = {
        "gap": 2 * scene.FINGER_OPEN,
        "finger_width": np.ptp(finger[:, 0]),
        "finger_thickness": np.ptp(root[:, 1]),
        "finger_out": hand[:, 2].min() - finger[:, 2].min(),
        "tip": -finger[:, 2].min(),
        "palm": hand[:, 2].min(),
        "hand_length": np.ptp(hand[:, 1]),
        "hand_width": np.ptp(near[:, 0]),
        "hand_width_max": np.ptp(hand[:, 0]),
    }
    assert got == pytest.approx(scene.HAND_SIZE, abs=1e-3)


def _fake_runtime():
    """A runtime with a sash that creeps down to 0.5 when it is let go above it."""

    class Host:
        def __init__(self, instance_id):
            self.h, self.held, self.calls, self.roles = 0.0, False, [], {}

        def register_principal(self, name, visibility):
            self.roles[name] = visibility

        def session(self, name):
            host = self

            class S:
                def invoke(self, *, instance_id, capability_id, arguments, request_id):
                    host.calls.append((capability_id, dict(arguments)))
                    host.h, host.held = arguments["height_m"], arguments["hold"]
                    return {"status": "succeeded"}

                def read(self, *, instance_id, state_ids=None):
                    obs = {"sash.height_m": {"value": host.h}}
                    if host.roles[name] == "evaluator":
                        obs["truth.secret"] = {"value": 42}
                    return {"observations": obs}

            return S()

        def step(self, dt):
            if self.h > 0.5 and not self.held:
                self.h = max(0.5, self.h - 0.1 * dt)

    spec = RuntimeSpec(
        module="scripts/fake.py",
        cls="Host",
        joints={"sash_joint": Bridge("sash.height_m", "sash.set", "height_m", scale=2.0, held_arg="hold", tol=1e-3)},
        readouts=("sash.height_m", "truth.secret"),
    )
    return Runtime(spec, module=SimpleNamespace(Host=Host))


def test_the_runtime_follows_the_scene_and_the_scene_follows_the_runtime() -> None:
    rt = _fake_runtime()
    host = rt.rt
    rt.sync({"sash_joint": 0.4}, set(), 0.0)
    assert host.calls == [("sash.set", {"height_m": 0.2, "hold": False})]
    rt.sync({"sash_joint": 0.4}, set(), 0.02)  # nothing moved: no call
    rt.sync({"sash_joint": 1.4}, {"sash_joint"}, 0.02)  # the gripper raises it above the stop and holds it
    assert host.calls[-1] == ("sash.set", {"height_m": 0.7, "hold": True}) and len(host.calls) == 2
    assert rt.joint_target("sash_joint") is None  # held: the scene leads
    rt.sync({"sash_joint": 1.4}, set(), 0.5)  # let go: the runtime creeps down on its own and now leads the sash
    assert host.calls[-1] == ("sash.set", {"height_m": 0.7, "hold": False}) and len(host.calls) == 3
    assert rt.joint_target("sash_joint") == pytest.approx(2 * 0.65)
    rt.sync({"sash_joint": 1.35}, set(), 2.0)  # the joint lags behind: no call sets the runtime back
    rt.sync({"sash_joint": 1.1}, set(), 0.02)
    assert len(host.calls) == 3 and host.h == 0.5 and rt.joint_target("sash_joint") == pytest.approx(1.0)
    rt.sync({"sash_joint": 1.0}, set(), 0.02)  # at rest where the runtime has it: the scene leads again
    assert rt.joint_target("sash_joint") is None and host.calls[-1] == ("sash.set", {"height_m": 0.5, "hold": False})
    rt.sync({"sash_joint": 1.6}, {"sash_joint"}, 0.02)  # taken hold of again
    assert host.calls[-1] == ("sash.set", {"height_m": 0.8, "hold": True})
    # the agent sees only its own view
    assert rt.readouts() == {"sash.height_m": 0.8} and rt.read("host")["truth.secret"] == 42


def test_the_pinned_files_cover_every_task_and_none_is_in_the_repository() -> None:
    m = assets.manifest()
    assert m["revision"] == REVISION and m["release"] == "1.3.0" and "CC BY-NC 4.0" in m["licence"]
    paths = {f["path"] for f in m["files"]}
    for f in m["files"]:
        assert f["url"].startswith(f"https://huggingface.co/datasets/MBZUAI/ChemLab-Assets/resolve/{REVISION}/")
        assert re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) and f["bytes"] > 0
        assert not f["path"].endswith((".glb", ".blend", ".png", ".webp"))
    assert set(RELEASE_FILES) <= paths
    for t in TASKS.values():
        inst = INSTRUMENTS[t.instrument]
        assert set(inst.files()) <= paths, t.id
        assert any(p.startswith(f"{inst.path}/meshes/") and p.endswith(".obj") for p in paths), t.id
        assert m["instruments"][inst.slug]["path"] == inst.path
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True).stdout.split()
    if tracked:  # a checkout: no instrument file is in git
        names = {Path(p).name for p in paths} - {"LICENSE", "CITATION.cff"}
        assert not [p for p in tracked if Path(p).name in names and "chemlab" in p], "an instrument file is in git"
        assert not [p for p in tracked if p.endswith((".obj", ".urdf", ".mtl")) and "chemlab" in p]


def test_without_the_files_the_backend_says_how_to_fetch_them(tmp_path, monkeypatch) -> None:
    from robouse.backends.chemlab.backend import ChemLabBackend

    monkeypatch.setenv("ROBOUSE_CHEMLAB_ASSETS", str(tmp_path / "none"))
    with pytest.raises(FileNotFoundError, match=r"robouse fetch-assets --chemlab.*CC BY-NC 4\.0"):
        ChemLabBackend({"id": "chemlab-fume-hood-sash"})
    with pytest.raises(KeyError, match="unknown chemlab task"):
        ChemLabBackend({"id": "chemlab-teleport"})


def test_fetch_downloads_every_pinned_file_with_its_hash(tmp_path, monkeypatch) -> None:
    got = []
    monkeypatch.setattr(assets, "fetch_file", lambda url, dest, sha, timeout: got.append((url, dest, sha)) or True)
    lines: list[str] = []
    assets.fetch(tmp_path, log=lines.append)
    m = assets.manifest()
    assert sorted((u, d.relative_to(tmp_path).as_posix(), s) for u, d, s in got) == sorted(
        (f["url"], f["path"], f["sha256"]) for f in m["files"]
    )
    assert "CC BY-NC 4.0" in lines[0] and lines[-1].startswith(f"{len(m['files'])} file(s) downloaded")


@pytest.mark.parametrize("path", ["../outside.txt", "assets/../../outside.txt", "/tmp/outside.txt"])
def test_fetch_writes_nothing_outside_the_download_folder(path, tmp_path, monkeypatch) -> None:
    """A manifest path that leaves the download folder (`..`, an absolute path) is refused before any download."""
    entry = {"url": "https://example.invalid/file", "sha256": "0" * 64, "bytes": 1}
    files = [{**entry, "path": "LICENSE"}, {**entry, "path": path}]
    monkeypatch.setattr(assets, "manifest", lambda: {"release": "1.3.0", "revision": REVISION, "files": files})
    got = []
    monkeypatch.setattr(assets, "fetch_file", lambda url, dest, sha, timeout: got.append(dest) or True)
    with pytest.raises(ValueError, match="outside the download folder"):
        assets.fetch(tmp_path / "chemlab", log=lambda line: None)
    assert got == []


def test_the_task_folders_are_the_generators(tmp_path) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "adapters" / "chemlab" / "generate.py"), "--out", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    made = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    have = sorted(
        p.relative_to(ROOT / "tasks" / "chemlab") for p in (ROOT / "tasks" / "chemlab").rglob("*") if p.is_file()
    )
    assert made == have and len(made) == 3 * len(TASKS)
    for rel in made:
        assert (tmp_path / rel).read_text() == (ROOT / "tasks" / "chemlab" / rel).read_text(), rel


def test_the_agent_view_names_no_target() -> None:
    """The observation reports the parts' states and positions; the targets are only in the instruction."""
    for t in TASKS.values():
        for p in t.parts:
            assert not ({*p.points, *p.sizes} & {"target", "goal", "target_deg", "target_m"}), t.id
        body = (ROOT / "tasks" / "chemlab" / t.id / "task.md").read_text()
        assert t.goal in body and t.success in body


# ---- with the instrument files ------------------------------------------------------------------------------------

HAVE_FILES = HAVE_MUJOCO and not assets.missing()
needs_files = pytest.mark.skipif(not HAVE_FILES, reason="needs MuJoCo and `robouse fetch-assets --chemlab`")


def _contract(slug: str) -> dict:
    return json.loads((assets.root() / INSTRUMENTS[slug].contract).read_text())


@needs_files
def test_bindings_and_targets_agree_with_the_contracts() -> None:
    for slug, inst in INSTRUMENTS.items():
        knobs = (_contract(slug).get("extensions", {}).get("matterix.bindings") or {}).get("knobs") or {}
        for joint, b in (inst.runtime.joints if inst.runtime else {}).items():
            if joint in knobs:  # the contract's own scene binding
                assert knobs[joint]["state"] == b.slot and knobs[joint]["capability"] == b.capability
                assert knobs[joint]["scale"] == pytest.approx(b.scale) and knobs[joint]["offset"] == pytest.approx(
                    b.offset
                )
    model = json.loads((assets.root() / INSTRUMENTS["esco_efa5uduvw"].path / "instrument_model.json").read_text())
    assert model["documented"]["sash_stop_m"]["value"] == pytest.approx(0.457)
    model = json.loads((assets.root() / INSTRUMENTS["binder_fd056"].path / "instrument_model.json").read_text())
    assert model["engineering"]["door_switch_rad"]["value"] == pytest.approx(0.05)
    hx = (assets.root() / INSTRUMENTS["mt_hx204"].runtime.module).read_text()
    assert "lid_m>=0.1" in hx and "1.6691" in json.dumps(_contract("mt_hx204"), ensure_ascii=False)
    ks = (assets.root() / INSTRUMENTS["ika_ks4000"].runtime.module).read_text()
    assert "hood>=1.4" in ks
    # 100 degC and 500 rpm are one turn of their knobs
    ika = INSTRUMENTS["ika_plate_rctdigital"].runtime.joints
    assert 373.15 * ika["knob_temperature_joint"].scale + ika["knob_temperature_joint"].offset == pytest.approx(
        2 * math.pi
    )
    assert 500 * math.pi / 30 * ika["knob_speed_joint"].scale == pytest.approx(2 * math.pi)


@needs_files
@pytest.mark.parametrize("task_id", sorted(TASKS))
def test_reference_solution_scores_1_and_noop_0(task_id, tmp_path, monkeypatch) -> None:
    from robouse import agent_cli
    from robouse.backends.chemlab import oracle
    from robouse.core.gl import auto_select
    from robouse.core.session import Episode
    from robouse.tasks import load_task

    auto_select()
    spec = load_task(ROOT / "tasks" / "chemlab" / task_id).spec
    ep = Episode(spec, tmp_path / "oracle")
    monkeypatch.setattr(agent_cli, "_send", lambda req, path=None: ep.handle(req))
    oracle.oracle_main(task_id)
    assert ep.finished and ep.result["success"], ep.result
    assert not ep.result["judge_detail"].get("runtime_refused")  # the runtime took every value the scene sent
    ep.close()
    ep = Episode(spec, tmp_path / "noop")
    ep.handle({"op": "done", "text": "noop control"})
    assert ep.finished and not ep.result["success"]
    ep.close()


def test_a_moved_download_folder_is_denied_to_agents(tmp_path, monkeypatch) -> None:
    """The instrument runtimes are Python modules that the episode server imports, outside the sandbox. In robouse's
    cache they are out of agents' reach; ROBOUSE_CHEMLAB_ASSETS can move them anywhere, where an agent could change a
    runtime or its data (or leave compiled bytecode beside it) for a later trial's server. A moved folder is denied as
    the cache is, in the Seatbelt profile and in bubblewrap's arguments."""
    from robouse import config
    from robouse.runner import sandbox

    moved = tmp_path / "chemlab-files"
    (moved / "scripts").mkdir(parents=True)
    monkeypatch.setenv("ROBOUSE_CHEMLAB_ASSETS", str(moved))
    real = os.path.realpath(moved)
    assert str(moved) in config.sandbox_denied_paths() and real in sandbox._denied([])
    assert f'(deny file-read* file-write* (subpath "{real}"))' in sandbox.sandbox_profile(tmp_path / "ws", (), [], [])
    args = sandbox.bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [], [])
    assert args[args.index(real) - 1] == "--tmpfs"
    monkeypatch.delenv("ROBOUSE_CHEMLAB_ASSETS")
    assert real not in sandbox._denied([])
