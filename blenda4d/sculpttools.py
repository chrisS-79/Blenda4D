# SPDX-License-Identifier: GPL-3.0-or-later
"""The tools column in the Sculpting tab: Blender's sculpt brushes by their own pictures, and the sculpt tools.

Related brushes share one button: hold it, or click its corner, for the others. With whole objects a click on a brush
goes into sculpting. The list is what this Blender has: a brush that no group names goes into the last group."""
import inspect
import os

import bpy
import bpy.utils.previews

from . import layouts, modeltools, switch

MODE = "SCULPT"
BLEND = "brushes/essentials_brushes-mesh_sculpt.blend"
_B, _T = "brush", "sculpt"
MULTIRES = {"Erase Multires Displacement", "Smear Multires Displacement"}

# Blender's brush: Blenda's name where that is another one
NAMES = {"Clay": "Wax", "Clay Strips": "Wax Strips", "Clay Thumb": "Wax Thumb", "Draw Sharp": "Knife", "Pinch/Magnify": "Pinch",
         "Flatten/Contrast": "Flatten", "Inflate/Deflate": "Inflate", "Fill/Deepen": "Fill", "Scrape/Fill": "Scrape",
         "Erase Multires Displacement": "Erase", "Smear Multires Displacement": "Smear Detail", "Face Set Paint": "Paint Face Sets"}


def _tool(idname, icon, name):
    return (_T, idname, icon, name, "")


GROUPS = [
    ["Draw", "Layer", "Blob"], ["Smooth", "Relax Slide", "Relax Pinch"],
    ["Grab", "Elastic Grab", "Grab 2D", "Grab Silhouette", "Nudge", "Thumb", "Twist"],
    ["Snake Hook", "Pull", "Elastic Snake Hook"], None,
    ["Clay", "Clay Strips", "Clay Thumb"], ["Draw Sharp", "Crease Sharp", "Crease Polish"], ["Pinch/Magnify"], ["Inflate/Deflate"],
    ["Flatten/Contrast", "Plateau", "Trim"], ["Scrape/Fill", "Scrape Multiplane"], ["Fill/Deepen"], None,
    ["Pose", "Bend/Twist Cloth", "Stretch/Move Cloth", "Boundary", "Bend Boundary Cloth", "Twist Boundary Cloth"],
    ["Drag Cloth", "Grab Cloth", "Grab Planar Cloth ", "Grab Random Cloth", "Push Cloth", "Inflate Cloth", "Expand/Contract Cloth",
     "Pinch Folds Cloth", "Pinch Point Cloth"],
    ["Erase Multires Displacement", "Smear Multires Displacement", "Density", "Scene Project"],
    ["Paint Hard", "Paint Soft", "Paint Blend", "Paint Square", "Paint Hard Pressure", "Paint Soft Pressure", "Airbrush", "Blur", "Smear",
     "Sharpen", "Blend Hard", "Blend Soft", "Blend Square"], None,
    ["Mask", _tool("builtin.box_mask", "ops.sculpt.border_mask", "Rectangle Mask"),
     _tool("builtin.lasso_mask", "ops.sculpt.lasso_mask", "Lasso Mask"), _tool("builtin.line_mask", "ops.sculpt.line_mask", "Line Mask"),
     _tool("builtin.polyline_mask", "ops.sculpt.polyline_mask", "Polygon Mask"),
     _tool("builtin.mask_by_color", "ops.sculpt.mask_by_color", "Mask by Color")],
    ["Face Set Paint", _tool("builtin.box_face_set", "ops.sculpt.border_face_set", "Rectangle Face Set"),
     _tool("builtin.lasso_face_set", "ops.sculpt.lasso_face_set", "Lasso Face Set"),
     _tool("builtin.line_face_set", "ops.sculpt.line_face_set", "Line Face Set"),
     _tool("builtin.polyline_face_set", "ops.sculpt.polyline_face_set", "Polygon Face Set"),
     _tool("builtin.face_set_edit", "ops.sculpt.face_set_edit", "Edit Face Set")],
    [_tool("builtin.box_hide", "ops.sculpt.border_hide", "Rectangle Hide"), _tool("builtin.lasso_hide", "ops.sculpt.lasso_hide", "Lasso Hide"),
     _tool("builtin.line_hide", "ops.sculpt.line_hide", "Line Hide"), _tool("builtin.polyline_hide", "ops.sculpt.polyline_hide", "Polygon Hide")],
    [_tool("builtin.box_trim", "ops.sculpt.box_trim", "Rectangle Trim"), _tool("builtin.lasso_trim", "ops.sculpt.lasso_trim", "Lasso Trim"),
     _tool("builtin.line_trim", "ops.sculpt.line_trim", "Line Trim"), _tool("builtin.polyline_trim", "ops.sculpt.polyline_trim", "Polygon Trim"),
     _tool("builtin.line_project", "ops.sculpt.line_project", "Line Project")],
    [_tool("builtin.mesh_filter", "ops.sculpt.mesh_filter", "Mesh Filter"), _tool("builtin.cloth_filter", "ops.sculpt.cloth_filter", "Cloth Filter"),
     _tool("builtin.color_filter", "ops.sculpt.color_filter", "Color Filter")], None,
    [_tool("builtin.move", "ops.transform.translate", "Move"), _tool("builtin.rotate", "ops.transform.rotate", "Rotate"),
     _tool("builtin.scale", "ops.transform.resize", "Scale"), _tool("builtin.transform", "ops.transform.transform", "Transform")],
    [_tool("builtin.annotate", "ops.gpencil.draw", "Annotate")],
]
_shown = {}                  # a group's first member -> the one picked last
_pcoll = [None]
_names = []


# --- Blender's brushes ----------------------------------------------------------------------------------------------------
def _file():
    return os.path.join(bpy.utils.resource_path("LOCAL"), "datafiles", "assets", *BLEND.split("/"))


def brushes():
    """The names of the brushes that come with this Blender."""
    if not _names and os.path.exists(_file()):
        with bpy.data.libraries.load(_file(), link=True, assets_only=True) as (src, _dst):
            _names.extend(src.brushes)
    return _names


def _preview(name):
    if _pcoll[0] is None:
        _pcoll[0] = bpy.utils.previews.new()
    pc = _pcoll[0]
    if name not in pc:
        pc.load(name, os.path.join(_file(), "Brush", name), "BLEND")
    return pc[name]


def icon_id(name):
    try:
        return _preview(name).icon_id
    except (OSError, KeyError, RuntimeError):
        return 0


_tex = {}


def texture(name, px):
    """The brush's picture, px square, averaged down so that it stays sharp. None until Blender has it."""
    key = (name, px)
    if key in _tex:
        return _tex[key]
    import gpu
    import numpy as np
    p = _preview(name)
    w, h = p.image_size
    if not w or not h:
        return None
    img = np.empty(w * h * 4, dtype=np.float32)
    p.image_pixels_float.foreach_get(img)
    img = img.reshape(h, w, 4)
    if not img[..., 3].any():
        return None
    ys, xs = np.linspace(0, h, px + 1).astype(int), np.linspace(0, w, px + 1).astype(int)
    pre = np.concatenate([img[..., :3] * img[..., 3:4], img[..., 3:4]], axis=-1)
    out = np.add.reduceat(np.add.reduceat(pre, ys[:-1], axis=0), xs[:-1], axis=1)
    out /= (np.diff(ys)[:, None] * np.diff(xs)[None, :])[..., None]
    a = out[..., 3:4]
    out = np.concatenate([np.where(a > 0, out[..., :3] / np.maximum(a, 1e-6), 0), a], axis=-1).astype(np.float32)
    _tex[key] = gpu.types.GPUTexture((px, px), format="RGBA32F", data=gpu.types.Buffer("FLOAT", px * px * 4, out.ravel().tolist()))
    return _tex[key]


def _entry(m):
    return m if isinstance(m, tuple) else (_B, m, "brush:" + m, NAMES.get(m, m).strip(), m.strip() if NAMES.get(m, m) != m else "")


def groups():
    """[[entry, ...] or None]: only what this Blender has."""
    have, used, out = set(brushes()), set(), []
    for g in GROUPS:
        if g is None:
            out.append(None)
            continue
        used.update(m for m in g if isinstance(m, str))
        keep = [_entry(m) for m in g if isinstance(m, tuple) or m in have]
        if keep:
            out.append(keep)
    rest = [_entry(m) for m in sorted(have - used)]
    if rest:
        out += [None, rest]
    return out


def all_entries():
    for g in groups():
        yield from g or ()


# --- the column ------------------------------------------------------------------------------------------------------------
def active(window):
    ws = window.workspace if window is not None else None
    return ws is not None and layouts.spec(layouts.current(ws))["base"] == "Sculpting" and bpy.context.mode in {"OBJECT", MODE}


def brush_shown(context):
    """The name of the brush in use, or ""."""
    if context.mode != MODE:
        return ""
    from . import bars
    if not bars.active_tool(context).startswith("builtin_brush") and bars.active_tool(context) != "builtin.brush":
        return ""
    ref = context.tool_settings.sculpt.brush_asset_reference
    rel = ref.relative_asset_identifier if ref is not None else ""
    return rel.replace("\\", "/").split("/Brush/", 1)[-1] if "/Brush/" in rel.replace("\\", "/") else ""


def why_not(context, entry):
    ob = context.view_layer.objects.active
    if ob is None or ob.type != "MESH":
        return "select a polygon object first"
    if "b4d_type" in ob:
        return "make the object editable first (C)"
    if entry[1] in MULTIRES and not any(m.type == "MULTIRES" for m in ob.modifiers):
        return "subdivide the object first (Attributes, Topology)"
    if entry[1] == "Density" and not (context.mode == MODE and ob.use_dynamic_topology_sculpting):
        return "switch Dynamic Topology on first (Attributes, Topology)"
    return ""


def label(entry):
    return f"{entry[3]} ({entry[4]})" if entry[4] and entry[4] != entry[3] else entry[3]


def items(context, active_tool):
    out = [{"tool": None, "icon": "magnifier", "label": "Zoom to Border"}, None]
    now = brush_shown(context)
    for members in groups():
        if members is None:
            if out[-1] is not None:
                out.append(None)
            continue
        key = members[0][1]

        def on(m):
            return m[1] == now if m[0] == _B else (context.mode == MODE and m[1] == active_tool)
        pick = next((m for m in members if on(m)), None)
        if pick is not None:
            _shown[key] = pick[1]
        shown = next((m for m in members if m[1] == _shown.get(key)), members[0])
        why = why_not(context, shown)
        out.append({"tool": None, "on": pick is not None, "icon": shown[2] if shown[0] == _B else shown[2], "label": label(shown),
                    "tip": label(shown) + (f": {why}" if why else "") + ("  (hold for more)" if len(members) > 1 else ""),
                    "entry": shown, "members": members, "dim": bool(why)})
    return out


def use(context, entry):
    """Pick the brush or tool; sculpting starts when it has not. True when it could."""
    if context.mode != MODE:
        bpy.ops.object.mode_set(mode=MODE)
        if bpy.context.mode != MODE:
            return False
        bpy.ops.ed.undo_push(message="Sculpt")
    if entry[0] == _T:
        bpy.ops.wm.tool_set_by_id(name=entry[1])
        return True
    try:
        bpy.ops.brush.asset_activate(asset_library_type="ESSENTIALS", asset_library_identifier="",
                                     relative_asset_identifier=f"{BLEND}/Brush/{entry[1]}")
    except RuntimeError as ex:
        print("Blenda 4D: brush", entry[1], ex)
        return False
    return True


def icon_kw(entry):
    if entry[0] == _B:
        iv = icon_id(entry[1])
        return {"icon_value": iv} if iv else {"icon": "BRUSH_DATA"}
    iv = modeltools.tool_icon(entry[2])
    return {"icon_value": iv} if iv else {}


# --- the brush in the Attribute Manager --------------------------------------------------------------------------------------
PAGES = [("BRUSH", "Brush", "The brush's size, strength and own settings"), ("STROKE", "Stroke", "How the stroke is laid down"),
         ("FALLOFF", "Falloff", "How the brush fades towards its edge"), ("STAMP", "Stamp", "A texture for the brush"),
         ("SYMMETRY", "Symmetry", "Sculpt on both sides at once"), ("TOPOLOGY", "Topology", "Subdivide and remesh the object"),
         ("OBJECT", "Object", "The object's own settings")]


def draw_page(layout, context, ob):
    """The Attribute Manager while sculpting. False: the object's own pages are wanted."""
    if context.mode != MODE or ob is None:
        return False
    wm, sculpt = context.window_manager, context.tool_settings.sculpt
    brush = sculpt.brush
    from . import bars
    tool = bars.active_tool(context)
    is_brush = bool(brush) and (tool == "builtin.brush" or tool.startswith("builtin_brush"))
    now = brush_shown(context)
    head = layout.row(align=True)
    _shelf(context)
    if is_brush:
        name = NAMES.get(now, now or brush.name).strip()
        head.label(text=f"Brush [{name}]", icon="BRUSH_DATA")
    else:
        e = next((e for e in all_entries() if e[1] == tool), None)
        head.label(text=f"Tool [{e[3] if e else tool.split('.')[-1].replace('_', ' ').title()}]", icon="TOOL_SETTINGS")
    tg = layout.grid_flow(row_major=True, columns=4, even_columns=True, align=True)
    for key, text, _d in PAGES:
        tg.prop_enum(wm, "b4d_sculpt_page", key, text=text)
    page = wm.b4d_sculpt_page
    if page == "OBJECT":
        layout.separator(factor=0.5)
        return False
    layout.separator(factor=0.5)
    layout.label(text=dict((p[0], p[1]) for p in PAGES)[page])
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False
    if page in {"BRUSH", "STROKE", "FALLOFF", "STAMP"} and not is_brush:
        if page == "BRUSH":
            _tool_page(col, context, tool)
        else:
            col.label(text="Pick a brush to see this page")
        return True
    {"BRUSH": _brush, "STROKE": _stroke, "FALLOFF": _falloff, "STAMP": _stamp, "SYMMETRY": _symmetry, "TOPOLOGY": _topology}[page](col, context, ob, brush)
    return True


def _shelf(context):
    """Blender's shelf of brushes would repeat the tools column along the bottom of the viewport."""
    view = next((a for a in context.screen.areas if a.type == "VIEW_3D" and a.spaces.active.show_region_asset_shelf), None)
    if view is not None and not bpy.app.timers.is_registered(_hide_shelf):
        bpy.app.timers.register(_hide_shelf, first_interval=0.0)


def _hide_shelf():
    for w in bpy.context.window_manager.windows:
        if w.workspace.name == switch.WORKSPACE:
            for a in w.screen.areas:
                if a.type == "VIEW_3D" and a.spaces.active.show_region_asset_shelf:
                    try:
                        a.spaces.active.show_region_asset_shelf = False
                    except AttributeError:
                        pass
    return None


def _tool_page(col, context, tool):
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper as T
    cls = T._tool_class_from_space_type("VIEW_3D")
    item = next((i for i in T._tools_flatten_with_dynamic(cls._tools[MODE], context=context) if getattr(i, "idname", "") == tool), None)
    active_tool = context.workspace.tools.from_space_view3d_mode(MODE, create=False)
    if item is not None and item.draw_settings is not None and active_tool is not None:
        try:
            item.draw_settings(context, col, active_tool)
            return
        except Exception:
            pass
    col.label(text="No settings for this tool")


def _try(fn, *args, **kw):
    """Blender's own rows for a brush: a version that draws them differently leaves the rest of the page standing."""
    try:
        fn(*args, **kw)
    except Exception as ex:
        if str(ex) not in _told:
            _told.add(str(ex))
            print("Blenda 4D: sculpt page", ex)


_told = set()


def _brush(col, context, ob, brush):
    from bl_ui import properties_paint_common as P
    ups = getattr(context.tool_settings.sculpt, "unified_paint_settings", None)
    _try(P.brush_settings, col, context, brush)
    col.separator()
    for attr, text in (("use_unified_size", "Link Size"), ("use_unified_strength", "Link Strength")):
        owner = brush if hasattr(brush, attr) else ups     # 5.3 keeps it with each brush
        if owner is not None:
            col.prop(owner, attr, text=text)
    box = col.column(heading="Advanced")
    _try(P.brush_settings_advanced, box, context, context.tool_settings.sculpt, brush)
    col.separator()
    row = col.row(align=True)
    row.operator("brush.asset_revert", text="Reset Brush", icon="LOOP_BACK")
    row.operator("brush.asset_save_as", text="Save as New Brush...", icon="FILE_TICK")


class _Panel:
    """Stands in for one of Blender's panels: draws its rows into this page."""

    def __init__(self, layout, cls):
        self.layout, self._cls, self.is_popover = layout, cls, False

    def __getattr__(self, name):
        v = getattr(self._cls, name)
        return (lambda *a, **k: v(self, *a, **k)) if inspect.isfunction(v) and not isinstance(
            inspect.getattr_static(self._cls, name), staticmethod) else v


def _blender(col, context, name):
    """One of Blender's own sculpt panels, drawn into the page. (Blenda keeps it out of its own places, roles.py.)"""
    import bl_ui.space_view3d_toolbar as tb
    cls = getattr(tb, name, None)
    if cls is not None:
        _try(cls.draw, _Panel(col, cls), context)


def _stroke(col, context, ob, brush):
    _blender(col, context, "VIEW3D_PT_tools_brush_stroke")
    col.separator()
    col.prop(brush, "use_smooth_stroke", text="Steady Stroke")
    sub = col.column()
    sub.active = brush.use_smooth_stroke
    sub.prop(brush, "smooth_stroke_radius", text="Radius", slider=True)
    sub.prop(brush, "smooth_stroke_factor", text="Factor", slider=True)


def _falloff(col, context, ob, brush):
    _blender(col, context, "VIEW3D_PT_tools_brush_falloff")


def _stamp(col, context, ob, brush):
    col.use_property_split = False
    col.template_ID_preview(brush, "texture", new="texture.new", rows=3, cols=8)
    col.use_property_split = True
    if brush.texture is not None:
        if brush.texture.type == "IMAGE":
            col.template_image(brush.texture, "image", brush.texture.image_user, compact=True)
        from bl_ui import properties_paint_common as P
        _try(P.brush_texture_settings, col, brush, True)


def _symmetry(col, context, ob, brush):
    me, sculpt = ob.data, context.tool_settings.sculpt
    row = col.row(align=True, heading="Mirror")
    for axis, attr in zip("XYZ", ("use_mirror_x", "use_mirror_y", "use_mirror_z")):
        row.prop(me, attr, text=axis, toggle=True)
    row = col.row(align=True, heading="Lock")
    for axis in "xyz":
        row.prop(sculpt, f"lock_{axis}", text=axis.upper(), toggle=True)
    row = col.row(align=True, heading="Tiling")
    for axis in "xyz":
        row.prop(sculpt, f"tile_{axis}", text=axis.upper(), toggle=True)
    col.prop(sculpt, "use_symmetry_feather", text="Feather")
    if hasattr(me, "radial_symmetry"):
        col.prop(me, "radial_symmetry", text="Radial")
    col.prop(sculpt, "tile_offset", text="Tile Offset")
    col.separator()
    col.prop(sculpt, "symmetrize_direction", text="Direction")
    col.operator("sculpt.symmetrize", text="Symmetrize")


def _topology(col, context, ob, brush):
    sculpt = context.tool_settings.sculpt
    multi = next((m for m in ob.modifiers if m.type == "MULTIRES"), None)
    dyn = ob.use_dynamic_topology_sculpting
    col.label(text="Subdivision")
    row = col.row(align=True)
    row.enabled = not dyn
    row.operator("blenda4d.sculpt_level", text="Subdivide", icon="MOD_MULTIRES").what = "SUBDIVIDE"
    row.operator("blenda4d.sculpt_level", text="Decrease", icon="REMOVE").what = "DOWN"
    row.operator("blenda4d.sculpt_level", text="Increase", icon="ADD").what = "UP"
    if multi is not None:
        col.prop(multi, "sculpt_levels", text="Level")
        col.prop(multi, "levels", text="Level in Editor")
        col.prop(multi, "render_levels", text="Level in Renderer")
        row = col.row(align=True)
        o = row.operator("object.multires_higher_levels_delete", text="Delete Higher")
        o.modifier = multi.name
        o = row.operator("object.multires_base_apply", text="Apply to Base")
        o.modifier = multi.name
    col.separator()
    row = col.row()
    row.enabled = multi is None
    row.operator("blenda4d.dynamic_detail", text="Dynamic Detail", icon="CHECKBOX_HLT" if dyn else "CHECKBOX_DEHLT")
    if multi is not None:
        col.label(text="Not with a Sculpt tag: delete the tag or Apply to Base first", icon="INFO")
    if dyn:
        col.prop(sculpt, "detail_type_method", text="Detailing")
        col.prop(sculpt, "detail_refine_method", text="Refine")
        col.prop(sculpt, {"CONSTANT": "constant_detail_resolution", "MANUAL": "constant_detail_resolution", "BRUSH": "detail_percent"}.get(
            sculpt.detail_type_method, "detail_size"), text="Detail")
        col.operator("sculpt.detail_flood_fill", text="Fill with Detail")
    col.separator()
    col.label(text="Remesh")
    col.prop(ob.data, "remesh_voxel_size", text="Voxel Size")
    col.prop(ob.data, "remesh_voxel_adaptivity", text="Adaptivity")
    row = col.row()
    row.enabled = multi is None and not dyn
    row.operator("object.voxel_remesh", text="Remesh")
    if multi is not None or dyn:
        col.label(text="Not with a Sculpt tag or Dynamic Detail on", icon="INFO")


class BLENDA4D_OT_sculpt_level(bpy.types.Operator):
    bl_idname = "blenda4d.sculpt_level"
    bl_label = "Sculpt Level"
    bl_options = {"REGISTER", "UNDO"}
    what: bpy.props.EnumProperty(items=[("SUBDIVIDE", "Subdivide", ""), ("UP", "Increase", ""), ("DOWN", "Decrease", "")], options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        return {"SUBDIVIDE": "Subdivide: four times as many polygons, with the levels below kept (Blender: Multiresolution)",
                "UP": "Go to the next finer level", "DOWN": "Go to the next coarser level"}[props.what]

    @classmethod
    def poll(cls, context):
        ob = context.view_layer.objects.active
        return (ob is not None and ob.type == "MESH" and context.mode in {"OBJECT", MODE}
                and ob.get("_b4d_freeze") is None)            # a frozen sculpt keeps its levels until thawed

    def execute(self, context):
        ob = context.view_layer.objects.active
        multi = next((m for m in ob.modifiers if m.type == "MULTIRES"), None)
        if self.what != "SUBDIVIDE":
            if multi is None:
                self.report({"INFO"}, "Subdivide the object first")
                return {"CANCELLED"}
            multi.sculpt_levels = min(multi.total_levels, max(0, multi.sculpt_levels + (1 if self.what == "UP" else -1)))
            multi.levels = multi.sculpt_levels
            return {"FINISHED"}
        if multi is None:
            multi = ob.modifiers.new("Multires", "MULTIRES")
        elif multi.sculpt_levels < multi.total_levels:
            multi.sculpt_levels = multi.levels = multi.total_levels       # a new level goes on the finest one
        bpy.ops.object.multires_subdivide(modifier=multi.name, mode="CATMULL_CLARK")
        multi.levels = multi.sculpt_levels = multi.total_levels
        return {"FINISHED"}


class BLENDA4D_OT_dynamic_detail(bpy.types.Operator):
    bl_idname = "blenda4d.dynamic_detail"
    bl_label = "Dynamic Detail"
    bl_description = ("Add polygons only where the brush goes, so detail grows where you sculpt; it can't be used "
                      "with a Sculpt tag's levels (Blender: Dynamic Topology)")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = context.view_layer.objects.active
        return context.mode == MODE and ob is not None and not any(m.type == "MULTIRES" for m in ob.modifiers)

    def execute(self, context):
        return bpy.ops.sculpt.dynamic_topology_toggle()


classes = (BLENDA4D_OT_sculpt_level, BLENDA4D_OT_dynamic_detail)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.b4d_sculpt_page = bpy.props.EnumProperty(
        name="Page", description="The page of settings the Attribute Manager shows while you sculpt", items=PAGES)


def unregister():
    if hasattr(bpy.types.WindowManager, "b4d_sculpt_page"):
        del bpy.types.WindowManager.b4d_sculpt_page
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    if _pcoll[0] is not None:
        bpy.utils.previews.remove(_pcoll[0])
        _pcoll[0] = None
    _tex.clear()
    _names.clear()
