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

MOGENS = ("cloner", "matrix")


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
    O.b4d_field_index = P.IntProperty()
    pct = dict(subtype="PERCENTAGE", update=_live)
    O.b4d_fx_strength = P.FloatProperty(name="Strength", default=100.0, soft_min=0.0, soft_max=100.0, min=-1000.0, max=1000.0,
                                        description="How strongly the effector works", **pct)
    O.b4d_fx_min = P.FloatProperty(name="Minimum", default=0.0, min=-1000.0, max=1000.0, description="The effect where the fields give nothing", **pct)
    O.b4d_fx_max = P.FloatProperty(name="Maximum", default=100.0, min=-1000.0, max=1000.0, description="The effect where the fields give full strength", **pct)
    O.b4d_fx_pos_on = P.BoolProperty(name="Position", default=True, update=_live, description="Move the clones")
    O.b4d_fx_pos = P.FloatVectorProperty(name="P", size=3, default=(0.0, 50.0, 0.0), update=_live, description="How far to move them (cm)")
    O.b4d_fx_scale_on = P.BoolProperty(name="Scale", default=False, update=_live, description="Scale the clones")
    O.b4d_fx_scale = P.FloatVectorProperty(name="S", size=3, default=(0.0, 0.0, 0.0), update=_live, description="How much to scale them (%: 100 = twice the size)")
    O.b4d_fx_uniform = P.BoolProperty(name="Uniform Scale", default=False, update=_live, description="One scale for all three axes")
    O.b4d_fx_uscale = P.FloatProperty(name="Scale", default=0.0, update=_live, description="How much to scale them on all axes (%)")
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


PROPS = ("b4d_fx_list", "b4d_fx_index", "b4d_field_list", "b4d_field_index")


# --- creation --------------------------------------------------------------------------------------------------------

DEFAULTS = {"fx_random": {"b4d_fx_pos": (50.0, 50.0, 50.0)},
            "fx_target": {"b4d_fx_pos_on": False},
            "fx_delay": {"b4d_fx_pos_on": False},
            "fx_time": {"b4d_fx_pos_on": False, "b4d_fx_rot_on": True, "b4d_fx_rot": (0.0, 90.0, 0.0)}}


def create(context, k):
    from .primitives import tidy_name
    label = (fx.EFFECTORS.get(k) or fx.FIELDS.get(k))[0]
    sel = list(context.selected_objects)
    ob = bpy.data.objects.new(label, None)
    ob.empty_display_type = "PLAIN_AXES"
    ob.empty_display_size = 0.15
    ob["b4d_type"] = k
    context.collection.objects.link(ob)
    tidy_name(ob)
    for attr, v in DEFAULTS.get(k, {}).items():
        setattr(ob, attr, v)
    if k in fx.EFFECTORS:
        for g in [o for o in sel if o.get("b4d_type") in MOGENS]:            # a selected Cloner takes it at once
            add_effector(g, ob)
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


def add_effector(gen, eff):
    if any(e.obj == eff for e in gen.b4d_fx_list):
        return
    it = gen.b4d_fx_list.add()
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
        lst = ob.b4d_fx_list if self.which == "fx" else ob.b4d_field_list
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
        lst = ob.b4d_fx_list if self.which == "fx" else ob.b4d_field_list
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

def _list(col, ob, which):
    lst = ob.b4d_fx_list if which == "fx" else ob.b4d_field_list
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
    col.menu("BLENDA4D_MT_fx_add" if which == "fx" else "BLENDA4D_MT_field_add",
             text="Add Effector" if which == "fx" else "Add Field", icon="ADD")


def page_cloner_effectors(col, ob):
    _list(col, ob, "fx")


def page_effector(col, ob):
    k = ob.get("b4d_type")
    c = col.column()
    c.prop(ob, "b4d_fx_strength")
    c.prop(ob, "b4d_fx_use_sel", text="Selection")
    if k != "fx_delay":
        c.prop(ob, "b4d_fx_min"); c.prop(ob, "b4d_fx_max")
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
        sub.prop(ob, "b4d_fx_uscale", text="S")
    else:
        for i, a in enumerate("XYZ"):
            sub.prop(ob, "b4d_fx_scale", index=i, text=f"S . {a}")
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
    if ob is not None and ob.get("b4d_type") in MOGENS and tab == "EFFECTORS":
        for o in objs:
            if fx.is_effector(o):
                add_effector(ob, o); took = True
    elif fx.is_effector(ob) and tab == "FIELDS":
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
        kinds.add(k, label, fx.ICONS[k], create=(lambda k: lambda context: create(context, k))(k),
                  tabs=[("EFFECTOR", "Effector"), ("PARAMETER", "Parameter"), ("FIELDS", "Fields")],
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


def unregister():
    global _handle
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
