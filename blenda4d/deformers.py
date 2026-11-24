# SPDX-License-Identifier: GPL-3.0-or-later
"""Deformers: objects that bend, twist or reshape the object they sit under.

A deformer is its own object in the Object Manager, placed as a child of what it deforms. It reaches its parent and
everything under the parent; a deformer under a Null instead reaches its siblings and what is under them. The
deformer's settings are on its Attribute Manager Object page. Moving, turning or sizing the deformer moves its
effect. Box deformers (Bend, Twist, Taper, Bulge, Shear) show their box in the viewport, and the box takes the
deformation too.

How it is wired: each deformer has one Geometry Nodes tree (deformers_nodes.py). Every object it reaches gets a
modifier using that tree; a handler keeps those modifiers matching the hierarchy, in order, switched on or off with
the deformer's check mark. Lattice is Blender's own lattice object and Lattice modifier.

The settings are stored as custom properties on the deformer (b4d_def_*), read by drivers in its tree. So a file
keeps deforming, and keyframes keep playing, in plain Blender and with Blenda mode off."""
import math

import bpy
from mathutils import Matrix, Vector

from . import kinds
from . import deformers_nodes as dn

SCALE = dn.SCALE
LATTICE_TAG = "Blenda: "                # the name prefix of the Lattice modifiers this module manages
BOX_MOD = "Blenda Box"                  # the modifier on a box deformer that draws its own box
TREE = "b4d_deform"                     # custom property: the deformer's node tree

# kind -> (label, icon, object form, tooltip, starting values)
DEFORMERS = {
    "bend": ("Bend", "MOD_SIMPLEDEFORM", "BOX", "Bend the object it sits under along an arc", {}),
    "bulge": ("Bulge", "MOD_CAST", "BOX", "Swell or pinch the middle of the object it sits under", {}),
    "shear": ("Shear", "MOD_SIMPLEDEFORM", "BOX", "Slide the top of the object sideways while the bottom stays", {}),
    "taper": ("Taper", "MOD_SIMPLEDEFORM", "BOX", "Narrow or widen the object toward its top", {}),
    "twist": ("Twist", "MOD_SIMPLEDEFORM", "BOX", "Turn the object more and more from bottom to top", {}),
    "lattice": ("Lattice", "MOD_LATTICE", "LATTICE", "Reshape the object by moving the points of a cage around it",
                {"b4d_def_strength": 100.0}),
    "shrinkwrap": ("Shrinkwrap", "MOD_SHRINKWRAP", "EMPTY", "Pull the object's points onto the surface of a target object",
                   {"b4d_def_strength": 100.0}),
    "smooth": ("Smooth", "MOD_SMOOTH", "EMPTY", "Relax the object's points toward their neighbours",
               {"b4d_def_strength": 100.0}),
    "displace": ("Displace", "MOD_DISPLACE", "EMPTY", "Push the object's points in and out with a noise pattern", {}),
    "wave": ("Wave", "MOD_WAVE", "EMPTY", "Ripple the object with a travelling wave", {}),
}
from . import moclone_deform as _md  # noqa: E402  PolyFX and MoExtrude use this system too
DEFORMERS.update(_md.KINDS)
BOX_KINDS = ("bend", "bulge", "shear", "taper", "twist")
FIT_KINDS = BOX_KINDS + ("lattice",)
ORDER = ("Bend", "Bulge", "Shear", "Taper", "Twist", "Lattice", "Shrinkwrap", "Smooth", "Displace", "Wave")

# setting -> (default, how the field shows). Enum settings are whole numbers, shown through a menu property below.
P = math.pi
SETTINGS = {
    "b4d_def_size": ((250.0, 250.0, 250.0), dict(min=0.01, soft_max=10000.0, precision=1, step=100,
                                                 description="Size of the deformer's box in centimetres; its height "
                                                             "runs along the deformer's own Z")),
    "b4d_def_mode": (0, None),
    "b4d_def_angle": (0.0, dict(subtype="ANGLE", soft_min=-2 * P, soft_max=2 * P,
                                description="How far the deformer turns the object from bottom to top")),
    "b4d_def_direction": (0.0, dict(subtype="ANGLE", soft_min=-2 * P, soft_max=2 * P,
                                    description="Which way, around the deformer's Z, the effect leans")),
    "b4d_def_strength": (0.0, dict(subtype="PERCENTAGE", soft_min=-100.0, soft_max=100.0, precision=1,
                                   description="How strong the effect is")),
    "b4d_def_curvature": (0.0, dict(subtype="PERCENTAGE", min=-99.0, soft_max=300.0, precision=1,
                                    description="0 changes evenly along the box; higher values hold back near the "
                                                "bottom and change faster near the top")),
    "b4d_def_fillet": (False, dict(description="Ease the change in and out at both ends of the box")),
    "b4d_def_keep": (True, dict(description="Bend without stretching; off keeps the two ends the same distance apart")),
    "b4d_def_origin": (0, None),
    "b4d_def_wrap_mode": (0, None),
    "b4d_def_distance": (0.0, dict(min=0.0, soft_max=10000.0, precision=1, step=100,
                                   description="Points farther than this from the target stay where they are "
                                               "(centimetres; 0 = no limit)")),
    "b4d_def_iterations": (10, dict(min=0, soft_max=100, max=1000, description="How many smoothing passes")),
    "b4d_def_height": (20.0, dict(soft_min=-1000.0, soft_max=1000.0, precision=1, step=100,
                                  description="How far points move, in centimetres")),
    "b4d_def_wavelength": (200.0, dict(min=0.1, soft_max=10000.0, precision=1, step=100,
                                       description="Distance from one crest to the next, in centimetres")),
    "b4d_def_speed": (0.0, dict(soft_min=-10.0, soft_max=10.0, precision=2,
                                description="How fast the pattern moves while the animation plays (per second)")),
    "b4d_def_phase": (0.0, dict(subtype="ANGLE", description="Shift the wave along its length")),
    "b4d_def_shape": (0, None),
    "b4d_def_noise_size": (100.0, dict(min=0.1, soft_max=10000.0, precision=1, step=100,
                                       description="Size of the bumps in centimetres; the pattern moves with the "
                                                   "deformer")),
    "b4d_def_detail": (2.0, dict(min=0.0, max=15.0, description="How much finer detail is layered on the bumps")),
    "b4d_def_seed": (0, dict(description="Pick a different pattern")),
    "b4d_def_along": (0, None),
}
KIND_SETTINGS = {k: sorted({path.split("[")[0] for _n, path in dn.VALUES.get(k, [])}) for k in DEFORMERS}
KIND_SETTINGS["shrinkwrap"] = KIND_SETTINGS["shrinkwrap"] + ["b4d_def_target"]
KIND_SETTINGS["lattice"] = ["b4d_def_strength"]


def kind_of(ob):
    k = ob.get("b4d_type") if ob is not None else None
    return k if k in DEFORMERS else None


def is_deformer(ob):
    return kind_of(ob) is not None


def tree_of(ob):
    t = ob.get(TREE) if ob is not None else None
    return t if isinstance(t, bpy.types.NodeTree) else None


def stamp(ob, kind, start=None):
    """Give the deformer every setting its kind reads (a missing one would break the tree's drivers)."""
    added = False
    for key in KIND_SETTINGS[kind]:
        if key in ob:
            continue
        added = True
        if key == "b4d_def_target":
            ob[key] = None
            continue
        default, ui = SETTINGS[key]
        v = (start or {}).get(key, default)
        ob[key] = list(v) if isinstance(v, tuple) else v
        if ui:
            ob.id_properties_ui(key).update(default=default, **ui)
    if kind == "shrinkwrap":
        try:
            ob.id_properties_ui("b4d_def_target").update(id_type="OBJECT", description="The surface to wrap onto")
        except (TypeError, KeyError):
            pass
    return added


def value(ob, key):
    v = ob.get(key, SETTINGS[key][0] if key in SETTINGS else None)
    return tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v


# --- which objects a deformer reaches ----------------------------------------------------------------------------
def targets(deformer):
    """Its parent and everything under the parent; under a non-mesh parent (a Null), its siblings and what is under
    them. Other deformers and what sits under them are skipped."""
    parent = deformer.parent
    if parent is None:
        return []
    roots = [parent] if parent.type == "MESH" else [c for c in parent.children if not is_deformer(c)]
    out = []

    def walk(ob):
        if ob.type == "MESH" and not is_deformer(ob):
            out.append(ob)
        for c in ob.children:
            if not is_deformer(c):
                walk(c)
    for r in roots:
        walk(r)
    return out


def _depth(mesh, deformer):
    """How far up from the mesh the deformer's parent is: nearer deformers act first."""
    n, p = 0, mesh
    while p is not None and p != deformer.parent:
        p, n = p.parent, n + 1
    return n


# --- keeping the modifiers in step -------------------------------------------------------------------------------
def _slot(m, name):
    """(owner, attribute) of a node modifier's input: Blender 5 keeps them in m.properties.inputs, older ones as an
    ID property m[identifier]."""
    ident = dn.socket_id(m.node_group, name)
    props = getattr(m, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        slot = getattr(props.inputs, ident, None)
        if slot is None:
            raise KeyError(name)
        return slot, "value"
    return m, f'["{ident}"]'


def _get(m, name):
    owner, attr = _slot(m, name)
    return owner.path_resolve(attr) if attr.startswith("[") else getattr(owner, attr)


def _put(m, name, v):
    owner, attr = _slot(m, name)
    if attr.startswith("["):
        owner[attr[2:-2]] = v
    else:
        setattr(owner, attr, v)


def _owner(m):
    """The deformer a modifier belongs to (None when it is not one of ours, False when its deformer is gone)."""
    if m.type == "NODES" and m.node_group is not None and m.node_group.get("b4d_deformer"):
        try:
            ob = _get(m, "Deformer")
            own = _get(m, "Own Box")
        except KeyError:
            return False
        if own:
            return None
        return ob if ob is not None else False
    if m.type == "LATTICE" and m.name.startswith(LATTICE_TAG):
        return m.object if m.object is not None else False
    return None


def _set(owner, attr, v):
    """Writing an unchanged value would tag the object and start the sync again."""
    if getattr(owner, attr) != v:
        setattr(owner, attr, v)


def _drives(tree, ob):
    ad = tree.animation_data
    return bool(ad) and any(t.id == ob for fc in ad.drivers for var in fc.driver.variables for t in var.targets)


def _ensure_tree(ob, kind, seen):
    if stamp(ob, kind):
        ob.update_tag()
    tree = tree_of(ob)
    if tree is None:
        tree = dn.build(ob, kind, DEFORMERS[kind][0])
        ob[TREE] = tree
    elif kind in _md.FILL and list(ob.get(_md.SIG, [])) != _md.signature(ob):   # its Effectors list changed
        _md.refill(tree, ob, kind)
    elif tree.name in seen or not _drives(tree, ob):         # a copied deformer: give it a tree of its own
        if kind in _md.FILL:                                 # its drivers also read its effectors: build it afresh
            tree = dn.build(ob, kind, DEFORMERS[kind][0])
        else:
            tree = tree.copy()
            dn.retarget(tree, ob)
        ob[TREE] = tree
    seen.add(tree.name)
    if kind == "shrinkwrap":
        n = dn.target_info(tree)
        t = ob.get("b4d_def_target")
        t = t if isinstance(t, bpy.types.Object) and t.type == "MESH" and t != ob else None
        if n is not None and n.inputs["Object"].default_value != t:
            n.inputs["Object"].default_value = t
    if kind in BOX_KINDS:
        m = ob.modifiers.get(BOX_MOD)
        if m is None:
            m = ob.modifiers.new(BOX_MOD, "NODES")
        if m.node_group != tree:
            m.node_group = tree
        if not _get(m, "Own Box"):
            _put(m, "Own Box", True)
            ob.update_tag()
    return tree


def _add(mesh, d):
    kind = kind_of(d)
    if kind == "lattice":
        m = mesh.modifiers.new(LATTICE_TAG + d.name, "LATTICE")
        m.object = d
    else:
        m = mesh.modifiers.new(DEFORMERS[kind][0], "NODES")
        m.node_group = tree_of(d)
        _put(m, "Deformer", d)
    m.show_expanded = False
    return m


def sync(scene):
    deformers = [ob for ob in scene.objects if is_deformer(ob)]
    seen = set()
    wanted = {}
    for d in deformers:
        kind = kind_of(d)
        if kind == "lattice":
            stamp(d, kind)
        else:
            _ensure_tree(d, kind, seen)
        for t in targets(d):
            wanted.setdefault(t, []).append(d)
    for mesh in scene.objects:
        if mesh.type != "MESH" or is_deformer(mesh):
            continue
        own = sorted(wanted.get(mesh, []), key=lambda d: (_depth(mesh, d), d.name))
        ours = []
        for m in list(mesh.modifiers):
            o = _owner(m)
            if o is None:
                continue
            if o is False or o not in own or o in [x for _, x in ours] or \
                    (m.type == "NODES" and m.node_group != tree_of(o)):
                mesh.modifiers.remove(m)
                continue
            ours.append((m, o))
        have = [o for _, o in ours]
        if have != own[:len(have)]:                  # out of order: put them all back in order at the end
            for m, _ in ours:
                mesh.modifiers.remove(m)
            ours, have = [], []
        for d in own[len(have):]:
            ours.append((_add(mesh, d), d))
        for m, d in ours:
            on = bool(d.get("_b4d_enabled", True))
            _set(m, "show_viewport", on)
            _set(m, "show_render", on)
            if m.type == "LATTICE":
                _set(m, "strength", float(value(d, "b4d_def_strength")) / 100.0)
                if m.name != LATTICE_TAG + d.name:
                    m.name = LATTICE_TAG + d.name


_busy = [False]


@bpy.app.handlers.persistent
def _on_update(scene, depsgraph=None):
    if _busy[0]:
        return
    _busy[0] = True
    try:
        sync(scene)
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        _busy[0] = False


# --- making one ----------------------------------------------------------------------------------------------------
def _evaluated_bounds(ob, context):
    """The parent's bounds as it shows, but without the deformers on it (they would fit the box to the bent shape)."""
    off = [m for m in ob.modifiers if _owner(m) is not None and m.show_viewport]
    for m in off:
        m.show_viewport = False
    dg = context.evaluated_depsgraph_get()
    dg.update()
    pts = [Vector(c) for c in ob.evaluated_get(dg).bound_box]
    for m in off:
        m.show_viewport = True
    return pts


def fit_to_parent(ob, context):
    """Size the box to the parent's bounds and put the deformer at their centre, upright."""
    parent = ob.parent
    if parent is None or parent.type != "MESH":
        return False
    pts = _evaluated_bounds(parent, context)
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.location = (lo + hi) / 2
    ob.rotation_euler = (0.0, 0.0, 0.0)
    if ob.rotation_mode == "QUATERNION":
        ob.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    size = [max(c, 0.01) for c in hi - lo]
    if kind_of(ob) == "lattice":
        ob.scale = size                                  # a lattice's cage is its scale
    else:
        ob.scale = (1.0, 1.0, 1.0)
        ob["b4d_def_size"] = [c / SCALE for c in size]
        ob.update_tag()
    return True


def make(context, kind, parent=None):
    label, _icon, form, _tip, start = DEFORMERS[kind]
    data = None
    if form == "BOX":
        data = dn.box_mesh(label)
    elif form == "LATTICE":
        data = bpy.data.lattices.new(label)
        data.points_u = data.points_v = data.points_w = 3
        for a in ("interpolation_type_u", "interpolation_type_v", "interpolation_type_w"):
            setattr(data, a, "KEY_BSPLINE")
    ob = bpy.data.objects.new(label, data)
    ob["b4d_type"] = kind
    coll = parent.users_collection[0] if parent is not None and parent.users_collection else context.collection
    coll.objects.link(ob)
    if form == "BOX":
        ob.display_type = "WIRE"                         # loose edges only: it never shows in a render
    elif form == "EMPTY":
        ob.empty_display_type = "PLAIN_AXES"
        ob.empty_display_size = 0.5
    elif form == "LATTICE":
        ob.scale = (2.5, 2.5, 2.5)
    stamp(ob, kind, start)
    if parent is not None:
        ob.parent = parent
        ob.matrix_parent_inverse = Matrix.Identity(4)
    if kind in FIT_KINDS:
        fit_to_parent(ob, context)
    if kind != "lattice":
        ob[TREE] = dn.build(ob, kind, label)
    sync(context.scene)
    return ob


def _creator(kind):
    def create(context):
        active = context.view_layer.objects.active
        parent = active if active is not None and active.select_get() else None
        if parent is not None and is_deformer(parent):          # a deformer selected: the new one goes beside it
            parent = parent.parent
        return make(context, kind, parent)
    return create


# --- menu settings (stored as whole numbers in the custom properties) -------------------------------------------
MENU_TIPS = {"b4d_def_mode": "Where the deformer acts: inside its box, or beyond it too",
             "b4d_def_origin": "The point the deformer works from",
             "b4d_def_wrap_mode": "How the object is wrapped around the shape",
             "b4d_def_shape": "The shape the object is wrapped onto",
             "b4d_def_along": "The direction the effect runs along"}


def _menu(key, name, items):
    items = tuple((ident, label, tip, i) for i, (ident, label, tip) in enumerate(items))

    def get(self):
        return int(self.get(key, 0))

    def put(self, v):
        self[key] = int(v)
        self.update_tag()
    return bpy.props.EnumProperty(name=name, items=items, get=get, set=put, description=MENU_TIPS.get(key, name))


def _lattice_size_get(self):
    return tuple(c / SCALE for c in self.scale)


def _lattice_size_set(self, v):
    self.scale = tuple(max(c * SCALE, 1e-4) for c in v)


def _interp_get(self):
    d = self.data if self.type == "LATTICE" else None
    return ("KEY_LINEAR", "KEY_CARDINAL", "KEY_BSPLINE").index(d.interpolation_type_u) if d else 2


def _interp_set(self, v):
    if self.type == "LATTICE":
        for a in ("interpolation_type_u", "interpolation_type_v", "interpolation_type_w"):
            setattr(self.data, a, ("KEY_LINEAR", "KEY_CARDINAL", "KEY_BSPLINE")[v])


def _menus():
    return {
        "b4d_def_mode": _menu("b4d_def_mode", "Mode", (
            ("LIMITED", "Limited", "Deform inside the box; beyond it the object carries on unchanged in shape"),
            ("WITHIN", "Within Box", "Deform only the points inside the box"),
            ("UNLIMITED", "Unlimited", "The effect carries on past the ends of the box"))),
        "b4d_def_origin": _menu("b4d_def_origin", "Origin", (
            ("BOTTOM", "Bottom", "The bottom stays put and the top bends"),
            ("CENTER", "Center", "The middle stays put and both ends bend the same way"),
            ("CENTER_S", "Center (S Shape)", "The middle stays put and the ends bend opposite ways"),
            ("TOP", "Top", "The top stays put and the bottom bends"))),
        "b4d_def_wrap_mode": _menu("b4d_def_wrap_mode", "Mode", (
            ("NEAREST", "Nearest Surface", "Each point goes to the closest place on the target"),
            ("NORMAL", "Along Normals", "Each point travels along its own normal until it meets the target"),
            ("AXIS", "Along Deformer Z", "Each point travels along the deformer's Z until it meets the target"))),
        "b4d_def_shape": _menu("b4d_def_shape", "Shape", (
            ("LINEAR", "Straight", "Crests run in straight lines across the deformer's X"),
            ("RIPPLE", "Ripple", "Crests run in rings around the deformer"))),
        "b4d_def_along": _menu("b4d_def_along", "Direction", (
            ("NORMAL", "Along Normals", "Points move straight out from the surface"),
            ("AXIS", "Along Deformer Z", "Points move along the deformer's Z"))),
        "b4d_def_grid": bpy.props.FloatVectorProperty(
            name="Grid Size", size=3, get=_lattice_size_get, set=_lattice_size_set, precision=1, step=100,
            description="Size of the lattice cage in centimetres"),
        "b4d_def_interp": bpy.props.EnumProperty(name="Interpolation", description="How the effect eases between its ends", get=_interp_get, set=_interp_set, items=(
            ("KEY_LINEAR", "Linear", "Straight between grid points", 0),
            ("KEY_CARDINAL", "Cardinal", "Curved, passing close to the points", 1),
            ("KEY_BSPLINE", "Smooth", "Smooth and soft", 2))),
    }


# --- operators ----------------------------------------------------------------------------------------------------
class BLENDA4D_OT_deformer_fit(bpy.types.Operator):
    bl_idname = "blenda4d.deformer_fit"
    bl_label = "Fit Box to Object"
    bl_description = "Size the deformer's box to the object it sits under and centre it there"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return kind_of(context.active_object) in FIT_KINDS

    def execute(self, context):
        if not fit_to_parent(context.active_object, context):
            self.report({"WARNING"}, "The deformer is not under a polygon object")
            return {"CANCELLED"}
        return {"FINISHED"}


class BLENDA4D_OT_lattice_reset(bpy.types.Operator):
    bl_idname = "blenda4d.lattice_reset"
    bl_label = "Reset Points"
    bl_description = "Put every point of the lattice back on its even grid"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return kind_of(context.active_object) == "lattice"

    def execute(self, context):
        ob = context.active_object
        editing = ob.mode == "EDIT"
        if editing:                                     # edit mode keeps its own copy of the points
            bpy.ops.object.mode_set(mode="OBJECT")
        d = ob.data
        nu, nv, nw = d.points_u, d.points_v, d.points_w
        for i, p in enumerate(d.points):
            u, v, w = i % nu, (i // nu) % nv, i // (nu * nv)
            p.co_deform = tuple((k / (n - 1) - 0.5) if n > 1 else 0.0 for k, n in ((u, nu), (v, nv), (w, nw)))
        d.update_tag()
        if editing:
            bpy.ops.object.mode_set(mode="EDIT")
        return {"FINISHED"}


# --- Attribute Manager pages ---------------------------------------------------------------------------------------
def _row(col, ob, key, text):
    if key in ob:
        col.prop(ob, f'["{key}"]', text=text)


def _size_rows(col, ob):
    if "b4d_def_size" not in ob:
        return
    sub = col.column(align=True)
    for i, a in enumerate("XYZ"):
        sub.prop(ob, '["b4d_def_size"]', index=i, text=f"Size . {a}")


def _fit_row(col):
    col.separator()
    col.operator("blenda4d.deformer_fit", icon="SHADING_BBOX")


def _not_reaching(col, ob):
    if ob.parent is None:
        col.label(text="Put it under an object to deform it", icon="INFO")


def page_box(col, ob):
    kind = kind_of(ob)
    _size_rows(col, ob)
    col.prop(ob, "b4d_def_mode", text="Mode")
    col.separator()
    if kind == "bend":
        _row(col, ob, "b4d_def_angle", "Strength")
        _row(col, ob, "b4d_def_direction", "Direction")
        _row(col, ob, "b4d_def_keep", "Keep Length")
        col.prop(ob, "b4d_def_origin", text="Origin")
    elif kind == "twist":
        _row(col, ob, "b4d_def_angle", "Angle")
    else:
        _row(col, ob, "b4d_def_strength", "Strength")
        if kind == "shear":
            _row(col, ob, "b4d_def_direction", "Direction")
        _row(col, ob, "b4d_def_curvature", "Curvature")
        _row(col, ob, "b4d_def_fillet", "Soft Ends")
    _fit_row(col)
    _not_reaching(col, ob)


def page_lattice(col, ob):
    sub = col.column(align=True)
    for i, a in enumerate("XYZ"):
        sub.prop(ob, "b4d_def_grid", index=i, text=f"Grid Size . {a}")
    d = ob.data
    if d is not None:
        sub = col.column(align=True)
        sub.prop(d, "points_u", text="Grid Points . X")
        sub.prop(d, "points_v", text="Grid Points . Y")
        sub.prop(d, "points_w", text="Grid Points . Z")
    col.prop(ob, "b4d_def_interp", text="Interpolation")
    _row(col, ob, "b4d_def_strength", "Strength")
    _fit_row(col)
    col.operator("blenda4d.lattice_reset", icon="FILE_REFRESH")
    _not_reaching(col, ob)


def page_shrinkwrap(col, ob):
    _row(col, ob, "b4d_def_target", "Target")
    col.prop(ob, "b4d_def_wrap_mode", text="Mode")
    _row(col, ob, "b4d_def_strength", "Strength")
    _row(col, ob, "b4d_def_distance", "Max Distance")
    if not isinstance(ob.get("b4d_def_target"), bpy.types.Object):
        col.label(text="Pick the object to wrap onto", icon="INFO")
    _not_reaching(col, ob)


def page_smooth(col, ob):
    _row(col, ob, "b4d_def_strength", "Strength")
    _row(col, ob, "b4d_def_iterations", "Iterations")
    _not_reaching(col, ob)


def page_displace(col, ob):
    _row(col, ob, "b4d_def_height", "Height")
    _row(col, ob, "b4d_def_noise_size", "Pattern Size")
    _row(col, ob, "b4d_def_detail", "Detail")
    _row(col, ob, "b4d_def_seed", "Seed")
    _row(col, ob, "b4d_def_speed", "Animation Speed")
    col.prop(ob, "b4d_def_along", text="Direction")
    _not_reaching(col, ob)


def page_wave(col, ob):
    _row(col, ob, "b4d_def_height", "Amplitude")
    _row(col, ob, "b4d_def_wavelength", "Wavelength")
    _row(col, ob, "b4d_def_speed", "Speed")
    _row(col, ob, "b4d_def_phase", "Phase")
    col.prop(ob, "b4d_def_shape", text="Shape")
    _not_reaching(col, ob)


PAGES = {**{k: page_box for k in BOX_KINDS}, "lattice": page_lattice, "shrinkwrap": page_shrinkwrap,
         "smooth": page_smooth, "displace": page_displace, "wave": page_wave}


# --- registration -----------------------------------------------------------------------------------------------------
classes = (BLENDA4D_OT_deformer_fit, BLENDA4D_OT_lattice_reset)
_registered = []


def register():
    for name, prop in _menus().items():
        setattr(bpy.types.Object, name, prop)
        _registered.append(name)
    for c in classes:
        bpy.utils.register_class(c)
    for kind in DEFORMERS:
        label, icon, _form, tip, _start = DEFORMERS[kind]
        if kind in _md.KINDS:
            _md.register_kind(kind, _creator(kind))
            continue
        kinds.add(kind, label, icon, create=_creator(kind), tabs=[("OBJECT", "Object")], pages={"OBJECT": PAGES[kind]},
                  describe=tip + " (with an object selected, it goes under that object)")
    by_label = {DEFORMERS[k][0]: k for k in DEFORMERS}
    for label in ORDER:
        kinds.create_button("deformers", label, by_label[label])
        kinds.menu_item("Create", label, by_label[label])
    for h in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post):
        if _on_update not in h:
            h.append(_on_update)


def unregister():
    for h in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post):
        if _on_update in h:
            h.remove(_on_update)
    for kind in DEFORMERS:
        kinds.KINDS.pop(kind, None)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    for name in _registered:
        if hasattr(bpy.types.Object, name):
            delattr(bpy.types.Object, name)
    _registered.clear()
