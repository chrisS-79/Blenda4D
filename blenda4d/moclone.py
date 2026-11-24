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

ICONS = {"cloner": "MOD_ARRAY", "matrix": "LIGHTPROBE_VOLUME", "fracture": "MOD_EXPLODE", "moinstance": "TRACKING_BACKWARDS",
         "tracer": "CURVE_PATH", "mospline": "OUTLINER_OB_CURVES", "voronoi": "MOD_EXPLODE", "motext": "OUTLINER_OB_FONT"}
TIPS = {"cloner": "Places copies of the objects under it in a row, ring, grid, honeycomb or on another object",
        "matrix": "Makes the points of a Cloner arrangement, shown as small cubes, for other Cloners to use",
        "fracture": "Makes the objects under it, or each of their loose parts, into clones that effectors move",
        "moinstance": "Leaves a trail of copies of an object along the path it moves (play the animation from the start)",
        "tracer": "Draws splines along the paths objects and their points move, or through them (play from the start)",
        "mospline": "Grows splines, fanned out and bent, or from another spline, for a Sweep; effectors move their points",
        "voronoi": "Cuts the objects under it into pieces around scattered points; each piece is a clone effectors move",
        "motext": "3D text whose whole text, lines, words and letters each have their own effectors"}


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


def page_fracture(col, ob):
    if g._missing(col, ob):
        return
    if not g.kids_of(ob):
        g._hint(col, "Put objects under the Fracture")
    g._rows(col, ob, [("Fracture Mode", "Mode")])


def page_voronoi(col, ob):
    if g._missing(col, ob):
        return
    if not g.kids_of(ob):
        g._hint(col, "Put objects under the Voronoi Fracture")
    c = col.column()
    c.prop(ob, "b4d_vor_colorize"); c.prop(ob, "b4d_vor_ngons"); c.prop(ob, "b4d_vor_offset")
    c.prop(ob, "b4d_vor_hull")
    sub = c.row(); sub.active = ob.b4d_vor_hull; sub.prop(ob, "b4d_vor_thickness")
    c.prop(ob, "b4d_vor_optimize")
    r = c.column(align=True)
    for i, a in enumerate("XYZ"):
        r.prop(ob, "b4d_vor_cell_scale", index=i, text=f"Scale Cells . {a}")


class BLENDA4D_UL_vor_sources(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.kind == "OBJECT":
            layout.prop(item, "obj", text="", emboss=False, icon="OBJECT_DATA")
        else:
            layout.prop(item, "name", text="", emboss=False, icon="STICKY_UVS_DISABLE")


class BLENDA4D_OT_vor_source(bpy.types.Operator):
    """Add a source of seed points (a Distribution Source, or the selected objects), or remove the chosen one"""
    bl_idname = "blenda4d.vor_source"
    bl_label = "Source"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty()
    action: bpy.props.StringProperty()          # DISTRIBUTION, OBJECTS or REMOVE

    def execute(self, context):
        gen = bpy.data.objects.get(self.owner)
        if gen is None:
            return {"CANCELLED"}
        lst = gen.b4d_vor_sources
        if self.action == "REMOVE":
            if 0 <= gen.b4d_vor_source_index < len(lst):
                lst.remove(gen.b4d_vor_source_index)
        elif self.action == "OBJECTS":
            for o in context.selected_objects:
                if o != gen and o not in g.kids_of(gen):
                    it = lst.add(); it.kind = "OBJECT"; it.obj = o; it.name = o.name
        else:
            it = lst.add(); it.name = "Distribution Source"
        gen.b4d_vor_source_index = max(0, len(lst) - 1)
        g.sync_all()
        return {"FINISHED"}


def page_vor_sources(col, ob):
    r = col.row()
    r.template_list("BLENDA4D_UL_vor_sources", "", ob, "b4d_vor_sources", ob, "b4d_vor_source_index", rows=3)
    side = r.column(align=True)
    for icon, act in (("ADD", "DISTRIBUTION"), ("OBJECT_DATA", "OBJECTS"), ("REMOVE", "REMOVE")):
        op = side.operator("blenda4d.vor_source", text="", icon=icon); op.owner, op.action = ob.name, act
    col.label(text="+ adds a Distribution Source", icon="ADD")
    col.label(text="The object button adds the selected objects", icon="OBJECT_DATA")
    if 0 <= ob.b4d_vor_source_index < len(ob.b4d_vor_sources):
        s = ob.b4d_vor_sources[ob.b4d_vor_source_index]
        c = col.column()
        if s.kind == "OBJECT":
            c.prop(s, "obj")
            return
        c.prop(s, "dist")
        if s.dist != "UNIFORM":
            c.prop(s, "deviation")
        if s.dist == "EXPONENTIAL":
            c.prop(s, "pull_x"); c.prop(s, "pull_y"); c.prop(s, "pull_z")
        c.prop(s, "amount"); c.prop(s, "seed"); c.prop(s, "inside"); c.prop(s, "per_object")
        r = c.column(align=True)
        for i, a in enumerate("XYZ"):
            r.prop(s, "pos", index=i, text=f"P . {a}")
        r = c.column(align=True)
        for i, a in enumerate("XYZ"):
            r.prop(s, "scale", index=i, text=f"S . {a}")


def page_vor_sorting(col, ob):
    c = col.column()
    c.prop(ob, "b4d_vor_sort")
    sub = c.column(); sub.active = ob.b4d_vor_sort
    sub.prop(ob, "b4d_vor_invert"); sub.prop(ob, "b4d_vor_sort_by")
    if ob.b4d_vor_sort_by == "DIRECTION":
        r = sub.column(align=True)
        for i, a in enumerate("XYZ"):
            r.prop(ob, "b4d_vor_sort_dir", index=i, text=f"Direction . {a}")
    elif ob.b4d_vor_sort_by == "OBJECT":
        sub.prop(ob, "b4d_vor_sort_obj")


def _create_voronoi(context):
    gen = g.create(context, "voronoi")
    if not len(gen.b4d_vor_sources):
        gen.b4d_vor_sources.add().name = "Distribution Source"
        g.sync_all()
    return gen


def _motext_changed(self, context):
    g.sync_all()


def page_motext(col, ob):
    if g._missing(col, ob):
        return
    c = col.column()
    c.prop(ob, "b4d_motext_text")
    r = c.split(factor=0.4, align=True)
    lab = r.row(); lab.alignment = "RIGHT"; lab.label(text="Font")
    r.template_ID(ob, "b4d_motext_font", open="font.open")
    c.prop(ob, "b4d_motext_align")
    g._rows(col, ob, [("Depth", "Depth"), ("Subdivision", "Subdivision"), ("Height", "Height"),
                      ("Horizontal Spacing", "Horizontal Spacing"), ("Vertical Spacing", "Vertical Spacing")])


def _level_page(lst, transform=False):
    def page(col, ob):
        moclone_fx_ui._list(col, ob, lst)
        if transform:
            col.separator()
            page_transform(col, ob)
    return page


def page_moinstance(col, ob):
    if g._missing(col, ob):
        return
    g._rows(col, ob, [("Object Reference", "Object Reference"), ("History Depth", "History Depth")])
    g._hint(col, "Animate the MoInstance itself and play from the first frame")


def _trace_changed(self, context):
    g.sync_all()


class B4DTraceEntry(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object, update=_trace_changed)


class BLENDA4D_UL_trace(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "obj", text="", emboss=False)


class BLENDA4D_OT_trace_link(bpy.types.Operator):
    """Add the selected objects to the Trace Link list, or take the chosen one out"""
    bl_idname = "blenda4d.trace_link"
    bl_label = "Trace Link"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty()
    remove: bpy.props.BoolProperty()

    def execute(self, context):
        gen = bpy.data.objects.get(self.owner)
        if gen is None:
            return {"CANCELLED"}
        lst = gen.b4d_trace_list
        if self.remove:
            if 0 <= gen.b4d_trace_index < len(lst):
                lst.remove(gen.b4d_trace_index)
        else:
            for o in context.selected_objects:
                if o != gen and not any(e.obj == o for e in lst):
                    lst.add().obj = o
            if not len(lst) or lst[-1].obj is not None and not context.selected_objects:
                lst.add()
        g.sync_all()
        return {"FINISHED"}


def page_tracer(col, ob):
    if g._missing(col, ob):
        return
    col.label(text="Trace Link")
    r = col.row()
    r.template_list("BLENDA4D_UL_trace", "", ob, "b4d_trace_list", ob, "b4d_trace_index", rows=3)
    side = r.column(align=True)
    a = side.operator("blenda4d.trace_link", text="", icon="ADD"); a.owner, a.remove = ob.name, False
    d = side.operator("blenda4d.trace_link", text="", icon="REMOVE"); d.owner, d.remove = ob.name, True
    g._rows(col, ob, [("Tracing Mode", "Tracing Mode"), ("Sample Step", "Sample Step"), ("Trace Active", "Trace Active"),
                      ("Trace Vertices", "Trace Vertices"), ("Handle Cloners", "Handle Cloners"), ("Include Cloner", "Include Cloner"),
                      ("Space", "Space"), None, ("Limit", "Limit"),
                      ("Amount", "Amount", lambda v: v("Limit") != "None"), ("Variance", "Variance", lambda v: v("Limit") != "None"), None,
                      ("Type", "Type"), ("Close Spline", "Close Spline"), ("Reverse Sequence", "Reverse Sequence")])


def page_mospline(col, ob):
    if g._missing(col, ob):
        return
    simple = lambda v: v("MoSpline Mode") == "Simple"
    spline = lambda v: v("MoSpline Mode") == "Spline"
    rows = [("MoSpline Mode", "Mode"), ("Grow Mode", "Grow Mode"), ("Start", "Start %"), ("End", "End %"), ("Offset", "Offset %"), None,
            ("Length", "Length", simple), ("Steps", "Steps", simple), ("Segments", "Segments", simple), ("Angle", "Angle", simple),
            ("Curve", "Curve", simple), ("Bend", "Bend", simple), ("Twist", "Twist", simple),
            ("Source Spline", "Source Spline", spline), ("Generation Mode", "Generation Mode", spline),
            ("Count", "Count", lambda v: spline(v) and v("Generation Mode") in ("Count", "Even")),
            ("Step", "Step", lambda v: spline(v) and v("Generation Mode") == "Step"), None, ("Width", "Width")]
    g._rows(col, ob, _only_mode(rows, ob))


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
    for c in (B4DTraceEntry, BLENDA4D_UL_trace, BLENDA4D_OT_trace_link, BLENDA4D_UL_vor_sources, BLENDA4D_OT_vor_source):
        bpy.utils.register_class(c)
    from . import moclone_voronoi
    moclone_voronoi.props()
    from . import moclone_deform
    moclone_deform.props()
    O = bpy.types.Object
    O.b4d_motext_text = bpy.props.StringProperty(name="Text", default="MoText", update=_motext_changed,
                                                 description="The text; type \\n for a new line")
    O.b4d_motext_font = bpy.props.PointerProperty(name="Font", type=bpy.types.VectorFont, update=_motext_changed)
    O.b4d_motext_align = bpy.props.EnumProperty(name="Align", items=[("LEFT", "Left", ""), ("CENTER", "Center", ""), ("RIGHT", "Right", "")],
                                                default="LEFT", update=_motext_changed)
    bpy.types.Object.b4d_trace_list = bpy.props.CollectionProperty(type=B4DTraceEntry)
    bpy.types.Object.b4d_trace_index = bpy.props.IntProperty()
    for k, page in (("cloner", page_cloner), ("matrix", page_matrix), ("fracture", page_fracture), ("moinstance", page_moinstance),
                    ("mospline", page_mospline), ("tracer", page_tracer), ("voronoi", page_voronoi), ("motext", page_motext)):
        g.ICONS[k] = ICONS[k]
        g.TIPS[k] = TIPS[k]
        g.PAGES[k] = page
        tabs = [("OBJECT", "Object"), ("TRANSFORM", "Transform"), ("EFFECTORS", "Effectors")]
        if k == "mospline":
            tabs = [tabs[0], tabs[2]]
        elif k == "tracer":
            tabs = tabs[:1]
        elif k == "voronoi":
            tabs = [tabs[0], ("SOURCES", "Sources"), ("SORTING", "Sorting"), tabs[1], tabs[2]]
        elif k == "motext":
            tabs = [tabs[0], ("ALL", "All"), ("LINES", "Lines"), ("WORDS", "Words"), ("LETTERS", "Letters")]
        kinds.add(k, g.LABELS[k], ICONS[k], create=_create_voronoi if k == "voronoi" else (lambda k: lambda context: g.create(context, k))(k),
                  tabs=tabs,
                  pages={"OBJECT": page, "TRANSFORM": page_transform, "EFFECTORS": moclone_fx_ui.page_cloner_effectors,
                         "SOURCES": page_vor_sources, "SORTING": page_vor_sorting, "ALL": _level_page("b4d_fx_list_all", True),
                         "LINES": _level_page("b4d_fx_list_lines"), "WORDS": _level_page("b4d_fx_list_words"), "LETTERS": _level_page("b4d_fx_list")},
                  titles={"OBJECT": g.LABELS[k], "TRANSFORM": "Transform", "EFFECTORS": "Effectors", "SOURCES": "Sources", "SORTING": "Sorting",
                          "ALL": "All", "LINES": "Lines", "WORDS": "Words", "LETTERS": "Letters"},
                  describe=TIPS[k] + {"cloner": " (selected objects go under it)", "fracture": " (selected objects go under it)",
                                      "moinstance": " (the selected object is its reference)", "tracer": " (the selected objects are traced)",
                                      "voronoi": " (selected objects go under it)"}.get(k, ""))
        kinds.create_button("moclone", g.LABELS[k], k)


def unregister():
    for c in (BLENDA4D_OT_vor_source, BLENDA4D_UL_vor_sources, BLENDA4D_OT_trace_link, BLENDA4D_UL_trace, B4DTraceEntry):
        if getattr(c, "is_registered", False):
            bpy.utils.unregister_class(c)
    from . import moclone_dyn
    moclone_dyn.unregister()
    moclone_fx_ui.unregister()
