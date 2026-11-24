# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone effectors and fields: their settings, creating them, the Effectors and Fields lists, their Attributes pages
and the field shapes drawn in the viewport. The nodes they make are in moclone_fx.py."""
import math

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from . import kinds
from . import moclone_fx as fx

from .moclone_gens import FX_GENS as MOGENS      # generators with an Effectors list


def _cloners():
    return [o for o in bpy.data.objects if o.get("b4d_type") in MOGENS]


def _live(self, context):
    """A changed value reaches the clones now (the drivers read it on the next update)."""
    for g in _cloners():
        g.update_tag()


def _restructure(self, context):
    """A changed list or linked object changes the Cloner's nodes: the generators' sync rebuilds them."""
    for g in _cloners():
        g["b4d_fx_sig"] = []
    from . import generators
    generators.sync_all()


class B4DFxEntry(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object, update=_restructure, poll=lambda self, o: fx.is_effector(o))
    on: bpy.props.BoolProperty(name="On", default=True, update=_live, description="Use this effector")
    strength: bpy.props.FloatProperty(name="Strength", default=100.0, min=-1000.0, max=1000.0, soft_min=0.0, soft_max=100.0,
                                      subtype="PERCENTAGE", update=_live, description="How strongly this effector works on this Cloner")


class B4DFieldEntry(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object, update=_restructure, poll=lambda self, o: fx.is_field(o))
    on: bpy.props.BoolProperty(name="On", default=True, update=_live, description="Use this field")
    opacity: bpy.props.FloatProperty(name="Opacity", default=100.0, min=0.0, max=100.0, subtype="PERCENTAGE", update=_live,
                                     description="How much this field counts")


def _props():
    O, P = bpy.types.Object, bpy.props
    O.b4d_fx_list = P.CollectionProperty(type=B4DFxEntry)
    O.b4d_fx_index = P.IntProperty()
    O.b4d_field_list = P.CollectionProperty(type=B4DFieldEntry)
    for lst in ("b4d_fx_list_all", "b4d_fx_list_lines", "b4d_fx_list_words"):     # MoText's All, Lines and Words
        setattr(O, lst, P.CollectionProperty(type=B4DFxEntry))
    O.b4d_field_index = P.IntProperty()
    pct = dict(subtype="PERCENTAGE", update=_live)
    O.b4d_fx_strength = P.FloatProperty(name="Strength", default=100.0, soft_min=0.0, soft_max=100.0, min=-1000.0, max=1000.0,
                                        description="How strongly the effector works", **pct)
    O.b4d_fx_min = P.FloatProperty(name="Minimum", default=0.0, min=-1000.0, max=1000.0, description="The effect where the fields give nothing", **pct)
    O.b4d_fx_max = P.FloatProperty(name="Maximum", default=100.0, min=-1000.0, max=1000.0, description="The effect where the fields give full strength", **pct)
    O.b4d_fx_pos_on = P.BoolProperty(name="Position", default=True, update=_live, description="Move the clones")
    O.b4d_fx_pos = P.FloatVectorProperty(name="P", size=3, default=(0.0, 50.0, 0.0), update=_live, description="How far to move them (cm)")
    O.b4d_fx_scale_on = P.BoolProperty(name="Scale", default=False, update=_live, description="Scale the clones")
    O.b4d_fx_scale = P.FloatVectorProperty(name="S", size=3, default=(100.0, 100.0, 100.0), soft_min=0.0, soft_max=200.0, update=_live,
                                           description="The clones' size in %: 100 is their own size, 0 makes them vanish, 200 doubles them")
    O.b4d_fx_uniform = P.BoolProperty(name="Uniform Scale", default=False, update=_live, description="One scale for all three axes")
    O.b4d_fx_uscale = P.FloatProperty(name="Scale", default=100.0, soft_min=0.0, soft_max=200.0, update=_live,
                                      description="The clones' size on all axes in %: 100 is their own size, 0 makes them vanish, 200 doubles them")
    O.b4d_fx_rot_on = P.BoolProperty(name="Rotation", default=False, update=_live, description="Turn the clones")
    O.b4d_fx_rot = P.FloatVectorProperty(name="R", size=3, default=(0.0, 0.0, 0.0), update=_live, description="How far to turn them (degrees)")
    O.b4d_fx_color_mode = P.EnumProperty(name="Color Mode", items=fx.COLOR_MODES, default="OFF", update=_live, description="How the effector colours the clones")
    O.b4d_fx_color = P.FloatVectorProperty(name="Color", size=3, subtype="COLOR", min=0.0, max=1.0, default=(1.0, 1.0, 1.0), update=_live)
    O.b4d_fx_use_sel = P.BoolProperty(name="Selection", default=False, update=_restructure,
                                      description="Work only on the clones in the Cloner's MoClone Selection tag")
    O.b4d_fx_visibility = P.BoolProperty(name="Visibility", default=False, update=_live, description="Hide the clones where the effector works under half strength")
    O.b4d_fx_random_mode = P.EnumProperty(name="Random Mode", items=fx.RANDOM_MODES, default="RANDOM", update=_live)
    O.b4d_fx_seed = P.IntProperty(name="Seed", default=12345, min=0, update=_live, description="Another seed gives other random values")
    O.b4d_fx_noise_scale = P.FloatProperty(name="Noise Scale", default=100.0, min=0.001, **pct, description="The size of the noise pattern")
    O.b4d_fx_speed = P.FloatProperty(name="Animation Speed", default=1.0, min=0.0, update=_live, description="How fast the noise moves")
    O.b4d_fx_shader_source = P.EnumProperty(name="Shader", items=fx.SHADER_SOURCES, default="NOISE", update=_live)
    O.b4d_fx_image = P.PointerProperty(name="Image", type=bpy.types.Image, update=_restructure, description="The image the clones read, by their U and V")
    O.b4d_fx_target_mode = P.EnumProperty(name="Target Mode", items=fx.TARGET_MODES, default="OBJECT", update=_live)
    O.b4d_fx_target = P.PointerProperty(name="Target Object", type=bpy.types.Object, update=_restructure, description="The object the clones face")
    O.b4d_fx_delay_mode = P.EnumProperty(name="Mode", items=fx.DELAY_MODES, default="BLEND", update=_live)
    O.b4d_fx_formula = P.StringProperty(name="Formula", default="sin((id/count+t)*360)", update=_restructure,
                                        description="The value that scales the Parameter tab's change; sin, cos and tan work in degrees")
    O.b4d_fx_freq = P.FloatProperty(name="f - Frequency", default=1.0, update=_live, description="The value of f in the formula")
    O.b4d_fx_tscale = P.FloatProperty(name="t - Project Time", default=1.0, update=_live,
                                      description="t in the formula is the time in seconds times this: more plays faster")
    O.b4d_fx_push_mode = P.EnumProperty(name="Mode", items=fx.PUSH_MODES, default="PUSH", update=_live)
    O.b4d_fx_radius = P.FloatProperty(name="Radius", default=50.0, min=0.0, update=_live,
                                      description="Each clone's room (cm): clones closer than twice this overlap")
    O.b4d_fx_iterations = P.IntProperty(name="Iterations", default=10, min=0, max=200, update=_live,
                                        description="How many times to check again: more gives fewer overlaps and takes longer")
    O.b4d_fx_volume = P.PointerProperty(name="Volume Object", type=bpy.types.Object, update=_restructure,
                                        poll=lambda self, o: o.type in ("MESH", "CURVE", "SURFACE", "META", "FONT"),
                                        description="Only the clones inside this closed object change")
    O.b4d_fx_re_on = P.BoolVectorProperty(name="On", size=6, default=(True,) * 6, update=_live,
                                          description="Take this part back from the effectors above and use this list's instead")
    for key, label in RE_PARTS:
        setattr(O, f"b4d_fx_ch_{key}", P.FloatProperty(name=label, default=100.0, min=-1000.0, max=1000.0, soft_min=0.0,
                                                       soft_max=100.0, subtype="PERCENTAGE", update=_live,
                                                       description=f"0%: the effectors above keep their {label.lower()}; 100%: this list's {label.lower()} replaces it"))
        for a in (("RGB" if key == "color" else "XYZ") if key in ("pos", "scale", "rot", "color") else ""):
            setattr(O, f"b4d_fx_ch_{key}_{a.lower()}", P.FloatProperty(name=f"{label}.{a} Strength", default=100.0, min=-1000.0, max=1000.0,
                                                                         soft_min=0.0, soft_max=100.0, subtype="PERCENTAGE", update=_live))
    O.b4d_fx_retime = P.BoolProperty(name="ReTime", default=False, update=_retime,
                                     description="Play the keyframed animation of the effectors in the list between Start and End")
    O.b4d_fx_retime_start = P.IntProperty(name="Start", default=0, update=_retime)
    O.b4d_fx_retime_end = P.IntProperty(name="End", default=90, update=_retime)
    from . import moclone_fx_more
    moclone_fx_more.props()
    # fields
    O.b4d_fd_size = P.FloatVectorProperty(name="Size", size=3, default=(200.0, 200.0, 200.0), min=0.0, update=_live, description="The box's size (cm)")
    O.b4d_fd_radius = P.FloatProperty(name="Radius", default=100.0, min=0.0, update=_live, description="Radius (cm)")
    O.b4d_fd_height = P.FloatProperty(name="Height", default=200.0, min=0.0, update=_live, description="Height (cm)")
    O.b4d_fd_tube = P.FloatProperty(name="Ring Radius", default=25.0, min=0.0, update=_live, description="The thickness of the ring (cm)")
    O.b4d_fd_length = P.FloatProperty(name="Length", default=200.0, min=0.0, update=_live, description="How long the ramp is (cm)")
    O.b4d_fd_angle = P.FloatProperty(name="End Angle", default=90.0, min=0.0, max=360.0, update=_live, description="Where the strength reaches none (degrees)")
    O.b4d_fd_inner = P.FloatProperty(name="Inner Offset", default=0.0, min=0.0, max=100.0, description="Full strength out to this share of the size", **pct)
    O.b4d_fd_invert = P.BoolProperty(name="Invert", default=False, update=_live, description="Strong outside, weak inside")
    O.b4d_fd_strength = P.FloatProperty(name="Strength", default=100.0, min=0.0, max=1000.0, soft_max=100.0, description="How strong the field is", **pct)
    O.b4d_fd_noise = P.BoolProperty(name="Noise", default=False, update=_live, description="A smooth noise through space instead of a value per clone")
    O.b4d_fd_scale = P.FloatProperty(name="Scale", default=100.0, min=0.001, update=_live, description="The size of the noise (cm)")
    O.b4d_fd_speed = P.FloatProperty(name="Animation Speed", default=0.0, min=0.0, update=_live, description="How fast the noise moves")
    O.b4d_fd_seed = P.IntProperty(name="Seed", default=0, min=0, update=_live)


RE_PARTS = (("pos", "Position"), ("scale", "Scale"), ("rot", "Rotation"), ("color", "Color"), ("weight", "Weight"), ("vis", "Visibility"))


def _retime(self, context):
    from . import moclone_fx_more
    moclone_fx_more.retime(self)


FORMULA_VARS = ("id", "count", "t", "f", "falloff", "px", "py", "pz", "rx", "ry", "rz", "sx", "sy", "sz", "u", "v", "w")
PROPS = ("b4d_fx_list", "b4d_fx_index", "b4d_field_list", "b4d_field_index")


# --- creation --------------------------------------------------------------------------------------------------------

DEFAULTS = {"fx_random": {"b4d_fx_pos": (50.0, 50.0, 50.0)},
            "fx_target": {"b4d_fx_pos_on": False},
            "fx_delay": {"b4d_fx_pos_on": False},
            "fx_time": {"b4d_fx_pos_on": False, "b4d_fx_rot_on": True, "b4d_fx_rot": (0.0, 90.0, 0.0)},
            "fx_inherit": {"b4d_fx_scale_on": True, "b4d_fx_rot_on": True},
            "fx_spline": {"b4d_fx_rot_on": True}}


SCALE_PCT = "b4d_fx_scale_pct"


def _convert_scale():
    """Effectors from 0.1.30 to 0.1.34 kept Scale as a change (0 = as it is, -100 = gone); it is now the clone's size
    in % (100 = as it is, 0 = gone). A value that was set moves up by 100 once, so the clones look the same."""
    for ob in bpy.data.objects:
        if not fx.is_effector(ob) or ob.get(SCALE_PCT):
            continue
        if ob.is_property_set("b4d_fx_scale"):              # never set: it reads the new default, 100
            ob.b4d_fx_scale = [c + 100.0 for c in ob.b4d_fx_scale]
        if ob.is_property_set("b4d_fx_uscale"):
            ob.b4d_fx_uscale = ob.b4d_fx_uscale + 100.0
        ob[SCALE_PCT] = 1


@bpy.app.handlers.persistent
def _loaded(*_args):
    _convert_scale()
    from . import moclone_bake
    moclone_bake.refresh_all()


def create(context, k):
    from .primitives import tidy_name
    label = (fx.EFFECTORS.get(k) or fx.FIELDS.get(k))[0]
    sel = list(context.selected_objects)
    ob = bpy.data.objects.new(label, None)
    ob.empty_display_type = "PLAIN_AXES"
    ob.empty_display_size = 0.15
    ob["b4d_type"] = k
    ob[SCALE_PCT] = 1                                       # Scale is in % of the clone's size (see _convert_scale)
    context.collection.objects.link(ob)
    tidy_name(ob)
    for attr, v in DEFAULTS.get(k, {}).items():
        setattr(ob, attr, v)
    if k == "fx_sound":                                     # one probe to start with: the low notes, as a spectrum
        p = ob.b4d_fx_probes.add(); p.name = "Probe 1"
    if k in fx.EFFECTORS:
        for g in [o for o in sel if o.get("b4d_type") in MOGENS + fx.NESTS]:  # a selected Cloner (or Group) takes it at once
            add_effector(g, ob, gen_list(g, context))
    else:
        for e in [o for o in sel if fx.is_effector(o)]:                     # a selected effector takes the field
            add_field(e, ob)
        subject = getattr(context.window_manager, "b4d_am_subject", "")
        if subject.startswith("OTAG:"):                                     # made from a tag's page: it joins that page's list
            name, _s, key = subject[5:].rpartition(":")
            owner = bpy.data.objects.get(name)
            if owner is not None and key == "RIGID" and owner.get("b4d_type") in MOGENS:
                add_field(owner, ob)
                owner.pop("b4d_dyn_sig", None)
            elif owner is not None:
                from . import field_tags
                _i, t = field_tags.entry(owner, key) if key in field_tags.SPECS else (None, None)
                if t is not None:
                    it = t.fields.add(); it.obj = ob
                    if field_tags.SPECS[key][4]:
                        t.transfer = "FIELDS"
                    else:
                        t.use_fields = True
                    field_tags._touch(owner)
    return ob


def add_effector(gen, eff, lst="b4d_fx_list"):
    lst = getattr(gen, lst)
    if gen == eff or any(e.obj == eff for e in lst):
        return
    it = lst.add()
    it.obj = eff


def add_field(eff, field):
    if any(f.obj == field for f in eff.b4d_field_list):
        return
    it = eff.b4d_field_list.add()
    it.obj = field


class BLENDA4D_OT_fx_remove(bpy.types.Operator):
    """Take this out of the list (the object stays in the scene)"""
    bl_idname = "blenda4d.fx_remove"
    bl_label = "Remove"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty()
    which: bpy.props.StringProperty()        # "fx" or "field"
    index: bpy.props.IntProperty()

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None:
            return {"CANCELLED"}
        lst = _lst(ob, self.which)
        if 0 <= self.index < len(lst):
            lst.remove(self.index)
        _restructure(None, context)
        return {"FINISHED"}


class BLENDA4D_OT_fx_move(bpy.types.Operator):
    """Move up or down the list: the effectors work in list order"""
    bl_idname = "blenda4d.fx_move"
    bl_label = "Move"
    bl_options = {"REGISTER", "UNDO"}
    owner: bpy.props.StringProperty()
    which: bpy.props.StringProperty()
    index: bpy.props.IntProperty()
    step: bpy.props.IntProperty()

    def execute(self, context):
        ob = bpy.data.objects.get(self.owner)
        if ob is None:
            return {"CANCELLED"}
        lst = _lst(ob, self.which)
        to = self.index + self.step
        if 0 <= self.index < len(lst) and 0 <= to < len(lst):
            lst.move(self.index, to)
        _restructure(None, context)
        return {"FINISHED"}


class BLENDA4D_OT_fx_select(bpy.types.Operator):
    """Select this effector or field to see its settings"""
    bl_idname = "blenda4d.fx_select"
    bl_label = "Select"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty()

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None:
            return {"CANCELLED"}
        for o in context.view_layer.objects.selected:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        return {"FINISHED"}


class BLENDA4D_MT_fx_add(bpy.types.Menu):
    bl_label = "Add Effector"
    bl_idname = "BLENDA4D_MT_fx_add"

    def draw(self, context):
        for k, (label, _tip) in fx.EFFECTORS.items():
            self.layout.operator("blenda4d.add_kind", text=label, icon=fx.ICONS[k]).kind = k


class BLENDA4D_MT_field_add(bpy.types.Menu):
    bl_label = "Add Field"
    bl_idname = "BLENDA4D_MT_field_add"

    def draw(self, context):
        for k, (label, _tip) in fx.FIELDS.items():
            self.layout.operator("blenda4d.add_kind", text=label, icon=fx.ICONS[k]).kind = k


# --- pages -----------------------------------------------------------------------------------------------------------

TAB_LISTS = {"ALL": "b4d_fx_list_all", "LINES": "b4d_fx_list_lines", "WORDS": "b4d_fx_list_words", "LETTERS": "b4d_fx_list"}


def _lst(ob, which):
    """which: "fx", "field", or a list's own name (MoText's All, Lines, Words, Letters)."""
    if which.startswith("b4d_"):
        return getattr(ob, which)
    return ob.b4d_fx_list if which == "fx" else ob.b4d_field_list


def gen_list(gen, context):
    """The Effectors list an effector made or dropped now joins: MoText's level shown on its page, else the list."""
    if gen.get("b4d_type") == "motext":
        return TAB_LISTS.get(getattr(context.window_manager, "b4d_am_tab", ""), "b4d_fx_list")
    return "b4d_fx_list"


def _list(col, ob, which):
    lst = _lst(ob, which)
    box = col.column(align=True)
    box.use_property_split = False                      # rows span the page: name on the left, strength on the right
    if not len(lst):
        box.label(text="Drag effectors here from the Object Manager" if which == "fx" else "Drag fields here from the Object Manager",
                  icon="INFO")
    for i, it in enumerate(lst):
        line = box.row(align=True)
        split = line.split(factor=0.62, align=True)
        left, row = split.row(align=True), split.row(align=True)
        left.alignment = "LEFT"
        if it.obj is None:
            left.label(text="(gone)", icon="ERROR")
        else:
            left.prop(it, "on", text="")
            from . import icons
            op = left.operator("blenda4d.fx_select", text=it.obj.name, emboss=False,
                               **icons.kw(fx.ICONS.get(it.obj.get("b4d_type"), "DOT"), "effectors" if which == "fx" else "fields"))
            op.name = it.obj.name
            row.prop(it, "strength" if which == "fx" else "opacity", text="")
        for icon, step in (("TRIA_UP", -1), ("TRIA_DOWN", 1)):
            m = row.operator("blenda4d.fx_move", text="", icon=icon, emboss=False)
            m.owner, m.which, m.index, m.step = ob.name, which, i, step
        r = row.operator("blenda4d.fx_remove", text="", icon="X", emboss=False)
        r.owner, r.which, r.index = ob.name, which, i
    col.separator()
    col.menu("BLENDA4D_MT_field_add" if which == "field" else "BLENDA4D_MT_fx_add",
             text="Add Field" if which == "field" else "Add Effector", icon="ADD")


def page_cloner_effectors(col, ob):
    _list(col, ob, "fx")


def page_effector(col, ob):
    k = ob.get("b4d_type")
    c = col.column()
    c.prop(ob, "b4d_fx_strength")
    c.prop(ob, "b4d_fx_use_sel", text="Selection")
    if k not in ("fx_delay", "fx_group", "fx_pushapart"):
        c.prop(ob, "b4d_fx_min"); c.prop(ob, "b4d_fx_max")
    if k == "fx_group":
        c.separator(); c.prop(ob, "b4d_fx_retime")
        sub = c.column(align=True); sub.active = ob.b4d_fx_retime
        sub.prop(ob, "b4d_fx_retime_start"); sub.prop(ob, "b4d_fx_retime_end")
    if k in fx.NESTS:
        c.separator(); c.label(text="Effectors")
        _list(c, ob, "fx")
    if k == "fx_formula":
        c.separator(); c.prop(ob, "b4d_fx_formula")
        from . import formula
        bad = formula.check(ob.b4d_fx_formula, FORMULA_VARS)
        if bad:
            c.label(text=bad, icon="ERROR")
        c.prop(ob, "b4d_fx_tscale"); c.prop(ob, "b4d_fx_freq")
        box = c.column(align=True); box.scale_y = 0.8
        for line in ("id: the clone's number, count: how many clones", "t: time in seconds, f: Frequency",
                     "px py pz: position, rx ry rz: rotation, sx sy sz: scale", "u v: place across the arrangement, falloff: the fields' value"):
            box.label(text=line)
    elif k == "fx_pushapart":
        c.separator(); c.prop(ob, "b4d_fx_push_mode", text="Mode"); c.prop(ob, "b4d_fx_radius"); c.prop(ob, "b4d_fx_iterations")
    elif k == "fx_volume":
        c.separator(); c.prop(ob, "b4d_fx_volume")
    elif k in ("fx_spline", "fx_inherit", "fx_sound"):
        from . import moclone_fx_more
        moclone_fx_more.page(c, ob)
    if k == "fx_random":
        c.separator(); c.prop(ob, "b4d_fx_random_mode", text="Random Mode"); c.prop(ob, "b4d_fx_seed")
        if ob.b4d_fx_random_mode in ("NOISE", "TURBULENCE"):
            c.prop(ob, "b4d_fx_noise_scale"); c.prop(ob, "b4d_fx_speed")
    elif k == "fx_shader":
        c.separator(); c.prop(ob, "b4d_fx_shader_source", text="Shader")
        if ob.b4d_fx_shader_source == "IMAGE":
            c.template_ID(ob, "b4d_fx_image", open="image.open")
        else:
            c.prop(ob, "b4d_fx_noise_scale")
    elif k == "fx_target":
        c.separator(); c.prop(ob, "b4d_fx_target_mode", text="Target Mode")
        if ob.b4d_fx_target_mode == "OBJECT":
            c.prop(ob, "b4d_fx_target")
    elif k == "fx_delay":
        c.separator(); c.prop(ob, "b4d_fx_delay_mode", text="Mode")
        c.label(text="Works on the effectors above it in the Cloner's list", icon="INFO")


def page_parameter(col, ob):
    k = ob.get("b4d_type")
    if k == "fx_reeffector":
        c = col.column()
        names = {"pos": "XYZ", "scale": "XYZ", "rot": "XYZ", "color": "RGB"}
        for slot, (key, label) in enumerate(RE_PARTS):
            r = c.row(align=True, heading=f"{label} Strength")
            r.prop(ob, "b4d_fx_re_on", index=slot, text="")
            sub = r.row(align=True); sub.active = ob.b4d_fx_re_on[slot]
            sub.prop(ob, f"b4d_fx_ch_{key}", text="")
            if key in names:
                axes = c.column(align=True); axes.active = ob.b4d_fx_re_on[slot]
                for a in names[key]:
                    axes.prop(ob, f"b4d_fx_ch_{key}_{a.lower()}")
            c.separator(factor=0.5)
        return
    if k == "fx_spline":
        from . import moclone_fx_more
        moclone_fx_more.page_parameter(col, ob)
        return
    if k == "fx_inherit":
        c = col.column()
        for n in ("b4d_fx_pos_on", "b4d_fx_scale_on", "b4d_fx_rot_on"):
            c.prop(ob, n)
        return
    if k == "fx_target":
        col.label(text="Target turns the clones; it has no other settings here", icon="INFO")
        col.prop(ob, "b4d_fx_visibility")
        return
    if k == "fx_delay":
        col.label(text="Delay follows the effectors above it", icon="INFO")
        return
    c = col.column()
    c.prop(ob, "b4d_fx_pos_on")
    sub = c.column(align=True); sub.active = ob.b4d_fx_pos_on
    for i, a in enumerate("XYZ"):
        sub.prop(ob, "b4d_fx_pos", index=i, text=f"P . {a}")
    c.separator()
    c.prop(ob, "b4d_fx_scale_on")
    sub = c.column(align=True); sub.active = ob.b4d_fx_scale_on
    sub.prop(ob, "b4d_fx_uniform")
    if ob.b4d_fx_uniform:
        sub.prop(ob, "b4d_fx_uscale", text="S %")
    else:
        for i, a in enumerate("XYZ"):
            sub.prop(ob, "b4d_fx_scale", index=i, text=f"S % . {a}")
    c.separator()
    c.prop(ob, "b4d_fx_rot_on")
    sub = c.column(align=True); sub.active = ob.b4d_fx_rot_on
    for i, a in enumerate("XYZ"):
        sub.prop(ob, "b4d_fx_rot", index=i, text=f"R . {a}")
    c.separator()
    c.prop(ob, "b4d_fx_color_mode", text="Color Mode")
    if ob.b4d_fx_color_mode == "CUSTOM":
        c.prop(ob, "b4d_fx_color")
    c.prop(ob, "b4d_fx_visibility")


def page_fields(col, ob):
    _list(col, ob, "field")


def page_field(col, ob):
    k = ob.get("b4d_type")
    c = col.column()
    if k == "fd_sphere":
        c.prop(ob, "b4d_fd_radius")
    elif k == "fd_box":
        for i, a in enumerate("XYZ"):
            c.prop(ob, "b4d_fd_size", index=i, text=f"Size . {a}")
    elif k in ("fd_cylinder", "fd_cone", "fd_capsule"):
        c.prop(ob, "b4d_fd_radius"); c.prop(ob, "b4d_fd_height")
    elif k == "fd_torus":
        c.prop(ob, "b4d_fd_radius"); c.prop(ob, "b4d_fd_tube")
    elif k == "fd_linear":
        c.prop(ob, "b4d_fd_length")
    elif k == "fd_radial":
        c.prop(ob, "b4d_fd_angle")
    elif k == "fd_random":
        c.prop(ob, "b4d_fd_noise"); c.prop(ob, "b4d_fd_seed")
        if ob.b4d_fd_noise:
            c.prop(ob, "b4d_fd_scale"); c.prop(ob, "b4d_fd_speed")
    c.separator()
    if k not in ("fd_linear", "fd_radial", "fd_random"):
        c.prop(ob, "b4d_fd_inner")
    c.prop(ob, "b4d_fd_invert"); c.prop(ob, "b4d_fd_strength")


# --- drag and drop from the Object Manager ---------------------------------------------------------------------------

def drop(context, objs, event):
    """Effectors let go over a Cloner's Effectors page join its list; fields over an effector's Fields page join its."""
    from . import roles
    over = next((a for a in context.window.screen.areas if roles.role(a) == "ATTRIBUTES"
                 and a.x <= event.mouse_x < a.x + a.width and a.y <= event.mouse_y < a.y + a.height), None)
    if over is None:
        return False
    ob = context.view_layer.objects.active
    tab = getattr(context.window_manager, "b4d_am_tab", "")
    took = False
    subject = getattr(context.window_manager, "b4d_am_subject", "")
    if subject.startswith("OTAG:") and subject.endswith(":RIGID"):     # a Cloner's Rigid Body page: fields that start it
        gen = bpy.data.objects.get(subject[5:].rpartition(":")[0])
        if gen is not None and gen.get("b4d_type") == "cloner":
            for o in objs:
                if fx.is_field(o):
                    add_field(gen, o); took = True
            if took:
                gen.pop("b4d_dyn_sig", None)
                over.tag_redraw()
            return took
    if ob is not None and ob.get("b4d_type") in MOGENS and (tab == "EFFECTORS" or (ob.get("b4d_type") == "motext" and tab in TAB_LISTS)):
        for o in objs:
            if fx.is_effector(o):
                add_effector(ob, o, gen_list(ob, context)); took = True
    elif ob is not None and ob.get("b4d_type") in fx.NESTS and tab == "EFFECTOR":
        for o in objs:
            if fx.is_effector(o) and o != ob:
                add_effector(ob, o); took = True
    elif (fx.is_effector(ob) or (ob is not None and ob.get("b4d_type") == "polyfx")) and tab == "FIELDS":
        for o in objs:
            if fx.is_field(o):
                add_field(ob, o); took = True
    if took:
        _restructure(None, context)
        over.tag_redraw()
    return took


# --- field shapes in the viewport ------------------------------------------------------------------------------------

_handle = None
OUTER, INNER, DIM = (1.0, 0.82, 0.25, 1.0), (1.0, 0.55, 0.15, 0.9), (1.0, 0.82, 0.25, 0.35)


def _circle(m, axis, r, center=(0, 0, 0), n=48):
    pts = []
    for k in range(n + 1):
        a = 2 * math.pi * k / n
        c, s = math.cos(a) * r, math.sin(a) * r
        v = {"X": (0, c, s), "Y": (c, 0, s), "Z": (c, s, 0)}[axis]
        pts.append(m @ Vector((v[0] + center[0], v[1] + center[1], v[2] + center[2])))
    return [(pts[i], pts[i + 1]) for i in range(n)]


def _box(m, hx, hy, hz):
    c = [Vector((x, y, z)) for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)]
    e = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
    return [(m @ c[a], m @ c[b]) for a, b in e]


def _shape(ob, scale=1.0):
    """Line pairs for the field's shape in Blender space (shown sizes in cm; shown Y = Blender Z)."""
    m = ob.matrix_world
    k = ob["b4d_type"]
    cm = 0.01 * scale
    if k == "fd_sphere":
        r = ob.b4d_fd_radius * cm
        return _circle(m, "X", r) + _circle(m, "Y", r) + _circle(m, "Z", r)
    if k == "fd_box":
        s = ob.b4d_fd_size
        return _box(m, s[0] * cm / 2, s[2] * cm / 2, s[1] * cm / 2)
    if k in ("fd_cylinder", "fd_capsule"):
        r, h = ob.b4d_fd_radius * cm, ob.b4d_fd_height * cm / 2
        out = _circle(m, "Z", r, (0, 0, h)) + _circle(m, "Z", r, (0, 0, -h))
        for a in range(4):
            x, y = math.cos(a * math.pi / 2) * r, math.sin(a * math.pi / 2) * r
            out.append((m @ Vector((x, y, h)), m @ Vector((x, y, -h))))
        return out
    if k == "fd_cone":
        r, h = ob.b4d_fd_radius * cm, ob.b4d_fd_height * cm / 2
        out = _circle(m, "Z", r, (0, 0, -h))
        for a in range(4):
            x, y = math.cos(a * math.pi / 2) * r, math.sin(a * math.pi / 2) * r
            out.append((m @ Vector((x, y, -h)), m @ Vector((0, 0, h))))
        return out
    if k == "fd_torus":
        r, t = ob.b4d_fd_radius * cm, ob.b4d_fd_tube * cm
        return _circle(m, "Z", r + t) + _circle(m, "Z", max(r - t, 0.0)) + _circle(m, "Z", r, (0, 0, t)) + _circle(m, "Z", r, (0, 0, -t))
    if k == "fd_linear":
        L = ob.b4d_fd_length * 0.01 / 2
        sq = 0.5
        out = []
        for y in (-L, L):                                          # shown Z = Blender Y
            c = [Vector((-sq, y, -sq)), Vector((sq, y, -sq)), Vector((sq, y, sq)), Vector((-sq, y, sq))]
            out += [(m @ c[i], m @ c[(i + 1) % 4]) for i in range(4)]
        out.append((m @ Vector((0, -L, 0)), m @ Vector((0, L, 0))))
        out += [(m @ Vector((0, L, 0)), m @ Vector((0.08, L - 0.15, 0))), (m @ Vector((0, L, 0)), m @ Vector((-0.08, L - 0.15, 0)))]
        return out
    if k == "fd_radial":
        R = 1.0
        end = math.radians(ob.b4d_fd_angle)
        out = [(m @ Vector((0, 0, 0)), m @ Vector((0, R, 0))), (m @ Vector((0, 0, 0)), m @ Vector((math.sin(end) * R, math.cos(end) * R, 0)))]
        n = 24
        for i in range(n):
            a0, a1 = end * i / n, end * (i + 1) / n
            out.append((m @ Vector((math.sin(a0) * R, math.cos(a0) * R, 0)), m @ Vector((math.sin(a1) * R, math.cos(a1) * R, 0))))
        return out
    if k == "fd_random":
        s = 0.5
        return _box(m, s, s, s)
    return []


def field_outlines(context):
    """For the viewport's click: each visible field and the lines of its shape (handles.py picks by them)."""
    out = []
    for o in context.view_layer.objects:
        if fx.is_field(o) and o.visible_get():
            out.append((o, _shape(o)))
    return out


def _draw():
    ctx = bpy.context
    try:
        objs = [o for o in ctx.view_layer.objects if fx.is_field(o) and o.visible_get()]
    except Exception:
        return
    if not objs:
        return
    sh = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    region = ctx.region
    sh.uniform_float("viewportSize", (region.width, region.height))
    gpu.state.blend_set("ALPHA")
    for o in objs:
        sel = o.select_get()
        for col, sc in ((OUTER if sel else DIM, 1.0),) + (((INNER, o.b4d_fd_inner / 100.0),) if sel and o.b4d_fd_inner > 0 and
                                                          o["b4d_type"] not in ("fd_linear", "fd_radial", "fd_random") else ()):
            segs = _shape(o, sc)
            if not segs:
                continue
            coords = [p for pair in segs for p in pair]
            sh.uniform_float("color", col)
            sh.uniform_float("lineWidth", 1.5 if sel else 1.0)
            batch_for_shader(sh, "LINES", {"pos": coords}).draw(sh)
    gpu.state.blend_set("NONE")


# --- registration ----------------------------------------------------------------------------------------------------

classes = (B4DFxEntry, B4DFieldEntry, BLENDA4D_OT_fx_remove, BLENDA4D_OT_fx_move, BLENDA4D_OT_fx_select,
           BLENDA4D_MT_fx_add, BLENDA4D_MT_field_add)


def register():
    global _handle
    for c in classes:
        bpy.utils.register_class(c)
    _props()
    from . import bars
    for group in ("effectors", "fields"):                 # the create column lists them in this module's order
        if group in bars.GROUPS:
            bars.GROUPS[group][:] = []
    for k, (label, tip) in fx.EFFECTORS.items():
        tabs = [("EFFECTOR", "Effector"), ("PARAMETER", "Parameter"), ("FIELDS", "Fields")]
        if k == "fx_group":
            tabs = tabs[:1]
        elif k == "fx_pushapart":
            tabs = tabs[:1]
        kinds.add(k, label, fx.ICONS[k], create=(lambda k: lambda context: create(context, k))(k),
                  tabs=tabs,
                  pages={"EFFECTOR": page_effector, "PARAMETER": page_parameter, "FIELDS": page_fields},
                  titles={"EFFECTOR": label, "PARAMETER": "Parameter", "FIELDS": "Fields"},
                  describe=tip + " (a selected Cloner takes it into its Effectors list)")
        kinds.create_button("effectors", label + " Effector", k)
    for k, (label, tip) in fx.FIELDS.items():
        kinds.add(k, label, fx.ICONS[k], create=(lambda k: lambda context: create(context, k))(k),
                  tabs=[("FIELD", "Field")], pages={"FIELD": page_field}, titles={"FIELD": label},
                  describe=tip + " (a selected effector takes it into its Fields list)")
        kinds.create_button("fields", label, k)
    from . import managers
    if drop not in managers.OM_DROP:
        managers.OM_DROP.append(drop)
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    from . import handles
    handles.outlines(field_outlines)
    if _loaded not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_loaded)
    try:
        _convert_scale()                                    # the file open while Blenda starts
    except AttributeError:
        pass


def unregister():
    global _handle
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    from . import managers
    if drop in managers.OM_DROP:
        managers.OM_DROP.remove(drop)
    for n in PROPS:
        if hasattr(bpy.types.Object, n):
            delattr(bpy.types.Object, n)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    from . import moclone_fx_more
    for c in reversed(moclone_fx_more.classes):
        if getattr(c, "is_registered", False):
            bpy.utils.unregister_class(c)
