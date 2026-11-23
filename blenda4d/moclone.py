# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone: the Cloner and the Matrix in the create column, the MoClone menu and the Attributes pages.

The objects themselves are node generators (generators.py builds and keeps them; moclone_nodes.py has their nodes).
Put objects under a Cloner and it places copies of them: in a row (Linear), a ring (Radial), a grid (Grid), a
honeycomb (Honeycomb) or on another object (Object). The Matrix makes the same arrangements as points, for other
Cloners to use; it shows as small cubes in the viewport and nothing in renders."""
import bpy

from . import generators as g
from . import kinds
from . import moclone_fx_ui

ICONS = {"cloner": "MOD_ARRAY", "matrix": "LIGHTPROBE_VOLUME"}
TIPS = {"cloner": "Places copies of the objects under it in a row, ring, grid, honeycomb or on another object",
        "matrix": "Makes the points of a Cloner arrangement, shown as small cubes, for other Cloners to use"}


def _mode(v):
    return v("Mode")


def _on_spline(v):
    ob = v("Object")
    return ob is not None and getattr(ob, "type", "") == "CURVE"


def _mode_rows(cloner):
    rows = [("Mode", "Mode")]
    if cloner:
        rows += [("Clones", "Clones"), ("Reset Coordinates", "Reset Coordinates")]
    rows += [("Seed", "Seed"), None,
             # Object
             ("Object", "Object", lambda v: _mode(v) == "Object"),
             ("Distribution", "Distribution", lambda v: _mode(v) == "Object"),
             ("Object Count", "Count", lambda v: _mode(v) == "Object" and (v("Distribution") in ("Surface", "Volume") or _on_spline(v))),
             ("Align Clone", "Align Clone", lambda v: _mode(v) == "Object"),
             # Linear
             ("Count", "Count", lambda v: _mode(v) == "Linear"), ("Offset", "Offset", lambda v: _mode(v) == "Linear"),
             ("Linear Mode", "Mode", lambda v: _mode(v) == "Linear"), ("Amount", "Amount %", lambda v: _mode(v) == "Linear"),
             ("Position", "Position", lambda v: _mode(v) == "Linear"), ("Scale", "Scale %", lambda v: _mode(v) == "Linear"),
             ("Rotation", "Rotation", lambda v: _mode(v) == "Linear"), ("Step Mode", "Step Mode", lambda v: _mode(v) == "Linear"),
             ("Step Size", "Step Size %", lambda v: _mode(v) == "Linear"), ("Step Rotation", "Step Rotation", lambda v: _mode(v) == "Linear"),
             # Radial
             ("Radial Count", "Count", lambda v: _mode(v) == "Radial"), ("Radius", "Radius", lambda v: _mode(v) == "Radial"),
             ("Plane", "Plane", lambda v: _mode(v) == "Radial"), ("Align", "Align", lambda v: _mode(v) == "Radial"),
             ("Start Angle", "Start Angle", lambda v: _mode(v) == "Radial"), ("End Angle", "End Angle", lambda v: _mode(v) == "Radial"),
             ("Radial Offset", "Offset", lambda v: _mode(v) == "Radial"), ("Offset Variation", "Offset Variation %", lambda v: _mode(v) == "Radial"),
             # Grid
             ("Grid Count X", "Count . X", lambda v: _mode(v) == "Grid"), ("Grid Count Y", "Count . Y", lambda v: _mode(v) == "Grid"), ("Grid Count Z", "Count . Z", lambda v: _mode(v) == "Grid"), ("Grid Mode", "Mode", lambda v: _mode(v) == "Grid"),
             ("Grid Size", "Size", lambda v: _mode(v) == "Grid"), ("Form", "Form", lambda v: _mode(v) == "Grid"),
             ("Form Object", "Form Object", lambda v: _mode(v) == "Grid" and v("Form") == "Object"),
             ("Fill", "Fill %", lambda v: _mode(v) == "Grid"),
             # Honeycomb
             ("Honeycomb Direction", "Offset Direction", lambda v: _mode(v) == "Honeycomb"),
             ("Honeycomb Offset", "Offset %", lambda v: _mode(v) == "Honeycomb"),
             ("Width Count", "Width Count", lambda v: _mode(v) == "Honeycomb"), ("Height Count", "Height Count", lambda v: _mode(v) == "Honeycomb"),
             ("Honeycomb Mode", "Mode", lambda v: _mode(v) == "Honeycomb"),
             ("Width", "Width", lambda v: _mode(v) == "Honeycomb"), ("Height", "Height", lambda v: _mode(v) == "Honeycomb"),
             ("Honeycomb Plane", "Orientation", lambda v: _mode(v) == "Honeycomb"), ("Honeycomb Form", "Form", lambda v: _mode(v) == "Honeycomb"),
             ("Honeycomb Spline", "Spline", lambda v: _mode(v) == "Honeycomb" and v("Honeycomb Form") == "Spline")]
    return rows


def _only_mode(rows, ob):
    """Rows of the other modes are left out, not just dimmed: the page shows what the chosen mode uses."""
    out = []
    for r in rows:
        if r is not None and r[0] == "Simulated":
            continue
        if r is not None and r[0] != "#" and len(r) > 2 and r[2] is not None:
            try:
                if not r[2](lambda name: g.gval(ob, name)):
                    continue
            except Exception:
                pass
        out.append(r)
    return out


def page_cloner(col, ob):
    if g._missing(col, ob):
        return
    if not g.kids_of(ob):
        g._hint(col, "Put objects under the Cloner")
    g._rows(col, ob, _only_mode(_mode_rows(True), ob))


def page_matrix(col, ob):
    if g._missing(col, ob):
        return
    g._rows(col, ob, _only_mode(_mode_rows(False), ob) + [None, ("Matrix Size", "Cube Size"), ("Show in Render", "Show in Render")])


def page_transform(col, ob):
    if g._missing(col, ob):
        return
    g._rows(col, ob, [("Clone Position", "Position"), ("Clone Scale", "Scale %"), ("Clone Rotation", "Rotation"), None,
                      ("Clone Color", "Color"), ("Clone Weight", "Weight %")])


def make_editable(context, gen):
    """Make Editable on a Cloner: a Null in its place with each clone as its own object (named after the child it
    copies, numbered), each at the clone's place and with the clone's colour as its object colour. True when done."""
    from mathutils import Matrix
    from . import collapse
    dg = context.evaluated_depsgraph_get()
    geo = gen.evaluated_get(dg).evaluated_geometry()
    pc = geo.instances_pointcloud()
    kids = g.kids_of(gen)
    if pc is None or not kids:
        return False
    tf = pc.attributes.get("instance_transform")
    ref = pc.attributes.get(".reference_index")
    col = pc.attributes.get("b4d_color")
    reset = bool(g.gval(gen, "Reset Coordinates"))
    sources = {}
    for c in kids:                                              # each child's shape as it shows, once
        ev = c.evaluated_get(dg)
        try:
            sources[c.name] = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
        except RuntimeError:
            sources[c.name] = None
    collapse._quiet()
    try:
        null = bpy.data.objects.new(gen.name, None)
        for coll in gen.users_collection:
            coll.objects.link(null)
        null.parent = gen.parent
        null.matrix_parent_inverse = Matrix.Identity(4)
        null.matrix_world = gen.matrix_world.copy()
        made = []
        for i in range(len(pc.points)):
            k = ref.data[i].value if ref is not None else 0
            child = kids[min(max(k, 0), len(kids) - 1)]
            src = sources.get(child.name)
            if src is None:
                continue
            ob = bpy.data.objects.new(f"{child.name} {i}", src.copy())
            for sl in child.material_slots:
                if sl.material is not None:
                    ob.data.materials.append(sl.material)
            for coll in gen.users_collection:
                coll.objects.link(ob)
            m = Matrix([list(r) for r in tf.data[i].value]) if tf is not None else Matrix.Identity(4)
            rel = gen.matrix_world.inverted() @ child.matrix_world     # the child in the Cloner's space
            if reset:                                                  # Reset Coordinates: its turn and size, not its place
                rel = Matrix.LocRotScale(None, rel.to_quaternion(), rel.to_scale())
            ob.parent = null
            ob.matrix_parent_inverse = Matrix.Identity(4)
            ob.matrix_world = gen.matrix_world @ m @ rel
            if col is not None:
                ob.color = tuple(col.data[i].color)
            made.append(ob)
        for src in sources.values():
            if src is not None and src.users == 0:
                bpy.data.meshes.remove(src)
        name = gen.name
        collapse._remove_tree(gen)
        null.name = name
    finally:
        collapse._loud()
    collapse._select(context, [null])
    return True


def register():
    moclone_fx_ui.register()
    from . import moclone_dyn
    moclone_dyn.register()
    for k, page in (("cloner", page_cloner), ("matrix", page_matrix)):
        g.ICONS[k] = ICONS[k]
        g.TIPS[k] = TIPS[k]
        g.PAGES[k] = page
        kinds.add(k, g.LABELS[k], ICONS[k], create=(lambda k: lambda context: g.create(context, k))(k),
                  tabs=[("OBJECT", "Object"), ("TRANSFORM", "Transform"), ("EFFECTORS", "Effectors")],
                  pages={"OBJECT": page, "TRANSFORM": page_transform, "EFFECTORS": moclone_fx_ui.page_cloner_effectors},
                  titles={"OBJECT": g.LABELS[k], "TRANSFORM": "Transform", "EFFECTORS": "Effectors"},
                  describe=TIPS[k] + (" (selected objects go under it)" if k == "cloner" else ""))
        kinds.create_button("moclone", g.LABELS[k], k)


def unregister():
    from . import moclone_dyn
    moclone_dyn.unregister()
    moclone_fx_ui.unregister()
