"""ChemLab-Assets instruments as MuJoCo scenes: the instrument's URDF converted to MJCF, standing on a bench, with a
floating Franka Hand (the Franka Emika Panda's two-finger hand, from MuJoCo Menagerie).

Conversion (URDF -> MJCF), done in memory at every episode start from the downloaded files, never written to disk:
- every link becomes a body and every joint a MuJoCo joint (revolute -> hinge with its limits, continuous -> unlimited
  hinge, prismatic -> slide, fixed -> none); the instrument's root is fixed to the world (no free joint);
- the URDF's primitive collision proxies (box, cylinder, sphere) become the collision geoms; they collide with the
  gripper only, never with each other, since several proxies overlap at rest and the joint limits already bound the
  parts' travel. Proxies thinner than 1.5 mm are left out: they are labels, prints, icons, display glass and flat
  keys laid over a larger proxy (some stand clear of the surface beneath, where a finger could catch on them);
- each link's visual OBJ is read, split by material (MuJoCo would merge an OBJ's materials into one) and passed to
  MuJoCo as inline mesh data, coloured with the material's diffuse colour from the MTL file;
- the URDF has no joint dynamics, so every moving joint gets damping, friction and armature (instruments.py), push
  keys a return spring, and every link gravity compensation: sashes are counterweighted and lids and doors are held
  by gas springs or their hinges' friction, so a part stays where it is let go.

The hand is Menagerie's own model, read from the pinned Menagerie files robouse already uses for the Panda (a checkout's
assets/menagerie, or `robouse fetch-assets`): the hand body and its two fingers with their meshes, materials, inertias,
collision geometry (the hand's and the fingers' meshes and each finger's five fingertip pads), slide joints (0 to
0.04 m per finger), the tendon and joint equality that couple the fingers, and the hand's actuator. It floats: it is
fixed to a free body welded to a mocap target, turned so that its fingers point along the body's -z, with the tool point
(between the fingertip pads) at the body's origin.

Frame: the asset frame, unchanged: metres, +x right, +y toward the back of the instrument, +z up; the instrument's
front faces -y and its footprint is centred on the origin, with its bottom on the bench top at z = 0.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# collision classes: bench and floor 4, instrument 2, gripper 1. Instrument geoms touch only the gripper.
STATIC = 'contype="4" conaffinity="1"'
PART = 'contype="2" conaffinity="1" group="3"'  # group 3: not drawn (the visual meshes are)
MOVING = 'contype="1" conaffinity="6"'
VISUAL = 'contype="0" conaffinity="0" group="2"'

DECAL_M = 0.0015  # collision proxies thinner than this are decals (labels, prints, display glass): not colliders
SUBSTEPS = 10  # 10 x 2 ms = one 20 ms control step
SETTLE_SUBSTEPS = 150


def _f(*v) -> str:
    return " ".join(f"{float(x):.6g}" for x in v)


# ---------------------------------------------------------------------------------------------------------------------
# URDF
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Origin:
    xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rpy: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def quat(self) -> np.ndarray:
        """URDF rpy (fixed axes x, then y, then z) as a MuJoCo quaternion (w, x, y, z)."""
        r, p, y = self.rpy
        cr, sr, cp, sp, cy, sy = (
            math.cos(r / 2),
            math.sin(r / 2),
            math.cos(p / 2),
            math.sin(p / 2),
            math.cos(y / 2),
            math.sin(y / 2),
        )
        return np.array(
            [
                cr * cp * cy + sr * sp * sy,
                sr * cp * cy - cr * sp * sy,
                cr * sp * cy + sr * cp * sy,
                cr * cp * sy - sr * sp * cy,
            ]
        )

    def attrs(self) -> str:
        out = f'pos="{_f(*self.xyz)}"'
        if any(abs(a) > 1e-12 for a in self.rpy):
            out += f' quat="{_f(*self.quat())}"'
        return out


@dataclass
class Link:
    name: str
    mass: float = 0.0
    inertial: Origin = field(default_factory=Origin)
    inertia: tuple[float, ...] = ()  # ixx iyy izz ixy ixz iyz
    visuals: list[tuple[Origin, str]] = field(default_factory=list)  # (origin, mesh file relative to the URDF)
    collisions: list[tuple[Origin, str, tuple[float, ...]]] = field(default_factory=list)  # (origin, kind, size)


@dataclass
class Joint:
    name: str
    type: str
    parent: str
    child: str
    origin: Origin
    axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    lower: float | None = None
    upper: float | None = None


@dataclass
class Urdf:
    path: Path
    root: str
    links: dict[str, Link]
    joints: list[Joint]

    def children(self, link: str) -> list[Joint]:
        return [j for j in self.joints if j.parent == link]

    def joint(self, name: str) -> Joint:
        for j in self.joints:
            if j.name == name:
                return j
        raise KeyError(f"no joint {name!r} in {self.path.name}")


def _origin(el: ET.Element | None) -> Origin:
    if el is None:
        return Origin()
    xyz = tuple(float(v) for v in (el.get("xyz") or "0 0 0").split())
    rpy = tuple(float(v) for v in (el.get("rpy") or "0 0 0").split())
    return Origin(xyz, rpy)  # type: ignore[arg-type]


def read_urdf(path: Path) -> Urdf:
    root_el = ET.parse(path).getroot()
    links: dict[str, Link] = {}
    for le in root_el.findall("link"):
        link = Link(le.get("name", ""))
        ine = le.find("inertial")
        if ine is not None:
            m = ine.find("mass")
            link.mass = float(m.get("value", 0)) if m is not None else 0.0
            link.inertial = _origin(ine.find("origin"))
            i = ine.find("inertia")
            if i is not None:
                link.inertia = tuple(float(i.get(k, 0)) for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz"))
        for ve in le.findall("visual"):
            mesh = ve.find("geometry/mesh")
            if mesh is not None and mesh.get("filename"):
                link.visuals.append((_origin(ve.find("origin")), mesh.get("filename", "")))
        for ce in le.findall("collision"):
            g = ce.find("geometry")
            if g is None or not len(g):
                continue
            shape = g[0]
            if shape.tag == "box":
                size = tuple(float(v) for v in shape.get("size", "0 0 0").split())
            elif shape.tag == "cylinder":
                size = (float(shape.get("radius", 0)), float(shape.get("length", 0)))
            elif shape.tag == "sphere":
                size = (float(shape.get("radius", 0)),)
            else:  # meshes as colliders: not used by these assets, skipped
                continue
            link.collisions.append((_origin(ce.find("origin")), shape.tag, size))
        links[link.name] = link
    joints = []
    for je in root_el.findall("joint"):
        ax = je.find("axis")
        lim = je.find("limit")
        lo = hi = None
        if lim is not None and lim.get("lower") not in (None, "") and lim.get("upper") not in (None, ""):
            lo, hi = float(lim.get("lower", 0)), float(lim.get("upper", 0))
        joints.append(
            Joint(
                name=je.get("name", ""),
                type=je.get("type", "fixed"),
                parent=je.find("parent").get("link", ""),  # type: ignore[union-attr]
                child=je.find("child").get("link", ""),  # type: ignore[union-attr]
                origin=_origin(je.find("origin")),
                axis=tuple(float(v) for v in ax.get("xyz", "1 0 0").split()) if ax is not None else (1.0, 0.0, 0.0),  # type: ignore[arg-type]
                lower=lo,
                upper=hi,
            )
        )
    children = {j.child for j in joints}
    roots = [n for n in links if n not in children]
    if len(roots) != 1:
        raise ValueError(f"{path.name}: expected one root link, found {roots}")
    return Urdf(path, roots[0], links, joints)


# ---------------------------------------------------------------------------------------------------------------------
# OBJ meshes, split by material
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class MeshPart:
    name: str
    rgba: tuple[float, float, float, float]
    vertices: np.ndarray  # (n, 3)
    faces: np.ndarray  # (m, 3), indices into vertices


def read_mtl(path: Path) -> dict[str, tuple[float, float, float, float]]:
    """Material name -> rgba from an MTL file's diffuse colour (Kd) and dissolve (d)."""
    out: dict[str, tuple[float, float, float, float]] = {}
    if not path.is_file():
        return out
    name, kd, d = None, (0.6, 0.6, 0.6), 1.0
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "newmtl":
            if name is not None:
                out[name] = (*kd, d)
            name, kd, d = " ".join(parts[1:]), (0.6, 0.6, 0.6), 1.0
        elif parts[0] == "Kd" and len(parts) >= 4:
            kd = tuple(min(1.0, max(0.0, float(v))) for v in parts[1:4])  # type: ignore[assignment]
        elif parts[0] == "d" and len(parts) >= 2:
            d = min(1.0, max(0.0, float(parts[1])))
        elif parts[0] == "Tr" and len(parts) >= 2:
            d = 1.0 - min(1.0, max(0.0, float(parts[1])))
    if name is not None:
        out[name] = (*kd, d)
    return out


def read_obj(path: Path, stem: str) -> list[MeshPart]:
    """An OBJ file as one mesh per material (polygons fanned into triangles)."""
    verts: list[tuple[float, float, float]] = []
    groups: dict[str, list[tuple[int, int, int]]] = {}
    mtl: dict[str, tuple[float, float, float, float]] = {}
    current = ""
    for line in path.read_text(errors="replace").splitlines():
        if not line or line[0] == "#":
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v" and len(parts) >= 4:
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif tag == "f" and len(parts) >= 4:
            idx = []
            for p in parts[1:]:
                i = int(p.split("/", 1)[0])
                idx.append(i - 1 if i > 0 else len(verts) + i)
            g = groups.setdefault(current, [])
            for k in range(1, len(idx) - 1):
                g.append((idx[0], idx[k], idx[k + 1]))
        elif tag == "usemtl":
            current = " ".join(parts[1:])
        elif tag == "mtllib":
            mtl.update(read_mtl(path.parent / " ".join(parts[1:])))
    v = np.asarray(verts, dtype=float).reshape(-1, 3)
    out = []
    for k, (mat, faces) in enumerate(groups.items()):
        f = np.asarray(faces, dtype=int).reshape(-1, 3)
        used = np.unique(f)
        if len(used) < 4:
            continue
        remap = np.full(len(v), -1, dtype=int)
        remap[used] = np.arange(len(used))
        out.append(MeshPart(f"{stem}_{k}", mtl.get(mat, (0.6, 0.6, 0.6, 1.0)), v[used], remap[f]))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# MJCF
# ---------------------------------------------------------------------------------------------------------------------


def _inertial(link: Link) -> str:
    if (
        link.mass <= 0
    ):  # links without mass (frames, slides between parts) get a token one: MuJoCo needs it to move them
        return '<inertial pos="0 0 0" mass="0.001" diaginertia="1e-7 1e-7 1e-7"/>'
    ixx, iyy, izz, ixy, ixz, iyz = link.inertia or (1e-4, 1e-4, 1e-4, 0.0, 0.0, 0.0)
    pos = f'pos="{_f(*link.inertial.xyz)}"'
    quat = f' quat="{_f(*link.inertial.quat())}"' if any(link.inertial.rpy) else ""
    if abs(ixy) + abs(ixz) + abs(iyz) > 1e-12:
        return f'<inertial {pos}{quat} mass="{_f(link.mass)}" fullinertia="{_f(ixx, iyy, izz, ixy, ixz, iyz)}"/>'
    return f'<inertial {pos}{quat} mass="{_f(link.mass)}" diaginertia="{_f(max(ixx, 1e-6), max(iyy, 1e-6), max(izz, 1e-6))}"/>'


def _thickness(kind: str, size: tuple[float, ...]) -> float:
    """A proxy's smallest full extent."""
    if kind == "box":
        return min(size)
    if kind == "cylinder":
        return min(2 * size[0], size[1])
    return 2 * size[0]


def _tuple(v) -> tuple:
    return tuple(v) if isinstance(v, (list, tuple)) else (v,)


def _collision(name: str, o: Origin, kind: str, size: tuple[float, ...], cls: str) -> str:
    if kind == "box":
        sz = _f(*(max(s / 2, 5e-4) for s in size))
        return f'<geom name="{name}" type="box" {o.attrs()} size="{sz}" rgba="0.5 0.5 0.9 0.3" {cls}/>'
    if kind == "cylinder":
        return f'<geom name="{name}" type="cylinder" {o.attrs()} size="{_f(max(size[0], 5e-4), max(size[1] / 2, 5e-4))}" rgba="0.5 0.5 0.9 0.3" {cls}/>'
    return (
        f'<geom name="{name}" type="sphere" {o.attrs()} size="{_f(max(size[0], 5e-4))}" rgba="0.5 0.5 0.9 0.3" {cls}/>'
    )


def instrument_xml(
    urdf: Urdf, joint_cfg: dict[str, dict], default_joint: dict, colliders: list[dict] | tuple = (), prefix: str = "i_"
) -> tuple[str, str]:
    """(assets, body tree) MJCF for an instrument. Bodies are the links with `prefix`, geoms `{prefix}{link}_c{k}`
    (collision) and unnamed (visual); joints keep their URDF names. `joint_cfg` gives a moving joint's damping,
    frictionloss, armature and an optional return spring (stiffness, springref), `default_joint` the same for the
    others. `colliders` adds collision geoms the URDF lacks ({link, type, fromto or pos, size}). Every link is
    gravity-compensated: lids, doors and sashes are counterbalanced or held by their hinges' friction."""
    assets: list[str] = []
    seen_mesh: dict[str, list[MeshPart]] = {}

    def body(link_name: str, j: Joint | None, depth: int) -> str:
        link = urdf.links[link_name]
        head = f'<body name="{prefix}{link_name}" gravcomp="1"'
        if j is not None:
            head += " " + j.origin.attrs()
        s = [head + ">", _inertial(link)]
        if j is not None and j.type in ("revolute", "continuous", "prismatic"):
            cfg = joint_cfg.get(j.name, default_joint)
            jt = "slide" if j.type == "prismatic" else "hinge"
            attrs = f'name="{j.name}" type="{jt}" axis="{_f(*j.axis)}"'
            if j.type != "continuous" and j.lower is not None and j.upper is not None:
                attrs += f' range="{_f(j.lower, j.upper)}" limited="true"'
            attrs += f' damping="{_f(cfg.get("damping", 1.0))}" frictionloss="{_f(cfg.get("frictionloss", 0.5))}"'
            attrs += f' armature="{_f(cfg.get("armature", 0.01))}"'
            if "stiffness" in cfg:
                attrs += f' stiffness="{_f(cfg["stiffness"])}" springref="{_f(cfg.get("springref", 0.0))}"'
            s.append(f"<joint {attrs}/>")
        for k, (o, kind, size) in enumerate(link.collisions):
            if _thickness(kind, size) >= DECAL_M:
                s.append(_collision(f"{prefix}{link_name}_c{k}", o, kind, size, PART))
        for k, c in enumerate(x for x in colliders if x["link"] == link_name):
            where = f'fromto="{_f(*c["fromto"])}"' if "fromto" in c else f'pos="{_f(*c["pos"])}"'
            s.append(
                f'<geom name="{prefix}{link_name}_x{k}" type="{c["type"]}" {where} size="{_f(*_tuple(c["size"]))}" '
                f'rgba="0.5 0.5 0.9 0.3" {PART}/>'
            )
        for k, (o, fname) in enumerate(link.visuals):
            mpath = urdf.path.parent / fname
            key = str(mpath)
            if key not in seen_mesh:
                parts = read_obj(mpath, f"{prefix}{link_name}_v{k}") if mpath.is_file() else []
                seen_mesh[key] = parts
                for p in parts:
                    assets.append(
                        f'<mesh name="{p.name}" vertex="{" ".join(f"{x:.5g}" for x in p.vertices.ravel())}" '
                        f'face="{" ".join(str(int(i)) for i in p.faces.ravel())}" inertia="shell"/>'
                    )
            for p in seen_mesh[key]:
                s.append(f'<geom type="mesh" mesh="{p.name}" {o.attrs()} rgba="{_f(*p.rgba)}" {VISUAL}/>')
        for cj in urdf.children(link_name):
            s.append(body(cj.child, cj, depth + 1))
        s.append("</body>")
        return "".join(s)

    tree = body(urdf.root, None, 0)
    return "".join(assets), tree


# ---------------------------------------------------------------------------------------------------------------------
# the scene: bench, instrument, gripper, cameras
# ---------------------------------------------------------------------------------------------------------------------

# Where the gripper's fingers point. "down": straight down with the fingers closing along y, as in the tabletop suites;
# "forward": horizontally into the instrument (+y), fingers closing along z, as when grasping a horizontal bar on a
# front panel.
APPROACH_QUAT = {
    "down": (1.0, 0.0, 0.0, 0.0),
    "forward": (math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0, 0.0),  # 90 degrees about x: tool axis +y
}


def quat_mul(a, b) -> np.ndarray:
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ]
    )


def hand_quat(approach: str, twist_rad: float) -> np.ndarray:
    """The gripper's orientation: its approach, turned by `twist_rad` about its own tool axis (local -z)."""
    twist = (math.cos(-twist_rad / 2), 0.0, 0.0, math.sin(-twist_rad / 2))  # positive twist: clockwise seen from behind
    return quat_mul(APPROACH_QUAT[approach], twist)


def _look(pos, target) -> str:
    p, t = np.asarray(pos, float), np.asarray(target, float)
    zc = p - t
    zc /= np.linalg.norm(zc)
    xc = np.cross([0, 0, 1.0], zc)
    if np.linalg.norm(xc) < 1e-6:
        xc = np.array([1.0, 0.0, 0.0])
    xc /= np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    return f'pos="{_f(*p)}" xyaxes="{_f(*xc, *yc)}"'


# The gripper: the Franka Hand of MuJoCo Menagerie's Franka Emika Panda, floating.
HAND_MODEL = "franka_emika_panda/panda.xml"  # in the Menagerie folder (robouse.assets); only its hand subtree is used
HAND = "franka/"  # the prefix of every element taken from it
FINGER_OPEN = 0.04  # the Panda's travel per finger (slide joints from 0 to 0.04 m): fully open, the pads are 8 cm apart
GRIP_OPEN_CTRL = 255.0  # the Menagerie hand actuator's control when fully open (0: closed)
# Menagerie's hand actuator pulls the fingers' tendon with 100 N/m, 2 to 4 N near closure: too weak to turn a knob by
# friction. Its gain, stiffness and damping are scaled by 20, as the roboharm suite's are, so that a closed grasp squeezes
# with about 20 to 70 N, the range of the real Franka Hand (70 N continuous, 140 N at most).
GRIP_SCALE = 20.0
GRIP_FORCE_N = 140.0
# The fingers' contact with the instrument (their meshes and pads): the friction, torsional friction and stiffness the
# suite's tasks were built with. The hand body keeps Menagerie's defaults.
FINGER_CONTACT = {"friction": (1.5, 0.02, 0.002), "condim": 4, "solref": (0.01, 1.0)}
# The hand's size as the task instructions give it, in metres (tests/test_chemlab.py measures each on the model). The
# closing direction is the hand's local y, the tool axis its local -z.
HAND_SIZE = {
    "gap": 0.08,  # between the fingertip pads, fully open
    "finger_width": 0.021,  # a finger across the closing direction
    "finger_thickness": 0.024,  # a finger along the closing direction, where it leaves the hand
    "finger_out": 0.046,  # how far the fingers reach out of the hand
    "tip": 0.0094,  # how far the fingertips reach beyond the tool point
    "palm": 0.037,  # how far behind the tool point the hand's body begins
    "hand_length": 0.204,  # the hand's body along the closing direction
    "hand_width": 0.038,  # the hand's body across the closing direction, where the fingers leave it
    "hand_width_max": 0.063,  # and at its widest, 9.5 to 11.5 cm behind the tool point
}


def _menagerie_hand():
    """Menagerie's Panda as a spec with only the meshes its hand subtree uses (the arm's are never loaded)."""
    import mujoco

    from ...assets import asset_root  # a checkout's assets/menagerie, $ROBOUSE_MENAGERIE_ASSETS, or the fetch cache
    from ..menagerie.sim.models import _delete

    panda = mujoco.MjSpec.from_file(str(asset_root() / HAND_MODEL))
    used = {g.meshname for g in panda.body("hand").find_all(mujoco.mjtObj.mjOBJ_GEOM) if g.meshname}
    for mesh in list(panda.meshes):
        if (mesh.name or Path(mesh.file).stem) not in used:  # a mesh without a name is named after its file
            _delete(panda, mesh)
    return panda


def tool_offset(panda) -> float:
    """How far the tool point is from the hand's flange along its fingers: the centre of the fingertip pads (the fingers'
    origin plus the large pad's offset on them), 0.1029 m in Menagerie's model."""
    return float(panda.body("left_finger").pos[2] + panda.find_default("fingertip_pad_collision_1").geom.pos[2])


def attach_hand(spec) -> None:
    """Fix Menagerie's Franka Hand to the scene's floating body `hand`, turned about its closing axis (y) so that its
    fingers point along the body's -z (Menagerie's hand points them along +z), with the fingertip pads' centre at the
    body's origin, and set it up for the scene: every part gravity-compensated, its collision geoms in the gripper's
    collision class, the fingers' contact as the suite's, the actuator's force as the real hand's, and no contact
    between the two fingers."""
    panda = _menagerie_hand()
    hand = panda.body("hand")
    hand.pos, hand.quat = [0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]  # its place on the arm's last link does not apply
    frame = spec.body("hand").add_frame(pos=[0.0, 0.0, tool_offset(panda)], quat=[0.0, 0.0, 1.0, 0.0])
    frame.attach_body(hand, HAND, "")
    fingers = {HAND + "left_finger", HAND + "right_finger"}
    for b in spec.bodies:
        if not b.name.startswith(HAND):
            continue
        b.gravcomp = 1.0
        for g in b.geoms:
            if g.contype == 0 and g.conaffinity == 0:  # a visual mesh
                continue
            g.contype, g.conaffinity = 1, 6  # MOVING: the instrument's parts (2) and the bench and floor (4)
            if b.name in fingers:
                g.friction, g.condim, g.solref = (
                    FINGER_CONTACT["friction"],
                    FINGER_CONTACT["condim"],
                    FINGER_CONTACT["solref"],
                )
    act = spec.actuator(HAND + "actuator8")
    act.gainprm[0] *= GRIP_SCALE
    act.biasprm[1] *= GRIP_SCALE
    act.biasprm[2] *= GRIP_SCALE
    act.forcerange = [-GRIP_FORCE_N, GRIP_FORCE_N]
    spec.add_exclude(bodyname1=HAND + "left_finger", bodyname2=HAND + "right_finger")


def scene_xml(urdf: Urdf, cfg: dict) -> str:
    """The scene for one task without the hand: the bench, the instrument, the cameras, and the gripper's floating body
    (`hand`, at the tool point, with the `tcp` site) welded to its mocap target. `cfg`: joints, default_joint and
    colliders (instrument_xml), bench_half and bench_height, the gripper's approach and home, cameras
    {name: (position, target, fovy)}. scene_model() attaches the hand and compiles it.

    The look: a light grey gradient sky, a plain light grey floor and a lab bench (bench_look), lit by a key light that
    casts shadows, a fill and a rim light, with a dim headlight. The floor and the bench collide through boxes and a
    plane that are not drawn (group 3); what is drawn of them collides with nothing.

    The floating body has a token mass at the tool point: without one its centre of mass is undefined, and MuJoCo would
    size the weld's softness from a point far from the hand, which made the weld pull a tenth as hard."""
    assets, tree = instrument_xml(urdf, cfg.get("joints", {}), cfg.get("default_joint", {}), cfg.get("colliders", ()))
    bx, by = cfg.get("bench_half", (1.0, 0.6))
    bench_h = float(cfg.get("bench_height", 0.9))
    home = cfg.get("home", (0.0, -0.6, 0.3))
    q = hand_quat(cfg.get("approach", "down"), 0.0)
    cams = "".join(f'<camera name="{n}" {_look(p, t)} fovy="{_f(fov)}"/>' for n, (p, t, fov) in cfg["cameras"].items())
    return f"""<mujoco model="robouse-chemlab">
  <compiler angle="radian" autolimits="true" balanceinertia="true"/>
  <option timestep="0.002" cone="elliptic" impratio="10" integrator="implicitfast"><flag multiccd="enable"/></option>
  <visual><global offwidth="1280" offheight="1280"/><quality shadowsize="8192"/><map znear="0.01" zfar="60"/>
    <headlight ambient="0.25 0.25 0.26" diffuse="0.1 0.1 0.1" specular="0 0 0"/></visual>
  <asset>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.80 0.81 0.83" rgb2="0.95 0.95 0.96" width="512" height="3072"/>
    <material name="floor" rgba="0.80 0.805 0.815 1" specular="0.03" shininess="0.05"/>
    <material name="benchtop" rgba="0.19 0.195 0.2 1" specular="0.45" shininess="0.7" reflectance="0.04"/>
    <material name="cabinet" rgba="0.83 0.84 0.85 1" specular="0.05" shininess="0.1"/>
    <material name="plinth" rgba="0.26 0.27 0.28 1" specular="0.03" shininess="0.05"/>
    {assets}
  </asset>
  <worldbody>
    <light name="key" directional="true" dir="0.45 0.75 -1" diffuse="0.55 0.55 0.53" specular="0.12 0.12 0.12" castshadow="true"/>
    <light name="fill" directional="true" dir="-0.7 0.35 -0.55" diffuse="0.2 0.2 0.21" specular="0 0 0" castshadow="false"/>
    <light name="rim" directional="true" dir="0.1 -0.85 -0.5" diffuse="0.12 0.12 0.12" specular="0 0 0" castshadow="false"/>
    <geom name="floor" type="plane" pos="0 0 {-bench_h}" size="6 6 0.1" group="3" {STATIC}/>
    <geom name="floor_look" type="plane" pos="0 0 {-bench_h}" size="40 40 1" material="floor" {VISUAL}/>
    <geom name="bench" type="box" pos="0 0 {-bench_h / 2}" size="{_f(bx, by, bench_h / 2)}" group="3" {STATIC}/>
    {bench_look(bx, by, bench_h)}
    {tree}
    <body name="mocap" mocap="true" pos="{_f(*home)}" quat="{_f(*q)}"/>
    <body name="hand" pos="{_f(*home)}" quat="{_f(*q)}" gravcomp="1"><freejoint name="hand_free"/>
      <inertial pos="0 0 0" mass="0.001" diaginertia="1e-7 1e-7 1e-7"/>
      <site name="tcp" pos="0 0 0" size="0.004" rgba="1 0 0 0"/></body>
    {cams}
  </worldbody>
  <equality><weld body1="mocap" body2="hand" solref="0.01 1"/></equality>
</mujoco>"""


def bench_look(bx: float, by: float, height: float) -> str:
    """How the bench looks, drawn over its collision box (which is not drawn): a lab bench, a dark epoxy-resin top 3 cm
    thick overhanging the cabinet by 2 cm, on a light cabinet with a dark recessed plinth. Visual only: these geoms
    collide with nothing, and the top's upper face is the collision box's, at z = 0."""
    top, over, kick, inset = 0.03, 0.02, 0.1, 0.04
    body = (height - top - kick) / 2
    return (
        f'<geom name="bench_top" type="box" pos="0 0 {_f(-top / 2)}" size="{_f(bx + over, by + over, top / 2)}" '
        f'material="benchtop" {VISUAL}/>'
        f'<geom name="bench_cabinet" type="box" pos="0 0 {_f(-top - body)}" size="{_f(bx, by, body)}" '
        f'material="cabinet" {VISUAL}/>'
        f'<geom name="bench_plinth" type="box" pos="0 0 {_f(-height + kick / 2)}" '
        f'size="{_f(bx - inset, by - inset, kick / 2)}" material="plinth" {VISUAL}/>'
    )


def scene_model(urdf: Urdf, cfg: dict):
    """The compiled scene for one task: scene_xml() with the Franka Hand attached to its floating body."""
    import mujoco

    spec = mujoco.MjSpec.from_string(scene_xml(urdf, cfg))
    attach_hand(spec)
    return spec.compile()
