# SPDX-License-Identifier: GPL-3.0-or-later
"""Make Editable (C) for generators, and Current State to Object.

Make Editable on a generator: what it makes becomes plain polygons in its place. A Subdivision Surface, Reduce
Polygons or Remesh with one object under it becomes that object, smoothed (or reduced, or remeshed), under the
generator's name; with several objects it becomes a Null over them. A node generator (Extrude, Lathe, Sweep, Loft,
Symmetry, Array, Instance, Connect, Boolean, Metaball) becomes its result; what it was made from goes. A result that is
a spline (Connect or Symmetry of splines) becomes a spline object.

What was inside goes into the result: generators and deformers under it. What acts from outside (a Subdivision Surface
above it, a deformer beside it) stays live, so the object looks the same before and after.

Current State to Object: a polygon copy of the selected object as it shows now, deformers and generators included; the
original stays as it was. The copy is placed where nothing changes it again, and has no animation."""
import bpy
import numpy as np
from mathutils import Matrix

from . import deformers, generators, primitives

LEAVES = {"MESH", "CURVE", "FONT", "SURFACE", "META", "CURVES", "POINTCLOUD"}


# --- what is inside ------------------------------------------------------------------------------------------------
def _inside(ob, scope):
    """Is ob scope itself or under it?"""
    while ob is not None:
        if ob == scope:
            return True
        ob = ob.parent
    return False


def _mod_owner(ob, m):
    """The object a modifier comes from: a deformer, a generator above, or ob itself."""
    d = deformers._owner(m)
    if d:
        return d
    if m.name in (generators.SUB_MOD, generators.SUB_PRE):
        return generators.generator_of(ob, "subdivision")
    if m.name == generators.RED_MOD:
        return generators.generator_of(ob, "reduce")
    if m.name in (generators.RM_MOD, generators.RM_SMOOTH):
        return generators.generator_of(ob, "remesh")
    return ob


def _outside(ob, scope):
    """ob's modifiers that act from outside scope: switched off while the result is taken."""
    return [m for m in ob.modifiers if m.show_viewport and not _inside(_mod_owner(ob, m), scope)]


def _result_mesh(ob, context, name):
    """A new mesh of what ob shows now (its switched-on modifiers applied), or None when it shows no polygons."""
    dg = context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    try:
        me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    except RuntimeError:
        return None
    if not len(me.vertices):
        bpy.data.meshes.remove(me)
        return None
    me.name = name
    for i in reversed(range(len(me.materials))):
        if me.materials[i] is None and len(me.materials) > 1:
            me.materials.pop(index=i)
    return me


def _result_curve(ob, context, name):
    """A generator whose result is splines: a spline object's data from the evaluated curves."""
    dg = context.evaluated_depsgraph_get()
    try:
        geo = ob.evaluated_get(dg).evaluated_geometry()
    except (AttributeError, RuntimeError):
        return None
    cv = getattr(geo, "curves", None)
    if cv is None or not len(cv.points):
        return None

    def attr(n, size, default):
        a = cv.attributes.get(n)
        if a is None:
            return None
        out = np.empty(len(a.data) * size, dtype=np.float64 if size > 1 or a.data_type == "FLOAT" else np.int64)
        a.data.foreach_get("vector" if size == 3 else "value", out)
        return out.reshape(-1, size) if size > 1 else out
    pos = np.empty(len(cv.points) * 3)
    cv.position_data.foreach_get("vector", pos)
    pos = pos.reshape(-1, 3)
    offs = np.empty(len(cv.curves) + 1, dtype=np.int64)
    cv.curve_offset_data.foreach_get("value", offs)
    cyclic, kind = attr("cyclic", 1, 0), attr("curve_type", 1, 1)
    hl, hr = attr("handle_left", 3, None), attr("handle_right", 3, None)
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    for i in range(len(cv.curves)):
        a, b = int(offs[i]), int(offs[i + 1])
        bez = kind is not None and int(kind[i]) == 2 and hl is not None and hr is not None
        sp = cu.splines.new("BEZIER" if bez else "POLY")
        if bez:
            sp.bezier_points.add(b - a - 1)
            for j, bp in enumerate(sp.bezier_points):
                bp.co, bp.handle_left, bp.handle_right = pos[a + j], hl[a + j], hr[a + j]
        else:
            sp.points.add(b - a - 1)
            for j, p in enumerate(sp.points):
                p.co = (*pos[a + j], 1.0)
        sp.use_cyclic_u = bool(cyclic[i]) if cyclic is not None else False
    return cu


def _leaves(ob):
    """What ob is made of as it shows: [(object, data owner for its result)] top down; deformers left out."""
    out = []
    if deformers.is_deformer(ob):
        return out
    k = generators.kind(ob)
    if k in generators.NODE_KINDS:
        return [ob]                                       # its children are what it is made from
    if ob.type in LEAVES:
        out.append(ob)
    for c in ob.children:
        out += _leaves(c)
    return out


# --- one result object ------------------------------------------------------------------------------------------------
def _plain(ob):
    """Nothing procedural is left on it: Blenda's kind and its own bookkeeping go."""
    for key in ("b4d_type", "b4d_kids", "b4d_consumed"):
        if key in ob:
            del ob[key]
    if ob.type == "MESH":
        for m in list(ob.modifiers):
            if m.name == generators.GEN_MOD or m in list(primitives._own_mods(ob)):
                ob.modifiers.remove(m)


def _bake(ob, context, scope, name):
    """ob's result as new data (mesh or curve), with what comes from outside scope left out, or None."""
    off = _outside(ob, scope) if scope is not None else []
    _quiet()                                               # or the update below would switch them on again
    for m in off:
        m.show_viewport = False
    try:
        context.view_layer.update()
        data = _result_mesh(ob, context, name) if ob.type in {"MESH", "META", "SURFACE", "CURVES", "POINTCLOUD"} else None
        if data is None and ob.type == "MESH":
            data = _result_curve(ob, context, name)
        if ob.type in {"CURVE", "FONT"}:
            data = _spline_or_mesh(ob, context, name)
    finally:
        for m in off:
            m.show_viewport = True
        _loud()
    return data


def _spline_or_mesh(ob, context, name):
    """A spline stays a spline: its modifiers (a deformer, a bevel) are applied by Blender's own conversion."""
    dg = context.evaluated_depsgraph_get()
    try:
        cu = ob.evaluated_get(dg).to_curve(dg, apply_modifiers=True).copy()
        ob.evaluated_get(dg).to_curve_clear()
        cu.name = name
        return cu
    except (RuntimeError, AttributeError):
        return None


def _new_object(src, data, name, parent, matrix):
    """A plain object for data, with src's object settings (material tags, color) but no animation."""
    new = src.copy() if src.type in {"MESH", "CURVE", "FONT"} and (data is None or type(data) is type(src.data)) else bpy.data.objects.new(name, data)
    if new.data is not data and data is not None:
        new.data = data
    new.animation_data_clear()
    new.name = name
    new.modifiers.clear() if new.type == "MESH" else None
    _plain(new)
    for coll in src.users_collection:
        coll.objects.link(new)
    new.parent = parent
    new.matrix_parent_inverse = Matrix.Identity(4)
    new.matrix_world = matrix
    return new


def _keep_outside(ob):
    """The modifiers that came from outside stay; sync() adds them again by the hierarchy anyway."""
    return [m for m in ob.modifiers if not _inside(_mod_owner(ob, m), ob)]


def _quiet():
    generators._busy[0] = True
    deformers._busy[0] = True


def _loud():
    generators._busy[0] = False
    deformers._busy[0] = False


def _remove_tree(ob, keep=()):
    for c in list(ob.children):
        if c in keep:
            continue
        _remove_tree(c, keep)
    if ob not in keep:
        bpy.data.objects.remove(ob)


# --- Make Editable on a generator ---------------------------------------------------------------------------------------------
def is_generator(ob):
    return generators.kind(ob) is not None


def make_editable(context, gen):
    """The generator becomes its result in its place. True when it did."""
    k = generators.kind(gen)
    if k is None:
        return False
    if k in generators.NODE_KINDS:
        data = _bake(gen, context, gen, gen.name)
        if data is None:
            return False
        keep = [c for c in gen.children if c.type in {"CAMERA", "LIGHT"}]
        mw = gen.matrix_world.copy()
        _quiet()
        try:
            if type(data) is bpy.types.Mesh:
                old = gen.data
                gen.data = data
                for m in list(gen.modifiers):
                    if _inside(_mod_owner(gen, m), gen):
                        gen.modifiers.remove(m)
                _plain(gen)
                if old is not None and old.users == 0:
                    bpy.data.meshes.remove(old)
                result = gen
            else:
                result = _new_object(gen, data, gen.name, gen.parent, mw)
                gen.name = gen.name + " (old)"
                result.name = result.name.replace(" (old)", "")
            for c in list(gen.children):
                if c in keep:
                    m = c.matrix_world.copy()
                    c.parent = result
                    c.matrix_parent_inverse = Matrix.Identity(4)
                    c.matrix_world = m
                elif c != result:
                    _remove_tree(c)
            if result is not gen:
                name = gen.name.replace(" (old)", "")
                bpy.data.objects.remove(gen)
                result.name = name
                gen = result
        finally:
            _loud()
        _select(context, [gen])
        return True
    # Subdivision Surface, Reduce Polygons, Remesh: each object under it takes the result, the generator goes
    leaves = [o for o in _leaves(gen) if o != gen]
    baked = [(o, _bake(o, context, gen, o.name)) for o in leaves]
    _quiet()
    try:
        tops = []
        for o, data in baked:
            if data is None:
                continue
            if type(data) is bpy.types.Mesh and o.type == "MESH":
                old = o.data
                o.data = data
                for m in list(o.modifiers):
                    if _inside(_mod_owner(o, m), gen):
                        o.modifiers.remove(m)
                _plain(o)
                if old is not None and old.users == 0:
                    bpy.data.meshes.remove(old)
            elif type(data) is bpy.types.Curve and o.type in {"CURVE", "FONT"}:
                o.data = data if o.type == "CURVE" else o.data
            if generators.kind(o) in generators.NODE_KINDS:   # a generator inside: what it was made from goes too
                for c in list(o.children):
                    if c.type not in {"CAMERA", "LIGHT"}:
                        _remove_tree(c)
                _plain(o)
        for o in [o for o in gen.children_recursive if generators.kind(o) in generators.MOD_KINDS]:
            _plain(o)                                       # an inner Subdivision Surface is a Null now: its work is done
            o.empty_display_type, o.empty_display_size = "PLAIN_AXES", 1.0
        for c in list(gen.children):
            if deformers.is_deformer(c):                    # its effect is in the result now
                _remove_tree(c)
        for o in list(gen.children):
            for d in [x for x in o.children_recursive if deformers.is_deformer(x) and all(_inside(t, gen) for t in deformers.targets(x))]:
                if d.name in bpy.data.objects:
                    _remove_tree(d)
        kids = list(gen.children)
        while len(kids) == 1 and kids[0].type == "EMPTY" and "b4d_type" not in kids[0] and kids[0].animation_data is None \
                and len(kids[0].children) == 1:             # an inner generator's Null with one object under it: that object
            inner = kids[0]
            child = inner.children[0]
            m = child.matrix_world.copy()
            child.parent = gen
            child.matrix_parent_inverse = Matrix.Identity(4)
            child.matrix_world = m
            bpy.data.objects.remove(inner)
            kids = list(gen.children)
        if len(kids) == 1 and gen.animation_data is None:
            top = kids[0]
            mw = top.matrix_world.copy()
            top.parent = gen.parent
            top.matrix_parent_inverse = Matrix.Identity(4)
            top.matrix_world = mw
            name = gen.name
            bpy.data.objects.remove(gen)
            top.name = name
            tops = [top]
        else:                                               # a Null over them, in the generator's place
            _plain(gen)
            gen.empty_display_type = "PLAIN_AXES"
            gen.empty_display_size = 1.0
            tops = [gen]
    finally:
        _loud()
    _select(context, tops)
    return True


# --- Current State to Object ---------------------------------------------------------------------------------------------------
def _clean_parent(ob):
    """The nearest place above ob where nothing would change a copy again (no generator, no deformer at work)."""
    chain = []
    p = ob.parent
    while p is not None:
        chain.append(p)
        p = p.parent
    place = None
    for a in reversed(chain):                               # from the top down, while it stays clean
        if generators.kind(a) is not None or any(deformers.is_deformer(c) for c in a.children):
            break
        place = a
    return place


def _copy_tree(ob, context, parent, matrix_of):
    """Copies of what ob shows, under parent; returns the top copy or None."""
    if deformers.is_deformer(ob) or ob.type in {"CAMERA", "LIGHT", "SPEAKER", "LIGHT_PROBE"}:
        return None
    k = generators.kind(ob)
    if ob.type in LEAVES or k in generators.NODE_KINDS:
        data = _bake(ob, context, None, ob.name)
        if data is None:
            return None
        new = _new_object(ob, data, ob.name, parent, matrix_of(ob))
        if k not in generators.NODE_KINDS:
            for c in ob.children:
                _copy_tree(c, context, new, matrix_of)
        return new
    kids = [c for c in ob.children if not deformers.is_deformer(c)]
    if k in generators.MOD_KINDS and len(kids) == 1:       # one object under it: that one, under the generator's name
        new = _copy_tree(kids[0], context, parent, matrix_of)
        if new is not None:
            new.name = ob.name
        return new
    null = bpy.data.objects.new(ob.name, None)
    for coll in ob.users_collection:
        coll.objects.link(null)
    null.parent = parent
    null.matrix_world = matrix_of(ob)
    made = [c for c in (_copy_tree(c, context, null, matrix_of) for c in kids) if c is not None]
    if not made:
        bpy.data.objects.remove(null)
        return None
    return null


def current_state(context, obs):
    """Copies of the objects as they show now; the originals stay. Returns the new top objects."""
    mats = {}

    def matrix_of(o):
        return mats.setdefault(o.name, o.matrix_world.copy())
    out = []
    _quiet()
    try:
        for ob in obs:
            new = _copy_tree(ob, context, _clean_parent(ob), matrix_of)
            if new is not None:
                out.append(new)
    finally:
        _loud()
    _select(context, out)
    return out


def _select(context, obs):
    for o in list(bpy.context.view_layer.objects):
        if o is not None:
            o.select_set(False)
    for o in obs:
        try:
            o.select_set(True)
        except RuntimeError:
            pass
    if obs:
        bpy.context.view_layer.objects.active = obs[0]
    generators.sync_all()
    for a in context.screen.areas:
        a.tag_redraw()


def tops(objs):
    """The selected objects that are not under another selected one."""
    s = set(objs)
    out = []
    for o in objs:
        p = o.parent
        while p is not None and p not in s:
            p = p.parent
        if p is None:
            out.append(o)
    return out


class BLENDA4D_OT_current_state(bpy.types.Operator):
    bl_idname = "blenda4d.current_state"
    bl_label = "Current State to Object"
    bl_description = ("A polygon copy of the selected objects as they show now, with their generators and deformers "
                      "applied. The originals stay as they are")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(context.selected_objects)

    def execute(self, context):
        new = current_state(context, tops(list(context.selected_objects)))
        if not new:
            self.report({"INFO"}, "Nothing to copy: select a polygon object, a spline or a generator")
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (BLENDA4D_OT_current_state,)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
