# SPDX-License-Identifier: GPL-3.0-or-later
"""Looking through a camera: the picture that will be rendered fills the viewport, and the part of the viewport outside
it is tinted. How much space is left around the picture, and the tint's colour and opacity, are on the camera's Object
page. They are kept in the file, and a new camera starts with the ones last chosen.

The picture is fitted when a viewport starts looking through a camera, when another camera or picture shape is picked,
and when the viewport changes size, as long as nobody has zoomed the picture since. The camera itself is not touched.
Blender keeps one tint colour, in its theme: it is the colour of the camera being looked through, and Blender's own
colour comes back when Blenda mode is turned off."""
import math

import bpy

from . import remember

FILE = "camera_view.json"
BLACK = (0.0, 0.0, 0.0)
_fitted = {}                 # RegionView3D pointer -> {"size", "shape", "cam", "zoom"}
_handles = []
_pending = [False]


def _region(area):
    from .roles import alive
    if not alive(area):                                    # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == "WINDOW"), None)


def _camera(scene, sp):
    ob = sp.camera if sp.use_local_camera else scene.camera
    return ob if ob is not None and ob.type == "CAMERA" else None


def _shape(scene, cam):
    r = scene.render
    w, h = r.resolution_x * r.pixel_aspect_x, r.resolution_y * r.pixel_aspect_y
    return round(w / max(1e-6, h), 4), cam.data.sensor_fit, round(room_of(cam.data), 4)


def room_of(data):
    return getattr(data, "b4d_room", 0.0)


# --- fitting -------------------------------------------------------------------------------------------------------------
def _wants(scene, area):
    """Is this viewport's picture to be fitted now?"""
    from . import magnify
    sp = area.spaces.active
    rv = sp.region_3d
    if rv is None:
        return False
    key = rv.as_pointer()
    if rv.view_perspective != "CAMERA" or magnify.on(sp):
        _fitted.pop(key, None)
        return False
    cam, region = _camera(scene, sp), _region(area)
    if cam is None or region is None or region.width < 2 or region.height < 2:
        return False
    st = _fitted.get(key)
    if st is None or st["cam"] != cam.name or st["room"] != room_of(cam.data):
        return True
    same = st["size"] == (region.width, region.height) and st["shape"] == _shape(scene, cam)
    return not same and abs(rv.view_camera_zoom - st["zoom"]) < 1e-3


def fit(window, area):
    from . import magnify, viewhistory
    scene, sp, region = window.scene, area.spaces.active, _region(area)
    rv, cam = sp.region_3d, _camera(scene, sp)
    if cam is None or region is None:
        return
    key = rv.as_pointer()
    entry = viewhistory._views.get(viewhistory._key(rv))
    still = entry is not None and entry["at"][0] == "CAMERA" and viewhistory.same(entry["at"], viewhistory.state(rv))
    magnify._camera.pop(key, None)
    with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
        bpy.ops.view3d.view_center_camera()                # Blender's own: the whole picture, edge to edge
    share = magnify._fac(rv.view_camera_zoom) * (1.0 - room_of(cam.data))
    rv.view_camera_zoom = max(-30.0, min(600.0, magnify._zoom_for(share)))
    _fitted[key] = {"size": (region.width, region.height), "shape": _shape(scene, cam), "cam": cam.name,
                    "room": room_of(cam.data), "zoom": rv.view_camera_zoom}
    if still:                                              # fitting again is not a view of its own for Undo View
        entry["at"] = entry["seen"] = viewhistory.state(rv)
    area.tag_redraw()


def _colour(scene, area):
    """The tint of the camera looked through is the one Blender draws."""
    sp = area.spaces.active
    rv = sp.region_3d
    from . import magnify
    if rv is None or rv.view_perspective != "CAMERA" or magnify.on(sp):
        return None
    cam = _camera(scene, sp)
    return tuple(cam.data.b4d_tint) if cam is not None else None


def _theme():
    return bpy.context.preferences.themes[0].view_3d


def _wrong(colour):
    return colour is not None and any(abs(a - b) > 0.004 for a, b in zip(colour, _theme().camera_passepartout))


def _paint(colour):
    if remember.get(FILE).get("blender_colour") is None:
        remember.put(FILE, "blender_colour", [round(v, 5) for v in _theme().camera_passepartout])
    _theme().camera_passepartout = colour


def _draw():
    ctx = bpy.context
    area, region, window = ctx.area, ctx.region, ctx.window
    if area is None or region is None or region.type != "WINDOW" or window is None or _pending[0]:
        return
    if _wants(ctx.scene, area) or _wrong(_colour(ctx.scene, area)):
        _pending[0] = True
        bpy.app.timers.register(_later, first_interval=0.0)


def _later():
    _pending[0] = False
    wm = bpy.context.window_manager
    painted = False
    for w in wm.windows if wm else ():
        for a in w.screen.areas:
            if a.type != "VIEW_3D" or not len(a.spaces):
                continue
            try:
                if _wants(w.scene, a):
                    fit(w, a)
                colour = _colour(w.scene, a)
                if not painted and _wrong(colour):         # two cameras on screen at once: the first one's
                    _paint(colour)
                painted = painted or colour is not None
            except (ReferenceError, RuntimeError, TypeError) as ex:
                print("Blenda 4D: camera view not fitted:", ex)
    return None


def redraw():
    wm = bpy.context.window_manager
    for w in wm.windows if wm else ():
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                a.tag_redraw()


def refit(rv):
    """Fit this viewport's picture again, whatever its zoom is now (Reset Magnify)."""
    _fitted.pop(rv.as_pointer(), None)
    redraw()


# --- the camera's options --------------------------------------------------------------------------------------------------
def _keep(data):
    remember.put(FILE, "room", round(data.b4d_room, 4))
    remember.put(FILE, "tint", [round(v, 4) for v in data.b4d_tint])
    remember.put(FILE, "on", data.show_passepartout)
    remember.put(FILE, "opacity", round(data.passepartout_alpha, 4))


_applying = [False]


def _changed(data, _context):
    if not _applying[0]:
        _keep(data)
    redraw()


def _alpha_set(data, v):
    data.passepartout_alpha = v
    if not _applying[0]:
        _keep(data)


def _on_set(data, v):
    data.show_passepartout = v
    if not _applying[0]:
        _keep(data)


def start(data):
    """A new camera's view options: the ones last chosen."""
    last = remember.get(FILE)
    _applying[0] = True
    try:
        if "room" in last:
            data.b4d_room = last["room"]
        if "tint" in last:
            data.b4d_tint = last["tint"]
        if "on" in last:
            data.show_passepartout = last["on"]
        if "opacity" in last:
            data.passepartout_alpha = last["opacity"]
    except (TypeError, ValueError):
        pass
    finally:
        _applying[0] = False


@bpy.app.handlers.persistent
def _loaded(path, *_args):
    _fitted.clear()
    _pending[0] = False
    if not path:                                           # a new file: its cameras too
        for data in bpy.data.cameras:
            start(data)


def register():
    C = bpy.types.Camera
    C.b4d_room = bpy.props.FloatProperty(
        name="Space Around Picture", subtype="FACTOR", default=0.0, min=0.0, max=0.5, update=_changed,
        description="How much of the viewport is left around the picture when looking through this camera: 0 fills the "
                    "viewport with it. The camera and the render are not changed")
    C.b4d_tint = bpy.props.FloatVectorProperty(
        name="Color", subtype="COLOR_GAMMA", size=3, default=BLACK, min=0.0, max=1.0, update=_changed,
        description="The color laid over the part of the viewport that will not be rendered (Blender: Passepartout)")
    C.b4d_tint_on = bpy.props.BoolProperty(
        name="Tinted Border", get=lambda s: s.show_passepartout, set=_on_set,
        description="Tint the part of the viewport that will not be rendered (Blender: Passepartout)")
    C.b4d_tint_opacity = bpy.props.FloatProperty(
        name="Opacity", subtype="FACTOR", min=0.0, max=1.0, get=lambda s: s.passepartout_alpha, set=_alpha_set,
        description="How opaque the tint is: 0 shows the scene outside the picture as it is, 1 hides it "
                    "(Blender: Passepartout Opacity)")
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL"))
    bpy.app.handlers.load_post.append(_loaded)


def unregister():
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), "WINDOW")
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    old = remember.get(FILE).get("blender_colour")
    if old is not None:
        try:
            _theme().camera_passepartout = old
        except (TypeError, ValueError):
            pass
        remember.put(FILE, "blender_colour", None)
    remember.stop()
    _fitted.clear()
    _pending[0] = False
    for n in ("b4d_room", "b4d_tint", "b4d_tint_on", "b4d_tint_opacity"):
        if hasattr(bpy.types.Camera, n):
            delattr(bpy.types.Camera, n)
