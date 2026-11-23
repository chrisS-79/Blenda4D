# SPDX-License-Identifier: GPL-3.0-or-later
"""The render region's own buttons, on its top edge at the right: Resume, Pause and Close.

Pausing a Cycles region keeps its picture as it is (Pause Preview); with EEVEE, which draws as it goes, it shows the
viewport's earlier display until Resume. Close takes the region away and puts the display back."""
import bpy


from . import strip

BUTTON, GAP, SPACE = 24, 3, 10               # px at scale 1
TIPS = {"RESUME": "Resume Render Region", "PAUSE": "Pause Render Region", "CLOSE": "Close Render Region"}
_state = {}                                  # SpaceView3D pointer -> {"paused", "shading" (before it was paused)}
_hover = [None]                              # (space pointer, button)
_handles = []
_keymaps = []


def _region(area):
    from .roles import alive
    if not alive(area):                                    # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == "WINDOW"), None)


def _through_camera(sp):
    from . import magnify
    return sp.region_3d is not None and sp.region_3d.view_perspective == "CAMERA" and not magnify.on(sp)


def box(context, area):
    """The region in region pixels (x0, y0, x1, y1), or None."""
    sp, region = area.spaces.active, _region(area)
    if sp.region_3d is None or region is None:
        return None
    from . import magnify
    if magnify.on(sp):
        return None
    if not _through_camera(sp):
        if not sp.use_render_border:
            return None
        w, h = region.width, region.height
        return (sp.render_border_min_x * w, sp.render_border_min_y * h, sp.render_border_max_x * w, sp.render_border_max_y * h)
    rd, scene = context.scene.render, context.scene
    cam = sp.camera if sp.use_local_camera else scene.camera
    if not rd.use_border or cam is None or cam.type != "CAMERA":
        return None
    from bpy_extras.view3d_utils import location_3d_to_region_2d as to2d
    pts = [to2d(region, sp.region_3d, cam.matrix_world.normalized() @ v) for v in cam.data.view_frame(scene=scene)]
    if any(p is None for p in pts):
        return None
    x0, x1 = min(p.x for p in pts), max(p.x for p in pts)
    y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
    return (x0 + rd.border_min_x * (x1 - x0), y0 + rd.border_min_y * (y1 - y0),
            x0 + rd.border_max_x * (x1 - x0), y0 + rd.border_max_y * (y1 - y0))


def paused(sp):
    return _state.get(sp.as_pointer(), {}).get("paused", False)


def live(sp):
    return sp.shading.type == "RENDERED" or paused(sp)


def _top(area, region):
    top = region.height
    for r in area.regions:
        if r.type in {"HEADER", "TOOL_HEADER"} and r.height > 1 and r.alignment == "TOP":
            top = min(top, r.y - region.y)
    return top


def _left(context, area):
    from . import toolcol
    return max((c[2] for c in toolcol.columns(context.window) if c[0] == area), default=0)


def buttons(context, area):
    """[(name, x0, y0, x1, y1)] on the region's top edge at the right, kept inside the viewport."""
    b = box(context, area)
    if b is None:
        return []
    region = _region(area)
    s = context.preferences.system.ui_scale
    n, g, sp = BUTTON * s, GAP * s, SPACE * s
    names = ["RESUME", "PAUSE", "CLOSE"] if live(area.spaces.active) else ["CLOSE"]
    total = n * len(names) + g * (len(names) - 1) + (sp if len(names) > 1 else 0)
    x1 = min(max(b[2], _left(context, area) + total + 4 * s), region.width - 4 * s)
    y0 = min(max(b[3] + 3 * s, 4 * s), _top(area, region) - n - 4 * s)
    out, x = [], x1 - total
    for name in names:
        if name == "CLOSE" and len(names) > 1:
            x += sp
        out.append((name, x, y0, x + n, y0 + n))
        x += n + g
    return out


# --- what the buttons do --------------------------------------------------------------------------------------------------
def pause(context, area, on):
    sp = area.spaces.active
    st = _state.setdefault(sp.as_pointer(), {"paused": False, "shading": None})
    if st["paused"] == on:
        return
    st["paused"] = on
    if context.scene.render.engine == "CYCLES" and hasattr(context.scene, "cycles"):
        context.scene.cycles.preview_pause = on
    elif on:
        from . import topbar
        st["shading"] = sp.shading.type
        before = topbar._state.get("render_view")
        sp.shading.type = before if before and before != "RENDERED" else "SOLID"
    elif st["shading"]:
        sp.shading.type, st["shading"] = st["shading"], None
    area.tag_redraw()


def close(context, area):
    from . import topbar
    sp = area.spaces.active
    was_live = live(sp)
    pause(context, area, False)
    _state.pop(sp.as_pointer(), None)
    if _through_camera(sp):
        context.scene.render.use_border = False
    sp.use_render_border = False
    if topbar._state.get("live_region") and was_live and sp.shading.type == "RENDERED":     # the display it started from
        sp.shading.type = topbar._state.get("render_view") or "SOLID"
        topbar._state["render_view"] = None
    topbar._state["live_region"] = False
    area.tag_redraw()


class _Mine:
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and box(context, context.area) is not None


class BLENDA4D_OT_region_resume(_Mine, bpy.types.Operator):
    bl_idname = "blenda4d.region_resume"
    bl_label = "Resume Render Region"
    bl_description = "Go on rendering the render region"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and paused(context.area.spaces.active)

    def execute(self, context):
        pause(context, context.area, False)
        return {"FINISHED"}


class BLENDA4D_OT_region_pause(_Mine, bpy.types.Operator):
    bl_idname = "blenda4d.region_pause"
    bl_label = "Pause Render Region"
    bl_description = "Stop rendering the render region for now"

    @classmethod
    def poll(cls, context):
        return super().poll(context) and live(context.area.spaces.active) and not paused(context.area.spaces.active)

    def execute(self, context):
        pause(context, context.area, True)
        return {"FINISHED"}


class BLENDA4D_OT_region_close(_Mine, bpy.types.Operator):
    bl_idname = "blenda4d.region_close"
    bl_label = "Close Render Region"
    bl_description = "Take the render region away"

    def execute(self, context):
        close(context, context.area)
        return {"FINISHED"}


# --- drawing --------------------------------------------------------------------------------------------------------------
def _draw():
    context = bpy.context
    area, region = context.area, context.region
    if area is None or region is None or region.type != "WINDOW":
        return
    shown = buttons(context, area)
    if not shown:
        return
    from . import anim as A
    sp, s = area.spaces.active, context.preferences.system.ui_scale
    is_paused = paused(sp)
    for name, x0, y0, x1, y1 in shown:
        lit = live(sp) and ((name == "PAUSE" and is_paused) or (name == "RESUME" and not is_paused))
        hot = _hover[0] == (sp.as_pointer(), name)
        strip._round_rect(x0, y0, x1, y1, 3 * s, strip.PRESSED if lit else strip.HOVER if hot else (0.16, 0.16, 0.16, 0.92))
        cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 0.24
        c = (0.9, 0.9, 0.9, 1.0)
        if name == "RESUME":
            A.tris([(cx - r * 0.8, cy - r), (cx - r * 0.8, cy + r), (cx + r, cy)], c)
        elif name == "PAUSE":
            for x in (cx - r * 0.55, cx + r * 0.55):
                A.rect(x - r * 0.28, cy - r, x + r * 0.28, cy + r, c)
        else:
            A.lines([(cx - r, cy - r), (cx + r, cy + r), (cx - r, cy + r), (cx + r, cy - r)], c, 1.8 * s)
    if _hover[0] and _hover[0][0] == sp.as_pointer():
        hit = next((b for b in shown if b[0] == _hover[0][1]), None)
        if hit:
            import blf
            text = TIPS[hit[0]]
            blf.size(0, strip.TIP_TEXT * s)
            w = blf.dimensions(0, text)[0] + 14 * s
            h = strip.TIP_TEXT * s + 10 * s
            x1 = min(region.width - 4 * s, hit[3])
            y0 = hit[2] - h - 4 * s
            strip._round_rect(x1 - w, y0, x1, y0 + h, 3 * s, strip.TIP_BORDER)
            strip._round_rect(x1 - w + 1, y0 + 1, x1 - 1, y0 + h - 1, 2.5 * s, strip.TIP_BG)
            blf.color(0, *strip.TIP_COLOR)
            blf.position(0, x1 - w + 7 * s, y0 + 7 * s, 0)
            blf.draw(0, text)


# --- input ------------------------------------------------------------------------------------------------------------------
def _under(context, event):
    area = context.area
    if area is None or area.type != "VIEW_3D" or context.region is None or context.region.type != "WINDOW":
        return None
    x, y = event.mouse_region_x, event.mouse_region_y
    return next((n for n, x0, y0, x1, y1 in buttons(context, area) if x0 <= x <= x1 and y0 <= y <= y1), None)


class BLENDA4D_OT_region_press(bpy.types.Operator):
    bl_idname = "blenda4d.region_press"
    bl_label = "Render Region button"
    bl_description = "Resume, pause or close the render region"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        name = _under(context, event)
        if event.type == "MOUSEMOVE":
            new = (context.area.spaces.active.as_pointer(), name) if name else None
            if new != _hover[0]:
                _hover[0] = new
                context.area.tag_redraw()
            return {"PASS_THROUGH"}
        if name is None:
            return {"PASS_THROUGH"}
        if name == "CLOSE":
            _hover[0] = None
            close(context, context.area)
        else:
            pause(context, context.area, name == "PAUSE")
        return {"FINISHED"}


classes = (BLENDA4D_OT_region_resume, BLENDA4D_OT_region_pause, BLENDA4D_OT_region_close, BLENDA4D_OT_region_press)


@bpy.app.handlers.persistent
def _loaded(_file):
    _state.clear()
    _hover[0] = None


def register():
    for c in classes:
        bpy.utils.register_class(c)
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL"))
    bpy.app.handlers.load_post.append(_loaded)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D", region_type="WINDOW")
        for kind, value in (("LEFTMOUSE", "PRESS"), ("MOUSEMOVE", "ANY")):
            _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_region_press.bl_idname, kind, value, head=True)))


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
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), "WINDOW")
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    _state.clear()
