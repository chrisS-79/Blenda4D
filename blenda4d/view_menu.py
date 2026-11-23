# SPDX-License-Identifier: GPL-3.0-or-later
"""The viewport's right-click menu, by what is being worked on.

Whole objects: the same object commands as the Object Manager's menu, and Blender's object commands that have no other
place (Shade Smooth, Auto Smooth, Set Origin, Apply, Join, Parent, Snap). Points, edges, polygons: the modeling
commands for that kind of element, then selection. Splines: the spline commands. Each entry is Blender's own command
under the name Blenda gives it; its tooltip says what Blender calls it."""
import bpy

from . import roles

SEP = None


def C(label, op, icon="NONE", **props):
    return (label, op, icon, props)


def M(label, menu, icon="NONE"):
    return (label, "@" + menu, icon, {})


SHARED_TOP = [C("Polygon Pen", "@tool:builtin.poly_build", "GREASEPENCIL"), C("Knife", "@tool:builtin.knife", "MOD_EDGESPLIT"),
              C("Loop Cut", "@tool:builtin.loop_cut", "MOD_MULTIRES"), C("Extrude", "@tool:builtin.extrude_region", "MOD_SOLIDIFY"),
              C("Bevel", "@tool:builtin.bevel", "MOD_BEVEL")]
POINTS = SHARED_TOP + [SEP,
          C("Connect Points", "mesh.vert_connect_path", "LINKED"), C("Close Polygon Hole", "mesh.edge_face_add", "SNAP_FACE"),
          C("Bridge", "mesh.bridge_edge_loops", "LINKED"), C("Weld", "mesh.merge", "AUTOMERGE_ON", type="CENTER"),
          C("Optimize", "mesh.remove_doubles", "AUTOMERGE_OFF"), C("Dissolve", "mesh.dissolve_verts", "X"),
          C("Slide", "transform.vert_slide", "ARROW_LEFTRIGHT"), C("Smooth", "mesh.vertices_smooth", "MOD_SMOOTH"),
          C("Split", "mesh.split", "UNLINKED"), C("Rip", "mesh.rip_move", "SCULPTMODE_HLT"), SEP,
          C("Subdivide", "mesh.subdivide", "MOD_SUBSURF"), C("Delete", "mesh.delete", "TRASH", type="VERT")]
EDGES = SHARED_TOP + [SEP,
         C("Connect", "mesh.subdivide", "LINKED"), C("Bridge", "mesh.bridge_edge_loops", "LINKED"),
         C("Close Polygon Hole", "mesh.edge_face_add", "SNAP_FACE"), C("Dissolve", "mesh.dissolve_edges", "X"),
         C("Slide", "transform.edge_slide", "ARROW_LEFTRIGHT"), C("Spin Edge", "mesh.edge_rotate", "LOOP_FORWARDS"),
         C("Weld", "mesh.merge", "AUTOMERGE_ON", type="CENTER"), C("Split", "mesh.split", "UNLINKED"),
         C("Edge to Spline", "blenda4d.edge_to_spline", "CURVE_DATA"), SEP,
         C("Break Phong Shading", "mesh.mark_sharp", "EDGESEL"), C("Unbreak Phong Shading", "mesh.mark_sharp", "SHARPCURVE", clear=True),
         C("Mark Seam", "mesh.mark_seam", "UV"), C("Clear Seam", "mesh.mark_seam", "X", clear=True), SEP,
         C("Select Loop", "mesh.select_edge_loop_multi", "ARROW_LEFTRIGHT"),
         C("Select Ring", "mesh.select_edge_ring_multi", "PROP_CON"), C("Delete", "mesh.delete", "TRASH", type="EDGE")]
POLYGONS = SHARED_TOP + [SEP,
            C("Extrude Inner", "@tool:builtin.inset_faces", "MOD_SOLIDIFY"), C("Matrix Extrude", "mesh.extrude_repeat", "MOD_ARRAY"),
            C("Smooth Shift", "@tool:builtin.extrude_along_normals", "ORIENTATION_NORMAL"),
            C("Bridge", "mesh.bridge_edge_loops", "LINKED"), C("Split", "mesh.split", "UNLINKED"),
            C("Disconnect", "mesh.edge_split", "MOD_EDGESPLIT", type="EDGE"), C("Poke", "mesh.poke", "MESH_ICOSPHERE"),
            C("Dissolve", "mesh.dissolve_faces", "X"), SEP,
            C("Subdivide", "mesh.subdivide", "MOD_SUBSURF"), C("Triangulate", "mesh.quads_convert_to_tris", "MOD_TRIANGULATE"),
            C("Untriangulate", "mesh.tris_convert_to_quads", "MESH_GRID"), SEP,
            C("Reverse Normals", "mesh.flip_normals", "NORMALS_FACE"), C("Align Normals", "mesh.normals_make_consistent", "NORMALS_FACE"),
            C("Shade Smooth", "mesh.faces_shade_smooth", "SHADING_SMOOTH"), C("Shade Flat", "mesh.faces_shade_flat", "SHADING_FLAT"), SEP,
            C("Delete", "mesh.delete", "TRASH", type="FACE")]
MESH_TAIL = [SEP, C("Select All", "mesh.select_all", "SELECT_SET", action="SELECT"),
             C("Deselect All", "mesh.select_all", "SELECT_SUBTRACT", action="DESELECT"),
             C("Invert Selection", "mesh.select_all", "SELECT_DIFFERENCE", action="INVERT"),
             C("Select Connected", "mesh.select_linked", "LINKED"), C("Grow Selection", "mesh.select_more", "ADD"),
             C("Shrink Selection", "mesh.select_less", "REMOVE"), SEP, C("Hide Selected", "mesh.hide", "HIDE_ON", unselected=False),
             C("Unhide All", "mesh.reveal", "HIDE_OFF")]
SPLINE = [C("Create Point", "curve.vertex_add", "ADD"), C("Subdivide", "curve.subdivide", "MOD_SUBSURF"),
          C("Delete Points", "curve.delete", "TRASH", type="VERT"), SEP,
          C("Hard Interpolation", "curve.handle_type_set", "HANDLE_VECTOR", type="VECTOR"),
          C("Soft Interpolation", "curve.handle_type_set", "HANDLE_AUTO", type="AUTOMATIC"),
          C("Equal Tangent Length", "curve.handle_type_set", "HANDLE_ALIGNED", type="ALIGNED"),
          C("Break Tangents", "curve.handle_type_set", "HANDLE_FREE", type="FREE_ALIGN"), SEP,
          C("Close Spline", "curve.cyclic_toggle", "CURVE_BEZCIRCLE"), C("Reverse Sequence", "curve.switch_direction", "ARROW_LEFTRIGHT"),
          C("Join Segment", "curve.make_segment", "LINKED"), C("Split Segment", "curve.split", "UNLINKED"),
          C("Smooth", "curve.smooth", "MOD_SMOOTH"), SEP,
          C("Select All", "curve.select_all", "SELECT_SET", action="SELECT"), C("Deselect All", "curve.select_all", "SELECT_SUBTRACT", action="DESELECT"),
          C("Select Connected", "curve.select_linked", "LINKED"), C("Hide Selected", "curve.hide", "HIDE_ON"), C("Unhide All", "curve.reveal", "HIDE_OFF")]
OBJECT_BLENDER = [M("Set Origin", "VIEW3D_MT_object_origin_menu_b4d", "OBJECT_ORIGIN"),
                  M("Apply", "VIEW3D_MT_object_apply", "CHECKMARK"), M("Snap", "VIEW3D_MT_snap", "SNAP_ON"), SEP,
                  C("Shade Smooth", "object.shade_smooth", "SHADING_SMOOTH"), C("Shade Auto Smooth", "object.shade_auto_smooth", "MOD_SMOOTH"),
                  C("Shade Flat", "object.shade_flat", "SHADING_FLAT"), SEP,
                  C("Connect and Delete", "object.join", "AUTOMERGE_ON"), C("Duplicate", "object.duplicate_move", "DUPLICATE"),
                  C("Instance", "object.duplicate_move_linked", "LINKED"), SEP,
                  C("Make Child of Active", "object.parent_set", "CON_CHILDOF", type="OBJECT", keep_transform=True),
                  C("Move Up a Level", "object.parent_clear", "X", type="CLEAR_KEEP_TRANSFORM"), SEP,
                  C("Delete", "object.delete", "TRASH")]


_icons = set()


def icon(name):
    """The icon when this Blender has it, else none."""
    if not _icons:
        _icons.update(i.identifier for i in bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items)
    return name if name in _icons else "NONE"


def _draw(lay, items):
    for it in items:
        if it is None:
            lay.separator()
            continue
        label, op, ic, props = it
        ic = icon(ic)
        if op.startswith("@tool:"):
            lay.operator("wm.tool_set_by_id", text=label, icon=ic).name = op[6:]
        elif op.startswith("@"):
            lay.menu(op[1:], text=label, icon=ic)
        else:
            o = lay.operator(op, text=label, icon=ic)
            for k, v in props.items():
                setattr(o, k, v)


class VIEW3D_MT_object_origin_menu_b4d(bpy.types.Menu):
    bl_idname = "VIEW3D_MT_object_origin_menu_b4d"
    bl_label = "Set Origin"
    bl_description = "Move the object's origin (its axis) without moving the object"

    def draw(self, context):
        lay = self.layout
        for text, kind in (("Axis to Center", "ORIGIN_CENTER_OF_VOLUME"), ("Axis to Bottom of Bounds", "ORIGIN_GEOMETRY"),
                           ("Axis to 3D Cursor", "ORIGIN_CURSOR"), ("Object to Axis (Geometry to Origin)", "GEOMETRY_ORIGIN")):
            lay.operator("object.origin_set", text=text).type = kind


class BLENDA4D_MT_view_context(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_view_context"
    bl_label = "Commands"
    bl_description = "The commands for what is being worked on"

    def draw(self, context):
        lay = self.layout
        lay.operator_context = "INVOKE_REGION_WIN"
        mode = context.mode
        if mode == "EDIT_MESH":
            v, e, f = context.tool_settings.mesh_select_mode
            _draw(lay, (POINTS if v else EDGES if e else POLYGONS) + MESH_TAIL)
        elif mode == "EDIT_CURVE":
            _draw(lay, SPLINE)
        elif mode == "OBJECT":
            from . import om_menu
            if context.selected_objects:
                om_menu.BLENDA4D_MT_om_context.draw(self, context)
                lay.separator()
                _draw(lay, OBJECT_BLENDER)
            else:
                lay.menu("BLENDA4D_MT_main_create", text="Create", icon="ADD")
                lay.operator("blenda4d.object_info", text="Scene Information", icon="SCENE_DATA").scene = True


class BLENDA4D_OT_view_context(bpy.types.Operator):
    bl_idname = "blenda4d.view_context"
    bl_label = "Commands"
    bl_description = "The commands for what is being worked on: whole objects, points, edges, polygons or splines"

    @classmethod
    def poll(cls, context):
        from . import switch
        return switch.is_on() and context.area is not None and context.area.type == "VIEW_3D" and \
            context.mode in {"OBJECT", "EDIT_MESH", "EDIT_CURVE"}

    def invoke(self, context, event):
        if context.mode == "OBJECT":                       # a right click on an object that is not selected picks it alone
            hit = _object_under(context, event)
            if hit is not None and not hit.select_get():
                for o in context.view_layer.objects:
                    o.select_set(False)
                hit.select_set(True)
                context.view_layer.objects.active = hit
        bpy.ops.wm.call_menu(name=BLENDA4D_MT_view_context.bl_idname)
        return {"FINISHED"}


def _object_under(context, event):
    from bpy_extras import view3d_utils
    region, r3 = context.region, context.region_data
    if region is None or r3 is None:
        return None
    co = (event.mouse_region_x, event.mouse_region_y)
    origin = view3d_utils.region_2d_to_origin_3d(region, r3, co)
    direction = view3d_utils.region_2d_to_vector_3d(region, r3, co)
    hit, _loc, _n, _i, ob, _m = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, direction)
    if not hit or ob is None:
        return None
    ob = ob.original
    while ob is not None and ob.get("b4d_consumed") is not None and ob.parent is not None:   # used up by a generator: the generator
        ob = ob.parent
    return ob if ob.name in context.view_layer.objects else None


classes = (VIEW3D_MT_object_origin_menu_b4d, BLENDA4D_MT_view_context, BLENDA4D_OT_view_context)
_keymaps = []


def register():
    for c in classes:
        bpy.utils.register_class(c)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        for name in ("Object Mode", "Mesh", "Curve"):
            km = kc.keymaps.new(name=name, space_type="EMPTY")
            _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_view_context.bl_idname, "RIGHTMOUSE", "PRESS")))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
