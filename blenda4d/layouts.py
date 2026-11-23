# SPDX-License-Identifier: GPL-3.0-or-later
"""Task tabs: the row of layouts at the right of the file tab, and their menu (also Window > Layouts).

A tab changes which panels show, never where one sits: tools on the left, the create column and the managers on the
right, new editors in the middle. Clicking a tab brings its saved arrangement back; Save Layout as keeps your own as
one more tab. Which tab a file shows is kept on its workspace, so it is there again when the file is opened."""
import json
import os

import bpy
from bpy_extras.io_utils import ImportHelper

from . import roles

KEY = "b4d_layout"
DEFAULT = "Layout"
#        name: (icon, what it is for, timeline shown, what is open under the viewport, Material Manager shown)
TABS = {
    "Layout": ("WORKSPACE", "General work: the viewport, the managers and the timeline", True, "", False),
    "Modeling": ("EDITMODE_HLT", "Building shapes: the timeline steps aside for a taller viewport", False, "", False),
    "Sculpting": ("SCULPTMODE_HLT", "Shaping like clay: the brushes in the tools column, their settings in Attributes", False, "", False),
    "UV Editing": ("UV", "Laying out texture coordinates: the UV Editor beside the viewport, with its tools below it", False, "UV", False),
    "Shading": ("SHADING_RENDERED", "Materials: the Node Editor opens under the viewport, and the Material Manager", False, "SHADER", True),
    "Animation": ("ANIM", "Movement: the Timeline opens under the viewport, with the Dope Sheet or the F-Curves", True, "KEYS", False),
    "Compositing": ("NODE_COMPOSITING", "Finishing: the result beside the viewport, the compositor's nodes below", False, "COMPOSITE", False),
    "Geometry Nodes": ("GEOMETRY_NODES", "Procedural objects: the spreadsheet beside the viewport, the nodes below", True, "GEOMETRY", False),
}
UNDER = ("", "KEYS", "SHADER", "COMPOSITE", "GEOMETRY", "UV")    # what can be open under the viewport (UV: beside it)
OLD_NAMES = {"Standard": DEFAULT}                          # the built-in layout's name before the tabs


# --- the files: saved layouts, the startup layout, the lock -------------------------------------------------------
def _file(name="layouts.json"):
    folder = bpy.utils.user_resource("CONFIG", path="blenda4d", create=True)
    return os.path.join(folder, name)


def _read(name):
    try:
        with open(_file(name), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(name, data):
    with open(_file(name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


_cache = {}


def load():
    if "layouts" not in _cache:
        _cache["layouts"] = {_free(k): v for k, v in _read("layouts.json").items() if isinstance(v, dict)}
    return _cache["layouts"]


def save(data):
    _write("layouts.json", data)
    _cache["layouts"] = data


def _free(name):
    """A saved layout may not share a tab's name (one saved before the tabs can)."""
    return name if name not in TABS and name not in OLD_NAMES else name + " (saved)"


def options():
    if "options" not in _cache:
        _cache["options"] = _read("layout_options.json")
    return _cache["options"]


def _set_option(key, value):
    data = dict(options())
    data[key] = value
    _write("layout_options.json", data)
    _cache["options"] = data


def locked():
    return bool(options().get("locked"))


def names():
    return list(TABS) + sorted(load())


def icon(name):
    return TABS[name][0] if name in TABS else "WINDOW"


# --- which layout a window shows ----------------------------------------------------------------------------------
def current(workspace):
    name = workspace.get(KEY, DEFAULT) if workspace is not None else DEFAULT
    return name if name in TABS or name in load() else DEFAULT


def spec(name):
    """{timeline, editors, materials, assets, sizes} of a layout."""
    entry = {} if name in TABS else load().get(name, {})
    return _spec(name if name in TABS else entry.get("base"), entry)


def _spec(base, entry):
    base = base if base in TABS else DEFAULT
    sizes = entry.get("sizes")
    editors = entry.get("editors", TABS[base][3])
    if editors not in UNDER:                               # saved before the node tabs: true or false
        editors = "KEYS" if editors else ""
    return {"base": base, "timeline": TABS[base][2] or editors == "KEYS", "editors": editors,
            "materials": bool(entry.get("materials", TABS[base][4])),
            "assets": bool(entry.get("assets")),
            "sizes": {k: float(v) for k, v in sizes.items() if isinstance(v, (int, float)) and v > 0} if isinstance(sizes, dict) else {}}


def workspace_of(screen):
    for w in bpy.context.window_manager.windows:
        if w.screen == screen:
            return w.workspace
    return next((ws for ws in bpy.data.workspaces if screen in list(ws.screens)), None)


DOCK = "b4d_dock"             # a workspace's own choice: the Timeline open or not, whatever its tab says


def spec_of(screen):
    ws = workspace_of(screen)
    out = spec(current(ws))
    if ws is not None and DOCK in ws:
        nodes = out["editors"] if out["editors"] != "KEYS" else ""      # a node tab has its nodes when it is folded away
        out["editors"] = "KEYS" if ws[DOCK] else nodes
        out["timeline"] = TABS[out["base"]][2] or out["editors"] == "KEYS"
    return out


def set_current(workspace, name):
    workspace[KEY] = name
    if DOCK in workspace:
        del workspace[DOCK]


def startup_spec():
    """The startup layout, when one was saved: what a new Blenda 4D workspace is built as."""
    entry = options().get("startup")
    return _spec(entry.get("base"), entry) if isinstance(entry, dict) else None


def snapshot(window):
    from . import build
    screen = window.screen
    s = build._scale()
    ws = window.workspace
    sizes = {}

    def width(role, key):
        a = next(iter(roles.areas(screen, role)), None)
        if a is not None:
            sizes[key] = round(a.width / s, 1)
        return a
    width("OBJECTS", "managers")
    width("MATERIALS", "materials")
    assets = width("ASSETS", "assets")
    if assets is not None and roles.areas(screen, "MODES"):    # always kept with the tools column's width in it
        from . import toolcol
        sizes["assets"] += toolcol.WIDTH
    attr = next(iter(roles.areas(screen, "ATTRIBUTES")), None)
    if attr is not None:
        whole = sum(a.height for r in ("OBJECTS", "OM_HEAD", "OM_BAR", "ATTRIBUTES") for a in roles.areas(screen, r))
        sizes["attributes"] = round(attr.height / max(1, whole + 2 * build.EDGE), 3)
    dock = roles.areas(screen, "TL_EDIT") + roles.areas(screen, "TL_BAR")
    views = [a for a in screen.areas if a.type == "VIEW_3D"]
    if len(dock) == 2 and views:
        high = sum(a.height for a in views if abs(a.x - views[0].x) < 8)
        mine = sum(a.height for a in dock) + build.EDGE
        sizes["editors"] = round((mine + 1) / max(1, mine + high + build.EDGE), 3)
    from . import nodetabs, uvtab
    nodetabs.sizes_of(screen, sizes)
    uvtab.sizes_of(screen, sizes)
    return {"base": spec(current(ws))["base"], "materials": bool(roles.areas(screen, "MATERIALS")),
            "assets": bool(roles.areas(screen, "ASSETS")), "editors": spec_of(screen)["editors"], "sizes": sizes}


# --- operators ----------------------------------------------------------------------------------------------------
class _Ready:
    @classmethod
    def poll(cls, context):
        from . import build, switch
        return not build.busy() and context.workspace is not None and context.workspace.name == switch.WORKSPACE


class BLENDA4D_OT_layout_use(_Ready, bpy.types.Operator):
    bl_idname = "blenda4d.layout_use"
    bl_label = "Use Layout"
    bl_description = "Switch to this layout"
    bl_options = {"INTERNAL"}
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        return TABS[props.name][1] if props.name in TABS else f"Your saved layout {props.name}"

    def execute(self, context):
        from . import build
        if self.name not in names():
            return {"CANCELLED"}
        build.run_steps(build.switch_steps(context.window, self.name))
        return {"FINISHED"}


class BLENDA4D_OT_layout_save(_Ready, bpy.types.Operator):
    bl_idname = "blenda4d.layout_save"
    bl_label = "Save Layout as"
    bl_description = "Save the current arrangement under a name; it becomes a tab"
    name: bpy.props.StringProperty(name="Name", default="My Layout")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        name = self.name.strip()
        if not name or name in TABS or name in OLD_NAMES:
            self.report({"WARNING"}, "Choose another name")
            return {"CANCELLED"}
        data = dict(load())
        data[name] = snapshot(context.window)
        save(data)
        set_current(context.workspace, name)
        _redraw()
        return {"FINISHED"}


class _Saved(_Ready):
    @classmethod
    def poll(cls, context):
        return super().poll(context) and current(context.workspace) not in TABS


class BLENDA4D_OT_layout_rename(_Saved, bpy.types.Operator):
    bl_idname = "blenda4d.layout_rename"
    bl_label = "Rename Layout"
    bl_description = "Give this saved layout another name"
    name: bpy.props.StringProperty(name="New Name")

    def invoke(self, context, event):
        self.name = current(context.workspace)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        data, old, name = dict(load()), current(context.workspace), self.name.strip()
        if old not in data or not name or name in TABS or name in OLD_NAMES or (name != old and name in data):
            self.report({"WARNING"}, "Choose another name")
            return {"CANCELLED"}
        data[name] = data.pop(old)
        save(data)
        set_current(context.workspace, name)
        _redraw()
        return {"FINISHED"}


class BLENDA4D_OT_layout_delete(_Saved, bpy.types.Operator):
    bl_idname = "blenda4d.layout_delete"
    bl_label = "Delete Layout"
    bl_description = "Delete this saved layout; its tab goes, and the window shows the layout it was made from"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        from . import build
        data, name = dict(load()), current(context.workspace)
        base = spec(name)["base"]
        data.pop(name, None)
        save(data)
        set_current(context.workspace, base)
        build.run_steps(build.switch_steps(context.window, base))
        return {"FINISHED"}


class BLENDA4D_OT_layout_reset(_Ready, bpy.types.Operator):
    bl_idname = "blenda4d.layout_reset"
    bl_label = "Reset to Default"
    bl_description = "Build the Layout tab again as it first was"

    def execute(self, context):
        from . import build
        set_current(context.workspace, DEFAULT)
        build.run_steps(build.steps(context.window))
        return {"FINISHED"}


class BLENDA4D_OT_layout_load(_Ready, bpy.types.Operator, ImportHelper):
    bl_idname = "blenda4d.layout_load"
    bl_label = "Load Layout"
    bl_description = "Add the layouts in a Blenda 4D layouts file (layouts.json) to your tabs"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            with open(self.filepath, encoding="utf-8") as f:
                new = json.load(f)
        except (OSError, ValueError):
            new = None
        good = {}
        for k, v in (new.items() if isinstance(new, dict) else ()):
            if isinstance(v, dict) and {"materials", "assets"} & set(v):
                good[_free(str(k))] = v
        if not good:
            self.report({"WARNING"}, "No Blenda 4D layouts in this file")
            return {"CANCELLED"}
        data = dict(load())
        for k, v in good.items():
            n, name = 2, k
            while name in data and data[name] != v:        # never over a layout of your own
                name, n = f"{k} {n}", n + 1
            data[name] = v
        save(data)
        _redraw()
        self.report({"INFO"}, "Added: " + ", ".join(sorted(good)))
        return {"FINISHED"}


class BLENDA4D_OT_layout_startup(_Ready, bpy.types.Operator):
    bl_idname = "blenda4d.layout_startup"
    bl_label = "Save as Startup Layout"
    bl_description = "New scenes start with the arrangement you see now"

    def execute(self, context):
        _set_option("startup", snapshot(context.window))
        self.report({"INFO"}, "New scenes start with this layout")
        return {"FINISHED"}


class BLENDA4D_OT_layout_lock(bpy.types.Operator):
    bl_idname = "blenda4d.layout_lock"
    bl_label = "Lock Layout"
    bl_description = "Keep the edges between panels from being dragged by accident"

    def execute(self, context):
        _set_option("locked", not locked())
        _redraw()
        return {"FINISHED"}


class BLENDA4D_OT_layout_edge(bpy.types.Operator):
    bl_idname = "blenda4d.layout_edge"
    bl_label = "Locked edge"
    bl_description = "Takes the click on an edge between panels while the layout is locked"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        from . import switch
        return locked() and context.workspace is not None and context.workspace.name == switch.WORKSPACE

    def invoke(self, context, event):
        x, y = event.mouse_x, event.mouse_y
        for a in context.screen.areas:                     # inside a region: not an edge
            for r in a.regions:
                if r.width > 1 and r.height > 1 and r.x < x < r.x + r.width - 1 and r.y < y < r.y + r.height - 1:
                    return {"PASS_THROUGH"}
        return {"FINISHED"}


class BLENDA4D_MT_layouts(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_layouts"
    bl_label = "Layouts"
    bl_description = "Switch, save and manage layouts"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"
        cur = current(context.workspace)
        for n in names():
            layout.operator("blenda4d.layout_use", text=n + ("  (shown)" if n == cur else ""), icon=icon(n)).name = n
        layout.separator()
        layout.operator("blenda4d.layout_load", text="Load Layout...", icon="FILE_FOLDER")
        layout.operator("blenda4d.layout_startup", text="Save as Startup Layout", icon="HOME")
        layout.operator("blenda4d.layout_save", text="Save Layout as...", icon="FILE_TICK")
        layout.operator("blenda4d.layout_rename", text="Rename Layout...", icon="GREASEPENCIL")
        layout.operator("blenda4d.layout_delete", text="Delete Layout...", icon="TRASH")
        layout.separator()
        layout.operator("blenda4d.layout_reset", text="Reset to Default", icon="LOOP_BACK")
        on = locked()
        layout.operator("blenda4d.layout_lock", text="Unlock Layout" if on else "Lock Layout", icon="LOCKED" if on else "UNLOCKED")


class BLENDA4D_MT_layouts_more(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_layouts_more"
    bl_label = "More"
    bl_description = "The tabs that do not fit in this window"

    def draw(self, context):
        for n in _more:
            self.layout.operator("blenda4d.layout_use", text=n, icon=icon(n)).name = n


# --- the row of tabs ------------------------------------------------------------------------------------------------
_more = []                   # the tabs in the > menu, set each time the row draws


def tab_units(name):
    """A tab's width in Blender's button units: its text and the room at its sides."""
    from . import menus
    return menus._text_width(name) / (20.0 * bpy.context.preferences.system.ui_scale) + 1.3


def fit(all_names, cur, free):
    """(tabs shown, tabs for the > menu) in `free` units. Tabs keep their size, and the one shown is always there."""
    if sum(tab_units(n) for n in all_names) <= free:
        return list(all_names), []
    free -= 1.2                                            # the > button
    used = tab_units(cur) if cur in all_names else 0.0
    shown = {cur}
    for n in all_names:
        if n != cur:
            used += tab_units(n)
            if used > free:
                break
            shown.add(n)
    return [n for n in all_names if n in shown], [n for n in all_names if n not in shown]


def draw_tabs(layout, context, free):
    cur = current(context.workspace)
    keep, rest = fit(names(), cur, free - 1.4)             # 1.4: the menu at the end
    _more[:] = rest
    row = layout.row(align=True)
    row.alignment = "RIGHT"
    for n in keep:
        b = row.row(align=True)
        b.ui_units_x = tab_units(n)
        b.operator("blenda4d.layout_use", text=n, depress=n == cur).name = n
    if rest:
        b = row.row(align=True)
        b.ui_units_x = 1.2
        b.emboss = "NONE"
        b.menu(BLENDA4D_MT_layouts_more.bl_idname, text="", icon="RIGHTARROW_THIN")
    b = row.row(align=True)
    b.ui_units_x = 1.4
    b.emboss = "NONE"
    b.menu(BLENDA4D_MT_layouts.bl_idname, text="", icon="THREE_DOTS")


def _redraw():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            a.tag_redraw()


_keymaps = []


classes = (BLENDA4D_OT_layout_use, BLENDA4D_OT_layout_save, BLENDA4D_OT_layout_rename, BLENDA4D_OT_layout_delete,
           BLENDA4D_OT_layout_reset, BLENDA4D_OT_layout_load, BLENDA4D_OT_layout_startup, BLENDA4D_OT_layout_lock,
           BLENDA4D_OT_layout_edge, BLENDA4D_MT_layouts, BLENDA4D_MT_layouts_more)


def register():
    _cache.clear()
    for c in classes:
        bpy.utils.register_class(c)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Screen Editing", space_type="EMPTY", region_type="WINDOW")
        _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_layout_edge.bl_idname, "LEFTMOUSE", "PRESS", head=True)))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
