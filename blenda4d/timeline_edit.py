# SPDX-License-Identifier: GPL-3.0-or-later
"""The Timeline above the strip: its bar (menus and tools) and, under it, the Dope Sheet or the F-Curves, drawn over
Blender's own keys. Both share the list at the left: Summary, the objects, a folder for each vector (Position, Rotation,
Scale) and a track per channel, with a switch for each row's animation. The list's edge can be dragged.

Dope Sheet: click a key (Shift: from the last one to here, Ctrl: add or take away), drag over empty space for a box,
drag a key to move what is selected, drag the bar under the ruler or its ends to move or scale the selected keys (Alt:
about the middle). Ctrl at the end of a drag leaves the originals; Ctrl+click on a row makes a key.
F-Curves: the curves of the tracks picked in the list, else of every object shown. Drag keys (Shift: one direction),
drag a tangent's end (Shift breaks it, Ctrl keeps its angle, Alt its length); Ctrl+click on a curve makes a key.
Both: middle drag pans, the wheel scrolls or zooms, Alt+right drag zooms."""
import math

import bpy
from mathutils import Vector

from . import anim as A, menus, roles, timeline as T
from .timeline_pages import scale_of

ROLE, BAR = "TL_EDIT", "TL_BAR"
BAR_PX = 64
RULER, ROW, STATUS, VALUES = 34, 18, 18, 48
LIST, LIST_MIN = 190, 90
ROW_MASTER = (0.23, 0.23, 0.23, 1.0)
ROW_OTHER = (0.215, 0.215, 0.23, 1.0)
AXIS_ROW = {0: (0.33, 0.19, 0.19, 1.0), 1: (0.18, 0.29, 0.19, 1.0), 2: (0.18, 0.23, 0.35, 1.0)}
AXIS_LINE = {0: (0.90, 0.33, 0.32, 1.0), 1: (0.45, 0.80, 0.40, 1.0), 2: (0.40, 0.58, 0.95, 1.0)}
OTHER_LINE = (0.82, 0.80, 0.56, 1.0)
ROW_SEL = (0.294, 0.294, 0.427, 1.0)
OBJECT = (0.91, 0.70, 0.36, 1.0)
HANDLE = (0.86, 0.86, 0.86, 0.9)
FOLDERS = {"location": "Position", "rotation_euler": "Rotation", "rotation_quaternion": "Rotation",
           "rotation_axis_angle": "Rotation", "scale": "Scale", "delta_location": "Delta Position",
           "delta_rotation_euler": "Delta Rotation", "delta_scale": "Delta Scale"}

_state = {}                  # (area, mode) -> {"view", "scroll", ...}
_folded, _picked = set(), set()
_clip = []                   # copied keys: (track key, frames from the first, value, handles ...)
_handles = []
_keymaps = []


# --- which mode, which objects --------------------------------------------------------------------------------------------
def mode(workspace):
    return "CURVES" if workspace is not None and workspace.get("b4d_tl_mode") == "CURVES" else "KEYS"


def set_mode(workspace, value):
    workspace["b4d_tl_mode"] = value
    A.redraw()


def only_selected(scene):
    return bool(scene.get("b4d_tl_only_selected", True))


def shown_objects(context):
    obs = A.objects(context) if only_selected(context.scene) else list(context.scene.objects)
    return sorted((ob for ob in obs if A.all_of(ob)), key=lambda o: o.name)


def all_curves(context):
    seen, out = set(), []
    for ob in shown_objects(context):
        for fc in A.all_of(ob):
            if fc.as_pointer() not in seen:
                seen.add(fc.as_pointer())
                out.append(fc)
    return out


def track_key(fc):
    block = A.owner_of(fc)
    return f"{type(block).__name__}:{block.name_full if block is not None else ''}:{fc.data_path}:{fc.array_index}"


# --- the list ---------------------------------------------------------------------------------------------------------------
def _label(fc):
    """(folder, name) of a track."""
    path = fc.data_path
    folder = FOLDERS.get(path)
    if folder:
        axes = "WXYZ" if path.endswith(("quaternion", "axis_angle")) else "XYZ"
        return folder, f"{folder} . {axes[fc.array_index] if fc.array_index < len(axes) else fc.array_index}"
    for start in ('constraints["', 'modifiers["'):
        if path.startswith(start):
            folder = path[len(start):].split('"]', 1)[0]
    name, size = path.split(".")[-1].strip('[]"').replace("_", " ").title(), 0
    if ".elements[" in path:                              # a gradient's knot
        try:
            name = f"Knot {int(path.rsplit('.elements[', 1)[1].split(']', 1)[0]) + 1} {name}"
        except ValueError:
            pass
        size = 4 if path.endswith("color") else 0
    elif path.endswith("default_value") and ".inputs[" in path:
        try:
            sock = A.owner_of(fc).path_resolve(path.rsplit(".", 1)[0])
            name = sock.name
            size = len(sock.default_value) if hasattr(sock.default_value, "__len__") else 0
        except (ValueError, AttributeError, ReferenceError):
            pass
    elif path.endswith("color"):
        size = 4
    if size >= 3 and fc.array_index < 4:
        name += " . " + ("RGBA" if size == 4 or path.endswith("color") else "XYZ")[fc.array_index]
    elif fc.array_index:
        name += f" . {fc.array_index}"
    return folder, name


def track_label(fc):
    return _label(fc)[1]


def axis_of(fc):
    return fc.array_index if fc.data_path in FOLDERS and fc.array_index < 3 else None


def tree(context):
    """[(key, depth, kind, name, curves, object, axis)], what is folded left out."""
    obs = shown_objects(context)
    rows = [("summary", 0, "summary", "Summary", all_curves(context), None, None)]
    for ob in obs:
        rows.append((f"o:{ob.name}", 1, "object", ob.name, A.all_of(ob), ob, None))
        if f"o:{ob.name}" in _folded:
            continue
        groups = {}
        for source, curves in A.sources(ob):
            for fc in curves:
                folder, name = _label(fc)
                groups.setdefault(source if source is not None else folder or name, []).append((fc, name, source or folder))
        for gname, items in groups.items():
            if items[0][2]:
                fkey = f"f:{ob.name}:{gname}"
                rows.append((fkey, 2, "folder", gname, [i[0] for i in items], ob, None))
                if fkey in _folded:
                    continue
            for fc, name, _f in sorted(items, key=lambda t: t[0].array_index) if items[0][2] in FOLDERS.values() else items:
                rows.append((f"t:{ob.name}:{track_key(fc)}", 3 if items[0][2] else 2, "track", name, [fc], ob, axis_of(fc)))
    return rows


# --- geometry -----------------------------------------------------------------------------------------------------------------
def _st(area):
    return _state.setdefault((area.as_pointer(), mode(bpy.context.workspace)), {"view": None, "scroll": 0.0})


def _geom(context, area, region):
    s = context.preferences.system.ui_scale
    W, H = region.width, region.height
    lw = round(min(max(LIST_MIN * s, context.window_manager.b4d_tl_list * s), max(LIST_MIN * s, W * 0.6)))
    if W < 260 * s:
        lw = 0                                            # too narrow for the list: all keys
    left = VALUES * s if mode(context.workspace) == "CURVES" else 8 * s
    return {"s": s, "W": W, "H": H, "lw": lw, "x0": lw + left, "x1": W - 8 * s, "y0": STATUS * s, "y1": H - RULER * s}


def _keys_range(curves, selected=False):
    xs = [kp.co.x for fc in curves for kp in fc.keyframe_points if kp.select_control_point or not selected]
    return (min(xs), max(xs)) if xs else None


def frame_view(context, g, curves, selected=False):
    """The view that holds these curves' keys: (first frame, last frame, lowest value, highest value)."""
    xs, ys = [], []
    for fc in curves:
        k = scale_of(fc)
        for kp in fc.keyframe_points:
            if kp.select_control_point or not selected:
                xs.append(kp.co.x)
                ys += [kp.co.y * k]
                if kp.interpolation == "BEZIER":
                    ys += [kp.handle_left[1] * k, kp.handle_right[1] * k]
    if not xs:
        a, b = A.view_range(context.scene)
        return a, b, -100.0, 100.0
    a, b, lo, hi = min(xs), max(xs), min(ys), max(ys)
    if b - a < 1:
        a, b = a - 5, b + 5
    if hi - lo < 1e-3:
        lo, hi = lo - 10, hi + 10
    return a - (b - a) * 0.06, b + (b - a) * 0.06, lo - (hi - lo) * 0.14, hi + (hi - lo) * 0.14


def to_x(g, f):
    return g["x0"] + (f - g["view"][0]) / max(1e-9, g["view"][1] - g["view"][0]) * (g["x1"] - g["x0"])


def to_f(g, x):
    return g["view"][0] + (x - g["x0"]) / max(1.0, g["x1"] - g["x0"]) * (g["view"][1] - g["view"][0])


def to_y(g, v):
    return g["y0"] + (v - g["view"][2]) / max(1e-9, g["view"][3] - g["view"][2]) * (g["y1"] - g["y0"])


def to_v(g, y):
    return g["view"][2] + (y - g["y0"]) / max(1.0, g["y1"] - g["y0"]) * (g["view"][3] - g["view"][2])


def _row_span(g, i):
    y1 = g["y1"] + g["scroll"] - i * ROW * g["s"]
    return y1 - ROW * g["s"], y1


def _row_at(g, y):
    if not g["y0"] <= y < g["y1"]:
        return None
    i = int((g["y1"] + g["scroll"] - y) // (ROW * g["s"]))
    return i if 0 <= i < len(g["rows"]) else None


def _most_scroll(g):
    return max(0.0, len(g["rows"]) * ROW * g["s"] - (g["y1"] - g["y0"]))


# --- drawing --------------------------------------------------------------------------------------------------------------------
def _draw():
    context = bpy.context
    area, region = context.area, context.region
    if region is None or roles.role(area) != ROLE:
        return
    import gpu
    g = _geom(context, area, region)
    st = _st(area)
    curves_mode = mode(context.workspace) == "CURVES"
    g["rows"] = tree(context)
    shown = _shown(context, g["rows"])
    st["curves"] = shown if curves_mode else all_curves(context)
    if curves_mode:
        ids = tuple(track_key(fc) for fc in shown)
        if st["view"] is None or st.get("ids") != ids:    # other curves now: show all of them
            st["ids"], st["view"] = ids, frame_view(context, g, shown)
    elif st["view"] is None:
        a, b = A.view_range(context.scene)
        pad = max(2, (b - a) * 0.04)
        st["view"] = (a - pad, b + pad, 0.0, 1.0)
    st["scroll"] = min(max(0.0, st["scroll"]), _most_scroll(g))
    g["view"], g["scroll"] = st["view"], st["scroll"]
    st["geom"] = g
    A.rect(0, 0, g["W"], g["H"], A.BG)
    if curves_mode:
        _draw_curves(context, g, st)
    else:
        _draw_keys(context, g, st)
    box = st.get("box")
    if box:
        x0, x1, y0, y1 = min(box[0], box[2]), max(box[0], box[2]), min(box[1], box[3]), max(box[1], box[3])
        A.rect(x0, y0, x1, y1, (1, 1, 1, 0.07))
        A.lines([(x0, y0), (x1, y0), (x1, y0), (x1, y1), (x1, y1), (x0, y1), (x0, y1), (x0, y0)], (1, 1, 1, 0.4))
    _draw_list(context, g)
    _draw_ruler(context, g, curves_mode)
    _draw_status(context, g)
    gpu.state.blend_set("NONE")
    from . import strip, toolcol                          # the columns beside it: their tooltips lie over it
    toolcol._draw_tip()
    strip._draw_tip()


def _grid_frames(g, least=40):
    a, b = g["view"][:2]
    step = A.step_for((g["x1"] - g["x0"]) / max(1e-9, b - a), least * g["s"])
    f = math.ceil(a / step) * step
    while f <= b:
        yield f
        f += step


def _outside(context, g):
    """The frames before and after the preview range are darker."""
    a, b = A.view_range(context.scene)
    for x0, x1 in ((g["lw"], to_x(g, a)), (to_x(g, b), g["W"])):
        x0, x1 = max(g["lw"], x0), min(g["W"], x1)
        if x1 > x0:
            A.rect(x0, g["y0"], x1, g["y1"], (0, 0, 0, 0.16))


def _square(x, y, r, color, filled=True):
    if filled:
        A.rect(x - r, y - r, x + r, y + r, color)
    else:
        A.lines([(x - r, y - r), (x + r, y - r), (x + r, y - r), (x + r, y + r), (x + r, y + r), (x - r, y + r),
                 (x - r, y + r), (x - r, y - r)], color)


def _visible(g):
    for i, row in enumerate(g["rows"]):
        y0, y1 = _row_span(g, i)
        if y1 > g["y0"] and y0 < g["y1"]:
            yield i, row, y0, y1


def _draw_keys(context, g, st):
    s = g["s"]
    for _i, row, y0, y1 in _visible(g):
        A.rect(g["lw"], y0 + 1, g["W"], y1 - 1, ROW_MASTER if row[2] != "track" else AXIS_ROW.get(row[6], ROW_OTHER))
    A.lines([p for f in _grid_frames(g) for p in ((to_x(g, f), g["y0"]), (to_x(g, f), g["y1"]))], (0, 0, 0, 0.25))
    a, b = g["view"][:2]
    ppf = to_x(g, 1) - to_x(g, 0)
    for _i, row, y0, y1 in _visible(g):
        found = {}
        for fc in row[4]:
            for kp in fc.keyframe_points:
                f = round(kp.co.x)
                n, t = found.get(f, (0, 0))
                found[f] = (n + bool(kp.select_control_point), t + 1)
        ym = (y0 + y1) / 2
        for f, (n, t) in sorted(found.items()):
            if not a - 1 <= f <= b + 1:
                continue
            x = to_x(g, f)
            if row[2] == "track":
                r = max(2.0 * s, min(ppf * 0.5 - 0.5, 4.5 * s))
                A.rect(x - r, y0 + 3 * s, x + r, y1 - 3 * s, A.KEY_SEL if n else A.KEY)
            else:
                _square(x, ym, max(3 * s, min(4.5 * s, ppf * 0.5)), A.KEY_SEL if n == t else A.KEY_PART if n else A.KEY, False)
    _outside(context, g)


def _shown(context, rows):
    """The curves F-Curve Mode draws: the picked tracks', else every object's that is shown."""
    picked, seen = [], set()
    for row in rows:
        if row[0] in _picked:
            for fc in row[4]:
                if fc.as_pointer() not in seen:
                    seen.add(fc.as_pointer())
                    picked.append(fc)
    return picked or all_curves(context)


def line_color(fc):
    axis = axis_of(fc)
    if axis is not None:
        return AXIS_LINE[axis]
    return (*fc.color, 1.0) if fc.color_mode == "CUSTOM" else OTHER_LINE


def _draw_curves(context, g, st):
    s = g["s"]
    a, b, lo, hi = g["view"]
    step = 10 ** math.floor(math.log10(max(1e-9, (hi - lo) / 4)))
    step *= next((m for m in (1, 2, 5, 10) if (hi - lo) / (step * m) <= max(2, (g["y1"] - g["y0"]) / (28 * s))), 10)
    grid, v = [], math.ceil(lo / step) * step
    marks = []
    while v <= hi:
        y = to_y(g, v)
        grid += [(g["x0"], y), (g["W"], y)]
        marks.append((y, "%g" % round(v, 6)))
        v += step
    for f in _grid_frames(g):
        grid += [(to_x(g, f), g["y0"]), (to_x(g, f), g["y1"])]
    A.lines(grid, (0.225, 0.225, 0.225, 1.0))
    if lo <= 0 <= hi:
        A.lines([(g["x0"], to_y(g, 0)), (g["W"], to_y(g, 0))], (0.08, 0.08, 0.08, 1.0))
    _outside(context, g)
    hits = []
    for fc in st["curves"]:
        col, k = line_color(fc), scale_of(fc)
        n = max(2, int(g["x1"] - g["x0"]) // 3)
        frames = sorted([a + (b - a) * i / n for i in range(n + 1)] + [kp.co.x for kp in fc.keyframe_points if a < kp.co.x < b])
        A.polyline([(to_x(g, f), to_y(g, fc.evaluate(f) * k)) for f in frames], col if not fc.mute else (*col[:3], 0.3), 1.6 * s)
        for kp in fc.keyframe_points:
            x, y = to_x(g, kp.co.x), to_y(g, kp.co.y * k)
            sel = kp.select_control_point
            if sel and kp.interpolation == "BEZIER":
                for side in ("left", "right"):
                    h = getattr(kp, "handle_" + side)
                    hx, hy = to_x(g, h[0]), to_y(g, h[1] * k)
                    A.lines([(x, y), (hx, hy)], HANDLE)
                    if broken(kp):
                        pts = [(hx + 3.2 * s * math.cos(t * math.pi / 4), hy + 3.2 * s * math.sin(t * math.pi / 4)) for t in range(8)]
                        A.tris([q for i in range(8) for q in ((hx, hy), pts[i], pts[(i + 1) % 8])], HANDLE)
                    else:
                        A.tris([(hx - 4 * s, hy - 3 * s), (hx + 4 * s, hy - 3 * s), (hx, hy + 4 * s)], HANDLE)
                    hits.append((side, fc, kp, hx, hy))
            _square(x, y, 3 * s, A.KEY_SEL if sel else (0.9, 0.9, 0.9, 1.0))
            hits.append(("key", fc, kp, x, y))
    st["hits"] = hits
    A.rect(g["lw"], g["y0"], g["x0"], g["y1"], A.BG)
    for y, label in marks:
        A.text(g["x0"] - 6 * s, y - 4 * s, label, A.DIM, 10 * s, "RIGHT")


def broken(kp):
    return kp.handle_left_type in {"FREE", "VECTOR"} or kp.handle_right_type in {"FREE", "VECTOR"}


def _draw_list(context, g):
    s, lw = g["s"], g["lw"]
    if not lw:
        return
    A.rect(0, g["y0"], lw, g["y1"], (0.185, 0.185, 0.185, 1.0))
    for _i, row, y0, y1 in _visible(g):
        key, depth, kind, name, curves, _ob, axis = row
        if key in _picked:
            A.rect(0, y0 + 1, lw, y1 - 1, ROW_SEL)
        x = 8 * s + depth * 12 * s
        ym = (y0 + y1) / 2
        if kind in {"object", "folder"}:
            cx = x + 3.5 * s
            _square(cx, ym, 3.5 * s, A.DIM, False)
            A.lines([(cx - 2 * s, ym), (cx + 2 * s, ym)] + ([(cx, ym - 2 * s), (cx, ym + 2 * s)] if key in _folded else []), A.TEXT)
        muted = bool(curves) and all(fc.mute for fc in curves)
        color = OBJECT if kind == "object" else AXIS_LINE.get(axis, A.TEXT) if kind == "track" else A.TEXT
        A.text(x + 13 * s, ym - 4 * s, name, color if not muted else A.DIM, 11 * s, room=lw - x - 34 * s)
        if curves:
            _square(lw - 12 * s, ym, 3.5 * s, A.DIM if muted else A.TEXT, not muted)
    A.rect(lw - 1, g["y0"], lw, g["H"], A.EDGE)


def _draw_ruler(context, g, curves_mode):
    s, lw, sc = g["s"], g["lw"], context.scene
    y0, y1 = g["y1"], g["H"]
    ymid = y0 + (y1 - y0) * (0.0 if curves_mode else 0.42)
    A.rect(0, y0, g["W"], y1, A.BAND)
    if lw:
        A.text(10 * s, y0 + (y1 - y0) / 2 - 4 * s, "F-Curve Mode" if curves_mode else "Dope Sheet", A.DIM, 11 * s, room=lw - 16 * s)
    ty = ymid + (12 if curves_mode else 6) * s
    marks = []
    for f in _grid_frames(g):
        x = to_x(g, f)
        marks += [(x, ymid), (x, ymid + 4 * s)]
        A.text(x, ty, str(int(f)), A.DIM, 10 * s, "CENTER")
    A.lines(marks, A.TICK)
    g["range"] = None
    if not curves_mode:
        sel = _keys_range(all_curves(context), True)
        if sel and round(sel[1]) > round(sel[0]):
            a, b = round(sel[0]), round(sel[1])
            xa, xb = max(lw, to_x(g, a)), to_x(g, b)
            A.rect(xa, y0 + 2 * s, xb, ymid - 2 * s, A.RANGE)
            for x in (to_x(g, a), xb):
                if x >= lw:
                    A.rect(x - 2 * s, y0 + 2 * s, x + 2 * s, ymid - 2 * s, A.RANGE_EDGE)
            g["range"] = (to_x(g, a), xb, a, b)
    for m in sc.timeline_markers:
        x = to_x(g, m.frame)
        if lw <= x <= g["W"]:
            A.tris([(x, y1 - 8 * s), (x - 4 * s, y1 - 1 * s), (x + 4 * s, y1 - 1 * s)], A.KEY_SEL if m.select else A.KEY)
    g["ymid"] = ymid
    x = to_x(g, sc.frame_current)
    if lw <= x <= g["W"]:
        w = A.text_width(str(sc.frame_current), 10 * s) + 8 * s
        A.rect(x - 0.7 * s, g["y0"], x + 0.7 * s, ty, A.NOW)
        A.rect(x - w / 2, ty - 5 * s, x + w / 2, ty + 12 * s, A.NOW)
        A.text(x, ty, str(sc.frame_current), (1, 1, 1, 1), 10 * s, "CENTER")


def _draw_status(context, g):
    s, sc = g["s"], context.scene
    A.rect(0, 0, g["W"], STATUS * s, A.DARK)
    a, b = A.view_range(sc)
    parts = [f"Current Frame  {sc.frame_current}", f"Preview  {a} to {b}"]
    sel = _keys_range(all_curves(context), True)
    if sel:
        parts.append(f"Selection  {round(sel[0])} to {round(sel[1])}")
    A.text(8 * s, 5 * s, "     ".join(parts), A.DIM, 10.5 * s, room=g["W"] - 16 * s)


# --- input --------------------------------------------------------------------------------------------------------------------------
def _deselect(context):
    for fc in all_curves(context):
        for kp in fc.keyframe_points:
            A.set_selected(kp, False)


class BLENDA4D_OT_tl_edit(bpy.types.Operator):
    bl_idname = "blenda4d.tl_edit"
    bl_label = "Timeline"
    bl_description = "Select and move keys in the Timeline"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == ROLE

    def invoke(self, context, event):
        self.st = _st(context.area)
        g = self.g = self.st.get("geom")
        if g is None:
            return {"PASS_THROUGH"}
        x, y = self.x0, self.y0 = event.mouse_region_x, event.mouse_region_y
        self.moved, self.saved, self.what = False, [], None
        self.curves_mode = mode(context.workspace) == "CURVES"
        ctrl = event.ctrl or event.oskey
        self.view0, self.scroll0 = g["view"], g["scroll"]
        done = None
        if event.type == "RIGHTMOUSE" and not event.alt:
            bpy.ops.wm.call_menu(name="BLENDA4D_MT_tl_context")
            return {"FINISHED"}
        if event.type == "RIGHTMOUSE":
            self.what, self.f0, self.v0 = "zoom", to_f(g, x), to_v(g, y)
        elif event.type == "MIDDLEMOUSE":
            self.what = "pan"
        elif g["lw"] and abs(x - g["lw"]) <= 4 * g["s"]:
            self.what = "divider"
        elif y >= g["y1"]:
            done = self._ruler(context, event, x, y, ctrl)
        elif x < g["lw"]:
            done = self._list(context, event, x, y, ctrl)
        elif self.curves_mode:
            done = self._curves(context, event, x, y, ctrl)
        else:
            done = self._keys(context, event, x, y, ctrl)
        if done:
            A.redraw()
            return {"FINISHED"}
        self.token = A.new_token()
        context.window_manager.modal_handler_add(self)
        A.redraw()
        return {"RUNNING_MODAL"}

    # each returns True when the press is all there is to it
    def _ruler(self, context, event, x, y, ctrl):
        g = self.g
        if y >= g["ymid"]:
            if ctrl:
                f = round(to_f(g, x))
                context.scene.timeline_markers.new(f"F_{f}", frame=f)
                A.push("Add Marker")
                return True
            self.what = "scrub"
            self._scrub(context, event, x)
            return False
        rng, r = g["range"], 6 * g["s"]
        self.f_start = to_f(g, x)
        if rng and min(abs(x - rng[0]), abs(x - rng[1])) <= r:
            first = abs(x - rng[0]) <= abs(x - rng[1])
            self.what, self.fixed, self.grabbed = "scale", rng[3] if first else rng[2], rng[2] if first else rng[3]
        elif rng and rng[0] < x < rng[1]:
            self.what = "move"
        else:
            self.what = "range"
        self.ends = (rng[2], rng[3]) if rng else None
        self.saved = A.remember(A.selected_points(context, all_curves(context)))
        return False

    def _list(self, context, event, x, y, ctrl):
        g, i = self.g, _row_at(self.g, y)
        if i is None:
            if not (ctrl or event.shift):
                _picked.clear()
            return True
        key, depth, kind, _name, curves, ob, _axis = g["rows"][i]
        s = g["s"]
        if x >= g["lw"] - 22 * s and curves:              # its animation, on or off
            off = not all(fc.mute for fc in curves)
            for fc in curves:
                fc.mute = off
            A.refresh(context)
            A.push("Animation On/Off")
            return True
        left = 8 * s + depth * 12 * s
        if kind in {"object", "folder"} and left - 3 * s <= x <= left + 11 * s:
            _folded.symmetric_difference_update({key})
            return True
        add = ctrl or event.shift
        if not add:
            _picked.clear()
            _deselect(context)
        if ctrl and key in _picked:
            _picked.discard(key)
        else:
            _picked.add(key)
            for fc in curves:
                for kp in fc.keyframe_points:
                    A.set_selected(kp, True)
        if kind == "track":
            from . import timeline_pages
            timeline_pages.show("TRACK", curves[0])
        return True

    def _start_move(self, context, x, y):
        self.what, self.f_start = "move", to_f(self.g, x)
        self.ends = None
        self.saved = A.remember(A.selected_points(context, self.st["curves"]))

    def _keys(self, context, event, x, y, ctrl):
        g, i = self.g, _row_at(self.g, y)
        hit = None
        if i is not None:
            near = min(((abs(to_x(g, kp.co.x) - x), round(kp.co.x)) for fc in g["rows"][i][4] for kp in fc.keyframe_points), default=None)
            if near and near[0] <= max(5 * g["s"], min(10 * g["s"], (to_x(g, 1) - to_x(g, 0)) / 2)):
                hit = near[1]
        if hit is None:
            if ctrl and i is not None and g["rows"][i][4]:
                f = round(to_f(g, x))
                A.new_token()
                for fc in g["rows"][i][4]:
                    A.add_key(fc, f)
                A.update(context, g["rows"][i][4])
                A.push("Add Keys")
                return True
            if not (event.shift or ctrl):
                _deselect(context)
            self.what = "box"
            return False
        points = [(fc, kp) for fc in g["rows"][i][4] for kp in fc.keyframe_points if round(kp.co.x) == hit]
        every = all(kp.select_control_point for _fc, kp in points)
        if ctrl:
            for _fc, kp in points:
                A.set_selected(kp, not every)
            return True
        if event.shift and self.st.get("anchor"):
            (i0, f0), rows = self.st["anchor"], g["rows"]
            for row in rows[min(i0, i):max(i0, i) + 1]:
                for fc in row[4]:
                    for kp in fc.keyframe_points:
                        if min(f0, hit) - 0.5 <= kp.co.x <= max(f0, hit) + 0.5:
                            A.set_selected(kp, True)
            return True
        if not every:
            _deselect(context)
            for _fc, kp in points:
                A.set_selected(kp, True)
        from . import timeline_pages
        timeline_pages.show("KEY", *points[0])
        self.st["anchor"] = (i, hit)
        self._start_move(context, x, y)
        return False

    def _curves(self, context, event, x, y, ctrl):
        g, r = self.g, 7 * self.g["s"]
        near = sorted(((h[0] == "key", abs(h[3] - x) + abs(h[4] - y), n) for n, h in enumerate(self.st.get("hits", ()))
                       if abs(h[3] - x) <= r and abs(h[4] - y) <= r))
        if near:
            kind, fc, kp, _hx, _hy = self.st["hits"][near[0][2]]
            if kind != "key":
                self.what, self.side, self.fc, self.kp = "tangent", kind, fc, kp
                self.old = (Vector(kp.handle_left), Vector(kp.handle_right), kp.handle_left_type, kp.handle_right_type)
                return False
            if ctrl or event.shift:
                A.set_selected(kp, not kp.select_control_point)
                return True
            if not kp.select_control_point:
                _deselect(context)
                A.set_selected(kp, True)
            from . import timeline_pages
            timeline_pages.show("KEY", fc, kp)
            self._start_move(context, x, y)
            return False
        if ctrl:
            f = round(to_f(g, x))
            best = min(((abs(to_y(g, fc.evaluate(to_f(g, x)) * scale_of(fc)) - y), n) for n, fc in enumerate(self.st["curves"])), default=None)
            if best and best[0] <= 9 * g["s"]:
                fc = self.st["curves"][best[1]]
                A.new_token()
                A.add_key(fc, f)
                A.update(context, {fc})
                A.push("Add Key")
            return True
        if not event.shift:
            _deselect(context)
        self.what = "box"
        return False

    def _scrub(self, context, event, x):
        f = round(to_f(self.g, x))
        if event.shift:
            f = min({round(kp.co.x) for fc in all_curves(context) for kp in fc.keyframe_points}, key=lambda k: abs(k - f), default=f)
        context.scene.frame_current = f

    def modal(self, context, event):
        if self.token != A.token():
            self.st.pop("box", None)
            return {"CANCELLED"}
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            x, y = event.mouse_region_x, event.mouse_region_y
            self.moved = self.moved or abs(x - self.x0) > 2 or abs(y - self.y0) > 2
            if self.moved or self.what == "scrub":
                self._drag(context, event, x, y)
            A.redraw()
            return {"RUNNING_MODAL"}
        ends = {"LEFTMOUSE", "MIDDLEMOUSE"} | ({"RIGHTMOUSE"} if self.what == "zoom" else set())
        if event.type in ends and event.value == "RELEASE":
            self._release(context, event)
            A.redraw()
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cancel(context)
            A.redraw()
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _drag(self, context, event, x, y):
        g, w = self.g, self.what
        a, b, lo, hi = self.view0
        if w == "scrub":
            self._scrub(context, event, x)
        elif w == "divider":
            context.window_manager.b4d_tl_list = max(LIST_MIN, x / g["s"])
        elif w == "pan":
            d = (x - self.x0) / max(1.0, g["x1"] - g["x0"]) * (b - a)
            v = (y - self.y0) / max(1.0, g["y1"] - g["y0"]) * (hi - lo) if self.curves_mode else 0.0
            self.st["view"] = (a - d, b - d, lo - v, hi - v)
            if not self.curves_mode:
                self.st["scroll"] = min(_most_scroll(g), max(0.0, self.scroll0 + (y - self.y0)))
        elif w == "zoom":
            kx, ky = 0.995 ** (x - self.x0), 0.995 ** (y - self.y0) if self.curves_mode else 1.0
            self.st["view"] = (self.f0 - (self.f0 - a) * kx, self.f0 + (b - self.f0) * kx,
                               self.v0 - (self.v0 - lo) * ky, self.v0 + (hi - self.v0) * ky)
        elif w == "box":
            self.st["box"] = (self.x0, self.y0, x, y)
        elif w == "range":
            fa, fb = sorted((self.f_start, to_f(g, x)))
            for fc in all_curves(context):
                for kp in fc.keyframe_points:
                    A.set_selected(kp, fa - 0.5 <= kp.co.x <= fb + 0.5)
        elif w == "scale":
            f = to_f(g, x)
            pivot = sum(self.ends) / 2 if event.alt else self.fixed
            k = (f - pivot) / ((self.grabbed - pivot) or 1e-6)
            A.retime(context, self.saved, lambda t: pivot + (t - pivot) * k)
        elif w == "move" and not self.curves_mode:
            d = round(to_f(g, x) - self.f_start)
            A.retime(context, self.saved, lambda t: t + d)
        elif w == "move":
            d, v = round(to_f(g, x) - self.f_start), to_v(g, y) - to_v(g, self.y0)
            if event.shift:
                d, v = (d, 0.0) if abs(x - self.x0) > abs(y - self.y0) else (0, v)
            for fc, kp, kx, ky, hl, hr, *_rest in self.saved:
                dv = v / scale_of(fc)
                kp.co = (kx + d, ky + dv)
                kp.handle_left = (hl[0] + d, hl[1] + dv)
                kp.handle_right = (hr[0] + d, hr[1] + dv)
            A.refresh(context)
        elif w == "tangent":
            self._tangent(context, event, x, y)

    def _tangent(self, context, event, x, y):
        kp, g, k = self.kp, self.g, scale_of(self.fc)
        # on screen, so that an angle is the angle you see
        ax = (g["x1"] - g["x0"]) / max(1e-9, g["view"][1] - g["view"][0])
        ay = (g["y1"] - g["y0"]) / max(1e-9, g["view"][3] - g["view"][2]) * k
        co = Vector(kp.co)

        def out(v):
            return Vector(((v.x - co.x) * ax, (v.y - co.y) * ay))

        def back(v):
            return co + Vector((v.x / ax, v.y / ay))
        left = self.side == "left"
        mine, other = out(self.old[0 if left else 1]), out(self.old[1 if left else 0])
        new = Vector((x - to_x(g, co.x), y - to_y(g, co.y * k)))
        if (event.ctrl or event.oskey) and mine.length > 1e-6:
            new = mine.normalized() * new.length
        elif event.alt and new.length > 1e-6:
            new = new.normalized() * mine.length
        new.x = min(0.0, new.x) if left else max(0.0, new.x)
        apart = event.shift or self.old[2] in {"FREE", "VECTOR"} or self.old[3] in {"FREE", "VECTOR"}
        kp.handle_left_type = kp.handle_right_type = "FREE" if apart else "ALIGNED"
        setattr(kp, "handle_" + self.side, back(new))
        if not apart and new.length > 1e-6:
            setattr(kp, "handle_right" if left else "handle_left", back(-new.normalized() * other.length))
        A.refresh(context)

    def _release(self, context, event):
        g, w = self.g, self.what
        box = self.st.pop("box", None)
        ctrl = event.ctrl or event.oskey
        if w == "box" and box:
            x0, x1, y0, y1 = min(box[0], box[2]), max(box[0], box[2]), min(box[1], box[3]), max(box[1], box[3])
            if self.curves_mode:
                for kind, _fc, kp, hx, hy in self.st.get("hits", ()):
                    if kind == "key" and x0 <= hx <= x1 and y0 <= hy <= y1:
                        A.set_selected(kp, not ctrl)
            else:
                fa, fb = to_f(g, x0), to_f(g, x1)
                for i, row in enumerate(g["rows"]):
                    r0, r1 = _row_span(g, i)
                    if r1 >= y0 and r0 <= y1:
                        for fc in row[4]:
                            for kp in fc.keyframe_points:
                                if fa <= kp.co.x <= fb:
                                    A.set_selected(kp, not ctrl)
        elif w in {"move", "scale"} and self.moved and self.saved:
            if ctrl:
                A.keep_copies(self.saved)
            else:
                A.drop_overlaid(self.saved)
            A.update(context, {t[0] for t in self.saved})
            A.push("Scale Keys" if w == "scale" else "Move Keys")
        elif w == "tangent" and self.moved:
            A.update(context, {self.fc})
            A.push("Edit Tangent")

    def _cancel(self, context):
        self.st.pop("box", None)
        if self.what in {"move", "scale"}:
            for _fc, kp, kx, ky, hl, hr, *_rest in self.saved:
                kp.co, kp.handle_left, kp.handle_right = (kx, ky), hl, hr
            A.refresh(context)
        elif self.what == "tangent":
            kp = self.kp
            kp.handle_left_type, kp.handle_right_type = self.old[2], self.old[3]
            kp.handle_left, kp.handle_right = self.old[0], self.old[1]
            A.refresh(context)
        elif self.what in {"pan", "zoom"}:
            self.st["view"], self.st["scroll"] = self.view0, self.scroll0


class BLENDA4D_OT_tl_wheel(bpy.types.Operator):
    bl_idname = "blenda4d.tl_wheel"
    bl_label = "Timeline wheel"
    bl_description = "Scroll the Dope Sheet (Ctrl: zoom), or zoom the F-Curves (Shift: values, Ctrl: time)"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == ROLE

    def invoke(self, context, event):
        st = _st(context.area)
        g = st.get("geom")
        if g is None:
            return {"PASS_THROUGH"}
        a, b, lo, hi = g["view"]
        up = event.type == "WHEELUPMOUSE"
        ctrl = event.ctrl or event.oskey
        if event.type == "TRACKPADPAN":
            dx, dy = event.mouse_x - event.mouse_prev_x, event.mouse_y - event.mouse_prev_y
            d = dx / max(1.0, g["x1"] - g["x0"]) * (b - a)
            v = dy / max(1.0, g["y1"] - g["y0"]) * (hi - lo) if mode(context.workspace) == "CURVES" else 0.0
            st["view"] = (a - d, b - d, lo - v, hi - v)
            if mode(context.workspace) != "CURVES":
                st["scroll"] = min(_most_scroll(g), max(0.0, st["scroll"] + dy))
        elif event.mouse_region_x < g["lw"] or (mode(context.workspace) == "KEYS" and not ctrl):
            st["scroll"] = min(_most_scroll(g), max(0.0, st["scroll"] + ROW * g["s"] * (-1 if up else 1)))
        else:
            f, v = to_f(g, event.mouse_region_x), to_v(g, event.mouse_region_y)
            k = 0.87 if up else 1 / 0.87
            kx = 1.0 if event.shift else k
            ky = 1.0 if ctrl or mode(context.workspace) == "KEYS" else k
            st["view"] = (f - (f - a) * kx, f + (b - f) * kx, v - (v - lo) * ky, v + (hi - v) * ky)
        A.redraw()
        return {"FINISHED"}


# --- commands: the bar's menus and tools, and their keys -------------------------------------------------------------------------
def _edit_area(context):
    return next(iter(roles.areas(context.screen, ROLE)), None)


class BLENDA4D_OT_tl_command(bpy.types.Operator):
    bl_idname = "blenda4d.tl_command"
    bl_label = "Timeline Command"
    bl_options = {"INTERNAL"}
    what: bpy.props.StringProperty()
    TIPS = {"KEYS": "Show the keys (Dope Sheet)", "CURVES": "Show the curves (Graph Editor)", "TOGGLE": "Switch between the Dope Sheet and the F-Curves",
            "ONLY": "Show only the selected objects' tracks", "ALL": "Show every key", "SELECTED": "Show the selected keys",
            "CURRENT": "Bring the current frame into view", "PREVIEW": "Show the preview range", "DELETE": "Delete the selected keys",
            "SELECT_ALL": "Select every key that is shown", "SELECT_NONE": "Deselect all keys", "INVERT": "Select the keys that are not selected",
            "COPY": "Copy the selected keys", "CUT": "Cut the selected keys", "PASTE": "Paste the copied keys at the current frame",
            "CLEAN": "Remove keys that change nothing (Clean Keyframes)", "UNUSED": "Remove tracks that never change",
            "REVERSE": "Turn the selected keys around in time", "SNAP": "Put the selected keys on whole frames",
            "MARKER": "Make a marker at the current frame", "MARKERS_DELETE": "Delete all markers",
            "FOLD": "Fold every object in the list", "UNFOLD": "Unfold every object in the list",
            "PREVIEW_SEL": "Set the preview range to the selected keys", "PREVIEW_ALL": "Set the preview range to the whole scene"}

    @classmethod
    def description(cls, context, props):
        return cls.TIPS.get(props.what, cls.bl_label)

    @classmethod
    def poll(cls, context):
        return context.screen is not None and (roles.role(context.area) in {ROLE, BAR, T.ROLE})

    def execute(self, context):
        w, ws, sc = self.what, context.workspace, context.scene
        area = _edit_area(context)
        st = _st(area) if area is not None else {}
        g = st.get("geom")
        curves = all_curves(context) if area is not None else A.curves(context)
        points = A.selected_points(context, curves)
        if w in {"KEYS", "CURVES", "TOGGLE"}:
            set_mode(ws, w if w != "TOGGLE" else "KEYS" if mode(ws) == "CURVES" else "CURVES")
        elif w == "ONLY":
            sc["b4d_tl_only_selected"] = not only_selected(sc)
        elif w in {"ALL", "SELECTED"} and g:
            among = st.get("curves", curves)
            if w == "ALL" or any(kp.select_control_point for fc in among for kp in fc.keyframe_points):
                st["view"] = frame_view(context, g, among, w == "SELECTED")
        elif w in {"CURRENT", "PREVIEW"} and g:
            a, b, lo, hi = g["view"]
            fa, fb = A.view_range(sc)
            st["view"] = (sc.frame_current - (b - a) / 2, sc.frame_current + (b - a) / 2, lo, hi) if w == "CURRENT" else \
                (fa - (fb - fa) * 0.04, fb + (fb - fa) * 0.04, lo, hi)
        elif w in {"SELECT_ALL", "SELECT_NONE", "INVERT"}:
            for fc in curves:
                for kp in fc.keyframe_points:
                    A.set_selected(kp, w == "SELECT_ALL" or (w == "INVERT" and not kp.select_control_point))
            T._range.clear()
        elif w in {"COPY", "CUT"}:
            first = min((kp.co.x for _fc, kp in points), default=0.0)
            _clip[:] = [(track_key(fc), kp.co.x - first, kp.co.y, tuple(Vector(kp.handle_left) - Vector(kp.co)),
                         tuple(Vector(kp.handle_right) - Vector(kp.co)), kp.interpolation, kp.handle_left_type, kp.handle_right_type)
                        for fc, kp in points]
            if w == "CUT" and points:
                A.delete_selected(context, curves)
                A.push("Cut Keys")
        elif w == "PASTE" and _clip:
            A.new_token()
            own = {track_key(fc): fc for ob in sc.objects for fc in A.all_of(ob)}
            for fc, kp in points:
                A.set_selected(kp, False)
            done = set()
            for key, df, value, hl, hr, interp, lt, rt in _clip:
                fc = own.get(key)
                if fc is None:
                    continue
                kp = fc.keyframe_points.insert(sc.frame_current + df, value)
                kp.interpolation, kp.handle_left_type, kp.handle_right_type = interp, lt, rt
                kp.handle_left, kp.handle_right = Vector(kp.co) + Vector(hl), Vector(kp.co) + Vector(hr)
                A.set_selected(kp, True)
                done.add(fc)
            A.update(context, done)
            A.push("Paste Keys")
        elif w == "DELETE" and points:
            A.delete_selected(context, curves)
            T._range.clear()
            A.push("Delete Keys")
        elif w == "CLEAN":
            n = self._clean(curves)
            A.update(context, curves)
            A.push("Clean Keys")
            self.report({"INFO"}, f"{n} key{'s' if n != 1 else ''} removed")
        elif w == "UNUSED":
            n = self._unused(context, curves)
            A.push("Delete Unused Tracks")
            self.report({"INFO"}, f"{n} track{'s' if n != 1 else ''} removed")
        elif w in {"REVERSE", "SNAP"} and points:
            saved = A.remember(points)
            if w == "REVERSE":
                a, b = min(t[2] for t in saved), max(t[2] for t in saved)
                for _fc, kp, x, _y, hl, hr, _i, lt, rt, _e in saved:
                    nx = a + b - x
                    kp.handle_left_type, kp.handle_right_type = rt, lt
                    kp.co.x = nx
                    kp.handle_left, kp.handle_right = (nx - (hr[0] - x), hr[1]), (nx - (hl[0] - x), hl[1])
            else:
                A.retime(context, saved, lambda t: t)
            A.update(context, {t[0] for t in saved})
            A.push("Reverse Keys" if w == "REVERSE" else "Snap Keys")
        elif w == "MARKER":
            sc.timeline_markers.new(f"F_{sc.frame_current}", frame=sc.frame_current)
            A.push("Add Marker")
        elif w == "MARKERS_DELETE":
            sc.timeline_markers.clear()
            A.push("Delete Markers")
        elif w == "FOLD":
            _folded.update(r[0] for r in tree(context) if r[2] in {"object", "folder"})
        elif w == "UNFOLD":
            _folded.clear()
        elif w == "PREVIEW_ALL":
            A.set_view_range(sc, sc.frame_start, sc.frame_end)
        elif w == "PREVIEW_SEL" and points:
            A.set_view_range(sc, min(kp.co.x for _fc, kp in points), max(kp.co.x for _fc, kp in points))
        else:
            A.redraw()
            return {"CANCELLED"}
        A.redraw()
        return {"FINISHED"}

    @staticmethod
    def _clean(curves):
        """Keys between two keys of the same value, with nothing happening there."""
        A.new_token()
        n = 0
        for fc in curves:
            fc.keyframe_points.sort()
            kps = list(fc.keyframe_points)
            drop = [i for i in range(1, len(kps) - 1)
                    if abs(kps[i].co.y - kps[i - 1].co.y) < 1e-6 and abs(kps[i].co.y - kps[i + 1].co.y) < 1e-6
                    and all(abs(kps[j].handle_left[1] - kps[j].co.y) < 1e-6 and abs(kps[j].handle_right[1] - kps[j].co.y) < 1e-6
                            or kps[j].interpolation != "BEZIER" for j in (i - 1, i, i + 1))]
            for i in reversed(drop):
                fc.keyframe_points.remove(fc.keyframe_points[i], fast=True)
            n += len(drop)
        return n

    @staticmethod
    def _unused(context, curves):
        A.new_token()
        dead = [fc for fc in curves if not len(fc.keyframe_points) or (
            not len(fc.modifiers) and len({round(kp.co.y, 6) for kp in fc.keyframe_points}) == 1 and BLENDA4D_OT_tl_command._flat(fc))]
        from bpy_extras import anim_utils
        n = 0
        for fc in dead:
            block = A.owner_of(fc)
            bag = anim_utils.animdata_get_channelbag_for_assigned_slot(block.animation_data) if block is not None else None
            holder = bag.fcurves if bag is not None else getattr(fc.id_data, "fcurves", None)
            if holder is not None:
                holder.remove(fc)
                n += 1
        A.update(context, [])
        return n

    @staticmethod
    def _flat(fc):
        return all(abs(kp.handle_left[1] - kp.co.y) < 1e-6 and abs(kp.handle_right[1] - kp.co.y) < 1e-6
                   or kp.interpolation != "BEZIER" for kp in fc.keyframe_points)


class _OnKeys:
    bl_options = {"INTERNAL", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.screen is not None and roles.role(context.area) in {ROLE, BAR, T.ROLE}

    def points(self, context):
        return A.selected_points(context, all_curves(context) if _edit_area(context) else A.curves(context))


class BLENDA4D_OT_tl_interpolation(_OnKeys, bpy.types.Operator):
    bl_idname = "blenda4d.tl_interpolation"
    bl_label = "Interpolation"
    kind: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, props):
        return next((d for k, _l, _i, d in A.INTERPOLATIONS if k == props.kind), cls.bl_label)

    def execute(self, context):
        A.interpolate(context, self.kind, self.points(context))
        return {"FINISHED"}


TANGENTS = (("AUTO", "Auto Tangents", "HANDLE_AUTO", "Let Blender shape the tangents"),
            ("AUTO_CLAMPED", "Clamp", "HANDLE_AUTOCLAMPED", "Shape the tangents so the curve never goes past its keys"),
            ("FREE", "Break Tangents", "HANDLE_FREE", "Let the two tangents turn on their own"),
            ("FLAT", "Zero Angle", "HANDLE_ALIGNED", "Make the tangents level"),
            ("ZERO", "Zero Length", "HANDLE_VECTOR", "Make the tangents as short as they can be"))


class BLENDA4D_OT_tl_tangent(_OnKeys, bpy.types.Operator):
    bl_idname = "blenda4d.tl_tangent"
    bl_label = "Tangents"
    kind: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, props):
        return next((d for k, _l, _i, d in TANGENTS if k == props.kind), cls.bl_label)

    def execute(self, context):
        A.tangents(context, self.kind, self.points(context))
        return {"FINISHED"}


def C(label, what, icon="NONE"):
    return menus.item(label, "blenda4d.tl_command", icon, what=what)


INTERP_ITEMS = [menus.item(l, "blenda4d.tl_interpolation", i, kind=k) for k, l, i, _d in A.INTERPOLATIONS]
TANGENT_ITEMS = [menus.item(l, "blenda4d.tl_tangent", i, kind=k) for k, l, i, _d in TANGENTS]
EDIT_ITEMS = [C("Cut", "CUT", "TRASH"), C("Copy", "COPY", "COPYDOWN"), C("Paste", "PASTE", "PASTEDOWN"), C("Delete", "DELETE", "X"), menus.SEP,
              C("Select All", "SELECT_ALL", "SELECT_EXTEND"), C("Deselect All", "SELECT_NONE", "SELECT_SET"), C("Invert Selection", "INVERT", "SELECT_DIFFERENCE")]
BAR_MENUS = [menus.simple_menu(name, items, "tl") for name, items in (
    ("Create", [menus.item("Record Active Objects", "blenda4d.tl_record", "KEYFRAME_HLT"), C("Marker", "MARKER", "MARKER_HLT")]),
    ("Edit", EDIT_ITEMS),
    ("Filter", [C("Only Selected Objects", "ONLY", "RESTRICT_SELECT_OFF")]),
    ("View", [C("Dope Sheet", "KEYS", "ACTION"), C("F-Curve Mode", "CURVES", "FCURVE"), C("Switch Mode", "TOGGLE", "UV_SYNC_SELECT"), menus.SEP,
              C("Fold All", "FOLD", "DISCLOSURE_TRI_RIGHT"), C("Unfold All", "UNFOLD", "DISCLOSURE_TRI_DOWN")]),
    ("Frame", [C("Frame All", "ALL", "VIEWZOOM"), C("Frame Selected", "SELECTED", "ZOOM_SELECTED"), C("Go to Current Frame", "CURRENT", "TIME"),
               C("Frame Preview Range", "PREVIEW", "PREVIEW_RANGE"), menus.SEP,
               C("Preview Range from Selected Keys", "PREVIEW_SEL", "CENTER_ONLY"), C("Preview Range from Scene", "PREVIEW_ALL", "SCENE_DATA")]),
    ("Functions", [C("Clean Tracks", "CLEAN", "BRUSH_DATA"), C("Delete Unused Tracks", "UNUSED", "TRASH"), menus.SEP,
                   C("Reverse Sequence", "REVERSE", "ARROW_LEFTRIGHT"), C("Snap to Frames", "SNAP", "SNAP_INCREMENT")]),
    ("Key", INTERP_ITEMS),
    ("F-Curve", TANGENT_ITEMS),
    ("Marker", [C("Add Marker", "MARKER", "MARKER_HLT"), C("Delete All Markers", "MARKERS_DELETE", "X")]))]
MORE_MENUS = menus.make_more(BAR_MENUS, "timeline")


class BLENDA4D_MT_tl_context(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_tl_context"
    bl_label = "Keys"

    def draw(self, context):
        lay = self.layout
        menus.draw_items(lay, INTERP_ITEMS)
        lay.separator()
        menus.draw_items(lay, TANGENT_ITEMS)
        lay.separator()
        menus.draw_items(lay, EDIT_ITEMS)
        lay.separator()
        menus.draw_items(lay, [C("Preview Range from Selected Keys", "PREVIEW_SEL", "CENTER_ONLY"), C("Preview Range from Scene", "PREVIEW_ALL", "SCENE_DATA")])


TOOLS = [[("blenda4d.tl_command", "ACTION", {"what": "KEYS"}), ("blenda4d.tl_command", "FCURVE", {"what": "CURVES"})],
         [("blenda4d.tl_command", "RESTRICT_SELECT_OFF", {"what": "ONLY"})],
         [("blenda4d.tl_interpolation", i, {"kind": k}) for k, _l, i, _d in A.INTERPOLATIONS],
         [("blenda4d.tl_tangent", i, {"kind": k}) for k, _l, i, _d in TANGENTS],
         [("blenda4d.tl_command", "VIEWZOOM", {"what": "ALL"}), ("blenda4d.tl_command", "ZOOM_SELECTED", {"what": "SELECTED"})],
         [("blenda4d.tl_command", "BRUSH_DATA", {"what": "CLEAN"}), ("blenda4d.tl_command", "TRASH", {"what": "UNUSED"})]]


class BLENDA4D_PT_tl_bar(roles.RolePanel, bpy.types.Panel):
    bl_label = "Timeline"
    role = BAR

    def draw(self, context):
        from . import bars, fitzoom
        col = self.layout.column(align=False)
        region = context.region
        s = context.preferences.system.ui_scale
        wide = region.width / max(0.1, fitzoom.zoom_of(region)) - 2 * bars.PANEL_MARGIN * s
        row = col.row(align=True)
        row.label(text="", icon="COLLAPSEMENU")
        menus.menu_bar(row, BAR_MENUS, avail=max(40 * s, wide - 24 * s))
        tools = col.row(align=True)
        tools.alignment = "LEFT"
        tools.scale_x = tools.scale_y = 1.2
        free, cur = wide / (24 * s), mode(context.workspace)
        for n, group in enumerate(TOOLS):                  # whole groups that do not fit are in the menus
            need = len(group) + (0.7 if n else 0)
            if need > free:
                break
            free -= need
            if n:
                tools.separator(factor=1.4)
            for op, icon, props in group:
                what = props.get("what")
                on = what == cur or (what == "ONLY" and only_selected(context.scene))
                o = tools.operator(op, text="", icon=icon, depress=on)
                for k, v in props.items():
                    setattr(o, k, v)


classes = (BLENDA4D_OT_tl_edit, BLENDA4D_OT_tl_wheel, BLENDA4D_OT_tl_command, BLENDA4D_OT_tl_interpolation, BLENDA4D_OT_tl_tangent,
           *BAR_MENUS, MORE_MENUS, BLENDA4D_MT_tl_context, BLENDA4D_PT_tl_bar)
# key, modifiers, command: each is also in the bar's menus
KEYS = (("H", {}, "ALL"), ("S", {}, "SELECTED"), ("F", {}, "SELECTED"), ("O", {}, "CURRENT"), ("TAB", {}, "TOGGLE"),
        ("DEL", {}, "DELETE"), ("BACK_SPACE", {}, "DELETE"), ("A", {"mod": True}, "SELECT_ALL"),
        ("A", {"mod": True, "shift": True}, "SELECT_NONE"), ("C", {"mod": True}, "COPY"), ("X", {"mod": True}, "CUT"), ("V", {"mod": True}, "PASTE"))


@bpy.app.handlers.persistent
def _loaded(_file):
    _state.clear()
    _picked.clear()
    _folded.clear()
    _clip.clear()


def register():
    import sys
    bpy.types.WindowManager.b4d_tl_list = bpy.props.FloatProperty(name="List Width", default=LIST, min=LIST_MIN, max=1000,
                                                                  description="The width of the Timeline's list")
    for c in classes:
        bpy.utils.register_class(c)
    _handles.append(bpy.types.SpaceProperties.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL"))
    bpy.app.handlers.load_post.append(_loaded)
    kc = bpy.context.window_manager.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.new(name="Property Editor", space_type="PROPERTIES", region_type="WINDOW")
    v2 = [kc.keymaps.new(name=n, space_type="EMPTY", region_type="WINDOW") for n in ("View2D", "View2D Buttons List")]
    for kind in ("LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE"):
        _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_tl_edit.bl_idname, kind, "PRESS", any=True, head=True)))
    for k in v2:                                          # before the Properties editor's own scrolling takes them
        _keymaps.append((k, k.keymap_items.new(BLENDA4D_OT_tl_edit.bl_idname, "MIDDLEMOUSE", "PRESS", any=True, head=True)))
    for k in [km] + v2:
        for kind in ("WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN"):
            _keymaps.append((k, k.keymap_items.new(BLENDA4D_OT_tl_wheel.bl_idname, kind, "ANY", any=True, head=True)))
    for kind, mods, what in KEYS:
        mods = dict(mods)
        if mods.pop("mod", False):
            mods["oskey" if sys.platform == "darwin" else "ctrl"] = True
        kmi = km.keymap_items.new("blenda4d.tl_command", kind, "PRESS", head=True, **mods)
        kmi.properties.what = what
        _keymaps.append((km, kmi))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    while _handles:
        bpy.types.SpaceProperties.draw_handler_remove(_handles.pop(), "WINDOW")
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    _state.clear()
    del bpy.types.WindowManager.b4d_tl_list
