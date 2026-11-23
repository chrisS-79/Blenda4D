# SPDX-License-Identifier: GPL-3.0-or-later
"""The Node Editor window: one material's nodes in a window of their own.

  menu row      Create, Edit, View, Node, Select | + (add a node) | the material | Search (find a node)
  node canvas   Blender's shader node editor, pinned to this material, with a live preview on every node
  right panel   the material's preview, then the settings of the node you click (Blender's own controls, in
                sections); with no node picked, the material's page as in the Attribute Manager

Opened by double-clicking a material in the Material Manager, or Open Node Editor on the material page. The window's
screen carries the material's name (KEY), which is how the header and the panel know they are in this window."""
import bpy

from . import roles, own_draw

KEY = "b4d_node_window"
CATEGORY = "Blenda 4D"
_own_header = [None]


def material_of(screen):
    """The material this Node Editor window shows: the one whose nodes are on its canvas (it follows the active
    object's material, like Blender's own editor), or the one it was opened for."""
    if screen is None or not screen.get(KEY):
        return None
    for a in screen.areas:
        if a.type == "NODE_EDITOR":
            tree = a.spaces.active.node_tree
            if tree is not None:
                for m in bpy.data.materials:
                    if m.node_tree == tree:
                        return m
    return bpy.data.materials.get(screen.get(KEY))


def _show_on_object(context, mat):
    """Make an object that uses mat the active one, with mat its active slot. Blender draws the previews on nodes
    only when the editor is not pinned, so the window follows the active object's material. False: nothing uses it."""
    vl = context.view_layer
    cands = [vl.objects.active] + [o for o in context.selected_objects] + list(vl.objects)
    for ob in cands:
        if ob is None:
            continue
        for i, slot in enumerate(getattr(ob, "material_slots", ())):
            if slot.material == mat:
                if vl.objects.active != ob:
                    for o in context.selected_objects:
                        o.select_set(False)
                    ob.select_set(True)
                    vl.objects.active = ob
                ob.active_material_index = i
                return True
    return False


def _previews_on(tree):
    for n in tree.nodes:
        if hasattr(n, "show_preview") and not n.show_preview and n.type not in {"FRAME", "REROUTE", "GROUP_INPUT",
                                                                                 "GROUP_OUTPUT"}:
            try:
                n.show_preview = True
            except (AttributeError, TypeError):
                pass


def _region(area, kind):
    if not roles.alive(area):                              # freed: reading it would crash
        return None
    return next((r for r in area.regions if r.type == kind), None)


def open_window(context, mat):
    """Open (or bring back) the Node Editor window for mat. True when it opened."""
    if not mat.use_nodes:
        mat.use_nodes = True
    wm = context.window_manager
    on_object = _show_on_object(context, mat)
    for w in wm.windows:                                  # already open: it now shows this material
        if w.screen.get(KEY):
            w.screen[KEY] = mat.name
            for a in w.screen.areas:
                if a.type == "NODE_EDITOR":
                    sp = a.spaces.active
                    sp.pin = not on_object
                    if not on_object:
                        sp.node_tree = mat.node_tree
                    a.tag_redraw()
            return True
    win = context.window or wm.windows[0]
    area = context.area if context.area is not None else max(win.screen.areas, key=lambda a: a.width * a.height)
    before = {w.as_pointer() for w in wm.windows}
    with context.temp_override(window=win, screen=win.screen, area=area):
        bpy.ops.wm.window_new()
    new = next((w for w in wm.windows if w.as_pointer() not in before), None)
    if new is None:
        return False
    new.screen[KEY] = mat.name
    ar = new.screen.areas[0]
    ar.type = "NODE_EDITOR"
    ar.ui_type = "ShaderNodeTree"
    sp = ar.spaces.active
    sp.shader_type = "OBJECT"
    if not on_object:                                     # nothing uses it: pinned (Blender draws no node previews then)
        sp.pin = True
        sp.node_tree = mat.node_tree
    sp.show_region_ui = True
    sp.show_region_toolbar = False
    sp.overlay.show_previews = True
    if hasattr(sp.overlay, "preview_shape"):
        sp.overlay.preview_shape = "3D"                   # a ball above each node
    if hasattr(sp.overlay, "show_context_path"):
        sp.overlay.show_context_path = False             # no "Shader Nodetree" path in the corner
    _previews_on(mat.node_tree)

    def settle(tries=[30]):
        tries[0] -= 1
        if not roles.alive(ar):
            return None
        try:
            reg = _region(ar, "WINDOW")
            side = _region(ar, "UI")
            if reg is None or reg.width < 2:
                return 0.05 if tries[0] > 0 else None
            if side is not None:
                try:
                    side.active_panel_category = CATEGORY
                except (TypeError, ValueError):
                    pass
            with bpy.context.temp_override(window=new, area=ar, region=reg):
                bpy.ops.node.view_all()
        except (ReferenceError, RuntimeError):
            pass
        return None
    bpy.app.timers.register(settle, first_interval=0.1)

    def reframe():                                        # again once the previews above the nodes are drawn
        if not roles.alive(ar):
            return None
        try:
            reg = _region(ar, "WINDOW")
            with bpy.context.temp_override(window=new, area=ar, region=reg):
                bpy.ops.node.view_all()
                for _ in range(2):                        # framing leaves out the previews above the nodes
                    bpy.ops.view2d.zoom_out()
        except (ReferenceError, RuntimeError, TypeError):
            pass
        return None
    bpy.app.timers.register(reframe, first_interval=2.5)
    _keep_previews()
    return True


def _keep_previews():
    """While a Node Editor window is open, nodes added there show their preview too."""
    if bpy.app.timers.is_registered(_tick):
        return
    bpy.app.timers.register(_tick, first_interval=1.0)


def _tick():
    open_ = False
    for w in bpy.context.window_manager.windows:
        from . import nodetabs
        mat = material_of(w.screen) or nodetabs.material_of(w.screen)
        if mat is not None and mat.node_tree is not None:
            open_ = True
            _previews_on(mat.node_tree)
    return 1.0 if open_ else None


# --- the menu row ---------------------------------------------------------------------------------------------------

class BLENDA4D_MT_nodewin_edit(bpy.types.Menu):
    bl_label = "Edit"

    def draw(self, context):
        lay = self.layout
        lay.operator("ed.undo", text="Undo")
        lay.operator("ed.redo", text="Redo")
        lay.separator()
        lay.operator("node.clipboard_copy", text="Copy")
        lay.operator("node.clipboard_paste", text="Paste")
        lay.operator("node.duplicate_move", text="Duplicate")
        lay.operator("node.delete", text="Delete")
        lay.separator()
        lay.operator("node.select_all", text="Select All").action = "SELECT"
        lay.operator("node.select_all", text="Deselect All").action = "DESELECT"


def _header(self, context):
    mat = material_of(context.screen)
    if mat is None:
        from . import nodetabs
        if nodetabs.docked(context):
            return nodetabs.node_header(self, context)
        return _own_header[0](self, context)
    lay = self.layout
    row = lay.row(align=True)
    row.menu("NODE_MT_add", text="Create")
    row.menu("BLENDA4D_MT_nodewin_edit", text="Edit")
    row.menu("NODE_MT_view", text="View")
    row.menu("NODE_MT_node", text="Node")
    row.menu("NODE_MT_select", text="Select")
    lay.separator(factor=2)
    lay.menu("NODE_MT_add", text="", icon="ADD")
    lay.label(text=mat.name, icon_value=lay.icon(mat))
    lay.separator_spacer()
    lay.operator("node.find_node", text="Search", icon="VIEWZOOM")


# --- the right panel ------------------------------------------------------------------------------------------------

class BLENDA4D_PT_nodewin(bpy.types.Panel):
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "Node"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        from . import nodetabs
        return material_of(context.screen) is not None or nodetabs.docked(context)

    def draw(self, context):
        from . import nodetabs
        mat = material_of(context.screen) or nodetabs.material_of(context.screen)
        lay = self.layout
        if mat is None:
            return nodetabs.node_panel(lay, context)
        tree = mat.node_tree
        node = tree.nodes.active if tree is not None else None
        if node is not None and (not node.select or node.type in {"OUTPUT_MATERIAL", "FRAME", "REROUTE"}):
            node = None
        head = lay.row()
        head.label(text=f"Material [{mat.name}]", icon_value=lay.icon(mat))
        lay.template_preview(mat, show_buttons=False)     # live ball on the checker floor (full width: never cropped)
        from . import matpage
        if node is None:
            matpage.draw_material(lay, context, mat, head=False)
            return
        lay.separator()
        lay.label(text=node.label or node.name, icon="NODE")
        matpage.draw_node(lay, context, node)


classes = (BLENDA4D_MT_nodewin_edit, BLENDA4D_PT_nodewin)


# --- one card per node: a frame behind each preview and its node --------------------------------------------------
# Blender draws a node's preview above the node, on its own. Behind both (BACKDROP, under the nodes) Blenda paints a
# frame in the node's colour from the node's top edge up around the preview, so preview and node read as one card.
PREVIEW_PAD = 6           # px around the preview (at UI scale 1)
_frame_handle = []


def _ui():
    sysp = bpy.context.preferences.system
    return max(0.5, sysp.ui_scale * sysp.pixel_size)


def _node_rect(node, s):
    loc = getattr(node, "location_absolute", None) or node.location
    x0, y1 = loc.x * s, loc.y * s
    return x0, y1 - node.dimensions.y, x0 + node.dimensions.x, y1


def _draw_frames():
    ctx = bpy.context
    from . import nodetabs
    if material_of(ctx.screen) is None and nodetabs.material_of(ctx.screen) is None:
        return
    sp, reg = ctx.space_data, ctx.region
    if sp is None or reg is None or not sp.overlay.show_previews or not sp.overlay.show_overlays:
        return
    tree = sp.edit_tree
    if tree is None:
        return
    from .strip import _round_rect
    th = ctx.preferences.themes[0].node_editor
    body = tuple(th.node_backdrop)

    def rgba(c):
        return (*c[:3], 1.0)
    s = _ui()
    v2d = reg.view2d
    active = tree.nodes.active
    for node in tree.nodes:
        if not getattr(node, "show_preview", False) or node.hide or node.type in {"FRAME", "REROUTE"}:
            continue
        x0, _y0, x1, y1 = _node_rect(node, s)
        top = y1 + (x1 - x0) - 4 * s                     # the preview is about as tall as the node is wide
        ax, ay = v2d.view_to_region(x0, y1 - 12 * s, clip=False)
        bx, by = v2d.view_to_region(x1, top, clip=False)
        zoom = (bx - ax) / max(1.0, (x1 - x0))
        r = 4 * s * zoom
        if node.select:
            edge = rgba(th.node_active if node == active else th.node_selected)
            line = max(1.0, 1.5 * zoom * s)
        else:
            edge = rgba(th.wire)                          # unselected nodes have a dark edge
            line = max(1.0, 0.75 * zoom * s)
        _round_rect(ax - line, ay, bx + line, by + line, r + line, edge)
        _round_rect(ax, ay, bx, by, r, body)


# --- previews on nodes: Blender's experimental "Shader Node Previews" setting, on while Blenda mode is on -----------
def _memory_file():
    import os
    folder = bpy.utils.user_resource("CONFIG", path="blenda4d", create=True)
    return os.path.join(folder, "node_previews.json")


def _previews_setting(on):
    import json
    exp = getattr(bpy.context.preferences, "experimental", None)
    if exp is None or not hasattr(exp, "use_shader_node_previews"):
        return
    try:
        if on:
            if not exp.use_shader_node_previews:          # remember that Blenda turned it on, to turn it off again
                with open(_memory_file(), "w") as f:
                    json.dump({"turned_on": True}, f)
                exp.use_shader_node_previews = True
        else:
            try:
                with open(_memory_file()) as f:
                    turned_on = json.load(f).get("turned_on")
            except (OSError, ValueError):
                turned_on = False
            if turned_on:
                exp.use_shader_node_previews = False
                import os
                os.remove(_memory_file())
    except (OSError, AttributeError, TypeError):
        pass


def register():
    for c in classes:
        bpy.utils.register_class(c)
    _own_header[0] = own_draw.swap("NODE_HT_header", _header)
    _previews_setting(True)
    _frame_handle.append(bpy.types.SpaceNodeEditor.draw_handler_add(_draw_frames, (), "WINDOW", "BACKDROP"))


def unregister():
    while _frame_handle:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_frame_handle.pop(), "WINDOW")
    _previews_setting(False)
    if _own_header[0] is not None:
        own_draw.restore("NODE_HT_header", _header)
        _own_header[0] = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
