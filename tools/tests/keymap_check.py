# Headless check of the Blenda 4D key map preset.
#   BLENDER_USER_CONFIG=<scratch> BLENDER_USER_SCRIPTS=<scratch> Blender -b --factory-startup --python tools/tests/keymap_check.py
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import blenda4d  # noqa: E402
from blenda4d import keymap, switch  # noqa: E402

FAIL = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAIL.append(what)


def find(kc, km_name, idname, key, **mods):
    km = kc.keymaps.get(km_name)
    for kmi in (km.keymap_items if km else ()):
        if kmi.idname == idname and kmi.type == key and kmi.active and \
                all(bool(getattr(kmi, m)) == bool(mods.get(m)) for m in ("shift", "ctrl", "alt", "oskey")):
            return kmi
    return None


def first(kc, km_name, key, **mods):
    """The first active item in a key map that answers this press (what Blender would run)."""
    km = kc.keymaps.get(km_name)
    for kmi in (km.keymap_items if km else ()):
        if kmi.type == key and kmi.active and kmi.value in ("PRESS", "CLICK", "ANY") and \
                (kmi.any or all(bool(getattr(kmi, m)) == bool(mods.get(m)) for m in ("shift", "ctrl", "alt", "oskey"))):
            return kmi
    return None


kcs = bpy.context.window_manager.keyconfigs
before = kcs.active.name                       # the key map before the add-on: what the Blender switch gives back
blenda4d.register()
check(kcs.active.name == "Blenda_4D", "turning the add-on on makes Blenda 4D the key map at once (active: %s)" % kcs.active.name)
# listed for as long as the add-on is installed, in either mode (keymap.add_preset_path)
check(any(os.path.isfile(os.path.join(d, "Blenda_4D.py")) for d in bpy.utils.preset_paths("keyconfig")),
      "preset listed once the add-on is on, before Blenda mode")
switch.set_mode(True)
listed = [os.path.join(d, f) for d in bpy.utils.preset_paths("keyconfig") for f in os.listdir(d) if f.endswith(".py")]
print("keyconfig presets:", [os.path.basename(p) for p in listed])
check(keymap.PRESET in listed, "Blenda_4D.py listed in preset_paths('keyconfig')")
check(bpy.path.display_name("Blenda_4D.py", title_case=False) == "Blenda 4D", "shown as 'Blenda 4D'")
check(kcs.active.name == "Blenda_4D", "Blenda mode on selects the Blenda 4D key map (active: %s)" % kcs.active.name)

# back to stock through the operator the Preferences dropdown uses, then to ours again
r = bpy.ops.preferences.keyconfig_activate(filepath=bpy.utils.preset_find("Blender", "keyconfig"))
check(r == {"FINISHED"} and kcs.active.name == "Blender", "keyconfig_activate(Blender) -> stock keys")
kc = kcs["Blender"]
check(find(kc, "Object Mode", "transform.resize", "S") is not None, "stock: S scales in Object Mode")
r = bpy.ops.preferences.keyconfig_activate(filepath=keymap.PRESET)
check(r == {"FINISHED"} and kcs.active.name == "Blenda_4D", "keyconfig_activate(Blenda_4D.py) works")
kc = kcs.active
mac = sys.platform == "darwin"
CMD = {"oskey": True} if mac else {"ctrl": True}

WANT = [
    ("3D View", "view3d.rotate", "LEFTMOUSE", {"alt": True}),
    ("3D View", "view3d.move", "MIDDLEMOUSE", {"alt": True}),
    ("3D View", "view3d.zoom", "RIGHTMOUSE", {"alt": True}),
    ("3D View", "view3d.move", "ONE", {}),
    ("3D View", "view3d.zoom", "TWO", {}),
    ("3D View", "view3d.rotate", "THREE", {}),
    ("3D View", "wm.tool_set_by_id", "E", {}),
    ("3D View", "wm.tool_set_by_id", "R", {}),
    ("3D View", "wm.tool_set_by_id", "T", {}),
    ("3D View", "wm.tool_set_by_id", "SPACE", {}),
    ("3D View", "wm.context_toggle_enum", "W", {}),
    ("3D View", "view3d.view_selected", "S", {}),
    ("3D View", "view3d.view_selected", "O", {}),
    ("3D View", "view3d.view_all", "H", {}),
    ("3D View", "blenda4d.view_persp", "F1", {}),
    ("3D View", "blenda4d.view_top", "F2", {}),
    ("3D View", "blenda4d.view_right", "F3", {}),
    ("3D View", "blenda4d.view_front", "F4", {}),
    ("3D View", "blenda4d.make_editable", "C", {}),
    ("Property Editor", "blenda4d.make_editable", "C", {}),
    ("3D View", "wm.call_menu", "C", {"alt": True}),
    ("Object Mode", "object.delete", "BACK_SPACE", {}),
    ("Object Mode", "object.delete", "DEL", {}),
    ("Object Mode", "object.select_all", "A", CMD),
    ("Object Mode", "object.select_all", "A", dict(CMD, shift=True)),
    ("Object Mode", "object.select_all", "A", {"shift": True}),
    ("Window", "render.render", "R", CMD),
    ("Window", "render.render", "R", {"shift": True}),
    ("Dopesheet", "action.view_all", "H", {}),
    ("Dopesheet", "action.view_selected", "S", {}),
    ("Dopesheet", "action.view_frame", "O", {}),
    ("Dopesheet", "wm.context_set_enum", "TAB", {}),
    ("Graph Editor", "graph.view_all", "H", {}),
    ("Graph Editor", "graph.view_selected", "S", {}),
    ("Graph Editor", "graph.view_frame", "O", {}),
    ("Graph Editor", "wm.context_set_enum", "TAB", {}),
    ("Dopesheet Generic", "screen.animation_play", "SPACE", {}),
]
for km_name, idname, key, mods in WANT:
    kmi = find(kc, km_name, idname, key, **mods)
    check(kmi is not None, f"{km_name}: {'+'.join([m for m in mods] + [key])} -> {idname}")
    top = first(kc, km_name, key, **mods)
    check(top is not None and top.idname == idname, f"   ...and nothing earlier in {km_name} takes it ({top and top.idname})")

check(find(kc, "3D View", "wm.tool_set_by_id", "E").properties.name == "builtin.move", "E = Move tool")
check(find(kc, "3D View", "blenda4d.view_front", "F4") is not None, "F4 = front view")
# defaults that would answer first in the viewport's mode key maps are gone
for km_name, key in (("Object Mode", "S"), ("Object Mode", "R"), ("Object Mode", "H"), ("Object Mode", "O"),
                     ("Mesh", "S"), ("Mesh", "R"), ("3D View Generic", "T"), ("Frames", "SPACE")):
    top = first(kc, km_name, key)
    check(top is None, f"{km_name}: bare {key} no longer taken by {top and top.idname}")
km = kc.keymaps["View3D Rotate Modal"]
check(not any(i.propvalue.startswith("AXIS_SNAP") for i in km.keymap_items), "orbit does not snap while Alt is held")
check(find(kc, "Window", "wm.save_mainfile", "S", **CMD) is not None, "untouched default: Save still works")
check(find(kc, "3D View", "transform.translate", "G") is not None or
      find(kc, "Object Mode", "transform.translate", "G") is not None, "untouched default: G still moves")

# Blender switch puts back the key map that was there before
switch.set_mode(False)
check(kcs.active.name == before, f"Blender switch restores '{before}' (active: {kcs.active.name})")
check(keymap.PRESET in [os.path.join(d, f) for d in bpy.utils.preset_paths("keyconfig") for f in os.listdir(d)],
      "preset still listed after the Blender switch (the add-on is still installed)")
check("Blenda_4D" not in kcs, "Blenda key configuration removed after Blender switch")
# a key map the person picked in Blenda mode is left alone by the switch
switch.set_mode(True)
bpy.ops.preferences.keyconfig_activate(filepath=bpy.utils.preset_find("Industry_Compatible", "keyconfig"))
switch.set_mode(False)
check(kcs.active.name == "Industry_Compatible", "a key map chosen in Preferences survives the Blender switch")
switch.set_mode(True)
check(kcs.active.name == "Blenda_4D", "Blenda mode on again selects Blenda 4D")
switch.set_mode(False)
check(kcs.active.name == "Industry_Compatible", "...and the switch back restores Industry Compatible")
blenda4d.unregister()
check(keymap.PRESET not in [os.path.join(d, f) for d in bpy.utils.preset_paths("keyconfig") for f in os.listdir(d)],
      "preset folder unregistered when the add-on is turned off")
print("KEYMAP CHECK", "PASSED" if not FAIL else "FAILED %d" % len(FAIL), flush=True)
