# SPDX-License-Identifier: GPL-3.0-or-later
"""Pieces as clones: Fracture, Voronoi Fracture, MoText and PolyFX hand their pieces (each marked with a piece
number) to the effectors the way a Cloner hands over its clones.

One point is made per piece, at the piece's centre, carrying the usual clone state (moclone_nodes.py). The effectors
change those points; then every point of every piece is moved, turned and scaled with its piece's point. Pieces an
effector hides are taken out."""
import bpy

from . import gen_caps as gc
from .primitives import _math

PIECE = "b4d_piece"
PIECE_COLOR = "Piece Color"


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


def _accumulate(nodes, links, typ, value, group, out="Total"):
    a = nodes.new("GeometryNodeAccumulateField"); a.data_type = typ; a.domain = "POINT"
    if hasattr(value, "is_output"):
        links.new(value, a.inputs[0])
    else:
        a.inputs[0].default_value = value
    links.new(group, [s for s in a.inputs if s.name in ("Group ID", "Group Index")][0])
    return a.outputs[out]


def piece_color_material():
    """Shows each piece's colour (its clone colour) on pieces that have no material of their own."""
    m = bpy.data.materials.get(PIECE_COLOR)
    if m is not None:
        return m
    m = bpy.data.materials.new(PIECE_COLOR)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    at = nt.nodes.new("ShaderNodeAttribute"); at.attribute_type = "GEOMETRY"; at.attribute_name = "b4d_color"
    at.location = (bsdf.location.x - 260, bsdf.location.y)
    nt.links.new(at.outputs["Color"], bsdf.inputs["Base Color"])
    return m


def bare_material(nodes, links, geo):
    """Faces with no material wear Piece Color."""
    sm = nodes.new("GeometryNodeSetMaterial"); links.new(geo, sm.inputs["Geometry"])
    sm.inputs["Material"].default_value = piece_color_material()
    return sm.outputs["Geometry"]


def pieces_effect(nodes, links, mesh, effect, o=None, piece=PIECE, colors=None, frame=None, blend=None):
    """mesh: geometry whose points carry an INT attribute `piece` numbered 0..N-1. effect(nodes, links, points) ->
    points runs the effectors (moclone_fx.effect_fn(..., drop_hidden=False)). o: the generator's settings, for the
    Transform tab (Clone Position, Scale, Rotation, Color, Weight). colors: a colour field per piece, or None.
    frame: each piece's own starting rotation (a field on the mesh, e.g. turned to its face's normal), so effectors
    move, turn and scale it in its own axes. blend: a field on the mesh, 0..1 per point, for how much of its piece's
    change each point takes (PolyFX Partial); None is all of it."""
    pid = _attr(nodes, piece, "INT")
    pos = gc.position(nodes)
    total = _accumulate(nodes, links, "FLOAT_VECTOR", pos, pid)
    count = _accumulate(nodes, links, "FLOAT", 1.0, pid)
    centre = gc.vmath(nodes, links, "SCALE", total, scale=_math(nodes, "DIVIDE", 1.0, _math(nodes, "MAXIMUM", count, 1.0, links), links))
    mesh = _store(nodes, links, mesh, "b4d_centre", "FLOAT_VECTOR", centre)
    if frame is not None:
        mesh = _store(nodes, links, mesh, "b4d_rot0", "QUATERNION", frame)
    if blend is not None:
        mesh = _store(nodes, links, mesh, "b4d_blend", "FLOAT", blend)
    first = _math(nodes, "COMPARE", _accumulate(nodes, links, "INT", 1, pid, "Leading"), 1.0, links)
    sep = nodes.new("GeometryNodeSeparateGeometry"); sep.domain = "POINT"
    links.new(mesh, sep.inputs["Geometry"]); links.new(first, sep.inputs["Selection"])
    m2p = nodes.new("GeometryNodeMeshToPoints"); m2p.mode = "VERTICES"; links.new(sep.outputs["Selection"], m2p.inputs["Mesh"])
    sp = nodes.new("GeometryNodeSetPosition"); links.new(m2p.outputs["Points"], sp.inputs["Geometry"])
    links.new(_attr(nodes, "b4d_centre", "FLOAT_VECTOR"), sp.inputs["Position"])
    srt = nodes.new("GeometryNodeSortElements"); srt.domain = "POINT"
    links.new(sp.outputs["Geometry"], srt.inputs["Geometry"]); links.new(_attr(nodes, piece, "INT"), srt.inputs["Sort Weight"])
    pts = srt.outputs["Geometry"]
    # the clone state of each piece
    idx = _attr(nodes, piece, "INT")
    n = nodes.new("GeometryNodeAttributeDomainSize"); n.component = "POINTCLOUD"; links.new(pts, n.inputs["Geometry"])
    u = _math(nodes, "DIVIDE", idx, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", n.outputs["Point Count"], 1.0, links), 1.0, links), links)
    pts = _store(nodes, links, pts, "b4d_index", "INT", idx)
    pts = _store(nodes, links, pts, "b4d_u", "FLOAT", u)
    pts = _store(nodes, links, pts, "b4d_uv", "FLOAT_VECTOR", gc.combine(nodes, links, u, None, None))
    rot = nodes.new("FunctionNodeEulerToRotation").outputs[0] if frame is None else _attr(nodes, "b4d_rot0", "QUATERNION")
    scale = (1.0, 1.0, 1.0)
    color = (1.0, 1.0, 1.0, 1.0) if colors is None else colors
    weight = 0.0
    if o is not None and "Clone Position" in o:
        from .moclone_nodes import _shown_vec, _euler
        ps = nodes.new("GeometryNodeSetPosition"); links.new(pts, ps.inputs["Geometry"])
        links.new(_shown_vec(nodes, links, o["Clone Position"], 0.01), ps.inputs["Offset"])
        pts = ps.outputs["Geometry"]
        rr = nodes.new("FunctionNodeRotateRotation"); rr.rotation_space = "LOCAL"
        links.new(rot, rr.inputs["Rotation"]); links.new(_euler(nodes, links, o["Clone Rotation"]), rr.inputs["Rotate By"])
        rot = rr.outputs[0]
        scale = _shown_vec(nodes, links, o["Clone Scale"], 0.01)
        if colors is None:
            color = o["Clone Color"]
        weight = _math(nodes, "DIVIDE", o["Clone Weight"], 100.0, links)
    pts = _store(nodes, links, pts, "b4d_rot_q", "QUATERNION", rot)
    pts = _store(nodes, links, pts, "b4d_scale", "FLOAT_VECTOR", scale)
    pts = _store(nodes, links, pts, "b4d_color", "FLOAT_COLOR", color)
    pts = _store(nodes, links, pts, "b4d_weight", "FLOAT", weight)
    if effect is not None:
        pts = effect(nodes, links, pts)

    def mine(field, typ):
        s = nodes.new("GeometryNodeSampleIndex"); s.data_type = typ; s.domain = "POINT"
        links.new(pts, s.inputs["Geometry"]); links.new(field, s.inputs["Value"]); links.new(_attr(nodes, piece, "INT"), s.inputs["Index"])
        return s.outputs[0]

    off = gc.vmath(nodes, links, "SUBTRACT", gc.position(nodes), _attr(nodes, "b4d_centre", "FLOAT_VECTOR"))
    q = mine(_attr(nodes, "b4d_rot_q", "QUATERNION"), "QUATERNION")
    if frame is not None:                      # into the piece's own axes, scaled there, then turned to where it is now
        back = nodes.new("FunctionNodeInvertRotation"); links.new(_attr(nodes, "b4d_rot0", "QUATERNION"), back.inputs[0])
        loc = nodes.new("FunctionNodeRotateVector"); links.new(off, loc.inputs["Vector"]); links.new(back.outputs[0], loc.inputs["Rotation"])
        off = loc.outputs[0]
    off = gc.vmath(nodes, links, "MULTIPLY", off, mine(_attr(nodes, "b4d_scale", "FLOAT_VECTOR"), "FLOAT_VECTOR"))
    rv = nodes.new("FunctionNodeRotateVector"); links.new(off, rv.inputs["Vector"])
    links.new(q, rv.inputs["Rotation"])
    moved = gc.vmath(nodes, links, "ADD", mine(gc.position(nodes), "FLOAT_VECTOR"), rv.outputs[0])
    if blend is not None:
        from .moclone_fx import _mix
        moved = _mix(nodes, links, "VECTOR", _attr(nodes, "b4d_blend", "FLOAT"), gc.position(nodes), moved)
    mv = nodes.new("GeometryNodeSetPosition"); links.new(mesh, mv.inputs["Geometry"])
    links.new(moved, mv.inputs["Position"])
    out = _store(nodes, links, mv.outputs["Geometry"], "b4d_color", "FLOAT_COLOR", mine(_attr(nodes, "b4d_color", "FLOAT_COLOR"), "FLOAT_COLOR"))
    drop = nodes.new("GeometryNodeDeleteGeometry"); drop.domain = "POINT"; links.new(out, drop.inputs["Geometry"])
    links.new(_math(nodes, "GREATER_THAN", mine(_attr(nodes, "b4d_hidden", "FLOAT"), "FLOAT"), 0.5, links), drop.inputs["Selection"])
    rm = nodes.new("GeometryNodeRemoveAttribute"); links.new(drop.outputs["Geometry"], rm.inputs["Geometry"])
    rm.inputs["Name"].default_value = "b4d_centre"
    out = rm.outputs["Geometry"]
    for name in (("b4d_rot0",) if frame is not None else ()) + (("b4d_blend",) if blend is not None else ()):
        r2 = nodes.new("GeometryNodeRemoveAttribute"); links.new(out, r2.inputs["Geometry"]); r2.inputs["Name"].default_value = name
        out = r2.outputs["Geometry"]
    return out


def random_colors(nodes, links, seed=0):
    """A bright random colour per piece (Colorize Fragments)."""
    from .moclone_fx import _rand
    h = _rand(nodes, links, 0.0, 1.0, _attr(nodes, PIECE, "INT"), seed)
    c = nodes.new("FunctionNodeCombineColor"); c.mode = "HSV"
    links.new(h, c.inputs[0]); c.inputs[1].default_value = 0.7; c.inputs[2].default_value = 0.9
    return c.outputs[0]
