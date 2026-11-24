# SPDX-License-Identifier: GPL-3.0-or-later
"""Node builders for the generators that are made from their children (Extrude, Lathe, Sweep, Loft, Symmetry, Array,
Instance, Connect, Boolean).

Each such generator is a mesh object with one Geometry Nodes modifier whose group is built for that object: the group
inputs are its settings (Blenda units: cm, degrees, percent), every child is read with an Object Info node in the
generator's space, and `build_<kind>(nodes, links, o, kids)` returns the output geometry.

Shown axes are Y up (coords.py): shown (x, y, z) = Blender (x, z, y). Lengths: 1 cm = 0.01 m."""
import math

import bpy

from . import gen_caps as gc
from .primitives import _math, _cm, SCALE

# caps and bevels shared by Extrude, Lathe, Sweep and Loft: (socket, type, default, row key)
CAPS = [("Start", "BOOL", True, 'caps.start'), ("End", "BOOL", True, 'caps.end'), ("Tessellation", "INT", 0, 'caps.type'),
        ("Density", "FLOAT", 20.0, 'caps.density'), ("Cap Size", "FLOAT", 10.0, 'caps.grid_size'), ("Quad Dominant", "BOOL", False, 'caps.quads'),
        ("Separate Controls", "BOOL", False, 'caps.separate'),
        ("S Shape", "INT", 0, 'caps.start_shape'), ("S Size", "FLOAT", 0.0, 'caps.start_size'), ("S Subdivision", "INT", 3, 'caps.start_segments'),
        ("S Tension", "FLOAT", 100.0, 'caps.start_tension'), ("S Extrusion", "BOOL", False, 'caps.start_raise'), ("S Offset", "FLOAT", 0.0, 'caps.start_offset'),
        ("E Shape", "INT", 0, 'caps.end_shape'), ("E Size", "FLOAT", 0.0, 'caps.end_size'), ("E Subdivision", "INT", 3, 'caps.end_segments'),
        ("E Tension", "FLOAT", 100.0, 'caps.end_tension'), ("E Extrusion", "BOOL", False, 'caps.end_raise'), ("E Offset", "FLOAT", 0.0, 'caps.end_offset'),
        ("Bevel Outside", "BOOL", False, 'caps.outward'),
        ("Shell Selection", "BOOL", False, 'select.shell'), ("Start Cap Selection", "BOOL", False, 'select.start_cap'),
        ("End Cap Selection", "BOOL", False, 'select.end_cap'), ("Start Bevel Selection", "BOOL", False, 'select.start_bevel'),
        ("End Bevel Selection", "BOOL", False, 'select.end_bevel')]
SELECTIONS = (("Shell Selection", "Shell"), ("Start Cap Selection", "Start Cap"), ("End Cap Selection", "End Cap"),
              ("Start Bevel Selection", "Start Bevel"), ("End Bevel Selection", "End Bevel"))
# gen_caps.flat_fill reads these numbers: 0/1 triangles, 2 n-gons, 3 even mesh, 4 regular grid
CAP_TYPES = [("Triangles", 0), ("N-gons", 2), ("Even Mesh", 3), ("Regular Grid", 4)]
BEVEL_SHAPES = [("Round", 0), ("Straight", 1), ("Steps", 2)]
CAP_MENUS = {"Tessellation": CAP_TYPES, "S Shape": BEVEL_SHAPES, "E Shape": BEVEL_SHAPES}

# kind -> (label, inputs [(socket, type, default, row key)], menus {socket: [(label, number)]}, hides its mesh children)
KINDS = {
    "extrude": ("Extrude",
                [("Direction", "INT", 0, 'extrude.direction'), ("Offset", "FLOAT", 20.0, 'extrude.offset'), ("Movement", "VECTOR", (0.0, 0.0, 20.0), 'extrude.movement'),
                 ("Subdivision", "INT", 1, 'extrude.segments'), ("Reverse Normals", "BOOL", False, 'extrude.reverse'),
                 ("Hierarchical", "BOOL", False, 'extrude.all_children')] + CAPS,
                {"Direction": [("Auto", 0), ("X", 1), ("Y", 2), ("Z", 3), ("Movement Vector", 4), ("Movement Direction", 5)], **CAP_MENUS}, False),
    "lathe": ("Lathe",
              [("Angle", "FLOAT", 360.0, 'lathe.angle'), ("Subdivision", "INT", 24, 'lathe.segments'), ("Movement", "FLOAT", 0.0, 'lathe.climb'),
               ("Scaling", "FLOAT", 100.0, 'lathe.end_scale'), ("Reverse Normals", "BOOL", False, 'lathe.reverse')] + CAPS,
              dict(CAP_MENUS), False),
    "sweep": ("Sweep",
              [("End Scale", "FLOAT", 100.0, 'sweep.end_scale'), ("End Rotation", "FLOAT", 0.0, 'sweep.end_twist'),
               ("Start Growth", "FLOAT", 0.0, 'sweep.start'), ("End Growth", "FLOAT", 100.0, 'sweep.end'),
               ("Banking", "BOOL", True, 'sweep.banking'), ("Reverse Normals", "BOOL", False, 'sweep.reverse')] + CAPS,
              dict(CAP_MENUS), False),
    "loft": ("Loft",
             [("Subdivision U", "INT", 16, 'loft.around'), ("Subdivision V", "INT", 4, 'loft.between'), ("Loop", "BOOL", False, 'loft.loop'),
              ("Linear Interpolation", "BOOL", False, 'loft.linear'), ("Reverse Normals", "BOOL", False, 'loft.reverse')] + CAPS,
             dict(CAP_MENUS), False),
    "symmetry": ("Symmetry",
                 [("Mirror Plane", "INT", 1, 'symmetry.plane'), ("Weld Points", "BOOL", True, 'symmetry.weld'), ("Weld Tolerance", "FLOAT", 0.01, 'symmetry.tolerance')],
                 {"Mirror Plane": [("XY", 0), ("ZY", 1), ("XZ", 2)]}, True),
    "array": ("Array",
              [("Radius", "FLOAT", 250.0, 'array.radius'), ("Copies", "INT", 7, 'array.copies'), ("Amplitude", "FLOAT", 0.0, 'array.amplitude'),
               ("Frequency", "FLOAT", 0.0, 'array.frequency'), ("Array Frequency", "FLOAT", 0.0, 'array.wave_frequency'),
               ("Keep Instances", "BOOL", False, 'array.instances')],
              {}, True),
    "instance": ("Instance", [("Reference Object", "OBJECT", None, 'instance.object')], {}, False),
    "connect": ("Connect",
                [("Objects", "OBJECT", None, 'connect.object'), ("Weld", "BOOL", True, 'connect.weld'), ("Tolerance", "FLOAT", 0.01, 'connect.tolerance')],
                {}, True),
    "metaball": ("Metaball",
                 [("Radius", "FLOAT", 20.0, 'metaball.radius'), ("Blend", "INT", 4, 'metaball.blend'), ("Swell", "FLOAT", 0.0, 'metaball.swell'),
                  ("Viewport Detail", "FLOAT", 5.0, 'metaball.view_voxel'), ("Render Detail", "FLOAT", 2.0, 'metaball.render_voxel')],
                 {}, True),
    "boolean": ("Boolean",
                [("Operation", "INT", 2, 'boolean.operation'), ("Fix Overlaps", "BOOL", True, 'boolean.self'),
                 ("Hard Cut Edges", "BOOL", False, 'boolean.hard_cut'), ("Mark Cut Edges", "BOOL", False, 'boolean.cut_edges')],
                {"Operation": [("Union", 1), ("Subtract", 2), ("Intersect", 3), ("Without", 4)]}, True),
}

SOCKET = {"FLOAT": "NodeSocketFloat", "INT": "NodeSocketInt", "VECTOR": "NodeSocketVector", "BOOL": "NodeSocketBool",
          "OBJECT": "NodeSocketObject", "COLOR": "NodeSocketColor"}
SKIN = ".b4d_skin"
HARD = ".b4d_hard"
SPLINE_KINDS = ("connect",)              # generators whose output can be a spline: a spline generator takes them too


# --- small node helpers ---------------------------------------------------------------------------

def _switch_geo(nodes, links, flag, off, on):
    sw = nodes.new("GeometryNodeSwitch")
    sw.input_type = "GEOMETRY"
    links.new(flag, sw.inputs["Switch"])
    links.new(off, sw.inputs["False"])
    links.new(on, sw.inputs["True"])
    return sw.outputs[0]


def _join(nodes, links, geos):
    j = nodes.new("GeometryNodeJoinGeometry")
    for g in geos:
        links.new(g, j.inputs[0])
    return j.outputs[0]


def _mark_skin(nodes, links, geo):
    """Tag the side faces: Reverse Normals turns them only, the caps keep facing out."""
    st = nodes.new("GeometryNodeStoreNamedAttribute"); st.data_type = "BOOLEAN"; st.domain = "FACE"
    links.new(geo, st.inputs["Geometry"]); st.inputs["Name"].default_value = SKIN; st.inputs["Value"].default_value = True
    return st.outputs["Geometry"]


def _flip_skin(nodes, links, geo, flag):
    attr = nodes.new("GeometryNodeInputNamedAttribute"); attr.data_type = "BOOLEAN"; attr.inputs["Name"].default_value = SKIN
    f = nodes.new("GeometryNodeFlipFaces"); links.new(geo, f.inputs["Mesh"]); links.new(attr.outputs["Attribute"], f.inputs["Selection"])
    out = _switch_geo(nodes, links, flag, geo, f.outputs["Mesh"])
    rm = nodes.new("GeometryNodeRemoveAttribute"); links.new(out, rm.inputs["Geometry"]); rm.inputs["Name"].default_value = SKIN
    return rm.outputs["Geometry"]


def _splines(kids):
    """Children a spline generator can use: curve objects (Blender curves and Blenda's spline objects), text, Connect."""
    return [g for ob, g in kids if ob.type in ("CURVE", "FONT") or ob.get("b4d_type") in SPLINE_KINDS]


def _resample_eval(nodes, links, curve):
    r = nodes.new("GeometryNodeResampleCurve")
    r.inputs["Mode"].default_value = "Evaluated"
    links.new(curve, r.inputs["Curve"])
    return r.outputs["Curve"]


def _resample_count(nodes, links, curve, count):
    r = nodes.new("GeometryNodeResampleCurve")
    r.inputs["Mode"].default_value = "Count"
    links.new(curve, r.inputs["Curve"])
    links.new(count, r.inputs["Count"])
    return r.outputs["Curve"]


def _merge(nodes, links, geo, dist):
    m = nodes.new("GeometryNodeMergeByDistance")
    links.new(geo, m.inputs["Geometry"])
    if hasattr(dist, "is_output"):
        links.new(dist, m.inputs["Distance"])
    else:
        m.inputs["Distance"].default_value = dist
    return m.outputs["Geometry"]


def _empty(nodes):
    return nodes.new("GeometryNodeJoinGeometry").outputs[0]


def _plane(nodes, links, curve):
    """(first point, unit normal, degenerate flag) of a planar contour from three samples."""
    smp = []
    for f in (0.0, 0.34, 0.67):
        c = nodes.new("GeometryNodeSampleCurve"); c.mode = "FACTOR"; c.data_type = "FLOAT"
        links.new(curve, c.inputs["Curves"]); c.inputs["Factor"].default_value = f
        smp.append(c.outputs["Position"])
    cr = gc.vmath(nodes, links, "CROSS_PRODUCT", gc.vmath(nodes, links, "SUBTRACT", smp[1], smp[0]), gc.vmath(nodes, links, "SUBTRACT", smp[2], smp[0]))
    ln = nodes.new("ShaderNodeVectorMath"); ln.operation = "LENGTH"; links.new(cr, ln.inputs[0])
    return smp[0], gc.vmath(nodes, links, "NORMALIZE", cr), _math(nodes, "LESS_THAN", ln.outputs["Value"], 1e-9, links)


def _sign(nodes, links, v):
    return _math(nodes, "SUBTRACT", _math(nodes, "MULTIPLY", _math(nodes, "GREATER_THAN", v, 0.0, links), 2.0, links), 1.0, links)


def _centre(nodes, links, geo):
    bb = nodes.new("GeometryNodeBoundBox"); links.new(geo, bb.inputs["Geometry"])
    return gc.vmath(nodes, links, "SCALE", gc.vmath(nodes, links, "ADD", bb.outputs["Min"], bb.outputs["Max"]), scale=0.5)


# --- builders: kids = [(object, geometry socket)] in Object Manager order ----------------------------

def _extrude_text(nodes, links, o, geo):
    """A text object reaches the nodes as filled letters (holes already right): lift the faces. No bevels on text yet."""
    ex = nodes.new("GeometryNodeExtrudeMesh"); ex.mode = "FACES"
    links.new(geo, ex.inputs["Mesh"]); links.new(gc.combine(nodes, links, z=_cm(nodes, links, o["Offset"])), ex.inputs["Offset"])
    ex.inputs["Individual"].default_value = False
    return gc.merge(nodes, links, gc.join(nodes, links, [ex.outputs["Mesh"], gc.flip(nodes, links, geo)]))


def build_extrude(nodes, links, o, kids):
    if kids and kids[0][0].type == "FONT":
        return _extrude_text(nodes, links, o, kids[0][1])
    curves = _splines(kids)
    if not curves:
        return _empty(nodes)
    # the first child alone (holes inside one spline); with Hierarchical every child joins in
    curve = _resample_eval(nodes, links, _switch_geo(nodes, links, o["Hierarchical"], curves[0], _join(nodes, links, curves)))
    return _extrude_curve(nodes, links, o, curve)


def _extrude_curve(nodes, links, o, curve):
    """The solid of a contour: Direction / Movement / Offset, Subdivision, caps and bevels."""
    p0, auto, flat_line = _plane(nodes, links, curve)
    auto = gc.switch(nodes, links, "VECTOR", flat_line, auto, (0.0, 1.0, 0.0))      # a straight line: along shown Z
    sep = gc.separate(nodes, links, gc.vmath(nodes, links, "SCALE", o["Movement"], scale=SCALE))
    move_bl = gc.combine(nodes, links, sep["X"], sep["Z"], sep["Y"])               # shown (x, y, z) -> Blender (x, z, y)
    off = _cm(nodes, links, o["Offset"])
    vec = gc.index_switch(nodes, links, "VECTOR", o["Direction"], [
        gc.vmath(nodes, links, "SCALE", auto, scale=off), gc.vmath(nodes, links, "SCALE", (1, 0, 0), scale=off),
        gc.vmath(nodes, links, "SCALE", (0, 0, 1), scale=off), gc.vmath(nodes, links, "SCALE", (0, 1, 0), scale=off),
        move_bl, gc.vmath(nodes, links, "SCALE", gc.vmath(nodes, links, "NORMALIZE", move_bl), scale=off)])
    n = gc.vmath(nodes, links, "SCALE", auto, scale=_sign(nodes, links, gc.dot(nodes, links, vec, auto)))
    R, Rinv = gc.align_z(nodes, links, n)
    flat = gc.move(nodes, links, gc.move(nodes, links, curve, translation=gc.vmath(nodes, links, "SCALE", p0, scale=-1.0)), rotation=Rinv)
    ring = gc.inward_ring(nodes, links, flat)
    # a direction inside the contour's plane has no height: build at height 1, the shear below lays it along the direction
    H = gc.switch(nodes, links, "FLOAT", _math(nodes, "LESS_THAN", gc.dot(nodes, links, vec, n), 1e-5, links), gc.dot(nodes, links, vec, n), 1.0)
    grow = gc.switch(nodes, links, "FLOAT", o["Bevel Outside"], 0.0,
                     _math(nodes, "MULTIPLY", _math(nodes, "MAXIMUM", _cm(nodes, links, o["S Size"]), _cm(nodes, links, gc.side_value(nodes, links, o, "E", "Size")), links), -1.0, links))
    base = gc.inset(nodes, links, ring, grow)
    sub = _math(nodes, "MAXIMUM", o["Subdivision"], 1, links)
    line = nodes.new("GeometryNodeMeshLine"); line.mode = "OFFSET"; line.count_mode = "TOTAL"
    links.new(_math(nodes, "ADD", sub, 1, links), line.inputs["Count"])
    links.new(gc.combine(nodes, links, y=_math(nodes, "DIVIDE", H, sub, links)), line.inputs["Offset"])
    m2c = nodes.new("GeometryNodeMeshToCurve"); links.new(line.outputs["Mesh"], m2c.inputs["Mesh"])
    wall = gc.part(nodes, links, _mark_skin(nodes, links, gc.sweep_ring(nodes, links, base, m2c.outputs["Curve"])), gc.PART_SHELL)
    top = gc.side_part(nodes, links, gc.move(nodes, links, gc.piece(nodes, links, o, "E", base), translation=gc.combine(nodes, links, z=H)), False)
    bottom = gc.side_part(nodes, links, gc.flip(nodes, links, gc.move(nodes, links, gc.piece(nodes, links, o, "S", base), scale=(1.0, 1.0, -1.0))), True)
    parts = [wall, gc.switch(nodes, links, "GEOMETRY", o["End"], _empty(nodes), top), gc.switch(nodes, links, "GEOMETRY", o["Start"], _empty(nodes), bottom)]
    out = gc.merge(nodes, links, gc.join(nodes, links, parts))
    # a direction that is not perpendicular to the contour shears the solid
    rv = nodes.new("FunctionNodeRotateVector"); links.new(vec, rv.inputs["Vector"]); links.new(Rinv, rv.inputs["Rotation"])
    vs = gc.separate(nodes, links, rv.outputs[0]); ps = gc.separate(nodes, links, gc.position(nodes))
    f = _math(nodes, "DIVIDE", ps["Z"], H, links)
    sh = nodes.new("GeometryNodeSetPosition"); links.new(out, sh.inputs["Geometry"])
    links.new(gc.combine(nodes, links, _math(nodes, "MULTIPLY", vs["X"], f, links), _math(nodes, "MULTIPLY", vs["Y"], f, links),
                         _math(nodes, "SUBTRACT", _math(nodes, "MULTIPLY", vs["Z"], f, links), ps["Z"], links)), sh.inputs["Offset"])
    back = gc.move(nodes, links, gc.move(nodes, links, sh.outputs["Geometry"], rotation=R), translation=p0)
    return _flip_skin(nodes, links, back, o["Reverse Normals"])


def build_lathe(nodes, links, o, kids):
    curves = _splines(kids)
    if not curves:
        return _empty(nodes)
    q = math.pi / 2
    ring = gc.inward_ring(nodes, links, gc.move(nodes, links, _resample_eval(nodes, links, curves[0]), rotation=(-q, 0.0, 0.0)))
    curve = gc.move(nodes, links, ring, rotation=(q, 0.0, 0.0))      # one winding for skin and caps
    n_pts = nodes.new("GeometryNodeAttributeDomainSize"); n_pts.component = "CURVE"; links.new(curve, n_pts.inputs["Geometry"])
    N = n_pts.outputs["Point Count"]
    sub = _math(nodes, "MAXIMUM", o["Subdivision"], 3, links)
    cyc = nodes.new("GeometryNodeSampleIndex"); cyc.data_type = "BOOLEAN"; cyc.domain = "CURVE"
    links.new(curve, cyc.inputs["Geometry"]); links.new(nodes.new("GeometryNodeInputSplineCyclic").outputs[0], cyc.inputs["Value"])
    NX = _math(nodes, "ADD", N, cyc.outputs[0], links)        # a closed contour repeats its first point
    grid = nodes.new("GeometryNodeMeshGrid")
    links.new(NX, grid.inputs["Vertices X"]); links.new(_math(nodes, "ADD", sub, 1, links), grid.inputs["Vertices Y"])
    idx = nodes.new("GeometryNodeInputIndex").outputs[0]
    NY = _math(nodes, "ADD", sub, 1, links)                   # grid index = x * NY + y
    i = _math(nodes, "FLOOR", _math(nodes, "DIVIDE", idx, NY, links), None, links)
    j = _math(nodes, "FLOORED_MODULO", idx, NY, links)
    v = _math(nodes, "DIVIDE", j, sub, links)
    s = nodes.new("GeometryNodeSampleIndex"); s.data_type = "FLOAT_VECTOR"; s.domain = "POINT"       # the contour's own points, so the caps weld
    links.new(curve, s.inputs["Geometry"]); links.new(gc.position(nodes), s.inputs["Value"])
    links.new(_math(nodes, "FLOORED_MODULO", i, N, links), s.inputs["Index"])
    rad = _math(nodes, "RADIANS", o["Angle"], None, links)
    ang = _math(nodes, "MULTIPLY", rad, v, links)
    rot = nodes.new("ShaderNodeVectorRotate"); rot.rotation_type = "AXIS_ANGLE"
    links.new(s.outputs[0], rot.inputs["Vector"]); rot.inputs["Axis"].default_value = (0, 0, 1); links.new(ang, rot.inputs["Angle"])
    end_s = _math(nodes, "DIVIDE", o["Scaling"], 100.0, links)
    scl = _math(nodes, "ADD", 1.0, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", end_s, 1.0, links), v, links), links)
    p = gc.vmath(nodes, links, "SCALE", rot.outputs[0], scale=scl)
    mvz = _cm(nodes, links, o["Movement"])
    p = gc.vmath(nodes, links, "ADD", p, gc.combine(nodes, links, z=_math(nodes, "MULTIPLY", mvz, v, links)))
    sp = nodes.new("GeometryNodeSetPosition"); links.new(grid.outputs["Mesh"], sp.inputs["Geometry"]); links.new(p, sp.inputs["Position"])
    skin = _mark_skin(nodes, links, sp.outputs["Geometry"])
    # caps close the two ends of a part turn of a closed contour
    start = gc.move(nodes, links, gc.side_part(nodes, links, gc.piece(nodes, links, o, "S", ring), True), rotation=(q, 0.0, 0.0))
    end = gc.flip(nodes, links, gc.move(nodes, links, gc.move(nodes, links, gc.side_part(nodes, links, gc.piece(nodes, links, o, "E", ring), False),
                                                               rotation=(q, 0.0, 0.0)), scale=(1.0, -1.0, 1.0)))
    t = nodes.new("GeometryNodeTransform"); links.new(end, t.inputs["Geometry"])
    links.new(gc.combine(nodes, links, z=mvz), t.inputs["Translation"])
    links.new(gc.combine(nodes, links, z=rad), t.inputs["Rotation"])
    links.new(gc.combine(nodes, links, end_s, end_s, end_s), t.inputs["Scale"])
    # the ends need caps whenever they do not meet: a part turn, or any turn that climbs or scales
    turn = _math(nodes, "FLOORED_MODULO", o["Angle"], 360.0, links)
    gap = _math(nodes, "MINIMUM", turn, _math(nodes, "SUBTRACT", 360.0, turn, links), links)
    shifted = _math(nodes, "ADD", _math(nodes, "ABSOLUTE", o["Movement"], None, links), _math(nodes, "ABSOLUTE", _math(nodes, "SUBTRACT", o["Scaling"], 100.0, links), None, links), links)
    partial = _math(nodes, "GREATER_THAN", _math(nodes, "ADD", gap, shifted, links), 0.01, links)
    open_ends = _math(nodes, "MULTIPLY", partial, cyc.outputs[0], links)
    parts = [skin, gc.switch(nodes, links, "GEOMETRY", _math(nodes, "MULTIPLY", open_ends, o["Start"], links), _empty(nodes), start),
             gc.switch(nodes, links, "GEOMETRY", _math(nodes, "MULTIPLY", open_ends, o["End"], links), _empty(nodes), t.outputs["Geometry"])]
    out = gc.outward(nodes, links, _merge(nodes, links, gc.join(nodes, links, parts), 1e-5))
    return _flip_skin(nodes, links, out, o["Reverse Normals"])


def build_sweep(nodes, links, o, kids):
    curves = _splines(kids)
    if len(curves) < 2:
        return _empty(nodes)
    profile, path = curves[0], curves[1]
    # the contour lies in the shown XY plane (Blender XZ): turn it into Curve to Mesh's XY profile plane
    prof = _resample_eval(nodes, links, gc.move(nodes, links, profile, rotation=(math.radians(90), 0, 0)))
    p = _resample_eval(nodes, links, path)
    tr = nodes.new("GeometryNodeTrimCurve"); tr.mode = "FACTOR"
    links.new(p, tr.inputs["Curve"])
    links.new(_math(nodes, "DIVIDE", o["Start Growth"], 100.0, links), tr.inputs[2]); links.new(_math(nodes, "DIVIDE", o["End Growth"], 100.0, links), tr.inputs[3])
    par = nodes.new("GeometryNodeSplineParameter").outputs["Factor"]
    end_s = _math(nodes, "DIVIDE", o["End Scale"], 100.0, links)
    end_r = _math(nodes, "RADIANS", o["End Rotation"], None, links)
    rad = nodes.new("GeometryNodeSetCurveRadius"); links.new(tr.outputs["Curve"], rad.inputs["Curve"])
    links.new(_math(nodes, "ADD", 1.0, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", end_s, 1.0, links), par, links), links), rad.inputs["Radius"])
    tilt = nodes.new("GeometryNodeSetCurveTilt"); links.new(rad.outputs["Curve"], tilt.inputs["Curve"])
    links.new(_math(nodes, "MULTIPLY", end_r, par, links), tilt.inputs["Tilt"])
    nmin = nodes.new("GeometryNodeSetCurveNormal"); nmin.inputs["Mode"].default_value = "Minimum Twist"; links.new(tilt.outputs["Curve"], nmin.inputs["Curve"])
    nz = nodes.new("GeometryNodeSetCurveNormal"); nz.inputs["Mode"].default_value = "Z Up"; links.new(tilt.outputs["Curve"], nz.inputs["Curve"])
    pathc = _switch_geo(nodes, links, o["Banking"], nz.outputs["Curve"], nmin.outputs["Curve"])
    # caps: the flat bevel + cap piece placed on each path end (Z = path tangent, X = path normal)
    ring = gc.inward_ring(nodes, links, prof)
    c2m = nodes.new("GeometryNodeCurveToMesh")
    links.new(pathc, c2m.inputs["Curve"]); links.new(ring, c2m.inputs["Profile Curve"])
    links.new(nodes.new("GeometryNodeInputRadius").outputs[0], c2m.inputs["Scale"])         # End Scale is kept as the path's radius

    def place(side, f, mirror, scale):
        g = gc.side_part(nodes, links, gc.piece(nodes, links, o, side, ring), side == "S")
        if side == "E":
            g = gc.move(nodes, links, g, rotation=gc.combine(nodes, links, z=end_r))
        if mirror:
            g = gc.flip(nodes, links, gc.move(nodes, links, g, scale=(1.0, 1.0, -1.0)))
        sc = nodes.new("GeometryNodeSampleCurve"); sc.mode = "FACTOR"; sc.data_type = "FLOAT"
        links.new(pathc, sc.inputs["Curves"]); sc.inputs["Factor"].default_value = f
        ax = nodes.new("FunctionNodeAxesToRotation"); ax.primary_axis = "Z"; ax.secondary_axis = "X"
        links.new(sc.outputs["Tangent"], ax.inputs["Primary Axis"]); links.new(sc.outputs["Normal"], ax.inputs["Secondary Axis"])
        return gc.move(nodes, links, g, translation=sc.outputs["Position"], rotation=ax.outputs[0],
                       scale=gc.combine(nodes, links, scale, scale, scale) if hasattr(scale, "is_output") else (scale, scale, scale))

    cy = nodes.new("GeometryNodeSampleIndex"); cy.data_type = "BOOLEAN"; cy.domain = "CURVE"
    links.new(pathc, cy.inputs["Geometry"]); links.new(nodes.new("GeometryNodeInputSplineCyclic").outputs[0], cy.inputs["Value"])
    open_path = _math(nodes, "SUBTRACT", 1.0, cy.outputs[0], links)
    parts = [_mark_skin(nodes, links, gc.flip(nodes, links, c2m.outputs["Mesh"])),
             gc.switch(nodes, links, "GEOMETRY", _math(nodes, "MULTIPLY", open_path, o["Start"], links), _empty(nodes), place("S", 0.0, True, 1.0)),
             gc.switch(nodes, links, "GEOMETRY", _math(nodes, "MULTIPLY", open_path, o["End"], links), _empty(nodes), place("E", 1.0, False, end_s))]
    return _flip_skin(nodes, links, gc.outward(nodes, links, _merge(nodes, links, gc.join(nodes, links, parts), 1e-4)), o["Reverse Normals"])


def _end_piece(nodes, links, o, side, ring_curve, away_from):
    """Bevel + cap on a planar ring anywhere in space, facing away from the point `away_from`."""
    p0, n, _d = _plane(nodes, links, ring_curve)
    c = _centre(nodes, links, ring_curve)
    n = gc.vmath(nodes, links, "SCALE", n, scale=_sign(nodes, links, gc.dot(nodes, links, n, gc.vmath(nodes, links, "SUBTRACT", c, away_from))))
    R, Rinv = gc.align_z(nodes, links, n)
    flat = gc.move(nodes, links, gc.move(nodes, links, ring_curve, translation=gc.vmath(nodes, links, "SCALE", p0, scale=-1.0)), rotation=Rinv)
    g = gc.side_part(nodes, links, gc.piece(nodes, links, o, side, gc.inward_ring(nodes, links, flat)), side == "S")
    return gc.move(nodes, links, gc.move(nodes, links, g, rotation=R), translation=p0)


def build_loft(nodes, links, o, kids):
    rings = _splines(kids)
    n = len(rings)
    if n == 0:
        return _empty(nodes)
    U = _math(nodes, "MAXIMUM", o["Subdivision U"], 2, links)
    V = _math(nodes, "MAXIMUM", o["Subdivision V"], 1, links)
    res = [_resample_count(nodes, links, g, U) for g in rings]
    if n == 1:                                    # a single spline is closed with a cap
        return _end_piece(nodes, links, o, "E", res[0], gc.vmath(nodes, links, "SUBTRACT", _centre(nodes, links, res[0]), (0.0, 0.0, 1.0)))
    allpts = _join(nodes, links, res)                       # point index = ring * U + i
    cyc = nodes.new("GeometryNodeInputSplineCyclic").outputs[0]
    # whether the first ring is closed decides whether the grid wraps around
    ccy = nodes.new("GeometryNodeSampleIndex"); ccy.data_type = "BOOLEAN"; ccy.domain = "CURVE"
    links.new(res[0], ccy.inputs["Geometry"]); links.new(cyc, ccy.inputs["Value"]); ccy.inputs["Index"].default_value = 0
    closed = ccy.outputs[0]
    nx = nodes.new("GeometryNodeSwitch"); nx.input_type = "INT"
    links.new(closed, nx.inputs["Switch"]); links.new(U, nx.inputs["False"]); links.new(_math(nodes, "ADD", U, 1, links), nx.inputs["True"])
    NX = nx.outputs[0]
    segs = _math(nodes, "MULTIPLY", V, _math(nodes, "ADD", _math(nodes, "SUBTRACT", n, 1, links), o["Loop"], links), links)
    ny = _math(nodes, "ADD", segs, 1, links)
    grid = nodes.new("GeometryNodeMeshGrid"); links.new(NX, grid.inputs["Vertices X"]); links.new(ny, grid.inputs["Vertices Y"])
    idx = nodes.new("GeometryNodeInputIndex").outputs[0]
    i = _math(nodes, "FLOORED_MODULO", _math(nodes, "FLOOR", _math(nodes, "DIVIDE", idx, ny, links), None, links), U, links)   # grid index = x * NY + y
    j = _math(nodes, "FLOORED_MODULO", idx, ny, links)
    rf = _math(nodes, "DIVIDE", j, V, links)                  # ring position (float)
    r0 = _math(nodes, "FLOOR", rf, None, links)
    t = _math(nodes, "SUBTRACT", rf, r0, links)

    def ring_pos(rk):
        rk = _math(nodes, "FLOORED_MODULO", rk, n, links)
        si = nodes.new("GeometryNodeSampleIndex"); si.data_type = "FLOAT_VECTOR"; si.domain = "POINT"
        links.new(allpts, si.inputs["Geometry"]); links.new(gc.position(nodes), si.inputs["Value"])
        links.new(_math(nodes, "ADD", _math(nodes, "MULTIPLY", rk, U, links), i, links), si.inputs["Index"])
        return si.outputs[0]

    def clamp_ring(rk):
        # without Loop the end rings repeat (Catmull-Rom end condition); with Loop they wrap
        c = _math(nodes, "MINIMUM", _math(nodes, "MAXIMUM", rk, 0, links), n - 1, links)
        sw = nodes.new("GeometryNodeSwitch"); sw.input_type = "INT"
        links.new(o["Loop"], sw.inputs["Switch"]); links.new(c, sw.inputs["False"]); links.new(rk, sw.inputs["True"])
        return sw.outputs[0]

    P0 = ring_pos(clamp_ring(_math(nodes, "SUBTRACT", r0, 1, links)))
    P1 = ring_pos(clamp_ring(r0))
    P2 = ring_pos(clamp_ring(_math(nodes, "ADD", r0, 1, links)))
    P3 = ring_pos(clamp_ring(_math(nodes, "ADD", r0, 2, links)))
    vm = gc.vmath
    lin = vm(nodes, links, "ADD", vm(nodes, links, "SCALE", P1, scale=_math(nodes, "SUBTRACT", 1.0, t, links)), vm(nodes, links, "SCALE", P2, scale=t))
    t2 = _math(nodes, "MULTIPLY", t, t, links); t3 = _math(nodes, "MULTIPLY", t2, t, links)
    a = vm(nodes, links, "SCALE", P1, scale=2.0)
    b = vm(nodes, links, "SCALE", vm(nodes, links, "SUBTRACT", P2, P0), scale=t)
    c = vm(nodes, links, "ADD", vm(nodes, links, "ADD", vm(nodes, links, "SCALE", P0, scale=2.0), vm(nodes, links, "SCALE", P1, scale=-5.0)),
           vm(nodes, links, "ADD", vm(nodes, links, "SCALE", P2, scale=4.0), vm(nodes, links, "SCALE", P3, scale=-1.0)))
    d = vm(nodes, links, "ADD", vm(nodes, links, "ADD", vm(nodes, links, "SCALE", P0, scale=-1.0), vm(nodes, links, "SCALE", P1, scale=3.0)),
           vm(nodes, links, "ADD", vm(nodes, links, "SCALE", P2, scale=-3.0), P3))
    cr = vm(nodes, links, "SCALE", vm(nodes, links, "ADD", vm(nodes, links, "ADD", a, b), vm(nodes, links, "ADD", vm(nodes, links, "SCALE", c, scale=t2), vm(nodes, links, "SCALE", d, scale=t3))), scale=0.5)
    mixn = nodes.new("ShaderNodeMix"); mixn.data_type = "VECTOR"
    links.new(o["Linear Interpolation"], mixn.inputs["Factor"]); links.new(cr, mixn.inputs[4]); links.new(lin, mixn.inputs[5])
    sp = nodes.new("GeometryNodeSetPosition"); links.new(grid.outputs["Mesh"], sp.inputs["Geometry"]); links.new(mixn.outputs[1], sp.inputs["Position"])
    skin = _merge(nodes, links, sp.outputs["Geometry"], 1e-5)
    # outward normals: flip the faces that point inward (normal . (position - centre))
    centre = _centre(nodes, links, skin)
    nrm = nodes.new("GeometryNodeInputNormal")
    inward = _math(nodes, "LESS_THAN", gc.dot(nodes, links, nrm.outputs[0], vm(nodes, links, "SUBTRACT", gc.position(nodes), centre)), 0.0, links)
    ff = nodes.new("GeometryNodeFlipFaces"); links.new(skin, ff.inputs["Mesh"]); links.new(inward, ff.inputs["Selection"])
    skin = _mark_skin(nodes, links, ff.outputs["Mesh"])
    no_loop = _math(nodes, "SUBTRACT", 1.0, o["Loop"], links)
    s0 = _switch_geo(nodes, links, _math(nodes, "MULTIPLY", o["Start"], no_loop, links), _empty(nodes), _end_piece(nodes, links, o, "S", res[0], _centre(nodes, links, res[1])))
    s1 = _switch_geo(nodes, links, _math(nodes, "MULTIPLY", o["End"], no_loop, links), _empty(nodes), _end_piece(nodes, links, o, "E", res[-1], _centre(nodes, links, res[-2])))
    out = _merge(nodes, links, _join(nodes, links, [skin, s0, s1]), 1e-4)
    return _flip_skin(nodes, links, out, o["Reverse Normals"])


def build_symmetry(nodes, links, o, kids):
    geos = [g for ob, g in kids if ob.type in ("MESH", "CURVE")]
    if not geos:
        return _empty(nodes)
    src = _join(nodes, links, geos)
    sw = nodes.new("GeometryNodeIndexSwitch"); sw.data_type = "VECTOR"
    while len(sw.index_switch_items) < 3:
        sw.index_switch_items.new()
    links.new(o["Mirror Plane"], sw.inputs["Index"])
    for k, v in ((1, (1, -1, 1)), (2, (-1, 1, 1)), (3, (1, 1, -1))):     # XY mirrors shown Z (Blender Y); ZY mirrors X; XZ mirrors shown Y (Blender Z)
        sw.inputs[k].default_value = v
    t = nodes.new("GeometryNodeTransform"); links.new(src, t.inputs["Geometry"]); links.new(sw.outputs[0], t.inputs["Scale"])
    ff = nodes.new("GeometryNodeFlipFaces"); links.new(t.outputs["Geometry"], ff.inputs["Mesh"])
    both = _join(nodes, links, [src, ff.outputs["Mesh"]])
    welded = _merge(nodes, links, both, _cm(nodes, links, o["Weld Tolerance"]))
    return _switch_geo(nodes, links, o["Weld Points"], both, welded)


def build_array(nodes, links, o, kids):
    geos = [g for ob, g in kids]
    if not geos:
        return _empty(nodes)
    src = _join(nodes, links, geos)
    count = _math(nodes, "ADD", o["Copies"], 1, links)
    circ = nodes.new("GeometryNodeCurvePrimitiveCircle"); circ.mode = "RADIUS"
    links.new(count, circ.inputs["Resolution"]); links.new(_cm(nodes, links, o["Radius"]), circ.inputs["Radius"])
    pts = nodes.new("GeometryNodeCurveToPoints"); pts.mode = "EVALUATED"; links.new(circ.outputs["Curve"], pts.inputs["Curve"])
    # a wave: Amplitude * sin(2 pi (Frequency * seconds + Array Frequency * index / count)) along shown Y (Blender Z)
    idx = nodes.new("GeometryNodeInputIndex").outputs[0]
    tm = nodes.new("GeometryNodeInputSceneTime").outputs["Seconds"]
    ph = _math(nodes, "ADD", _math(nodes, "MULTIPLY", o["Frequency"], tm, links), _math(nodes, "MULTIPLY", o["Array Frequency"], _math(nodes, "DIVIDE", idx, count, links), links), links)
    z = _math(nodes, "MULTIPLY", _cm(nodes, links, o["Amplitude"]), _math(nodes, "SINE", _math(nodes, "MULTIPLY", ph, 2 * math.pi, links), None, links), links)
    off = nodes.new("ShaderNodeCombineXYZ"); links.new(z, off.inputs["Z"])
    sp = nodes.new("GeometryNodeSetPosition"); links.new(pts.outputs["Points"], sp.inputs["Geometry"]); links.new(off.outputs[0], sp.inputs["Offset"])
    inst = nodes.new("GeometryNodeInstanceOnPoints"); links.new(sp.outputs["Geometry"], inst.inputs["Points"]); links.new(src, inst.inputs["Instance"])
    real = nodes.new("GeometryNodeRealizeInstances"); links.new(inst.outputs["Instances"], real.inputs["Geometry"])
    return _switch_geo(nodes, links, o["Keep Instances"], real.outputs["Geometry"], inst.outputs["Instances"])


def build_instance(nodes, links, o, kids):
    info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "ORIGINAL"
    links.new(o["Reference Object"], info.inputs["Object"])
    return info.outputs["Geometry"]


def build_connect(nodes, links, o, kids):
    geos = [g for ob, g in kids if ob.type in ("MESH", "CURVE", "FONT")]
    if not geos:
        return _empty(nodes)
    src = _join(nodes, links, geos)
    return _switch_geo(nodes, links, o["Weld"], src, _merge(nodes, links, src, _cm(nodes, links, o["Tolerance"])))


def _bool(nodes, links, op, first, rest=()):
    b = nodes.new("GeometryNodeMeshBoolean"); b.operation = op; b.solver = "EXACT"
    if op == "DIFFERENCE":
        links.new(first, b.inputs["Mesh 1"])
        for g in rest:
            links.new(g, b.inputs["Mesh 2"])
    else:
        for g in (first, *rest):
            links.new(g, b.inputs[1])              # inputs[0] is the hidden "Mesh 1"
    return b.outputs["Mesh"]


def _bool_or(nodes, links, a, b):
    n = nodes.new("FunctionNodeBooleanMath"); n.operation = "OR"
    links.new(a, n.inputs[0]); links.new(b, n.inputs[1])
    return n.outputs[0]


def _boolean_step(nodes, links, o, op, res, g):
    b = nodes.new("GeometryNodeMeshBoolean"); b.operation = "DIFFERENCE" if op == "WITHOUT" else op; b.solver = "EXACT"
    links.new(o["Fix Overlaps"], b.inputs["Self Intersection"])
    if b.operation == "DIFFERENCE":
        links.new(res, b.inputs["Mesh 1"]); links.new(g, b.inputs["Mesh 2"])
    else:
        links.new(res, b.inputs[1]); links.new(g, b.inputs[1])
    out = b.outputs["Mesh"]
    cut = b.outputs["Intersecting Edges"]
    # Hard Cut Edges: the edges along the cut are shaded sharp
    hard = nodes.new("FunctionNodeBooleanMath"); hard.operation = "AND"; links.new(cut, hard.inputs[0]); links.new(o["Hard Cut Edges"], hard.inputs[1])
    edge = nodes.new("GeometryNodeSetShadeSmooth"); edge.domain = "EDGE"; links.new(out, edge.inputs[0]); links.new(hard.outputs[0], edge.inputs["Selection"])
    edge.inputs["Shade Smooth"].default_value = False
    # Mark Cut Edges: the cut is kept as an edge selection named "Cut"
    mark = nodes.new("GeometryNodeStoreNamedAttribute"); mark.domain = "EDGE"; mark.data_type = "BOOLEAN"
    links.new(edge.outputs[0], mark.inputs["Geometry"]); mark.inputs["Name"].default_value = "Cut"
    links.new(cut, mark.inputs["Value"])
    out = _switch_geo(nodes, links, o["Mark Cut Edges"], edge.outputs[0], mark.outputs[0])
    # Hard Cut Edges is applied again after the Phong shading, which would smooth the cut back
    hold = nodes.new("GeometryNodeStoreNamedAttribute"); hold.domain = "EDGE"; hold.data_type = "BOOLEAN"
    links.new(out, hold.inputs["Geometry"]); hold.inputs["Name"].default_value = HARD
    before = nodes.new("GeometryNodeInputNamedAttribute"); before.data_type = "BOOLEAN"; before.inputs["Name"].default_value = HARD
    links.new(_bool_or(nodes, links, hard.outputs[0], before.outputs["Attribute"]), hold.inputs["Value"])      # earlier cuts stay hard
    out = hold.outputs[0]
    if op == "WITHOUT":                         # the cutter's surface goes, which leaves the hole open
        near = nodes.new("GeometryNodeProximity"); near.target_element = "FACES"; links.new(g, near.inputs[0])
        drop = nodes.new("GeometryNodeDeleteGeometry"); drop.domain = "FACE"; links.new(out, drop.inputs["Geometry"])
        links.new(_math(nodes, "LESS_THAN", near.outputs["Distance"], 1e-4, links), drop.inputs["Selection"])
        out = drop.outputs[0]
    return out


def build_boolean(nodes, links, o, kids):
    """The first child is the base; the others act on it in turn, top to bottom."""
    geos = [g for ob, g in kids if ob.type == "MESH"]
    if len(geos) < 2:
        return geos[0] if geos else _empty(nodes)
    chains = [_join(nodes, links, geos)]                    # 0: not used by the menu
    for op in ("UNION", "DIFFERENCE", "INTERSECT", "WITHOUT"):
        res = geos[0]
        for g in geos[1:]:
            res = _boolean_step(nodes, links, o, op, res, g)
        chains.append(res)
    return gc.index_switch(nodes, links, "GEOMETRY", o["Operation"], chains)


def build_metaball(nodes, links, o, kids):
    """Every point of the children becomes a ball of Radius; a sphere primitive is one ball of its own size. The balls
    are melted into one surface: a distance field, filleted Blend times where they meet, turned back into a mesh."""
    balls = []
    for ob, g in kids:
        if ob.get("b4d_type") == "sphere":
            bb = nodes.new("GeometryNodeBoundBox"); links.new(g, bb.inputs["Geometry"])
            size = gc.separate(nodes, links, gc.vmath(nodes, links, "SUBTRACT", bb.outputs["Max"], bb.outputs["Min"]))
            pt = nodes.new("GeometryNodePoints"); pt.inputs["Count"].default_value = 1
            links.new(_centre(nodes, links, g), pt.inputs["Position"])
            links.new(_math(nodes, "MULTIPLY", _math(nodes, "MAXIMUM", size["X"], size["Y"], links), 0.5, links), pt.inputs["Radius"])
            balls.append(pt.outputs["Points"])
            continue
        real = nodes.new("GeometryNodeRealizeInstances"); links.new(g, real.inputs["Geometry"])
        mp = nodes.new("GeometryNodeMeshToPoints"); mp.mode = "VERTICES"; links.new(real.outputs[0], mp.inputs["Mesh"])
        cp = nodes.new("GeometryNodeCurveToPoints"); cp.mode = "EVALUATED"; links.new(real.outputs[0], cp.inputs["Curve"])
        both = _join(nodes, links, [mp.outputs["Points"], cp.outputs["Points"]])
        r = nodes.new("GeometryNodeSetPointRadius"); links.new(both, r.inputs["Points"]); links.new(_cm(nodes, links, o["Radius"]), r.inputs["Radius"])
        balls.append(r.outputs["Points"])
    if not balls:
        return _empty(nodes)
    pts = _join(nodes, links, balls)
    view = nodes.new("GeometryNodeIsViewport").outputs[0]
    sw = nodes.new("GeometryNodeSwitch"); sw.input_type = "FLOAT"; links.new(view, sw.inputs["Switch"])
    links.new(_cm(nodes, links, o["Render Detail"]), sw.inputs["False"]); links.new(_cm(nodes, links, o["Viewport Detail"]), sw.inputs["True"])
    voxel = _math(nodes, "MAXIMUM", sw.outputs[0], 0.002, links)
    sdf = nodes.new("GeometryNodePointsToSDFGrid"); links.new(pts, sdf.inputs["Points"]); links.new(voxel, sdf.inputs["Voxel Size"])
    links.new(nodes.new("GeometryNodeInputRadius").outputs[0], sdf.inputs["Radius"])
    fil = nodes.new("GeometryNodeSDFGridFillet"); links.new(sdf.outputs[0], fil.inputs["Grid"]); links.new(o["Blend"], fil.inputs["Iterations"])
    mesh = nodes.new("GeometryNodeGridToMesh"); links.new(fil.outputs[0], mesh.inputs["Grid"])
    links.new(_cm(nodes, links, o["Swell"]), mesh.inputs["Threshold"])
    return mesh.outputs["Mesh"]


BUILDERS = {"metaball": build_metaball, "extrude": build_extrude, "lathe": build_lathe, "sweep": build_sweep, "loft": build_loft, "symmetry": build_symmetry,
            "array": build_array, "instance": build_instance, "connect": build_connect, "boolean": build_boolean}

# MoClone's Cloner and Matrix are node generators too (moclone_nodes.py)
from . import moclone_nodes as _mc  # noqa: E402
KINDS["cloner"] = ("Cloner", _mc.CLONER_INPUTS, _mc.CLONER_MENUS, True)
KINDS["matrix"] = ("Matrix", _mc.MATRIX_INPUTS, _mc.MATRIX_MENUS, True)
BUILDERS["cloner"] = _mc.build_cloner
BUILDERS["matrix"] = _mc.build_matrix
from . import moclone_gens as _mg  # noqa: E402
KINDS.update(_mg.KINDS)
BUILDERS.update(_mg.BUILDERS)


# --- group construction ---------------------------------------------------------------------------

def make_group(name, kind, kids, owner):
    """A fresh node group for one generator object: its settings as inputs, Object Info per child, the builder's output."""
    old = bpy.data.node_groups.get(name)
    if old is not None:
        bpy.data.node_groups.remove(old)
    from .node_arrange import drop_parts
    drop_parts(name)                                  # stage groups left from the last build of this generator
    label, inputs, menus, _consumes = KINDS[kind]
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.is_modifier = True
    tree["b4d_owner"] = owner
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    if kind in _mg.OWN_MESH:                          # its own mesh (made in Python) is what it works on
        tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    for sname, stype, default, _key in inputs:
        if sname in menus:
            tree.interface.new_socket(sname, in_out="INPUT", socket_type="NodeSocketMenu")
            continue
        s = tree.interface.new_socket(sname, in_out="INPUT", socket_type=SOCKET[stype])
        if default is not None:
            s.default_value = default
        if stype == "INT":
            s.min_value, s.max_value = 0, 100000
        elif stype == "FLOAT":
            s.min_value, s.max_value = -100000.0, 100000.0
    nodes, links = tree.nodes, tree.links
    gin = nodes.new("NodeGroupInput"); gout = nodes.new("NodeGroupOutput")
    o = dict((sock.name, sock) for sock in gin.outputs)
    from .node_arrange import stage, arrange
    _settings = stage(tree, "Settings"); _settings.__enter__()
    for sname, items in menus.items():
        ms = nodes.new("GeometryNodeMenuSwitch"); ms.data_type = "INT"; ms.enum_items.clear()
        for lab, _num in items:
            ms.enum_items.new(lab)
        links.new(gin.outputs[sname], ms.inputs["Menu"])
        for lab, num in items:
            ms.inputs[lab].default_value = num
        o[sname] = ms.outputs[0]
        dflt = dict((n, d) for n, t, d, k in inputs)[sname]
        tree.interface.items_tree[sname].default_value = next((lab for lab, num in items if num == dflt), items[0][0])
    _settings.__exit__(None, None, None)
    kid_geo = []
    _kids = stage(tree, "Children"); _kids.__enter__()
    for child in kids:
        info = nodes.new("GeometryNodeObjectInfo")
        info.transform_space = "ORIGINAL" if kind == "array" else "RELATIVE"     # the ring sits on the Array, wherever the child is
        info.inputs["Object"].default_value = child
        kid_geo.append((child, info.outputs["Geometry"]))
    _kids.__exit__(None, None, None)
    with stage(tree, label):
        if kind in ("cloner", "matrix"):              # MoClone: the Cloner's effectors act between its points and its clones
            from . import moclone_fx
            gen_ob = bpy.data.objects.get(owner)
            out = BUILDERS[kind](nodes, links, o, kid_geo, effect=moclone_fx.effect_fn(gen_ob) if gen_ob is not None else None)
        elif kind in _mg.BUILDERS:                    # MoClone generators: the builder runs the effectors itself
            out = BUILDERS[kind](nodes, links, o, kid_geo, gen=bpy.data.objects.get(owner))
        else:
            out = BUILDERS[kind](nodes, links, o, kid_geo)
    if "Shell Selection" in o:
        with stage(tree, "Selections"):
            out = _part_selections(nodes, links, o, out)
    from .primitives import _phong
    with stage(tree, "Phong Shading"):
        out = _phong(tree, out)                                  # generators are Phong shaded like the primitives
    _hard = stage(tree, "Hard Edges"); _hard.__enter__()
    if kind == "boolean":
        hard = nodes.new("GeometryNodeInputNamedAttribute"); hard.data_type = "BOOLEAN"; hard.inputs["Name"].default_value = HARD
        sharp = nodes.new("GeometryNodeSetShadeSmooth"); sharp.domain = "EDGE"; sharp.inputs["Shade Smooth"].default_value = False
        links.new(out, sharp.inputs[0]); links.new(hard.outputs["Attribute"], sharp.inputs["Selection"])
        rm = nodes.new("GeometryNodeRemoveAttribute"); links.new(sharp.outputs[0], rm.inputs["Geometry"]); rm.inputs["Name"].default_value = HARD
        out = rm.outputs[0]
    _hard.__exit__(None, None, None)
    links.new(out, gout.inputs["Geometry"])
    arrange(tree)                                                # readable in the node editor, not a pile
    return tree


def _part_selections(nodes, links, o, out):
    """Selections: a part that is switched on is kept as a face selection named after it ("Shell", "Start Cap" ...),
    so materials and Blender's own tools can use it."""
    for sock, name in SELECTIONS:
        cmp = nodes.new("FunctionNodeCompare"); cmp.data_type = "INT"; cmp.operation = "EQUAL"
        links.new(gc.part_field(nodes), cmp.inputs[0]); cmp.inputs[1].default_value = gc.PART_NAMES[name]
        st = nodes.new("GeometryNodeStoreNamedAttribute"); st.data_type = "BOOLEAN"; st.domain = "FACE"
        links.new(out, st.inputs["Geometry"]); st.inputs["Name"].default_value = name; links.new(cmp.outputs[0], st.inputs["Value"])
        out = _switch_geo(nodes, links, o[sock], out, st.outputs["Geometry"])
    return out
