# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone dynamics: a Rigid Body (or Collider Body) tag on a Cloner makes every clone a body in Blender's own
rigid-body simulation, so clones fall with gravity, hit each other and Collider Body objects, and are pushed by
Blender's force fields (Wind, Turbulence, Force...).

Blender simulates objects, not clones, so each clone gets a body object of its own: hidden from the Object Manager
and not selectable, kept in the collection "Blenda Clone Bodies". At the simulation's start frame the bodies sit
exactly where the clones are (after the effectors); a change to the Cloner, its children or its effectors there puts
them back. While the tag is on, the Cloner shows the bodies instead of its own clones."""
import bpy
from mathutils import Matrix

COLL = "Blenda Clone Bodies"
SHAPES = [("CONVEX_HULL", "Convex Hull", "A tight wrap around each clone: fast and good for most shapes"),
          ("BOX", "Box", "Each clone collides as a box"), ("SPHERE", "Sphere", "Each clone collides as a ball"),
          ("MESH", "Mesh", "Each clone collides with its exact surface: slow, for hollow shapes")]
_busy = [False]
_selected = {}                       # Cloner name: per clone, is it in the MoClone Selection (unselected clones hold still)


def on(gen):
    return gen.get("b4d_dyn") in ("ACTIVE", "PASSIVE")


def bodies(gen):
    return sorted((o for o in bpy.data.objects if o.get("b4d_body_of") == gen.name), key=lambda o: o["b4d_body_i"])


def _collection(scene):
    c = bpy.data.collections.get(COLL)
    if c is None:
        c = bpy.data.collections.new(COLL)
    if c.name not in scene.collection.children:
        scene.collection.children.link(c)
    return c


def _world(scene):
    if scene.rigidbody_world is None:
        with bpy.context.temp_override(scene=scene):
            bpy.ops.rigidbody.world_add()
    w = scene.rigidbody_world
    if w.collection is None:
        w.collection = bpy.data.collections.new("RigidBodyWorld")
    return w


def _simulated(gen, value):
    """The Cloner hides its own clones while its bodies stand in for them (the generator's Simulated input)."""
    from . import generators as g
    from .primitives import set_input
    mod = g.gen_mod(gen)
    if mod is None or mod.node_group is None or "Simulated" not in mod.node_group.interface.items_tree:
        return
    set_input(mod, mod.node_group.interface.items_tree["Simulated"].identifier, bool(value))
    gen.update_tag()


def _clones(gen):
    """[(child, matrix in world, colour)] for each clone as it is now."""
    from . import generators as g
    _simulated(gen, False)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    out = []
    gen_sel = _selected.setdefault(gen.name, [])
    gen_sel.clear()
    geo = gen.evaluated_get(dg).evaluated_geometry()
    pc = geo.instances_pointcloud() if geo is not None else None
    kids = g.kids_of(gen)
    if pc is not None and kids:
        tf, ref, col = pc.attributes.get("instance_transform"), pc.attributes.get(".reference_index"), pc.attributes.get("b4d_color")
        sel = pc.attributes.get("b4d_sel")
        reset = bool(g.gval(gen, "Reset Coordinates"))
        for i in range(len(pc.points)):
            child = kids[min(max(ref.data[i].value if ref else 0, 0), len(kids) - 1)]
            m = Matrix([list(r) for r in tf.data[i].value]) if tf is not None else Matrix.Identity(4)
            rel = gen.matrix_world.inverted() @ child.matrix_world
            if reset:
                rel = Matrix.LocRotScale(None, rel.to_quaternion(), rel.to_scale())
            out.append((child, gen.matrix_world @ m @ rel, tuple(col.data[i].color) if col is not None else (1, 1, 1, 1)))
            gen_sel.append(sel.data[i].value > 0.5 if sel is not None else True)
    _simulated(gen, on(gen))
    return out


def _shape_mesh(child, cache):
    m = cache.get(child.name)
    if m is None:
        dg = bpy.context.evaluated_depsgraph_get()
        m = bpy.data.meshes.new_from_object(child.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        m.name = f"{child.name} (clone body)"
        for sl in child.material_slots:
            if sl.material is not None and sl.material.name not in m.materials:
                m.materials.append(sl.material)
        if not m.materials:
            from .moclone_nodes import clone_color_material
            m.materials.append(clone_color_material())
        cache[child.name] = m
    return m


START = [("IMMEDIATELY", "Immediately", "Every clone moves from the first frame: press play and gravity takes them"),
         ("COLLISION", "On Collision", "Clones rest in place until something hits them"),
         ("FIELD", "When a Field Reaches It", "A clone holds its place until a field in the list below first reaches it, then falls"),
         ("LOOSEN", "As a Field Loosens It", "A clone hangs in place on a spring (Follow Position); as a field's strength there "
                                              "rises the spring weakens and the clone sags, and near 100 % it falls")]
ANCHOR = "Blenda Clone Anchor"
RELEASE = 0.98                       # As a Field Loosens It: the spring lets go at this field strength


def _fcurves(ob):
    ad = ob.animation_data
    act = ad.action if ad else None
    if act is None:
        return []
    try:
        from bpy_extras import anim_utils
        bag = anim_utils.action_get_channelbag_for_slot(act, ad.action_slot)
        return list(bag.fcurves) if bag else []
    except Exception:
        return list(getattr(act, "fcurves", []))


def matrix_at(ob, frame):
    """ob's world matrix at a frame, from its keyframes (location, rotation, scale) and its parent's, without moving
    the scene to that frame (that would step the simulation)."""
    from mathutils import Euler, Vector
    fcs = {(f.data_path, f.array_index): f for f in _fcurves(ob)}
    if not fcs:
        local = ob.matrix_basis.copy()
    else:
        def ch(path, i, now):
            f = fcs.get((path, i))
            return f.evaluate(frame) if f else now
        loc = Vector([ch("location", i, ob.location[i]) for i in range(3)])
        rot = Euler([ch("rotation_euler", i, ob.rotation_euler[i]) for i in range(3)], ob.rotation_euler.order)
        sc = Vector([ch("scale", i, ob.scale[i]) for i in range(3)])
        local = Matrix.LocRotScale(loc, rot, sc)
    if ob.parent is not None:
        return matrix_at(ob.parent, frame) @ ob.matrix_parent_inverse @ local
    return local


def field_value(f, mw, point):
    """A field's strength at a world point (the same shapes as the clones' fields in moclone_fx.py)."""
    import math
    p = mw.inverted() @ point
    x, y, z = p.x * 100.0, p.z * 100.0, p.y * 100.0                      # shown cm, Y up
    k = f.get("b4d_type")
    inner = min(max(f.b4d_fd_inner / 100.0, 0.0), 0.999)

    def shape(d):
        return min(max((1.0 - d) / (1.0 - inner), 0.0), 1.0)
    r, h = max(f.b4d_fd_radius, 1e-4), max(f.b4d_fd_height / 2.0, 1e-4)
    if k == "fd_sphere":
        v = shape(math.sqrt(x * x + y * y + z * z) / r)
    elif k == "fd_box":
        sx, sy, sz = (max(c / 2.0, 1e-4) for c in f.b4d_fd_size)
        v = shape(max(abs(x) / sx, abs(y) / sy, abs(z) / sz))
    elif k == "fd_cylinder":
        v = shape(max(math.hypot(x, z) / r, abs(y) / h))
    elif k == "fd_cone":
        t = min(max((h - y) / (2.0 * h), 1e-4), 1.0)
        v = shape(max(math.hypot(x, z) / (r * t), abs(y) / h))
    elif k == "fd_capsule":
        cy = max(abs(y) - max(h - r, 0.0), 0.0)
        v = shape(math.sqrt(x * x + cy * cy + z * z) / r)
    elif k == "fd_torus":
        v = shape(math.hypot(math.hypot(x, z) - r, y) / max(f.b4d_fd_tube, 1e-4))
    elif k == "fd_linear":
        v = min(max(z / max(f.b4d_fd_length, 1e-4) + 0.5, 0.0), 1.0)
    elif k == "fd_radial":
        a = math.degrees(math.atan2(x, z)) % 360.0
        v = min(max(1.0 - a / max(f.b4d_fd_angle, 1e-3), 0.0), 1.0)
    else:
        v = 0.0
    if f.b4d_fd_invert:
        v = 1.0 - v
    return v * f.b4d_fd_strength / 100.0


def _start_frames(gen, scene, mats):
    """The frame each body starts moving: the first frame a listed field reaches its clone (None: never)."""
    fields = [e.obj for e in gen.b4d_field_list if e.on and e.obj is not None and e.obj.get("b4d_type", "").startswith("fd_")]
    w = scene.rigidbody_world
    first = w.point_cache.frame_start if w else scene.frame_start
    last = max(w.point_cache.frame_end if w else scene.frame_end, scene.frame_end)
    out = [None] * len(mats)
    if not fields:
        return out
    per_frame = [(f, [matrix_at(f, fr) for fr in range(first, last + 1)]) for f in fields]
    for i, mw in enumerate(mats):
        p = mw.translation
        for k, fr in enumerate(range(first, last + 1)):
            if any(field_value(f, ms[k], p) > 0.0 for f, ms in per_frame):
                out[i] = fr
                break
    return out


def _values(gen, scene, mats):
    """Per clone, per frame from the start: the strongest listed field's value there (0..1)."""
    fields = [e.obj for e in gen.b4d_field_list if e.on and e.obj is not None and e.obj.get("b4d_type", "").startswith("fd_")]
    w = scene.rigidbody_world
    first = w.point_cache.frame_start if w else scene.frame_start
    last = max(w.point_cache.frame_end if w else scene.frame_end, scene.frame_end)
    frames = list(range(first, last + 1))
    per = [(f, [matrix_at(f, fr) for fr in frames]) for f in fields]
    out = []
    for mw in mats:
        p = mw.translation
        out.append([max([field_value(f, ms[k], p) for f, ms in per] or [0.0]) for k in range(len(frames))])
    return frames, out


def _anchor(scene):
    """One still, passive body that every Follow Position spring holds on to; it collides with nothing."""
    a = bpy.data.objects.get(ANCHOR)
    if a is None:
        me = bpy.data.meshes.new(ANCHOR)
        me.from_pydata([(0, 0, 0), (0.001, 0, 0), (0, 0.001, 0), (0, 0, 0.001)], [], [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)])
        a = bpy.data.objects.new(ANCHOR, me)
        a["b4d_internal"] = True
        a.hide_select = True
        a.hide_render = True
        a.display_type = "BOUNDS"
        _collection(scene).objects.link(a)
    if a.name not in scene.rigidbody_world.collection.objects:
        scene.rigidbody_world.collection.objects.link(a)
    if a.rigid_body is None:
        with bpy.context.temp_override(object=a, active_object=a, selected_objects=[a]):
            bpy.ops.rigidbody.object_add(type="PASSIVE")
    a.rigid_body.type = "PASSIVE"
    a.rigid_body.collision_collections = [i == 19 for i in range(20)]
    return a


def springs(gen):
    return [o for o in bpy.data.objects if o.get("b4d_spring_of") == gen.name]


def _drop_springs(gen):
    for o in springs(gen):
        bpy.data.objects.remove(o)


def _spring(gen, ob, anchor, scene):
    name = f"{ob.name} spring"
    sp = bpy.data.objects.get(name)
    if sp is None:
        sp = bpy.data.objects.new(name, None)
        sp["b4d_spring_of"], sp["b4d_internal"] = gen.name, True
        sp.hide_select = True
        sp.empty_display_size = 0.001
        _collection(scene).objects.link(sp)
        with bpy.context.temp_override(object=sp, active_object=sp, selected_objects=[sp]):
            bpy.ops.rigidbody.constraint_add(type="GENERIC_SPRING")
    sp.matrix_world = ob.matrix_world.copy()
    c = sp.rigid_body_constraint
    c.type = "GENERIC_SPRING"
    c.object1, c.object2 = anchor, ob
    c.spring_type = "SPRING2"
    for ax in ("x", "y", "z"):
        for kind in ("", "ang_"):
            setattr(c, f"use_spring_{kind}{ax}", True)
            setattr(c, f"spring_damping_{kind}{ax}", 0.5)
    return sp


def _set_stiffness(c, k):
    for ax in ("x", "y", "z"):
        setattr(c, f"spring_stiffness_{ax}", k)
        setattr(c, f"spring_stiffness_ang_{ax}", k * 0.25)


def _key_stiffness(c, frame):
    for ax in ("x", "y", "z"):
        c.keyframe_insert(f"spring_stiffness_{ax}", frame=frame)
        c.keyframe_insert(f"spring_stiffness_ang_{ax}", frame=frame)


def _loosen(gen, scene, mats):
    """As a Field Loosens It: each clone hangs on a spring to its place (Follow Position); the spring's stiffness falls
    with the field's value at the clone and the spring lets go at full strength."""
    anchor = _anchor(scene)
    frames, values = _values(gen, scene, mats)
    hold = gen.b4d_dyn_follow / 100.0 * 4000.0 * gen.b4d_dyn_mass       # stiff enough to hold the clone up
    for ob, vals in zip(bodies(gen), values):
        ob.rigid_body.kinematic = False
        sp = _spring(gen, ob, anchor, scene)
        c = sp.rigid_body_constraint
        if sp.animation_data is not None:
            sp.animation_data_clear()
        c.enabled = True
        last = None
        released = None
        for fr, v in zip(frames, vals):
            if v >= RELEASE:
                released = fr
                break
            q = round(v, 2)
            if q != last:                                   # a key only where the value changes
                _set_stiffness(c, hold * (1.0 - q) ** 2)
                _key_stiffness(c, fr)
                last = q
        if released is not None:
            c.keyframe_insert("enabled", frame=frames[0])
            c.enabled = False
            c.keyframe_insert("enabled", frame=released)
            c.enabled = True
        _set_stiffness(c, hold)


def _activation(gen, ob, frame):
    """Hold the body in place (Blender's Animated) until frame, then let it move. frame None: it never moves."""
    rb = ob.rigid_body
    if ob.animation_data is not None:
        ob.animation_data_clear()
    mode = gen.b4d_dyn_start
    rb.use_deactivation = rb.use_start_deactivated = gen.get("b4d_dyn") == "ACTIVE" and mode == "COLLISION"
    if gen.get("b4d_dyn") != "ACTIVE" or mode != "FIELD":
        rb.kinematic = False
        return
    scene = bpy.context.scene
    w = scene.rigidbody_world
    first = w.point_cache.frame_start if w else scene.frame_start
    rb.kinematic = True
    if frame is None:
        return
    rb.keyframe_insert("kinematic", frame=first)
    rb.kinematic = False
    rb.keyframe_insert("kinematic", frame=max(frame, first + 1))
    rb.kinematic = True                                   # what shows at the start frame


def _settings(gen, ob):
    rb = ob.rigid_body
    if rb is None:
        return
    rb.type = gen.get("b4d_dyn", "ACTIVE")
    rb.mass = gen.b4d_dyn_mass
    rb.friction = gen.b4d_dyn_friction
    rb.restitution = gen.b4d_dyn_bounce
    rb.collision_shape = gen.b4d_dyn_shape
    rb.enabled = gen.b4d_dyn_dynamic if rb.type == "ACTIVE" else False


def rebuild(gen):
    """The bodies match the clones: as many, in their places, with the tag's settings. Only at the start frame."""
    if _busy[0]:
        return
    scene = bpy.context.scene
    _busy[0] = True
    try:
        world = _world(scene)
        coll = _collection(scene)
        clones = _clones(gen)
        have = bodies(gen)
        for ob in have[len(clones):]:                          # fewer clones now: their bodies go
            me = ob.data
            bpy.data.objects.remove(ob)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
        have = have[:len(clones)]
        cache = {}
        new = []
        for i, (child, mw, col) in enumerate(clones):
            shape = _shape_mesh(child, cache)
            if i < len(have):
                ob = have[i]
                if ob.data != shape:
                    ob.data = shape
            else:
                ob = bpy.data.objects.new(f"{gen.name} body {i}", shape)
                ob["b4d_body_of"], ob["b4d_body_i"], ob["b4d_internal"] = gen.name, i, True
                coll.objects.link(ob)
                ob.hide_select = True
                new.append(ob)
            ob.matrix_world = mw
            ob.color = col
        for ob in new:
            if ob.name not in world.collection.objects:
                world.collection.objects.link(ob)          # Blender gives an object in this collection a rigid body
        for ob in bodies(gen):
            if ob.rigid_body is None:
                with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
                    bpy.ops.rigidbody.object_add()
            _settings(gen, ob)
        mats = [m for _c, m, _col in clones]
        starts = _start_frames(gen, scene, mats) if gen.b4d_dyn_start == "FIELD" else [None] * len(mats)
        for ob, fr in zip(bodies(gen), starts):
            _activation(gen, ob, fr)
        for ob, picked in zip(bodies(gen), _selected.get(gen.name, [])):
            if not picked:                                 # outside the MoClone Selection: held, still a collider
                if ob.animation_data is not None:
                    ob.animation_data_clear()
                ob.rigid_body.kinematic = True
        if gen.get("b4d_dyn") == "ACTIVE" and gen.b4d_dyn_start == "LOOSEN":
            _loosen(gen, scene, mats)
        else:
            _drop_springs(gen)
        for me in cache.values():
            if me.users == 0:
                bpy.data.meshes.remove(me)
        gen["b4d_dyn_sig"] = _signature(gen)
        world.point_cache.frame_end = max(world.point_cache.frame_end, scene.frame_end)
    finally:
        _busy[0] = False


def clear(gen):
    _drop_springs(gen)
    for ob in bodies(gen):
        me = ob.data
        bpy.data.objects.remove(ob)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    gen.pop("b4d_dyn", None)
    gen.pop("b4d_dyn_sig", None)
    _simulated(gen, False)


def _signature(gen):
    """What the bodies were made from: the Cloner's nodes' inputs, its place, its children's and effectors' places."""
    from . import generators as g
    from .primitives import input_slot
    vals = []
    mod = g.gen_mod(gen)
    if mod is not None and mod.node_group is not None:
        for it in mod.node_group.interface.items_tree:
            if it.item_type == "SOCKET" and it.in_out == "INPUT" and it.name != "Simulated":
                try:
                    owner, attr = input_slot(mod, it.identifier)
                    v = getattr(owner, attr)
                    vals.append(str(tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else (v.name if hasattr(v, "name") else v)))
                except Exception:
                    pass
    obs = [gen] + list(gen.children) + [e.obj for e in getattr(gen, "b4d_fx_list", []) if e.obj is not None]
    for e in getattr(gen, "b4d_fx_list", []):
        if e.obj is not None:
            obs += [f.obj for f in e.obj.b4d_field_list if f.obj is not None]
            vals.append(str([round(getattr(e.obj, p), 4) if isinstance(getattr(e.obj, p), float) else str(tuple(getattr(e.obj, p))) if hasattr(getattr(e.obj, p), "__len__") else str(getattr(e.obj, p))
                             for p in ("b4d_fx_strength", "b4d_fx_pos", "b4d_fx_scale", "b4d_fx_rot", "b4d_fx_pos_on", "b4d_fx_seed")]))
    from . import field_tags
    vals += field_tags.signature(gen)
    for _i, t in field_tags.entries(gen):
        obs += [f.obj for f in t.fields if f.obj is not None]
        vals.append(str(round(t.threshold, 3)))
    vals.append(gen.b4d_dyn_start + str(round(gen.b4d_dyn_follow, 3)) + str(round(gen.b4d_dyn_mass, 4)))
    for e in gen.b4d_field_list:
        f = e.obj
        if f is not None:
            obs.append(f)
            vals.append(str([(fc.data_path, fc.array_index, [tuple(k.co) for k in fc.keyframe_points]) for fc in _fcurves(f)]))
            vals.append(str([getattr(f, p, None) for p in ("b4d_fd_radius", "b4d_fd_inner", "b4d_fd_invert", "b4d_fd_strength", "b4d_fd_height", "b4d_fd_length")]))
            vals.append(str(tuple(f.b4d_fd_size)) + str(e.on))
    for o in obs:
        vals.append(o.name + str([round(x, 4) for r in o.matrix_world for x in r]))
    return str(hash(tuple(vals)))


def _at_start(scene):
    w = scene.rigidbody_world
    return w is None or scene.frame_current <= w.point_cache.frame_start


@bpy.app.handlers.persistent
def _sync(scene, depsgraph=None):
    """At the start frame, bodies follow any change to their Cloner."""
    if _busy[0] or not _at_start(scene):
        return
    for gen in [o for o in scene.objects if o.get("b4d_type") == "cloner" and on(o)]:
        if gen.get("b4d_dyn_sig") != _signature(gen):
            rebuild(gen)
    for ob in [o for o in bpy.data.objects if (o.get("b4d_body_of") or o.get("b4d_spring_of"))
               and not on(bpy.data.objects.get(o.get("b4d_body_of") or o.get("b4d_spring_of")) or o)]:
        bpy.data.objects.remove(ob)                       # the Cloner went or lost its tag


_pending = [False]


@bpy.app.handlers.persistent
def _on_update(scene, depsgraph=None):
    """Blender's update handlers must not add objects or evaluate the scene (Blender 5.2 crashes): the work is done
    from a timer, right after the update."""
    if _pending[0] or _busy[0]:
        return
    _pending[0] = True

    def run():
        _pending[0] = False
        try:
            _sync(bpy.context.scene)
        except Exception as ex:
            print("Blenda 4D:", __name__, ex)
        return None
    bpy.app.timers.register(run, first_interval=0.0)


def _changed(self, context):
    for ob in bodies(self):
        _settings(self, ob)
    w = context.scene.rigidbody_world
    if w is not None:
        w.point_cache.frame_start = w.point_cache.frame_start      # settings changed: the cache starts again


def tag(context, gen, kind):
    """kind: "ACTIVE" (Rigid Body) or "PASSIVE" (Collider Body)."""
    gen["b4d_dyn"] = kind
    gen.pop("b4d_dyn_sig", None)
    rebuild(gen)
    _simulated(gen, True)


def page(col, gen):
    c = col.column()
    if gen.get("b4d_dyn") == "ACTIVE":
        c.prop(gen, "b4d_dyn_dynamic", text="Dynamic")
        c.prop(gen, "b4d_dyn_start", text="Start")
        if gen.b4d_dyn_start in ("FIELD", "LOOSEN"):
            if gen.b4d_dyn_start == "LOOSEN":
                c.prop(gen, "b4d_dyn_follow", text="Follow Position")
            from . import moclone_fx_ui
            moclone_fx_ui._list(c, gen, "field")
            c.separator()
        c.prop(gen, "b4d_dyn_mass", text="Mass")
    c.prop(gen, "b4d_dyn_friction", text="Friction", slider=True)
    c.prop(gen, "b4d_dyn_bounce", text="Bounce", slider=True)
    c.prop(gen, "b4d_dyn_shape", text="Shape")
    c.separator()
    c.label(text="Each clone is its own body.", icon="INFO")
    c.label(text="Change the Cloner at the first frame, then play.")
    c.label(text="Collider Body objects are hit.")


def _restart(self, context):
    self.pop("b4d_dyn_sig", None)
    _sync(context.scene)


PROPS = ("b4d_dyn_follow", "b4d_dyn_start", "b4d_dyn_mass", "b4d_dyn_friction", "b4d_dyn_bounce", "b4d_dyn_shape", "b4d_dyn_dynamic")


def register():
    O, P = bpy.types.Object, bpy.props
    O.b4d_dyn_mass = P.FloatProperty(name="Mass", default=1.0, min=0.001, update=_changed, description="Each clone's mass (kg)")
    O.b4d_dyn_friction = P.FloatProperty(name="Friction", default=0.5, min=0.0, max=1.0, update=_changed, description="How much clones grip")
    O.b4d_dyn_bounce = P.FloatProperty(name="Bounce", default=0.0, min=0.0, max=1.0, update=_changed, description="How much clones bounce")
    O.b4d_dyn_shape = P.EnumProperty(name="Shape", items=SHAPES, default="CONVEX_HULL", update=_changed, description="The shape each clone collides as")
    O.b4d_dyn_start = P.EnumProperty(name="Start", items=START, default="IMMEDIATELY", update=_restart,
                                     description="When the clones start to move")
    O.b4d_dyn_follow = P.FloatProperty(name="Follow Position", default=100.0, min=0.0, max=1000.0, soft_max=100.0, subtype="PERCENTAGE",
                                       update=_restart, description="How firmly each clone holds its place before the field loosens it")
    O.b4d_dyn_dynamic = P.BoolProperty(name="Dynamic", default=True, update=_changed, description="Clones move with the simulation")
    if _on_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_update)
    if _on_update not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_on_update)


def unregister():
    for h in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post):
        for fn in (_sync, _on_update):
            if fn in h:
                h.remove(fn)
    for n in PROPS:
        if hasattr(bpy.types.Object, n):
            delattr(bpy.types.Object, n)
