# SPDX-License-Identifier: GPL-3.0-or-later
"""The create column, drawn by Blenda 4D into the viewport's toolbar strip (moved to the viewport's right edge by
build.py). Blender keeps that strip at a fixed width when the window is resized, but lays its own buttons out with a
fixed panel inset (style.panelspace, 8 px x UI scale) that Python cannot change; drawing the column ourselves gives
thin margins. Same mechanics as Blender add-ons that draw their own strips: a POST_PIXEL draw handler paints the
cells, and operators placed in the strip's key map ("3D View Generic", see view3d_tools_region_init) take hover and
clicks there and pass every other event through.

Click a cell: run its button. Press and hold (or click the corner mark): open the group's menu. Rest on a cell: its
name shows beside the strip."""
import math
import os
import time

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import bars, icons, roles, switch

CELL = 48              # px at UI scale 1: as big as the tools column's buttons
SIDE = 4               # px between the strip's edge and the cells (Blender's own buttons sit 10 px in)
TOP = 4
GAP = 10               # between groups
RADIUS = 3
ICON = 0.65            # icon picture (it has its own padding) as a share of the cell
BG = (0.169, 0.169, 0.169, 1.0)        # 2b2b2b, the managers' background
CELL_BG = (0.239, 0.239, 0.239, 1.0)
DIVIDER = (0.19, 0.19, 0.19, 1.0)
HOVER = (0.33, 0.33, 0.33, 1.0)
PRESSED = (0.294, 0.294, 0.427, 1.0)   # 4b4b6d, Blenda's selection colour
MARK = (0.70, 0.70, 0.70, 1.0)
DIM = 0.35                             # alpha of a button with nothing behind it yet
HOLD_SECONDS = 0.28
CORNER = 10                            # px: the corner-mark zone that opens the menu at once
TIP_DELAY = 0.5
TIP_TEXT = 12
TIP_BG = (0.11, 0.11, 0.11, 0.97)
TIP_BORDER = (0.30, 0.30, 0.30, 1.0)
TIP_COLOR = (0.88, 0.88, 0.88, 1.0)

_state = {"hover": None, "pressed": None, "boxes": [], "region": None}
_tip = {}
_tex = {}
_handles = []
_keymaps = []


# --- drawing helpers ---------------------------------------------------------------------------------------------------
def _rect(x0, y0, x1, y1, color):
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(sh, "TRI_FAN", {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]})
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def _round_rect(x0, y0, x1, y1, r, color):
    pts = []
    for cx, cy, a0 in ((x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270)):
        for i in range(5):
            a = math.radians(a0 + i * 22.5)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    batch = batch_for_shader(sh, "TRI_FAN", {"pos": pts})
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)
    gpu.state.blend_set("NONE")


def _texture(path):
    """A picture icon as a GPU texture (loaded once, pixels kept, the image removed from the file)."""
    tex = _tex.get(path)
    if tex is None and os.path.exists(path):
        import numpy as np
        img = bpy.data.images.load(path, check_existing=False)
        w, h = img.size
        a = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(a)
        bpy.data.images.remove(img)
        tex = _tex[path] = gpu.types.GPUTexture((w, h), format="RGBA32F", data=gpu.types.Buffer("FLOAT", w * h * 4, a.tolist()))
    return tex


def _icon(path, x, y, size, alpha=1.0):
    tex = _texture(path)
    if tex is None:
        return
    sh = gpu.shader.from_builtin("IMAGE_COLOR")
    batch = batch_for_shader(sh, "TRI_FAN", {"pos": [(x, y), (x + size, y), (x + size, y + size), (x, y + size)],
                                             "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]})
    gpu.state.blend_set("ALPHA")
    sh.bind()
    sh.uniform_sampler("image", tex)
    sh.uniform_float("color", (1.0, 1.0, 1.0, alpha))
    batch.draw(sh)
    gpu.state.blend_set("NONE")


# --- the column ----------------------------------------------------------------------------------------------------
def _icon_path(name, icon, members):
    p = os.path.join(icons.DIR, f"{icon.lower()}__{name}.png")
    if os.path.exists(p):
        return p
    first = members[0][1]                                 # a member without its own picture: the group's first one
    return os.path.join(icons.DIR, f"{first.lower()}__{name}.png")


def _items():
    out = []
    for g in bars.CREATE_GROUPS:
        if g is None:
            out.append(None)
            continue
        name, members = g
        label, icon, op, props = members[min(bars._head.get(name, 0), len(members) - 1)]
        out.append({"group": name, "label": label, "op": op, "members": members, "path": _icon_path(name, icon, members)})
    return out


def _layout(region):
    """Cells as (x0, y0, x1, y1, item) in region pixels, top down; smaller cells when the strip is short."""
    s = bpy.context.preferences.system.ui_scale
    items = _items()
    n = sum(1 for it in items if it)
    gaps = sum(1 for it in items if it is None)
    cell = min(CELL * s, region.width - 2 * SIDE * s)    # as big as the tools column's, at every scale; when the
    total = n * cell + gaps * GAP * s + 2 * TOP * s       # strip is shorter it scrolls, as that column does
    high = region.height - _inset()
    _state["max_scroll"] = max(0.0, total - high)
    _state["scroll"] = min(max(_state.get("scroll", 0.0), 0.0), _state["max_scroll"])
    x0 = (region.width - cell) / 2
    y = high - TOP * s + _state["scroll"]
    boxes = []
    for it in items:
        if it is None:
            y -= GAP * s
            continue
        boxes.append((x0, y - cell, x0 + cell, y, it))
        y -= cell
    return boxes


def _strip_region(context):
    """The viewport's strip, or the column's own area (four views, or editors under the viewport)."""
    r, a = context.region, context.area
    if r is None or a is None:
        return False
    return (r.type == "TOOLS" and a.type == "VIEW_3D") or (r.type == "WINDOW" and roles.role(a) == "CREATE")


def _inset():
    """Its own area starts level with the viewport's header, the strip below it: the cells stay where they are."""
    ctx = bpy.context
    if ctx.region is None or ctx.region.type != "WINDOW" or roles.role(ctx.area) != "CREATE":
        return 0
    from . import build
    return build.view_top(ctx.window, ctx.area)


def _shows(area):
    return area.type == "VIEW_3D" or roles.role(area) in {"CREATE", "TL_EDIT"}


def _draw():
    context = bpy.context
    if not switch.is_on() or not _strip_region(context):
        return
    region = context.region
    s = context.preferences.system.ui_scale
    boxes = _layout(region)
    _state["boxes"], _state["region"] = boxes, region.as_pointer()
    _rect(0, 0, region.width, region.height, BG)
    runs = []
    for b in boxes:                                       # touching cells share one rounded button
        if runs and abs(runs[-1][-1][1] - b[3]) < 0.5:
            runs[-1].append(b)
        else:
            runs.append([b])
    for run in runs:
        _round_rect(run[0][0], run[-1][1], run[0][2], run[0][3], RADIUS * s, CELL_BG)
        for b in run[1:]:
            _rect(b[0], b[3] - 0.5, b[2], b[3] + 0.5, DIVIDER)
    for i, (x0, y0, x1, y1, it) in enumerate(boxes):
        if i == _state["pressed"]:
            _round_rect(x0, y0, x1, y1, RADIUS * s, PRESSED)
        elif i == _state["hover"]:
            _round_rect(x0, y0, x1, y1, RADIUS * s, HOVER)
        size = (x1 - x0) * ICON
        _icon(it["path"], x0 + (x1 - x0 - size) / 2, y0 + (y1 - y0 - size) / 2, size, 1.0 if it["op"] else DIM)
        if len(it["members"]) > 1:                        # the corner mark: press and hold for more
            m = 5 * s
            sh = gpu.shader.from_builtin("UNIFORM_COLOR")
            batch = batch_for_shader(sh, "TRIS", {"pos": [(x1 - m - 2, y0 + 2), (x1 - 2, y0 + 2), (x1 - 2, y0 + m + 2)]})
            gpu.state.blend_set("ALPHA")
            sh.bind()
            sh.uniform_float("color", MARK)
            batch.draw(sh)
            gpu.state.blend_set("NONE")
    if _state["scroll"] > 0 and _inset():                 # scrolled cells do not show through above the column
        _rect(0, region.height - _inset(), region.width, region.height, BG)


def _hit(region, x, y):
    if region.as_pointer() != _state.get("region") or y > region.height - _inset():
        return None, None
    for i, b in enumerate(_state["boxes"]):
        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            return i, b
    return None, None


def _redraw(context):
    for a in context.screen.areas:
        if _shows(a):
            a.tag_redraw()


# --- tooltip: the button's name beside the strip, over the viewport ---------------------------------------------------
def _tip_set(context, box):
    _tip.clear()
    if box is None:
        return
    region = context.region
    it = box[4]
    text = it["label"] + ("  (hold for more)" if len(it["members"]) > 1 else "")
    _tip.update(text=text, y=region.y + (box[1] + box[3]) / 2, x=region.x, t=time.time(), shown=False)
    if not bpy.app.timers.is_registered(_tip_tick):
        bpy.app.timers.register(_tip_tick, first_interval=TIP_DELAY)


def _tip_tick():
    if not _tip or _tip.get("shown"):
        return None
    if time.time() - _tip["t"] < TIP_DELAY:
        return 0.05
    _tip["shown"] = True
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if _shows(a):
                a.tag_redraw()
    return None


def _draw_tip():
    if not _tip.get("shown"):
        return
    region = bpy.context.region
    if region is None or region.type != "WINDOW":
        return
    s = bpy.context.preferences.system.ui_scale
    blf.size(0, TIP_TEXT * s)
    tw = blf.dimensions(0, _tip["text"])[0]
    w, h = tw + 14 * s, TIP_TEXT * s + 10 * s
    wx, wy = _tip["x"] - 6 * s - w, _tip["y"] - h / 2          # to the strip's left, level with the button
    rx, ry = wx - region.x, wy - region.y
    if rx > region.width or rx + w < 0 or ry > region.height or ry + h < 0:
        return
    _round_rect(rx, ry, rx + w, ry + h, 3 * s, TIP_BORDER)
    _round_rect(rx + 1, ry + 1, rx + w - 1, ry + h - 1, 2.5 * s, TIP_BG)
    gpu.state.blend_set("ALPHA")
    blf.color(0, *TIP_COLOR)
    blf.position(0, rx + 7 * s, ry + 7 * s, 0)
    blf.draw(0, _tip["text"])
    gpu.state.blend_set("NONE")


# --- input -----------------------------------------------------------------------------------------------------------
class BLENDA4D_OT_strip_hover(bpy.types.Operator):
    bl_idname = "blenda4d.strip_hover"
    bl_label = "Create column hover"
    bl_description = "Shows the name of the create button under the pointer"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        i, box = (None, None)
        if switch.is_on() and _strip_region(context):
            i, box = _hit(context.region, event.mouse_region_x, event.mouse_region_y)
        if i != _state["hover"]:
            _state["hover"] = i
            _tip_set(context, box)
            _redraw(context)
        return {"PASS_THROUGH"}


class BLENDA4D_OT_strip_click(bpy.types.Operator):
    """Click: add it. Press and hold: the whole group."""
    bl_idname = "blenda4d.strip_click"
    bl_label = "Create column click"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        if not switch.is_on() or not _strip_region(context):
            return {"PASS_THROUGH"}
        self.index, self.box = _hit(context.region, event.mouse_region_x, event.mouse_region_y)
        if self.box is None:
            return {"FINISHED"}                           # a click between cells does nothing
        _tip.clear()
        it = self.box[4]
        s = context.preferences.system.ui_scale
        x0, y0, x1, y1 = self.box[:4]
        many = len(it["members"]) > 1
        if many and event.mouse_region_x >= x1 - CORNER * s and event.mouse_region_y <= y0 + CORNER * s:
            return self._menu(context, it)
        _state["pressed"] = self.index
        _redraw(context)
        if not many:
            return self._run(context, it)
        self.t0 = time.time()
        self.timer = context.window_manager.event_timer_add(0.03, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        it = self.box[4]
        if event.type == "TIMER" and time.time() - self.t0 > HOLD_SECONDS:
            self._end(context)
            return self._menu(context, it)
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self._end(context)
            return self._run(context, it)
        if event.type in {"RIGHTMOUSE", "ESC"} or time.time() - self.t0 > 2.0:
            self._end(context)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _end(self, context):
        context.window_manager.event_timer_remove(self.timer)

    def _run(self, context, it):
        _state["pressed"] = None
        _redraw(context)
        if it["op"] is None:
            self.report({"INFO"}, it["label"] + ": not available yet")
            return {"CANCELLED"}
        bpy.ops.blenda4d.create("INVOKE_DEFAULT", group=it["group"])
        return {"FINISHED"}

    def _menu(self, context, it):
        _state["pressed"] = None
        _redraw(context)
        bpy.ops.wm.call_menu(name="BLENDA4D_MT_create_" + it["group"])
        return {"FINISHED"}


class BLENDA4D_OT_strip_scroll(bpy.types.Operator):
    """Scroll the create column when it is taller than the strip"""
    bl_idname = "blenda4d.strip_scroll"
    bl_label = "Create column scroll"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        if not switch.is_on() or not _strip_region(context) or not _state.get("max_scroll"):
            return {"PASS_THROUGH"}
        s = context.preferences.system.ui_scale
        if event.type == "TRACKPADPAN":
            step = (event.mouse_y - event.mouse_prev_y)
        else:
            step = (-1 if event.type == "WHEELUPMOUSE" else 1) * CELL * s
        _state["scroll"] = min(max(_state.get("scroll", 0.0) + step, 0.0), _state["max_scroll"])
        _state["hover"] = None
        _tip.clear()
        _redraw(context)
        return {"FINISHED"}


classes = (BLENDA4D_OT_strip_hover, BLENDA4D_OT_strip_click, BLENDA4D_OT_strip_scroll)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    for space, fn, kind in ((bpy.types.SpaceView3D, _draw, "TOOLS"), (bpy.types.SpaceView3D, _draw_tip, "WINDOW"),
                            (bpy.types.SpaceProperties, _draw, "WINDOW")):
        _handles.append((space, space.draw_handler_add(fn, (), kind, "POST_PIXEL"), kind))
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        for name, space in (("3D View Generic", "VIEW_3D"), ("Property Editor", "PROPERTIES")):
            km = kc.keymaps.new(name=name, space_type=space, region_type="WINDOW")
            _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_strip_click.bl_idname, "LEFTMOUSE", "PRESS", head=True)))
            _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_strip_hover.bl_idname, "MOUSEMOVE", "ANY", head=True)))
        kmv = kc.keymaps.new(name="View2D Buttons List", space_type="EMPTY", region_type="WINDOW")   # before the
        for ev in ("WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN"):                                # strip's scroll
            _keymaps.append((kmv, kmv.keymap_items.new(BLENDA4D_OT_strip_scroll.bl_idname, ev, "ANY", head=True)))
        kmw = kc.keymaps.new(name="Window", space_type="EMPTY", region_type="WINDOW")
        _keymaps.append((kmw, kmw.keymap_items.new(BLENDA4D_OT_strip_hover.bl_idname, "MOUSEMOVE", "ANY")))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    for space, h, kind in _handles:
        try:
            space.draw_handler_remove(h, kind)
        except ValueError:
            pass
    _handles.clear()
    _tex.clear()
    _tip.clear()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
