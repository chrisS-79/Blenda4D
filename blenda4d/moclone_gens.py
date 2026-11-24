# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone generators beyond the Cloner and Matrix: their settings (node group inputs) and node builders.

Fracture turns the objects under it, or each loose part of them, into clones the effectors move. The others follow in
this module as they are built. Pages and menu entries are in moclone.py."""
import bpy

from . import gen_caps as gc
from . import moclone_pieces as mp
from .moclone_nodes import TRANSFORM
from .primitives import _math

FRACTURE_MODES = [("Straight", 0), ("Explode Segments", 1), ("Explode Segments & Connect", 2)]
FRACTURE_INPUTS = [("Fracture Mode", "INT", 0, 'fracture.mode')] + TRANSFORM

MOINSTANCE_INPUTS = [("Object Reference", "OBJECT", None, 'moinstance.object'), ("History Depth", "INT", 10, 'moinstance.depth')] + TRANSFORM
TRACE_MODES = [("Trace Paths", 0), ("Connect All Objects", 1), ("Connect Elements", 2)]
HANDLE_CLONERS = [("Nodes Only", 0), ("Immediate Clones", 1), ("Clones of Clones", 2)]
SPACES = [("Global", 0), ("Local", 1)]
LIMITS = [("None", 0), ("From Start", 1), ("From End", 2)]
SPLINE_TYPES = [("Linear", 0), ("Cubic", 1), ("Akima", 2), ("B-Spline", 3), ("Bezier", 4)]
TRACER_INPUTS = [("Tracing Mode", "INT", 0, 'tracer.mode'), ("Sample Step", "INT", 1, 'tracer.step'), ("Trace Active", "BOOL", True, 'tracer.active'),
                 ("Trace Vertices", "BOOL", True, 'tracer.vertices'), ("Handle Cloners", "INT", 1, 'tracer.cloners'),
                 ("Include Cloner", "BOOL", False, 'tracer.include'), ("Space", "INT", 0, 'tracer.space'), ("Limit", "INT", 0, 'tracer.limit'),
                 ("Amount", "INT", 10, 'tracer.amount'), ("Variance", "INT", 0, 'tracer.variance'), ("Type", "INT", 0, 'tracer.type'),
                 ("Close Spline", "BOOL", False, 'tracer.close'), ("Reverse Sequence", "BOOL", False, 'tracer.reverse')]
TRACER_MENUS = {"Tracing Mode": TRACE_MODES, "Handle Cloners": HANDLE_CLONERS, "Space": SPACES, "Limit": LIMITS, "Type": SPLINE_TYPES}
MOSPLINE_MODES = [("Simple", 0), ("Spline", 1)]
GROW_MODES = [("Complete Spline", 0), ("Separate Segments", 1)]
GEN_MODES = [("Vertex", 0), ("Count", 1), ("Even", 2), ("Step", 3)]
MOSPLINE_INPUTS = [("MoSpline Mode", "INT", 0, 'mospline.mode'), ("Grow Mode", "INT", 0, 'mospline.grow'),
                   ("Start", "FLOAT", 0.0, 'mospline.start'), ("End", "FLOAT", 100.0, 'mospline.end'), ("Offset", "FLOAT", 0.0, 'mospline.offset'),
                   ("Length", "FLOAT", 100.0, 'mospline.length'), ("Steps", "INT", 20, 'mospline.steps'), ("Segments", "INT", 1, 'mospline.segments'),
                   ("Angle", "VECTOR", (0.0, 0.0, 0.0), 'mospline.angle'), ("Curve", "FLOAT", 0.0, 'mospline.curve'),
                   ("Bend", "FLOAT", 0.0, 'mospline.bend'), ("Twist", "FLOAT", 0.0, 'mospline.twist'), ("Width", "FLOAT", 5.0, 'mospline.width'),
                   ("Source Spline", "OBJECT", None, 'mospline.source'), ("Generation Mode", "INT", 1, 'mospline.gen_mode'),
                   ("Count", "INT", 20, 'mospline.count'), ("Step", "FLOAT", 10.0, 'mospline.step')]
MOSPLINE_MENUS = {"MoSpline Mode": MOSPLINE_MODES, "Grow Mode": GROW_MODES, "Generation Mode": GEN_MODES}

KINDS = {"fracture": ("Fracture", FRACTURE_INPUTS, {"Fracture Mode": FRACTURE_MODES}, True),
         "moinstance": ("MoInstance", MOINSTANCE_INPUTS, {}, False),
         "tracer": ("Tracer", TRACER_INPUTS, TRACER_MENUS, False),
         "mospline": ("MoSpline", MOSPLINE_INPUTS, MOSPLINE_MENUS, False),
         "voronoi": ("Voronoi Fracture", list(TRANSFORM), {}, True),
         "motext": ("MoText", [("Depth", "FLOAT", 20.0, 'motext.depth'), ("Subdivision", "INT", 1, 'motext.segments'),
                               ("Height", "FLOAT", 200.0, 'motext.height'), ("Horizontal Spacing", "FLOAT", 0.0, 'motext.hspace'),
                               ("Vertical Spacing", "FLOAT", 0.0, 'motext.vspace')] + TRANSFORM, {}, False)}
WITH_EFFECTORS = ("fracture", "moinstance", "mospline", "voronoi", "motext")
OWN_MESH = ("voronoi",)                                   # generators whose own mesh is the input (made in Python)
FX_GENS = ("cloner", "matrix") + WITH_EFFECTORS + ("polyfx", "moextrude")    # objects with an Effectors list
OWN_SIG = ("tracer", "moinstance", "voronoi", "motext")                        # generators whose nodes also hang on linked objects


def extra_signature(gen):
    """What else shapes a generator's nodes: the Tracer's Trace Link list, the MoInstance's reference."""
    k = gen.get("b4d_type")
    if k == "tracer":
        return ["trace:" + ",".join(e.obj.name for e in getattr(gen, "b4d_trace_list", []) if e.obj is not None)]
    if k == "moinstance":
        from . import generators as g
        ref = g.gval(gen, "Object Reference")
        bare = ref is not None and not any(sl.material for sl in getattr(ref, "material_slots", []))
        return [f"ref:{ref.name if ref else ''}:{bare}"]
    if k == "voronoi":
        from . import moclone_voronoi
        return ["vor:" + moclone_voronoi.signature(gen)]
    if k == "motext":
        f = gen.b4d_motext_font
        return [f"text:{gen.b4d_motext_text}:{f.name if f else ''}:{gen.b4d_motext_align}:{bool(gen.material_slots)}"]
    return []


def _kid_parts(nodes, links, kids):
    """Each child realized, numbered (b4d_kid) and, with no material, wearing Piece Color."""
    parts = []
    for k, (child, geo) in enumerate(kids):
        r = nodes.new("GeometryNodeRealizeInstances"); links.new(geo, r.inputs["Geometry"])
        g = r.outputs["Geometry"]
        if not any(sl.material for sl in getattr(child, "material_slots", [])):
            g = mp.bare_material(nodes, links, g)
        g = mp._store(nodes, links, g, "b4d_kid", "INT", k)
        parts.append(g)
    return parts


def build_fracture(nodes, links, o, kids, gen=None):
    """Straight: each child is one clone. Explode Segments: each loose part of each child is one clone. Explode
    Segments & Connect: the same, with touching points joined again afterwards."""
    if not kids:
        return nodes.new("GeometryNodeJoinGeometry").outputs[0]
    mesh = gc.join(nodes, links, _kid_parts(nodes, links, kids))
    island = nodes.new("GeometryNodeInputMeshIsland").outputs["Island Index"]
    piece = gc.index_switch(nodes, links, "INT", o["Fracture Mode"], [mp._attr(nodes, "b4d_kid", "INT"), island, island])
    mesh = mp._store(nodes, links, mesh, mp.PIECE, "INT", piece)
    from . import moclone_fx
    effect = moclone_fx.effect_fn(gen, drop_hidden=False) if gen is not None else None
    out = mp.pieces_effect(nodes, links, mesh, effect, o)
    joined = gc.merge(nodes, links, out)
    return gc.switch(nodes, links, "GEOMETRY", _math(nodes, "COMPARE", o["Fracture Mode"], 2.0, links), out, joined)


BUILDERS = {"fracture": build_fracture}


# --- shared -------------------------------------------------------------------------------------------------------

def _clone_state(nodes, links, pts, o, index=None):
    """The usual clone state on points (moclone_nodes.py), with the Transform tab applied."""
    from .moclone_nodes import _shown_vec, _euler
    idx = index if index is not None else nodes.new("GeometryNodeInputIndex").outputs[0]
    n = nodes.new("GeometryNodeAttributeDomainSize"); n.component = "POINTCLOUD"; links.new(pts, n.inputs["Geometry"])
    u = _math(nodes, "DIVIDE", idx, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", n.outputs["Point Count"], 1.0, links), 1.0, links), links)
    pts = mp._store(nodes, links, pts, "b4d_index", "INT", idx)
    pts = mp._store(nodes, links, pts, "b4d_u", "FLOAT", u)
    pts = mp._store(nodes, links, pts, "b4d_uv", "FLOAT_VECTOR", gc.combine(nodes, links, u, None, None))
    if "Clone Position" in o:
        rv = nodes.new("FunctionNodeRotateVector"); links.new(_shown_vec(nodes, links, o["Clone Position"], 0.01), rv.inputs["Vector"])
        links.new(mp._attr(nodes, "b4d_rot_q", "QUATERNION"), rv.inputs["Rotation"])
        sp = nodes.new("GeometryNodeSetPosition"); links.new(pts, sp.inputs["Geometry"]); links.new(rv.outputs[0], sp.inputs["Offset"])
        pts = sp.outputs["Geometry"]
        rr = nodes.new("FunctionNodeRotateRotation"); rr.rotation_space = "LOCAL"
        links.new(mp._attr(nodes, "b4d_rot_q", "QUATERNION"), rr.inputs["Rotation"]); links.new(_euler(nodes, links, o["Clone Rotation"]), rr.inputs["Rotate By"])
        pts = mp._store(nodes, links, pts, "b4d_rot_q", "QUATERNION", rr.outputs[0])
        pts = mp._store(nodes, links, pts, "b4d_scale", "FLOAT_VECTOR",
                        gc.vmath(nodes, links, "MULTIPLY", mp._attr(nodes, "b4d_scale", "FLOAT_VECTOR"), _shown_vec(nodes, links, o["Clone Scale"], 0.01)))
        pts = mp._store(nodes, links, pts, "b4d_color", "FLOAT_COLOR", o["Clone Color"])
        pts = mp._store(nodes, links, pts, "b4d_weight", "FLOAT", _math(nodes, "DIVIDE", o["Clone Weight"], 100.0, links))
    return pts


def _world(nodes, links, ob_socket=None):
    """The world transform of an object (the generator itself when ob_socket is None)."""
    info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "ORIGINAL"
    links.new(ob_socket if ob_socket is not None else nodes.new("GeometryNodeSelfObject").outputs[0], info.inputs["Object"])
    return info


# --- MoInstance ---------------------------------------------------------------------------------------------------

def build_moinstance(nodes, links, o, kids, gen=None):
    """A trail of the reference object along the path the MoInstance itself has moved: each frame its place is kept,
    History Depth places deep; clone 0 is where it is now. Plays forward from the first frame (a simulation)."""
    sim_in = nodes.new("GeometryNodeSimulationInput"); sim_out = nodes.new("GeometryNodeSimulationOutput")
    sim_in.pair_with_output(sim_out)
    empty = nodes.new("GeometryNodePoints"); empty.inputs["Count"].default_value = 0
    links.new(empty.outputs[0], sim_in.inputs["Geometry"])
    prev = mp._store(nodes, links, sim_in.outputs["Geometry"], "b4d_age", "INT", _math(nodes, "ADD", mp._attr(nodes, "b4d_age", "INT"), 1.0, links))
    old = nodes.new("GeometryNodeDeleteGeometry"); old.domain = "POINT"; links.new(prev, old.inputs["Geometry"])
    links.new(_math(nodes, "GREATER_THAN", _math(nodes, "ADD", mp._attr(nodes, "b4d_age", "INT"), 0.5, links), _math(nodes, "MAXIMUM", o["History Depth"], 1.0, links), links),
              old.inputs["Selection"])
    now = nodes.new("GeometryNodePoints"); now.inputs["Count"].default_value = 1
    new = mp._store(nodes, links, now.outputs[0], "b4d_age", "INT", 0)
    new = mp._store(nodes, links, new, "b4d_mat", "FLOAT4X4", _world(nodes, links).outputs["Transform"])
    hist = gc.join(nodes, links, [new, old.outputs["Geometry"]])
    srt = nodes.new("GeometryNodeSortElements"); srt.domain = "POINT"; links.new(hist, srt.inputs["Geometry"])
    links.new(mp._attr(nodes, "b4d_age", "INT"), srt.inputs["Sort Weight"])
    links.new(srt.outputs["Geometry"], sim_out.inputs["Geometry"])
    pts = sim_out.outputs["Geometry"]
    # each kept place, seen from where the MoInstance is now
    inv = nodes.new("FunctionNodeInvertMatrix"); links.new(_world(nodes, links).outputs["Transform"], inv.inputs[0])
    mm = nodes.new("FunctionNodeMatrixMultiply"); links.new(inv.outputs[0], mm.inputs[0]); links.new(mp._attr(nodes, "b4d_mat", "FLOAT4X4"), mm.inputs[1])
    sep = nodes.new("FunctionNodeSeparateTransform"); links.new(mm.outputs[0], sep.inputs[0])
    sp = nodes.new("GeometryNodeSetPosition"); links.new(pts, sp.inputs["Geometry"]); links.new(sep.outputs["Translation"], sp.inputs["Position"])
    pts = mp._store(nodes, links, sp.outputs["Geometry"], "b4d_rot_q", "QUATERNION", sep.outputs["Rotation"])
    pts = mp._store(nodes, links, pts, "b4d_scale", "FLOAT_VECTOR", sep.outputs["Scale"])
    pts = mp._store(nodes, links, pts, "b4d_color", "FLOAT_COLOR", (1.0, 1.0, 1.0, 1.0))
    pts = _clone_state(nodes, links, pts, o)
    if gen is not None:
        from . import moclone_fx
        pts = moclone_fx.effect_fn(gen)(nodes, links, pts)
    ref = nodes.new("GeometryNodeObjectInfo"); ref.transform_space = "ORIGINAL"
    links.new(o["Object Reference"], ref.inputs["Object"])
    shape = ref.outputs["Geometry"]
    from . import generators as g
    r = g.gval(gen, "Object Reference") if gen is not None else None
    if r is not None and not any(sl.material for sl in getattr(r, "material_slots", [])):
        from .moclone_nodes import clone_color_material
        sm = nodes.new("GeometryNodeSetMaterial"); links.new(shape, sm.inputs["Geometry"]); sm.inputs["Material"].default_value = clone_color_material()
        shape = sm.outputs["Geometry"]
    inst = nodes.new("GeometryNodeInstanceOnPoints")
    links.new(pts, inst.inputs["Points"]); links.new(shape, inst.inputs["Instance"])
    links.new(mp._attr(nodes, "b4d_rot_q", "QUATERNION"), inst.inputs["Rotation"])
    links.new(mp._attr(nodes, "b4d_scale", "FLOAT_VECTOR"), inst.inputs["Scale"])
    return inst.outputs["Instances"]


# --- Tracer -------------------------------------------------------------------------------------------------------

def _traced(nodes, links, o, gen):
    """The points being traced now, one geometry: b4d_obj is which Trace Link entry, b4d_tid a number per point."""
    parts = []
    objs = [e.obj for e in getattr(gen, "b4d_trace_list", []) if e.obj is not None] if gen is not None else []
    for k, ob in enumerate(objs):
        info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"; info.inputs["Object"].default_value = ob
        geo = info.outputs["Geometry"]
        clones = nodes.new("GeometryNodeInstancesToPoints"); links.new(geo, clones.inputs["Instances"])
        real = nodes.new("GeometryNodeRealizeInstances"); links.new(geo, real.inputs["Geometry"])
        verts = nodes.new("GeometryNodeMeshToPoints"); verts.mode = "VERTICES"; links.new(real.outputs["Geometry"], verts.inputs["Mesh"])
        cpts = nodes.new("GeometryNodeCurveToPoints"); cpts.mode = "EVALUATED"; links.new(real.outputs["Geometry"], cpts.inputs["Curve"])
        allv = gc.join(nodes, links, [verts.outputs["Points"], cpts.outputs["Points"]])
        centre = nodes.new("GeometryNodePoints"); centre.inputs["Count"].default_value = 1
        links.new(info.outputs["Location"], centre.inputs["Position"])
        has_clones = nodes.new("GeometryNodeAttributeDomainSize"); has_clones.component = "INSTANCES"; links.new(geo, has_clones.inputs["Geometry"])
        cl = _math(nodes, "GREATER_THAN", has_clones.outputs["Instance Count"], 0.0, links)
        # a Cloner: Nodes Only traces its centre, Immediate Clones and Clones of Clones each clone
        cloner_pts = gc.switch(nodes, links, "GEOMETRY", _math(nodes, "GREATER_THAN", o["Handle Cloners"], 0.5, links), centre.outputs["Points"], clones.outputs["Points"])
        cloner_pts = gc.switch(nodes, links, "GEOMETRY", o["Include Cloner"], cloner_pts, gc.join(nodes, links, [cloner_pts, centre.outputs["Points"]]))
        nv = nodes.new("GeometryNodeAttributeDomainSize"); nv.component = "POINTCLOUD"; links.new(allv, nv.inputs["Geometry"])
        has_pts = _math(nodes, "GREATER_THAN", nv.outputs["Point Count"], 0.0, links)       # an Empty has none: its centre
        plain = gc.switch(nodes, links, "GEOMETRY", _math(nodes, "MULTIPLY", o["Trace Vertices"], has_pts, links), centre.outputs["Points"], allv)
        pts = gc.switch(nodes, links, "GEOMETRY", cl, plain, cloner_pts)
        parts.append(mp._store(nodes, links, pts, "b4d_obj", "INT", k))
    if not parts:
        return None
    geo = gc.join(nodes, links, parts)
    return mp._store(nodes, links, geo, "b4d_tid", "INT", nodes.new("GeometryNodeInputIndex").outputs[0])


def build_tracer(nodes, links, o, kids, gen=None):
    """Splines from where the Trace Link objects' points have been (Trace Paths, a simulation that plays forward from
    the first frame) or through where they are now (Connect All Objects / Connect Elements)."""
    now = _traced(nodes, links, o, gen)
    if now is None:
        return nodes.new("GeometryNodeJoinGeometry").outputs[0]
    # Global: the points as they are in the world, so moving the Tracer moves the trails; Local: as the Tracer sees them
    w = _world(nodes, links)
    to_world = nodes.new("GeometryNodeTransform"); to_world.inputs["Mode"].default_value = "Matrix"
    links.new(now, to_world.inputs["Geometry"]); links.new(w.outputs["Transform"], to_world.inputs["Transform"])
    now = gc.switch(nodes, links, "GEOMETRY", _math(nodes, "GREATER_THAN", o["Space"], 0.5, links), to_world.outputs["Geometry"], now)
    frame = nodes.new("GeometryNodeInputSceneTime").outputs["Frame"]
    sim_in = nodes.new("GeometryNodeSimulationInput"); sim_out = nodes.new("GeometryNodeSimulationOutput")
    sim_in.pair_with_output(sim_out)
    empty = nodes.new("GeometryNodePoints"); empty.inputs["Count"].default_value = 0
    links.new(empty.outputs[0], sim_in.inputs["Geometry"])
    hist = sim_in.outputs["Geometry"]
    start = float(bpy.context.scene.frame_start)
    since = _math(nodes, "SUBTRACT", frame, start, links)
    step = _math(nodes, "MAXIMUM", o["Sample Step"], 1.0, links)
    on_step = _math(nodes, "LESS_THAN", _math(nodes, "FLOORED_MODULO", since, step, links), 0.5, links)
    tid = mp._attr(nodes, "b4d_tid", "INT")
    from .moclone_fx import _rand
    spread = _math(nodes, "ROUND", _math(nodes, "MULTIPLY", _rand(nodes, links, -1.0, 1.0, tid, 7), o["Variance"], links), None, links)
    amount = _math(nodes, "MAXIMUM", _math(nodes, "ADD", o["Amount"], spread, links), 1.0, links)
    from_start = _math(nodes, "COMPARE", o["Limit"], 1.0, links)
    still = _math(nodes, "SUBTRACT", 1.0, _math(nodes, "MULTIPLY", from_start, _math(nodes, "GREATER_THAN", since, _math(nodes, "SUBTRACT", amount, 0.5, links), links), links), links)
    add = _math(nodes, "MULTIPLY", _math(nodes, "MULTIPLY", on_step, o["Trace Active"], links), still, links)
    fresh = mp._store(nodes, links, now, "b4d_frame", "FLOAT", frame)
    keep_new = nodes.new("GeometryNodeDeleteGeometry"); keep_new.domain = "POINT"; links.new(fresh, keep_new.inputs["Geometry"])
    links.new(_math(nodes, "LESS_THAN", add, 0.5, links), keep_new.inputs["Selection"])
    hist = gc.join(nodes, links, [hist, keep_new.outputs["Geometry"]])
    # From End: only the last Amount frames
    old = nodes.new("GeometryNodeDeleteGeometry"); old.domain = "POINT"; links.new(hist, old.inputs["Geometry"])
    links.new(_math(nodes, "MULTIPLY", _math(nodes, "COMPARE", o["Limit"], 2.0, links),
                    _math(nodes, "LESS_THAN", mp._attr(nodes, "b4d_frame", "FLOAT"), _math(nodes, "SUBTRACT", frame, amount, links), links), links),
              old.inputs["Selection"])
    links.new(old.outputs["Geometry"], sim_out.inputs["Geometry"])
    paths = nodes.new("GeometryNodePointsToCurves"); links.new(sim_out.outputs["Geometry"], paths.inputs["Points"])
    links.new(mp._attr(nodes, "b4d_tid", "INT"), paths.inputs["Curve Group ID"]); links.new(mp._attr(nodes, "b4d_frame", "FLOAT"), paths.inputs["Weight"])
    every = nodes.new("GeometryNodePointsToCurves"); links.new(now, every.inputs["Points"])
    links.new(mp._attr(nodes, "b4d_tid", "INT"), every.inputs["Weight"])
    each = nodes.new("GeometryNodePointsToCurves"); links.new(now, each.inputs["Points"])
    links.new(mp._attr(nodes, "b4d_obj", "INT"), each.inputs["Curve Group ID"]); links.new(mp._attr(nodes, "b4d_tid", "INT"), each.inputs["Weight"])
    curves = gc.index_switch(nodes, links, "GEOMETRY", o["Tracing Mode"], [paths.outputs["Curves"], every.outputs["Curves"], each.outputs["Curves"]])
    typed = []
    for kind in ("POLY", "CATMULL_ROM", "CATMULL_ROM", "NURBS", "BEZIER"):
        t = nodes.new("GeometryNodeCurveSplineType"); t.spline_type = kind; links.new(curves, t.inputs["Curve"])
        typed.append(t.outputs["Curve"])
    curves = gc.index_switch(nodes, links, "GEOMETRY", o["Type"], typed)
    cyc = nodes.new("GeometryNodeSetSplineCyclic"); links.new(curves, cyc.inputs["Curve"]); links.new(o["Close Spline"], cyc.inputs["Cyclic"])
    rev = nodes.new("GeometryNodeReverseCurve"); links.new(cyc.outputs["Curve"], rev.inputs["Curve"])
    return gc.switch(nodes, links, "GEOMETRY", o["Reverse Sequence"], cyc.outputs["Curve"], rev.outputs["Curve"])


# --- MoSpline -----------------------------------------------------------------------------------------------------

def build_mospline(nodes, links, o, kids, gen=None):
    """Simple: Segments lines of Steps points grown from the centre, fanned out by Angle and bent by Curve, Bend and
    Twist along their length. Spline: a copy of the Source Spline. Start, End and Offset show part of it (grow it);
    Width is its thickness for a Sweep; the Effectors move its points."""
    from .moclone_nodes import _shown_vec
    steps = _math(nodes, "MAXIMUM", o["Steps"], 2.0, links)
    segs = _math(nodes, "MAXIMUM", o["Segments"], 1.0, links)
    pts = nodes.new("GeometryNodePoints"); links.new(_math(nodes, "MULTIPLY", steps, segs, links), pts.inputs["Count"])
    i = nodes.new("GeometryNodeInputIndex").outputs[0]
    seg = _math(nodes, "FLOOR", _math(nodes, "DIVIDE", i, steps, links), None, links)
    j = _math(nodes, "SUBTRACT", i, _math(nodes, "MULTIPLY", seg, steps, links), links)
    t = _math(nodes, "DIVIDE", j, _math(nodes, "SUBTRACT", steps, 1.0, links), links)
    fan = _math(nodes, "DIVIDE", seg, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", segs, 1.0, links), 1.0, links), links)
    deg = 3.141592653589793 / 180.0
    spread = gc.vmath(nodes, links, "SCALE", _shown_vec(nodes, links, o["Angle"], deg), scale=fan)
    bendv = gc.combine(nodes, links, _math(nodes, "MULTIPLY", o["Curve"], deg, links), _math(nodes, "MULTIPLY", o["Bend"], deg, links),
                       _math(nodes, "MULTIPLY", o["Twist"], deg, links))           # shown X, Z, Y: Curve forward, Bend sideways, Twist about its length
    e1 = nodes.new("FunctionNodeEulerToRotation"); links.new(spread, e1.inputs[0])
    e2 = nodes.new("FunctionNodeEulerToRotation"); links.new(gc.vmath(nodes, links, "SCALE", bendv, scale=t), e2.inputs[0])
    rr = nodes.new("FunctionNodeRotateRotation"); rr.rotation_space = "LOCAL"; links.new(e1.outputs[0], rr.inputs["Rotation"]); links.new(e2.outputs[0], rr.inputs["Rotate By"])
    stepv = nodes.new("FunctionNodeRotateVector"); links.new(rr.outputs[0], stepv.inputs["Rotation"])
    links.new(gc.combine(nodes, links, 0.0, 0.0, _math(nodes, "DIVIDE", _math(nodes, "MULTIPLY", o["Length"], 0.01, links), _math(nodes, "SUBTRACT", steps, 1.0, links), links)),
              stepv.inputs["Vector"])
    acc = mp._accumulate(nodes, links, "FLOAT_VECTOR", stepv.outputs[0], seg, "Trailing")
    sp = nodes.new("GeometryNodeSetPosition"); links.new(pts.outputs[0], sp.inputs["Geometry"]); links.new(acc, sp.inputs["Position"])
    simple = mp._store(nodes, links, sp.outputs["Geometry"], "b4d_seg", "INT", seg)
    simple = mp._store(nodes, links, simple, "b4d_step", "FLOAT", j)
    p2c = nodes.new("GeometryNodePointsToCurves"); links.new(simple, p2c.inputs["Points"])
    links.new(mp._attr(nodes, "b4d_seg", "INT"), p2c.inputs["Curve Group ID"]); links.new(mp._attr(nodes, "b4d_step", "FLOAT"), p2c.inputs["Weight"])
    # Spline mode: the Source Spline, its points kept (Vertex), Count of them, or one every Step
    src = nodes.new("GeometryNodeObjectInfo"); src.transform_space = "RELATIVE"; links.new(o["Source Spline"], src.inputs["Object"])
    real = nodes.new("GeometryNodeRealizeInstances"); links.new(src.outputs["Geometry"], real.inputs["Geometry"])
    by_count = nodes.new("GeometryNodeResampleCurve"); links.new(real.outputs["Geometry"], by_count.inputs["Curve"])
    by_count.inputs["Mode"].default_value = "Count"; links.new(_math(nodes, "MAXIMUM", o["Count"], 2.0, links), by_count.inputs["Count"])
    by_len = nodes.new("GeometryNodeResampleCurve"); links.new(real.outputs["Geometry"], by_len.inputs["Curve"])
    by_len.inputs["Mode"].default_value = "Length"; links.new(_math(nodes, "MAXIMUM", _math(nodes, "MULTIPLY", o["Step"], 0.01, links), 1e-3, links), by_len.inputs["Length"])
    spline = gc.index_switch(nodes, links, "GEOMETRY", o["Generation Mode"], [real.outputs["Geometry"], by_count.outputs["Curve"], by_count.outputs["Curve"], by_len.outputs["Curve"]])
    curve = gc.switch(nodes, links, "GEOMETRY", o["MoSpline Mode"], p2c.outputs["Curves"], spline)
    # grow: Start..End, slid by Offset
    s0 = _math(nodes, "ADD", _math(nodes, "MULTIPLY", o["Start"], 0.01, links), _math(nodes, "MULTIPLY", o["Offset"], 0.01, links), links)
    s1 = _math(nodes, "ADD", _math(nodes, "MULTIPLY", o["End"], 0.01, links), _math(nodes, "MULTIPLY", o["Offset"], 0.01, links), links)
    trim = nodes.new("GeometryNodeTrimCurve"); trim.mode = "FACTOR"; links.new(curve, trim.inputs["Curve"])
    links.new(_clamp01(nodes, links, s0), trim.inputs[2]); links.new(_clamp01(nodes, links, s1), trim.inputs[3])
    curve = trim.outputs["Curve"]
    rad = nodes.new("GeometryNodeSetCurveRadius"); links.new(curve, rad.inputs["Curve"]); links.new(_math(nodes, "MULTIPLY", o["Width"], 0.005, links), rad.inputs["Radius"])
    curve = rad.outputs["Curve"]
    # effectors move the points; each point is a clone
    fac = nodes.new("GeometryNodeSplineParameter").outputs["Factor"]
    curve = mp._store(nodes, links, curve, "b4d_rot_q", "QUATERNION", nodes.new("FunctionNodeEulerToRotation").outputs[0])
    curve = mp._store(nodes, links, curve, "b4d_scale", "FLOAT_VECTOR", (1.0, 1.0, 1.0))
    curve = mp._store(nodes, links, curve, "b4d_color", "FLOAT_COLOR", (1.0, 1.0, 1.0, 1.0))
    curve = mp._store(nodes, links, curve, "b4d_index", "INT", nodes.new("GeometryNodeInputIndex").outputs[0])
    curve = mp._store(nodes, links, curve, "b4d_u", "FLOAT", fac)
    curve = mp._store(nodes, links, curve, "b4d_uv", "FLOAT_VECTOR", gc.combine(nodes, links, fac, None, None))
    if gen is not None:
        from . import moclone_fx
        curve = moclone_fx.effect_fn(gen)(nodes, links, curve)
    return curve


def _clamp01(nodes, links, v):
    return _math(nodes, "MINIMUM", _math(nodes, "MAXIMUM", v, 0.0, links), 1.0, links)


def build_voronoi(nodes, links, o, kids, gen=None):
    """The pieces cut in Python (moclone_voronoi.py) come in as the object's own mesh; each is a clone."""
    from . import moclone_voronoi, moclone_fx
    if gen is not None and gen.get("b4d_vor_sig") != moclone_voronoi.signature(gen):
        moclone_voronoi.compute(gen)
    colors = mp.random_colors(nodes, links) if gen is not None and gen.b4d_vor_colorize else None
    effect = moclone_fx.effect_fn(gen, drop_hidden=False) if gen is not None else None
    return mp.pieces_effect(nodes, links, o["Geometry"], effect, o, colors=colors)


# --- MoText -------------------------------------------------------------------------------------------------------

MAX_CHARS = 1000


def _text_ranks(text):
    """Per character: its letter, word and line number among the visible characters (-1 for spaces and line
    breaks), each counted from 0 without gaps."""
    letters, words, lines = [], [], []
    li = wi = ln = -1
    in_word = False
    line_has = False
    cur_line = 0
    for ch in text:
        if ch == "\n":
            cur_line += 1; in_word = False; line_has = False
            letters.append(-1); words.append(-1); lines.append(-1)
            continue
        if ch.isspace():
            in_word = False
            letters.append(-1); words.append(-1); lines.append(-1)
            continue
        if not in_word:
            wi += 1; in_word = True
        if not line_has:
            ln += 1; line_has = True
        li += 1
        letters.append(li); words.append(wi); lines.append(ln)
    return letters, words, lines


def build_motext(nodes, links, o, kids, gen=None):
    """Text, extruded to Depth in Subdivision steps; the whole text, each line, each word and each letter are clones
    of their own effector lists (All, Lines, Words, Letters), applied in that order."""
    text = (gen.b4d_motext_text if gen is not None else "MoText").replace("\\n", "\n")[:MAX_CHARS]
    if not text.strip():
        return nodes.new("GeometryNodeJoinGeometry").outputs[0]
    s2c = nodes.new("GeometryNodeStringToCurves")
    s2c.inputs["String"].default_value = text
    if gen is not None and gen.b4d_motext_font is not None:
        s2c.inputs["Font"].default_value = gen.b4d_motext_font
    s2c.inputs["Align X"].default_value = {"LEFT": "Left", "CENTER": "Center", "RIGHT": "Right"}[gen.b4d_motext_align if gen else "LEFT"]
    h = _math(nodes, "MULTIPLY", o["Height"], 0.01, links)
    links.new(h, s2c.inputs["Size"])
    links.new(_math(nodes, "ADD", 1.0, _math(nodes, "DIVIDE", o["Horizontal Spacing"], _math(nodes, "MAXIMUM", _math(nodes, "MULTIPLY", o["Height"], 0.55, links), 1e-3, links), links), links),
              s2c.inputs["Character Spacing"])
    links.new(_math(nodes, "ADD", 1.0, _math(nodes, "DIVIDE", o["Vertical Spacing"], _math(nodes, "MAXIMUM", o["Height"], 1e-3, links), links), links), s2c.inputs["Line Spacing"])
    letters, words, lines = _text_ranks(text)
    inst = s2c.outputs["Curve Instances"]
    ii = nodes.new("GeometryNodeInputIndex").outputs[0]
    for name, ranks in (("b4d_letter", letters), ("b4d_word", words), ("b4d_line", lines)):
        inst = mp._store(nodes, links, inst, name, "INT", gc.index_switch(nodes, links, "INT", ii, ranks), domain="INSTANCE")
    real = nodes.new("GeometryNodeRealizeInstances"); links.new(inst, real.inputs["Geometry"])
    curves = real.outputs["Geometry"]
    fill = nodes.new("GeometryNodeFillCurve"); links.new(curves, fill.inputs["Curve"]); links.new(mp._attr(nodes, "b4d_letter", "INT"), fill.inputs["Group ID"])
    fill.inputs["Mode"].default_value = "N-gons"
    face = fill.outputs["Mesh"]
    # the fill's points take their letter, word and line from the nearest curve point (Sample Nearest reads point
    # clouds and meshes, not curves)
    cpts = nodes.new("GeometryNodeCurveToPoints"); cpts.mode = "EVALUATED"; links.new(curves, cpts.inputs["Curve"])
    src = cpts.outputs["Points"]
    near = nodes.new("GeometryNodeSampleNearest"); near.domain = "POINT"; links.new(src, near.inputs["Geometry"])
    for name in ("b4d_letter", "b4d_word", "b4d_line"):
        s = nodes.new("GeometryNodeSampleIndex"); s.data_type = "INT"; s.domain = "POINT"
        links.new(src, s.inputs["Geometry"]); links.new(mp._attr(nodes, name, "INT"), s.inputs["Value"]); links.new(near.outputs["Index"], s.inputs["Index"])
        face = mp._store(nodes, links, face, name, "INT", s.outputs[0])
    # Depth in Subdivision steps (built flat, faces out, then stood up below)
    rin = nodes.new("GeometryNodeRepeatInput"); rout = nodes.new("GeometryNodeRepeatOutput"); rin.pair_with_output(rout)
    sub = _math(nodes, "MAXIMUM", o["Subdivision"], 1.0, links)
    links.new(sub, rin.inputs["Iterations"])
    start = mp._store(nodes, links, face, "b4d_top", "BOOLEAN", True, domain="FACE")
    links.new(start, rin.inputs["Geometry"])
    ex = nodes.new("GeometryNodeExtrudeMesh"); ex.mode = "FACES"; ex.inputs["Individual"].default_value = False
    links.new(rin.outputs["Geometry"], ex.inputs["Mesh"]); links.new(mp._attr(nodes, "b4d_top", "BOOLEAN"), ex.inputs["Selection"])
    depth = _math(nodes, "MULTIPLY", o["Depth"], 0.01, links)
    links.new(gc.combine(nodes, links, 0.0, 0.0, _math(nodes, "DIVIDE", depth, sub, links)), ex.inputs["Offset"])
    top = nodes.new("GeometryNodeStoreNamedAttribute"); top.data_type = "BOOLEAN"; top.domain = "FACE"
    links.new(ex.outputs["Mesh"], top.inputs["Geometry"]); top.inputs["Name"].default_value = "b4d_top"; links.new(ex.outputs["Top"], top.inputs["Value"])
    links.new(top.outputs["Geometry"], rout.inputs["Geometry"])
    # the front sits at 0 and the depth runs back; stood up, the text faces shown -Z and its depth runs along +Z
    solid = gc.merge(nodes, links, gc.join(nodes, links, [gc.flip(nodes, links, face), rout.outputs["Geometry"]]))
    solid = gc.move(nodes, links, solid, translation=gc.combine(nodes, links, 0.0, 0.0, _math(nodes, "MULTIPLY", depth, -1.0, links)))
    solid = gc.move(nodes, links, solid, rotation=(1.5707963267948966, 0.0, 0.0))
    rm = nodes.new("GeometryNodeRemoveAttribute"); links.new(solid, rm.inputs["Geometry"]); rm.inputs["Name"].default_value = "b4d_top"
    mesh = rm.outputs["Geometry"]
    if gen is not None and not gen.material_slots:
        mesh = mp.bare_material(nodes, links, mesh)
    from . import moclone_fx
    for lst, attr, with_o in (("b4d_fx_list_all", None, True), ("b4d_fx_list_lines", "b4d_line", False),
                              ("b4d_fx_list_words", "b4d_word", False), ("b4d_fx_list", "b4d_letter", False)):
        if gen is None or (not moclone_fx.effectors_of(gen, lst) and not with_o):
            continue
        piece = 0 if attr is None else mp._attr(nodes, attr, "INT")
        mesh = mp._store(nodes, links, mesh, mp.PIECE, "INT", piece)
        mesh = mp.pieces_effect(nodes, links, mesh, moclone_fx.effect_fn(gen, lst, drop_hidden=False), o if with_o else None)
    return mesh


BUILDERS.update({"moinstance": build_moinstance, "tracer": build_tracer, "mospline": build_mospline, "voronoi": build_voronoi,
                 "motext": build_motext})
