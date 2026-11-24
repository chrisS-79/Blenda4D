# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone effectors that read another object or a file: Spline, Inheritance and Sound, plus the Group effector's
ReTime. Their settings, pages and nodes; moclone_fx.py calls in here."""
import math

import bpy

from . import gen_caps as gc
from . import moclone_fx as fx
from .moclone_fx import _attr, _clamp, _driven, _mix, _rand, _store
from .primitives import _math

GENERATORS = ("cloner", "matrix", "fracture", "voronoi", "motext", "moinstance", "tracer")

SPLINE_MODES = [("STEP", "Step", "Clones spread evenly along the spline, in their order", 0),
                ("FALLOFF", "Falloff", "Each clone's place on the spline comes from its fields' value", 1),
                ("RELATIVE", "Relative", "Clones keep their own uneven spacing, laid along the spline", 2)]
SEGMENT_MODES = [("INDEX", "Use Index", "Only the segment with the number below", 0),
                 ("EVEN", "Even Spacing", "The clones are shared out equally between the segments", 1),
                 ("RANDOM", "Random", "Each clone goes to a random segment", 2),
                 ("FULL", "Full Spacing", "One spacing over all segments: longer ones get more clones", 3)]
AXES = [("XP", "+X", "", 0), ("YP", "+Y", "", 1), ("ZP", "+Z", "", 2), ("XN", "-X", "", 3), ("YN", "-Y", "", 4), ("ZN", "-Z", "", 5)]
SPLINE_TRANSFORM = [("ABSOLUTE", "Absolute", "Clones sit on the spline", 0),
                    ("NODE", "Relative to Node", "Each clone moves along its own copy of the spline, turned with the clone", 1),
                    ("SPLINE", "Relative to Spline", "Clones move with the spline's shape without snapping onto it", 2)]
INHERIT_MODES = [("DIRECT", "Direct", "Clones take the object's state now", 0),
                 ("ANIMATION", "Animation", "The object's keyframed animation plays on the clones, one after another with Step Gap", 1)]
INHERIT_SPACE = [("GENERATOR", "Generator", "The clones turn and scale together, around the Cloner's centre", 0),
                 ("NODE", "Node", "Each clone turns and scales around its own centre", 1)]
INHERIT_ANIM = [("IN", "To (In)", "Clones start as they are and go to where the animation ends", 0),
                ("OUT", "From (Out)", "Clones start where the animation starts and come back to themselves", 1)]
SOUND_DIST = [("ITERATE", "Iterate", "The probes take turns: clone 1 the first probe, clone 2 the second...", 0),
              ("DISTRIBUTE", "Distribute", "Each probe takes a run of clones", 1),
              ("BLEND", "Blend", "The probes blend smoothly from the first clone to the last", 2)]
SAMPLING = [("PEAK", "Peak", "The loudest part of the probe, the same for its clones", 0),
            ("AVERAGE", "Average", "The probe's average loudness, the same for its clones", 1),
            ("STEP", "Step", "The probe's pitches spread over its clones: a spectrum display", 2)]
CHANNELS = [("MIX", "Mix", "Both channels together", 0), ("LEFT", "Left", "", 1), ("RIGHT", "Right", "", 2)]
PROBE_COLOR = [("DEFAULT", "Default", "A colour by loudness, from blue through green and yellow to red", 0),
               ("CUSTOM", "Custom Color", "The colour below", 1)]


def _live(self, context):
    from .moclone_fx_ui import _live as live
    live(self, context)


def _restructure(self, context):
    from .moclone_fx_ui import _restructure as rs
    rs(self, context)


class B4DSoundProbe(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Name", default="Probe")
    low_freq: bpy.props.FloatProperty(name="Low Frequency", default=20.0, min=1.0, max=24000.0, update=_restructure, description="Hz")
    high_freq: bpy.props.FloatProperty(name="High Frequency", default=2000.0, min=1.0, max=24000.0, update=_restructure, description="Hz")
    low_loud: bpy.props.FloatProperty(name="Low Loudness", default=0.0, min=0.0, max=100.0, subtype="PERCENTAGE", update=_restructure,
                                      description="Quieter than this gives nothing")
    high_loud: bpy.props.FloatProperty(name="High Loudness", default=100.0, min=0.0, max=100.0, subtype="PERCENTAGE", update=_restructure,
                                       description="This loud gives full strength")
    sampling: bpy.props.EnumProperty(name="Sampling", items=SAMPLING, default="STEP", update=_restructure)
    decay: bpy.props.FloatProperty(name="Decay", default=0.0, min=0.0, max=99.0, subtype="PERCENTAGE", update=_restructure,
                                   description="0: follows the sound at once; more: falls back slowly after a loud moment")
    strength: bpy.props.FloatProperty(name="Strength", default=100.0, soft_min=-100.0, soft_max=100.0, subtype="PERCENTAGE", update=_restructure,
                                      description="Below 0 turns the effect around")
    clamp: bpy.props.BoolProperty(name="Clamp", default=True, update=_restructure, description="Louder than High Loudness stays at full strength")
    color_mode: bpy.props.EnumProperty(name="Color", items=PROBE_COLOR, default="DEFAULT", update=_restructure)
    color: bpy.props.FloatVectorProperty(name="Custom Color", size=3, subtype="COLOR", min=0.0, max=1.0, default=(1.0, 0.5, 0.1), update=_restructure)


class BLENDA4D_UL_probes(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        r = layout.row(align=True)
        r.prop(item, "name", text="", emboss=False)
        r.label(text=f"{item.low_freq:.0f}-{item.high_freq:.0f} Hz")


class BLENDA4D_OT_probe(bpy.types.Operator):
    """Add a probe (a pitch range the clones listen to) or remove the selected one"""
    bl_idname = "blenda4d.sound_probe"
    bl_label = "Probe"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty()
    remove: bpy.props.BoolProperty()

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None:
            return {"CANCELLED"}
        if self.remove:
            if 0 <= ob.b4d_fx_probe_index < len(ob.b4d_fx_probes):
                ob.b4d_fx_probes.remove(ob.b4d_fx_probe_index)
                ob.b4d_fx_probe_index = max(0, ob.b4d_fx_probe_index - 1)
        else:
            p = ob.b4d_fx_probes.add(); p.name = f"Probe {len(ob.b4d_fx_probes)}"
            ob.b4d_fx_probe_index = len(ob.b4d_fx_probes) - 1
        _restructure(None, context)
        return {"FINISHED"}


def _freeze(self, context):
    if self.b4d_fx_snd_freeze:
        self.b4d_fx_snd_frozen = context.scene.frame_current
    _live(self, context)


def props():
    for c in classes:
        if not getattr(c, "is_registered", False):
            bpy.utils.register_class(c)
    O, P = bpy.types.Object, bpy.props
    is_curve = lambda self, o: o.type == "CURVE"
    # Spline
    O.b4d_fx_spline = P.PointerProperty(name="Spline", type=bpy.types.Object, poll=is_curve, update=_restructure,
                                        description="The spline the clones move onto")
    O.b4d_fx_rail = P.PointerProperty(name="Rail", type=bpy.types.Object, poll=is_curve, update=_restructure,
                                      description="Each clone's Y axis points at the same place on this spline (its first segment)")
    O.b4d_fx_spl_mode = P.EnumProperty(name="Mode", items=SPLINE_MODES, default="STEP", update=_live)
    O.b4d_fx_spl_falloff = P.FloatProperty(name="Falloff Modifier", default=100.0, min=1.0, subtype="PERCENTAGE", update=_live,
                                           description="How far along the spline full field strength takes a clone")
    O.b4d_fx_spl_axis = P.EnumProperty(name="Relative Offset Axis", items=AXES, default="XP", update=_live,
                                       description="The direction the clones' own spacing is measured along")
    O.b4d_fx_spl_up = P.FloatVectorProperty(name="Up Vector", size=3, default=(0.0, 0.0, 0.0), update=_live,
                                            description="A fixed up direction for the clones (0, 0, 0: the spline's own); stops flips where the spline bends the other way")
    O.b4d_fx_spl_target_rail = P.BoolProperty(name="Target Rail", default=True, update=_live,
                                              description="Off: clones only turn around their own length toward the rail")
    O.b4d_fx_spl_offset = P.FloatProperty(name="Offset", default=0.0, subtype="PERCENTAGE", update=_live, description="Slides the clones along the spline")
    O.b4d_fx_spl_start = P.FloatProperty(name="Start", default=0.0, subtype="PERCENTAGE", update=_live)
    O.b4d_fx_spl_end = P.FloatProperty(name="End", default=100.0, subtype="PERCENTAGE", update=_live)
    O.b4d_fx_spl_clamp = P.BoolProperty(name="Clamp", default=False, update=_live,
                                        description="Clones pushed past an end stay there (off: they come round from the other end)")
    O.b4d_fx_spl_seg_mode = P.EnumProperty(name="Segment Mode", items=SEGMENT_MODES, default="EVEN", update=_live)
    O.b4d_fx_spl_segment = P.IntProperty(name="Segment", default=0, min=0, update=_live)
    O.b4d_fx_spl_seed = P.IntProperty(name="Seed", default=12345, min=0, update=_live)
    O.b4d_fx_spl_transform = P.EnumProperty(name="Transform Mode", items=SPLINE_TRANSFORM, default="ABSOLUTE", update=_live)
    # Inheritance
    O.b4d_fx_inherit = P.PointerProperty(name="Object", type=bpy.types.Object, update=_restructure,
                                         description="The object (or Cloner) the clones follow")
    O.b4d_fx_inh_mode = P.EnumProperty(name="Inheritance Mode", items=INHERIT_MODES, default="DIRECT", update=_restructure)
    O.b4d_fx_inh_morph = P.BoolProperty(name="Morph Motion Object", default=True, update=_restructure,
                                        description="With a Cloner as the Object: each clone blends to that Cloner's clone with the same number")
    O.b4d_fx_inh_falloff = P.BoolProperty(name="Falloff Based", default=False, update=_live,
                                          description="The fields pick the moment of the animation: 0 its start, 1 its end")
    O.b4d_fx_inh_space = P.EnumProperty(name="Transform Space", items=INHERIT_SPACE, default="GENERATOR", update=_live)
    O.b4d_fx_inh_anim = P.EnumProperty(name="Animation", items=INHERIT_ANIM, default="IN", update=_live)
    O.b4d_fx_inh_start = P.IntProperty(name="Start", default=0, update=_live, description="The frame the animation starts playing on the clones")
    O.b4d_fx_inh_end = P.IntProperty(name="End", default=30, update=_live, description="The frame it has finished playing")
    O.b4d_fx_inh_gap = P.FloatProperty(name="Step Gap", default=0.0, update=_live, description="Each clone starts this many frames after the one before")
    O.b4d_fx_inh_loop = P.BoolProperty(name="Loop Animation", default=False, update=_live)
    # Sound
    O.b4d_fx_sound = P.StringProperty(name="Sound Track", subtype="FILE_PATH", update=_restructure, description="The sound file the clones listen to")
    O.b4d_fx_snd_dist = P.EnumProperty(name="Distribution", items=SOUND_DIST, default="ITERATE", update=_live)
    O.b4d_fx_snd_channels = P.EnumProperty(name="Channels", items=CHANNELS, default="MIX", update=_restructure)
    O.b4d_fx_snd_freeze = P.BoolProperty(name="Freeze Value", default=False, update=_freeze, description="Hold the value of the frame it was switched on")
    O.b4d_fx_snd_frozen = P.IntProperty(default=1, update=_live)
    O.b4d_fx_probes = P.CollectionProperty(type=B4DSoundProbe)
    O.b4d_fx_probe_index = P.IntProperty()


# --- pages -----------------------------------------------------------------------------------------------------------

def page(c, ob):
    k = ob.get("b4d_type")
    if k == "fx_spline":
        c.separator()
        c.prop(ob, "b4d_fx_spl_mode")
        if ob.b4d_fx_spl_mode == "FALLOFF":
            c.prop(ob, "b4d_fx_spl_falloff")
        elif ob.b4d_fx_spl_mode == "RELATIVE":
            c.prop(ob, "b4d_fx_spl_axis")
        c.prop(ob, "b4d_fx_spline")
        r = c.column(align=True)
        for i, a in enumerate("XYZ"):
            r.prop(ob, "b4d_fx_spl_up", index=i, text=f"Up Vector . {a}")
        c.prop(ob, "b4d_fx_rail")
        sub = c.row(); sub.active = ob.b4d_fx_rail is not None; sub.prop(ob, "b4d_fx_spl_target_rail")
        c.prop(ob, "b4d_fx_spl_offset"); c.prop(ob, "b4d_fx_spl_start"); c.prop(ob, "b4d_fx_spl_end"); c.prop(ob, "b4d_fx_spl_clamp")
        c.prop(ob, "b4d_fx_spl_seg_mode")
        if ob.b4d_fx_spl_seg_mode == "INDEX":
            c.prop(ob, "b4d_fx_spl_segment")
        elif ob.b4d_fx_spl_seg_mode == "RANDOM":
            c.prop(ob, "b4d_fx_spl_seed")
    elif k == "fx_inherit":
        c.separator()
        c.prop(ob, "b4d_fx_inh_mode"); c.prop(ob, "b4d_fx_inherit")
        src = ob.b4d_fx_inherit
        if ob.b4d_fx_inh_mode == "DIRECT":
            sub = c.row(); sub.active = src is not None and src.get("b4d_type") in GENERATORS
            sub.prop(ob, "b4d_fx_inh_morph")
        else:
            c.prop(ob, "b4d_fx_inh_falloff"); c.prop(ob, "b4d_fx_inh_space"); c.prop(ob, "b4d_fx_inh_anim")
            r = c.column(align=True); r.prop(ob, "b4d_fx_inh_start"); r.prop(ob, "b4d_fx_inh_end")
            c.prop(ob, "b4d_fx_inh_gap"); c.prop(ob, "b4d_fx_inh_loop")
            if src is not None and not _has_keys(src):
                c.label(text="The Object has no keyframes on its position, rotation or scale", icon="INFO")
    elif k == "fx_sound":
        c.separator()
        c.prop(ob, "b4d_fx_sound")
        from . import moclone_bake
        err = moclone_bake.sound_error(ob)
        if err:
            c.label(text=err, icon="ERROR")
        c.prop(ob, "b4d_fx_snd_dist"); c.prop(ob, "b4d_fx_snd_channels"); c.prop(ob, "b4d_fx_snd_freeze")
        c.separator(); c.label(text="Probes")
        r = c.row()
        r.template_list("BLENDA4D_UL_probes", "", ob, "b4d_fx_probes", ob, "b4d_fx_probe_index", rows=3)
        side = r.column(align=True)
        a = side.operator("blenda4d.sound_probe", text="", icon="ADD"); a.owner, a.remove = ob.name, False
        d = side.operator("blenda4d.sound_probe", text="", icon="REMOVE"); d.owner, d.remove = ob.name, True
        if 0 <= ob.b4d_fx_probe_index < len(ob.b4d_fx_probes):
            p = ob.b4d_fx_probes[ob.b4d_fx_probe_index]
            col = c.column(align=True); col.prop(p, "low_freq"); col.prop(p, "high_freq")
            col = c.column(align=True); col.prop(p, "low_loud"); col.prop(p, "high_loud")
            c.prop(p, "sampling"); c.prop(p, "decay"); c.prop(p, "strength"); c.prop(p, "clamp"); c.prop(p, "color_mode")
            if p.color_mode == "CUSTOM":
                c.prop(p, "color")


def page_parameter(col, ob):
    """The Spline effector's Parameter tab: how the clones are moved and turned."""
    c = col.column()
    c.prop(ob, "b4d_fx_spl_transform")
    c.prop(ob, "b4d_fx_pos_on")
    c.prop(ob, "b4d_fx_rot_on")
    sub = c.column(align=True); sub.active = ob.b4d_fx_rot_on
    for i, a in enumerate("XYZ"):
        sub.prop(ob, "b4d_fx_rot", index=i, text=f"R . {a}")


def _has_keys(src):
    from . import moclone_bake
    return bool(moclone_bake.motion_curves(src))


# --- Spline ----------------------------------------------------------------------------------------------------------

def _curve(nodes, links, ob):
    info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"
    info.inputs["Object"].default_value = ob
    real = nodes.new("GeometryNodeRealizeInstances"); links.new(info.outputs["Geometry"], real.inputs["Geometry"])
    return real.outputs["Geometry"]


def _sample(nodes, links, curve, factor, index=None):
    """Position, tangent, normal at factor along all segments (index None) or along one segment."""
    s = nodes.new("GeometryNodeSampleCurve"); s.mode = "FACTOR"; s.use_all_curves = index is None
    links.new(curve, s.inputs["Curves"]); links.new(factor, s.inputs["Factor"])
    if index is not None:
        links.new(index, s.inputs["Curve Index"])
    return s.outputs["Position"], s.outputs["Tangent"], s.outputs["Normal"]


def _frame(nodes, links, tangent, up):
    """A rotation whose X runs along the spline and whose Z (shown Y) leans toward up."""
    a = nodes.new("FunctionNodeAlignRotationToVector"); a.axis = "X"; a.pivot_axis = "AUTO"
    links.new(tangent, a.inputs["Vector"])
    b = nodes.new("FunctionNodeAlignRotationToVector"); b.axis = "Z"; b.pivot_axis = "X"
    links.new(a.outputs[0], b.inputs["Rotation"]); links.new(up, b.inputs["Vector"])
    return b.outputs[0]


def spline(nodes, links, geo, gen, i, e, w):
    sp = e.b4d_fx_spline
    if sp is None:
        return geo
    curve = _curve(nodes, links, sp)
    idx = _attr(nodes, "b4d_index", "INT")
    cnt = fx._count(nodes, links, geo)
    nseg = nodes.new("GeometryNodeAttributeDomainSize"); nseg.component = "CURVE"; links.new(curve, nseg.inputs["Geometry"])
    nseg = _math(nodes, "MAXIMUM", nseg.outputs["Spline Count"], 1.0, links)
    seg_mode = _driven(nodes, e, "b4d_fx_spl_seg_mode")
    # which segment, and the clone's number and count within it
    per = _math(nodes, "CEIL", _math(nodes, "DIVIDE", cnt, nseg, links), None, links)
    even_seg = _math(nodes, "FLOOR", _math(nodes, "DIVIDE", idx, per, links), None, links)
    rnd_seg = _rand(nodes, links, 0, 1, idx, _driven(nodes, e, "b4d_fx_spl_seed"))
    rnd_seg = _math(nodes, "FLOOR", _math(nodes, "MULTIPLY", rnd_seg, _math(nodes, "SUBTRACT", nseg, 1e-3, links), links), None, links)
    seg = gc.index_switch(nodes, links, "INT", seg_mode, [_math(nodes, "MINIMUM", _driven(nodes, e, "b4d_fx_spl_segment"), _math(nodes, "SUBTRACT", nseg, 1.0, links), links),
                                                          even_seg, rnd_seg, 0])
    local = gc.switch(nodes, links, "FLOAT", _math(nodes, "COMPARE", seg_mode, 1.0, links), idx, _math(nodes, "SUBTRACT", idx, _math(nodes, "MULTIPLY", even_seg, per, links), links))
    n_in = gc.switch(nodes, links, "FLOAT", _math(nodes, "COMPARE", seg_mode, 1.0, links), cnt, per)
    step = _math(nodes, "DIVIDE", local, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", n_in, 1.0, links), 1.0, links), links)
    # Falloff: the fields' value; Relative: the clone's place along an axis of the arrangement
    fall = fx.falloff(nodes, links, e)
    fv = _math(nodes, "MULTIPLY", 1.0 if fall is None else fall, _driven(nodes, e, "b4d_fx_spl_falloff", "var*0.01"), links)
    ax = _driven(nodes, e, "b4d_fx_spl_axis")
    p = gc.separate(nodes, links, gc.position(nodes))
    coord = gc.index_switch(nodes, links, "FLOAT", _math(nodes, "FLOORED_MODULO", ax, 3.0, links), [p["X"], p["Z"], p["Y"]])   # shown X, Y, Z
    stat = nodes.new("GeometryNodeAttributeStatistic"); stat.domain = "POINT"; links.new(geo, stat.inputs["Geometry"]); links.new(coord, stat.inputs["Attribute"])
    rel = _math(nodes, "DIVIDE", _math(nodes, "SUBTRACT", coord, stat.outputs["Min"], links), _math(nodes, "MAXIMUM", stat.outputs["Range"], 1e-6, links), links)
    rel = gc.switch(nodes, links, "FLOAT", _math(nodes, "GREATER_THAN", ax, 2.5, links), rel, _math(nodes, "SUBTRACT", 1.0, rel, links))
    f = gc.index_switch(nodes, links, "FLOAT", _driven(nodes, e, "b4d_fx_spl_mode"), [step, fv, rel])
    start, end = _driven(nodes, e, "b4d_fx_spl_start", "var*0.01"), _driven(nodes, e, "b4d_fx_spl_end", "var*0.01")
    f0 = _math(nodes, "ADD", start, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", end, start, links), f, links), links)
    g = _math(nodes, "ADD", f0, _driven(nodes, e, "b4d_fx_spl_offset", "var*0.01"), links)
    clamped = _clamp(nodes, links, g)
    outside = _math(nodes, "GREATER_THAN", _math(nodes, "ADD", _math(nodes, "LESS_THAN", g, 0.0, links), _math(nodes, "GREATER_THAN", g, 1.0, links), links), 0.5, links)
    wrapped = gc.switch(nodes, links, "FLOAT", outside, g, _math(nodes, "FLOORED_MODULO", g, 1.0, links))
    g = gc.switch(nodes, links, "FLOAT", _driven(nodes, e, "b4d_fx_spl_clamp"), wrapped, clamped)
    full = _math(nodes, "COMPARE", seg_mode, 3.0, links)
    pa, ta, na = _sample(nodes, links, curve, g)
    pi_, ti, ni = _sample(nodes, links, curve, g, seg)
    pos_s = gc.switch(nodes, links, "VECTOR", full, pi_, pa)
    tan = gc.switch(nodes, links, "VECTOR", full, ti, ta)
    nor = gc.switch(nodes, links, "VECTOR", full, ni, na)
    p0a, t0a, _n = _sample(nodes, links, curve, f0)
    p0i, t0i, _n = _sample(nodes, links, curve, f0, seg)
    pos0 = gc.switch(nodes, links, "VECTOR", full, p0i, p0a)
    # up: the Up Vector, else the rail, else the spline's own normal
    upv = fx._vec(nodes, links, e, "b4d_fx_spl_up")
    has_up = _math(nodes, "GREATER_THAN", fx._vlen(nodes, links, upv), 1e-6, links)
    up = gc.switch(nodes, links, "VECTOR", has_up, nor, upv)
    if e.b4d_fx_rail is not None:
        rail = _curve(nodes, links, e.b4d_fx_rail)
        rp, _t, _n = _sample(nodes, links, rail, g, nodes.new("FunctionNodeInputInt").outputs[0])
        up = gc.vmath(nodes, links, "SUBTRACT", rp, pos_s)
    aligned = _frame(nodes, links, tan, up)
    if e.b4d_fx_rail is not None:
        loose = _frame(nodes, links, tan, gc.switch(nodes, links, "VECTOR", has_up, nor, upv))
        aligned = gc.switch(nodes, links, "ROTATION", _driven(nodes, e, "b4d_fx_spl_target_rail"), loose, aligned)
    ww = _clamp(nodes, links, w)
    mode = _driven(nodes, e, "b4d_fx_spl_transform")
    delta = gc.vmath(nodes, links, "SUBTRACT", pos_s, pos0)
    # Relative to Node: the spline's change, seen from its start, turned with each clone (its start pointing along Z)
    frame0 = _frame(nodes, links, gc.switch(nodes, links, "VECTOR", full, t0i, t0a), up)
    inv = nodes.new("FunctionNodeInvertRotation"); links.new(frame0, inv.inputs[0])
    loc = nodes.new("FunctionNodeRotateVector"); links.new(delta, loc.inputs["Vector"]); links.new(inv.outputs[0], loc.inputs["Rotation"])
    swap = gc.separate(nodes, links, loc.outputs[0])
    along_z = gc.combine(nodes, links, swap["Z"], swap["Y"], swap["X"])         # the start's run (X) laid along the clone's Z
    mine = nodes.new("FunctionNodeRotateVector"); links.new(along_z, mine.inputs["Vector"]); links.new(_attr(nodes, "b4d_rot_q", "QUATERNION"), mine.inputs["Rotation"])
    target = gc.index_switch(nodes, links, "VECTOR", mode, [pos_s, gc.vmath(nodes, links, "ADD", gc.position(nodes), mine.outputs[0]),
                                                           gc.vmath(nodes, links, "ADD", gc.position(nodes), delta)])
    move = _math(nodes, "MULTIPLY", ww, _driven(nodes, e, "b4d_fx_pos_on"), links)
    newp = _mix(nodes, links, "VECTOR", move, gc.position(nodes), target)
    st = nodes.new("GeometryNodeSetPosition"); links.new(geo, st.inputs["Geometry"]); links.new(newp, st.inputs["Position"])
    geo = st.outputs["Geometry"]
    extra = fx._euler(nodes, links, fx._vec(nodes, links, e, "b4d_fx_rot", f"var*{math.pi / 180.0!r}"))
    rr = nodes.new("FunctionNodeRotateRotation"); rr.rotation_space = "LOCAL"
    links.new(aligned, rr.inputs["Rotation"]); links.new(extra, rr.inputs["Rotate By"])
    turn = _math(nodes, "MULTIPLY", ww, _driven(nodes, e, "b4d_fx_rot_on"), links)
    q = _attr(nodes, "b4d_rot_q", "QUATERNION")
    geo = _store(nodes, links, geo, "b4d_rot_q", "QUATERNION", _mix(nodes, links, "ROTATION", _clamp(nodes, links, turn), q, rr.outputs[0]))
    geo = fx._apply_color(nodes, links, geo, e, w)
    return fx._apply_visibility(nodes, links, geo, e, w)


# --- Inheritance -----------------------------------------------------------------------------------------------------

def _mat(nodes, links, loc, rot, scale):
    c = nodes.new("FunctionNodeCombineTransform")
    links.new(loc, c.inputs["Translation"]); links.new(rot, c.inputs["Rotation"]); links.new(scale, c.inputs["Scale"])
    return c.outputs[0]


def _apply_delta(nodes, links, geo, e, w, d_loc, d_rot, d_scale, generator_space):
    """Move each clone by a change of place, rotation and scale, as strongly as w and the Parameter tab's switches say.
    generator_space: turns and scales swing the clones around the Cloner's centre; else around their own."""
    ww = _clamp(nodes, links, w, -10.0, 10.0)
    on = lambda name: _math(nodes, "MULTIPLY", ww, _driven(nodes, e, name), links)
    q = _attr(nodes, "b4d_rot_q", "QUATERNION")
    rpos = nodes.new("FunctionNodeRotateVector"); links.new(gc.vmath(nodes, links, "MULTIPLY", gc.position(nodes), d_scale), rpos.inputs["Vector"])
    links.new(d_rot, rpos.inputs["Rotation"])
    swung = gc.vmath(nodes, links, "ADD", rpos.outputs[0], d_loc)
    shifted = gc.vmath(nodes, links, "ADD", gc.position(nodes), d_loc)
    swing = _math(nodes, "MULTIPLY", generator_space, _driven(nodes, e, "b4d_fx_rot_on"), links)
    target = gc.switch(nodes, links, "VECTOR", swing, shifted, swung)
    newp = _mix(nodes, links, "VECTOR", on("b4d_fx_pos_on"), gc.position(nodes), target)
    sp = nodes.new("GeometryNodeSetPosition"); links.new(geo, sp.inputs["Geometry"]); links.new(newp, sp.inputs["Position"])
    geo = sp.outputs["Geometry"]
    rr = nodes.new("FunctionNodeRotateRotation"); rr.rotation_space = "GLOBAL"
    links.new(q, rr.inputs["Rotation"]); links.new(d_rot, rr.inputs["Rotate By"])
    geo = _store(nodes, links, geo, "b4d_rot_q", "QUATERNION", _mix(nodes, links, "ROTATION", _clamp(nodes, links, on("b4d_fx_rot_on")), q, rr.outputs[0]))
    sc = _attr(nodes, "b4d_scale", "FLOAT_VECTOR")
    geo = _store(nodes, links, geo, "b4d_scale", "FLOAT_VECTOR", _mix(nodes, links, "VECTOR", on("b4d_fx_scale_on"), sc, gc.vmath(nodes, links, "MULTIPLY", sc, d_scale)))
    return geo


def inherit(nodes, links, geo, gen, i, e, w):
    src = e.b4d_fx_inherit
    if src is None or src == gen:
        return geo
    if e.b4d_fx_inh_mode == "DIRECT":
        if src.get("b4d_type") in GENERATORS and e.b4d_fx_inh_morph:
            # each clone blends to the source Cloner's clone with its number
            info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"; info.inputs["Object"].default_value = src
            idx = _attr(nodes, "b4d_index", "INT")
            cnt = nodes.new("GeometryNodeAttributeDomainSize"); cnt.component = "INSTANCES"; links.new(info.outputs["Geometry"], cnt.inputs["Geometry"])
            j = _math(nodes, "FLOORED_MODULO", idx, _math(nodes, "MAXIMUM", cnt.outputs["Instance Count"], 1.0, links), links)

            def theirs(field, typ):
                s = nodes.new("GeometryNodeSampleIndex"); s.data_type = typ; s.domain = "INSTANCE"
                links.new(info.outputs["Geometry"], s.inputs["Geometry"]); links.new(field, s.inputs["Value"]); links.new(j, s.inputs["Index"])
                return s.outputs[0]

            has = _math(nodes, "GREATER_THAN", cnt.outputs["Instance Count"], 0.0, links)
            ww = _math(nodes, "MULTIPLY", _clamp(nodes, links, w), has, links)
            on = lambda name: _math(nodes, "MULTIPLY", ww, _driven(nodes, e, name), links)
            sp = nodes.new("GeometryNodeSetPosition"); links.new(geo, sp.inputs["Geometry"])
            links.new(_mix(nodes, links, "VECTOR", on("b4d_fx_pos_on"), gc.position(nodes), theirs(gc.position(nodes), "FLOAT_VECTOR")), sp.inputs["Position"])
            geo = sp.outputs["Geometry"]
            q = _attr(nodes, "b4d_rot_q", "QUATERNION")
            geo = _store(nodes, links, geo, "b4d_rot_q", "QUATERNION",
                         _mix(nodes, links, "ROTATION", on("b4d_fx_rot_on"), q, theirs(nodes.new("GeometryNodeInputInstanceRotation").outputs[0], "QUATERNION")))
            sc = _attr(nodes, "b4d_scale", "FLOAT_VECTOR")
            geo = _store(nodes, links, geo, "b4d_scale", "FLOAT_VECTOR",
                         _mix(nodes, links, "VECTOR", on("b4d_fx_scale_on"), sc, theirs(nodes.new("GeometryNodeInputInstanceScale").outputs[0], "FLOAT_VECTOR")))
            geo = fx._apply_color(nodes, links, geo, e, ww, theirs(_attr(nodes, "b4d_color", "FLOAT_COLOR"), "FLOAT_COLOR"))
            return fx._apply_visibility(nodes, links, geo, e, w)
        # an ordinary object: the clones move with it as if fixed to it (its change since the Cloner's own place)
        info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"; info.inputs["Object"].default_value = src
        geo = _apply_delta(nodes, links, geo, e, w, info.outputs["Location"], info.outputs["Rotation"], info.outputs["Scale"],
                           _math(nodes, "ADD", 1.0, 0.0, links))
        return fx._apply_visibility(nodes, links, geo, e, w)
    # Animation: the object's keyframes, kept in a small image, played on each clone
    from . import moclone_bake
    img, a0, a1 = moclone_bake.motion_image(e)
    if img is None:
        return geo
    span = max(a1 - a0, 1)
    frame = nodes.new("GeometryNodeInputSceneTime").outputs["Frame"]
    idx = _attr(nodes, "b4d_index", "INT")
    start = _driven(nodes, e, "b4d_fx_inh_start"); end = _driven(nodes, e, "b4d_fx_inh_end")
    local = _math(nodes, "SUBTRACT", _math(nodes, "SUBTRACT", frame, start, links), _math(nodes, "MULTIPLY", idx, _driven(nodes, e, "b4d_fx_inh_gap"), links), links)
    prog = _math(nodes, "DIVIDE", local, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", end, start, links), 1e-3, links), links)
    looped = _math(nodes, "FLOORED_MODULO", prog, 1.0, links)
    prog = gc.switch(nodes, links, "FLOAT", _driven(nodes, e, "b4d_fx_inh_loop"), _clamp(nodes, links, prog), looped)
    fall = fx.falloff(nodes, links, e)
    if fall is not None:
        prog = gc.switch(nodes, links, "FLOAT", _driven(nodes, e, "b4d_fx_inh_falloff"), prog, _clamp(nodes, links, fall))
        w = gc.switch(nodes, links, "FLOAT", _driven(nodes, e, "b4d_fx_inh_falloff"), w,
                      _math(nodes, "MULTIPLY", _driven(nodes, e, "b4d_fx_strength", "var*0.01"), 1.0, links))

    def at(p):
        """The object's place, rotation and scale at progress p (0..1 of its keyframed range)."""
        u = _math(nodes, "DIVIDE", _math(nodes, "ADD", _math(nodes, "MULTIPLY", p, float(span), links), 0.5, links), float(span + 1), links)
        out = []
        for row in range(3):
            t = nodes.new("GeometryNodeImageTexture"); t.interpolation = "Linear"; t.extension = "EXTEND"
            t.inputs["Image"].default_value = img
            links.new(gc.combine(nodes, links, u, (row + 0.5) / 3.0, 0.0), t.inputs["Vector"])
            out.append(t.outputs["Color"])
        return out[0], fx._euler(nodes, links, out[1]), out[2]

    def matrix(p):
        loc, rot, sc = at(p)
        return _mat(nodes, links, loc, rot, sc)

    mid = matrix(prog)
    first, last = matrix(0.0), matrix(1.0)
    ref = gc.switch(nodes, links, "MATRIX", _driven(nodes, e, "b4d_fx_inh_anim"), first, last)
    inv = nodes.new("FunctionNodeInvertMatrix"); links.new(ref, inv.inputs[0])
    mm = nodes.new("FunctionNodeMatrixMultiply"); links.new(mid, mm.inputs[0]); links.new(inv.outputs[0], mm.inputs[1])
    sep = nodes.new("FunctionNodeSeparateTransform"); links.new(mm.outputs[0], sep.inputs[0])
    gen_space = _math(nodes, "COMPARE", _driven(nodes, e, "b4d_fx_inh_space"), 0.0, links)
    geo = _apply_delta(nodes, links, geo, e, w, sep.outputs["Translation"], sep.outputs["Rotation"], sep.outputs["Scale"], gen_space)
    return fx._apply_visibility(nodes, links, geo, e, w)


# --- Sound -----------------------------------------------------------------------------------------------------------

def sound(nodes, links, geo, gen, i, e, w):
    from . import moclone_bake
    img, n_probes, cols, frames, first = moclone_bake.sound_image(e)
    if img is None:
        return geo
    idx = _attr(nodes, "b4d_index", "INT")
    cnt = fx._count(nodes, links, geo)
    P = float(n_probes)
    dist = _driven(nodes, e, "b4d_fx_snd_dist")
    frame = gc.switch(nodes, links, "FLOAT", _driven(nodes, e, "b4d_fx_snd_freeze"), nodes.new("GeometryNodeInputSceneTime").outputs["Frame"],
                      _driven(nodes, e, "b4d_fx_snd_frozen"))
    u = _math(nodes, "DIVIDE", _math(nodes, "ADD", _math(nodes, "SUBTRACT", frame, float(first), links), 0.5, links), float(frames), links)
    rows = n_probes * cols + n_probes

    def read(row):
        t = nodes.new("GeometryNodeImageTexture"); t.interpolation = "Linear"; t.extension = "EXTEND"
        t.inputs["Image"].default_value = img
        links.new(gc.combine(nodes, links, u, _math(nodes, "DIVIDE", _math(nodes, "ADD", row, 0.5, links), float(rows), links), 0.0), t.inputs["Vector"])
        return t.outputs["Color"]

    # which probe each clone listens to, and its place among that probe's clones (for Step)
    it_p = _math(nodes, "FLOORED_MODULO", idx, P, links)
    it_n = _math(nodes, "CEIL", _math(nodes, "DIVIDE", cnt, P, links), None, links)
    it_f = _math(nodes, "DIVIDE", _math(nodes, "FLOOR", _math(nodes, "DIVIDE", idx, P, links), None, links), _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", it_n, 1.0, links), 1.0, links), links)
    x = _math(nodes, "DIVIDE", _math(nodes, "MULTIPLY", idx, P, links), _math(nodes, "MAXIMUM", cnt, 1.0, links), links)
    ds_p = _math(nodes, "MINIMUM", _math(nodes, "FLOOR", x, None, links), P - 1.0, links)
    ds_n = _math(nodes, "DIVIDE", cnt, P, links)
    ds_f = _clamp(nodes, links, _math(nodes, "DIVIDE", _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", x, ds_p, links), ds_n, links),
                                      _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", ds_n, 1.0, links), 1.0, links), links))
    bl = _math(nodes, "MULTIPLY", _math(nodes, "DIVIDE", idx, _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", cnt, 1.0, links), 1.0, links), links), P - 1.0, links)
    bl_p = _math(nodes, "FLOOR", bl, None, links)
    bl_t = _math(nodes, "SUBTRACT", bl, bl_p, links)
    u_all = _attr(nodes, "b4d_u", "FLOAT")
    probe = gc.index_switch(nodes, links, "FLOAT", dist, [it_p, ds_p, bl_p])
    frac = gc.index_switch(nodes, links, "FLOAT", dist, [it_f, ds_f, u_all])
    col = _math(nodes, "ROUND", _math(nodes, "MULTIPLY", frac, float(cols - 1), links), None, links)

    def value(p):
        c = gc.separate(nodes, links, read(_math(nodes, "ADD", _math(nodes, "MULTIPLY", p, float(cols), links), col, links)))
        return c["X"]

    v0 = value(probe)
    v1 = value(_math(nodes, "MINIMUM", _math(nodes, "ADD", probe, 1.0, links), P - 1.0, links))
    v = gc.switch(nodes, links, "FLOAT", _math(nodes, "COMPARE", dist, 2.0, links), v0, _math(nodes, "ADD", v0, _math(nodes, "MULTIPLY", bl_t, _math(nodes, "SUBTRACT", v1, v0, links), links), links))
    # colour: the probe's own colour, or blue to red by loudness
    pc = read(_math(nodes, "ADD", float(n_probes * cols), probe, links))
    sep = nodes.new("FunctionNodeSeparateColor"); links.new(pc, sep.inputs[0])
    ramp = nodes.new("ShaderNodeValToRGB"); cr = ramp.color_ramp
    cr.elements[0].color = (0.05, 0.2, 1.0, 1.0); cr.elements[1].color = (1.0, 0.1, 0.05, 1.0)
    for pos, c in ((0.33, (0.1, 0.9, 0.3, 1.0)), (0.66, (1.0, 0.9, 0.1, 1.0))):
        el = cr.elements.new(pos); el.color = c
    links.new(_clamp(nodes, links, v), ramp.inputs["Fac"])
    own = gc.switch(nodes, links, "RGBA", _math(nodes, "GREATER_THAN", sep.outputs["Alpha"], 0.5, links), ramp.outputs["Color"], pc)
    own = gc.switch(nodes, links, "RGBA", _math(nodes, "GREATER_THAN", _driven(nodes, e, "b4d_fx_color_mode"), 1.5, links), own, fx._color(nodes, links, e, "b4d_fx_color"))
    pos, sc, rot = fx._params(nodes, links, e)
    wv = _math(nodes, "MULTIPLY", w, v, links)
    geo = fx._apply_transform(nodes, links, geo, wv, pos, sc, rot)
    geo = fx._apply_color(nodes, links, geo, e, _clamp(nodes, links, wv), own)
    return fx._apply_visibility(nodes, links, geo, e, w)


# --- Group: ReTime ---------------------------------------------------------------------------------------------------

RETIME_TRACK = "Blenda ReTime"


def retime(group):
    """ReTime on: each effector in the Group's list plays its keyframed action as an NLA strip squeezed into Start..End.
    Off: the actions go back as they were."""
    for entry in group.b4d_fx_list:
        c = entry.obj
        if c is None or c == group:
            continue
        ad = c.animation_data
        if ad is None:
            continue
        old = ad.nla_tracks.get(RETIME_TRACK)
        if old is not None:                                        # undo an earlier ReTime first
            act = old.strips[0].action if len(old.strips) else None
            ad.nla_tracks.remove(old)
            if act is not None and ad.action is None:
                ad.action = act
        if not group.b4d_fx_retime or ad.action is None:
            continue
        act = ad.action
        a0, a1 = act.frame_range
        tr = ad.nla_tracks.new(); tr.name = RETIME_TRACK
        st = tr.strips.new(act.name, int(group.b4d_fx_retime_start), act)
        span = max(group.b4d_fx_retime_end - group.b4d_fx_retime_start, 1)
        st.scale = span / max(a1 - a0, 1e-3)
        ad.action = None
    _restructure(group, bpy.context)


classes = (B4DSoundProbe, BLENDA4D_UL_probes, BLENDA4D_OT_probe)
