# SPDX-License-Identifier: GPL-3.0-or-later
"""Make Editable (C) and Ctrl+drag copy.

Make Editable: a primitive becomes a plain polygon object. Its own generator is applied and its kind is dropped, so
its procedural settings are gone and the Object Manager shows it as a polygon object. Deformers on it stay live.
A spline shape becomes a plain spline; any other object is converted to a mesh as Blender does it.

Ctrl+drag on the Move handle: the selected objects are copied first, then the handle moves the copies."""
import bpy

from . import primitives


def _apply(context, ob, mod):
    with context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def make_editable(context, ob):
    """True when the object changed."""
    from . import collapse
    if collapse.is_generator(ob):                          # a generator: its result takes its place
        return collapse.make_editable(context, ob)
    kind = ob.get("b4d_type")
    if ob.type == "MESH" and kind in primitives.TYPE_TO_KIND:
        if ob.data.users > 1:
            ob.data = ob.data.copy()
        for mod in list(primitives._own_mods(ob)):
            _apply(context, ob, mod)
        del ob["b4d_type"]
        return True
    from . import splines
    if splines.shape_kind(ob) is not None:
        with context.temp_override(object=ob, active_object=ob):
            bpy.ops.blenda4d.spline_make_editable()
        return True
    if ob.type in {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD"}:
        with context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
            bpy.ops.object.convert(target="MESH")
        if "b4d_type" in ob and primitives.GENERATOR_MOD not in ob.modifiers:
            del ob["b4d_type"]
        return True
    return False


class BLENDA4D_OT_make_editable(bpy.types.Operator):
    bl_idname = "blenda4d.make_editable"
    bl_label = "Make Editable"
    bl_description = ("Turn the selected primitives into polygon objects whose points can be edited (their settings go). "
                      "A generator becomes what it makes, in its place")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects or context.active_object)

    def execute(self, context):
        from . import collapse
        obs = collapse.tops(list(context.selected_objects)) or [context.active_object]
        done = 0
        for name in [o.name for o in obs if o is not None]:   # one may take another's place: look each up again
            ob = bpy.data.objects.get(name)
            if ob is not None:
                done += make_editable(context, ob)
        if not done:
            self.report({"INFO"}, "Nothing to make editable")
            return {"CANCELLED"}
        for a in context.screen.areas:
            a.tag_redraw()
        return {"FINISHED"}


class BLENDA4D_OT_copy_for_drag(bpy.types.Operator):
    """Copy the selected objects; the drag that started this goes on to move the copies"""
    bl_idname = "blenda4d.copy_for_drag"
    bl_label = "Copy and Move"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def invoke(self, context, event):
        bpy.ops.object.duplicate(linked=False)
        return {"FINISHED", "PASS_THROUGH"}


class BLENDA4D_OT_edge_to_spline(bpy.types.Operator):
    """Make a spline object from the selected edges; the polygon object stays as it is"""
    bl_idname = "blenda4d.edge_to_spline"
    bl_label = "Edge to Spline"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = context.edit_object
        return ob is not None and ob.type == "MESH"

    def execute(self, context):
        ob = context.edit_object
        ob.update_from_editmode()
        if not any(e.select for e in ob.data.edges):
            self.report({"INFO"}, "Select the edges to turn into a spline first")
            return {"CANCELLED"}
        before = set(bpy.data.objects)
        bpy.ops.mesh.duplicate()
        bpy.ops.mesh.separate(type="SELECTED")             # the copy of the edges becomes an object of its own
        new = next((o for o in bpy.data.objects if o not in before), None)
        bpy.ops.object.mode_set(mode="OBJECT")
        if new is None:
            return {"CANCELLED"}
        for o in context.view_layer.objects:
            o.select_set(False)
        new.select_set(True)
        context.view_layer.objects.active = new
        new.modifiers.clear()                               # the copy carries the mesh's modifiers: not wanted
        bpy.ops.object.convert(target="CURVE")
        new.name = ob.name + " Spline"
        new.data.name = new.name
        new.data.materials.clear()
        if "b4d_type" in new:
            del new["b4d_type"]
        return {"FINISHED"}


# --- Ctrl+C / Ctrl+V: polygons as well as objects ------------------------------------------------------------------
_clip = {"kind": None, "mesh": None, "matrix": None, "name": ""}


def _copy_polygons(ob):
    import bmesh
    ob.update_from_editmode()
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    keep = {f for f in bm.faces if f.select}
    if not keep:
        bm.free()
        return False
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in keep], context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    old = _clip.get("mesh")
    if old is not None and old.name in bpy.data.meshes and old.users == 0:
        bpy.data.meshes.remove(old)
    me = bpy.data.meshes.new(".Blenda Polygon Clipboard")
    bm.to_mesh(me)
    bm.free()
    for m in ob.data.materials:
        me.materials.append(m)
    _clip.update(kind="POLYGONS", mesh=me, matrix=ob.matrix_world.copy(), name=ob.name)
    return True


class BLENDA4D_OT_copy(bpy.types.Operator):
    """Copy: the selected polygons in Edit Mode, the selected objects otherwise"""
    bl_idname = "blenda4d.copy"
    bl_label = "Copy"

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "EDIT_MESH"}

    def execute(self, context):
        if context.mode == "EDIT_MESH":
            if not _copy_polygons(context.edit_object):
                self.report({"INFO"}, "Select the polygons to copy first")
                return {"CANCELLED"}
            self.report({"INFO"}, "Polygons copied")
            return {"FINISHED"}
        _clip["kind"] = "OBJECTS"
        return bpy.ops.view3d.copybuffer()


class BLENDA4D_OT_paste(bpy.types.Operator):
    """Paste: copied polygons become a new object (Object Mode) or join the edited object (Edit Mode)"""
    bl_idname = "blenda4d.paste"
    bl_label = "Paste"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode in {"OBJECT", "EDIT_MESH"}

    def execute(self, context):
        me = _clip.get("mesh")
        polys = _clip["kind"] == "POLYGONS" and me is not None and me.name in bpy.data.meshes
        if not polys:
            if context.mode != "OBJECT":
                return {"CANCELLED"}
            return bpy.ops.view3d.pastebuffer()
        if context.mode == "EDIT_MESH":                     # into the object being edited, where they were
            import bmesh
            ob = context.edit_object
            bm = bmesh.from_edit_mesh(ob.data)
            for f in bm.faces:
                f.select = False
            tmp = me.copy()
            tmp.transform(ob.matrix_world.inverted() @ _clip["matrix"])
            n = len(bm.faces)
            bm.from_mesh(tmp)
            bpy.data.meshes.remove(tmp)
            bm.faces.ensure_lookup_table()
            for f in bm.faces[n:]:
                f.select = True
            bm.select_flush(True)
            bmesh.update_edit_mesh(ob.data)
            return {"FINISHED"}
        new_me = me.copy()
        new_me.name = _clip["name"] + " Polygons"
        ob = bpy.data.objects.new(new_me.name, new_me)
        ob.matrix_world = _clip["matrix"]
        context.collection.objects.link(ob)
        for o in context.view_layer.objects:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        return {"FINISHED"}


class BLENDA4D_OT_move_along_normal(bpy.types.Operator):
    """Move the selected points, edges or polygons straight out or in along the surface (Shrink/Fatten in Blender)"""
    bl_idname = "blenda4d.move_along_normal"
    bl_label = "Move Along Normal"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def invoke(self, context, event):
        return bpy.ops.transform.shrink_fatten("INVOKE_DEFAULT")


def _edge_menu(self, context):
    """Blender's right-click menu in Edit Mode, edge selection: Blenda's edge commands at the end."""
    if context.mode != "EDIT_MESH" or not context.tool_settings.mesh_select_mode[1]:
        return
    lay = self.layout
    lay.separator()
    lay.operator("blenda4d.move_along_normal", icon="ORIENTATION_NORMAL")   # small icons, as in the rest of the menu
    lay.operator("blenda4d.edge_to_spline", icon="CURVE_DATA")


# M, then a letter: the modelling commands that have a two-key shortcut (Edit Mode).
M_KEYS = {"S": ("Bevel", "tool", "builtin.bevel"), "K": ("Knife", "tool", "builtin.knife"),
          "T": ("Extrude", "tool", "builtin.extrude_region"), "W": ("Inset", "tool", "builtin.inset_faces"),
          "L": ("Loop Cut", "tool", "builtin.loop_cut"), "B": ("Bridge", "op", "mesh.bridge_edge_loops"),
          "E": ("Polygon Pen", "tool", "builtin.poly_build")}   # click points to build polygons; snaps to points / edges


class BLENDA4D_OT_m_keys(bpy.types.Operator):
    """M, then a letter: S Bevel, K Knife, T Extrude, W Inset, L Loop Cut, B Bridge, E Polygon Pen"""
    bl_idname = "blenda4d.m_keys"
    bl_label = "Modelling Commands (M)"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH"

    def invoke(self, context, event):
        hint = "   ".join(f"{k} {v[0]}" for k, v in M_KEYS.items())
        context.workspace.status_text_set("M:   " + hint + "   (Esc cancels)")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _done(self, context):
        context.workspace.status_text_set(None)

    def modal(self, context, event):
        if event.value != "PRESS" or event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE", "LEFT_SHIFT", "RIGHT_SHIFT",
                                                     "LEFT_CTRL", "RIGHT_CTRL", "LEFT_ALT", "RIGHT_ALT", "OSKEY"}:
            return {"RUNNING_MODAL"}
        self._done(context)
        hit = M_KEYS.get(event.type)
        if hit is None:
            return {"CANCELLED"}
        _label, kind, ident = hit
        try:
            if kind == "tool":
                bpy.ops.wm.tool_set_by_id(name=ident)
            else:
                mod, name = ident.split(".")
                getattr(getattr(bpy.ops, mod), name)("INVOKE_DEFAULT")
        except RuntimeError as ex:
            self.report({"INFO"}, str(ex).split("Error: ")[-1].strip())
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (BLENDA4D_OT_make_editable, BLENDA4D_OT_copy_for_drag, BLENDA4D_OT_m_keys, BLENDA4D_OT_edge_to_spline, BLENDA4D_OT_copy, BLENDA4D_OT_paste, BLENDA4D_OT_move_along_normal)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(_edge_menu)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(_edge_menu)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
