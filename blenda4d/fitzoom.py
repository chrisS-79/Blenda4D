# SPDX-License-Identifier: GPL-3.0-or-later
"""Strips keep their look when the window gets shorter: Blender squeezes an area's height with the window, but not the
buttons in it, which would be cut in half. Each strip is an area of its own, so Blender's own area zoom (Ctrl+scroll)
takes its whole content down together, in proportion, just enough to fit, and back up when there is room again."""
import bpy

from . import roles

#          role: (height it is built at, its normal zoom, the smallest share of that). The command bar's icons end up
#          no smaller than Blender's own toolbar icons, at the least height Blender gives an area.
STRIPS = {"PALETTE": (62, 1.726, 0.42), "DOC_TABS": (30, 1.0, 0.8), "OM_BAR": (30, 1.0, 0.8), "MM_BAR": (30, 1.0, 0.8),
          "AB_BAR": (30, 1.0, 0.8), "TIMELINE": (97, 1.0, 0.6), "TL_BAR": (64, 1.0, 0.75), "VIEW_TABS": (30, 1.0, 0.8), "PV_TOP": (60, 1.0, 0.75)}
_tried = {}                  # area -> (height, zoom asked for): asked once, whatever Blender makes of it
_pending = set()
_handles = []


def zoom_of(region):
    v = region.view2d
    x0, x1 = v.region_to_view(0, 0)[0], v.region_to_view(1000, 0)[0]
    return 1000.0 / (x1 - x0) if x1 > x0 else 1.0


def wanted(area, role):
    from . import build
    height, zoom, smallest = STRIPS[role]
    share = area.height / max(1.0, build.px(height))
    return zoom * min(1.0, max(smallest, share))


def _apply(window, area, region, zoom):
    with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
        bpy.ops.view2d.reset()
        if zoom > 1.001:                                  # Blender's zoom_in: new scale = 1 / (1 - 2 * fac)
            f = (1.0 - 1.0 / zoom) / 2.0
            bpy.ops.view2d.zoom_in(zoomfacx=f, zoomfacy=f)
        elif zoom < 0.999:
            f = (1.0 / zoom - 1.0) / 2.0
            bpy.ops.view2d.zoom_out(zoomfacx=-f, zoomfacy=-f)


def _watch():
    ctx = bpy.context
    area, region, window = ctx.area, ctx.region, ctx.window
    if area is None or region is None or region.type != "WINDOW" or window is None or region.width <= 1:
        return
    role = roles.role(area)
    if role not in STRIPS:
        return
    key, want = area.as_pointer(), wanted(area, role)
    if abs(zoom_of(region) / want - 1.0) < 0.03 or key in _pending or _tried.get(key) == (area.height, round(want, 3)):
        return
    _pending.add(key)

    def later():
        _pending.discard(key)
        try:
            if roles.role(area) == role:
                want_now = wanted(area, role)
                _tried[key] = (area.height, round(want_now, 3))
                _apply(window, area, region, want_now)
                area.tag_redraw()
        except (ReferenceError, RuntimeError, TypeError):
            pass
        return None
    bpy.app.timers.register(later, first_interval=0.0)


def register():
    _handles.append(bpy.types.SpaceProperties.draw_handler_add(_watch, (), "WINDOW", "POST_PIXEL"))


def unregister():
    while _handles:
        bpy.types.SpaceProperties.draw_handler_remove(_handles.pop(), "WINDOW")
    _tried.clear()
    _pending.clear()
