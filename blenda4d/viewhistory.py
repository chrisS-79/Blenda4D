# SPDX-License-Identifier: GPL-3.0-or-later
"""Undo View and Redo View: step back and forward through a viewport's own views (orbit, pan, zoom, framing, side
views). Blender's undo does not cover these. Each viewport has its own history, as long as the file is open,
and in it the perspective and each side view (F1 to F4, four views) their own: a step never swaps one for the other.

A view counts once it has been still for a moment, so one drag is one step. Looking through a camera, orbiting moves
the camera object itself and Blender's normal undo already covers that: here only going into and out of the camera,
and its zoom and offset on screen, are steps. Nothing in the scene is ever changed."""
import time

import bpy

LIMIT = 100                  # steps kept per viewport
STILL = 0.3                  # seconds without a change: the view is a step
_views = {}                  # (RegionView3D pointer, its side) -> {"undo", "redo", "at" (the last step's view), "seen", "t"}
_handles = []


def _rv3d(area):
    return area.spaces.active.region_3d if area is not None and area.type == "VIEW_3D" else None


def _magnified(rv):
    """Magnify looks through a camera of its own: for the history that is still the free perspective."""
    from . import magnify
    return rv.as_pointer() in magnify._on


def state(rv):
    if rv.view_perspective == "CAMERA" and _magnified(rv):
        return ("PERSP", tuple(rv.view_location), tuple(rv.view_rotation), rv.view_distance)
    if rv.view_perspective == "CAMERA":
        return ("CAMERA", tuple(rv.view_camera_offset), rv.view_camera_zoom)
    if rv.lock_rotation:                                  # a side view of the four: it pans and zooms, never turns
        return ("SIDE", tuple(rv.view_location), rv.view_distance)
    return (rv.view_perspective, tuple(rv.view_location), tuple(rv.view_rotation), rv.view_distance)


def _flat(s):
    out = []
    for v in s[1:]:
        out += list(v) if isinstance(v, tuple) else [v]
    return out


def same(a, b):
    if a[0] != b[0]:
        return False
    return all(abs(x - y) <= 1e-5 * max(1.0, abs(x), abs(y)) for x, y in zip(_flat(a), _flat(b)))


def _put(rv, s):
    if s[0] == "SIDE":
        rv.view_location, rv.view_distance = s[1], s[2]
        return
    rv.view_perspective = s[0]
    if s[0] == "CAMERA":
        rv.view_camera_offset, rv.view_camera_zoom = s[1], s[2]
    else:
        rv.view_location, rv.view_rotation, rv.view_distance = s[1], s[2], s[3]


def _commit(h, now):
    """The view has come to rest: the one it came from becomes a step."""
    if now[0] == "PERSP":
        h["persp"] = now
    if same(h["at"], now):
        return
    h["undo"].append(h["at"])
    del h["undo"][:-LIMIT]
    h["redo"].clear()
    h["at"] = now


def _key(rv):
    """Which history a viewport is in: the free view's, or that of the side a locked view looks from."""
    side = tuple(round(v, 1) for v in rv.view_rotation) if rv.lock_rotation and rv.view_perspective != "CAMERA" else None
    return rv.as_pointer(), side


def _entry(rv):
    key = _key(rv)
    if key not in _views:
        s = state(rv)
        _views[key] = {"undo": [], "redo": [], "at": s, "seen": s, "t": 0.0, "persp": s if s[0] == "PERSP" else None}
    return _views[key]


def _draw():
    rv = _rv3d(bpy.context.area)
    if rv is None or bpy.context.region.type != "WINDOW":
        return
    h, now = _entry(rv), state(rv)
    if not same(h["seen"], now):
        h["seen"], h["t"] = now, time.time()
        if not bpy.app.timers.is_registered(_settle):
            bpy.app.timers.register(_settle, first_interval=STILL)


def _settle():
    wm = bpy.context.window_manager
    waiting = False
    for w in wm.windows:
        for a in w.screen.areas:
            rv = _rv3d(a)
            if rv is None:
                continue
            h = _views.get(_key(rv))
            if h is None:
                continue
            if same(h["seen"], h["at"]):
                continue
            if time.time() - h["t"] < STILL * 0.95:
                waiting = True
            else:
                _commit(h, h["seen"])
    return STILL if waiting else None


def to_last_perspective(rv):
    """The viewport's own perspective as it was last left (before a camera or a side view). False: none is known."""
    h = _views.get((rv.as_pointer(), None))
    if h is None or h["persp"] is None:
        return False
    rv.lock_rotation = False
    _put(rv, h["persp"])
    return True


def available(context, redo):
    rv = _rv3d(context.area)
    if rv is None:
        return False
    h = _views.get(_key(rv))
    if h is None:
        return False
    moved = not same(h["at"], state(rv))
    return bool(h["redo"]) and not moved if redo else bool(h["undo"]) or moved


def step(context, redo):
    rv = _rv3d(context.area)
    if rv is None:
        return False
    from . import magnify
    magnify.leave(context.area)
    h = _entry(rv)
    _commit(h, state(rv))                                 # a move that has not settled yet is a step too
    src, dst = (h["redo"], h["undo"]) if redo else (h["undo"], h["redo"])
    if not src:
        return False
    dst.append(h["at"])
    h["at"] = src.pop()
    _put(rv, h["at"])
    if h["at"][0] == "PERSP":
        h["persp"] = h["at"]
    h["at"] = h["seen"] = state(rv)
    context.area.tag_redraw()
    return True


class _Step:
    bl_options = {"INTERNAL"}
    redo = False

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        return {"FINISHED"} if step(context, self.redo) else {"CANCELLED"}


class BLENDA4D_OT_view_undo(_Step, bpy.types.Operator):
    bl_idname = "blenda4d.view_undo"
    bl_label = "Undo View"
    bl_description = "Step back to this viewport's previous view (orbit, pan, zoom). The scene is not changed"


class BLENDA4D_OT_view_redo(_Step, bpy.types.Operator):
    bl_idname = "blenda4d.view_redo"
    bl_label = "Redo View"
    bl_description = "Step forward again after Undo View"
    redo = True


classes = (BLENDA4D_OT_view_undo, BLENDA4D_OT_view_redo)


@bpy.app.handlers.persistent
def _loaded(_file):
    _views.clear()


def register():
    for c in classes:
        bpy.utils.register_class(c)
    _views.clear()
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL"))
    if _loaded not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_loaded)


def unregister():
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), "WINDOW")
    if bpy.app.timers.is_registered(_settle):
        bpy.app.timers.unregister(_settle)
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    _views.clear()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
