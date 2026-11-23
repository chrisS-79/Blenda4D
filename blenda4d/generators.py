# SPDX-License-Identifier: GPL-3.0-or-later
"""Generators: objects in the Object Manager that are made from their children.

Two kinds of generator:
- Node generators (Extrude, Lathe, Sweep, Loft, Symmetry, Array, Instance, Connect, Boolean): a mesh object with one
  Geometry Nodes modifier whose group is built for that object from its children (generators_nodes.py). The children
  are read live; when children are added, removed or renamed the group is built again (settings kept).
  Symmetry, Array, Connect and Boolean hide their mesh children (shown as a wire so they stay selectable).
- Modifier generators (Subdivision Surface, Reduce Polygons, Remesh): an empty whose mesh descendants get a Blender
  modifier kept in step with the generator's settings; taking a mesh out of the generator removes its modifier.

Create > generator with objects selected puts them under it: the generator takes the first object's place in the
hierarchy. sync() runs after every scene update and keeps all of this in step."""
import bpy
from mathutils import Matrix

from . import generators_nodes as gn
from . import kinds

GEN_MOD = "Blenda Generator"
MOD_KINDS = ("subdivision", "reduce", "remesh")
NODE_KINDS = tuple(gn.KINDS)
ICONS = {"subdivision": "MOD_SUBSURF", "extrude": "MOD_SOLIDIFY", "lathe": "MOD_SCREW", "loft": "MOD_SKIN", "sweep": "MOD_CURVE",
         "boolean": "MOD_BOOLEAN", "connect": "AUTOMERGE_OFF", "symmetry": "MOD_MIRROR", "instance": "OUTLINER_OB_GROUP_INSTANCE",
         "array": "MOD_ARRAY", "remesh": "MOD_REMESH", "reduce": "MOD_DECIM", "metaball": "META_BALL"}
LABELS = {"subdivision": "Subdivision Surface", "reduce": "Reduce Polygons", "remesh": "Remesh"}
LABELS.update({k: v[0] for k, v in gn.KINDS.items()})
TIPS = {"subdivision": "Smooths the objects placed under it",
        "extrude": "Turns the spline under it into a solid with depth",
        "lathe": "Spins the spline under it around the vertical axis",
        "loft": "Stretches a skin across the splines under it, in order",
        "sweep": "Moves the first spline under it along the second",
        "boolean": "Joins or cuts the objects under it: the first is the base, the rest act on it",
        "connect": "Joins the objects under it into one",
        "symmetry": "Mirrors the objects under it across a plane through its own origin",
        "instance": "Shows a live copy of another object",
        "array": "Places copies of the objects under it in a ring",
        "remesh": "Rebuilds the objects under it as an even mesh",
        "reduce": "Lowers the polygon count of the objects under it",
        "metaball": "Melts the points of the objects under it into one soft surface"}
SUB_MOD, SUB_PRE, RED_MOD, RM_MOD, RM_SMOOTH = "Blenda Subdivision", "Blenda Pre-Subdivision", "Blenda Reduce", "Blenda Remesh", "Blenda Remesh Smooth"


def kind(ob):
    k = ob.get("b4d_type") if ob is not None else None
    return k if k in MOD_KINDS or k in NODE_KINDS else None


def enabled(ob):
    return bool(ob.get("_b4d_enabled", True))


def gen_mod(ob):
    return ob.modifiers.get(GEN_MOD) if ob is not None else None


def slot(ob, name):
    """(owner, attribute) of a node generator's setting, or None."""
    from .primitives import input_slot
    mod = gen_mod(ob)
    if mod is None or mod.node_group is None or name not in mod.node_group.interface.items_tree:
        return None
    try:
        return input_slot(mod, mod.node_group.interface.items_tree[name].identifier)
    except (KeyError, AttributeError):
        return None


def gval(ob, name):
    s = slot(ob, name)
    return getattr(*s) if s else None


def kids_of(gen):
    """Children in Object Manager order (by name, as the Object Manager lists them)."""
    return sorted(gen.children, key=lambda c: c.name)


def generator_of(ob, want):
    """The nearest modifier generator of kind `want` above ob. A node generator that hides its children stops the
    search: its own result gets the modifier instead (otherwise it would be applied twice)."""
    p = ob.parent
    while p is not None:
        k = p.get("b4d_type")
        if k == want:
            return p
        if k in NODE_KINDS and gn.KINDS[k][3]:
            return None
        p = p.parent
    return None


# --- creation ----------------------------------------------------------------------------------------------------

def wrap(gen, targets):
    """Put gen above targets: it takes the first one's place in the hierarchy; they keep their place in the world."""
    first = targets[0]
    gen.parent = first.parent
    gen.matrix_parent_inverse = Matrix.Identity(4)
    gen.matrix_world = Matrix.Identity(4)
    for t in targets:
        mw = t.matrix_world.copy()
        t.parent = gen
        t.matrix_parent_inverse = Matrix.Identity(4)
        t.matrix_world = mw


def _selection(context):
    sel = list(context.selected_objects)
    active = context.view_layer.objects.active
    if active in sel:
        sel.remove(active)
        sel.insert(0, active)
    ids = set(sel)
    out = []
    for o in sel:                                   # an object whose parent is selected too moves with it
        p = o.parent
        while p is not None and p not in ids:
            p = p.parent
        if p is None:
            out.append(o)
    return out


def create(context, k):
    from .primitives import tidy_name
    sel = _selection(context)
    label = LABELS[k]
    if k in MOD_KINDS:
        gen = bpy.data.objects.new(label, None)
        gen.empty_display_type = "PLAIN_AXES"
        gen.empty_display_size = 0.0001                 # the generator itself draws nothing; its result is on the children
    else:
        gen = bpy.data.objects.new(label, bpy.data.meshes.new(label))
    context.collection.objects.link(gen)
    gen["b4d_type"] = k
    tidy_name(gen)
    if k == "instance":
        gen.location = context.scene.cursor.location
        rebuild(gen)
        if sel:
            gen.matrix_world = sel[0].matrix_world.copy()
            s = slot(gen, "Reference Object")
            if s:
                setattr(*s, sel[0])
    else:
        if sel:
            wrap(gen, sel)
        else:
            gen.location = context.scene.cursor.location
        if k in NODE_KINDS:
            rebuild(gen)
    sync_all()
    return gen


# --- node generators -----------------------------------------------------------------------------------------

def connect_members(gen):
    """Connect joins its whole hierarchy (and the object in its Objects field); a generator counts as one member."""
    out = []

    def walk(ob):
        if ob.type in ("MESH", "CURVE", "FONT"):
            out.append(ob)
        if ob.get("b4d_type") not in NODE_KINDS:
            for c in kids_of(ob):
                walk(c)
    link = gval(gen, "Objects")
    for ob in kids_of(gen) + ([link] if link is not None and link != gen else []):
        walk(ob)
    return out


def _closed(ob):
    splines = getattr(getattr(ob, "data", None), "splines", None)
    return bool(splines) and all(sp.use_cyclic_u for sp in splines)


def inputs_of(gen):
    k = gen.get("b4d_type")
    if k == "connect":
        return connect_members(gen)
    kids = kids_of(gen)
    if k == "sweep" and len(kids) >= 2 and kids[0].type == kids[1].type == "CURVE" and not _closed(kids[0]) and _closed(kids[1]):
        kids[0], kids[1] = kids[1], kids[0]          # the closed spline is the shape, the open one the path, whatever their names
    return kids


def rebuild(gen):
    k = gen["b4d_type"]
    kids = inputs_of(gen)
    mod = gen_mod(gen)
    if mod is None:
        mod = gen.modifiers.new(GEN_MOD, "NODES")
    old = {}
    if mod.node_group is not None:
        from .primitives import input_slot
        for it in mod.node_group.interface.items_tree:
            if it.item_type == "SOCKET" and it.in_out == "INPUT":
                try:
                    owner, attr = input_slot(mod, it.identifier)
                    v = getattr(owner, attr)
                    old[it.name] = tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v     # copied: the swap frees it
                except Exception:
                    pass
    tree = gn.make_group(f"Blenda {LABELS[k]} [{gen.name}]", k, kids, gen.name)
    mod.node_group = tree
    from .primitives import set_input
    for name, v in old.items():
        if name in tree.interface.items_tree:
            try:
                set_input(mod, tree.interface.items_tree[name].identifier, v)
            except Exception:
                pass
    gen["b4d_kids"] = [o.name for o in kids]
    if k in ("cloner", "matrix"):
        from . import moclone_fx
        gen["b4d_fx_sig"] = moclone_fx.signature(gen)
    gen.update_tag()


def _needs_rebuild(gen):
    mod = gen_mod(gen)
    if mod is None or mod.node_group is None or mod.node_group.get("b4d_owner") != gen.name:
        return True
    if gen.get("b4d_type") in ("cloner", "matrix"):
        from . import moclone_fx
        if list(gen.get("b4d_fx_sig", [])) != moclone_fx.signature(gen):
            return True
    return list(gen.get("b4d_kids", [])) != [o.name for o in inputs_of(gen)]


def _consume(ob):
    if "b4d_consumed" in ob:
        return
    ob["b4d_consumed"] = {"display": ob.display_type, "render": int(ob.hide_render)}
    ob.display_type = "WIRE"
    ob.hide_render = True


def _release(ob):
    was = ob.get("b4d_consumed")
    if was is None:
        return
    # Copy the values out before deleting the property: `was` points into it, and reading it after the delete
    # reads freed memory (it crashed Blender on Linux).
    try:
        display, render = str(was.get("display", "TEXTURED")), bool(was.get("render", 0))
    except (TypeError, AttributeError):
        display, render = "TEXTURED", False
    del ob["b4d_consumed"]
    try:
        ob.display_type = display
    except TypeError:
        ob.display_type = "TEXTURED"
    ob.hide_render = render


def sync_nodes(scene):
    keep = set()
    for gen in scene.objects:
        k = gen.get("b4d_type")
        if k not in NODE_KINDS:
            continue
        if _needs_rebuild(gen):
            rebuild(gen)
        if gn.KINDS[k][3] and enabled(gen):
            for o in inputs_of(gen):
                if o.type == "MESH":
                    keep.add(o.name)
                    _consume(o)
    for ob in scene.objects:
        if "b4d_consumed" in ob and ob.name not in keep:
            _release(ob)


# --- modifier generators -------------------------------------------------------------------------------------

def _apply(mod, want):
    for key, v in want.items():
        cur = getattr(mod, key)
        if isinstance(v, float) and isinstance(cur, float):
            if abs(cur - v) <= 0.02 * max(abs(v), 1e-6):     # small drift (Remesh reads the object's size) does not re-set it
                continue
        elif cur == v:
            continue
        setattr(mod, key, v)


def _ensure(ob, name, mtype):
    m = ob.modifiers.get(name)
    if m is None:
        m = ob.modifiers.new(name, mtype)
    return m


def _drop(ob, *names):
    for n in names:
        m = ob.modifiers.get(n)
        if m is not None:
            ob.modifiers.remove(m)


def sync_subdivision(ob):
    gen = generator_of(ob, "subdivision")
    if gen is None:
        return _drop(ob, SUB_PRE, SUB_MOD)
    on = enabled(gen)
    pre = ob.modifiers.get(SUB_PRE)
    if gen.b4d_sub_pre > 0:
        if pre is None:
            pre = ob.modifiers.new(SUB_PRE, "SUBSURF")
            main = ob.modifiers.get(SUB_MOD)
            if main is not None:
                ob.modifiers.move(len(ob.modifiers) - 1, list(ob.modifiers).index(main))
        _apply(pre, {"subdivision_type": "SIMPLE", "levels": gen.b4d_sub_pre, "render_levels": gen.b4d_sub_pre,
                     "show_viewport": on, "show_render": on})
    elif pre is not None:
        ob.modifiers.remove(pre)
    _apply(_ensure(ob, SUB_MOD, "SUBSURF"), {
        "subdivision_type": gen.b4d_sub_type, "levels": gen.b4d_sub_view, "render_levels": gen.b4d_sub_render,
        "uv_smooth": gen.b4d_sub_uv, "boundary_smooth": gen.b4d_sub_boundary, "use_creases": gen.b4d_sub_creases,
        "show_only_control_edges": False, "show_viewport": on, "show_render": on})


def sync_reduce(ob):
    gen = generator_of(ob, "reduce")
    if gen is None:
        return _drop(ob, RED_MOD)
    on = enabled(gen)
    m = _ensure(ob, RED_MOD, "DECIMATE")
    _apply(m, {"decimate_type": "COLLAPSE", "ratio": max(0.0, 1.0 - gen.b4d_red_strength / 100.0),
               "use_collapse_triangulate": gen.b4d_red_triangulate, "use_symmetry": gen.b4d_red_symmetry,
               "symmetry_axis": gen.b4d_red_axis, "show_viewport": on, "show_render": on})


def sync_remesh(ob):
    gen = generator_of(ob, "remesh")
    if gen is None:
        return _drop(ob, RM_MOD, RM_SMOOTH)
    on = enabled(gen)
    size = max(ob.dimensions) if max(ob.dimensions) > 0 else 1.0
    if gen.b4d_rm_target == "COUNT":            # n polygons over a surface ~ size / sqrt(n) per block
        voxel = size / max(2.0, float(max(1, gen.b4d_rm_count)) ** 0.5)
    else:                                       # Density 100 % ~ 20 blocks across the object
        voxel = size / max(2.0, 20.0 * gen.b4d_rm_density / 100.0)
    _apply(_ensure(ob, RM_MOD, "REMESH"), {"mode": "VOXEL", "voxel_size": max(0.005, voxel), "use_smooth_shade": False,
                                           "show_viewport": on, "show_render": on})
    if gen.b4d_rm_smooth > 0:
        _apply(_ensure(ob, RM_SMOOTH, "SMOOTH"), {"iterations": gen.b4d_rm_smooth, "factor": 0.5, "show_viewport": on, "show_render": on})
    else:
        _drop(ob, RM_SMOOTH)


def sync_modifiers(scene):
    for ob in scene.objects:
        if ob.type != "MESH":
            continue
        if generator_of(ob, "subdivision") is not None or SUB_MOD in ob.modifiers or SUB_PRE in ob.modifiers:
            sync_subdivision(ob)
        if generator_of(ob, "reduce") is not None or RED_MOD in ob.modifiers:
            sync_reduce(ob)
        if generator_of(ob, "remesh") is not None or RM_MOD in ob.modifiers or RM_SMOOTH in ob.modifiers:
            sync_remesh(ob)


# --- sync ------------------------------------------------------------------------------------------------------

_busy = [False]


def sync(scene):
    if _busy[0] or scene is None:
        return
    _busy[0] = True
    try:
        sync_nodes(scene)
        sync_modifiers(scene)
    finally:
        _busy[0] = False


def sync_all():
    sync(bpy.context.scene)


@bpy.app.handlers.persistent       # opening a file drops handlers that are not persistent
def _on_update(scene, depsgraph=None):
    sync(scene)


def _update(self, context):
    sync_all()


# --- Attribute Manager pages -----------------------------------------------------------------------------------
# a row: (socket, label) or (socket, label, active-when(value_of)); None = a gap; ("#", text) = a heading

def _rows(col, ob, rows):
    def value(name):
        return gval(ob, name)
    for r in rows:
        if r is None:
            col.separator()
            continue
        if r[0] == "#":
            col.label(text=r[1])
            continue
        s = slot(ob, r[0])
        if s is None:
            continue
        owner, attr = s
        try:
            v = getattr(owner, attr)
        except AttributeError:
            continue
        holder = col.column(align=True)
        if len(r) > 2 and r[2] is not None:
            holder.active = bool(r[2](value))
        if hasattr(v, "__len__") and not isinstance(v, str) and len(v) == 4:      # a colour: one swatch
            holder.prop(owner, attr, text=r[1])
        elif hasattr(v, "__len__") and not isinstance(v, str):
            for i, axis in enumerate("XYZ"):
                holder.prop(owner, attr, index=i, text=f"{r[1]} . {axis}")
        else:
            holder.prop(owner, attr, text=r[1])


def _hint(col, text):
    col.label(text=text, icon="INFO")


def _missing(col, ob):
    if gen_mod(ob) is None or gen_mod(ob).node_group is None:
        col.label(text="This generator's nodes are missing", icon="ERROR")
        return True
    return False


def _spline_count(ob):
    return len(gn._splines([(o, None) for o in kids_of(ob)]))


def page_extrude(col, ob):
    if _missing(col, ob):
        return
    if not _spline_count(ob) and not any(o.type == "FONT" for o in kids_of(ob)):
        _hint(col, "Put a spline under the Extrude")
    moving = ("Movement Vector", "Movement Direction")
    _rows(col, ob, [("Direction", "Direction"), ("Offset", "Offset", lambda v: v("Direction") != "Movement Vector"),
                    ("Movement", "Movement", lambda v: v("Direction") in moving), None,
                    ("Subdivision", "Segments"), ("Hierarchical", "Use All Children"), ("Reverse Normals", "Reverse Normals")])


def page_lathe(col, ob):
    if _missing(col, ob):
        return
    if not _spline_count(ob):
        _hint(col, "Put a spline under the Lathe")
    _rows(col, ob, [("Angle", "Angle"), ("Subdivision", "Segments"), ("Movement", "Climb"), ("Scaling", "End Scale %"),
                    ("Reverse Normals", "Reverse Normals")])


def page_sweep(col, ob):
    if _missing(col, ob):
        return
    if _spline_count(ob) < 2:
        _hint(col, "Put two splines under the Sweep: the shape, then the path")
    _rows(col, ob, [("End Scale", "End Scale %"), ("End Rotation", "End Twist"), None,
                    ("Start Growth", "Start %"), ("End Growth", "End %"), None,
                    ("Banking", "Banking"), ("Reverse Normals", "Reverse Normals")])


def page_loft(col, ob):
    if _missing(col, ob):
        return
    if not _spline_count(ob):
        _hint(col, "Put splines under the Loft, in order")
    _rows(col, ob, [("Subdivision U", "Segments Around"), ("Subdivision V", "Segments Between"), None,
                    ("Loop", "Close the Loop"), ("Linear Interpolation", "Straight Between Splines"), ("Reverse Normals", "Reverse Normals")])


def page_symmetry(col, ob):
    if _missing(col, ob):
        return
    if not kids_of(ob):
        _hint(col, "Put objects under the Symmetry")
    _rows(col, ob, [("Mirror Plane", "Mirror Plane"), ("Weld Points", "Weld Points"),
                    ("Weld Tolerance", "Weld Distance", lambda v: v("Weld Points"))])


def page_array(col, ob):
    if _missing(col, ob):
        return
    if not kids_of(ob):
        _hint(col, "Put objects under the Array")
    _rows(col, ob, [("Radius", "Radius"), ("Copies", "Copies"), None, ("Amplitude", "Wave Height"), ("Frequency", "Wave Speed"),
                    ("Array Frequency", "Waves Around"), None, ("Keep Instances", "Keep as Instances")])


def page_instance(col, ob):
    if _missing(col, ob):
        return
    _rows(col, ob, [("Reference Object", "Reference Object")])


def page_connect(col, ob):
    if _missing(col, ob):
        return
    if not connect_members(ob):
        _hint(col, "Put objects under the Connect")
    _rows(col, ob, [("Objects", "Also Join"), ("Weld", "Weld"), ("Tolerance", "Weld Distance", lambda v: v("Weld"))])


def page_boolean(col, ob):
    if _missing(col, ob):
        return
    if sum(1 for o in kids_of(ob) if o.type == "MESH") < 2:
        _hint(col, "Put two or more objects under the Boolean")
    _rows(col, ob, [("Operation", "Operation"), ("Fix Overlaps", "Fix Overlaps Inside Each"),
                    ("Hard Cut Edges", "Hard Cut Edges"), ("Mark Cut Edges", "Mark Cut Edges")])


def page_metaball(col, ob):
    if _missing(col, ob):
        return
    if not kids_of(ob):
        _hint(col, "Put objects or splines under the Metaball")
    _rows(col, ob, [("Radius", "Ball Radius"), ("Blend", "Blend"), ("Swell", "Swell"), None,
                    ("Viewport Detail", "Viewport Voxel"), ("Render Detail", "Render Voxel")])


def page_caps(col, ob):
    if _missing(col, ob):
        return
    closed = (lambda v: not v("Loop")) if ob.get("b4d_type") == "loft" else None
    grid = ("Even Mesh", "Regular Grid")
    rows = [("Start", "Start Cap", closed), ("End", "End Cap", closed), None,
            ("Tessellation", "Cap Type"), ("Density", "Density", lambda v: v("Tessellation") == "Even Mesh"),
            ("Cap Size", "Grid Size", lambda v: v("Tessellation") == "Regular Grid"),
            ("Quad Dominant", "Quads", lambda v: v("Tessellation") in grid), None,
            ("Separate Controls", "Separate Settings per End")]
    sep = bool(gval(ob, "Separate Controls"))
    for p, title in (("S", "Start Bevel" if sep else "Bevel"), ("E", "End Bevel")):
        if p == "E" and not sep:
            break
        size = (lambda p: lambda v: (v(p + " Size") or 0) > 0)(p)
        rows += [None, ("#", title), (p + " Shape", "Shape"), (p + " Size", "Size"),
                 (p + " Subdivision", "Segments", size),
                 (p + " Tension", "Roundness %", (lambda p: lambda v: (v(p + " Size") or 0) > 0 and v(p + " Shape") == "Round")(p)),
                 (p + " Extrusion", "Raise Cap"), (p + " Offset", "Raise By", (lambda p: lambda v: v(p + " Extrusion"))(p))]
    if ob.get("b4d_type") == "extrude":
        rows += [None, ("Bevel Outside", "Bevel Outward")]
    _rows(col, ob, rows)


def page_selections(col, ob):
    if _missing(col, ob):
        return
    col.label(text="Keep each part as a named face selection")
    _rows(col, ob, [("Shell Selection", "Shell"), ("Start Cap Selection", "Start Cap"), ("End Cap Selection", "End Cap"),
                    ("Start Bevel Selection", "Start Bevel"), ("End Bevel Selection", "End Bevel")])


def page_subdivision(col, ob):
    col.prop(ob, "b4d_sub_type", text="Type")
    col.prop(ob, "b4d_sub_view", text="Viewport Level")
    col.prop(ob, "b4d_sub_render", text="Render Level")
    col.prop(ob, "b4d_sub_pre", text="Flat Pre-Subdivision")
    col.separator()
    col.prop(ob, "b4d_sub_uv", text="UV Smoothing")
    col.prop(ob, "b4d_sub_boundary", text="Open Edges")
    col.prop(ob, "b4d_sub_creases", text="Use Creases")


def page_reduce(col, ob):
    col.prop(ob, "b4d_red_strength", text="Reduction %")
    col.prop(ob, "b4d_red_triangulate", text="Triangulate")
    col.prop(ob, "b4d_red_symmetry", text="Symmetric")
    r = col.row()
    r.active = ob.b4d_red_symmetry
    r.prop(ob, "b4d_red_axis", text="Axis")


def page_remesh(col, ob):
    col.prop(ob, "b4d_rm_target", text="Target")
    r = col.row()
    r.active = ob.b4d_rm_target == "DENSITY"
    r.prop(ob, "b4d_rm_density", text="Density %")
    r = col.row()
    r.active = ob.b4d_rm_target == "COUNT"
    r.prop(ob, "b4d_rm_count", text="Polygon Count")
    col.prop(ob, "b4d_rm_smooth", text="Smoothing Steps")


CAPS_TABS = [("OBJECT", "Object"), ("CAPS", "Caps"), ("SELECT", "Selections")]
PAGES = {"extrude": page_extrude, "lathe": page_lathe, "sweep": page_sweep, "loft": page_loft, "symmetry": page_symmetry,
         "array": page_array, "instance": page_instance, "connect": page_connect, "boolean": page_boolean,
         "subdivision": page_subdivision, "reduce": page_reduce, "remesh": page_remesh, "metaball": page_metaball}
# the create column's order
ORDER = ("subdivision", "extrude", "lathe", "loft", "sweep", "boolean", "connect", "symmetry", "instance", "array", "remesh", "reduce", "metaball")


# --- registration ----------------------------------------------------------------------------------------------

def _props():
    O = bpy.types.Object
    P = bpy.props
    O.b4d_sub_type = P.EnumProperty(description='How the surface is divided: rounded, or kept as it is with only more polygons', name="Type", items=[("CATMULL_CLARK", "Smooth", "Rounds the surface"),
                                                        ("SIMPLE", "Flat", "Adds polygons without rounding")], default="CATMULL_CLARK", update=_update)
    O.b4d_sub_view = P.IntProperty(name="Viewport Level", default=2, min=0, max=6, update=_update,
                                   description="How often the surface is divided in the viewport")
    O.b4d_sub_render = P.IntProperty(name="Render Level", default=2, min=0, max=6, update=_update,
                                     description="How often the surface is divided when rendering")
    O.b4d_sub_pre = P.IntProperty(name="Flat Pre-Subdivision", default=0, min=0, max=6, update=_update,
                                  description="Divide without rounding first: keeps the form closer to the cage")
    O.b4d_sub_uv = P.EnumProperty(description='How the texture layout follows the smoothed surface', name="UV Smoothing", items=[("PRESERVE_BOUNDARIES", "Keep Borders", "Smooth UVs, keep their borders"),
                                                              ("SMOOTH_ALL", "Smooth All", "Smooth UVs everywhere"),
                                                              ("PRESERVE_CORNERS", "Keep Corners", "Smooth UVs, keep their corners"),
                                                              ("NONE", "None", "UVs are not smoothed")], default="PRESERVE_BOUNDARIES", update=_update)
    O.b4d_sub_boundary = P.EnumProperty(description='Whether open edges are rounded along with the rest', name="Open Edges", items=[("ALL", "Smooth", "Open edges are rounded too"),
                                                                 ("PRESERVE_CORNERS", "Keep Corners", "Corners of open edges stay sharp")],
                                        default="ALL", update=_update)
    O.b4d_sub_creases = P.BoolProperty(name="Use Creases", default=True, update=_update, description="Edges marked with a crease stay sharper")
    O.b4d_red_strength = P.FloatProperty(name="Reduction", default=90.0, min=0.0, max=100.0, subtype="PERCENTAGE", update=_update,
                                         description="How many polygons are taken away")
    O.b4d_red_triangulate = P.BoolProperty(name="Triangulate", default=False, update=_update, description="Make the result all triangles")
    O.b4d_red_symmetry = P.BoolProperty(name="Symmetric", default=False, update=_update, description="Reduce both sides of an axis alike")
    O.b4d_red_axis = P.EnumProperty(description='The axis the reduced object stays mirrored across', name="Axis", items=[("X", "X", "Mirror across X"), ("Y", "Y", "Mirror across Y"), ("Z", "Z", "Mirror across Z")], default="X", update=_update)
    O.b4d_rm_target = P.EnumProperty(description='Set the new polygon size by density or by a polygon count', name="Target", items=[("DENSITY", "Density", "Blocks set by a share of the object's size"),
                                                           ("COUNT", "Polygon Count", "Aim for about this many polygons")], default="DENSITY", update=_update)
    O.b4d_rm_density = P.FloatProperty(name="Density", default=100.0, min=1.0, max=10000.0, update=_update,
                                       description="100 % is about 20 blocks across the object")
    O.b4d_rm_count = P.IntProperty(description='How many polygons the result has', name="Polygon Count", default=1000, min=1, max=900000, update=_update)
    O.b4d_rm_smooth = P.IntProperty(name="Smoothing Steps", default=0, min=0, max=100, update=_update, description="Relax the new mesh")


PROPS = ("b4d_sub_type", "b4d_sub_view", "b4d_sub_render", "b4d_sub_pre", "b4d_sub_uv", "b4d_sub_boundary", "b4d_sub_creases",
         "b4d_red_strength", "b4d_red_triangulate", "b4d_red_symmetry", "b4d_red_axis",
         "b4d_rm_target", "b4d_rm_density", "b4d_rm_count", "b4d_rm_smooth")


def register():
    _props()
    for k in ORDER:
        if k in ("extrude", "lathe", "sweep", "loft"):
            tabs = CAPS_TABS
            pages = {"OBJECT": PAGES[k], "CAPS": page_caps, "SELECT": page_selections}
        else:
            tabs = [("OBJECT", "Object")]
            pages = {"OBJECT": PAGES[k]}
        kinds.add(k, LABELS[k], ICONS[k], create=(lambda k: lambda context: create(context, k))(k), tabs=tabs, pages=pages,
                  titles={"OBJECT": LABELS[k], "CAPS": "Caps", "SELECT": "Selections"},
                  describe=TIPS[k] + ("" if k == "instance" else " (selected objects go under it)"))
        kinds.create_button("generators", LABELS[k], k)
        kinds.menu_item("Create", LABELS[k], k)
    if _on_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_update)


def unregister():
    if _on_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_update)
    for n in PROPS:
        if hasattr(bpy.types.Object, n):
            delattr(bpy.types.Object, n)
