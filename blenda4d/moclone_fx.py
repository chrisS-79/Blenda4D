# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone effectors and fields.

An effector is an object (an Empty) that changes the clones of the Cloners whose Effectors list holds it: Plain,
Random, Shader, Step, Delay, Target and Time. A field is an object that says how strongly an effector works where each
clone is: Linear, Spherical, Box, Cylinder, Cone, Capsule, Torus, Radial and Random. An effector with no fields works
on every clone at full strength.

Settings live on the effector and field objects (Blender properties, so they can be keyframed) and reach the clones
through drivers on Value nodes in the Cloner's node group: changing a value updates the clones at once. Adding,
removing or reordering effectors or fields rebuilds the Cloner's nodes (signature())."""
import math

import bpy

from . import gen_caps as gc
from .primitives import _math

EFFECTORS = {"fx_plain": ("Plain", "Moves, scales and turns clones, as strongly as its fields say"),
             "fx_random": ("Random", "Moves, scales, turns and colours each clone by a random amount"),
             "fx_shader": ("Shader", "Uses a texture's brightness to move, scale and turn clones, and its colours to colour them"),
             "fx_step": ("Step", "Changes clones step by step, from none on the first clone to all on the last"),
             "fx_delay": ("Delay", "Makes clones follow the effectors above it with a lag, smoothly or springing"),
             "fx_target": ("Target", "Turns clones to face an object or the camera"),
             "fx_time": ("Time", "Changes clones more and more as time goes on"),
             "fx_formula": ("Formula", "Changes clones by a formula you type, from each clone's number, place and the time"),
             "fx_inherit": ("Inheritance", "Moves clones to where another Cloner's clones are, or plays an object's animation on them"),
             "fx_pushapart": ("Push Apart", "Moves, shrinks or hides clones so they don't overlap"),
             "fx_reeffector": ("ReEffector", "Runs the effectors in its own list, as strongly as its fields say"),
             "fx_sound": ("Sound", "Changes clones by a sound's loudness, each clone listening to its own pitch range"),
             "fx_spline": ("Spline", "Moves clones onto a spline"),
             "fx_volume": ("Volume", "Changes the clones inside an object"),
             "fx_group": ("Group", "Runs the effectors in its own list together, so one Strength works on them all")}
NESTS = ("fx_group", "fx_reeffector")                               # effectors that hold an Effectors list of their own
FIELDS = {"fd_linear": ("Linear Field", "Full strength on one side, none on the other, in a ramp along its Z axis"),
          "fd_sphere": ("Spherical Field", "Full strength inside a sphere, fading to none at its surface"),
          "fd_box": ("Box Field", "Full strength inside a box, fading to none at its sides"),
          "fd_cylinder": ("Cylinder Field", "Full strength inside a cylinder, fading to none at its surface"),
          "fd_cone": ("Cone Field", "Full strength inside a cone, fading to none at its surface"),
          "fd_capsule": ("Capsule Field", "Full strength inside a capsule, fading to none at its surface"),
          "fd_torus": ("Torus Field", "Full strength inside a ring, fading to none at its surface"),
          "fd_radial": ("Radial Field", "Strength by angle around its Y axis: a pie slice"),
          "fd_random": ("Random Field", "A random strength for each clone, or a noise pattern through space")}
ICONS = {"fx_plain": "EMPTY_AXIS", "fx_random": "FORCE_TURBULENCE", "fx_shader": "TEXTURE", "fx_step": "IPO_CONSTANT",
         "fx_delay": "TIME", "fx_target": "TRACKER", "fx_time": "PREVIEW_RANGE",
         "fx_formula": "DRIVER", "fx_inherit": "LINKED", "fx_pushapart": "FULLSCREEN_EXIT", "fx_reeffector": "LOOP_BACK",
         "fx_sound": "SOUND", "fx_spline": "CURVE_BEZCURVE", "fx_volume": "MESH_ICOSPHERE", "fx_group": "GROUP",
         "fd_linear": "IPO_LINEAR", "fd_sphere": "SPHERE", "fd_box": "CUBE", "fd_cylinder": "MESH_CYLINDER", "fd_cone": "CONE",
         "fd_capsule": "MESH_CAPSULE", "fd_torus": "MESH_TORUS", "fd_radial": "MOD_SCREW", "fd_random": "FORCE_TURBULENCE"}
COLOR_MODES = [("OFF", "Off", "Effector leaves the clone colours as they are", 0),
               ("EFFECTOR", "Effector Color", "Colours the clones with the effector's own colour (Basic tab)", 1),
               ("CUSTOM", "Custom Color", "Colours the clones with the Color below", 2)]
RANDOM_MODES = [("RANDOM", "Random", "A fixed random value for each clone", 0),
                ("GAUSSIAN", "Gaussian", "Random values that gather around the middle", 1),
                ("NOISE", "Noise", "A smooth noise through space that can move over time", 2),
                ("TURBULENCE", "Turbulence", "A sharper, rougher noise through space", 3)]
DELAY_MODES = [("BLEND", "Blend", "Clones ease toward where the effectors above put them", 0),
               ("SPRING", "Spring", "Clones overshoot and spring back", 1)]
TARGET_MODES = [("OBJECT", "Object", "Clones face the Target Object", 0), ("CAMERA", "Camera", "Clones face the scene camera", 1)]
PUSH_MODES = [("HIDE", "Hide", "Hides clones that overlap ones earlier in the order; none move", 0),
              ("PUSH", "Push Apart", "Moves clones away from each other until they don't overlap", 1),
              ("SCALE", "Scale Apart", "Shrinks overlapping clones until they just touch", 2),
              ("X", "Along X", "Pushes each clone only along its own X axis", 3),
              ("Y", "Along Y", "Pushes each clone only along its own Y axis", 4),
              ("Z", "Along Z", "Pushes each clone only along its own Z axis", 5)]
SHADER_SOURCES = [("NOISE", "Noise", "A noise pattern", 0), ("IMAGE", "Image", "An image, laid over the clones by their U and V", 1)]
AXES = [("XP", "+X", "", 0), ("XN", "-X", "", 1), ("YP", "+Y", "", 2), ("YN", "-Y", "", 3), ("ZP", "+Z", "", 4), ("ZN", "-Z", "", 5)]


def is_effector(ob):
    return ob is not None and ob.get("b4d_type") in EFFECTORS


def is_field(ob):
    return ob is not None and ob.get("b4d_type") in FIELDS


LISTS = ("b4d_fx_list", "b4d_fx_list_all", "b4d_fx_list_lines", "b4d_fx_list_words")   # MoText: Letters, All, Lines, Words


def effectors_of(gen, lst="b4d_fx_list"):
    return [(i, e) for i, e in enumerate(getattr(gen, lst, [])) if is_effector(e.obj)]


def fields_of(eff):
    return [(i, f) for i, f in enumerate(getattr(eff, "b4d_field_list", [])) if is_field(f.obj)]


def signature(gen):
    """What shapes the Cloner's nodes: its effectors and their fields, in order."""
    out = [f"bare:{c.name}" for c in gen.children if not any(sl.material for sl in getattr(c, "material_slots", []))]
    from . import field_tags
    out += field_tags.clone_tag_signature(gen) + [f"sel:{getattr(e.obj, 'b4d_fx_use_sel', False)}" for _i, e in effectors_of(gen)]
    for lst in LISTS:
        for i, e in effectors_of(gen, lst):
            out += _sig_one(i, e.obj, lst[11:] + ":")
    from . import moclone_gens
    out += moclone_gens.extra_signature(gen)
    return out


def _sig_one(i, ob, pad, depth=0):
    tgt, img = getattr(ob, "b4d_fx_target", None), getattr(ob, "b4d_fx_image", None)
    out = [f"{pad}{i}:{ob.name}:{ob['b4d_type']}:{tgt.name if tgt else ''}:{img.name if img else ''}:{_extra(ob)}"]
    for j, f in fields_of(ob):
        out.append(f"{pad}  {j}:{f.obj.name}:{f.obj['b4d_type']}")
    if ob["b4d_type"] in NESTS and depth < 4:
        for j, c in effectors_of(ob):
            if c.obj != ob:
                out += _sig_one(j, c.obj, pad + "    ", depth + 1)
    return out


def _extra(ob):
    """What else shapes this effector's nodes: a typed formula, the objects it reads, a sound."""
    k = ob["b4d_type"]
    if k == "fx_formula":
        return ob.b4d_fx_formula
    if k in ("fx_volume", "fx_spline", "fx_inherit"):
        o = getattr(ob, {"fx_volume": "b4d_fx_volume", "fx_spline": "b4d_fx_spline", "fx_inherit": "b4d_fx_inherit"}[k], None)
        rail = getattr(ob, "b4d_fx_rail", None) if k == "fx_spline" else None
        extra = ""
        if k == "fx_inherit":
            from . import moclone_bake
            extra = moclone_bake.motion_key(ob)
        return f"{o.name if o else ''}:{rail.name if rail else ''}:{extra}"
    if k == "fx_sound":
        from . import moclone_bake
        return moclone_bake.sound_key(ob)
    return ""


# --- drivers ---------------------------------------------------------------------------------------------------------

def _driven(nodes, owner, path, expr="var"):
    n = nodes.new("ShaderNodeValue")
    d = n.outputs[0].driver_add("default_value").driver
    d.type = "SCRIPTED"
    v = d.variables.new(); v.name = "var"; v.type = "SINGLE_PROP"
    v.targets[0].id = owner
    v.targets[0].data_path = path
    d.expression = expr
    return n.outputs[0]


def _vec(nodes, links, owner, path, expr="var"):
    """A shown (Y up) vector property as a Blender vector: shown (x, y, z) -> Blender (x, z, y)."""
    return gc.combine(nodes, links, _driven(nodes, owner, f"{path}[0]", expr), _driven(nodes, owner, f"{path}[2]", expr),
                      _driven(nodes, owner, f"{path}[1]", expr))


def _color(nodes, links, owner, path):
    c = nodes.new("FunctionNodeCombineColor")
    for k, ch in enumerate(("Red", "Green", "Blue")):
        links.new(_driven(nodes, owner, f"{path}[{k}]"), c.inputs[ch])
    c.inputs["Alpha"].default_value = 1.0
    return c.outputs[0]


def _attr(nodes, name, typ):
    a = nodes.new("GeometryNodeInputNamedAttribute"); a.data_type = typ
    a.inputs["Name"].default_value = name
    return a.outputs["Attribute"]


def _store(nodes, links, geo, name, typ, value):
    st = nodes.new("GeometryNodeStoreNamedAttribute"); st.data_type = typ; st.domain = "POINT"
    links.new(geo, st.inputs["Geometry"]); st.inputs["Name"].default_value = name
    links.new(value, st.inputs["Value"])
    return st.outputs["Geometry"]


def _euler(nodes, links, rad_vec):
    e = nodes.new("FunctionNodeEulerToRotation"); links.new(rad_vec, e.inputs[0])
    return e.outputs[0]


def _clamp(nodes, links, v, lo=0.0, hi=1.0):
    return _math(nodes, "MINIMUM", _math(nodes, "MAXIMUM", v, lo, links), hi, links)


def _mix(nodes, links, kind, f, a, b):
    m = nodes.new("ShaderNodeMix"); m.data_type = kind
    if kind == "VECTOR":
        m.factor_mode = "UNIFORM"
    links.new(f, m.inputs["Factor"])
    names = {"FLOAT": ("A", "B"), "VECTOR": ("A", "B"), "RGBA": ("A", "B"), "ROTATION": ("A", "B")}[kind]
    ins = [s for s in m.inputs if s.enabled and s.name in names]
    for sock, v in zip(ins, (a, b)):
        links.new(v, sock)
    return [s for s in m.outputs if s.enabled][0]


def _rand(nodes, links, lo, hi, ident, seed, typ="FLOAT"):
    r = nodes.new("FunctionNodeRandomValue"); r.data_type = typ
    ins = [s for s in r.inputs if s.enabled]
    for sock, v in zip(ins[:2], (lo, hi)):
        if hasattr(v, "is_output"):
            links.new(v, sock)
        else:
            sock.default_value = v
    links.new(ident, r.inputs["ID"])
    links.new(seed, r.inputs["Seed"]) if hasattr(seed, "is_output") else setattr(r.inputs["Seed"], "default_value", seed)
    return [s for s in r.outputs if s.enabled][0]


# --- fields ----------------------------------------------------------------------------------------------------------

def _local(nodes, links, field):
    """The current clone position in the field's own space (shown sizes are cm, so this is in cm too, Y up)."""
    info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"
    info.inputs["Object"].default_value = field
    inv = nodes.new("FunctionNodeInvertMatrix"); links.new(info.outputs["Transform"], inv.inputs[0])
    tp = nodes.new("FunctionNodeTransformPoint"); links.new(gc.position(nodes), tp.inputs["Vector"])
    links.new(inv.outputs[0], tp.inputs["Transform"])
    p = gc.separate(nodes, links, gc.vmath(nodes, links, "SCALE", tp.outputs[0], scale=100.0))
    return p["X"], p["Z"], p["Y"]                                  # shown x, y, z


def _length(nodes, links, *v):
    t = 0.0
    for c in v:
        t = _math(nodes, "ADD", t, _math(nodes, "MULTIPLY", c, c, links), links)
    return _math(nodes, "SQRT", t, None, links)


def _shape_value(nodes, links, f, d):
    """d: 0 at the centre, 1 at the shape's surface. Inner Offset keeps full strength out to that share."""
    inner = _clamp(nodes, links, _driven(nodes, f, "b4d_fd_inner", "var*0.01"), 0.0, 0.999)
    return _clamp(nodes, links, _math(nodes, "DIVIDE", _math(nodes, "SUBTRACT", 1.0, d, links), _math(nodes, "SUBTRACT", 1.0, inner, links), links))


def field_value(nodes, links, f):
    k = f["b4d_type"]
    x, y, z = _local(nodes, links, f)
    ab = lambda v: _math(nodes, "ABSOLUTE", v, None, links)
    size = [_math(nodes, "MAXIMUM", _driven(nodes, f, f"b4d_fd_size[{i}]", "var*0.5"), 1e-4, links) for i in range(3)]     # half sizes
    radius = _math(nodes, "MAXIMUM", _driven(nodes, f, "b4d_fd_radius"), 1e-4, links)
    height = _math(nodes, "MAXIMUM", _driven(nodes, f, "b4d_fd_height", "var*0.5"), 1e-4, links)
    if k == "fd_sphere":
        v = _shape_value(nodes, links, f, _math(nodes, "DIVIDE", _length(nodes, links, x, y, z), radius, links))
    elif k == "fd_box":
        d = _math(nodes, "MAXIMUM", _math(nodes, "MAXIMUM", _math(nodes, "DIVIDE", ab(x), size[0], links), _math(nodes, "DIVIDE", ab(y), size[1], links), links),
                  _math(nodes, "DIVIDE", ab(z), size[2], links), links)
        v = _shape_value(nodes, links, f, d)
    elif k == "fd_cylinder":
        d = _math(nodes, "MAXIMUM", _math(nodes, "DIVIDE", _length(nodes, links, x, z), radius, links), _math(nodes, "DIVIDE", ab(y), height, links), links)
        v = _shape_value(nodes, links, f, d)
    elif k == "fd_cone":
        # tip at the top (shown +Y), base of Radius at the bottom
        t = _clamp(nodes, links, _math(nodes, "DIVIDE", _math(nodes, "SUBTRACT", height, y, links), _math(nodes, "MULTIPLY", height, 2.0, links), links), 1e-4, 1.0)
        d = _math(nodes, "MAXIMUM", _math(nodes, "DIVIDE", _length(nodes, links, x, z), _math(nodes, "MULTIPLY", radius, t, links), links),
                  _math(nodes, "DIVIDE", ab(y), height, links), links)
        v = _shape_value(nodes, links, f, d)
    elif k == "fd_capsule":
        cy = _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", ab(y), _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", height, radius, links), 0.0, links), links), 0.0, links)
        v = _shape_value(nodes, links, f, _math(nodes, "DIVIDE", _length(nodes, links, x, cy, z), radius, links))
    elif k == "fd_torus":
        ring = _math(nodes, "SUBTRACT", _length(nodes, links, x, z), radius, links)
        tube = _math(nodes, "MAXIMUM", _driven(nodes, f, "b4d_fd_tube"), 1e-4, links)
        v = _shape_value(nodes, links, f, _math(nodes, "DIVIDE", _length(nodes, links, ring, y), tube, links))
    elif k == "fd_linear":
        # 0 at -Length/2, 1 at +Length/2 along the field's Z
        length = _math(nodes, "MAXIMUM", _driven(nodes, f, "b4d_fd_length"), 1e-4, links)
        v = _clamp(nodes, links, _math(nodes, "ADD", _math(nodes, "DIVIDE", z, length, links), 0.5, links))
    elif k == "fd_radial":
        # by angle around Y: full at 0 degrees, none at the End Angle
        ang = _math(nodes, "DEGREES", _math(nodes, "ARCTAN2", x, z, links), None, links)
        ang = _math(nodes, "FLOORED_MODULO", ang, 360.0, links)
        end = _math(nodes, "MAXIMUM", _driven(nodes, f, "b4d_fd_angle"), 1e-3, links)
        v = _clamp(nodes, links, _math(nodes, "SUBTRACT", 1.0, _math(nodes, "DIVIDE", ang, end, links), links))
    else:  # fd_random
        noise = nodes.new("ShaderNodeTexNoise"); noise.noise_dimensions = "4D"
        links.new(gc.vmath(nodes, links, "SCALE", gc.combine(nodes, links, x, y, z),
                           scale=_math(nodes, "DIVIDE", 1.0, _math(nodes, "MAXIMUM", _driven(nodes, f, "b4d_fd_scale"), 1e-3, links), links)), noise.inputs["Vector"])
        tm = nodes.new("GeometryNodeInputSceneTime").outputs["Seconds"]
        links.new(_math(nodes, "ADD", _math(nodes, "MULTIPLY", tm, _driven(nodes, f, "b4d_fd_speed"), links), _driven(nodes, f, "b4d_fd_seed", "var*0.731"), links), noise.inputs["W"])
        rnd = _rand(nodes, links, 0.0, 1.0, _attr(nodes, "b4d_index", "INT"), _driven(nodes, f, "b4d_fd_seed"))
        smooth = _clamp(nodes, links, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", noise.outputs["Fac"], 0.5, links), 2.2, links), -0.5, 0.5)
        smooth = _math(nodes, "ADD", smooth, 0.5, links)
        v = gc.switch(nodes, links, "FLOAT", _driven(nodes, f, "b4d_fd_noise"), rnd, smooth)
    # Remap: Invert, then Strength
    inv = _driven(nodes, f, "b4d_fd_invert")
    v = _mix(nodes, links, "FLOAT", inv, v, _math(nodes, "SUBTRACT", 1.0, v, links))
    return _math(nodes, "MULTIPLY", v, _driven(nodes, f, "b4d_fd_strength", "var*0.01"), links)


def falloff(nodes, links, eff):
    """How strongly the effector works on each clone: 1 with no fields; otherwise the fields, the strongest wins."""
    fs = fields_of(eff)
    if not fs:
        return None
    v = 0.0
    for j, entry in fs:
        on = _driven(nodes, eff, f"b4d_field_list[{j}].on")
        fv = _math(nodes, "MULTIPLY", field_value(nodes, links, entry.obj), _math(nodes, "MULTIPLY", on, _driven(nodes, eff, f"b4d_field_list[{j}].opacity", "var*0.01"), links), links)
        v = _math(nodes, "MAXIMUM", v, fv, links)
    return v


# --- effectors ----------------------------------------------------------------------------------------------------

def _params(nodes, links, e):
    """The Parameter tab: position (cm), scale, rotation (radians), as Blender vectors. Scale is set as a percentage of
    the clone's own size (100 = as it is, 0 = gone, 200 = twice); here it becomes the change from 100 (0 = none)."""
    pos = gc.vmath(nodes, links, "SCALE", _vec(nodes, links, e, "b4d_fx_pos", "var*0.01"), scale=_driven(nodes, e, "b4d_fx_pos_on"))
    uni = _driven(nodes, e, "b4d_fx_uniform")
    us = _driven(nodes, e, "b4d_fx_uscale", "(var-100)*0.01")
    sc = gc.switch(nodes, links, "VECTOR", _math(nodes, "GREATER_THAN", uni, 0.5, links),
                   _vec(nodes, links, e, "b4d_fx_scale", "(var-100)*0.01"), gc.combine(nodes, links, us, us, us))
    sc = gc.vmath(nodes, links, "SCALE", sc, scale=_driven(nodes, e, "b4d_fx_scale_on"))
    rot = gc.vmath(nodes, links, "SCALE", _vec(nodes, links, e, "b4d_fx_rot", f"var*{math.pi / 180.0!r}"), scale=_driven(nodes, e, "b4d_fx_rot_on"))
    return pos, sc, rot


def _apply_transform(nodes, links, geo, w, pos, sc, rot):
    """Add w x (pos, scale, rot) to each clone, in the clone's own space (Transform Space: Node)."""
    q = _attr(nodes, "b4d_rot_q", "QUATERNION")
    rv = nodes.new("FunctionNodeRotateVector"); links.new(gc.vmath(nodes, links, "SCALE", pos, scale=w), rv.inputs["Vector"]); links.new(q, rv.inputs["Rotation"])
    sp = nodes.new("GeometryNodeSetPosition"); links.new(geo, sp.inputs["Geometry"]); links.new(rv.outputs[0], sp.inputs["Offset"])
    geo = sp.outputs["Geometry"]
    grow = gc.vmath(nodes, links, "ADD", gc.combine(nodes, links, 1.0, 1.0, 1.0), gc.vmath(nodes, links, "SCALE", sc, scale=w))
    grow = gc.vmath(nodes, links, "MAXIMUM", grow, (0.0, 0.0, 0.0))     # a clone shrinks to nothing, never inside out
    geo = _store(nodes, links, geo, "b4d_scale", "FLOAT_VECTOR", gc.vmath(nodes, links, "MULTIPLY", _attr(nodes, "b4d_scale", "FLOAT_VECTOR"), grow))
    rr = nodes.new("FunctionNodeRotateRotation"); rr.rotation_space = "LOCAL"
    links.new(q, rr.inputs["Rotation"]); links.new(_euler(nodes, links, gc.vmath(nodes, links, "SCALE", rot, scale=w)), rr.inputs["Rotate By"])
    return _store(nodes, links, geo, "b4d_rot_q", "QUATERNION", rr.outputs[0])


def _apply_color(nodes, links, geo, e, w, own=None):
    """Color Mode: the clone colour moves toward the effector's colour as strongly as w."""
    mode = _driven(nodes, e, "b4d_fx_color_mode")
    eff_col = _color(nodes, links, e, "color")
    cus_col = _color(nodes, links, e, "b4d_fx_color")
    col = gc.switch(nodes, links, "RGBA", _math(nodes, "GREATER_THAN", mode, 1.5, links), eff_col, cus_col)
    if own is not None:                                            # Random and Shader bring their own colour
        col = own
    f = _math(nodes, "MULTIPLY", _clamp(nodes, links, w), _math(nodes, "GREATER_THAN", mode, 0.5, links), links)
    return _store(nodes, links, geo, "b4d_color", "FLOAT_COLOR", _mix(nodes, links, "RGBA", f, _attr(nodes, "b4d_color", "FLOAT_COLOR"), col))


def _apply_visibility(nodes, links, geo, e, w):
    """Visibility: clones where the effector works under half strength are hidden (at the end, so every effector
    still counts them)."""
    hide = _math(nodes, "MULTIPLY", _driven(nodes, e, "b4d_fx_visibility"), _math(nodes, "LESS_THAN", w, 0.5, links), links)
    prev = _attr(nodes, "b4d_hidden", "FLOAT")
    return _store(nodes, links, geo, "b4d_hidden", "FLOAT", _math(nodes, "MAXIMUM", prev, hide, links))


def _weight(nodes, links, gen, i, e, lst="b4d_fx_list"):
    """Strength x the list's own strength and switch x (Minimum..Maximum over the fields' value)."""
    fall = falloff(nodes, links, e)
    lo = _driven(nodes, e, "b4d_fx_min", "var*0.01")
    hi = _driven(nodes, e, "b4d_fx_max", "var*0.01")
    v = hi if fall is None else _math(nodes, "ADD", lo, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", hi, lo, links), fall, links), links)
    s = _math(nodes, "MULTIPLY", _driven(nodes, e, "b4d_fx_strength", "var*0.01"),
              _math(nodes, "MULTIPLY", _driven(nodes, gen, f"{lst}[{i}].strength", "var*0.01"), _driven(nodes, gen, f"{lst}[{i}].on"), links), links)
    return _math(nodes, "MULTIPLY", v, s, links)


def _signed_rand(nodes, links, e, ident, salt, mode, scale_by=None):
    """-1..1 per clone: Random, Gaussian, Noise or Turbulence."""
    seed = _math(nodes, "ADD", _driven(nodes, e, "b4d_fx_seed"), salt, links)
    uni = _rand(nodes, links, -1.0, 1.0, ident, seed)
    g = 0.0
    for k in range(3):
        g = _math(nodes, "ADD", g, _rand(nodes, links, -1.0, 1.0, ident, _math(nodes, "ADD", seed, 101 * (k + 1), links)), links)
    gauss = _clamp(nodes, links, _math(nodes, "MULTIPLY", g, 0.6, links), -1.0, 1.0)
    noise = nodes.new("ShaderNodeTexNoise"); noise.noise_dimensions = "4D"
    links.new(gc.vmath(nodes, links, "SCALE", gc.position(nodes), scale=_math(nodes, "DIVIDE", 100.0, _math(nodes, "MAXIMUM", _driven(nodes, e, "b4d_fx_noise_scale"), 1e-3, links), links)), noise.inputs["Vector"])
    tm = nodes.new("GeometryNodeInputSceneTime").outputs["Seconds"]
    links.new(_math(nodes, "ADD", _math(nodes, "MULTIPLY", tm, _driven(nodes, e, "b4d_fx_speed"), links), _math(nodes, "MULTIPLY", seed, 0.137, links), links), noise.inputs["W"])
    smooth = _clamp(nodes, links, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", noise.outputs["Fac"], 0.5, links), 4.0, links), -1.0, 1.0)
    turb = _math(nodes, "SUBTRACT", _math(nodes, "MULTIPLY", _math(nodes, "ABSOLUTE", smooth, None, links), 2.0, links), 1.0, links)
    return gc.index_switch(nodes, links, "FLOAT", mode, [uni, gauss, smooth, turb])


def _random(nodes, links, geo, gen, i, e, w):
    pos, sc, rot = _params(nodes, links, e)
    ident = _attr(nodes, "b4d_index", "INT")
    mode = _driven(nodes, e, "b4d_fx_random_mode")
    r = [_signed_rand(nodes, links, e, ident, 17 * (k + 1), mode) for k in range(3)]
    rv = gc.combine(nodes, links, *r)
    us = gc.combine(nodes, links, r[0], r[0], r[0])
    sc_r = gc.switch(nodes, links, "VECTOR", _math(nodes, "GREATER_THAN", _driven(nodes, e, "b4d_fx_uniform"), 0.5, links), rv, us)
    geo = _apply_transform(nodes, links, geo, w, gc.vmath(nodes, links, "MULTIPLY", pos, rv), gc.vmath(nodes, links, "MULTIPLY", sc, sc_r),
                           gc.vmath(nodes, links, "MULTIPLY", rot, gc.combine(nodes, links, *[_signed_rand(nodes, links, e, ident, 53 * (k + 1), mode) for k in range(3)])))
    hue = _math(nodes, "ADD", _math(nodes, "MULTIPLY", _signed_rand(nodes, links, e, ident, 211, mode), 0.5, links), 0.5, links)
    hsv = nodes.new("FunctionNodeCombineColor"); hsv.mode = "HSV"
    links.new(hue, hsv.inputs[0]); hsv.inputs[1].default_value = 1.0; hsv.inputs[2].default_value = 1.0
    color_custom = _math(nodes, "GREATER_THAN", _driven(nodes, e, "b4d_fx_color_mode"), 1.5, links)
    own = gc.switch(nodes, links, "RGBA", color_custom, hsv.outputs[0], _color(nodes, links, e, "b4d_fx_color"))
    geo = _apply_color(nodes, links, geo, e, w, own)
    return _apply_visibility(nodes, links, geo, e, w)


def _shader(nodes, links, geo, gen, i, e, w):
    uv = _attr(nodes, "b4d_uv", "FLOAT_VECTOR")
    noise = nodes.new("ShaderNodeTexNoise")
    links.new(gc.vmath(nodes, links, "SCALE", uv, scale=_driven(nodes, e, "b4d_fx_noise_scale", "var*0.05")), noise.inputs["Vector"])
    img = nodes.new("GeometryNodeImageTexture")
    if e.b4d_fx_image is not None:
        img.inputs["Image"].default_value = e.b4d_fx_image
    links.new(uv, img.inputs["Vector"])
    src = _math(nodes, "GREATER_THAN", _driven(nodes, e, "b4d_fx_shader_source"), 0.5, links)
    col = gc.switch(nodes, links, "RGBA", src, noise.outputs["Color"], img.outputs["Color"])
    sep = nodes.new("FunctionNodeSeparateColor"); links.new(col, sep.inputs[0])
    lum = _math(nodes, "ADD", _math(nodes, "ADD", _math(nodes, "MULTIPLY", sep.outputs[0], 0.2126, links), _math(nodes, "MULTIPLY", sep.outputs[1], 0.7152, links), links),
                _math(nodes, "MULTIPLY", sep.outputs[2], 0.0722, links), links)
    # brightness 0.5 is no change, darker moves the other way: the value runs -1..1
    value = _math(nodes, "SUBTRACT", _math(nodes, "MULTIPLY", lum, 2.0, links), 1.0, links)
    pos, sc, rot = _params(nodes, links, e)
    geo = _apply_transform(nodes, links, geo, _math(nodes, "MULTIPLY", w, value, links), pos, sc, rot)
    color_custom = _math(nodes, "GREATER_THAN", _driven(nodes, e, "b4d_fx_color_mode"), 1.5, links)
    own = gc.switch(nodes, links, "RGBA", color_custom, col, _color(nodes, links, e, "b4d_fx_color"))
    geo = _apply_color(nodes, links, geo, e, w, own)
    return _apply_visibility(nodes, links, geo, e, w)


def _plain(nodes, links, geo, gen, i, e, w):
    geo = _apply_transform(nodes, links, geo, w, *_params(nodes, links, e))
    geo = _apply_color(nodes, links, geo, e, w)
    return _apply_visibility(nodes, links, geo, e, w)


def _step(nodes, links, geo, gen, i, e, w):
    u = _attr(nodes, "b4d_u", "FLOAT")
    return _plain(nodes, links, geo, gen, i, e, _math(nodes, "MULTIPLY", w, u, links))


def _time(nodes, links, geo, gen, i, e, w):
    tm = nodes.new("GeometryNodeInputSceneTime").outputs["Seconds"]
    return _plain(nodes, links, geo, gen, i, e, _math(nodes, "MULTIPLY", w, tm, links))


def _target(nodes, links, geo, gen, i, e, w):
    info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"
    if e.b4d_fx_target is not None:
        info.inputs["Object"].default_value = e.b4d_fx_target
    cam = nodes.new("GeometryNodeInputActiveCamera")
    ci = nodes.new("GeometryNodeObjectInfo"); ci.transform_space = "RELATIVE"; links.new(cam.outputs[0], ci.inputs["Object"])
    where = gc.switch(nodes, links, "VECTOR", _math(nodes, "GREATER_THAN", _driven(nodes, e, "b4d_fx_target_mode"), 0.5, links),
                      info.outputs["Location"], ci.outputs["Location"])
    d = gc.vmath(nodes, links, "SUBTRACT", where, gc.position(nodes))
    # a clone's Z (shown) = Blender +Y faces the target, its Y (shown) = Blender +Z stays up
    face = nodes.new("FunctionNodeAlignRotationToVector"); face.axis = "Y"; face.pivot_axis = "AUTO"
    links.new(d, face.inputs["Vector"])
    up = nodes.new("FunctionNodeAlignRotationToVector"); up.axis = "Z"; up.pivot_axis = "Y"
    links.new(face.outputs[0], up.inputs["Rotation"]); up.inputs["Vector"].default_value = (0.0, 0.0, 1.0)
    q = _attr(nodes, "b4d_rot_q", "QUATERNION")
    turned = _mix(nodes, links, "ROTATION", _clamp(nodes, links, w), q, up.outputs[0])
    geo = _store(nodes, links, geo, "b4d_rot_q", "QUATERNION", turned)
    return _apply_visibility(nodes, links, geo, e, w)


def _delay(nodes, links, geo, gen, i, e, w):
    """The clones' state from the effectors above eases toward where they are now (Blend) or springs (Spring)."""
    sim_in = nodes.new("GeometryNodeSimulationInput"); sim_out = nodes.new("GeometryNodeSimulationOutput")
    sim_in.pair_with_output(sim_out)
    links.new(geo, sim_in.inputs["Geometry"])
    prev = sim_in.outputs["Geometry"]
    idx = nodes.new("GeometryNodeInputIndex").outputs[0]

    def before(field, typ):
        s = nodes.new("GeometryNodeSampleIndex"); s.data_type = typ; s.domain = "POINT"
        links.new(prev, s.inputs["Geometry"]); links.new(field, s.inputs["Value"]); links.new(idx, s.inputs["Index"])
        return s.outputs[0]

    # how far each frame closes the gap: full strength = a long lag
    lag = _clamp(nodes, links, _math(nodes, "SUBTRACT", 1.0, _math(nodes, "MULTIPLY", _clamp(nodes, links, w), 0.95, links), links), 0.02, 1.0)
    spring = _math(nodes, "GREATER_THAN", _driven(nodes, e, "b4d_fx_delay_mode"), 0.5, links)
    p_prev, p_now = before(gc.position(nodes), "FLOAT_VECTOR"), gc.position(nodes)
    v_prev = before(_attr(nodes, "b4d_vel", "FLOAT_VECTOR"), "FLOAT_VECTOR")
    eased = _mix(nodes, links, "VECTOR", lag, p_prev, p_now)
    # spring: velocity pulled toward the target and damped
    vel = gc.vmath(nodes, links, "ADD", gc.vmath(nodes, links, "SCALE", v_prev, scale=0.8),
                   gc.vmath(nodes, links, "SCALE", gc.vmath(nodes, links, "SUBTRACT", p_now, p_prev), scale=lag))
    sprung = gc.vmath(nodes, links, "ADD", p_prev, vel)
    newp = gc.switch(nodes, links, "VECTOR", spring, eased, sprung)
    sp = nodes.new("GeometryNodeSetPosition"); links.new(geo, sp.inputs["Geometry"]); links.new(newp, sp.inputs["Position"])
    out = _store(nodes, links, sp.outputs["Geometry"], "b4d_vel", "FLOAT_VECTOR", gc.vmath(nodes, links, "SUBTRACT", newp, p_prev))
    sc = _mix(nodes, links, "VECTOR", lag, before(_attr(nodes, "b4d_scale", "FLOAT_VECTOR"), "FLOAT_VECTOR"), _attr(nodes, "b4d_scale", "FLOAT_VECTOR"))
    out = _store(nodes, links, out, "b4d_scale", "FLOAT_VECTOR", sc)
    rq = _mix(nodes, links, "ROTATION", lag, before(_attr(nodes, "b4d_rot_q", "QUATERNION"), "QUATERNION"), _attr(nodes, "b4d_rot_q", "QUATERNION"))
    out = _store(nodes, links, out, "b4d_rot_q", "QUATERNION", rq)
    links.new(out, sim_out.inputs["Geometry"])
    return sim_out.outputs["Geometry"]


def _vlen(nodes, links, v):
    n = nodes.new("ShaderNodeVectorMath"); n.operation = "LENGTH"; links.new(v, n.inputs[0])
    return n.outputs["Value"]


def _vdist(nodes, links, a, b):
    n = nodes.new("ShaderNodeVectorMath"); n.operation = "DISTANCE"; links.new(a, n.inputs[0]); links.new(b, n.inputs[1])
    return n.outputs["Value"]


def _count(nodes, links, geo):
    """How many clones: points of a point cloud, or of curves (MoSpline)."""
    total = 0.0
    for comp in ("POINTCLOUD", "CURVE"):
        n = nodes.new("GeometryNodeAttributeDomainSize"); n.component = comp
        links.new(geo, n.inputs["Geometry"])
        total = _math(nodes, "ADD", total, n.outputs["Point Count"], links)
    return total


def _formula(nodes, links, geo, gen, i, e, w):
    """The typed formula's value (sin(...) runs -1..1) scales the Parameter tab's change, as Shader's brightness does."""
    from . import formula
    p = gc.separate(nodes, links, gc.vmath(nodes, links, "SCALE", gc.position(nodes), scale=100.0))
    eul = nodes.new("FunctionNodeRotationToEuler"); links.new(_attr(nodes, "b4d_rot_q", "QUATERNION"), eul.inputs[0])
    r = gc.separate(nodes, links, gc.vmath(nodes, links, "SCALE", eul.outputs[0], scale=180.0 / math.pi))
    sc = gc.separate(nodes, links, _attr(nodes, "b4d_scale", "FLOAT_VECTOR"))
    uv = gc.separate(nodes, links, _attr(nodes, "b4d_uv", "FLOAT_VECTOR"))
    fall = falloff(nodes, links, e)
    var = {"id": _attr(nodes, "b4d_index", "INT"), "count": _count(nodes, links, geo),
           "t": _math(nodes, "MULTIPLY", nodes.new("GeometryNodeInputSceneTime").outputs["Seconds"], _driven(nodes, e, "b4d_fx_tscale"), links),
           "f": _driven(nodes, e, "b4d_fx_freq"),
           "falloff": 1.0 if fall is None else fall,
           "px": p["X"], "py": p["Z"], "pz": p["Y"], "rx": r["X"], "ry": r["Z"], "rz": r["Y"],
           "sx": sc["X"], "sy": sc["Z"], "sz": sc["Y"], "u": uv["X"], "v": uv["Y"], "w": 0.0}
    value = formula.build(nodes, links, e.b4d_fx_formula, var)
    if not hasattr(value, "is_output"):
        value = _math(nodes, "ADD", value, 0.0, links)
    pos, sc_, rot = _params(nodes, links, e)
    geo = _apply_transform(nodes, links, geo, _math(nodes, "MULTIPLY", w, value, links), pos, sc_, rot)
    geo = _apply_color(nodes, links, geo, e, _math(nodes, "MULTIPLY", w, value, links))
    return _apply_visibility(nodes, links, geo, e, w)


def _volume(nodes, links, geo, gen, i, e, w):
    """Works only on the clones inside the Volume Object: a ray from the clone leaves through the inside of a face."""
    vol = e.b4d_fx_volume
    if vol is None or vol.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT"):
        inside = 0.0
    else:
        info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"
        info.inputs["Object"].default_value = vol
        real = nodes.new("GeometryNodeRealizeInstances"); links.new(info.outputs["Geometry"], real.inputs["Geometry"])
        votes = 0.0
        for d in ((0.0, 0.0, 1.0), (0.577, 0.577, -0.577), (-0.707, 0.0, -0.707)):     # three rays outvote a seam
            ray = nodes.new("GeometryNodeRaycast")
            links.new(real.outputs["Geometry"], ray.inputs["Target Geometry"])
            ray.inputs["Ray Direction"].default_value = d
            ray.inputs["Ray Length"].default_value = 1e5
            facing = _math(nodes, "GREATER_THAN", gc.dot(nodes, links, ray.outputs["Hit Normal"], d), 0.0, links)
            votes = _math(nodes, "ADD", votes, _math(nodes, "MULTIPLY", ray.outputs["Is Hit"], facing, links), links)
        inside = _math(nodes, "GREATER_THAN", votes, 1.5, links)
    return _plain(nodes, links, geo, gen, i, e, _math(nodes, "MULTIPLY", w, inside, links))


def _push_apart(nodes, links, geo, gen, i, e, w):
    """Each clone has a sphere of Radius x its size. Hide: a clone whose sphere overlaps an earlier kept clone's goes.
    Push Apart: overlapping neighbours step apart, a little more each Iteration (Along X/Y/Z: only along the clone's own
    axis). Scale Apart: overlapping clones shrink until they just touch."""
    mode = _driven(nodes, e, "b4d_fx_push_mode")
    is_mode = lambda m: _math(nodes, "COMPARE", mode, float(m), links)
    pushing = _math(nodes, "GREATER_THAN", _math(nodes, "ADD", is_mode(1), _math(nodes, "GREATER_THAN", mode, 2.5, links), links), 0.5, links)
    ww = _clamp(nodes, links, w)
    idx = nodes.new("GeometryNodeInputIndex").outputs[0]
    R = _math(nodes, "MAXIMUM", _driven(nodes, e, "b4d_fx_radius", "var*0.01"), 1e-5, links)
    size = lambda field: _math(nodes, "MAXIMUM", _math(nodes, "MAXIMUM", gc.separate(nodes, links, field)["X"], gc.separate(nodes, links, field)["Y"], links),
                               gc.separate(nodes, links, field)["Z"], links)
    own_r = _math(nodes, "MULTIPLY", R, size(_attr(nodes, "b4d_scale", "FLOAT_VECTOR")), links)

    def sample(g, field, typ, index):
        s = nodes.new("GeometryNodeSampleIndex"); s.data_type = typ; s.domain = "POINT"
        links.new(g, s.inputs["Geometry"]); links.new(field, s.inputs["Value"]); links.new(index, s.inputs["Index"])
        return s.outputs[0]

    def nearest(g, group=None):
        n = nodes.new("GeometryNodeIndexOfNearest"); links.new(gc.position(nodes), n.inputs["Position"])
        if group is not None:
            links.new(group, n.inputs["Group ID"])
        ni = n.outputs["Index"]
        gap = _math(nodes, "ADD", own_r, _math(nodes, "MULTIPLY", R, size(sample(g, _attr(nodes, "b4d_scale", "FLOAT_VECTOR"), "FLOAT_VECTOR", ni)), links), links)
        return ni, n.outputs["Has Neighbor"], sample(g, gc.position(nodes), "FLOAT_VECTOR", ni), gap

    iters = _driven(nodes, e, "b4d_fx_iterations")
    # Push Apart / Along X, Y, Z
    rin = nodes.new("GeometryNodeRepeatInput"); rout = nodes.new("GeometryNodeRepeatOutput"); rin.pair_with_output(rout)
    links.new(_math(nodes, "MULTIPLY", iters, pushing, links), rin.inputs["Iterations"])
    links.new(geo, rin.inputs["Geometry"])
    g = rin.outputs["Geometry"]
    # every clone is pushed by its nearest neighbour in each of four groups (number mod 4), so a crowd spreads evenly
    # instead of pairs trading places
    K = 4
    cls = _math(nodes, "FLOORED_MODULO", idx, float(K), links)
    jitter = gc.combine(nodes, links, *[_rand(nodes, links, -1e-4, 1e-4, idx, k) for k in (3, 5, 7)])
    q = _attr(nodes, "b4d_rot_q", "QUATERNION")
    axis = nodes.new("FunctionNodeRotateVector"); links.new(q, axis.inputs["Rotation"])
    links.new(gc.index_switch(nodes, links, "VECTOR", _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", mode, 3.0, links), 0.0, links),
                              [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)]), axis.inputs["Vector"])
    same_i, same_has, same_pos, same_gap = nearest(g, cls)               # nearest other clone in its own group
    step = (0.0, 0.0, 0.0)
    for c in range(K):
        part = nodes.new("GeometryNodeSeparateGeometry"); part.domain = "POINT"
        links.new(g, part.inputs["Geometry"]); links.new(_math(nodes, "COMPARE", cls, float(c), links), part.inputs["Selection"])
        sn = nodes.new("GeometryNodeSampleNearest"); sn.domain = "POINT"; links.new(part.outputs["Selection"], sn.inputs["Geometry"])
        opos = sample(part.outputs["Selection"], gc.position(nodes), "FLOAT_VECTOR", sn.outputs["Index"])
        ogap = _math(nodes, "ADD", own_r, _math(nodes, "MULTIPLY", R, size(sample(part.outputs["Selection"], _attr(nodes, "b4d_scale", "FLOAT_VECTOR"), "FLOAT_VECTOR", sn.outputs["Index"])), links), links)
        n_in = nodes.new("GeometryNodeAttributeDomainSize"); n_in.component = "POINTCLOUD"; links.new(part.outputs["Selection"], n_in.inputs["Geometry"])
        mine = _math(nodes, "COMPARE", cls, float(c), links)
        npos = gc.switch(nodes, links, "VECTOR", mine, opos, same_pos)
        gap = gc.switch(nodes, links, "FLOAT", mine, ogap, same_gap)
        has = gc.switch(nodes, links, "FLOAT", mine, _math(nodes, "GREATER_THAN", n_in.outputs["Point Count"], 0.0, links), same_has)
        away = gc.vmath(nodes, links, "ADD", gc.vmath(nodes, links, "SUBTRACT", gc.position(nodes), npos), jitter)   # two on one spot still part
        over = _math(nodes, "MULTIPLY", _math(nodes, "MAXIMUM", _math(nodes, "SUBTRACT", gap, _vlen(nodes, links, away), links), 0.0, links), has, links)
        free = gc.vmath(nodes, links, "NORMALIZE", away)
        # Along an axis: the clone's own X, Y or Z (shown Y = Blender Z), toward the side the neighbour isn't
        side = _math(nodes, "SIGN", gc.dot(nodes, links, away, axis.outputs[0]), None, links)
        side = gc.switch(nodes, links, "FLOAT", _math(nodes, "COMPARE", side, 0.0, links), side, 1.0)
        dirn = gc.switch(nodes, links, "VECTOR", _math(nodes, "GREATER_THAN", mode, 2.5, links), free, gc.vmath(nodes, links, "SCALE", axis.outputs[0], scale=side))
        step = gc.vmath(nodes, links, "ADD", step, gc.vmath(nodes, links, "SCALE", dirn, scale=_math(nodes, "MULTIPLY", over, _math(nodes, "MULTIPLY", ww, 0.5, links), links)))
    sp = nodes.new("GeometryNodeSetPosition"); links.new(g, sp.inputs["Geometry"]); links.new(step, sp.inputs["Offset"])
    links.new(sp.outputs["Geometry"], rout.inputs["Geometry"])
    geo = rout.outputs["Geometry"]
    # Scale Apart: shrink so the spheres just touch
    _ni, has, npos, gap = nearest(geo)
    room = _clamp(nodes, links, _math(nodes, "DIVIDE", _vdist(nodes, links, gc.position(nodes), npos), _math(nodes, "MAXIMUM", gap, 1e-6, links), links))
    room = gc.switch(nodes, links, "FLOAT", has, 1.0, room)
    f = _math(nodes, "MULTIPLY", ww, is_mode(2), links)
    shrink = _math(nodes, "ADD", 1.0, _math(nodes, "MULTIPLY", f, _math(nodes, "SUBTRACT", room, 1.0, links), links), links)
    geo = _store(nodes, links, geo, "b4d_scale", "FLOAT_VECTOR", gc.vmath(nodes, links, "SCALE", _attr(nodes, "b4d_scale", "FLOAT_VECTOR"), scale=shrink))
    # Hide: clone by clone in order, a clone whose sphere overlaps one already kept is hidden (state 0 undecided,
    # 1 kept, 2 hidden). One pass per clone: exact, the same on every computer.
    hin = nodes.new("GeometryNodeRepeatInput"); hout = nodes.new("GeometryNodeRepeatOutput"); hin.pair_with_output(hout)
    on = _math(nodes, "GREATER_THAN", _driven(nodes, e, "b4d_fx_strength"), 0.0, links)     # one value: a pass count can't vary per clone
    links.new(_math(nodes, "MULTIPLY", _count(nodes, links, geo), _math(nodes, "MULTIPLY", is_mode(0), on, links), links), hin.inputs["Iterations"])
    geo = _store(nodes, links, geo, "b4d_push_st", "INT", _math(nodes, "MULTIPLY", idx, 0.0, links))
    links.new(geo, hin.inputs["Geometry"])
    g = hin.outputs["Geometry"]
    k = hin.outputs["Iteration"]
    kept = nodes.new("GeometryNodeSeparateGeometry"); kept.domain = "POINT"
    links.new(g, kept.inputs["Geometry"]); links.new(_math(nodes, "COMPARE", _attr(nodes, "b4d_push_st", "INT"), 1.0, links), kept.inputs["Selection"])
    kg = kept.outputs["Selection"]
    here = sample(g, gc.position(nodes), "FLOAT_VECTOR", k)
    my_r = _math(nodes, "MULTIPLY", R, size(sample(g, _attr(nodes, "b4d_scale", "FLOAT_VECTOR"), "FLOAT_VECTOR", k)), links)
    near = nodes.new("GeometryNodeSampleNearest"); near.domain = "POINT"; links.new(kg, near.inputs["Geometry"]); links.new(here, near.inputs["Sample Position"])
    kpos = sample(kg, gc.position(nodes), "FLOAT_VECTOR", near.outputs["Index"])
    kgap = _math(nodes, "ADD", my_r, _math(nodes, "MULTIPLY", R, size(sample(kg, _attr(nodes, "b4d_scale", "FLOAT_VECTOR"), "FLOAT_VECTOR", near.outputs["Index"])), links), links)
    cnt = nodes.new("GeometryNodeAttributeDomainSize"); cnt.component = "POINTCLOUD"; links.new(kg, cnt.inputs["Geometry"])
    hit = _math(nodes, "MULTIPLY", _math(nodes, "LESS_THAN", _vdist(nodes, links, here, kpos), kgap, links),
                _math(nodes, "GREATER_THAN", cnt.outputs["Point Count"], 0.0, links), links)
    st = nodes.new("GeometryNodeStoreNamedAttribute"); st.data_type = "INT"; st.domain = "POINT"
    links.new(g, st.inputs["Geometry"]); st.inputs["Name"].default_value = "b4d_push_st"
    links.new(_math(nodes, "COMPARE", idx, k, links), st.inputs["Selection"])
    links.new(_math(nodes, "ADD", 1.0, hit, links), st.inputs["Value"])
    links.new(st.outputs["Geometry"], hout.inputs["Geometry"])
    geo = hout.outputs["Geometry"]
    gone = _math(nodes, "COMPARE", _attr(nodes, "b4d_push_st", "INT"), 2.0, links)
    geo = _store(nodes, links, geo, "b4d_hidden", "FLOAT", _math(nodes, "MAXIMUM", _attr(nodes, "b4d_hidden", "FLOAT"), gone, links))
    for name in ("b4d_push_st",):
        rm = nodes.new("GeometryNodeRemoveAttribute"); links.new(geo, rm.inputs["Geometry"]); rm.inputs["Name"].default_value = name
        geo = rm.outputs["Geometry"]
    return geo


def _nested(nodes, links, geo, gen, e, w, depth):
    """The effectors in a Group's or ReEffector's own list, each as strong as its own settings x w."""
    for j, entry in effectors_of(e):
        c = entry.obj
        if c == e or depth > 4:
            continue
        cw = _math(nodes, "MULTIPLY", _weight(nodes, links, e, j, c), w, links)
        geo = apply_one(nodes, links, geo, gen, j, c, cw, depth + 1)
    return geo


def _group(nodes, links, geo, gen, i, e, w, depth=0):
    return _nested(nodes, links, geo, gen, e, w, depth)


BASE = (("position", "b4d_base_p", "FLOAT_VECTOR"), ("b4d_scale", "b4d_base_s", "FLOAT_VECTOR"), ("b4d_rot_q", "b4d_base_r", "QUATERNION"),
        ("b4d_color", "b4d_base_c", "FLOAT_COLOR"), ("b4d_weight", "b4d_base_w", "FLOAT"), ("b4d_hidden", "b4d_base_h", "FLOAT"))


def _has_reeffector(owner, depth=0, lst="b4d_fx_list"):
    for _j, entry in effectors_of(owner, lst):
        if entry.obj["b4d_type"] == "fx_reeffector" or (entry.obj["b4d_type"] in NESTS and depth < 4 and entry.obj != owner
                                                         and _has_reeffector(entry.obj, depth + 1)):
            return True
    return False


def keep_base(nodes, links, geo):
    """The clones' state before any effector, for a ReEffector to start its own effectors from."""
    for name, base, typ in BASE:
        geo = _store(nodes, links, geo, base, typ, gc.position(nodes) if name == "position" else _attr(nodes, name, typ))
    return geo


def _reeffector(nodes, links, geo, gen, i, e, w, depth=0):
    """Inside its fields, each switched-on part (Position, Scale, Rotation, Color, Weight, Visibility) of the effectors
    above it is taken back and its own effectors' result, started from the clones' first state, put in instead; the
    part's Strength blends between the two."""
    start = nodes.new("GeometryNodeSetPosition"); links.new(geo, start.inputs["Geometry"]); links.new(_attr(nodes, "b4d_base_p", "FLOAT_VECTOR"), start.inputs["Position"])
    b = start.outputs["Geometry"]
    for name, base, typ in BASE[1:]:
        b = _store(nodes, links, b, name, typ, _attr(nodes, base, typ))
    own = _nested(nodes, links, b, gen, e, 1.0, depth)
    idx = nodes.new("GeometryNodeInputIndex").outputs[0]

    def theirs(field, typ):
        s = nodes.new("GeometryNodeSampleIndex"); s.data_type = typ; s.domain = "POINT"
        links.new(own, s.inputs["Geometry"]); links.new(field, s.inputs["Value"]); links.new(idx, s.inputs["Index"])
        return s.outputs[0]

    ww = _clamp(nodes, links, w, -10.0, 10.0)

    def amount(key, slot, axes=False):
        f = _math(nodes, "MULTIPLY", ww, _math(nodes, "MULTIPLY", _driven(nodes, e, f"b4d_fx_re_on[{slot}]"), _driven(nodes, e, f"b4d_fx_ch_{key}", "var*0.01"), links), links)
        if not axes:
            return f
        a = [_driven(nodes, e, f"b4d_fx_ch_{key}_{ch}", "var*0.01") for ch in ("rgb" if key == "color" else "xyz")]
        if key in ("pos", "scale", "rot"):
            a = [a[0], a[2], a[1]]                                   # shown X, Y, Z -> Blender X, Y (shown Z), Z (shown Y)
        return gc.vmath(nodes, links, "SCALE", gc.combine(nodes, links, *a), scale=f)

    def vmix(f, a, b_):
        m = nodes.new("ShaderNodeMix"); m.data_type = "VECTOR"; m.factor_mode = "NON_UNIFORM"
        links.new(f, m.inputs[1]); links.new(a, m.inputs[4]); links.new(b_, m.inputs[5])
        return m.outputs[1]

    sp = nodes.new("GeometryNodeSetPosition"); links.new(geo, sp.inputs["Geometry"])
    links.new(vmix(amount("pos", 0, True), gc.position(nodes), theirs(gc.position(nodes), "FLOAT_VECTOR")), sp.inputs["Position"])
    geo = sp.outputs["Geometry"]
    sc = _attr(nodes, "b4d_scale", "FLOAT_VECTOR")
    geo = _store(nodes, links, geo, "b4d_scale", "FLOAT_VECTOR", vmix(amount("scale", 1, True), sc, theirs(sc, "FLOAT_VECTOR")))
    q = _attr(nodes, "b4d_rot_q", "QUATERNION")
    e1 = nodes.new("FunctionNodeRotationToEuler"); links.new(q, e1.inputs[0])
    e2 = nodes.new("FunctionNodeRotationToEuler"); links.new(theirs(q, "QUATERNION"), e2.inputs[0])
    geo = _store(nodes, links, geo, "b4d_rot_q", "QUATERNION", _euler(nodes, links, vmix(amount("rot", 2, True), e1.outputs[0], e2.outputs[0])))
    col = _attr(nodes, "b4d_color", "FLOAT_COLOR")
    cv = vmix(amount("color", 3, True), col, theirs(col, "FLOAT_COLOR"))
    cc = gc.separate(nodes, links, cv); cc_n = nodes.new("FunctionNodeCombineColor")
    for k, ch in enumerate(("X", "Y", "Z")):
        links.new(cc[ch], cc_n.inputs[k])
    cc_n.inputs["Alpha"].default_value = 1.0
    geo = _store(nodes, links, geo, "b4d_color", "FLOAT_COLOR", cc_n.outputs[0])
    for key, slot, name in (("weight", 4, "b4d_weight"), ("vis", 5, "b4d_hidden")):
        v = _attr(nodes, name, "FLOAT")
        geo = _store(nodes, links, geo, name, "FLOAT", _mix(nodes, links, "FLOAT", _clamp(nodes, links, amount(key, slot)), v, theirs(v, "FLOAT")))
    return geo


def _spline(nodes, links, geo, gen, i, e, w):
    from . import moclone_fx_more
    return moclone_fx_more.spline(nodes, links, geo, gen, i, e, w)


def _inherit(nodes, links, geo, gen, i, e, w):
    from . import moclone_fx_more
    return moclone_fx_more.inherit(nodes, links, geo, gen, i, e, w)


def _sound(nodes, links, geo, gen, i, e, w):
    from . import moclone_fx_more
    return moclone_fx_more.sound(nodes, links, geo, gen, i, e, w)


APPLY = {"fx_plain": _plain, "fx_random": _random, "fx_shader": _shader, "fx_step": _step, "fx_delay": _delay,
         "fx_target": _target, "fx_time": _time, "fx_formula": _formula, "fx_volume": _volume, "fx_pushapart": _push_apart,
         "fx_spline": _spline, "fx_inherit": _inherit, "fx_sound": _sound}


def apply_one(nodes, links, geo, gen, i, e, w, depth=0):
    """One effector. Its strength per clone is read once, where the clone is before it moves: the fields would
    otherwise be read again after the move, and a clone pushed out of a field would lose the rest of the effect."""
    k = e["b4d_type"]
    if hasattr(w, "is_output"):
        name = f"b4d_w{depth}"
        geo = _store(nodes, links, geo, name, "FLOAT", w)
        w = _attr(nodes, name, "FLOAT")
    if k == "fx_group":
        return _group(nodes, links, geo, gen, i, e, w, depth)
    if k == "fx_reeffector":
        return _reeffector(nodes, links, geo, gen, i, e, w, depth)
    return APPLY[k](nodes, links, geo, gen, i, e, w)



def effect_fn(gen, lst="b4d_fx_list", drop_hidden=True):
    """geo -> geo through the Cloner's effectors in list order; hidden clones go at the end (drop_hidden False: they
    keep b4d_hidden = 1, for generators that hide pieces themselves)."""
    def effect(nodes, links, geo):
        items = effectors_of(gen, lst)
        from . import field_tags
        geo = field_tags.clone_tags(nodes, links, gen, geo)            # MoClone Weightmap and Selection
        if not items:
            return geo
        geo = _store(nodes, links, geo, "b4d_hidden", "FLOAT", nodes.new("ShaderNodeValue").outputs[0])
        if _has_reeffector(gen, 0, lst):
            geo = keep_base(nodes, links, geo)
        for i, entry in items:
            e = entry.obj
            w = _weight(nodes, links, gen, i, e, lst)
            from . import field_tags
            if field_tags.has(gen, "MG_WEIGHT"):                       # each clone's weight scales the effector
                w = _math(nodes, "MULTIPLY", w, _attr(nodes, "b4d_weight", "FLOAT"), links)
            if field_tags.has(gen, "MG_SEL") and e.b4d_fx_use_sel:     # Selection: only the selected clones
                w = _math(nodes, "MULTIPLY", w, _attr(nodes, "b4d_sel", "FLOAT"), links)
            geo = apply_one(nodes, links, geo, gen, i, e, w)
        if not drop_hidden:
            return geo
        drop = nodes.new("GeometryNodeDeleteGeometry"); drop.domain = "POINT"
        links.new(geo, drop.inputs["Geometry"]); links.new(_math(nodes, "GREATER_THAN", _attr(nodes, "b4d_hidden", "FLOAT"), 0.5, links), drop.inputs["Selection"])
        return drop.outputs["Geometry"]
    return effect
