# SPDX-License-Identifier: GPL-3.0-or-later
"""Keys and tracks: what the timeline, the Dope Sheet and the F-Curves read and change. The data, the interpolation
and the undo are Blender's own; this module finds the curves an object owns, moves keys safely and draws the basics.

A drag remembers keyframes. Anything that inserts, removes or sorts keys can move them in memory, so every such edit
calls new_token(): a drag whose token is not the current one stops at once and never writes to a stale key."""
import bpy
from bpy_extras import anim_utils

BG = (0.169, 0.169, 0.169, 1.0)
DARK = (0.137, 0.137, 0.137, 1.0)
BAND = (0.204, 0.204, 0.204, 1.0)
FIELD = (0.11, 0.11, 0.11, 1.0)
TEXT = (0.82, 0.82, 0.82, 1.0)
DIM = (0.54, 0.54, 0.54, 1.0)
TICK = (0.38, 0.38, 0.38, 1.0)
KEY = (0.70, 0.70, 0.70, 1.0)
KEY_SEL = (0.91, 0.57, 0.23, 1.0)
KEY_PART = (0.82, 0.74, 0.42, 1.0)
RANGE = (0.91, 0.57, 0.23, 0.28)
RANGE_EDGE = (0.91, 0.57, 0.23, 0.95)
NOW = (0.42, 0.42, 0.72, 1.0)
EDGE = (0.09, 0.09, 0.09, 1.0)

_token = [0]
_owner = {}                  # curve -> the data-block it animates


def new_token():
    _token[0] += 1
    return _token[0]


def token():
    return _token[0]


# --- whose keys -----------------------------------------------------------------------------------------------------
def curves_of(block):
    """The F-Curves of a data-block's own action."""
    ad = getattr(block, "animation_data", None)
    if ad is None or ad.action is None:
        return []
    try:
        bag = anim_utils.animdata_get_channelbag_for_assigned_slot(ad)
    except (AttributeError, TypeError, RuntimeError):
        bag = None
    out = list(bag.fcurves) if bag is not None else list(getattr(ad.action, "fcurves", []))
    for fc in out:
        _owner[fc.as_pointer()] = block
    return out


def owner_of(fc):
    return _owner.get(fc.as_pointer())


def sources(ob):
    """[(folder, curves)]: everything an object animates. Folder None is the object itself."""
    out = [(None, curves_of(ob))]
    data = getattr(ob, "data", None)
    if data is not None:
        name = {"CAMERA": "Camera", "LIGHT": "Light", "CURVE": "Spline", "FONT": "Text"}.get(ob.type, "Object Data")
        out.append((name, curves_of(data)))
        shape_keys = getattr(data, "shape_keys", None)
        if shape_keys is not None:
            out.append(("Shape Keys", curves_of(shape_keys)))
    seen = set()
    for slot in getattr(ob, "material_slots", ()):
        mat = slot.material
        if mat is not None and mat.name not in seen:
            seen.add(mat.name)
            out.append((f"Material: {mat.name}", curves_of(mat) + (curves_of(mat.node_tree) if mat.node_tree else [])))
    return [(f, c) for f, c in out if c]


def all_of(ob):
    return [fc for _f, curves in sources(ob) for fc in curves]


def objects(context):
    """The selected objects, the active one among them."""
    obs = list(context.view_layer.objects.selected)
    act = context.view_layer.objects.active
    if act is not None and act not in obs and act.name in context.view_layer.objects:
        obs.append(act)
    return obs


def curves(context):
    return [fc for ob in objects(context) for fc in all_of(ob)]


def selected_points(context, among=None):
    return [(fc, kp) for fc in (curves(context) if among is None else among) for kp in fc.keyframe_points
            if kp.select_control_point]


def set_selected(kp, on):
    kp.select_control_point = kp.select_left_handle = kp.select_right_handle = on


def key_frames(context):
    """{frame: is one of its keys selected} of the selected objects."""
    out = {}
    for fc in curves(context):
        for kp in fc.keyframe_points:
            f = round(kp.co.x)
            out[f] = out.get(f, False) or kp.select_control_point
    return out


def select_between(context, a, b, extend=False):
    for fc in curves(context):
        for kp in fc.keyframe_points:
            if a - 0.5 <= kp.co.x <= b + 0.5:
                set_selected(kp, True)
            elif not extend:
                set_selected(kp, False)


# --- changing them ----------------------------------------------------------------------------------------------------
def refresh(context):
    context.scene.frame_set(context.scene.frame_current)
    redraw()


def update(context, changed=None):
    """After an edit: keys in order, curves and the scene up to date."""
    new_token()
    for fc in (curves(context) if changed is None else changed):
        fc.keyframe_points.sort()
        fc.update()
    for ob in objects(context):
        ob.update_tag(refresh={"TIME"})
    refresh(context)


def push(message):
    bpy.ops.ed.undo_push(message=message)


def remember(points):
    return [(fc, kp, kp.co.x, kp.co.y, tuple(kp.handle_left), tuple(kp.handle_right), kp.interpolation,
             kp.handle_left_type, kp.handle_right_type, kp.easing) for fc, kp in points]


def retime(context, saved, fn):
    """Each remembered key goes to fn(its frame), on whole frames, its tangents with it. Nothing is sorted here."""
    for fc, kp, x, _y, hl, hr, *_rest in saved:
        nx = round(fn(x))
        k = (fn(x + 1e-3) - fn(x)) / 1e-3
        kp.co.x = nx
        kp.handle_left = (nx + (hl[0] - x) * k, hl[1])
        kp.handle_right = (nx + (hr[0] - x) * k, hr[1])
    for fc in {t[0] for t in saved}:
        fc.id_data.update_tag()
    refresh(context)


def drop_overlaid(saved):
    """Keys moved onto others replace them, as one key per frame is all a curve can hold."""
    for fc in {t[0] for t in saved}:
        moved = {round(kp.co.x) for kp in fc.keyframe_points if kp.select_control_point}
        for kp in reversed(list(fc.keyframe_points)):
            if not kp.select_control_point and round(kp.co.x) in moved:
                fc.keyframe_points.remove(kp, fast=True)


def keep_copies(saved):
    """The keys stay where they were, and the moved ones are copies."""
    for fc, _kp, x, y, hl, hr, interp, lt, rt, easing in saved:
        if any(abs(p.co.x - x) < 0.01 for p in fc.keyframe_points):
            continue
        p = fc.keyframe_points.insert(x, y, options={"FAST"})
        p.interpolation, p.handle_left_type, p.handle_right_type, p.easing = interp, lt, rt, easing
        p.handle_left, p.handle_right = hl, hr
        set_selected(p, False)


def delete_selected(context, among=None):
    new_token()
    among = curves(context) if among is None else among
    n = 0
    for fc in among:
        for kp in reversed(list(fc.keyframe_points)):
            if kp.select_control_point:
                fc.keyframe_points.remove(kp, fast=True)
                n += 1
    update(context, among)
    return n


def add_key(fc, frame):
    kp = fc.keyframe_points.insert(frame, fc.evaluate(frame))
    set_selected(kp, True)
    return kp


INTERPOLATIONS = (("LINEAR", "Linear", "IPO_LINEAR", "Straight from key to key"),
                  ("STEP", "Step", "IPO_CONSTANT", "Hold each key's value until the next one"),
                  ("SPLINE", "Spline", "IPO_BEZIER", "Curve through the keys"),
                  ("SOFT", "Soft", "IPO_SINE", "Curve through the keys without going past them"),
                  ("EASE_IN", "Ease In", "IPO_EASE_OUT", "Slow down into the key"),
                  ("EASE_EASE", "Ease Ease", "IPO_EASE_IN_OUT", "Slow down into the key and speed up out of it"),
                  ("EASE_OUT", "Ease Out", "IPO_EASE_IN", "Speed up out of the key"))


def interpolate(context, kind, points):
    for _fc, kp in points:
        if kind in ("LINEAR", "STEP"):
            kp.interpolation = "LINEAR" if kind == "LINEAR" else "CONSTANT"
            continue
        kp.interpolation = "BEZIER"
        if kind == "SPLINE":
            kp.handle_left_type = kp.handle_right_type = "AUTO"
        elif kind == "SOFT":
            kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
        else:
            if kind in ("EASE_IN", "EASE_EASE"):
                kp.handle_left_type = "FREE"
                kp.handle_left = (kp.handle_left[0], kp.co.y)
            if kind in ("EASE_OUT", "EASE_EASE"):
                kp.handle_right_type = "FREE"
                kp.handle_right = (kp.handle_right[0], kp.co.y)
    update(context, {p[0] for p in points})


def tangents(context, kind, points):
    """AUTO, AUTO_CLAMPED, FREE (broken), FLAT (no angle) or ZERO (no length)."""
    for _fc, kp in points:
        kp.interpolation = "BEZIER"
        kp.handle_left_type = kp.handle_right_type = kind if kind in ("AUTO", "AUTO_CLAMPED") else "FREE"
        if kind == "FLAT":
            kp.handle_left = (kp.handle_left[0], kp.co.y)
            kp.handle_right = (kp.handle_right[0], kp.co.y)
        elif kind == "ZERO":
            kp.handle_left = tuple(kp.co)
            kp.handle_right = tuple(kp.co)
    update(context, {p[0] for p in points})


# --- recording ---------------------------------------------------------------------------------------------------------
CHANNELS = (("pos", "Position", "CON_LOCLIKE"), ("rot", "Rotation", "CON_ROTLIKE"), ("scl", "Scale", "CON_SIZELIKE"),
            ("param", "Parameter", "PROPERTIES"))
SETS = {(1, 0, 0): "Location", (0, 1, 0): "Rotation", (0, 0, 1): "Scaling", (1, 1, 0): "BUILTIN_KSI_LocRot",
        (1, 0, 1): "LocScale", (0, 1, 1): "RotScale", (1, 1, 1): "LocRotScale"}
_kept = {}                   # what Autokeying's settings were before Blenda changed them


def apply_channels(context):
    """Autokeying keys the switched-on channels: Blender's Only Insert Keying Set, with the set for them."""
    wm, ts, sc = context.window_manager, context.tool_settings, context.scene
    _kept.setdefault(ts.id_data.name, ts.use_keyframe_insert_keyingset)
    names = {SETS.get((int(wm.b4d_rec_pos), int(wm.b4d_rec_rot), int(wm.b4d_rec_scl)), "")}
    names |= {n.replace("BUILTIN_KSI_", "") for n in names}
    found = next((k for k in sc.keying_sets_all if k.bl_idname in names or k.bl_idname.replace("BUILTIN_KSI_", "") in names), None)
    if found is not None and not wm.b4d_rec_param:
        sc.keying_sets_all.active = found
    ts.use_keyframe_insert_keyingset = found is not None and not wm.b4d_rec_param


def record(context, frame=None):
    """A key for each switched-on channel of the selected objects. How many were made."""
    new_token()
    wm = context.window_manager
    f = context.scene.frame_current if frame is None else frame
    n = 0
    for ob in objects(context):
        rot = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(ob.rotation_mode, "rotation_euler")
        for on, path in ((wm.b4d_rec_pos, "location"), (wm.b4d_rec_rot, rot), (wm.b4d_rec_scl, "scale")):
            if on:
                try:
                    n += bool(ob.keyframe_insert(path, frame=f))
                except (RuntimeError, TypeError):
                    pass
    update(context)
    return n


# --- the range the timeline shows ---------------------------------------------------------------------------------------
def view_range(scene):
    a, b = scene.frame_preview_start, scene.frame_preview_end
    if b <= a:
        a, b = scene.frame_start, scene.frame_end
    return a, max(a + 1, b)


def set_view_range(scene, a, b):
    a, b = int(round(a)), int(round(b))
    a = max(scene.frame_start, min(a, scene.frame_end - 1))
    scene.frame_preview_start, scene.frame_preview_end = a, min(scene.frame_end, max(b, a + 1))


def step_for(px_per_frame, least):
    for st in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if st * px_per_frame >= least:
            return st
    return 10000


# --- drawing --------------------------------------------------------------------------------------------------------------
def rect(x0, y0, x1, y1, color):
    from . import strip
    import gpu
    gpu.state.blend_set("ALPHA")
    strip._rect(x0, y0, x1, y1, color)


def lines(pts, color, width=1.0):
    if not pts:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    sh = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(sh, "LINES", {"pos": [(p[0], p[1], 0.0) for p in pts]})
    gpu.state.blend_set("ALPHA")
    sh.bind()
    sh.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    sh.uniform_float("lineWidth", width)
    sh.uniform_float("color", color)
    batch.draw(sh)


def polyline(pts, color, width=1.5):
    if len(pts) < 2:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    sh = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(sh, "LINE_STRIP", {"pos": [(p[0], p[1], 0.0) for p in pts]})
    gpu.state.blend_set("ALPHA")
    sh.bind()
    sh.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    sh.uniform_float("lineWidth", width)
    sh.uniform_float("color", color)
    batch.draw(sh)


def tris(pts, color):
    import gpu
    from gpu_extras.batch import batch_for_shader
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(sh, "TRIS", {"pos": pts})
    gpu.state.blend_set("ALPHA")
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def text_width(text, size):
    import blf
    blf.size(0, size)
    return blf.dimensions(0, text)[0]


def text(x, y, s, color, size, align="LEFT", room=None):
    """Draw s; with `room` (pixels) a text that is too long ends in an ellipsis."""
    import blf
    blf.size(0, size)
    if room is not None and blf.dimensions(0, s)[0] > room:
        while s and blf.dimensions(0, s + "…")[0] > room:
            s = s[:-1]
        s = s + "…" if s else ""
    w = blf.dimensions(0, s)[0]
    x -= w / 2 if align == "CENTER" else w if align == "RIGHT" else 0
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, s)
    return w


def redraw():
    from . import roles
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type in {"VIEW_3D", "DOPESHEET_EDITOR", "GRAPH_EDITOR"} or \
                    roles.role(a) in {"TIMELINE", "TL_BAR", "TL_EDIT", "ATTRIBUTES"}:
                a.tag_redraw()


def register():
    W = bpy.types.WindowManager
    for ch, label, _icon in CHANNELS:
        setattr(W, f"b4d_rec_{ch}", bpy.props.BoolProperty(
            name=label, default=ch != "param", update=lambda self, context: apply_channels(context),
            description=("Record and Autokeying key every setting you change" if ch == "param"
                         else f"Record and Autokeying key the {label.lower()}")))


def unregister():
    for sc in bpy.data.scenes:
        if sc.name in _kept:
            sc.tool_settings.use_keyframe_insert_keyingset = _kept[sc.name]
    _kept.clear()
    _owner.clear()
    for ch, _l, _i in CHANNELS:
        delattr(bpy.types.WindowManager, f"b4d_rec_{ch}")
