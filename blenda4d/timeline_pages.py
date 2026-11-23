# SPDX-License-Identifier: GPL-3.0-or-later
"""The Key and Track pages of the Attribute Manager. Clicking a key or a track in the Timeline shows its page, every
row on Blender's own value: numbers belong to the key that was clicked, the type and the tangent switches to every
selected key."""
import math

import bpy

from . import anim as A

_ref = {"KEY": None, "TRACK": None}          # (data-block, data path, index[, frame]): names, never a pointer


def scale_of(fc):
    """Blender's value -> the value shown: centimetres for positions, degrees for rotations."""
    path = fc.data_path
    if path.endswith("location"):
        return 100.0
    if path.endswith("rotation_euler") or (path.endswith("rotation_axis_angle") and fc.array_index > 0):
        return 180.0 / math.pi
    return 1.0




def show(subject, fc, kp=None):
    from . import timeline_edit
    _ref[subject] = (timeline_edit.track_key(fc), None if kp is None else kp.co.x)
    wm = bpy.context.window_manager
    wm.b4d_am_subject = subject + ":"
    if getattr(wm, "b4d_right_tab", "ATTRIBUTES") != "ATTRIBUTES":
        wm.b4d_right_tab = "ATTRIBUTES"


def _curve(subject):
    from . import timeline_edit
    ref = _ref[subject]
    if ref is None:
        return None
    return next((fc for ob in bpy.context.scene.objects for fc in A.all_of(ob) if timeline_edit.track_key(fc) == ref[0]), None)


def _key():
    fc = _curve("KEY")
    if fc is None:
        return None, None
    return fc, min(fc.keyframe_points, key=lambda k: abs(k.co.x - _ref["KEY"][1]), default=None)


def _points():
    fc, kp = _key()
    from . import timeline_edit                          # the keys the Timeline shows: never ones out of sight
    out = A.selected_points(bpy.context, timeline_edit.all_curves(bpy.context))
    return out or ([(fc, kp)] if kp is not None else [])


TYPES = (("SPLINE", "Spline", "Curve through the keys"), ("LINEAR", "Linear", "Straight from key to key"),
         ("STEP", "Step", "Hold the value until the next key"))
BLENDER = ("BEZIER", "LINEAR", "CONSTANT")


def _type_get(self):
    _fc, kp = _key()
    return BLENDER.index(kp.interpolation) if kp is not None and kp.interpolation in BLENDER else 0


def _type_set(self, v):
    pts = _points()
    for _fc, kp in pts:
        kp.interpolation = BLENDER[v]
    A.update(bpy.context, {p[0] for p in pts})


def _number(name):
    side, _, part = name.partition("_")

    def get(self):
        fc, kp = _key()
        if kp is None:
            return 0.0
        k = scale_of(fc)
        if side == "key":
            return kp.co.x if part == "time" else kp.co.y * k
        h = getattr(kp, "handle_" + side)
        return h[0] - kp.co.x if part == "time" else (h[1] - kp.co.y) * k

    def set_(self, v):
        fc, kp = _key()
        if kp is None:
            return
        k = scale_of(fc)
        if side == "key":
            axis = 0 if part == "time" else 1
            new = round(v) if axis == 0 else v / k
            d = new - kp.co[axis]
            kp.co[axis] = new
            kp.handle_left[axis] += d
            kp.handle_right[axis] += d
            if axis == 0:
                _ref["KEY"] = (_ref["KEY"][0], new)
        else:
            if kp.handle_left_type not in {"FREE", "VECTOR"}:
                kp.handle_left_type = kp.handle_right_type = "ALIGNED"
            h = getattr(kp, "handle_" + side)
            if part == "time":
                h[0] = kp.co.x + (min(0.0, v) if side == "left" else max(0.0, v))
            else:
                h[1] = kp.co.y + v / k
        A.update(bpy.context, {fc})
    return {"get": get, "set": set_}


def _flag(kind):
    def get(self):
        _fc, kp = _key()
        t = kp.handle_left_type if kp is not None else ""
        return t in {"auto": ("AUTO", "AUTO_CLAMPED"), "clamp": ("AUTO_CLAMPED",), "broken": ("FREE", "VECTOR")}[kind]

    def set_(self, on):
        pts = _points()
        for _fc, kp in pts:
            auto = kp.handle_left_type in {"AUTO", "AUTO_CLAMPED"}
            if kind == "auto":
                t = "AUTO" if on else "ALIGNED"
            elif kind == "clamp":
                t = "AUTO_CLAMPED" if on else "AUTO" if auto else "ALIGNED"
            else:
                t = "FREE" if on else "ALIGNED"
            kp.handle_left_type = kp.handle_right_type = t
        A.update(bpy.context, {p[0] for p in pts})
    return {"get": get, "set": set_}


MODES = (("CONSTANT", "Constant", "Keep the first or last key's value"), ("CONTINUE", "Continue", "Go on in the same direction"),
         ("REPEAT", "Repeat", "Play the keys again"), ("OFFSET", "Offset Repeat", "Play the keys again from where they ended"),
         ("OSCILLATE", "Oscillate", "Play the keys forwards and backwards"))
CYCLES = {"REPEAT": "REPEAT", "OFFSET": "REPEAT_OFFSET", "OSCILLATE": "MIRROR"}


def _cycles(fc, make=False):
    m = next((m for m in fc.modifiers if m.type == "CYCLES"), None)
    if m is None and make:
        m = fc.modifiers.new("CYCLES")
        m.mode_before = m.mode_after = "NONE"
    return m


def _outside(side):
    def get(self):
        fc = _curve("TRACK")
        if fc is None:
            return 0
        m = _cycles(fc)
        mode = getattr(m, "mode_" + side) if m else "NONE"
        for i, (k, _l, _d) in enumerate(MODES):
            if CYCLES.get(k) == mode:
                return i
        return 1 if fc.extrapolation == "LINEAR" else 0

    def set_(self, v):
        fc = _curve("TRACK")
        if fc is None:
            return
        key = MODES[v][0]
        if key in CYCLES:
            setattr(_cycles(fc, make=True), "mode_" + side, CYCLES[key])
        else:
            m = _cycles(fc)
            if m is not None:
                setattr(m, "mode_" + side, "NONE")
                if m.mode_before == m.mode_after == "NONE":
                    fc.modifiers.remove(m)
            fc.extrapolation = "LINEAR" if key == "CONTINUE" else "CONSTANT"
        A.update(bpy.context, {fc})
    return {"get": get, "set": set_}


def _times(side):
    def get(self):
        fc = _curve("TRACK")
        m = _cycles(fc) if fc else None
        return getattr(m, "cycles_" + side) if m else 0

    def set_(self, v):
        fc = _curve("TRACK")
        m = _cycles(fc) if fc else None
        if m is not None:
            setattr(m, "cycles_" + side, v)
            A.update(bpy.context, {fc})
    return {"get": get, "set": set_}


def _on_get(self):
    fc = _curve("TRACK")
    return bool(fc and not fc.mute)


def _on_set(self, v):
    fc = _curve("TRACK")
    if fc is not None:
        fc.mute = not v
        A.update(bpy.context, {fc})


_B, _F, _E, _I = bpy.props.BoolProperty, bpy.props.FloatProperty, bpy.props.EnumProperty, bpy.props.IntProperty


class BLENDA4D_TimelinePage(bpy.types.PropertyGroup):
    key_type: _E(name="Type", items=TYPES, get=_type_get, set=_type_set, description="How the curve leaves the selected keys")
    key_time: _F(name="Key Time", precision=0, description="The key's frame", **_number("key_time"))
    key_value: _F(name="Key Value", description="The key's value", **_number("key_value"))
    auto: _B(name="Auto Tangents", description="Let Blender shape the tangents", **_flag("auto"))
    clamp: _B(name="Clamp", description="Keep the curve from going past its keys", **_flag("clamp"))
    broken: _B(name="Break Tangents", description="Let the two tangents turn on their own", **_flag("broken"))
    left_time: _F(name="Left Time", description="The left tangent's length in frames", **_number("left_time"))
    left_value: _F(name="Left Value", description="The left tangent's height", **_number("left_value"))
    right_time: _F(name="Right Time", description="The right tangent's length in frames", **_number("right_time"))
    right_value: _F(name="Right Value", description="The right tangent's height", **_number("right_value"))
    animation: _B(name="Animation", description="Use this track's keys", get=_on_get, set=_on_set)
    before: _E(name="Before", items=MODES, description="What happens before the first key", **_outside("before"))
    after: _E(name="After", items=MODES, description="What happens after the last key", **_outside("after"))
    times_before: _I(name="Repetitions", min=0, description="How many times before the first key (0: no end)", **_times("before"))
    times_after: _I(name="Repetitions", min=0, description="How many times after the last key (0: no end)", **_times("after"))


def _page(layout):
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False
    return col


def draw_key(layout, context, _ob):
    from . import timeline_edit
    fc, kp = _key()
    if kp is None:
        return False
    tp, n = context.window_manager.b4d_tl, len(_points())
    layout.label(text=f"Key [{timeline_edit.track_label(fc)}]" + (f"  {n} keys" if n > 1 else ""), icon="KEYFRAME_HLT")
    layout.label(text="Key Properties")
    col = _page(layout)
    col.prop(tp, "key_type")
    col.prop(tp, "key_time")
    col.prop(tp, "key_value")
    layout.separator(factor=0.5)
    layout.label(text="Tangents")
    col = _page(layout)
    col.enabled = kp.interpolation == "BEZIER"
    for name in ("auto", "clamp", "broken", "left_time", "right_time", "left_value", "right_value"):
        col.prop(tp, name)
    return True


def draw_track(layout, context, _ob):
    from . import timeline_edit
    fc = _curve("TRACK")
    if fc is None:
        return False
    tp = context.window_manager.b4d_tl
    layout.label(text=f"Track [{timeline_edit.track_label(fc)}]", icon="FCURVE")
    layout.label(text="Track Properties")
    col = _page(layout)
    col.prop(tp, "animation")
    for side in ("before", "after"):
        col.prop(tp, side)
        sub = col.column()
        sub.enabled = getattr(tp, side) in CYCLES
        sub.prop(tp, "times_" + side)
    col.prop(fc, "color_mode", text="Color")
    if fc.color_mode == "CUSTOM":
        col.prop(fc, "color", text="Custom")
    return True


def register():
    from . import managers
    bpy.utils.register_class(BLENDA4D_TimelinePage)
    bpy.types.WindowManager.b4d_tl = bpy.props.PointerProperty(type=BLENDA4D_TimelinePage)
    managers.AM_SUBJECTS["KEY"] = draw_key
    managers.AM_SUBJECTS["TRACK"] = draw_track


def unregister():
    from . import managers
    managers.AM_SUBJECTS.pop("KEY", None)
    managers.AM_SUBJECTS.pop("TRACK", None)
    _ref.update(KEY=None, TRACK=None)
    del bpy.types.WindowManager.b4d_tl
    bpy.utils.unregister_class(BLENDA4D_TimelinePage)
