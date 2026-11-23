# SPDX-License-Identifier: GPL-3.0-or-later
"""Blenda 4D key map, a key configuration preset (Preferences > Keymap).

Built the way Blender builds its own presets: Blender's default key map is generated, then Blenda 4D's
motion-design keys are put at the front of their key maps, and the default keys that would answer the same press
first are taken out. Every key Blender binds that is not listed below works as in Blender.
"""
import os

import bpy

DIRNAME, FILENAME = os.path.split(__file__)
IDNAME = os.path.splitext(FILENAME)[0]

# Where a key works, and which other key maps answer the same press before it (or alongside it) in that place.
VIEWPORT = ("3D View", "3D View Generic", "Object Mode", "Object Non-modal", "Mesh", "Curve", "Curves", "Armature",
            "Pose", "Lattice", "Metaball", "Point Cloud", "Grease Pencil Edit Mode")
VIEWPORT_TOOLS = "3D View Tool:"          # the active tool's key maps come before all of the above
TIMELINE = ("Dopesheet", "Dopesheet Generic", "Graph Editor", "Graph Editor Generic")
GLOBAL = ("Window", "Screen")
OBJECT_PANELS = ("Property Editor", "View2D Buttons List")

# Blenda 4D's keys: (key map, operator, event, properties).
# Ctrl keys also get a Cmd version on macOS (as in Blender's own presets).
KEYS = [
    # --- viewport navigation: hold Alt and drag with a mouse button, or hold 1 / 2 / 3 and move the mouse
    ("3D View", "view3d.rotate", {"type": "LEFTMOUSE", "value": "PRESS", "alt": True}, None),
    ("3D View", "view3d.move", {"type": "MIDDLEMOUSE", "value": "PRESS", "alt": True}, None),
    # middle drag orbits, a middle click switches between one view and four
    ("3D View", "view3d.rotate", {"type": "MIDDLEMOUSE", "value": "CLICK_DRAG"}, None),
    ("3D View", "blenda4d.quad_view", {"type": "MIDDLEMOUSE", "value": "CLICK"}, None),
    ("3D View", "view3d.zoom", {"type": "RIGHTMOUSE", "value": "PRESS", "alt": True}, None),
    # Alt+wheel zooms like the wheel alone; Ctrl+Alt+wheel (Cmd+Option on a Mac) magnifies the picture around the
    # pointer without moving the camera, and Ctrl+Alt+middle drag moves the magnified picture
    ("3D View", "view3d.zoom", {"type": "WHEELINMOUSE", "value": "PRESS", "alt": True}, [("delta", 1)]),
    ("3D View", "view3d.zoom", {"type": "WHEELOUTMOUSE", "value": "PRESS", "alt": True}, [("delta", -1)]),
    ("3D View", "blenda4d.magnify_in", {"type": "WHEELINMOUSE", "value": "PRESS", "ctrl": True, "alt": True}, None),
    ("3D View", "blenda4d.magnify_out", {"type": "WHEELOUTMOUSE", "value": "PRESS", "ctrl": True, "alt": True}, None),
    ("3D View", "blenda4d.magnify_scroll", {"type": "TRACKPADPAN", "value": "ANY", "ctrl": True, "alt": True}, None),
    ("3D View", "blenda4d.magnify_pan", {"type": "MIDDLEMOUSE", "value": "PRESS", "ctrl": True, "alt": True}, None),
    ("3D View", "view3d.move", {"type": "ONE", "value": "PRESS"}, None),
    ("3D View", "view3d.zoom", {"type": "TWO", "value": "PRESS"}, None),
    ("3D View", "view3d.rotate", {"type": "THREE", "value": "PRESS"}, None),
    # --- tools: E move, R rotate, T scale, Space back to selection
    ("3D View", "wm.tool_set_by_id", {"type": "E", "value": "PRESS"}, [("name", "builtin.move")]),
    ("3D View", "wm.tool_set_by_id", {"type": "R", "value": "PRESS"}, [("name", "builtin.rotate")]),
    ("3D View", "wm.tool_set_by_id", {"type": "T", "value": "PRESS"}, [("name", "builtin.scale")]),
    ("3D View", "wm.tool_set_by_id", {"type": "SPACE", "value": "PRESS"}, [("name", "builtin.select_box")]),
    # Ctrl+drag with the Move tool: copy the selected objects and move the copy (Edit Mode: nothing changes)
    ("3D View Tool: Move", "object.duplicate_move", {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "ctrl": True}, None),
    # --- selection tools: 9 Live (paint), 0 Rectangle, 8 Lasso
    ("3D View", "wm.tool_set_by_id", {"type": "NINE", "value": "PRESS"}, [("name", "builtin.select_circle")]),
    ("3D View", "wm.tool_set_by_id", {"type": "ZERO", "value": "PRESS"}, [("name", "builtin.select_box")]),
    ("3D View", "wm.tool_set_by_id", {"type": "EIGHT", "value": "PRESS"}, [("name", "builtin.select_lasso")]),
    # --- modelling (Edit Mode): K Knife, D Extrude, I Inset, B Bridge, M then a letter for the rest
    ("Mesh", "wm.tool_set_by_id", {"type": "K", "value": "PRESS"}, [("name", "builtin.knife")]),
    ("Mesh", "wm.tool_set_by_id", {"type": "D", "value": "PRESS"}, [("name", "builtin.extrude_region")]),
    ("Mesh", "wm.tool_set_by_id", {"type": "I", "value": "PRESS"}, [("name", "builtin.inset_faces")]),
    ("Mesh", "mesh.bridge_edge_loops", {"type": "B", "value": "PRESS"}, None),
    ("Mesh", "blenda4d.m_keys", {"type": "M", "value": "PRESS"}, None),
    # Enter: between the object and its points / edges / polygons (Edit Mode)
    ("3D View", "object.editmode_toggle", {"type": "RET", "value": "PRESS"}, None),
    # Alt+G: group the selected objects under a null; F5: four views
    ("Object Mode", "blenda4d.group", {"type": "G", "value": "PRESS", "alt": True}, None),
    ("Object Mode", "blenda4d.ungroup", {"type": "G", "value": "PRESS", "shift": True}, None),
    ("Property Editor", "blenda4d.group", {"type": "G", "value": "PRESS", "alt": True}, None),
    ("Property Editor", "blenda4d.ungroup", {"type": "G", "value": "PRESS", "shift": True}, None),
    ("3D View", "blenda4d.quad_view", {"type": "F5", "value": "PRESS"}, None),
    # F9: record a key for the selected objects (I is Inset in Edit Mode)
    ("Object Mode", "anim.keyframe_insert", {"type": "F9", "value": "PRESS"}, None),
    # Ctrl+C / Ctrl+V: polygons in Edit Mode (paste in Object Mode makes a new object), objects otherwise
    ("3D View", "blenda4d.copy", {"type": "C", "value": "PRESS", "ctrl": True}, None),
    ("3D View", "blenda4d.paste", {"type": "V", "value": "PRESS", "ctrl": True}, None),
    # W: move along the world axes or the object's own axes
    ("3D View", "wm.context_toggle_enum", {"type": "W", "value": "PRESS"},
     [("data_path", "scene.transform_orientation_slots[0].type"), ("value_1", "GLOBAL"), ("value_2", "LOCAL")]),
    # --- framing: S, O and F frame the selection, H frames everything
    ("3D View", "view3d.view_selected", {"type": "S", "value": "PRESS"}, None),
    ("3D View", "view3d.view_selected", {"type": "O", "value": "PRESS"}, None),
    ("3D View", "view3d.view_selected", {"type": "F", "value": "PRESS"}, None),
    ("3D View", "view3d.view_all", {"type": "H", "value": "PRESS"}, None),
    # --- Undo View / Redo View: Ctrl+Shift+Z / Ctrl+Shift+Y over a viewport. On a Mac these are the real Ctrl key only
    # (see NO_CMD): Cmd+Shift+Z stays redo. Elsewhere Ctrl+Shift+Z is redo too, so redo is also on Ctrl+Y everywhere.
    ("3D View", "blenda4d.view_undo", {"type": "Z", "value": "PRESS", "ctrl": True, "shift": True, "repeat": True}, None),
    ("3D View", "blenda4d.view_redo", {"type": "Y", "value": "PRESS", "ctrl": True, "shift": True, "repeat": True}, None),
    ("Screen", "ed.redo", {"type": "Y", "value": "PRESS", "ctrl": True, "repeat": True}, None),
    # --- views: F1 perspective, F2 top, F3 right, F4 front
    ("3D View", "blenda4d.view_persp", {"type": "F1", "value": "PRESS"}, None),
    ("3D View", "blenda4d.view_top", {"type": "F2", "value": "PRESS"}, None),
    ("3D View", "blenda4d.view_right", {"type": "F3", "value": "PRESS"}, None),
    ("3D View", "blenda4d.view_front", {"type": "F4", "value": "PRESS"}, None),
    # --- C: make the selected objects editable (their live result becomes a plain mesh)
    ("3D View", "blenda4d.make_editable", {"type": "C", "value": "PRESS"}, None),
    ("Property Editor", "blenda4d.make_editable", {"type": "C", "value": "PRESS"}, None),
    ("View2D Buttons List", "blenda4d.make_editable", {"type": "C", "value": "PRESS"}, None),
    # Alt+C: the Create menu
    ("3D View", "wm.call_menu", {"type": "C", "value": "PRESS", "alt": True}, [("name", "BLENDA4D_MT_main_create")]),
    # --- delete without asking
    ("Object Mode", "object.delete", {"type": "BACK_SPACE", "value": "PRESS"}, [("use_global", False), ("confirm", False)]),
    ("Object Mode", "object.delete", {"type": "DEL", "value": "PRESS"}, [("use_global", False), ("confirm", False)]),
    # --- selection: Ctrl+A all, Ctrl+Shift+A none, Shift+A invert
    ("Object Mode", "object.select_all", {"type": "A", "value": "PRESS", "ctrl": True}, [("action", "SELECT")]),
    ("Object Mode", "object.select_all", {"type": "A", "value": "PRESS", "ctrl": True, "shift": True}, [("action", "DESELECT")]),
    ("Object Mode", "object.select_all", {"type": "A", "value": "PRESS", "shift": True}, [("action", "INVERT")]),
    # --- render: Ctrl+R renders the active view, Shift+R renders the scene into the render window
    ("Window", "render.render", {"type": "R", "value": "PRESS", "ctrl": True}, [("use_viewport", True)]),
    ("Window", "render.render", {"type": "R", "value": "PRESS", "shift": True}, None),
    # --- timeline (Dope Sheet and Graph Editor): H frame all, S frame selected keys, O frame the current frame,
    # Tab switches between keys and curves, Space plays
    ("Dopesheet", "action.view_all", {"type": "H", "value": "PRESS"}, None),
    ("Dopesheet", "action.view_selected", {"type": "S", "value": "PRESS"}, None),
    ("Dopesheet", "action.view_frame", {"type": "O", "value": "PRESS"}, None),
    ("Dopesheet", "wm.context_set_enum", {"type": "TAB", "value": "PRESS"}, [("data_path", "area.type"), ("value", "GRAPH_EDITOR")]),
    ("Graph Editor", "graph.view_all", {"type": "H", "value": "PRESS"}, None),
    ("Graph Editor", "graph.view_selected", {"type": "S", "value": "PRESS"}, None),
    ("Graph Editor", "graph.view_frame", {"type": "O", "value": "PRESS"}, None),
    ("Graph Editor", "wm.context_set_enum", {"type": "TAB", "value": "PRESS"}, [("data_path", "area.type"), ("value", "DOPESHEET_EDITOR")]),
    ("Dopesheet Generic", "screen.animation_play", {"type": "SPACE", "value": "PRESS"}, None),
    ("Graph Editor Generic", "screen.animation_play", {"type": "SPACE", "value": "PRESS"}, None),
]

# Keys put first in their key map without taking any default key out (the default key still answers after ours):
# Ctrl+drag on the Move handle copies the selected objects, then the handle's own drag moves the copies.
ADD_FIRST = [
    ("Generic Gizmo Maybe Drag", "blenda4d.copy_for_drag", {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "ctrl": True}, None),
    ("Generic Gizmo Drag", "blenda4d.copy_for_drag", {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "ctrl": True}, None),
]

# Default keys taken out with no replacement in the same key map.
#   Space no longer plays everywhere (it picks the selection tool in the viewport; it still plays in the timeline).
#   Orbiting while Alt is held must not snap the view to the nearest side view.
#   Alt+wheel zooms the viewport instead of changing the frame.
REMOVE = [
    ("Frames", {"type": "WHEELUPMOUSE", "value": "PRESS", "alt": True}),
    ("Frames", {"type": "WHEELDOWNMOUSE", "value": "PRESS", "alt": True}),
    ("Frames", {"type": "SPACE", "value": "PRESS"}),
]
REMOVE_MODAL = {"View3D Rotate Modal": ("AXIS_SNAP_ENABLE", "AXIS_SNAP_DISABLE")}

NO_CMD = {"blenda4d.view_undo", "blenda4d.view_redo"}      # no Cmd version of these on a Mac

MODIFIERS = ("shift", "ctrl", "alt", "oskey")


def _signature(event):
    return (event.get("type"), tuple(bool(event.get(m)) for m in MODIFIERS), bool(event.get("any")))


def _clashes(event, other):
    """True when a default item answers the same press as one of ours."""
    if other.get("value") == "DOUBLE_CLICK" or other.get("type") != event.get("type"):
        return False
    if other.get("any"):
        return True
    return _signature(other)[1] == _signature(event)[1]


def _shadows(km_name, all_names):
    for group in (VIEWPORT, TIMELINE, GLOBAL, OBJECT_PANELS):
        if km_name in group:
            names = set(group)
            if group is VIEWPORT:
                names |= {n for n in all_names if n.startswith(VIEWPORT_TOOLS)}
            if km_name in ("Dopesheet", "Graph Editor"):          # each timeline editor only shadows its own maps
                names = {n for n in names if n.startswith(km_name.split()[0])}
            return names
    return {km_name}


def _default_module():
    path = os.path.join(bpy.utils.system_resource("SCRIPTS"), "presets", "keyconfig", "keymap_data", "blender_default.py")
    return bpy.utils.execfile(path)


def generate_keymaps():
    """Blender's default key map data with Blenda 4D's keys on top (the format of bl_keymap_utils.io)."""
    default = _default_module()
    inputs = bpy.context.preferences.inputs
    emulate = inputs.use_mouse_emulate_3_button and inputs.mouse_emulate_3_button_modifier == "ALT"
    data = default.generate_keymaps(default.Params(
        select_mouse="LEFT",
        use_mouse_emulate_3_button=emulate,
        spacebar_action="PLAY",
        use_gizmo_drag=True,
        use_fallback_tool=True,
        use_fallback_tool_select_handled=False,
    ))
    by_name = {name: content for name, _args, content in data}
    names = list(by_name)

    for km_name, event in REMOVE:
        content = by_name.get(km_name)
        if content:
            content["items"] = [it for it in content["items"] if not _clashes(event, it[1])]
    for km_name, values in REMOVE_MODAL.items():
        content = by_name.get(km_name)
        if content:
            content["items"] = [it for it in content["items"] if it[0] not in values]

    ours = {}
    for km_name, idname, event, props in KEYS:
        ours.setdefault(km_name, []).append((idname, dict(event), {"properties": list(props)} if props else None))
        for other in _shadows(km_name, names):
            content = by_name.get(other)
            if content:
                content["items"] = [it for it in content["items"] if not _clashes(event, it[1])]
    for km_name, idname, event, props in ADD_FIRST:
        ours.setdefault(km_name, []).append((idname, dict(event), {"properties": list(props)} if props else None))
    for km_name, items in ours.items():
        content = by_name.get(km_name)
        if content is not None:
            content["items"] = items + content["items"]
    return data


def load():
    from sys import platform
    from bl_keymap_utils.io import keyconfig_init_from_data

    kc = bpy.context.window_manager.keyconfigs.new(IDNAME)
    data = generate_keymaps()
    if platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        data = keyconfig_data_oskey_from_ctrl_for_macos(data)
        for _name, _args, content in data:
            content["items"] = [it for it in content["items"] if not (it[0] in NO_CMD and it[1].get("oskey"))]
    keyconfig_init_from_data(kc, data)


if __name__ == "__main__":
    load()
