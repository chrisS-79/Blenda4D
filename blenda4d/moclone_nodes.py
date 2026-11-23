# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone node builders: the Cloner and the Matrix.

Both are node generators (generators_nodes.py): a mesh object with one Geometry Nodes modifier built from its children.
The builder makes one point per clone, keeps each clone's state on the point as attributes, lets effectors change that
state (moclone_fx.py), then places the children on the points (Cloner) or shows the points as small cubes (Matrix).

Clone state on each point (Blender space):
  position         where the clone sits
  b4d_rot          rotation (Euler, radians)
  b4d_scale        scale
  b4d_color        colour (the material reads it with an Attribute node named "b4d_color", Instancer)
  b4d_weight       weight, 0..1
  b4d_u            the clone's place along the arrangement, 0 at the first clone, 1 at the last
  b4d_uv           the clone's place across the arrangement (U along, V across a grid or honeycomb), 0..1
  b4d_index        the clone's number

Shown values are Y up, cm, degrees, percent (coords.py): shown (x, y, z) = Blender (x, z, y)."""
import math

import bpy

from . import gen_caps as gc
from .primitives import _math, _cm

MODES = [("Object", 0), ("Linear", 1), ("Radial", 2), ("Grid", 3), ("Honeycomb", 4)]
CLONES = [("Iterate", 0), ("Random", 1)]          # Blend and Sort come with Modify Clone on the effectors
PLANES = [("XY", 0), ("ZY", 1), ("XZ", 2)]
PER = [("Per Step", 0), ("End Point", 1)]
STEP_MODES = [("Single Value", 0), ("Cumulative", 1)]
FORMS = [("Cube", 0), ("Sphere", 1), ("Cylinder", 2), ("Object", 3)]
HONEY_FORMS = [("Square", 0), ("Circle", 1), ("Spline", 2)]
HONEY_DIR = [("Width", 0), ("Height", 1)]
DISTRIBUTIONS = [("Vertex", 0), ("Edge", 1), ("Polygon Center", 2), ("Surface", 3), ("Volume", 4), ("Axis", 5)]

TRANSFORM = [("Clone Position", "VECTOR", (0.0, 0.0, 0.0), 'clone.position'), ("Clone Scale", "VECTOR", (100.0, 100.0, 100.0), 'clone.scale'),
             ("Clone Rotation", "VECTOR", (0.0, 0.0, 0.0), 'clone.rotation'), ("Clone Color", "COLOR", (1.0, 1.0, 1.0, 1.0), 'clone.color'),
             ("Clone Weight", "FLOAT", 0.0, 'clone.weight')]

CLONER_INPUTS = [
    ("Mode", "INT", 1, 'cloner.mode'), ("Clones", "INT", 0, 'cloner.clones'), ("Reset Coordinates", "BOOL", True, 'cloner.reset'),
    ("Seed", "INT", 1234567, 'cloner.seed'),
    # Linear
    ("Count", "INT", 3, 'linear.count'), ("Offset", "INT", 0, 'linear.offset'), ("Linear Mode", "INT", 0, 'linear.mode'),
    ("Amount", "FLOAT", 100.0, 'linear.amount'), ("Position", "VECTOR", (0.0, 50.0, 0.0), 'linear.position'),
    ("Scale", "VECTOR", (100.0, 100.0, 100.0), 'linear.scale'), ("Rotation", "VECTOR", (0.0, 0.0, 0.0), 'linear.rotation'),
    ("Step Mode", "INT", 0, 'linear.step_mode'), ("Step Size", "FLOAT", 100.0, 'linear.step_size'),
    ("Step Rotation", "VECTOR", (0.0, 0.0, 0.0), 'linear.step_rotation'),
    # Radial
    ("Radial Count", "INT", 6, 'radial.count'), ("Radius", "FLOAT", 200.0, 'radial.radius'), ("Plane", "INT", 0, 'radial.plane'),
    ("Align", "BOOL", True, 'radial.align'), ("Start Angle", "FLOAT", 0.0, 'radial.start'), ("End Angle", "FLOAT", 360.0, 'radial.end'),
    ("Radial Offset", "FLOAT", 0.0, 'radial.offset'), ("Offset Variation", "FLOAT", 0.0, 'radial.variation'),
    # Grid
    ("Grid Count X", "INT", 3, 'grid.count_x'), ("Grid Count Y", "INT", 3, 'grid.count_y'), ("Grid Count Z", "INT", 3, 'grid.count_z'), ("Grid Mode", "INT", 1, 'grid.mode'),
    ("Grid Size", "VECTOR", (200.0, 200.0, 200.0), 'grid.size'), ("Form", "INT", 0, 'grid.form'), ("Fill", "FLOAT", 100.0, 'grid.fill'),
    ("Form Object", "OBJECT", None, 'grid.object'),
    # Honeycomb
    ("Honeycomb Direction", "INT", 0, 'honey.direction'), ("Honeycomb Offset", "FLOAT", 50.0, 'honey.offset'),
    ("Width Count", "INT", 5, 'honey.width_count'), ("Height Count", "INT", 5, 'honey.height_count'), ("Honeycomb Mode", "INT", 0, 'honey.mode'),
    ("Width", "FLOAT", 50.0, 'honey.width'), ("Height", "FLOAT", 50.0, 'honey.height'), ("Honeycomb Plane", "INT", 0, 'honey.plane'),
    ("Honeycomb Form", "INT", 0, 'honey.form'), ("Honeycomb Spline", "OBJECT", None, 'honey.spline'),
    # Object
    ("Object", "OBJECT", None, 'object.object'), ("Distribution", "INT", 0, 'object.distribution'),
    ("Object Count", "INT", 20, 'object.count'), ("Align Clone", "BOOL", True, 'object.align'),
    ("Simulated", "BOOL", False, 'dyn.simulated'),           # set by MoClone dynamics: bodies stand in for the clones
] + TRANSFORM

CLONER_MENUS = {"Mode": MODES, "Clones": CLONES, "Linear Mode": PER, "Step Mode": STEP_MODES, "Plane": PLANES,
                "Grid Mode": PER, "Form": FORMS, "Honeycomb Direction": HONEY_DIR, "Honeycomb Plane": PLANES,
                "Honeycomb Form": HONEY_FORMS, "Honeycomb Mode": PER, "Distribution": DISTRIBUTIONS}

MATRIX_INPUTS = [i for i in CLONER_INPUTS if i[0] not in ("Clones", "Reset Coordinates")] + [
    ("Matrix Size", "FLOAT", 10.0, 'matrix.size'), ("Show in Render", "BOOL", False, 'matrix.render')]
MATRIX_MENUS = {k: v for k, v in CLONER_MENUS.items() if k != "Clones"}


# --- small helpers -------------------------------------------------------------------------------------------------

def _shown_vec(nodes, links, sock, scale=1.0):
    """A shown (Y up) vector socket as a Blender vector, times scale."""
    s = gc.separate(nodes, links, sock)
    v = gc.combine(nodes, links, s["X"], s["Z"], s["Y"])
    return v if scale == 1.0 else gc.vmath(nodes, links, "SCALE", v, scale=scale)


def _euler(nodes, links, shown_deg):
    """Shown rotation in degrees (X, Y, Z, Y up) -> a Blender rotation socket."""
    rad = _shown_vec(nodes, links, shown_deg, math.pi / 180.0)
    e = nodes.new("FunctionNodeEulerToRotation")
    links.new(rad, e.inputs[0])
    return e.outputs[0]


def _rand(nodes, links, lo, hi, ident, seed, typ="FLOAT"):
    r = nodes.new("FunctionNodeRandomValue"); r.data_type = typ
    names = {"FLOAT": ("Min", "Max"), "INT": ("Min", "Max")}[typ]
    idx = 2 if typ == "FLOAT" else 4                      # Random Value's float/int min-max sockets
    for sock_name, v in zip(names, (lo, hi)):
        sock = [s for s in r.inputs if s.name == sock_name and s.enabled][0]
        if hasattr(v, "is_output"):
            links.new(v, sock)
        else:
            sock.default_value = v
    links.new(ident, r.inputs["ID"])
    if hasattr(seed, "is_output"):
        links.new(seed, r.inputs["Seed"])
    else:
        r.inputs["Seed"].default_value = seed
    return [s for s in r.outputs if s.enabled][0]


def _attr(nodes, name, typ):
    a = nodes.new("GeometryNodeInputNamedAttribute"); a.data_type = typ
    a.inputs["Name"].default_value = name
    return a.outputs["Attribute"]


def _store(nodes, links, geo, name, typ, value, domain="POINT"):
    st = nodes.new("GeometryNodeStoreNamedAttribute"); st.data_type = typ; st.domain = domain
    links.new(geo, st.inputs["Geometry"]); st.inputs["Name"].default_value = name
    if hasattr(value, "is_output"):
        links.new(value, st.inputs["Value"])
    else:
        st.inputs["Value"].default_value = value
    return st.outputs["Geometry"]


def _count_of(nodes, links, geo):
    n = nodes.new("GeometryNodeAttributeDomainSize"); n.component = "POINTCLOUD"
    links.new(geo, n.inputs["Geometry"])
    return n.outputs["Point Count"]


def _ramp(nodes, links, i, n):
    """0 at the first clone, 1 at the last."""
    return _math(nodes, "DIVIDE", i, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", n, 1.0, links), 1.0, links), links)


def _per(nodes, links, flag, count):
    """Per Step: 1 per step; End Point: the whole value spread over the steps."""
    return gc.switch(nodes, links, "FLOAT", _math(nodes, "GREATER_THAN", flag, 0.5, links), 1.0,
                     _math(nodes, "DIVIDE", 1.0, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", count, 1.0, links), 1.0, links), links))


# --- arrangements: each returns (count, position, rotation (shown deg vector), scale (Blender vector), keep) -------

def _linear(nodes, links, o, i):
    n = _math(nodes, "ADD", o["Count"], o["Offset"], links)
    k = i                                                         # the Offset's leading clones are made, then dropped
    f = _math(nodes, "MULTIPLY", _per(nodes, links, o["Linear Mode"], o["Count"]), _math(nodes, "DIVIDE", o["Amount"], 100.0, links), links)
    # each step's move, turned by Step Rotation (Single Value: the same turn each step; Cumulative: the turn grows)
    tri = _math(nodes, "MULTIPLY", k, _math(nodes, "MULTIPLY", _math(nodes, "ADD", k, 1.0, links), 0.5, links), links)
    cumulative = _math(nodes, "GREATER_THAN", o["Step Mode"], 0.5, links)
    turn = gc.vmath(nodes, links, "SCALE", o["Step Rotation"], scale=gc.switch(nodes, links, "FLOAT", cumulative, k, tri))
    move = _shown_vec(nodes, links, o["Position"], 0.01)
    move = gc.vmath(nodes, links, "SCALE", move, scale=_math(nodes, "MULTIPLY", f, _math(nodes, "DIVIDE", o["Step Size"], 100.0, links), links))
    rv = nodes.new("FunctionNodeRotateVector"); links.new(move, rv.inputs["Vector"]); links.new(_euler(nodes, links, turn), rv.inputs["Rotation"])
    acc = nodes.new("GeometryNodeAccumulateField"); acc.data_type = "FLOAT_VECTOR"; acc.domain = "POINT"
    links.new(rv.outputs[0], acc.inputs["Value"])
    t = _math(nodes, "MULTIPLY", k, f, links)
    rot = gc.vmath(nodes, links, "ADD", gc.vmath(nodes, links, "SCALE", o["Rotation"], scale=t), turn)
    # Per Step compounds the size step by step (it never turns inside out); End Point runs evenly to the value
    sv = gc.separate(nodes, links, _shown_vec(nodes, links, o["Scale"], 0.01))
    end = _math(nodes, "GREATER_THAN", o["Linear Mode"], 0.5, links)
    scale = gc.combine(nodes, links, *[gc.switch(nodes, links, "FLOAT", end,
                                                 _math(nodes, "POWER", _math(nodes, "MAXIMUM", sv[c], 0.0, links), t, links),
                                                 _math(nodes, "ADD", 1.0, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", sv[c], 1.0, links), t, links), links))
                                       for c in ("X", "Y", "Z")])
    keep = _math(nodes, "GREATER_THAN", i, _math(nodes, "SUBTRACT", o["Offset"], 0.5, links), links)
    uv = gc.combine(nodes, links, _ramp(nodes, links, i, n), None, None)
    return n, acc.outputs["Trailing"], rot, scale, keep, uv


def _radial(nodes, links, o, i):
    n = o["Radial Count"]
    span = _math(nodes, "SUBTRACT", o["End Angle"], o["Start Angle"], links)
    full = _math(nodes, "GREATER_THAN", _math(nodes, "ABSOLUTE", span, None, links), 359.99, links)
    div = gc.switch(nodes, links, "FLOAT", full, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", n, 1, links), 1.0, links), _math(nodes, "MAXIMUM", n, 1.0, links))
    gap = _math(nodes, "DIVIDE", span, div, links)
    jitter = _math(nodes, "MULTIPLY", _math(nodes, "MULTIPLY", _rand(nodes, links, -0.5, 0.5, i, o["Seed"]),
                                             _math(nodes, "DIVIDE", o["Offset Variation"], 100.0, links), links), gap, links)
    deg = _math(nodes, "ADD", _math(nodes, "ADD", o["Start Angle"], _math(nodes, "MULTIPLY", gap, i, links), links),
                _math(nodes, "ADD", o["Radial Offset"], jitter, links), links)
    a = _math(nodes, "RADIANS", deg, None, links)
    R = _cm(nodes, links, o["Radius"])
    c = _math(nodes, "MULTIPLY", R, _math(nodes, "COSINE", a, None, links), links)
    s = _math(nodes, "MULTIPLY", R, _math(nodes, "SINE", a, None, links), links)
    # shown planes -> Blender: XY = (x, z), ZY = (y, z), XZ = (x, y)
    pos = gc.index_switch(nodes, links, "VECTOR", o["Plane"],
                          [gc.combine(nodes, links, c, None, s), gc.combine(nodes, links, None, c, s), gc.combine(nodes, links, c, s, None)])
    turn = _math(nodes, "MULTIPLY", deg, o["Align"], links)
    # Align turns each clone around the plane's axis (shown Z for XY, X for ZY, Y for XZ) so it faces outward
    rot = gc.index_switch(nodes, links, "VECTOR", o["Plane"],
                          [gc.combine(nodes, links, z=turn), gc.combine(nodes, links, x=_math(nodes, "MULTIPLY", turn, -1.0, links)),
                           gc.combine(nodes, links, y=_math(nodes, "MULTIPLY", turn, -1.0, links))])
    return n, pos, rot, (1.0, 1.0, 1.0), 1.0, gc.combine(nodes, links, _ramp(nodes, links, i, n), None, None)


def _grid(nodes, links, o, i):
    cx, cy, cz = [_math(nodes, "MAXIMUM", o["Grid Count " + k], 1.0, links) for k in ("X", "Y", "Z")]
    n = _math(nodes, "MULTIPLY", _math(nodes, "MULTIPLY", cx, cy, links), cz, links)
    ix = _math(nodes, "FLOORED_MODULO", i, cx, links)
    rest = _math(nodes, "FLOOR", _math(nodes, "DIVIDE", i, cx, links), None, links)
    iy = _math(nodes, "FLOORED_MODULO", rest, cy, links)
    iz = _math(nodes, "FLOOR", _math(nodes, "DIVIDE", rest, cy, links), None, links)
    size = gc.separate(nodes, links, o["Grid Size"])
    end = _math(nodes, "GREATER_THAN", o["Grid Mode"], 0.5, links)

    def spacing(cnt, sz):
        each = gc.switch(nodes, links, "FLOAT", end, sz, _math(nodes, "DIVIDE", sz, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", cnt, 1, links), 1.0, links), links))
        return _math(nodes, "MULTIPLY", each, 0.01, links)

    def centred(idx, cnt):
        return _math(nodes, "SUBTRACT", idx, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", cnt, 1, links), 0.5, links), links)

    sx, sy, sz = (_math(nodes, "MULTIPLY", centred(ix, cx), spacing(cx, size["X"]), links),
                  _math(nodes, "MULTIPLY", centred(iy, cy), spacing(cy, size["Y"]), links),
                  _math(nodes, "MULTIPLY", centred(iz, cz), spacing(cz, size["Z"]), links))
    pos = gc.combine(nodes, links, sx, sz, sy)                    # shown (x, y, z) -> Blender (x, z, y)

    def unit(idx, cnt):                                           # -1..1 across the grid
        half = _math(nodes, "MAXIMUM", _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", cnt, 1, links), 0.5, links), 0.5, links)
        return _math(nodes, "DIVIDE", centred(idx, cnt), half, links)

    ux, uy, uz = unit(ix, cx), unit(iy, cy), unit(iz, cz)

    def length(*v):
        total = 0.0
        for u in v:
            total = _math(nodes, "ADD", total, _math(nodes, "MULTIPLY", u, u, links), links)
        return _math(nodes, "SQRT", total, None, links)

    box = _math(nodes, "MAXIMUM", _math(nodes, "MAXIMUM", _math(nodes, "ABSOLUTE", ux, None, links), _math(nodes, "ABSOLUTE", uy, None, links), links),
                _math(nodes, "ABSOLUTE", uz, None, links), links)
    d = gc.index_switch(nodes, links, "FLOAT", o["Form"], [box, length(ux, uy, uz), length(ux, uz), box])
    # Fill: 100 % keeps the whole form, less keeps only an outer shell of that thickness
    shell = _math(nodes, "GREATER_THAN", d, _math(nodes, "SUBTRACT", 1.0, _math(nodes, "ADD", _math(nodes, "DIVIDE", o["Fill"], 100.0, links), 1e-4, links), links), links)
    keep = _math(nodes, "MULTIPLY", shell, _math(nodes, "LESS_THAN", d, 1.0005, links), links)
    inside = _inside(nodes, links, o["Form Object"], pos)
    keep = gc.index_switch(nodes, links, "FLOAT", o["Form"], [keep, keep, keep, inside])
    uv = gc.combine(nodes, links, _ramp(nodes, links, ix, cx), _ramp(nodes, links, iy, cy), None)
    return n, pos, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), keep, uv


def _inside(nodes, links, obj_sock, point):
    """1 where point is inside the object's mesh: a ray up from the point crosses the surface an odd number of times
    is too costly; the nearest face's normal pointing away from the point says inside."""
    info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"
    links.new(obj_sock, info.inputs["Object"])
    near = nodes.new("GeometryNodeSampleNearestSurface"); near.data_type = "FLOAT_VECTOR"
    links.new(info.outputs["Geometry"], near.inputs["Mesh"])
    normal = nodes.new("GeometryNodeInputNormal")
    links.new(normal.outputs[0], near.inputs["Value"]); links.new(point, near.inputs["Sample Position"])
    pos_near = nodes.new("GeometryNodeSampleNearestSurface"); pos_near.data_type = "FLOAT_VECTOR"
    links.new(info.outputs["Geometry"], pos_near.inputs["Mesh"])
    links.new(gc.position(nodes), pos_near.inputs["Value"]); links.new(point, pos_near.inputs["Sample Position"])
    away = gc.vmath(nodes, links, "SUBTRACT", pos_near.outputs["Value"], point)
    return _math(nodes, "GREATER_THAN", gc.dot(nodes, links, away, near.outputs["Value"]), 0.0, links)


def _honeycomb(nodes, links, o, i):
    by_height = _math(nodes, "GREATER_THAN", o["Honeycomb Direction"], 0.5, links)
    along = gc.switch(nodes, links, "FLOAT", by_height, o["Width Count"], o["Height Count"])
    across = gc.switch(nodes, links, "FLOAT", by_height, o["Height Count"], o["Width Count"])
    n = _math(nodes, "MULTIPLY", along, across, links)
    ia = _math(nodes, "FLOORED_MODULO", i, along, links)
    ib = _math(nodes, "FLOOR", _math(nodes, "DIVIDE", i, along, links), None, links)
    end = _math(nodes, "GREATER_THAN", o["Honeycomb Mode"], 0.5, links)       # End Point: Width/Height are the whole size

    def spacing(size, cnt):
        return _cm(nodes, links, gc.switch(nodes, links, "FLOAT", end, size,
                                           _math(nodes, "DIVIDE", size, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", cnt, 1, links), 1.0, links), links)))
    wa = spacing(gc.switch(nodes, links, "FLOAT", by_height, o["Width"], o["Height"]), along)
    wb = spacing(gc.switch(nodes, links, "FLOAT", by_height, o["Height"], o["Width"]), across)
    odd = _math(nodes, "FLOORED_MODULO", ib, 2.0, links)
    shift = _math(nodes, "MULTIPLY", odd, _math(nodes, "DIVIDE", o["Honeycomb Offset"], 100.0, links), links)   # 100 % = one cell
    a = _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", _math(nodes, "ADD", ia, shift, links), _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", along, 1, links), 0.5, links), links), wa, links)
    b = _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", ib, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", across, 1, links), 0.5, links), links), wb, links)
    x, y = gc.switch(nodes, links, "FLOAT", by_height, a, b), gc.switch(nodes, links, "FLOAT", by_height, b, a)
    pos = gc.index_switch(nodes, links, "VECTOR", o["Honeycomb Plane"],
                          [gc.combine(nodes, links, x, None, y), gc.combine(nodes, links, None, x, y), gc.combine(nodes, links, x, y, None)])
    # Circle: the cells inside the ellipse that fits the honeycomb; Spline: the cells inside a closed spline
    half_x = _math(nodes, "MAXIMUM", _math(nodes, "MULTIPLY", _math(nodes, "MULTIPLY", gc.switch(nodes, links, "FLOAT", by_height, wa, wb),
                                                                     gc.switch(nodes, links, "FLOAT", by_height, along, across), links), 0.5, links), 1e-6, links)
    half_y = _math(nodes, "MAXIMUM", _math(nodes, "MULTIPLY", _math(nodes, "MULTIPLY", gc.switch(nodes, links, "FLOAT", by_height, wb, wa),
                                                                     gc.switch(nodes, links, "FLOAT", by_height, across, along), links), 0.5, links), 1e-6, links)
    rx, ry = _math(nodes, "DIVIDE", x, half_x, links), _math(nodes, "DIVIDE", y, half_y, links)
    circle = _math(nodes, "LESS_THAN", _math(nodes, "ADD", _math(nodes, "MULTIPLY", rx, rx, links), _math(nodes, "MULTIPLY", ry, ry, links), links), 1.0, links)
    info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"
    links.new(o["Honeycomb Spline"], info.inputs["Object"])
    p = gc.separate(nodes, links, gc.position(nodes))
    flat = nodes.new("GeometryNodeSetPosition"); links.new(info.outputs["Geometry"], flat.inputs["Geometry"])
    links.new(gc.index_switch(nodes, links, "VECTOR", o["Honeycomb Plane"],
                              [gc.combine(nodes, links, p["X"], p["Z"], None), gc.combine(nodes, links, p["Y"], p["Z"], None),
                               gc.combine(nodes, links, p["X"], p["Y"], None)]), flat.inputs["Position"])
    fill = nodes.new("GeometryNodeFillCurve"); links.new(flat.outputs["Geometry"], fill.inputs["Curve"])
    ray = nodes.new("GeometryNodeRaycast"); links.new(fill.outputs["Mesh"], ray.inputs["Target Geometry"])
    links.new(gc.combine(nodes, links, x, y, 1.0), ray.inputs["Source Position"])
    ray.inputs["Ray Direction"].default_value = (0.0, 0.0, -1.0); ray.inputs["Ray Length"].default_value = 2.0
    keep = gc.index_switch(nodes, links, "FLOAT", o["Honeycomb Form"], [1.0, circle, ray.outputs["Is Hit"]])
    uv = gc.combine(nodes, links, _ramp(nodes, links, ia, along), _ramp(nodes, links, ib, across), None)
    return n, pos, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), keep, uv


def _object_points(nodes, links, o):
    """Object mode: points on the linked object (in the Cloner's space), with a direction for Align Clone."""
    info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"
    links.new(o["Object"], info.inputs["Object"])
    mesh = info.outputs["Geometry"]
    normal = nodes.new("GeometryNodeInputNormal").outputs[0]
    # Vertex
    m2p = nodes.new("GeometryNodeMeshToPoints"); m2p.mode = "VERTICES"; links.new(mesh, m2p.inputs["Mesh"])
    verts = _store(nodes, links, m2p.outputs["Points"], "b4d_dir", "FLOAT_VECTOR", normal)
    # Edge: the middle of each edge
    m2e = nodes.new("GeometryNodeMeshToPoints"); m2e.mode = "EDGES"; links.new(mesh, m2e.inputs["Mesh"])
    edges = _store(nodes, links, m2e.outputs["Points"], "b4d_dir", "FLOAT_VECTOR", normal)
    # Polygon Center
    m2f = nodes.new("GeometryNodeMeshToPoints"); m2f.mode = "FACES"; links.new(mesh, m2f.inputs["Mesh"])
    faces = _store(nodes, links, m2f.outputs["Points"], "b4d_dir", "FLOAT_VECTOR", normal)
    # Surface: Count points scattered over the faces
    dist = nodes.new("GeometryNodeDistributePointsOnFaces"); dist.distribute_method = "RANDOM"
    links.new(mesh, dist.inputs["Mesh"])
    area = nodes.new("GeometryNodeInputMeshFaceArea")
    total = nodes.new("GeometryNodeAttributeStatistic"); total.domain = "FACE"; links.new(mesh, total.inputs["Geometry"])
    links.new(area.outputs[0], total.inputs["Attribute"])
    links.new(_math(nodes, "DIVIDE", o["Object Count"], _math(nodes, "MAXIMUM", total.outputs["Sum"], 1e-9, links), links), dist.inputs["Density"])
    links.new(o["Seed"], dist.inputs["Seed"])
    surf = _store(nodes, links, dist.outputs["Points"], "b4d_dir", "FLOAT_VECTOR", dist.outputs["Normal"])
    # Volume: Count points inside the mesh
    vol = nodes.new("GeometryNodeMeshToVolume"); links.new(mesh, vol.inputs["Mesh"])
    vd = nodes.new("GeometryNodeDistributePointsInVolume"); links.new(vol.outputs["Volume"], vd.inputs["Volume"])
    bb = nodes.new("GeometryNodeBoundBox"); links.new(mesh, bb.inputs["Geometry"])
    ext = gc.separate(nodes, links, gc.vmath(nodes, links, "SUBTRACT", bb.outputs["Max"], bb.outputs["Min"]))
    box_vol = _math(nodes, "MULTIPLY", _math(nodes, "MULTIPLY", ext["X"], ext["Y"], links), ext["Z"], links)
    links.new(_math(nodes, "DIVIDE", _math(nodes, "MULTIPLY", o["Object Count"], 2.0, links), _math(nodes, "MAXIMUM", box_vol, 1e-9, links), links), vd.inputs["Density"])
    links.new(o["Seed"], vd.inputs["Seed"])
    up = gc.combine(nodes, links, None, None, 1.0)
    volume = _store(nodes, links, vd.outputs["Points"], "b4d_dir", "FLOAT_VECTOR", up)
    # Axis: one clone at the object's origin
    one = nodes.new("GeometryNodePoints"); one.inputs["Count"].default_value = 1
    links.new(info.outputs["Location"], one.inputs["Position"])
    axis = _store(nodes, links, one.outputs["Points"], "b4d_dir", "FLOAT_VECTOR", up)
    pts = gc.index_switch(nodes, links, "GEOMETRY", o["Distribution"], [verts, edges, faces, surf, volume, axis])
    al = nodes.new("FunctionNodeAlignRotationToVector"); al.axis = "Z"; al.pivot_axis = "AUTO"
    links.new(_attr(nodes, "b4d_dir", "FLOAT_VECTOR"), al.inputs["Vector"])
    straight = nodes.new("FunctionNodeEulerToRotation")
    rot = gc.switch(nodes, links, "ROTATION", o["Align Clone"], straight.outputs[0], al.outputs[0])
    pts = _store(nodes, links, pts, "b4d_rot_q", "QUATERNION", rot)
    # a spline: Count clones spread evenly along it (Axis: one at its origin), turned along the spline with Align Clone
    c2p = nodes.new("GeometryNodeCurveToPoints"); c2p.mode = "COUNT"
    links.new(info.outputs["Geometry"], c2p.inputs["Curve"]); links.new(o["Object Count"], c2p.inputs["Count"])
    along = gc.switch(nodes, links, "ROTATION", o["Align Clone"], nodes.new("FunctionNodeEulerToRotation").outputs[0], c2p.outputs["Rotation"])
    on_curve = _store(nodes, links, c2p.outputs["Points"], "b4d_rot_q", "QUATERNION", along)
    is_axis = _math(nodes, "GREATER_THAN", o["Distribution"], 4.5, links)
    on_curve = gc.switch(nodes, links, "GEOMETRY", is_axis, on_curve, nodes.new("GeometryNodeJoinGeometry").outputs[0])
    return gc.join(nodes, links, [pts, on_curve])


# --- the clones ----------------------------------------------------------------------------------------------------

def clone_points(nodes, links, o):
    """One point per clone with its starting state, before effectors."""
    i = nodes.new("GeometryNodeInputIndex").outputs[0]
    layouts = [_linear(nodes, links, o, i), _radial(nodes, links, o, i), _grid(nodes, links, o, i), _honeycomb(nodes, links, o, i)]
    mode = _math(nodes, "SUBTRACT", o["Mode"], 1, links)                   # 0 Object, 1 Linear ... -> layouts index
    pts = nodes.new("GeometryNodePoints")
    links.new(gc.index_switch(nodes, links, "INT", mode, [l[0] for l in layouts]), pts.inputs["Count"])
    place = nodes.new("GeometryNodeSetPosition"); links.new(pts.outputs["Points"], place.inputs["Geometry"])     # real points first: Accumulate reads them
    links.new(gc.index_switch(nodes, links, "VECTOR", mode, [l[1] for l in layouts]), place.inputs["Position"])
    geo = place.outputs["Geometry"]
    rot = _euler(nodes, links, gc.index_switch(nodes, links, "VECTOR", mode, [l[2] for l in layouts]))
    geo = _store(nodes, links, geo, "b4d_rot_q", "QUATERNION", rot)
    geo = _store(nodes, links, geo, "b4d_scale", "FLOAT_VECTOR", gc.index_switch(nodes, links, "VECTOR", mode, [l[3] for l in layouts]))
    geo = _store(nodes, links, geo, "b4d_uv", "FLOAT_VECTOR", gc.index_switch(nodes, links, "VECTOR", mode, [l[5] for l in layouts]))
    drop = nodes.new("GeometryNodeDeleteGeometry"); drop.domain = "POINT"; links.new(geo, drop.inputs["Geometry"])
    links.new(_math(nodes, "LESS_THAN", gc.index_switch(nodes, links, "FLOAT", mode, [l[4] for l in layouts]), 0.5, links), drop.inputs["Selection"])
    arranged = drop.outputs["Geometry"]
    obj = _store(nodes, links, _object_points(nodes, links, o), "b4d_scale", "FLOAT_VECTOR", gc.combine(nodes, links, 1.0, 1.0, 1.0))
    oi = nodes.new("GeometryNodeInputIndex").outputs[0]
    obj = _store(nodes, links, obj, "b4d_uv", "FLOAT_VECTOR", gc.combine(nodes, links, _ramp(nodes, links, oi, _count_of(nodes, links, obj)), None, None))
    geo = gc.switch(nodes, links, "GEOMETRY", _math(nodes, "LESS_THAN", o["Mode"], 0.5, links), arranged, obj)
    # the Transform tab acts on every clone, in the clone's own space
    sp = nodes.new("GeometryNodeSetPosition"); links.new(geo, sp.inputs["Geometry"])
    rv = nodes.new("FunctionNodeRotateVector"); links.new(_shown_vec(nodes, links, o["Clone Position"], 0.01), rv.inputs["Vector"])
    links.new(_attr(nodes, "b4d_rot_q", "QUATERNION"), rv.inputs["Rotation"])
    links.new(rv.outputs[0], sp.inputs["Offset"])
    geo = sp.outputs["Geometry"]
    rr = nodes.new("FunctionNodeRotateRotation"); rr.rotation_space = "LOCAL"
    links.new(_attr(nodes, "b4d_rot_q", "QUATERNION"), rr.inputs["Rotation"]); links.new(_euler(nodes, links, o["Clone Rotation"]), rr.inputs["Rotate By"])
    geo = _store(nodes, links, geo, "b4d_rot_q", "QUATERNION", rr.outputs[0])
    geo = _store(nodes, links, geo, "b4d_scale", "FLOAT_VECTOR",
                 gc.vmath(nodes, links, "MULTIPLY", _attr(nodes, "b4d_scale", "FLOAT_VECTOR"), _shown_vec(nodes, links, o["Clone Scale"], 0.01)))
    geo = _store(nodes, links, geo, "b4d_color", "FLOAT_COLOR", o["Clone Color"])
    geo = _store(nodes, links, geo, "b4d_weight", "FLOAT", _math(nodes, "DIVIDE", o["Clone Weight"], 100.0, links))
    idx = nodes.new("GeometryNodeInputIndex").outputs[0]
    geo = _store(nodes, links, geo, "b4d_u", "FLOAT", _ramp(nodes, links, idx, _count_of(nodes, links, geo)))
    geo = _store(nodes, links, geo, "b4d_index", "INT", idx)
    return geo


def _pick(nodes, links, o, n_children, geo):
    """Which child each clone shows: Iterate (in turn, in Object Manager order) or Random."""
    i = _attr(nodes, "b4d_index", "INT")
    it = _math(nodes, "FLOORED_MODULO", i, n_children, links)
    rnd = _rand(nodes, links, 0, n_children - 1, i, o["Seed"], typ="INT")
    return gc.index_switch(nodes, links, "INT", o["Clones"], [it, rnd])


CLONE_COLOR = "Clone Color"


def clone_color_material():
    """A material that shows each clone's colour (the Cloner's Color and the effectors' colours). Other materials can
    show it too: an Attribute node, Type Instancer, Name b4d_color."""
    m = bpy.data.materials.get(CLONE_COLOR)
    if m is not None:
        return m
    m = bpy.data.materials.new(CLONE_COLOR)
    # clones carry the colour as an instance attribute; clone bodies (dynamics) and made-editable clones carry it as
    # their object colour: the attribute's alpha picks which
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    at = nt.nodes.new("ShaderNodeAttribute"); at.attribute_type = "INSTANCER"; at.attribute_name = "b4d_color"
    at.location = (bsdf.location.x - 260, bsdf.location.y)
    oi = nt.nodes.new("ShaderNodeObjectInfo"); oi.location = (bsdf.location.x - 260, bsdf.location.y - 200)
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.location = (bsdf.location.x - 140, bsdf.location.y)
    nt.links.new(at.outputs["Alpha"], mix.inputs["Factor"])
    nt.links.new(oi.outputs["Color"], mix.inputs[6]); nt.links.new(at.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return m


def build_cloner(nodes, links, o, kids, effect=None):
    """kids: [(child object, geometry in the Cloner's space)]. effect(geo) -> geo applies the effectors."""
    geo = clone_points(nodes, links, o)
    if effect is not None:
        geo = effect(nodes, links, geo)
    shapes = []
    bare = clone_color_material()
    for child, rel in kids:
        # Reset Coordinates: each clone is the child as it is in its own space; off: the child keeps its offset from the Cloner
        own = nodes.new("GeometryNodeObjectInfo"); own.transform_space = "ORIGINAL"
        own.inputs["Object"].default_value = child
        # Reset Coordinates drops only the child's place: its own rotation and scale stay on every clone
        place = nodes.new("GeometryNodeObjectInfo"); place.transform_space = "RELATIVE"
        place.inputs["Object"].default_value = child
        turned = gc.move(nodes, links, own.outputs["Geometry"], rotation=place.outputs["Rotation"], scale=place.outputs["Scale"])
        shape = gc.switch(nodes, links, "GEOMETRY", o["Reset Coordinates"], rel, turned)
        if not any(sl.material for sl in getattr(child, "material_slots", [])):
            # a child with no material wears Clone Color: each clone shows its own colour in Material and Render view
            sm = nodes.new("GeometryNodeSetMaterial"); links.new(shape, sm.inputs["Geometry"])
            sm.inputs["Material"].default_value = bare
            shape = sm.outputs["Geometry"]
        shapes.append(shape)
    if not shapes:
        return nodes.new("GeometryNodeJoinGeometry").outputs[0]
    g2i = nodes.new("GeometryNodeGeometryToInstance")
    for g in reversed(shapes):                                   # the socket keeps the last link first
        links.new(g, g2i.inputs[0])
    inst = nodes.new("GeometryNodeInstanceOnPoints")
    links.new(geo, inst.inputs["Points"]); links.new(g2i.outputs[0], inst.inputs["Instance"])
    inst.inputs["Pick Instance"].default_value = True
    links.new(_pick(nodes, links, o, len(shapes), geo), inst.inputs["Instance Index"])
    links.new(_attr(nodes, "b4d_rot_q", "QUATERNION"), inst.inputs["Rotation"])
    links.new(_attr(nodes, "b4d_scale", "FLOAT_VECTOR"), inst.inputs["Scale"])
    # while a Rigid Body tag simulates the clones, their bodies show instead (moclone_dyn.py)
    return gc.switch(nodes, links, "GEOMETRY", o["Simulated"], inst.outputs["Instances"], nodes.new("GeometryNodeJoinGeometry").outputs[0])


def build_matrix(nodes, links, o, kids, effect=None):
    """The Matrix: the clone points, drawn as small cubes in the viewport (and in renders only with Show in Render)."""
    o = dict(o)
    o.setdefault("Clones", 0)
    geo = clone_points(nodes, links, o)
    if effect is not None:
        geo = effect(nodes, links, geo)
    cube = nodes.new("GeometryNodeMeshCube")
    s = _cm(nodes, links, o["Matrix Size"])
    links.new(gc.combine(nodes, links, s, s, s), cube.inputs["Size"])
    inst = nodes.new("GeometryNodeInstanceOnPoints")
    links.new(geo, inst.inputs["Points"]); links.new(cube.outputs["Mesh"], inst.inputs["Instance"])
    links.new(_attr(nodes, "b4d_rot_q", "QUATERNION"), inst.inputs["Rotation"])
    links.new(_attr(nodes, "b4d_scale", "FLOAT_VECTOR"), inst.inputs["Scale"])
    # the points go along (a Cloner in Object mode can clone onto a Matrix's points)
    shown = gc.join(nodes, links, [inst.outputs["Instances"], geo])
    view = nodes.new("GeometryNodeIsViewport").outputs[0]
    visible = _math(nodes, "MAXIMUM", view, o["Show in Render"], links)
    return gc.switch(nodes, links, "GEOMETRY", _math(nodes, "GREATER_THAN", visible, 0.5, links), geo, shown)
