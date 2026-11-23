# SPDX-License-Identifier: GPL-3.0-or-later
"""Magnify: enlarge what a viewport shows, around the pointer, as an image is enlarged: the camera does not move and
the perspective does not change. Option+Cmd+wheel (Ctrl+Alt+wheel on Windows and Linux), Option+Cmd+middle drag to move
the enlarged picture, and View > Magnify. All the way out, the viewport is exactly as it was.

Side views and parallel views enlarge by their own zoom, and a scene camera's view by its zoom and offset on screen.
Blender's free perspective has neither, so while it is magnified the viewport looks through a camera of its own, in the
same place with the same lens, that is in no scene and goes when Magnify ends. Orbiting and zooming move that camera."""
import math

import blf
import bpy
from mathutils import Vector

from . import strip

NAME = ".blenda4d_magnify"
STEP = 1.18
MOST = 30.0
_on = {}                     # RegionView3D pointer -> {"cam", "mag", "k", "sx", "sy", and the viewport's own settings}
_camera = {}                 # RegionView3D pointer -> a scene camera's zoom and offset before its view was magnified
_handles = []


def _region(area):
    from .roles import alive
    if not alive(area):                                    # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == "WINDOW"), None)


def entry(sp):
    """What is known of this viewport's magnifying, when it is magnified with a camera of its own."""
    if sp is None or sp.type != "VIEW_3D" or sp.region_3d is None:
        return None
    return _on.get(sp.region_3d.as_pointer())


def on(sp):
    e = entry(sp)
    return e is not None and sp.region_3d.view_perspective == "CAMERA" and sp.camera is not None and sp.camera.name == e["cam"]


# --- the camera of its own ------------------------------------------------------------------------------------------------
def _zoom_for(fac):
    return 50.0 * (2.0 * math.sqrt(fac) - math.sqrt(2.0))


def _frame(sp, region, e):
    """How many times wider than the view the camera's frame is, so its lines stay out of sight."""
    r = bpy.context.scene.render
    frame = (r.resolution_y * r.pixel_aspect_y) / max(1e-6, r.resolution_x * r.pixel_aspect_x)
    return max(1.1, 1.1 * (region.height / max(1, region.width)) / max(1e-6, frame))


def _enter(area, sp, region):
    rv = sp.region_3d
    rv.update()
    e = {"local": sp.use_local_camera, "camera": sp.camera, "lock": sp.lock_camera, "mag": 1.0, "sx": 0.0, "sy": 0.0,
         "zoom": rv.view_camera_zoom, "offset": tuple(rv.view_camera_offset)}
    cd = bpy.data.cameras.new(NAME)
    ob = bpy.data.objects.new(NAME, cd)
    cd.show_passepartout = False
    cd.clip_start, cd.clip_end = sp.clip_start, sp.clip_end
    half = 1.0 / rv.window_matrix[0][0]                    # half the view's width, one unit away
    e["k"] = _frame(sp, region, e)
    cd.sensor_fit, cd.sensor_width = "HORIZONTAL", 36.0
    cd.lens = max(1.0, 36.0 / (2.0 * half * e["k"]))
    ob.rotation_mode = "QUATERNION"
    ob.matrix_world = ob.matrix_basis = rv.view_matrix.inverted()
    e["cam"] = ob.name
    sp.use_local_camera = True
    sp.camera = ob
    rv.view_perspective = "CAMERA"
    sp.lock_camera = True
    rv.view_camera_offset = (0.0, 0.0)
    _on[rv.as_pointer()] = e
    return e


def _apply(sp, region, e):
    rv = sp.region_3d
    fac = e["k"] * e["mag"]
    rv.view_camera_zoom = min(600.0, _zoom_for(fac))
    rv.view_camera_offset = (max(-1.0, min(1.0, e["sx"] / (2.0 * fac * region.width))),
                             max(-1.0, min(1.0, e["sy"] / (2.0 * fac * region.height))))


def _keep_inside(region, e):
    """The picture cannot be moved off its own edges."""
    mx, my = (e["mag"] - 1.0) * region.width / 2.0, (e["mag"] - 1.0) * region.height / 2.0
    e["sx"], e["sy"] = max(-mx, min(mx, e["sx"])), max(-my, min(my, e["sy"]))


def _remove(e):
    ob = bpy.data.objects.get(e["cam"])
    if ob is not None:
        cd = ob.data
        bpy.data.objects.remove(ob)
        if cd is not None and cd.users == 0:
            bpy.data.cameras.remove(cd)


def leave(area):
    """Back to the viewport's own view (where it looks from now)."""
    if area is None or area.type != "VIEW_3D" or not len(area.spaces):
        return
    sp = area.spaces.active
    rv = sp.region_3d
    e = _on.pop(rv.as_pointer(), None) if rv is not None else None
    if e is None:
        return
    ob = bpy.data.objects.get(e["cam"])
    pose = ob.matrix_world.copy() if ob is not None and rv.view_perspective == "CAMERA" and sp.camera == ob else None
    if rv.view_perspective == "CAMERA":                    # undo can put another camera in its place
        rv.view_perspective = "PERSP"
    rv.view_camera_zoom, rv.view_camera_offset = e["zoom"], e["offset"]      # a scene camera's own, for next time
    sp.use_local_camera = e["local"]
    if e["local"]:
        sp.camera = e["camera"]
    sp.lock_camera = e["lock"]
    if pose is not None:
        rv.view_matrix = pose.inverted()
    _remove(e)
    area.tag_redraw()


def leave_all():
    wm = bpy.context.window_manager
    for w in wm.windows if wm else ():
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                leave(a)


# --- magnifying -------------------------------------------------------------------------------------------------------------
def magnify(context, area, factor, at=None):
    """Enlarge the area's view `factor` times around `at` (region pixels; None: the middle)."""
    sp, region = area.spaces.active, _region(area)
    rv = sp.region_3d
    mid = Vector((region.width / 2.0, region.height / 2.0))
    q = (Vector(at) if at is not None else mid.copy()) - mid
    if not on(sp) and rv.view_perspective != "PERSP":
        if rv.view_perspective == "CAMERA":
            _scene_camera(rv, region, factor, q)
        else:
            _parallel(rv, region, factor, q)
        area.tag_redraw()
        return True
    e = entry(sp) if on(sp) else None
    if e is None:
        if factor <= 1.0:
            return False
        leave(area)                                        # anything left over from before
        e = _enter(area, sp, region)
    new = min(MOST, e["mag"] * factor)
    if new <= 1.0005:
        leave(area)
        return True
    f = new / e["mag"]
    e["sx"], e["sy"] = f * (q.x + e["sx"]) - q.x, f * (q.y + e["sy"]) - q.y
    e["mag"] = new
    _keep_inside(region, e)
    _apply(sp, region, e)
    area.tag_redraw()
    return True


def _fac(zoom):
    return ((math.sqrt(2.0) + zoom / 50.0) ** 2) / 4.0


def camera_magnified(sp):
    """How much a scene camera's view is enlarged, when it is (1.0: not)."""
    rv = sp.region_3d
    base = _camera.get(rv.as_pointer()) if rv is not None and rv.view_perspective == "CAMERA" and not on(sp) else None
    return _fac(rv.view_camera_zoom) / _fac(base[0]) if base else 1.0


def _scene_camera(rv, region, factor, q):
    z, key = rv.view_camera_zoom, rv.as_pointer()
    if key not in _camera:
        if factor <= 1.0:
            return
        _camera[key] = (z, tuple(rv.view_camera_offset))
    z0, offset0 = _camera[key]
    fac = _fac(z)
    new = min(600.0, _zoom_for(fac * factor))
    if factor < 1.0 and _fac(new) <= _fac(z0) * 1.0005:    # all the way out: as it was before
        rv.view_camera_zoom, rv.view_camera_offset = z0, offset0
        del _camera[key]
        return
    fac2 = _fac(new)
    f = fac2 / fac
    ox, oy = rv.view_camera_offset
    sx, sy = 2.0 * fac * region.width * ox, 2.0 * fac * region.height * oy
    sx, sy = f * (q.x + sx) - q.x, f * (q.y + sy) - q.y
    if factor < 1.0:                                       # on the way out the picture drifts back to where it started
        mag, b = fac2 / _fac(z0), (2.0 * _fac(z0) * region.width * offset0[0], 2.0 * _fac(z0) * region.height * offset0[1])
        mx, my = (mag - 1.0) * region.width / 2.0, (mag - 1.0) * region.height / 2.0
        sx = max(mag * b[0] - mx, min(mag * b[0] + mx, sx))
        sy = max(mag * b[1] - my, min(mag * b[1] + my, sy))
    rv.view_camera_zoom = new
    rv.view_camera_offset = (max(-1.0, min(1.0, sx / (2.0 * fac2 * region.width))),
                             max(-1.0, min(1.0, sy / (2.0 * fac2 * region.height))))


def _parallel(rv, region, factor, q):
    rv.update()
    m = rv.window_matrix
    right = rv.view_rotation @ Vector((1.0, 0.0, 0.0))
    up = rv.view_rotation @ Vector((0.0, 1.0, 0.0))
    per_px = 2.0 / (m[0][0] * region.width)
    d = (1.0 - 1.0 / factor) * per_px
    rv.view_location = rv.view_location + right * (q.x * d) + up * (q.y * d)
    rv.view_distance = rv.view_distance / factor


def pan(context, area, dx, dy):
    """Move the enlarged picture by pixels."""
    sp, region = area.spaces.active, _region(area)
    rv = sp.region_3d
    if on(sp):
        e = entry(sp)
        e["sx"], e["sy"] = e["sx"] - dx, e["sy"] - dy
        _keep_inside(region, e)
        _apply(sp, region, e)
    elif rv.view_perspective == "CAMERA":
        fac = ((math.sqrt(2.0) + rv.view_camera_zoom / 50.0) ** 2) / 4.0
        ox, oy = rv.view_camera_offset
        rv.view_camera_offset = (max(-1.0, min(1.0, ox - dx / (2.0 * fac * region.width))),
                                 max(-1.0, min(1.0, oy - dy / (2.0 * fac * region.height))))
    elif rv.view_perspective == "ORTHO":
        per_px = 2.0 / (rv.window_matrix[0][0] * region.width)
        rv.view_location = rv.view_location - rv.view_rotation @ Vector((dx * per_px, dy * per_px, 0.0))
    area.tag_redraw()


class _InView:
    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and context.area.spaces.active.region_3d is not None


class _Magnify(_InView):
    bl_options = {"INTERNAL"}
    wheel, menu = STEP, 1.5

    def factor(self, event):
        return self.wheel

    def invoke(self, context, event):
        factor = self.factor(event)
        r = _region(context.area)
        at = (event.mouse_x - r.x, event.mouse_y - r.y)
        magnify(context, context.area, factor, at)
        return {"FINISHED"}

    def execute(self, context):                            # from the menu: around the middle
        magnify(context, context.area, self.menu)
        return {"FINISHED"}


class BLENDA4D_OT_magnify_in(_Magnify, bpy.types.Operator):
    bl_idname = "blenda4d.magnify_in"
    bl_label = "Magnify In"
    bl_description = "Enlarge what the viewport shows, as an image is enlarged: the camera does not move"


class BLENDA4D_OT_magnify_out(_Magnify, bpy.types.Operator):
    bl_idname = "blenda4d.magnify_out"
    bl_label = "Magnify Out"
    bl_description = "Make the enlarged picture smaller again; all the way out, the view is as it was"
    wheel, menu = 1.0 / STEP, 1.0 / 1.5


class BLENDA4D_OT_magnify_scroll(_Magnify, bpy.types.Operator):
    bl_idname = "blenda4d.magnify_scroll"
    bl_label = "Magnify"
    bl_description = "Enlarge what the viewport shows with two fingers on a trackpad"

    def factor(self, event):
        return 1.006 ** max(-120, min(120, event.mouse_y - event.mouse_prev_y))


class BLENDA4D_OT_magnify_pan(_InView, bpy.types.Operator):
    bl_idname = "blenda4d.magnify_pan"
    bl_label = "Move Magnified Picture"
    bl_description = "Drag the enlarged picture about; the camera does not move"
    bl_options = {"INTERNAL", "GRAB_CURSOR", "BLOCKING"}

    def invoke(self, context, event):
        self.at, self.button, self.area = (event.mouse_x, event.mouse_y), event.type, context.area
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            pan(context, self.area, event.mouse_x - self.at[0], event.mouse_y - self.at[1])
            self.at = (event.mouse_x, event.mouse_y)
        elif (event.type == self.button and event.value == "RELEASE") or event.type in {"ESC", "WINDOW_DEACTIVATE"}:
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class BLENDA4D_OT_magnify_reset(_InView, bpy.types.Operator):
    bl_idname = "blenda4d.magnify_reset"
    bl_label = "Reset Magnify"
    bl_description = "Show the view at its normal size again"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return super().poll(context) and (on(context.area.spaces.active) or
                                          context.area.spaces.active.region_3d.view_perspective == "CAMERA")

    def execute(self, context):
        sp = context.area.spaces.active
        if on(sp):
            leave(context.area)
        else:
            rv = sp.region_3d
            rv.view_camera_zoom, rv.view_camera_offset = _camera.pop(rv.as_pointer(), (0.0, (0.0, 0.0)))
            from . import camview
            camview.refit(rv)
        return {"FINISHED"}


# --- what it shows, and keeping it right -------------------------------------------------------------------------------------
def _draw():
    context = bpy.context
    area, region = context.area, context.region
    if area is None or region is None or region.type != "WINDOW":
        return
    sp = area.spaces.active
    e = entry(sp)
    if e is None:
        mag = camera_magnified(sp)
        if mag > 1.0005:
            _label(context, area, region, mag)
        return
    if not on(sp):                                         # something else changed the view: tidy up after this draw
        if not bpy.app.timers.is_registered(_tidy):
            bpy.app.timers.register(_tidy, first_interval=0.0)
        return
    ob = sp.camera                                         # orbiting moves its own transform; being in no scene, its
    if any(abs(a - b) > 1e-7 for x, y in zip(ob.matrix_basis, ob.matrix_world) for a, b in zip(x, y)):   # place does not follow
        if not bpy.app.timers.is_registered(_follow):
            bpy.app.timers.register(_follow, first_interval=0.0)
    _label(context, area, region, e["mag"])


def _label(context, area, region, mag):
    s = context.preferences.system.ui_scale
    text = f"Magnified {mag * 100:.0f}%"
    blf.size(0, 12 * s)
    w = blf.dimensions(0, text)[0]
    top = region.height
    for r in area.regions:
        if r.type in {"HEADER", "TOOL_HEADER"} and r.height > 1 and r.alignment == "TOP":
            top = min(top, r.y - region.y)
    x = (region.width - w) / 2
    strip._round_rect(x - 8 * s, top - 30 * s, x + w + 8 * s, top - 8 * s, 3 * s, (0.11, 0.11, 0.11, 0.8))
    blf.color(0, 0.86, 0.86, 0.86, 1.0)
    blf.position(0, x, top - 23 * s, 0)
    blf.draw(0, text)


def _follow():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D" and on(a.spaces.active):
                ob = a.spaces.active.camera
                ob.matrix_world = ob.matrix_basis.copy()
                a.tag_redraw()
    return None


def _tidy():
    """Viewports that stopped looking through their own camera get their settings back; stray cameras go."""
    wm = bpy.context.window_manager
    used = set()
    for w in wm.windows:
        for a in w.screen.areas:
            if a.type != "VIEW_3D" or not len(a.spaces):
                continue
            sp = a.spaces.active
            if entry(sp) is not None and not on(sp):
                leave(a)
            elif on(sp):
                used.add(entry(sp)["cam"])
    for ob in [o for o in bpy.data.objects if o.name.startswith(NAME) and o.name not in used]:
        cd = ob.data
        bpy.data.objects.remove(ob)
        if cd is not None and cd.users == 0:
            bpy.data.cameras.remove(cd)
    return None


@bpy.app.handlers.persistent
def _before_save(*_args):
    leave_all()


@bpy.app.handlers.persistent
def _loaded(*_args):
    _on.clear()
    _camera.clear()
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D" and a.spaces.active.camera is not None and a.spaces.active.camera.name.startswith(NAME):
                a.spaces.active.use_local_camera = False
                a.spaces.active.region_3d.view_perspective = "PERSP"
    _tidy()


@bpy.app.handlers.persistent
def _undone(*_args):
    """Undo can take the camera away under the view."""
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D" and entry(a.spaces.active) is not None and not on(a.spaces.active):
                leave(a)


classes = (BLENDA4D_OT_magnify_in, BLENDA4D_OT_magnify_out, BLENDA4D_OT_magnify_scroll, BLENDA4D_OT_magnify_pan, BLENDA4D_OT_magnify_reset)
HANDLERS = (("save_pre", _before_save), ("load_post", _loaded), ("undo_post", _undone), ("redo_post", _undone))


def register():
    for c in classes:
        bpy.utils.register_class(c)
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL"))
    for name, fn in HANDLERS:
        h = getattr(bpy.app.handlers, name)
        if fn not in h:
            h.append(fn)


def unregister():
    leave_all()
    _on.clear()
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), "WINDOW")
    if bpy.app.timers.is_registered(_tidy):
        bpy.app.timers.unregister(_tidy)
    for name, fn in HANDLERS:
        h = getattr(bpy.app.handlers, name)
        if fn in h:
            h.remove(fn)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
