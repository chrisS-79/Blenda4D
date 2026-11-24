# SPDX-License-Identifier: GPL-3.0-or-later
"""PolyFX and MoExtrude: MoClone objects that sit under a mesh, like deformers, and work on its faces.

PolyFX makes every face of the mesh a clone the effectors in its list move, turn and scale in the face's own axes
(Full Polys); Partial lets its fields decide, point by point, how much of that each point takes. MoExtrude pushes
faces out in steps; each step moves, scales and turns by the Transform tab and by the effectors in its list (Per Step:
the change adds up step after step; From Root: each step is a clone of its own, step 0 at the root).

They use the deformer system (deformers.py): one node tree per object, a modifier on every mesh it reaches. Their
settings are Blender properties read by drivers; changing the Effectors list or the Polygon Selection rebuilds the tree."""
import math

import bpy

from . import gen_caps as gc
from . import moclone_pieces as mp
from .primitives import _math

KINDS = {"polyfx": ("PolyFX", "MOD_TRIANGULATE", "EMPTY", "Makes every face of the mesh it sits under a clone the effectors move", {}),
         "moextrude": ("MoExtrude", "MOD_SOLIDIFY", "EMPTY", "Pushes the faces of the mesh it sits under out in steps the effectors shape", {})}
SIG = "b4d_fx_sig"


def _live(self, context):
    from .moclone_fx_ui import _live as live
    live(self, context)


def _rebuild(self, context):
    self[SIG] = []
    self.update_tag()


def props():
    O, P = bpy.types.Object, bpy.props
    O.b4d_pfx_mode = P.EnumProperty(name="Mode", items=[("FULL", "Full Polys", "Each face moves, turns and scales as one piece", 0),
                                                        ("PARTIAL", "Partial Polys", "Each point takes as much as the PolyFX's own fields give there", 1)],
                                    default="FULL", update=_live)
    O.b4d_mx_mode = P.EnumProperty(name="Transform", items=[("STEP", "Per Step", "The change is added again at every step", 0),
                                                           ("ROOT", "From Root", "Each step is a clone of its own, numbered from the root", 1)],
                                   default="STEP", update=_rebuild)
    O.b4d_mx_steps = P.IntProperty(name="Extrusion Steps", default=3, min=0, max=500, update=_live)
    O.b4d_mx_selection = P.StringProperty(name="Polygon Selection", default="", update=_rebuild,
                                          description="Only the faces in this face selection (a true/false face attribute); empty: every face")
    O.b4d_mx_pos = P.FloatVectorProperty(name="P", size=3, default=(0.0, 0.0, 20.0), update=_live,
                                         description="Each step's move in the face's own axes (cm): Z is outward along the face")
    O.b4d_mx_scale = P.FloatVectorProperty(name="S", size=3, default=(100.0, 100.0, 100.0), update=_live,
                                           description="Each step's size in % of the step before")
    O.b4d_mx_rot = P.FloatVectorProperty(name="R", size=3, default=(0.0, 0.0, 0.0), update=_live, description="Each step's turn (degrees)")


def signature(ob):
    from . import moclone_fx
    return moclone_fx.signature(ob) + [f"mx:{getattr(ob, 'b4d_mx_mode', '')}:{getattr(ob, 'b4d_mx_selection', '')}"]


# --- trees ---------------------------------------------------------------------------------------------------------

def _face_frame(nodes, links, normal):
    """The face's own axes: its shown Z (Blender's local Y) is the face's normal, as for every clone."""
    a = nodes.new("FunctionNodeAlignRotationToVector"); a.axis = "Y"; a.pivot_axis = "AUTO"
    links.new(normal, a.inputs["Vector"])
    return a.outputs[0]


def fill_polyfx(tree, ob):
    from . import moclone_fx
    from .moclone_fx import _driven
    nodes, links = tree.nodes, tree.links
    gin, gout = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput"); gout.is_active_output = True
    split = nodes.new("GeometryNodeSplitEdges"); links.new(gin.outputs["Geometry"], split.inputs["Mesh"])
    mesh = split.outputs["Mesh"]
    mesh = mp._store(nodes, links, mesh, mp.PIECE, "INT", nodes.new("GeometryNodeInputMeshIsland").outputs["Island Index"])
    frame = _face_frame(nodes, links, nodes.new("GeometryNodeInputNormal").outputs[0])
    mode = _driven(nodes, ob, "b4d_pfx_mode")                       # also marks the tree as this PolyFX's own
    fall = moclone_fx.falloff(nodes, links, ob)
    blend = None
    if fall is not None:
        partial = _math(nodes, "COMPARE", mode, 1.0, links)
        blend = _math(nodes, "ADD", _math(nodes, "MULTIPLY", partial, fall, links), _math(nodes, "SUBTRACT", 1.0, partial, links), links)
    out = mp.pieces_effect(nodes, links, mesh, moclone_fx.effect_fn(ob, drop_hidden=False), None, frame=frame, blend=blend)
    links.new(out, gout.inputs[0])
    ob[SIG] = signature(ob)


def _selection(nodes, ob):
    name = getattr(ob, "b4d_mx_selection", "")
    if not name:
        return True
    a = nodes.new("GeometryNodeInputNamedAttribute"); a.data_type = "BOOLEAN"; a.inputs["Name"].default_value = name
    return a.outputs["Attribute"]


def fill_moextrude(tree, ob):
    from . import moclone_fx
    from .moclone_fx import _driven, _vec, _euler
    nodes, links = tree.nodes, tree.links
    gin, gout = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput"); gout.is_active_output = True
    mesh = gin.outputs["Geometry"]
    sel = _selection(nodes, ob)
    mesh = mp._store(nodes, links, mesh, "b4d_top", "BOOLEAN", sel, domain="FACE")
    # each selected face's number among the selected (its clone), its centre and its own axes
    acc = nodes.new("GeometryNodeAccumulateField"); acc.data_type = "INT"; acc.domain = "FACE"
    links.new(mp._attr(nodes, "b4d_top", "BOOLEAN"), acc.inputs[0])
    mesh = mp._store(nodes, links, mesh, "b4d_rank", "INT", _math(nodes, "SUBTRACT", acc.outputs["Leading"], 1.0, links), domain="FACE")
    mesh = mp._store(nodes, links, mesh, "b4d_fn", "FLOAT_VECTOR", nodes.new("GeometryNodeInputNormal").outputs[0], domain="FACE")
    faces = nodes.new("GeometryNodeSeparateGeometry"); faces.domain = "FACE"
    links.new(mesh, faces.inputs["Geometry"]); links.new(mp._attr(nodes, "b4d_top", "BOOLEAN"), faces.inputs["Selection"])
    pts = nodes.new("GeometryNodeMeshToPoints"); pts.mode = "FACES"; links.new(faces.outputs["Selection"], pts.inputs["Mesh"])
    pts = pts.outputs["Points"]
    nfaces = nodes.new("GeometryNodeAttributeDomainSize"); nfaces.component = "POINTCLOUD"; links.new(pts, nfaces.inputs["Geometry"])
    nf = nfaces.outputs["Point Count"]
    steps = _math(nodes, "MAXIMUM", _driven(nodes, ob, "b4d_mx_steps"), 0.0, links)
    root = ob.b4d_mx_mode == "ROOT"
    if root:
        # From Root: a clone for every step of every face, numbered step by step from the root
        dup = nodes.new("GeometryNodeDuplicateElements"); dup.domain = "POINT"
        links.new(pts, dup.inputs["Geometry"]); links.new(_math(nodes, "MAXIMUM", steps, 1.0, links), dup.inputs["Amount"])
        pts = mp._store(nodes, links, dup.outputs["Geometry"], "b4d_k", "INT", dup.outputs["Duplicate Index"])
        srt = nodes.new("GeometryNodeSortElements"); srt.domain = "POINT"; links.new(pts, srt.inputs["Geometry"])
        links.new(_math(nodes, "ADD", _math(nodes, "MULTIPLY", mp._attr(nodes, "b4d_rank", "INT"), 100000.0, links), mp._attr(nodes, "b4d_k", "INT"), links),
                  srt.inputs["Sort Weight"])
        pts = srt.outputs["Geometry"]
        clone_idx = mp._attr(nodes, "b4d_k", "INT")
    else:
        clone_idx = mp._attr(nodes, "b4d_rank", "INT")
    frame0 = _face_frame(nodes, links, mp._attr(nodes, "b4d_fn", "FLOAT_VECTOR"))
    n = nodes.new("GeometryNodeAttributeDomainSize"); n.component = "POINTCLOUD"; links.new(pts, n.inputs["Geometry"])
    count = _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", steps if root else n.outputs["Point Count"], 1.0, links), 1.0, links)
    u = _math(nodes, "DIVIDE", clone_idx, count, links)
    pts = mp._store(nodes, links, pts, "b4d_index", "INT", clone_idx)
    pts = mp._store(nodes, links, pts, "b4d_u", "FLOAT", u)
    pts = mp._store(nodes, links, pts, "b4d_uv", "FLOAT_VECTOR", gc.combine(nodes, links, u, None, None))
    pts = mp._store(nodes, links, pts, "b4d_rot_q", "QUATERNION", frame0)
    pts = mp._store(nodes, links, pts, "b4d_scale", "FLOAT_VECTOR", (1.0, 1.0, 1.0))
    pts = mp._store(nodes, links, pts, "b4d_color", "FLOAT_COLOR", (1.0, 1.0, 1.0, 1.0))
    pts = mp._store(nodes, links, pts, "b4d_p0", "FLOAT_VECTOR", gc.position(nodes))
    pts = moclone_fx.effect_fn(ob, drop_hidden=False)(nodes, links, pts)
    # what the effectors did to each clone, in its face's axes
    inv0 = nodes.new("FunctionNodeInvertRotation"); links.new(frame0, inv0.inputs[0])
    dp = nodes.new("FunctionNodeRotateVector"); links.new(gc.vmath(nodes, links, "SUBTRACT", gc.position(nodes), mp._attr(nodes, "b4d_p0", "FLOAT_VECTOR")), dp.inputs["Vector"])
    links.new(inv0.outputs[0], dp.inputs["Rotation"])
    pts = mp._store(nodes, links, pts, "b4d_dp", "FLOAT_VECTOR", dp.outputs[0])
    dq = nodes.new("FunctionNodeRotateRotation"); dq.rotation_space = "GLOBAL"
    links.new(inv0.outputs[0], dq.inputs["Rotation"]); links.new(mp._attr(nodes, "b4d_rot_q", "QUATERNION"), dq.inputs["Rotate By"])
    pts = mp._store(nodes, links, pts, "b4d_dq", "QUATERNION", dq.outputs[0])
    fx_pts = pts
    # the steps
    # shown X, Y, Z in the face's axes (shown Z out along the face) -> Blender local X, Z, Y
    step_p = gc.vmath(nodes, links, "SCALE", _vec(nodes, links, ob, "b4d_mx_pos"), scale=0.01)
    step_s = gc.vmath(nodes, links, "SCALE", _vec(nodes, links, ob, "b4d_mx_scale"), scale=0.01)
    step_r = nodes.new("FunctionNodeEulerToRotation")
    links.new(gc.vmath(nodes, links, "SCALE", _vec(nodes, links, ob, "b4d_mx_rot"), scale=math.pi / 180.0), step_r.inputs[0])
    rin = nodes.new("GeometryNodeRepeatInput"); rout = nodes.new("GeometryNodeRepeatOutput"); rin.pair_with_output(rout)
    links.new(steps, rin.inputs["Iterations"]); links.new(mesh, rin.inputs["Geometry"])
    g = rin.outputs["Geometry"]
    k = rin.outputs["Iteration"]
    rank = mp._attr(nodes, "b4d_rank", "INT")
    which = rank if not root else _math(nodes, "ADD", _math(nodes, "MULTIPLY", rank, _math(nodes, "MAXIMUM", steps, 1.0, links), links), k, links)

    def fx(name, typ):
        s = nodes.new("GeometryNodeSampleIndex"); s.data_type = typ; s.domain = "POINT"
        links.new(fx_pts, s.inputs["Geometry"]); links.new(mp._attr(nodes, name, typ), s.inputs["Value"]); links.new(which, s.inputs["Index"])
        return s.outputs[0]

    ex = nodes.new("GeometryNodeExtrudeMesh"); ex.mode = "FACES"; ex.inputs["Individual"].default_value = True
    links.new(g, ex.inputs["Mesh"]); links.new(mp._attr(nodes, "b4d_top", "BOOLEAN"), ex.inputs["Selection"])
    # the move: the step's own P plus the effectors', in the face's axes (per face)
    fr = _face_frame(nodes, links, mp._attr(nodes, "b4d_fn", "FLOAT_VECTOR"))
    mv = nodes.new("FunctionNodeRotateVector"); links.new(gc.vmath(nodes, links, "ADD", step_p, fx("b4d_dp", "FLOAT_VECTOR")), mv.inputs["Vector"])
    links.new(fr, mv.inputs["Rotation"])
    links.new(mv.outputs[0], ex.inputs["Offset"])
    g2 = mp._store(nodes, links, ex.outputs["Mesh"], "b4d_top", "BOOLEAN", ex.outputs["Top"], domain="FACE")
    # turn and scale the new top faces around their centres, in their own axes
    top = mp._attr(nodes, "b4d_top", "BOOLEAN")                     # on points: a point of a top face
    tot = mp._accumulate(nodes, links, "FLOAT_VECTOR", gc.vmath(nodes, links, "SCALE", gc.position(nodes), scale=top), rank)
    cnt = mp._accumulate(nodes, links, "FLOAT", top, rank)
    centre = gc.vmath(nodes, links, "SCALE", tot, scale=_math(nodes, "DIVIDE", 1.0, _math(nodes, "MAXIMUM", cnt, 1e-6, links), links))
    back = nodes.new("FunctionNodeInvertRotation"); links.new(fr, back.inputs[0])
    loc = nodes.new("FunctionNodeRotateVector"); links.new(gc.vmath(nodes, links, "SUBTRACT", gc.position(nodes), centre), loc.inputs["Vector"])
    links.new(back.outputs[0], loc.inputs["Rotation"])
    scaled = gc.vmath(nodes, links, "MULTIPLY", gc.vmath(nodes, links, "MULTIPLY", loc.outputs[0], step_s), fx("b4d_scale", "FLOAT_VECTOR"))
    turn = nodes.new("FunctionNodeRotateRotation"); turn.rotation_space = "LOCAL"
    links.new(step_r.outputs[0], turn.inputs["Rotation"]); links.new(fx("b4d_dq", "QUATERNION"), turn.inputs["Rotate By"])
    t1 = nodes.new("FunctionNodeRotateVector"); links.new(scaled, t1.inputs["Vector"]); links.new(turn.outputs[0], t1.inputs["Rotation"])
    t2 = nodes.new("FunctionNodeRotateVector"); links.new(t1.outputs[0], t2.inputs["Vector"]); links.new(fr, t2.inputs["Rotation"])
    sp = nodes.new("GeometryNodeSetPosition"); links.new(g2, sp.inputs["Geometry"]); links.new(top, sp.inputs["Selection"])
    links.new(gc.vmath(nodes, links, "ADD", centre, t2.outputs[0]), sp.inputs["Position"])
    # the top faces now face their turned way: the next step goes on from there
    g3 = mp._store(nodes, links, sp.outputs["Geometry"], "b4d_fn", "FLOAT_VECTOR", nodes.new("GeometryNodeInputNormal").outputs[0], domain="FACE")
    links.new(g3, rout.inputs["Geometry"])
    out = rout.outputs["Geometry"]
    for name in ("b4d_top", "b4d_rank", "b4d_fn"):
        rm = nodes.new("GeometryNodeRemoveAttribute"); links.new(out, rm.inputs["Geometry"]); rm.inputs["Name"].default_value = name
        out = rm.outputs["Geometry"]
    links.new(out, gout.inputs[0])
    ob[SIG] = signature(ob)


FILL = {"polyfx": fill_polyfx, "moextrude": fill_moextrude}


def refill(tree, ob, kind):
    """Empty the tree and build it again (its interface stays)."""
    for nd in list(tree.nodes):
        tree.nodes.remove(nd)
    if tree.animation_data:
        for fc in list(tree.animation_data.drivers):
            tree.animation_data.drivers.remove(fc)
    FILL[kind](tree, ob)
    from .node_arrange import arrange
    arrange(tree)


# --- pages ---------------------------------------------------------------------------------------------------------

def page_polyfx(col, ob):
    c = col.column()
    c.prop(ob, "b4d_pfx_mode")
    if ob.b4d_pfx_mode == "PARTIAL":
        c.label(text="Partial uses the fields on the PolyFX's own Fields tab", icon="INFO")
    if ob.parent is None or ob.parent.type != "MESH":
        c.label(text="Put the PolyFX under a polygon object", icon="INFO")


def page_moextrude(col, ob):
    c = col.column()
    c.prop(ob, "b4d_mx_mode"); c.prop(ob, "b4d_mx_steps"); c.prop(ob, "b4d_mx_selection")
    if ob.parent is None or ob.parent.type != "MESH":
        c.label(text="Put the MoExtrude under a polygon object", icon="INFO")


def page_mx_transform(col, ob):
    c = col.column(align=True)
    for i, a in enumerate("XYZ"):
        c.prop(ob, "b4d_mx_pos", index=i, text=f"P . {a}")
    c = col.column(align=True)
    for i, a in enumerate("XYZ"):
        c.prop(ob, "b4d_mx_scale", index=i, text=f"S % . {a}")
    c = col.column(align=True)
    for i, a in enumerate("XYZ"):
        c.prop(ob, "b4d_mx_rot", index=i, text=f"R . {a}")


def register_kind(kind, create):
    from . import kinds
    from .moclone_fx_ui import page_cloner_effectors, page_fields
    label, icon, _form, tip, _start = KINDS[kind]
    if kind == "polyfx":
        tabs = [("OBJECT", "Object"), ("EFFECTORS", "Effectors"), ("FIELDS", "Fields")]
        pages = {"OBJECT": page_polyfx, "EFFECTORS": page_cloner_effectors, "FIELDS": page_fields}
    else:
        tabs = [("OBJECT", "Object"), ("TRANSFORM", "Transform"), ("EFFECTORS", "Effectors")]
        pages = {"OBJECT": page_moextrude, "TRANSFORM": page_mx_transform, "EFFECTORS": page_cloner_effectors}
    kinds.add(kind, label, icon, create=create, tabs=tabs, pages=pages,
              titles={t: (label if t == "OBJECT" else n) for t, n in tabs},
              describe=tip + " (with an object selected, it goes under that object)")
    kinds.create_button("moclone", label, kind)
