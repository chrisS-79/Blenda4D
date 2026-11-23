# SPDX-License-Identifier: GPL-3.0-or-later
"""Material Manager: menu row, tool row (New, Asset Browser, Apply, Pick, Delete, Delete Unused, Delete Duplicates,
Search), the materials as previews (Icon View), a list (List View) or a list with their textures (Layer View), and a
bottom strip with the three views and the preview size slider. Everything is Blender's own buttons and previews.

The bottom strip is an area of its own (role MM_BAR) under the Material Manager, because a panel cannot be pinned
to the bottom of its area."""
import bpy

from . import menus, roles

PX_MIN, PX_MAX = 20, 160
VIEWS = (("LIST", "List View", "Material names in a list", "LONGDISPLAY", 0),
         ("ICONS", "Icon View", "Material previews in a grid", "IMGDISPLAY", 1),
         ("LAYERS", "Layer View", "Material names in a list, each with the textures it uses", "RENDERLAYERS", 2))


def current(context):
    return bpy.data.materials.get(context.window_manager.b4d_material)


def materials(context):
    wm = context.window_manager
    out = [m for m in bpy.data.materials if not m.is_grease_pencil and not m.name.startswith(".")]
    out.reverse()                                     # newest first
    if wm.b4d_mm_search and wm.b4d_mm_filter:
        needle = wm.b4d_mm_filter.lower()
        out = [m for m in out if needle in m.name.lower()]
    return out


def remove_material(mat):
    """Unpin it from any node editor first: freeing a tree an editor still shows crashes the next draw."""
    tree = mat.node_tree
    for screen in bpy.data.screens:
        for a in screen.areas:
            for sp in a.spaces:
                if sp.type == "NODE_EDITOR" and tree is not None and sp.node_tree == tree:
                    sp.pin = False
                    sp.node_tree = None
            a.tag_redraw()
    bpy.data.materials.remove(mat)


def _put_on(ob, mat):
    if not hasattr(getattr(ob, "data", None), "materials"):
        return False
    if ob.data.materials:
        ob.data.materials[0] = mat
    else:
        ob.data.materials.append(mat)
    return True


def _tag_redraw():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if roles.role(a) in ("MATERIALS", "MM_BAR", "OBJECTS", "ATTRIBUTES"):
                a.tag_redraw()


class BLENDA4D_OT_mm_apply(bpy.types.Operator):
    bl_idname = "blenda4d.mm_apply"
    bl_label = "Apply Material"
    bl_description = "Put the selected material on the selected objects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return current(context) is not None and bool(context.selected_objects)

    def execute(self, context):
        mat = current(context)
        n = sum(_put_on(ob, mat) for ob in context.selected_objects)
        _tag_redraw()
        return {"FINISHED"} if n else {"CANCELLED"}


class BLENDA4D_OT_mm_pick(bpy.types.Operator):
    bl_idname = "blenda4d.mm_pick"
    bl_label = "Pick Material"
    bl_description = "Select the material of the active object"

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and bool(getattr(getattr(ob, "data", None), "materials", None)) and ob.data.materials[0] is not None

    def execute(self, context):
        context.window_manager.b4d_material = context.active_object.data.materials[0].name
        _tag_redraw()
        return {"FINISHED"}


class BLENDA4D_OT_mm_delete(bpy.types.Operator):
    bl_idname = "blenda4d.mm_delete"
    bl_label = "Delete Material"
    bl_description = "Delete the selected material"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return current(context) is not None

    def invoke(self, context, event):
        mat = current(context)
        if mat.users - int(mat.use_fake_user) > 0:
            return context.window_manager.invoke_confirm(self, event, title="Delete Material",
                                                         message=f"\"{mat.name}\" is used by objects. Delete it anyway?",
                                                         confirm_text="Delete")
        return self.execute(context)

    def execute(self, context):
        remove_material(current(context))
        context.window_manager.b4d_material = ""
        _tag_redraw()
        return {"FINISHED"}


class BLENDA4D_OT_mm_delete_unused(bpy.types.Operator):
    bl_idname = "blenda4d.mm_delete_unused"
    bl_label = "Delete Unused Materials"
    bl_description = "Delete every material that no object uses"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # a deleted object's mesh stays until the file is saved and still counts as a user; leftovers do not count
        left = {}
        for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.metaballs, bpy.data.volumes, bpy.data.hair_curves,
                     bpy.data.pointclouds):
            for d in coll:
                if d.users == 0:
                    for m in d.materials:
                        if m is not None:
                            left[m.name] = left.get(m.name, 0) + 1
        gone = 0
        for m in list(materials(context)):
            if m.users - int(m.use_fake_user) - left.get(m.name, 0) <= 0:
                remove_material(m)
                gone += 1
        if bpy.data.materials.get(context.window_manager.b4d_material) is None:
            context.window_manager.b4d_material = ""
        self.report({"INFO"}, f"Deleted {gone} unused material{'s' if gone != 1 else ''}")
        _tag_redraw()
        return {"FINISHED"}


def _socket_value(s):
    v = getattr(s, "default_value", None)
    try:
        return tuple(round(x, 5) for x in v)
    except TypeError:
        return round(v, 5) if isinstance(v, float) else v


def fingerprint(m):
    """Two materials are duplicates when every setting, node and link matches; names do not count."""
    own = tuple((p.identifier, repr(getattr(m, p.identifier))) for p in m.bl_rna.properties
                if p.type in ("BOOLEAN", "INT", "FLOAT", "ENUM") and not p.is_readonly and not getattr(p, "is_array", False)
                and p.identifier != "use_fake_user" and not p.identifier.startswith("paint_"))
    if m.node_tree is None:
        return own, tuple(round(x, 5) for x in m.diffuse_color)
    nodes = sorted(m.node_tree.nodes, key=lambda n: n.name)
    index = {n.name: i for i, n in enumerate(nodes)}
    data = []
    for n in nodes:
        extra = tuple((p.identifier, repr(getattr(n, p.identifier))) for p in n.bl_rna.properties
                      if p.type == "ENUM" and not p.is_readonly and p.identifier != "bl_static_type")
        data.append((n.bl_idname, extra, n.image.name if getattr(n, "image", None) else None,
                     tuple((s.name, _socket_value(s)) for s in n.inputs)))
    wires = sorted((index[l.from_node.name], l.from_socket.name, index[l.to_node.name], l.to_socket.name)
                   for l in m.node_tree.links)
    return own, tuple(data), tuple(wires)


class BLENDA4D_OT_mm_delete_duplicates(bpy.types.Operator):
    bl_idname = "blenda4d.mm_delete_duplicates"
    bl_label = "Delete Duplicate Materials"
    bl_description = "Delete materials identical to another one; whatever used them gets the one that stays"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        keep, gone = {}, 0
        for m in sorted(materials(context), key=lambda x: (len(x.name), x.name)):    # "Mat" stays, "Mat.001" goes
            k = keep.setdefault(fingerprint(m), m)
            if k != m:
                m.user_remap(k)
                remove_material(m)
                gone += 1
        if bpy.data.materials.get(context.window_manager.b4d_material) is None:
            context.window_manager.b4d_material = ""
        self.report({"INFO"}, f"Deleted {gone} duplicate material{'s' if gone != 1 else ''}")
        _tag_redraw()
        return {"FINISHED"}


CHECK_A = (0.541, 0.553, 0.565)       # the grey checkerboard behind each preview ball
CHECK_B = (0.380, 0.388, 0.396)
FRAME = (0.992, 0.647, 0.247)         # thin orange frame around the selected material's preview
_pcoll = []
_tiles = {}                           # key -> (checksum, preview)


def tile_icon(mat, selected, px, layout):
    """Blender's own preview render of the material, laid on a checkerboard (and framed when selected).
    Falls back to the plain preview until Blender has rendered it."""
    import numpy as np
    plain = layout.icon(mat)
    p = mat.preview
    if p is None or not _pcoll:
        return plain
    w, h = p.image_size
    pix = p.image_pixels_float
    if not w or not h:
        w, h = p.icon_size
        pix = p.icon_pixels_float
        if not w or not h:
            return plain
    src = np.empty(w * h * 4, np.float32)
    pix.foreach_get(src)
    if not src[3::4].any():
        return plain                                  # not rendered yet
    f = max(1, round(w / max(px, 1))) if selected else 0
    key = f"{mat.name}|{f}"
    check = hash(src[::61].tobytes()) ^ hash((w, h))
    hit = _tiles.get(key)
    if hit is not None and hit[0] == check:
        return hit[1].icon_id
    img = src.reshape(h, w, 4)
    sq = max(2, w // 8)
    yy, xx = np.mgrid[0:h, 0:w]
    bg = np.where((((yy // sq) + (xx // sq)) % 2 == 0)[..., None], np.array(CHECK_A, np.float32), np.array(CHECK_B, np.float32))
    a = img[..., 3:4]
    out = np.empty((h, w, 4), np.float32)
    out[..., :3] = img[..., :3] * a + bg * (1 - a)
    out[..., 3] = 1.0
    if f:
        for sl in (np.s_[:f, :], np.s_[-f:, :], np.s_[:, :f], np.s_[:, -f:]):
            out[sl][..., :3] = FRAME
    pcoll = _pcoll[0]
    prev = pcoll.get(key) or pcoll.new(key)
    prev.image_size = (w, h)
    prev.image_pixels_float.foreach_set(out.ravel())
    _tiles[key] = (check, prev)
    return prev.icon_id


def _textures(mat):
    if mat.node_tree is None:
        return []
    return sorted({n.image.name for n in mat.node_tree.nodes if getattr(n, "image", None) is not None})


def draw_tools(layout, context):
    """The tool row under the menus."""
    layout.use_property_split = False
    wm = context.window_manager
    sp = layout.split(factor=0.86, align=False)      # a split, not a stretch spacer: a spacer here pushes the
    row = sp.row(align=False)                         # tile rows below it out of place
    row.alignment = "LEFT"
    row.scale_x = row.scale_y = 1.25
    row.operator("blenda4d.new_material", text="", icon="ADD")
    row.operator("blenda4d.toggle_column", text="", icon="ASSET_MANAGER",
                 depress=bool(roles.areas(context.screen, "ASSETS"))).name = "ASSETS"
    row.operator("blenda4d.mm_apply", text="", icon="CHECKMARK")
    row.operator("blenda4d.mm_pick", text="", icon="EYEDROPPER")
    row.operator("blenda4d.mm_delete", text="", icon="TRASH")
    row.operator("blenda4d.mm_delete_unused", text="", icon="ORPHAN_DATA")
    row.operator("blenda4d.mm_delete_duplicates", text="", icon="DUPLICATE")
    right = sp.row(align=False)
    right.alignment = "RIGHT"
    right.scale_x = right.scale_y = 1.25
    right.prop(wm, "b4d_mm_search", text="", icon="VIEWZOOM", toggle=True, icon_only=True)
    if wm.b4d_mm_search:
        layout.prop(wm, "b4d_mm_filter", text="", icon="VIEWZOOM", placeholder="Search")


def draw_materials(layout, context):
    layout.use_property_split = False       # the Tool tab turns it on, which keeps an empty label column on the left
    wm = context.window_manager
    cur = wm.b4d_material
    mats = materials(context)
    if wm.b4d_mm_view == "ICONS":
        px = wm.b4d_mm_px
        cols, cw = grid_columns(context, px)
        grid = layout.column(align=True)               # rows packed close: a small gap, the name right under each ball
        for i in range(0, len(mats), cols):
            if i:
                grid.separator(factor=ROW_SEP)
            row = grid.row(align=True)
            row.alignment = "LEFT"
            for j in range(cols):
                if i + j >= len(mats):
                    break
                cell = row.column(align=True)
                cell.ui_units_x = cw / 20
                mat = mats[i + j]
                cell.template_icon(icon_value=tile_icon(mat, mat.name == cur, px, layout), scale=px / 20)
                cell.operator("blenda4d.mat_pick", text=mat.name, emboss=mat.name == cur, depress=mat.name == cur).name = mat.name
        return
    col = layout.column(align=False)
    s = max(1.0, min(wm.b4d_mm_px, 80) / 20)            # the size slider grows the list rows too
    for mat in mats:
        row = col.row(align=False)
        row.alignment = "LEFT"
        row.template_icon(icon_value=tile_icon(mat, mat.name == cur, wm.b4d_mm_px, layout), scale=s)
        name = row.column(align=True)
        name.separator(factor=max(0.0, (s - 1) * 1.25))     # level with the middle of the preview
        name.operator("blenda4d.mat_pick", text=mat.name, emboss=mat.name == cur, depress=mat.name == cur).name = mat.name
        if wm.b4d_mm_view == "LAYERS":
            texs = _textures(mat)
            box = col.column(align=True)
            box.active = False
            for t in texs or ["No textures"]:
                r = box.row()
                r.separator(factor=s * 2.2)
                r.label(text=t, icon="IMAGE_DATA" if texs else "BLANK1")


def draw_bar(layout, context):
    layout.use_property_split = False
    wm = context.window_manager
    row = layout.row(align=False)
    views = row.row(align=True)
    views.prop(wm, "b4d_mm_view", expand=True, icon_only=True)
    row.separator_spacer()
    size = row.row(align=True)
    size.ui_units_x = 8
    from .managers import size_bar
    size_bar(size, "b4d_mm_px", step=8)


class BLENDA4D_PT_mm_bar(roles.RolePanel, bpy.types.Panel):
    bl_label = "Material View"
    role = "MM_BAR"

    def draw(self, context):
        draw_bar(self.layout, context)


def _px_update(self, context):
    _tag_redraw()


GRID_TOP = 4.3         # units from the panel's top to the first row of tiles (title, menus, tool row): measured
NAME_UNITS = 1.0       # a tile's name button under its preview
TILE_GAP = 6           # pixels between tiles, side by side
ROW_SEP = 0.5          # separator factor between rows of tiles
ROW_GAP = 0.15         # units between rows of tiles that separator makes: measured (64 px tiles repeat every 87 px)
LEFT = 11              # pixels from the panel's left edge to the first tile's cell: measured


def grid_columns(context, px):
    """(columns, column width in pixels at 100 %) of the icon view: as many as fit, each a ball and a small gap."""
    ui = context.preferences.system.ui_scale
    cw = px + TILE_GAP
    return max(1, int((context.region.width / ui - LEFT - 4) // cw)), cw


def tile_at(context, x, y):
    """(material, "name" | "preview") under region point x, y in the icon view, or (None, None) on empty space."""
    wm = context.window_manager
    mats = materials(context)
    region = context.region
    if wm.b4d_mm_view != "ICONS" or region is None:
        return None, None
    ui = context.preferences.system.ui_scale
    unit = 20 * ui
    vx, vy = region.view2d.region_to_view(x, y)
    down = -vy                                      # view y runs down from 0 at the panel's top
    px = wm.b4d_mm_px
    cols, cw = grid_columns(context, px)
    pitch = px * ui + (NAME_UNITS + ROW_GAP) * unit
    top = GRID_TOP * unit
    if down < top:
        return None, "above"                        # the title, menus and tool row
    row, dy = divmod(down - top, pitch)
    col = int((vx - LEFT * ui) // (cw * ui))
    if not 0 <= col < cols:
        return None, None
    i = int(row) * cols + col
    if i >= len(mats) or (vx - LEFT * ui) - col * cw * ui > px * ui:
        return None, None
    if dy <= px * ui:
        return mats[i], "preview"
    if dy <= px * ui + NAME_UNITS * unit:
        return mats[i], "name"
    return None, None


class BLENDA4D_OT_mm_double(bpy.types.Operator):
    bl_idname = "blenda4d.mm_double"
    bl_label = "Material Manager Double-Click"
    bl_description = "Double-click a material to open its nodes; its name to rename it; empty space for a new material"
    bl_options = {"UNDO", "INTERNAL"}
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == "MATERIALS"

    def invoke(self, context, event):
        mat, part = tile_at(context, event.mouse_region_x, event.mouse_region_y)
        if part == "above":
            return {"PASS_THROUGH"}
        if mat is None:
            bpy.ops.blenda4d.new_material()
            _tag_redraw()
            return {"FINISHED"}
        if part != "name":                          # the preview: the material's nodes in the Node Editor window
            from . import nodewin
            context.window_manager.b4d_material = mat.name
            nodewin.open_window(context, mat)
            return {"FINISHED"}
        self.name = mat.name
        context.window_manager.b4d_material = mat.name
        return context.window_manager.invoke_popup(self, width=max(160, context.window_manager.b4d_mm_px * 2))

    def draw(self, context):
        mat = bpy.data.materials.get(self.name)
        if mat is not None:
            self.layout.activate_init = True        # the field opens for typing with the whole name selected
            self.layout.prop(mat, "name", text="", icon="MATERIAL")

    def execute(self, context):
        return {"FINISHED"}


class BLENDA4D_OT_mm_click(bpy.types.Operator):
    bl_idname = "blenda4d.mm_click"
    bl_label = "Material Manager Click"
    bl_description = "Click a material to select it; click empty space to select none"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == "MATERIALS"

    def invoke(self, context, event):
        mat, part = tile_at(context, event.mouse_region_x, event.mouse_region_y)
        if part == "above" or (mat is None and context.window_manager.b4d_mm_view != "ICONS"):
            return {"PASS_THROUGH"}
        wm = context.window_manager
        from . import matpage
        if mat is None:                             # empty space: no material selected, the object shows again
            wm.b4d_material = ""
            if wm.b4d_am_subject.startswith(matpage.SUBJECT + ":"):
                wm.b4d_am_subject = ""
        else:
            wm.b4d_material = mat.name
            matpage.show(context, mat)
            if event.shift:                         # as Shift-clicking its name: onto the selected objects
                for ob in context.selected_objects:
                    if hasattr(ob.data, "materials"):
                        if ob.data.materials:
                            ob.data.materials[0] = mat
                        else:
                            ob.data.materials.append(mat)
        for a in context.screen.areas:
            a.tag_redraw()
        return {"FINISHED"}


# --- tiles follow edits ---------------------------------------------------------------------------------------------
# A tile copies Blender's own preview of the material; Blender re-renders that preview only when it draws the
# material's icon itself, which the tiles never do. So an edited material asks for a new render here. (Blender's
# change list leaves out materials no object uses, so the nodes are compared instead.)
_stale = set()
_wait = [0]


_sigs = {}                   # material -> signature of what its preview shows


def _value(v):
    try:
        return tuple(round(x, 5) for x in v)
    except TypeError:
        return round(v, 5) if isinstance(v, float) else v


def _signature(mat):
    """What the preview depends on: every node's kind, unlinked input values and the links."""
    tree = mat.node_tree
    if not mat.use_nodes or tree is None:
        return hash((tuple(mat.diffuse_color), mat.metallic, mat.roughness))
    parts = []
    for n in tree.nodes:
        parts.append(n.bl_idname)
        for i in n.inputs:
            if not i.is_linked and hasattr(i, "default_value"):
                parts.append(_value(i.default_value))
        img = getattr(n, "image", None)
        if img is not None:
            parts.append(img.name)
    parts.extend((lk.from_socket.identifier, lk.from_node.name, lk.to_socket.identifier, lk.to_node.name) for lk in tree.links)
    return hash(tuple(parts))


def _watch():
    """While a Material Manager is open: a material whose nodes changed gets a new preview render."""
    wm = bpy.context.window_manager
    if wm is None or not any(roles.role(a) == "MATERIALS" for w in wm.windows for a in w.screen.areas):
        return 1.0
    for mat in bpy.data.materials:
        if mat.is_grease_pencil:
            continue
        sig = _signature(mat)
        old = _sigs.get(mat.name)
        _sigs[mat.name] = sig
        if old is not None and old != sig:
            _stale.add(mat.name)
    if _stale and not bpy.app.timers.is_registered(_rerender):
        bpy.app.timers.register(_rerender, first_interval=0.3)      # once the edit has settled
    return 0.5


def _rerender():
    wm = bpy.context.window_manager
    window = wm.windows[0] if wm and wm.windows else None
    for name in list(_stale):
        mat = bpy.data.materials.get(name)
        if mat is None or window is None:
            continue
        try:
            with bpy.context.temp_override(window=window, id=mat):
                bpy.ops.ed.lib_id_generate_preview()
        except (RuntimeError, TypeError):
            pass
    _stale.clear()
    _wait[0] = 12                                    # redraw for a few seconds while the render finishes
    if not bpy.app.timers.is_registered(_redraw_until_done):
        bpy.app.timers.register(_redraw_until_done, first_interval=0.25)
    return None


def _redraw_until_done():
    _tag_redraw()
    _wait[0] -= 1
    return 0.25 if _wait[0] > 0 else None


_keys = []


classes = (BLENDA4D_OT_mm_click, BLENDA4D_OT_mm_double, BLENDA4D_OT_mm_apply, BLENDA4D_OT_mm_pick, BLENDA4D_OT_mm_delete, BLENDA4D_OT_mm_delete_unused,
           BLENDA4D_OT_mm_delete_duplicates, BLENDA4D_PT_mm_bar)


def register():
    import bpy.utils.previews
    _pcoll.append(bpy.utils.previews.new())
    for c in classes:
        bpy.utils.register_class(c)
    W = bpy.types.WindowManager
    W.b4d_mm_view = bpy.props.EnumProperty(description='Show materials as previews, as a list, or as a list with their textures', name="View", items=VIEWS, default="ICONS", update=_px_update)
    W.b4d_mm_px = bpy.props.IntProperty(description='How large the material previews are', name="Preview Size", default=64, min=PX_MIN, max=PX_MAX, subtype="PIXEL",
                                        update=_px_update)
    W.b4d_mm_search = bpy.props.BoolProperty(name="Search Materials", description="Search materials by name")
    W.b4d_mm_filter = bpy.props.StringProperty(description='Show only materials whose name contains this', name="Search", options={"TEXTEDIT_UPDATE"}, update=_px_update)
    if not bpy.app.timers.is_registered(_watch):
        bpy.app.timers.register(_watch, first_interval=1.0, persistent=True)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        km = kc.keymaps.new(name="Property Editor", space_type="PROPERTIES")
        _keys.append((km.name, km.keymap_items.new("blenda4d.mm_double", "LEFTMOUSE", "DOUBLE_CLICK").idname))
        for shift in (False, True):
            _keys.append((km.name, km.keymap_items.new("blenda4d.mm_click", "LEFTMOUSE", "CLICK", shift=shift).idname))


def unregister():
    for t in (_watch, _rerender, _redraw_until_done):
        if bpy.app.timers.is_registered(t):
            bpy.app.timers.unregister(t)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:                               # looked up fresh: held keymap items can be freed at quit
        for name, idname in _keys:
            km = kc.keymaps.get(name)
            if km is not None:
                for kmi in list(km.keymap_items):
                    if kmi.idname == idname:
                        km.keymap_items.remove(kmi)
    _keys.clear()
    W = bpy.types.WindowManager
    for n in ("b4d_mm_view", "b4d_mm_px", "b4d_mm_search", "b4d_mm_filter"):
        delattr(W, n)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    from bpy.utils import previews
    for pc in _pcoll:
        previews.remove(pc)
    _pcoll.clear()
    _tiles.clear()
