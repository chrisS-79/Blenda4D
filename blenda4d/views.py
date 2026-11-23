# SPDX-License-Identifier: GPL-3.0-or-later
"""F1-F4 switch between the Perspective, Top, Right and Front views, and each one comes back where you left it."""
import math

import bpy
from mathutils import Euler

from . import build, quadview, viewhistory, viewmenus

START_ROTATION = Euler((math.radians(65.0), 0.0, math.radians(35.0))).to_quaternion()

VIEWS = [("PERSP", "Perspective", "Perspective view"),
         ("TOP", "Top", "Top view"),
         ("RIGHT", "Right", "Right view"),
         ("FRONT", "Front", "Front view")]


def _region(area):
    from .roles import alive
    if not alive(area):                                    # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == "WINDOW"), None)


def _start_perspective(window, area):
    rv = area.spaces.active.region_3d
    rv.lock_rotation = False
    rv.view_perspective = "PERSP"
    rv.view_rotation = START_ROTATION
    try:
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=_region(area)):
            bpy.ops.view3d.view_all(center=False)
    except RuntimeError:
        pass


def _leave_scene_camera(area):
    sp = area.spaces.active
    if sp.region_3d.view_perspective == "CAMERA":
        viewmenus.back_to_editor(area, sp)


def _to_perspective(window, area):
    """The viewport's own perspective, as left: out of a camera however it was entered (the Cameras menu or Blender's own
    Numpad 0), out of Cameras > Left, Back, Bottom and Blender's own side views. A parallel view at a free angle keeps
    its angle."""
    rv = area.spaces.active.region_3d
    if rv.view_perspective == "CAMERA":
        _leave_scene_camera(area)                         # also puts the viewport's own focal length back
        if not viewhistory.to_last_perspective(rv):
            rv.view_perspective = "PERSP"
    elif rv.view_perspective == "ORTHO":
        if not rv.is_orthographic_side_view:
            rv.view_perspective = "PERSP"
        elif not viewhistory.to_last_perspective(rv):
            _start_perspective(window, area)


def switch_single(window, area, target):
    current = quadview.corner_of_single(area)
    if current == target:
        if target == "PERSP":
            _to_perspective(window, area)
            area.tag_redraw()
        return

    quadview._saved[current] = quadview.state(area)
    saved = quadview._saved.get(target)
    if saved:
        quadview.apply(area, saved)
    elif quadview.AXIS[target]:
        quadview._axis_view(window, area, target)
    else:
        _start_perspective(window, area)

    if target == "PERSP":
        area.spaces.active.region_3d.lock_rotation = False
        _to_perspective(window, area)
    quadview._saved["ALONE"] = target
    area.tag_redraw()


def _run(context, target):
    from . import magnify
    magnify.leave_all()
    screen = context.screen
    views = quadview.views(screen)
    if len(views) > 1:
        keep = next((a for a in views if quadview.corner_of(a, screen) == target), None)
        if keep:
            build.run_steps(quadview.expand_steps(context.window, keep))
    else:
        switch_single(context.window, context.area, target)
    return {"FINISHED"}


def _make_operator(target, label, description):
    def execute(self, context):
        return _run(context, target)

    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and not build.busy()

    return type(f"BLENDA4D_OT_view_{target.lower()}", (bpy.types.Operator,), {
        "bl_idname": f"blenda4d.view_{target.lower()}",
        "bl_label": label,
        "bl_description": description,
        "poll": classmethod(poll),
        "execute": execute,
    })


CLASSES = [_make_operator(*v) for v in VIEWS]


@bpy.app.handlers.persistent
def _loaded(_file):
    quadview._saved.clear()                               # another file's views are not this one's


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if _loaded not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_loaded)


def unregister():
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
