# SPDX-License-Identifier: GPL-3.0-or-later
"""Pages for the tags the Object Manager's right-click menu puts on (om_menu.TAGS).

A click on a tag's icon in an object's row shows that tag's settings in the Attribute Manager. Align to Spline is
Blender's Follow Path constraint set up so the object rides the spline itself: a spline dropped from the Object
Manager onto its page becomes its path, and the Position slider moves the object from the spline's start (0) to its
end (1); keying Position animates the ride. A Limit Location held at zero, just before the Follow Path, keeps the
object's own position out of it, so the object sits on the spline rather than beside it."""
import bpy

from . import managers, om_menu

SUBJECT = "OTAG"                      # wm.b4d_am_subject = "OTAG:<object>:<tag key>" while a tag's page is shown
HOLD = "b4d spline hold"


# --- Align to Spline -----------------------------------------------------------------------------------------------
def setup_align(con):
    """A new Align to Spline: placed by Position, the object's Z axis along the spline when Tangential is on."""
    con.use_fixed_location = True
    con.offset_factor = 0.0
    con.forward_axis = "FORWARD_Z"
    con.up_axis = "UP_Y"
    keep_hold(con.id_data)


def keep_hold(ob):
    """Add, place, mute or take away the zero hold so it matches the object's Align to Spline tags."""
    paths = [c for c in ob.constraints if c.type == "FOLLOW_PATH"]
    hold = ob.constraints.get(HOLD)
    if not paths:
        if hold is not None:
            ob.constraints.remove(hold)
        return
    if hold is None:
        hold = ob.constraints.new("LIMIT_LOCATION")
        hold.name = HOLD
        for a in "xyz":
            setattr(hold, f"use_min_{a}", True)
            setattr(hold, f"use_max_{a}", True)
        hold.owner_space = "WORLD"
    order = list(ob.constraints)
    i, j = order.index(hold), order.index(paths[0])
    if i > j:
        ob.constraints.move(i, j)
    rest = all(c.mute or c.target is None for c in paths)
    if hold.mute != rest:
        hold.mute = rest


@bpy.app.handlers.persistent
def _watch(scene, depsgraph):
    try:
        for u in depsgraph.updates:
            ob = u.id.original if isinstance(u.id, bpy.types.Object) else None
            if ob is not None and (ob.constraints.get(HOLD) is not None or any(c.type == "FOLLOW_PATH" for c in ob.constraints)):
                keep_hold(ob)
    except (ReferenceError, AttributeError, RuntimeError):
        pass


def _align_page(col, ob, con):
    col.prop(con, "target", text="Spline Path")
    col.prop(con, "use_curve_follow", text="Tangential")
    row = col.row()
    row.enabled = con.use_fixed_location
    row.prop(con, "offset_factor", text="Position", slider=True)
    row = col.row()
    row.enabled = con.use_curve_follow
    row.prop(con, "forward_axis", text="Axis")
    row = col.row()
    row.enabled = con.use_curve_follow
    row.prop(con, "up_axis", text="Up Axis")
    if con.target is None:
        col.label(text="Drag a spline from the Object Manager onto this page", icon="INFO")


# --- the other tags --------------------------------------------------------------------------------------------------
def _target_page(col, ob, con):
    col.prop(con, "target", text="Target Object")
    col.prop(con, "track_axis", text="Axis")
    col.prop(con, "influence", text="Strength", slider=True)


def _camera_page(col, ob, con):
    col.prop(con, "target", text="Camera")
    col.prop(con, "track_axis", text="Axis")
    col.prop(con, "up_axis", text="Up Axis")


def _protection_page(col, ob):
    for label, attr in (("P", "lock_location"), ("S", "lock_scale"), ("R", "lock_rotation")):
        row = col.row(align=True)
        row.label(text=label)
        for i, a in enumerate("XYZ"):
            row.prop(ob, attr, index=i, text=a, toggle=True)


def _rigid_page(col, ob):
    rb = ob.rigid_body
    if rb is None:
        return
    col.prop(rb, "enabled", text="Dynamic")
    col.prop(rb, "mass", text="Mass")
    col.prop(rb, "friction", text="Friction", slider=True)
    col.prop(rb, "restitution", text="Bounce", slider=True)
    col.prop(rb, "collision_shape", text="Shape")


def _cloth_page(col, ob):
    m = next((m for m in ob.modifiers if m.type == "CLOTH"), None)
    if m is None:
        return
    s = m.settings
    col.prop(s, "quality", text="Steps")
    col.prop(s, "mass", text="Mass")
    col.prop(s, "tension_stiffness", text="Stiffness")
    col.prop(s, "air_damping", text="Air Drag")
    col.prop(m.collision_settings, "use_self_collision", text="Self Collision")


def _collider_page(col, ob):
    c = ob.collision
    if c is None:
        return
    col.prop(c, "thickness_outer", text="Thickness")
    col.prop(c, "cloth_friction", text="Friction")
    col.prop(c, "damping", text="Damping", slider=True)


def _sculpt_page(col, ob):
    m = next((m for m in ob.modifiers if m.type == "MULTIRES"), None)
    if m is None:
        return
    frozen = frozen_levels(ob) is not None
    col.prop(ob, "b4d_sculpt_freeze", text="Freeze")
    body = col.column()
    body.enabled = not frozen
    body.prop(m, "sculpt_levels", text="Level")
    body.prop(m, "levels", text="Level in Editor")
    body.prop(m, "render_levels", text="Level in Renderer")
    row = body.row(align=True)
    row.operator("blenda4d.sculpt_level", text="Subdivide", icon="MOD_MULTIRES").what = "SUBDIVIDE"
    row.operator("blenda4d.sculpt_level", text="Decrease", icon="REMOVE").what = "DOWN"
    row.operator("blenda4d.sculpt_level", text="Increase", icon="ADD").what = "UP"
    row = body.row(align=True)
    o = row.operator("object.multires_higher_levels_delete", text="Delete Higher Levels")
    o.modifier = m.name
    o = row.operator("object.multires_base_apply", text="Apply to Base")
    o.modifier = m.name
    if frozen:
        col.label(text="Frozen: shown at the lowest level, sculpting paused", icon="FREEZE")


# --- Freeze: a heavy sculpt shown at its lowest level while you work on the rest of the scene ------------------------
def frozen_levels(ob):
    v = ob.get("_b4d_freeze")
    return int(v) if v is not None else None


def _freeze_get(self):
    return frozen_levels(self) is not None


def _freeze_set(self, on):
    m = next((m for m in self.modifiers if m.type == "MULTIRES"), None)
    if m is None:
        return
    if on and frozen_levels(self) is None:
        self["_b4d_freeze"] = m.levels                     # remember the editor level, then show the base
        m.levels = 0
        if self.mode == "SCULPT" and bpy.context.view_layer.objects.active == self:
            bpy.ops.object.mode_set(mode="OBJECT")         # sculpting paused while frozen
    elif not on and frozen_levels(self) is not None:
        m.levels = min(frozen_levels(self), m.total_levels)
        del self["_b4d_freeze"]


def draw_subject(layout, context, ob):
    """The tag's page; False when the subject is gone (the object's own page shows instead)."""
    s = context.window_manager.b4d_am_subject
    if not s.startswith(SUBJECT + ":"):
        return False
    name, _sep, key = s[len(SUBJECT) + 1:].rpartition(":")
    tob = bpy.data.objects.get(name)
    if tob is None or tob != ob or key not in om_menu.TAGS or not om_menu.has(tob, key):
        return False
    t = om_menu.TAGS[key]
    layout.label(text=f"{t[1]} Tag [{tob.name}]", icon=om_menu.icon(t[2]))
    layout.label(text="Tag Properties")
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = True
    if key in om_menu.CON:
        con = om_menu._con(tob, key)
        {"ALIGN_SPLINE": _align_page, "TARGET": _target_page, "LOOK_CAMERA": _camera_page}[key](col, tob, con)
    else:
        {"SCULPT": _sculpt_page, "PROTECTION": _protection_page, "RIGID": _rigid_page, "COLLIDER": _rigid_page, "CLOTH": _cloth_page,
         "COLLISION": _collider_page}.get(key, lambda c, o: None)(col, tob)
    return True


# --- the tag's button in the Object Manager, and dropping a spline onto its page --------------------------------------
def picked(context, ob, key):
    return context.window_manager.b4d_am_subject == f"{SUBJECT}:{ob.name}:{key}"


def om_tag_button(layout, ob, key, icon):
    on = picked(bpy.context, ob, key)
    op = layout.operator("blenda4d.om_tag_pick", text="", icon=icon, emboss=on, depress=on)
    op.name, op.key = ob.name, key


class BLENDA4D_OT_om_tag_pick(bpy.types.Operator):
    bl_idname = "blenda4d.om_tag_pick"
    bl_label = "Tag"
    bl_description = "Show this tag's settings in the Attribute Manager"
    bl_options = {"UNDO"}
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})
    key: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None or self.key not in om_menu.TAGS:
            return {"CANCELLED"}
        if context.mode != "OBJECT" and context.view_layer.objects.active != ob:
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in context.view_layer.objects.selected:
            if o != ob:
                o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        context.window_manager.b4d_am_subject = f"{SUBJECT}:{ob.name}:{self.key}"
        for a in context.screen.areas if context.screen else ():
            a.tag_redraw()
        return {"FINISHED"}


def drop(context, objs, event):
    """Objects dragged out of the Object Manager and let go over a tag page with an object field: the first one that
    fits fills it (a spline for Align to Spline, any object for Target). True when the drop was taken."""
    s = context.window_manager.b4d_am_subject
    if not s.startswith(SUBJECT + ":"):
        return False
    from . import roles
    over = next((a for a in context.window.screen.areas if roles.role(a) == "ATTRIBUTES"
                 and a.x <= event.mouse_x < a.x + a.width and a.y <= event.mouse_y < a.y + a.height), None)
    if over is None:
        return False
    name, _sep, key = s[len(SUBJECT) + 1:].rpartition(":")
    ob = bpy.data.objects.get(name)
    if ob is None or key not in {"ALIGN_SPLINE", "TARGET"}:
        return False
    con = om_menu._con(ob, key)
    if con is None:
        return False
    for o in objs:
        if o == ob or (key == "ALIGN_SPLINE" and o.type != "CURVE"):
            continue
        con.target = o
        if key == "ALIGN_SPLINE":
            keep_hold(ob)
            o.update_tag(refresh={"OBJECT", "DATA"})     # the spline becomes a path only when Blender looks at it again
        ob.update_tag(refresh={"OBJECT"})
        context.view_layer.update()
        over.tag_redraw()
        return True
    return False


classes = (BLENDA4D_OT_om_tag_pick,)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.b4d_sculpt_freeze = bpy.props.BoolProperty(
        name="Freeze", get=_freeze_get, set=_freeze_set,
        description="Show this sculpt at its lowest level and pause sculpting on it, so the rest of the scene stays "
                    "quick; renders keep the full detail")
    managers.AM_SUBJECTS[SUBJECT] = draw_subject
    managers.OM_TAG_PICK[:] = [om_tag_button]
    managers.OM_DROP[:] = [drop]
    if _watch not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_watch)


def unregister():
    if _watch in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_watch)
    managers.OM_DROP.clear()
    managers.OM_TAG_PICK.clear()
    managers.AM_SUBJECTS.pop(SUBJECT, None)
    if hasattr(bpy.types.Object, "b4d_sculpt_freeze"):
        del bpy.types.Object.b4d_sculpt_freeze
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
