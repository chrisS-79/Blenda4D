# SPDX-License-Identifier: GPL-3.0-or-later
"""Object handles: the yellow dots on a selected object that you drag in the viewport to change its settings
(a Cloner's radius or size, a field's radius...). The Attribute Manager follows live; Escape puts the value back;
each drag is one undo step.

A module adds handles for its objects with provide(fn): fn(ob) returns a list of Handle or None. A handle sits at a
point in the object's own space and moves along a direction there (or freely in the view's plane when the direction is
None); dragging calls set(value) with the new place (a Vector in the object's space) and the place it started."""
import math

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector, geometry

DOT = (253 / 255, 228 / 255, 115 / 255, 1.0)     # the handle yellow
INNER = (0.62, 0.38, 1.0, 1.0)                   # an Inner Offset handle is purple
HOT = (1.0, 1.0, 1.0, 1.0)
DOT_R, HIT = 4.0, 10
_providers = []
_draws = []
_keys = []
_shown = {}                                      # area pointer -> [(x, y, handle)] in region pixels
_drag = [None]


class Handle:
    def __init__(self, name, at, set, axis=None, label=None, colour=DOT, readout=None):
        self.name = name                # what it sets, for the readout ("Radius")
        self.at = Vector(at)            # where it sits, in the object's own space
        self.axis = Vector(axis).normalized() if axis is not None else None
        self.set = set                  # set(new_place, start_place)
        self.colour = colour
        self.readout = readout          # () -> text while dragging


def provide(fn):
    if fn not in _providers:
        _providers.append(fn)


def handles_of(ob):
    out = []
    for fn in _providers:
        try:
            out += fn(ob) or []
        except Exception as ex:                    # a provider must never break drawing
            print("Blenda 4D: handles:", ex)
    return out


def _target(context):
    ob = context.active_object
    if ob is None or not ob.select_get() or context.mode != "OBJECT" or not ob.visible_get():
        return None
    return ob


def _px(context):
    """Interface pixels to region pixels (a Retina screen has two region pixels to each)."""
    sy = context.preferences.system
    return sy.ui_scale * sy.pixel_size


def _region_xy(context, world):
    return view3d_utils.location_3d_to_region_2d(context.region, context.region_data, world)


def _draw():
    import gpu
    from gpu_extras.batch import batch_for_shader
    context = bpy.context
    area = context.area
    if area is None:
        return
    key = area.as_pointer()
    _shown[key] = []
    ob = _target(context)
    if ob is None:
        return
    hs = handles_of(ob)
    if not hs:
        return
    s = context.preferences.system.ui_scale
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    mw = ob.matrix_world
    dragging = _drag[0]
    for h in hs:
        p = _region_xy(context, mw @ h.at)
        if p is None:
            continue
        _shown[key].append((p.x, p.y, h))
        hot = dragging is not None and dragging == h.name
        r = DOT_R * s * (1.3 if hot else 1.0)
        for col, rr in (((0.0, 0.0, 0.0, 0.6), r + 1.2 * s), (HOT if hot else h.colour, r)):   # a dark rim, then the dot
            pts = [(p.x, p.y)] + [(p.x + math.cos(2 * math.pi * i / 16) * rr, p.y + math.sin(2 * math.pi * i / 16) * rr) for i in range(17)]
            sh.uniform_float("color", col)
            batch_for_shader(sh, "TRI_FAN", {"pos": pts}).draw(sh)
    gpu.state.blend_set("NONE")


def hit(context, x, y, second=False):
    """The dot under the mouse; with second, the next one when two sit on the same spot (a Cone's Top Radius on its
    Height: Shift picks it)."""
    s = _px(context)
    near = sorted((max(abs(hx - x), abs(hy - y)), i, h) for i, (hx, hy, h) in enumerate(_shown.get(context.area.as_pointer(), []))
                  if max(abs(hx - x), abs(hy - y)) <= HIT * s)
    if not near:
        return None
    return near[1][2] if second and len(near) > 1 else near[0][2]


PICK = 8                                          # how near (interface pixels) a click must be to a drawn outline to pick it
OUTLINES = []                                     # fn(context) -> [(object, [(world a, world b), ...])]


def outlines(fn):
    if fn not in OUTLINES:
        OUTLINES.append(fn)


def _shapes(context):
    for fn in OUTLINES:
        try:
            yield from fn(context)
        except Exception:
            continue


def _pick_drawn(context, mx, my):
    """The object whose drawn outline passes nearest the click, within PICK pixels; None if none does."""
    if context.mode != "OBJECT":
        return None
    reach = PICK * _px(context)
    best, dist = None, reach
    for ob, segs in _shapes(context):
        for a, b in segs:
            pa, pb = _region_xy(context, a), _region_xy(context, b)
            if pa is None or pb is None:
                continue
            d = _seg_dist(mx, my, pa.x, pa.y, pb.x, pb.y)
            if d < dist:
                best, dist = ob, d
    return best


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _place(context, ob, start, axis, mx, my):
    """Where the mouse is, in the object's space: on the handle's line, or on the view plane through the start."""
    region, rv3d = context.region, context.region_data
    o = view3d_utils.region_2d_to_origin_3d(region, rv3d, (mx, my))
    d = view3d_utils.region_2d_to_vector_3d(region, rv3d, (mx, my))
    inv = ob.matrix_world.inverted()
    lo, ld = inv @ o, (inv.to_3x3() @ d).normalized()
    if axis is not None:
        near = geometry.intersect_line_line(start, start + axis, lo, lo + ld)
        return near[0] if near else start
    n = (inv.to_3x3() @ (rv3d.view_rotation @ Vector((0, 0, -1)))).normalized()
    p = geometry.intersect_line_plane(lo, lo + ld, start, n)
    return p if p is not None else start


class BLENDA4D_GT_dots(bpy.types.Gizmo):
    """The dots and drawn outlines as one gizmo: Blender asks gizmos first, before any tool, so the dots drag and
    the outlines pick whatever tool is active (the Move tool's own click would otherwise take them)."""
    bl_idname = "BLENDA4D_GT_dots"

    def draw(self, context):
        pass                                             # handles._draw draws the dots

    def test_select(self, context, location):
        mx, my = location
        if _target(context) is not None and hit(context, mx, my) is not None:
            return 0
        return 0 if _pick_drawn(context, mx, my) is not None else -1

    def invoke(self, context, event):
        mx, my = event.mouse_region_x, event.mouse_region_y
        ob = _target(context)
        h = hit(context, mx, my, second=event.shift) if ob is not None else None
        self.ob = None
        if h is None:
            picked = _pick_drawn(context, mx, my)
            if picked is None:
                return {"PASS_THROUGH"}
            # the gizmo holds the click until the button comes up, so the active tool never sees its press or
            # release (its release on empty space would deselect everything); the pick is made on release
            self.pick = (picked.name, event.shift)
            return {"RUNNING_MODAL"}
        self.pick = None
        self.ob, self.hname, self.start, self.axis = ob, h.name, h.at.copy(), h.axis
        self.undo = _snapshot(ob)
        _drag[0] = h.name
        return {"RUNNING_MODAL"}

    def modal(self, context, event, tweak):
        if self.ob is None:
            return {"RUNNING_MODAL"} if self.pick else {"FINISHED"}
        h = next((x for x in handles_of(self.ob) if x.name == self.hname), None)
        if h is not None:
            h.set(_place(context, self.ob, self.start, self.axis, event.mouse_region_x, event.mouse_region_y), self.start)
            self.ob.update_tag()
            text = h.readout() if h.readout else None
            context.workspace.status_text_set(f"{h.name}: {text}" if text else h.name)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        if self.ob is None:
            if self.pick and not cancel:
                name, extend = self.pick
                self.pick = None
                _select([bpy.data.objects.get(name)], "ADD" if extend else "SET", context.view_layer, make_active=True)
                context.area.tag_redraw()
                bpy.ops.ed.undo_push(message="Select")
            return
        if cancel:
            _restore(self.ob, self.undo)
        _drag[0] = None
        context.workspace.status_text_set(None)
        for a in context.screen.areas:                   # the Attribute Manager shows the new value
            a.tag_redraw()
        if not cancel:
            bpy.ops.ed.undo_push(message=f"Drag {self.hname}")


class BLENDA4D_GGT_dots(bpy.types.GizmoGroup):
    bl_idname = "BLENDA4D_GGT_dots"
    bl_label = "Blenda 4D handles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"PERSISTENT", "SHOW_MODAL_ALL"}

    @classmethod
    def poll(cls, context):
        from . import switch
        return switch.is_on() and context.mode == "OBJECT"

    def setup(self, context):
        self.gizmos.new(BLENDA4D_GT_dots.bl_idname)


# --- the Rectangle selection takes a field when its frame crosses the field's drawn shape --------------------------

def _select(objs, mode, vl, make_active=False):
    objs = [o for o in objs if o is not None]
    if mode == "SET":
        for o in vl.objects.selected:
            if o not in objs:
                o.select_set(False)
    for o in objs:
        if mode == "SUB":
            o.select_set(False)
        elif mode == "XOR":
            o.select_set(not o.select_get())
        else:
            o.select_set(True)
    if make_active and objs and mode != "SUB":
        vl.objects.active = objs[0]


def _box_hits(context, region, rv3d, x0, y0, x1, y1):
    from mathutils.geometry import intersect_line_line_2d
    corners = [Vector((x0, y0)), Vector((x1, y0)), Vector((x1, y1)), Vector((x0, y1))]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    out = []
    for ob, segs in _shapes(context):
        for a, b in segs:
            pa = view3d_utils.location_3d_to_region_2d(region, rv3d, a)
            pb = view3d_utils.location_3d_to_region_2d(region, rv3d, b)
            if pa is None or pb is None:
                continue
            if any(x0 <= p.x <= x1 and y0 <= p.y <= y1 for p in (pa, pb)) or \
                    any(intersect_line_line_2d(pa, pb, c, d) for c, d in edges):
                out.append(ob)
                break
    return out


class BLENDA4D_OT_box_watch(bpy.types.Operator):
    """Rectangle Selection that also takes drawn shapes: Blender's own Rectangle Selection draws and applies the frame,
    then any field whose drawn shape the frame crosses is added (Blender alone only looks at the field's centre)"""
    bl_idname = "blenda4d.box_watch"
    bl_label = "Rectangle Selection"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        mode = "AND" if event.shift and event.ctrl else "ADD" if event.shift else "SUB" if event.ctrl else "SET"
        try:
            r = bpy.ops.view3d.select_box("INVOKE_DEFAULT", mode=mode, wait_for_input=False)
        except RuntimeError:
            return {"PASS_THROUGH"}
        if "RUNNING_MODAL" not in r or context.mode != "OBJECT" or not OUTLINES:
            return {"FINISHED"}
        self.mode, self.start = mode, (event.mouse_region_x, event.mouse_region_y)
        self.area, self.region = context.area, context.region
        context.window_manager.modal_handler_add(self)    # after the frame's own handler, so it hears the release first
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            return {"CANCELLED", "PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            rect = (self.start[0], self.start[1], event.mouse_x - self.region.x, event.mouse_y - self.region.y)
            mode, area, region = self.mode, self.area, self.region

            def apply():                                  # once Blender has applied its own frame
                _box_apply(area, region, rect, mode)
                return None
            bpy.app.timers.register(apply, first_interval=0.0)
            self.done = True
            return {"PASS_THROUGH"}
        if getattr(self, "done", False):
            return {"FINISHED", "PASS_THROUGH"}
        return {"PASS_THROUGH"}


def _box_apply(area, region, rect, mode):
    context = bpy.context
    try:
        xa, ya, xb, yb = (int(round(v)) for v in rect)
        x0, x1 = sorted((xa, xb))
        y0, y1 = sorted((ya, yb))
        # Blender's own Rectangle Selection, on exactly this frame (the same again if it already ran: no harm)
        with context.temp_override(window=context.window_manager.windows[0] if context.window is None else context.window,
                                   area=area, region=region):
            bpy.ops.view3d.select_box(xmin=x0, xmax=x1, ymin=y0, ymax=y1, mode=mode, wait_for_input=False)
        hits = _box_hits(context, region, region.data, x0, y0, x1, y1)
    except (ReferenceError, AttributeError, RuntimeError):
        return
    if hits and mode != "AND":
        _select(hits, mode if mode == "SUB" else "ADD", context.view_layer)
    try:
        area.tag_redraw()
        bpy.ops.ed.undo_push(message="Select")
    except (ReferenceError, RuntimeError):
        pass


_BOX_KEYMAPS = ("3D View Tool: Select Box", "3D View Tool: Select Box (fallback)")


def _add_box_keys():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    for name in _BOX_KEYMAPS:
        km = kc.keymaps.new(name=name, space_type="VIEW_3D", region_type="WINDOW", tool=True)
        kmi = km.keymap_items.new(BLENDA4D_OT_box_watch.bl_idname, "LEFTMOUSE", "CLICK_DRAG", any=True)
        _keys.append((km, kmi))


# Escape puts every setting a handle can reach back as it was
_SNAP = []                                       # fn(ob) -> state, fn(ob, state)


def snapshot_with(take, give):
    _SNAP.append((take, give))


def _snapshot(ob):
    return [(give, take(ob)) for take, give in _SNAP]


def _restore(ob, snap):
    for give, state in snap or []:
        try:
            give(ob, state)
        except Exception:
            pass
    ob.update_tag()


def register():
    for c in (BLENDA4D_GT_dots, BLENDA4D_GGT_dots, BLENDA4D_OT_box_watch):
        bpy.utils.register_class(c)
    _draws.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL"))
    _add_box_keys()


def unregister():
    for km, kmi in _keys:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keys.clear()
    for h in _draws:
        bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
    _draws.clear()
    _shown.clear()
    for c in (BLENDA4D_OT_box_watch, BLENDA4D_GGT_dots, BLENDA4D_GT_dots):
        bpy.utils.unregister_class(c)
