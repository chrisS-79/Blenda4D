# SPDX-License-Identifier: GPL-3.0-or-later
"""The Sculpting and UV Editing tabs go into the mode they work in, and the next tab comes back out of it.

Only an object that can be edited is taken in (a primitive first has to be made editable), and only the mode the tab
itself chose is left again: one you picked stays yours."""
import bpy

KEY = "b4d_tab_mode"
MODES = {"Sculpting": "SCULPT", "UV Editing": "EDIT"}
NOW = {"SCULPT": "SCULPT", "EDIT": "EDIT_MESH"}


def editable(ob):
    return ob is not None and ob.type == "MESH" and "b4d_type" not in ob and ob.library is None and not ob.hide_get()


def _set(window, mode, message):
    from . import build, topbar
    view = build.biggest_view(window.screen)
    region = next((r for r in view.regions if r.type == "WINDOW"), None)
    with bpy.context.temp_override(window=window, screen=window.screen, area=view, region=region):
        bpy.ops.object.mode_set(mode=mode)
        if mode == "EDIT" and not bpy.context.tool_settings.mesh_select_mode[2]:
            bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.ed.undo_push(message=message)


def switched(window, old, new):
    """The window goes from one tab's base layout to another's."""
    ws, ob = window.workspace, window.view_layer.objects.active
    want, mine = MODES.get(new), ws.get(KEY, "")
    try:
        if mine and mine != want:
            del ws[KEY]
            if ob is not None and ob.mode == mine:
                _set(window, "OBJECT", "Model")
        if want:
            if want == "EDIT":
                bpy.context.scene.tool_settings.use_uv_select_sync = True      # one selection, in the viewport and the UV Editor
            if editable(ob) and ob.mode == "OBJECT":
                _set(window, want, "Sculpt" if want == "SCULPT" else "Polygons")
                ws[KEY] = want
            if want == "EDIT":
                window_manager_page(ob)
    except (RuntimeError, AttributeError, ReferenceError) as ex:
        print("Blenda 4D: the tab's mode", ex)


def window_manager_page(ob):
    """UV Editing shows the UV page in the Attribute Manager."""
    try:
        bpy.context.window_manager.b4d_am_tab = "UV"
    except TypeError:
        pass
