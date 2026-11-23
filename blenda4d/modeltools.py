# SPDX-License-Identifier: GPL-3.0-or-later
"""The tools column in the Modeling tab: Blender's whole set of mesh tools, arranged for what is being worked on.

Select, Move, Rotate and Scale stay at the top. The rest follows the mode (points, edges or polygons), with one-click
commands (close a hole, bridge, weld, subdivide) among the tools. Related tools share one button: hold it, or click its
corner, for the others, and the one picked last is the one shown. With whole objects the polygon tools stay in sight;
clicking one goes to the polygons with that tool. What cannot be used yet is dimmed, and its name says why."""
import os

import bpy

from . import icons, layouts

ACCENTS = {(117, 255, 175): (245, 179, 85), (217, 175, 245): (166, 144, 230)}     # Blender's tool accents -> Blenda's:
#                                                                  making geometry is orange, reshaping it is violet
_T, _C = "tool", "command"

# (kind, id, icon, name, Blender's name for it when that is another one)
LIVE = (_T, "builtin.select_circle", "ops.generic.select_circle", "Live Selection", "Select Circle")
RECT = (_T, "builtin.select_box", "ops.generic.select_box", "Rectangle Selection", "Select Box")
LASSO = (_T, "builtin.select_lasso", "ops.generic.select_lasso", "Lasso Selection", "Select Lasso")
MOVE = (_T, "builtin.move", "ops.transform.translate", "Move", "")
ROTATE = (_T, "builtin.rotate", "ops.transform.rotate", "Rotate", "")
SCALE = (_T, "builtin.scale", "ops.transform.resize", "Scale", "")
TRANSFORM = (_T, "builtin.transform", "ops.transform.transform", "Transform", "")
CAGE = (_T, "builtin.scale_cage", "ops.transform.resize.cage", "Scale Cage", "")

POLY_PEN = (_T, "builtin.poly_build", "ops.mesh.polybuild_hover", "Polygon Pen", "Poly Build")
HOLE = (_C, "mesh.edge_face_add", "snap_face", "Close Polygon Hole", "Fill")
EXTRUDE = [(_T, "builtin.extrude_region", "ops.mesh.extrude_region_move", "Extrude", "Extrude Region"),
           (_T, "builtin.extrude_manifold", "ops.mesh.extrude_manifold", "Extrude Manifold", ""),
           (_T, "builtin.extrude_along_normals", "ops.mesh.extrude_region_shrink_fatten", "Extrude Along Normals", ""),
           (_T, "builtin.extrude_individual", "ops.mesh.extrude_faces_move", "Extrude Individual", ""),
           (_T, "builtin.extrude_to_cursor", "ops.mesh.dupli_extrude_cursor", "Extrude to Cursor", "")]
INSET = (_T, "builtin.inset_faces", "ops.mesh.inset", "Inset", "Inset Faces")
BEVEL = (_T, "builtin.bevel", "ops.mesh.bevel", "Bevel", "")
BRIDGE = (_C, "mesh.bridge_edge_loops", "linked", "Bridge", "Bridge Edge Loops")
WELD = [(_C, "mesh.merge:CENTER", "automerge_on", "Weld", "Merge at Center"),
        (_C, "mesh.merge:COLLAPSE", "fullscreen_exit", "Collapse", "Merge, Collapse"),
        (_C, "mesh.remove_doubles", "automerge_off", "Optimize", "Merge by Distance")]
LOOP = [(_T, "builtin.loop_cut", "ops.mesh.loopcut_slide", "Loop Cut", ""),
        (_T, "builtin.offset_edge_loop_cut", "ops.mesh.offset_edge_loops_slide", "Offset Edge Loop Cut", "")]
KNIFE = [(_T, "builtin.knife", "ops.mesh.knife_tool", "Line Cut", "Knife"),
         (_T, "builtin.bisect", "ops.mesh.bisect", "Plane Cut", "Bisect")]
SUBDIVIDE = [(_C, "mesh.subdivide", "mod_subsurf", "Subdivide", ""),
             (_C, "mesh.unsubdivide", "mod_decim", "Unsubdivide", ""),
             (_C, "mesh.quads_convert_to_tris", "mod_triangulate", "Triangulate", ""),
             (_C, "mesh.tris_convert_to_quads", "mesh_grid", "Untriangulate", "Tris to Quads")]
SPIN = (_T, "builtin.spin", "ops.mesh.spin", "Spin", "")
SMOOTH = [(_T, "builtin.smooth", "ops.mesh.vertices_smooth", "Smooth", ""),
          (_T, "builtin.randomize", "ops.transform.vertex_random", "Randomize", "")]
SLIDE_E = (_T, "builtin.edge_slide", "ops.transform.edge_slide", "Edge Slide", "")
SLIDE_V = (_T, "builtin.vertex_slide", "ops.transform.vert_slide", "Vertex Slide", "")
FATTEN = [(_T, "builtin.shrink_fatten", "ops.transform.shrink_fatten", "Move Along Normals", "Shrink/Fatten"),
          (_T, "builtin.push_pull", "ops.transform.push_pull", "Push/Pull", "")]
SHEAR = [(_T, "builtin.shear", "ops.transform.shear", "Shear", ""),
         (_T, "builtin.to_sphere", "ops.transform.tosphere", "To Sphere", "")]
RIP = [(_T, "builtin.rip_region", "ops.mesh.rip", "Rip", "Rip Region"),
       (_T, "builtin.rip_edge", "ops.mesh.rip_edge", "Rip Edge", "")]
ADD = [(_T, "builtin.primitive_cube_add", "ops.mesh.primitive_cube_add_gizmo", "Draw Cube", "Add Cube"),
       (_T, "builtin.primitive_cone_add", "ops.mesh.primitive_cone_add_gizmo", "Draw Cone", "Add Cone"),
       (_T, "builtin.primitive_cylinder_add", "ops.mesh.primitive_cylinder_add_gizmo", "Draw Cylinder", "Add Cylinder"),
       (_T, "builtin.primitive_uv_sphere_add", "ops.mesh.primitive_sphere_add_gizmo", "Draw Sphere", "Add UV Sphere"),
       (_T, "builtin.primitive_ico_sphere_add", "ops.mesh.primitive_sphere_add_gizmo", "Draw Ico Sphere", "Add Ico Sphere")]
TAIL = [(_T, "builtin.annotate", "ops.gpencil.draw", "Annotate", ""), (_T, "builtin.measure", "ops.view3d.ruler", "Measure", ""),
        (_T, "builtin.cursor", "ops.generic.cursor", "Cursor", "")]

HEAD = [[RECT, LIVE, LASSO], None, MOVE, ROTATE, [SCALE, CAGE], TRANSFORM, None]
POLYGONS = [POLY_PEN, HOLE, ADD, None, EXTRUDE, INSET, BEVEL, BRIDGE, None, LOOP, KNIFE, SUBDIVIDE, WELD, None,
            FATTEN, SMOOTH, [SLIDE_E, SLIDE_V], SHEAR, SPIN, RIP, None]
EDGES = [POLY_PEN, HOLE, None, EXTRUDE, BEVEL, BRIDGE, None, LOOP, KNIFE, SUBDIVIDE, WELD, None,
         [SLIDE_E, SLIDE_V], SMOOTH, FATTEN, SHEAR, SPIN, RIP, INSET, ADD, None]
POINTS = [POLY_PEN, HOLE, None, EXTRUDE, BEVEL, BRIDGE, None, KNIFE, LOOP, SUBDIVIDE, WELD, None,
          [SLIDE_V, SLIDE_E], SMOOTH, FATTEN, SHEAR, SPIN, RIP, INSET, ADD, None]
EVERYWHERE = {e[1] for e in (LIVE, RECT, LASSO, MOVE, ROTATE, SCALE, TRANSFORM, CAGE, *ADD, *TAIL)}    # no mesh needed
KEEP_ICON = {e[1] for e in (LIVE, RECT, LASSO, *TAIL)}                     # these look the same in every tab

_shown = {}                  # first member's id -> the id of the one picked last
_open = []                   # the group whose menu is open
_handles = {}                # icon name -> icon_value


def active(window):
    """Is the column this one: a Modeling tab, with whole objects or a mesh being edited?"""
    ws = window.workspace if window is not None else None
    return ws is not None and layouts.spec(layouts.current(ws))["base"] == "Modeling" and \
        bpy.context.mode in {"OBJECT", "EDIT_MESH"}


def _parts(context):
    if context.mode != "EDIT_MESH":
        return POLYGONS
    v, e, f = context.tool_settings.mesh_select_mode
    return POINTS if v else EDGES if e else POLYGONS


def why_not(context, entry):
    """Why this cannot be used now, or "" when it can."""
    if entry[0] in {"brush", "sculpt"}:
        from . import sculpttools
        return sculpttools.why_not(context, entry)
    if entry[1] in EVERYWHERE:
        return ""
    if context.mode == "EDIT_MESH":
        me = context.edit_object.data if context.edit_object else None
        if entry[0] == _C and me is not None and not any(m.total_vert_sel for m in _meshes(context)):
            return "select something first"
        return ""
    ob = context.view_layer.objects.active
    if ob is None or ob.type != "MESH":
        return "select a polygon object first"
    if "b4d_type" in ob:
        return "make the object editable first (C)"
    return "select something first" if entry[0] == _C else ""


def _meshes(context):
    return [ob.data for ob in getattr(context, "objects_in_mode_unique_data", ()) if ob.type == "MESH"]


def _label(entry):
    return f"{entry[3]} ({entry[4]})" if entry[4] else entry[3]


def items(context, active_tool):
    out = [{"tool": None, "icon": "magnifier", "label": "Zoom to Border"}]
    for e in HEAD + _parts(context) + TAIL:
        if e is None:
            if out[-1] is not None:
                out.append(None)
            continue
        members = e if isinstance(e, list) else [e]
        key = members[0][1]
        pick = next((m for m in members if m[1] == active_tool), None)
        if pick is not None:
            _shown[key] = pick[1]
        pick = next((m for m in members if m[1] == _shown.get(key)), members[0])
        why = why_not(context, pick)
        out.append({"tool": pick[1] if pick[0] == _T else None, "icon": pick[2] if pick[1] in KEEP_ICON else "model:" + pick[2],
                    "label": _label(pick), "tip": _label(pick) + (f": {why}" if why else "") + ("  (hold for more)" if len(members) > 1 else ""),
                    "entry": pick, "members": members, "dim": bool(why)})
    return out


# --- using one -----------------------------------------------------------------------------------------------------------
def use(context, entry):
    """Pick the tool, or run the command. True when it could."""
    why = why_not(context, entry)
    if why:
        ob = context.view_layer.objects.active

        def draw(self, _context):
            self.layout.label(text=f"{entry[3]}: {why}")
            if ob is not None and "b4d_type" in ob:
                self.layout.operator("blenda4d.make_editable", text="Make Editable", icon="MESH_DATA")
        context.window_manager.popup_menu(draw, title="", icon="INFO")
        return False
    if entry[0] in {"brush", "sculpt"}:
        from . import sculpttools
        return sculpttools.use(context, entry)
    if context.mode == "OBJECT" and entry[1] not in EVERYWHERE:
        bpy.ops.blenda4d.set_mode(mode="POLYGONS")
        if bpy.context.mode != "EDIT_MESH":
            return False
        bpy.ops.ed.undo_push(message="Polygons")           # going into the polygons is a step of its own
    if entry[0] == _T:
        bpy.ops.wm.tool_set_by_id(name=entry[1])
        if entry[1] == "builtin.bevel":                   # points are bevelled as points, the rest along their edges
            tool = bpy.context.workspace.tools.from_space_view3d_mode("EDIT_MESH", create=False)
            if tool is not None and tool.idname == entry[1]:
                points = bpy.context.tool_settings.mesh_select_mode[0] and bpy.context.mode == "EDIT_MESH"
                tool.operator_properties("mesh.bevel").affect = "VERTICES" if points else "EDGES"
        return True
    name, _, kind = entry[1].partition(":")
    mod, op = name.split(".")
    kw = {"type": kind} if kind else {}
    try:
        getattr(getattr(bpy.ops, mod), op)("EXEC_DEFAULT", False, **kw)          # the caller adds the one undo step
    except RuntimeError as ex:
        text = str(ex).strip().splitlines()[0].replace("Error: ", "")

        def draw(self, _context):
            self.layout.label(text=f"{entry[3]}: {text}")
        context.window_manager.popup_menu(draw, title="", icon="INFO")
        return False
    return True


class BLENDA4D_OT_model_tool(bpy.types.Operator):
    bl_idname = "blenda4d.model_tool"
    bl_label = "Modeling Tool"
    bl_options = {"INTERNAL"}
    group: bpy.props.StringProperty()
    which: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, props):
        e = _find(props.group, props.which)
        return _label(e) if e else cls.bl_label

    def execute(self, context):
        e = _find(self.group, self.which)
        if e is None:
            return {"CANCELLED"}
        if self.group:
            from . import sculpttools
            (sculpttools._shown if e[0] in {"brush", "sculpt"} else _shown)[self.group] = self.which
        from . import topbar, toolcol
        area, region, _sp = topbar.main_view(context)
        if area is None:
            return {"CANCELLED"}
        with context.temp_override(window=context.window, area=area, region=region):
            done = use(bpy.context, e)
        if done and e[0] == _C:
            bpy.ops.ed.undo_push(message=e[3])
        toolcol._redraw(context.window)
        return {"FINISHED"} if done else {"CANCELLED"}


def _find(group, which):
    from . import sculpttools
    if any(m[1] == which for m in (_open[0] if _open else ())):
        return next(m for m in _open[0] if m[1] == which)
    return next((m for m in (*all_entries(), *sculpttools.all_entries()) if m[1] == which), None)


def all_entries():
    for e in HEAD + POLYGONS + EDGES + POINTS + TAIL:
        for m in (e if isinstance(e, list) else [e] if e else []):
            yield m


class BLENDA4D_MT_model_tools(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_model_tools"
    bl_label = "Tools"

    def draw(self, context):
        for m in _open[0] if _open else ():
            row = self.layout.row()
            row.enabled = not why_not(context, m)
            o = row.operator("blenda4d.model_tool", text=("   " if m[0] in {_T, "sculpt"} else "") + m[3], **icon_kw(m))
            o.group, o.which = _open[0][0][1], m[1]


def open_menu(members):
    _open[:] = [members]
    bpy.ops.wm.call_menu(name=BLENDA4D_MT_model_tools.bl_idname)


# --- icons -----------------------------------------------------------------------------------------------------------------
def recolour(cols):
    """Blender's accent colours in a tool icon's corner colours (bytes, RGBA) -> Blenda's."""
    out = bytearray(cols)
    for i in range(0, len(out), 4):
        new = ACCENTS.get(tuple(out[i:i + 3]))
        if new:
            out[i:i + 3] = bytes(new)
    return bytes(out)


def blender_icon_file(name):
    v = "%d.%d" % bpy.app.version[:2]
    base = os.path.join(bpy.utils.resource_path("LOCAL"), "datafiles", "icons", name + ".dat")
    if os.path.exists(base):
        return base
    p = os.path.join(os.path.dirname(bpy.app.binary_path), "..", "Resources", v, "datafiles", "icons", name + ".dat")
    return p if os.path.exists(p) else None


def command_icon(name):
    p = os.path.join(icons.DIR, name + "__model.png")
    return p if os.path.exists(p) else None


def icon_kw(entry):
    """The entry's icon for a menu."""
    if entry[0] in {"brush", "sculpt"}:
        from . import sculpttools
        return sculpttools.icon_kw(entry)
    if entry[0] == _C:
        iv = icons.icon(entry[2].upper(), "model")
        return {"icon_value": iv} if iv else {"icon": entry[2].upper()}
    iv = tool_icon(entry[2])
    return {"icon_value": iv} if iv else {}


def tool_icon(name):
    """One of Blender's tool icons in Blenda's accent colours, for a button or menu item."""
    if name not in _handles:
        path, iv = blender_icon_file(name), 0
        if path:
            with open(path, "rb") as f:
                b = f.read()
            if b[:3] == b"VCO":
                n = (len(b) - 8) // 18
                try:
                    iv = bpy.app.icons.new_triangles((b[4] or 256, b[5] or 256), b[8:8 + n * 6], recolour(b[8 + n * 6:8 + n * 18]))
                except (TypeError, ValueError):
                    iv = 0
        _handles[name] = iv
    iv = _handles[name]
    if not iv:
        from . import bars
        iv = bars.tool_icon(name)
    return iv


classes = (BLENDA4D_OT_model_tool, BLENDA4D_MT_model_tools)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    for iv in _handles.values():
        if iv:
            try:
                bpy.app.icons.release(iv)
            except (ValueError, TypeError):
                pass
    _handles.clear()
    _open.clear()
