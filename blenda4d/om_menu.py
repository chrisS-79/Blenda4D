# SPDX-License-Identifier: GPL-3.0-or-later
"""The Object Manager's right-click menu: tags, selection, Make Editable and Current State to
Object, grouping, the object's tracks, materials and information.

A right click on an object that is not selected selects it first. Every entry works on the selected objects. Tags are
Blender's own features shown as tags: a Target tag is a Damped Track constraint, a Rigid Body tag is Blender's rigid
body, and so on; each one shows in the object's row and can be taken off again from this menu."""
import bpy

from . import managers, roles
from .view_menu import icon

# tag key: (menu, name, icon, Blender's name for it)
TAGS = {
    "TARGET": ("Animation", "Target", "CON_TRACKTO", "Damped Track constraint"),
    "LOOK_CAMERA": ("Animation", "Look at Camera", "CON_CAMERASOLVER", "Track To constraint aimed at the scene camera"),
    "ALIGN_SPLINE": ("Animation", "Align to Spline", "CON_FOLLOWPATH", "Follow Path constraint"),
    "MATERIAL": ("Material", "Material", "MATERIAL", "Material slot"),
    "PHONG": ("Modeling", "Phong", "SHADING_SMOOTH", "Smooth by Angle"),
    "PROTECTION": ("Other", "Protection", "LOCKED", "Locked location, rotation and scale"),
    "RIGID": ("Simulation", "Rigid Body", "RIGID_BODY", "Rigid body, active"),
    "COLLIDER": ("Simulation", "Collider Body", "RIGID_BODY_CONSTRAINT", "Rigid body, passive"),
    "CLOTH": ("Simulation", "Cloth", "MOD_CLOTH", "Cloth modifier"),
    "COLLISION": ("Simulation", "Cloth Collider", "MOD_PHYSICS", "Collision modifier"),
    "SCULPT": ("Sculpting", "Sculpt", "SCULPTMODE_HLT", "Multiresolution modifier"),   # put on by Subdivide while sculpting
}
CON = {"TARGET": "DAMPED_TRACK", "LOOK_CAMERA": "TRACK_TO", "ALIGN_SPLINE": "FOLLOW_PATH"}
MENUS = ("Animation", "Material", "Modeling", "Other", "Simulation")
B4D = "b4d_tag"                       # constraints Blenda put on as a tag carry this in their name


def _con(ob, key):
    return next((c for c in ob.constraints if c.type == CON[key] and c.name.startswith(TAGS[key][1])), None)


def has(ob, key):
    """Does the object carry this tag?"""
    if key in CON:
        return _con(ob, key) is not None
    if key == "PHONG":
        return ob.type == "MESH" and any(m.type == "NODES" and m.node_group and "Smooth by Angle" in m.node_group.name or
                                         m.name.startswith("Smooth") for m in ob.modifiers)
    if key == "PROTECTION":
        return all(ob.lock_location) and all(ob.lock_rotation) and all(ob.lock_scale)
    if key in {"RIGID", "COLLIDER"}:
        rb = ob.rigid_body
        return rb is not None and (rb.type == "ACTIVE") == (key == "RIGID")
    if key == "CLOTH":
        return any(m.type == "CLOTH" for m in ob.modifiers)
    if key == "COLLISION":
        return any(m.type == "COLLISION" for m in ob.modifiers)
    if key == "SCULPT":
        return any(m.type == "MULTIRES" for m in ob.modifiers)
    if key == "MATERIAL":
        return any(sl.material for sl in getattr(ob, "material_slots", ()))
    return False


def tags(ob):
    """The tags this menu put on (shown in the object's row, after the materials)."""
    return [(icon(TAGS[k][2]), k) for k in TAGS if k not in {"MATERIAL", "PHONG"} and has(ob, k)]


def _mesh_only(key):
    return key in {"SCULPT", "PHONG", "RIGID", "COLLIDER", "CLOTH", "COLLISION", "MATERIAL"}


def add(context, ob, key):
    if _mesh_only(key) and ob.type != "MESH":
        return False
    if has(ob, key):
        return False
    if key in CON:
        c = ob.constraints.new(CON[key])
        c.name = TAGS[key][1]
        if key == "LOOK_CAMERA":
            c.target = context.scene.camera if context.scene.camera != ob else None
            c.track_axis, c.up_axis = "TRACK_Z", "UP_Y"
        elif key == "TARGET":
            c.track_axis = "TRACK_NEGATIVE_Z"
        elif key == "ALIGN_SPLINE":
            from . import tag_pages
            tag_pages.setup_align(c)
        return True
    with context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
        if key == "PHONG":
            bpy.ops.object.shade_auto_smooth()
        elif key == "PROTECTION":
            ob.lock_location = ob.lock_rotation = ob.lock_scale = (True, True, True)
        elif key in {"RIGID", "COLLIDER"}:
            if ob.rigid_body is None:
                bpy.ops.rigidbody.object_add(type="ACTIVE" if key == "RIGID" else "PASSIVE")
            else:
                ob.rigid_body.type = "ACTIVE" if key == "RIGID" else "PASSIVE"
        elif key == "CLOTH":
            ob.modifiers.new("Cloth", "CLOTH")
        elif key == "COLLISION":
            ob.modifiers.new("Collision", "COLLISION")
        elif key == "SCULPT":                              # levels to sculpt on, the first one made
            m = ob.modifiers.new("Multires", "MULTIRES")
            bpy.ops.object.multires_subdivide(modifier=m.name, mode="CATMULL_CLARK")
        elif key == "MATERIAL":
            mat = bpy.data.materials.get(context.window_manager.b4d_material) or bpy.data.materials.new("Mat")
            ob.data.materials.append(mat)
    return True


def remove(context, ob, key):
    if key in CON:
        c = _con(ob, key)
        if c is not None:
            ob.constraints.remove(c)
        if key == "ALIGN_SPLINE":
            from . import tag_pages
            tag_pages.keep_hold(ob)
    elif key == "PHONG":
        for m in [m for m in ob.modifiers if m.name.startswith("Smooth")]:
            ob.modifiers.remove(m)
    elif key == "PROTECTION":
        ob.lock_location = ob.lock_rotation = ob.lock_scale = (False, False, False)
    elif key in {"RIGID", "COLLIDER"}:
        with context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
            bpy.ops.rigidbody.object_remove()
    elif key in {"CLOTH", "COLLISION"}:
        for m in [m for m in ob.modifiers if m.type == key]:
            ob.modifiers.remove(m)
    elif key == "SCULPT":                                  # the sculpted detail goes with it, as when a Sculpt tag is deleted
        for m in [m for m in ob.modifiers if m.type == "MULTIRES"]:
            ob.modifiers.remove(m)
        ob.pop("_b4d_freeze", None)


class BLENDA4D_OT_om_tag(bpy.types.Operator):
    bl_idname = "blenda4d.om_tag"
    bl_label = "Tag"
    bl_options = {"REGISTER", "UNDO"}
    key: bpy.props.StringProperty(options={"SKIP_SAVE"})
    off: bpy.props.BoolProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        t = TAGS.get(props.key)
        if t is None:
            return cls.bl_label
        return (f"Take the {t[1]} tag off the selected objects" if props.off else f"Give the selected objects a {t[1]} tag") + f" ({t[3]})"

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        n = 0
        for ob in context.selected_objects:
            if self.off:
                if has(ob, self.key):
                    remove(context, ob, self.key)
                    n += 1
            elif add(context, ob, self.key):
                n += 1
        if not n:
            self.report({"INFO"}, "Nothing to change" if self.off else f"The selected objects cannot take a {TAGS[self.key][1]} tag, or have one")
            return {"CANCELLED"}
        _redraw(context)
        return {"FINISHED"}


def _tag_menu(group):
    def draw(self, context):
        for key, t in TAGS.items():
            if t[0] == group:
                self.layout.operator("blenda4d.om_tag", text=t[1], icon=icon(t[2])).key = key
    return type(f"BLENDA4D_MT_om_tags_{group.lower()}", (bpy.types.Menu,), {
        "bl_idname": f"BLENDA4D_MT_om_tags_{group.lower()}", "bl_label": f"{group} Tags", "bl_description": f"Add {group.lower()} tags", "draw": draw})


TAG_MENUS = [_tag_menu(g) for g in MENUS]


class BLENDA4D_MT_om_tags_remove(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_om_tags_remove"
    bl_label = "Remove Tag"
    bl_description = "Take a tag off the selected objects"

    def draw(self, context):
        found = [k for k in TAGS if any(has(ob, k) for ob in context.selected_objects)]
        for k in found:
            o = self.layout.operator("blenda4d.om_tag", text=TAGS[k][1], icon=icon(TAGS[k][2]))
            o.key, o.off = k, True
        if not found:
            self.layout.label(text="No tags on the selected objects")


# --- selection, grouping ------------------------------------------------------------------------------------------------
class BLENDA4D_OT_select_children(bpy.types.Operator):
    bl_idname = "blenda4d.select_children"
    bl_label = "Select Children"
    bl_description = "Add everything under the selected objects to the selection"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        for ob in list(context.selected_objects):
            for c in ob.children_recursive:
                if c.name in context.view_layer.objects:
                    c.select_set(True)
        return {"FINISHED"}


def _lift(ob, parent):
    mw = ob.matrix_world.copy()
    ob.parent = parent
    ob.matrix_parent_inverse.identity()
    ob.matrix_world = mw


class BLENDA4D_OT_ungroup(bpy.types.Operator):
    bl_idname = "blenda4d.ungroup"
    bl_label = "Ungroup Objects"
    bl_description = "The objects under each selected Null move up a level, and the Null goes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and any(ob.children for ob in context.selected_objects)

    def execute(self, context):
        done = 0
        for ob in list(context.selected_objects):
            if not ob.children:
                continue
            kids = list(ob.children)
            for c in kids:
                _lift(c, ob.parent)
                c.select_set(True)
            if ob.type == "EMPTY" and "b4d_type" not in ob:
                bpy.data.objects.remove(ob)
            done += 1
        if not done:
            return {"CANCELLED"}
        _redraw(context)
        return {"FINISHED"}


class BLENDA4D_OT_delete_without_children(bpy.types.Operator):
    bl_idname = "blenda4d.delete_without_children"
    bl_label = "Delete Without Children"
    bl_description = "Delete the selected objects; what is under them moves up a level and stays"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        for ob in list(context.selected_objects):
            for c in list(ob.children):
                _lift(c, ob.parent)
            bpy.data.objects.remove(ob)
        _redraw(context)
        return {"FINISHED"}


class BLENDA4D_OT_show_tracks(bpy.types.Operator):
    bl_idname = "blenda4d.show_tracks"
    bl_label = "Show Tracks"
    bl_options = {"REGISTER"}
    curves: bpy.props.BoolProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        return "Open the Timeline under the viewport with " + ("the F-Curves of the selected objects" if props.curves else
                                                                "the keys of the selected objects (Dope Sheet)")

    def execute(self, context):
        from . import build, timeline_edit
        timeline_edit.set_mode(context.workspace, "CURVES" if self.curves else "KEYS")
        if not roles.areas(context.screen, "TL_EDIT") and not build.busy():
            build.run_steps(build.dock_steps(context.window, True))
        _redraw(context)
        return {"FINISHED"}


# --- materials ----------------------------------------------------------------------------------------------------------------
def _give(context, mat):
    n = 0
    for ob in context.selected_objects:
        if hasattr(ob.data, "materials"):
            ob.data.materials.append(mat)
            n += 1
    context.window_manager.b4d_material = mat.name
    return n


class BLENDA4D_OT_new_default_material(bpy.types.Operator):
    bl_idname = "blenda4d.new_default_material"
    bl_label = "New Default Material"
    bl_description = "Make a new material and give it to the selected objects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and any(hasattr(ob.data, "materials") for ob in context.selected_objects)

    def execute(self, context):
        mat = bpy.data.materials.new("Mat")
        mat.use_nodes = True
        _give(context, mat)
        _redraw(context)
        return {"FINISHED"}


class BLENDA4D_OT_give_material(bpy.types.Operator):
    bl_idname = "blenda4d.give_material"
    bl_label = "Give Material"
    bl_description = "Give this material to the selected objects"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        mat = bpy.data.materials.get(self.name)
        if mat is None or not _give(context, mat):
            return {"CANCELLED"}
        _redraw(context)
        return {"FINISHED"}


class BLENDA4D_MT_om_materials(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_om_materials"
    bl_label = "Material"
    bl_description = "Give one of this scene's materials to the selected objects"

    def draw(self, context):
        mats = sorted((m for m in bpy.data.materials if not m.is_grease_pencil and not m.name.startswith(".")), key=lambda m: m.name.lower())
        for m in mats:
            self.layout.operator("blenda4d.give_material", text=m.name, icon_value=self.layout.icon(m)).name = m.name
        if not mats:
            self.layout.label(text="No materials yet")


# --- information ------------------------------------------------------------------------------------------------------------------
def _counts(obs, context):
    dg = context.evaluated_depsgraph_get()
    pts = polys = 0
    for ob in obs:
        if ob.type == "MESH":
            me = ob.evaluated_get(dg).data
            pts, polys = pts + len(me.vertices), polys + len(me.polygons)
    return pts, polys


class BLENDA4D_OT_object_info(bpy.types.Operator):
    bl_idname = "blenda4d.object_info"
    bl_label = "Object Information"
    bl_description = "How many points, polygons, objects and tags the selected objects have"
    scene: bpy.props.BoolProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        return "How many objects, points, polygons, materials and lights the scene has" if props.scene else cls.bl_description

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        lay = self.layout
        if self.scene:
            obs = list(context.scene.objects)
            pts, polys = _counts(obs, context)
            lay.label(text="Scene Information", icon="SCENE_DATA")
            rows = (("Objects", len(obs)), ("Polygon objects", sum(o.type == "MESH" for o in obs)), ("Points", pts), ("Polygons", polys),
                    ("Lights", sum(o.type == "LIGHT" for o in obs)), ("Cameras", sum(o.type == "CAMERA" for o in obs)),
                    ("Materials", len(bpy.data.materials)), ("Frames", context.scene.frame_end - context.scene.frame_start + 1))
        else:
            obs = list(context.selected_objects)
            pts, polys = _counts(obs, context)
            lay.label(text="Object Information" if len(obs) == 1 else f"{len(obs)} Objects", icon="INFO")
            kids = sum(len(o.children_recursive) for o in obs)
            ntags = sum(len(managers._tags(o)) for o in obs)
            rows = (("Points (as shown)", pts), ("Polygons (as shown)", polys), ("Objects under them", kids), ("Tags", ntags),
                    ("Materials", sum(len([s for s in getattr(o, "material_slots", ()) if s.material]) for o in obs)))
        for k, v in rows:
            r = lay.split(factor=0.6)
            r.label(text=k)
            r.label(text=f"{v:,}")

    def execute(self, context):
        return {"FINISHED"}


# --- the menu ------------------------------------------------------------------------------------------------------------------------
class BLENDA4D_MT_om_context(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_om_context"
    bl_label = "Object"
    bl_description = "Commands for the selected objects"

    def draw(self, context):
        lay = self.layout
        lay.operator_context = "INVOKE_DEFAULT"
        for m in TAG_MENUS:
            lay.menu(m.bl_idname)
        lay.menu(BLENDA4D_MT_om_tags_remove.bl_idname, icon=icon("X"))
        lay.separator()
        lay.operator("blenda4d.select_children", icon=icon("OUTLINER"))
        lay.separator()
        lay.operator("blenda4d.make_editable", icon=icon("GREASEPENCIL"))
        lay.operator("blenda4d.current_state", icon=icon("FREEZE"))
        lay.separator()
        lay.operator("blenda4d.group", icon=icon("ADD"))
        lay.operator("blenda4d.ungroup", icon=icon("X"))
        lay.operator("blenda4d.delete_without_children", icon=icon("TRASH"))
        lay.separator()
        lay.operator("blenda4d.show_tracks", text="Show Tracks", icon=icon("ACTION")).curves = False
        lay.operator("blenda4d.show_tracks", text="Show F-Curves", icon=icon("FCURVE")).curves = True
        lay.separator()
        lay.operator("blenda4d.new_default_material", icon=icon("ADD"))
        lay.menu(BLENDA4D_MT_om_materials.bl_idname)
        lay.separator()
        lay.operator("blenda4d.object_info", text="Object Information", icon=icon("INFO")).scene = False
        lay.operator("blenda4d.object_info", text="Scene Information", icon=icon("SCENE_DATA")).scene = True


class BLENDA4D_OT_om_context(bpy.types.Operator):
    bl_idname = "blenda4d.om_context"
    bl_label = "Object Manager Menu"
    bl_description = "The commands for the object under the pointer and the other selected objects"

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == "OBJECTS"

    def invoke(self, context, event):
        ob = managers.object_at(context, event)
        if ob is None:
            return {"PASS_THROUGH"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if not ob.select_get():                             # a right click on an unselected object picks it alone
            for o in context.view_layer.objects:
                o.select_set(False)
            ob.select_set(True)
        context.view_layer.objects.active = ob
        _redraw(context)
        bpy.ops.wm.call_menu(name=BLENDA4D_MT_om_context.bl_idname)
        return {"FINISHED"}


def _viewport_menu(self, context):
    if context.mode == "OBJECT":
        lay = self.layout
        lay.separator()
        lay.operator("blenda4d.make_editable", icon=icon("GREASEPENCIL"))
        lay.operator("blenda4d.current_state", icon=icon("FREEZE"))


def _redraw(context):
    for a in context.screen.areas:
        a.tag_redraw()


classes = (BLENDA4D_OT_om_tag, *TAG_MENUS, BLENDA4D_MT_om_tags_remove, BLENDA4D_OT_select_children, BLENDA4D_OT_ungroup,
           BLENDA4D_OT_delete_without_children, BLENDA4D_OT_show_tracks, BLENDA4D_OT_new_default_material, BLENDA4D_OT_give_material,
           BLENDA4D_MT_om_materials, BLENDA4D_OT_object_info, BLENDA4D_MT_om_context, BLENDA4D_OT_om_context)
_keymaps = []


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_object_context_menu.prepend(_viewport_menu)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        km = kc.keymaps.new(name="Property Editor", space_type="PROPERTIES")
        _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_om_context.bl_idname, "RIGHTMOUSE", "PRESS")))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    bpy.types.VIEW3D_MT_object_context_menu.remove(_viewport_menu)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
