# SPDX-License-Identifier: GPL-3.0-or-later
"""Drag and drop from the Material Manager: drag a material onto an object's row in the Object Manager, or onto an
object in the 3D view, to give that object the material.

How it is wired: a CLICK_DRAG keymap item in the Property Editor starts blenda4d.mm_drag while the mouse is in the
Material Manager (the same way the Asset Browser's drag into the viewport and the Object Manager's own re-parent drag
work). The operator finds the material under the press, follows the mouse, and while it is over the Object Manager
highlights the row under it (a draw handler, like the Object Manager's own row highlights). Releasing over a row puts
the material in that object's first slot (a new slot when the object has none); releasing over the 3D view ray-casts
the surface under the mouse (like the Asset Browser's drop) and puts the material on the object hit — the same rule as
Shift-clicking a material in the list.
"""

import bpy

from . import managers, matman, roles

LIST_TOP = 4.9          # units from the panel's top to the first material row in the list and layer views (title,
#                         menus, tool row — the same head the icon view's GRID_TOP covers): measured in
#                         tools/tests/matdrag_ui.py


def _row_h(context):
    """Height of one material row in the list and layer views, in pixels: its preview plus the row padding.

    context: the UI context; reads the UI scale, pixel size and the preview-size setting from it.
    Returns the row height in pixels.
    """
    ui = context.preferences.system.ui_scale
    s = max(1.0, min(context.window_manager.b4d_mm_px, 80) / 20)
    return s * 20 * ui + 2 * context.preferences.system.pixel_size


def mat_at(context, x, y, region=None):
    """The material under a point in the Material Manager.

    context: the UI context; the current view (icons, list, layers), preview size and search filter decide the layout.
    x, y: the point in region coordinates (as event.mouse_region_x, event.mouse_region_y).
    region: the Material Manager's window region to map the point through; defaults to context.region.
    Returns the Material under the point, or None on empty space, the head, or outside the list.
    """
    wm = context.window_manager
    region = region or context.region
    if region is None or region.type != "WINDOW":
        return None
    if wm.b4d_mm_view == "ICONS":
        mat, _part = matman.tile_at(context, x, y)
        return mat
    mats = matman.materials(context)
    if not mats:
        return None
    unit = 20 * context.preferences.system.ui_scale
    _vx, vy = region.view2d.region_to_view(x, y)
    down = -vy                                  # view y runs down from 0 at the panel's top
    top = LIST_TOP * unit
    row_h = _row_h(context)
    tex_h = managers.row_height()
    for m in mats:
        h = row_h
        if wm.b4d_mm_view == "LAYERS":          # a layer-view row also holds the material's texture rows
            h += max(1, len(matman._textures(m))) * tex_h
        if top <= down < top + h:
            return m
        top += h
    return None


def assign(ob, mat):
    """Give an object a material: mat goes into its first slot, or a new slot is made when it has none.

    ob: the Object to receive the material (None is allowed and refused).
    mat: the Material to assign (None is allowed and refused).
    Returns True when the material was put on the object, False when the object takes no material.
    """
    if ob is None or mat is None or not hasattr(getattr(ob, "data", None), "materials"):
        return False
    if ob.data.materials:
        ob.data.materials[0] = mat
    else:
        ob.data.materials.append(mat)
    return True


def _role_under(context, role, x, y):
    """The window region of a role area (e.g. "MATERIALS") under a window position.

    context: the UI context; its window's screen holds the areas to search.
    role: the role the area must have (roles.role(area) == role).
    x, y: the window position (as event.mouse_x, event.mouse_y).
    Returns the area's WINDOW region under the point, or None.
    """
    for area in context.window.screen.areas:
        if roles.role(area) != role:
            continue
        for region in area.regions:
            if region.type == "WINDOW" and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return region
    return None


def _om_under(context, x, y):
    """The Object Manager's area and window region under a window position.

    context: the UI context; its window's screen holds the areas to search (None window gives (None, None)).
    x, y: the window position (as event.mouse_x, event.mouse_y).
    Returns (area, region) of the Object Manager under the point, or (None, None).
    """
    if context.window is None:
        return None, None
    for area in context.window.screen.areas:
        if roles.role(area) != "OBJECTS":
            continue
        for region in area.regions:
            if region.type == "WINDOW" and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return area, region
    return None, None


def _target(context, event):
    """The object whose Object Manager row is under the mouse.

    context: the UI context; the Object Manager search filter decides which rows exist.
    event: the mouse event; its window position (mouse_x, mouse_y) is mapped to a row.
    Returns the row object's name, or "" when the mouse is over no row.
    """
    _area, region = _om_under(context, event.mouse_x, event.mouse_y)
    if region is None:
        return ""
    rows = managers.visible_rows(context)
    i = managers.row_at(context, region, event.mouse_y)
    return rows[i][0].name if 0 <= i < len(rows) else ""


def _view_under(context, x, y):
    """A 3D view's area and window region under a window position.

    context: the UI context; its window's screen holds the areas to search (None window gives (None, None)).
    x, y: the window position (as event.mouse_x, event.mouse_y).
    Returns (area, region) of a 3D view under the point, or (None, None).
    """
    if context.window is None:
        return None, None
    for area in context.window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type == "WINDOW" and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                return area, region
    return None, None


def _view_target(context, event):
    """The object under the mouse in a 3D view: a ray-cast surface hit, like the Asset Browser's drop.

    context: the UI context; its scene and evaluated depsgraph are used for the ray cast.
    event: the mouse event; its window position (mouse_x, mouse_y) picks the ray.
    Returns the Object hit (the original, not an instance), or None on empty space or outside a 3D view.
    """
    from . import assets
    _area, region = _view_under(context, event.mouse_x, event.mouse_y)
    if region is None:
        return None
    _loc, ob = assets.drop_point(context, region, event.mouse_x, event.mouse_y)
    return ob


class BLENDA4D_OT_mm_drag(bpy.types.Operator):
    bl_idname = "blenda4d.mm_drag"
    bl_label = "Drag Material"
    bl_description = "Drag a material onto an object in the Object Manager or the 3D view to give the object that material"
    bl_options = {"UNDO", "INTERNAL"}
    mat_name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == "MATERIALS"

    def invoke(self, context, event):
        # CLICK_DRAG invokes on the first move, so the press position is where the material is looked up
        region = _role_under(context, "MATERIALS", event.mouse_prev_press_x, event.mouse_prev_press_y)
        mat = None
        if region is not None:
            mat = mat_at(context, event.mouse_prev_press_x - region.x, event.mouse_prev_press_y - region.y, region)
        if mat is None:
            return {"PASS_THROUGH"}
        self.mat_name = mat.name                # by name: the material could be deleted while dragging
        context.window_manager.b4d_mat_drop = ""
        context.window.cursor_modal_set("HAND")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _end(self, context):
        context.window_manager.b4d_mat_drop = ""
        context.window.cursor_modal_restore()
        for a in context.window.screen.areas:
            a.tag_redraw()

    def modal(self, context, event):
        wm = context.window_manager
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            t = _target(context, event)
            if t != wm.b4d_mat_drop:
                wm.b4d_mat_drop = t
                for a in context.window.screen.areas:
                    a.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            t = _target(context, event)
            ob = bpy.data.objects.get(t) if t else _view_target(context, event)
            self._end(context)
            if ob is None or not assign(ob, bpy.data.materials.get(self.mat_name)):
                return {"CANCELLED"}
            wm.b4d_material = self.mat_name
            matman._tag_redraw()
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"} or (event.type == "LEFTMOUSE" and event.value == "PRESS"):
            self._end(context)                  # a fresh press while dragging: cancel, never stay modal
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


_draw = []


def _draw_drop():
    """Highlight in the Object Manager the row a dragged material would land on, like its own row highlights."""
    context = bpy.context
    if roles.role(context.area) != "OBJECTS":
        return
    name = context.window_manager.b4d_mat_drop
    if not name:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    region = context.region
    rows = managers.visible_rows(context)
    i = next((i for i, (ob, _d) in enumerate(rows) if ob.name == name), None)
    if i is None or region is None:
        return
    h = managers.row_height()
    top = region.view2d.view_to_region(0, -(managers.rows_top() + i) * h, clip=False)[1]
    bottom = region.view2d.view_to_region(0, -(managers.rows_top() + i + 1) * h, clip=False)[1]
    c = context.preferences.themes[0].user_interface.wcol_regular.inner_sel
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ADDITIVE")            # lightens the row behind the text instead of covering it
    batch = batch_for_shader(shader, "TRIS", {"pos": [(0, bottom), (region.width, bottom), (region.width, top), (0, top)]},
                             indices=[(0, 1, 2), (0, 2, 3)])
    shader.uniform_float("color", (c[0] * 0.95, c[1] * 0.95, c[2] * 0.95, 1.0))
    batch.draw(shader)
    gpu.state.blend_set("NONE")


_keys = []

classes = (BLENDA4D_OT_mm_drag,)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.b4d_mat_drop = bpy.props.StringProperty(
        description="The Object Manager row a material dragged from the Material Manager would land on")
    _draw.append(bpy.types.SpaceProperties.draw_handler_add(_draw_drop, (), "WINDOW", "POST_PIXEL"))
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        km = kc.keymaps.new(name="Property Editor", space_type="PROPERTIES")
        _keys.append((km.name, km.keymap_items.new("blenda4d.mm_drag", "LEFTMOUSE", "CLICK_DRAG").idname))


def unregister():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:                           # looked up fresh: held keymap items can be freed at quit
        for name, idname in _keys:
            km = kc.keymaps.get(name)
            if km is not None:
                for kmi in list(km.keymap_items):
                    if kmi.idname == idname:
                        km.keymap_items.remove(kmi)
    _keys.clear()
    for h in _draw:
        bpy.types.SpaceProperties.draw_handler_remove(h, "WINDOW")
    _draw.clear()
    W = bpy.types.WindowManager
    if hasattr(W, "b4d_mat_drop"):
        delattr(W, "b4d_mat_drop")
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
