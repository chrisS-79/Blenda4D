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
             "fx_time": ("Time", "Changes clones more and more as time goes on")}
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
SHADER_SOURCES = [("NOISE", "Noise", "A noise pattern", 0), ("IMAGE", "Image", "An image, laid over the clones by their U and V", 1)]
AXES = [("XP", "+X", "", 0), ("XN", "-X", "", 1), ("YP", "+Y", "", 2), ("YN", "-Y", "", 3), ("ZP", "+Z", "", 4), ("ZN", "-Z", "", 5)]


def is_effector(ob):
    return ob is not None and ob.get("b4d_type") in EFFECTORS


def is_field(ob):
    return ob is not None and ob.get("b4d_type") in FIELDS


def effectors_of(gen):
    return [(i, e) for i, e in enumerate(getattr(gen, "b4d_fx_list", [])) if is_effector(e.obj)]


def fields_of(eff):
    return [(i, f) for i, f in enumerate(getattr(eff, "b4d_field_list", [])) if is_field(f.obj)]


def signature(gen):
    """What shapes the Cloner's nodes: its effectors and their fields, in order."""
    out = [f"bare:{c.name}" for c in gen.children if not any(sl.material for sl in getattr(c, "material_slots", []))]
    from . import field_tags
    out += field_tags.clone_tag_signature(gen) + [f"sel:{getattr(e.obj, 'b4d_fx_use_sel', False)}" for _i, e in effectors_of(gen)]
    for i, e in effectors_of(gen):
        tgt, img = getattr(e.obj, "b4d_fx_target", None), getattr(e.obj, "b4d_fx_image", None)
        out.append(f"{i}:{e.obj.name}:{e.obj['b4d_type']}:{tgt.name if tgt else ''}:{img.name if img else ''}")
        for j, f in fields_of(e.obj):
            out.append(f"  {j}:{f.obj.name}:{f.obj['b4d_type']}")
    return out


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
    """The Parameter tab: position (cm), scale (fraction, 0 = no change), rotation (radians), as Blender vectors."""
    pos = gc.vmath(nodes, links, "SCALE", _vec(nodes, links, e, "b4d_fx_pos", "var*0.01"), scale=_driven(nodes, e, "b4d_fx_pos_on"))
    uni = _driven(nodes, e, "b4d_fx_uniform")
    us = _driven(nodes, e, "b4d_fx_uscale", "var*0.01")
    sc = gc.switch(nodes, links, "VECTOR", _math(nodes, "GREATER_THAN", uni, 0.5, links),
                   _vec(nodes, links, e, "b4d_fx_scale", "var*0.01"), gc.combine(nodes, links, us, us, us))
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


def _weight(nodes, links, gen, i, e):
    """Strength x the list's own strength and switch x (Minimum..Maximum over the fields' value)."""
    fall = falloff(nodes, links, e)
    lo = _driven(nodes, e, "b4d_fx_min", "var*0.01")
    hi = _driven(nodes, e, "b4d_fx_max", "var*0.01")
    v = hi if fall is None else _math(nodes, "ADD", lo, _math(nodes, "MULTIPLY", _math(nodes, "SUBTRACT", hi, lo, links), fall, links), links)
    s = _math(nodes, "MULTIPLY", _driven(nodes, e, "b4d_fx_strength", "var*0.01"),
              _math(nodes, "MULTIPLY", _driven(nodes, gen, f"b4d_fx_list[{i}].strength", "var*0.01"), _driven(nodes, gen, f"b4d_fx_list[{i}].on"), links), links)
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


APPLY = {"fx_plain": _plain, "fx_random": _random, "fx_shader": _shader, "fx_step": _step, "fx_delay": _delay,
         "fx_target": _target, "fx_time": _time}


def effect_fn(gen):
    """geo -> geo through the Cloner's effectors in list order; hidden clones go at the end."""
    def effect(nodes, links, geo):
        items = effectors_of(gen)
        from . import field_tags
        geo = field_tags.clone_tags(nodes, links, gen, geo)            # MoClone Weightmap and Selection
        if not items:
            return geo
        geo = _store(nodes, links, geo, "b4d_hidden", "FLOAT", nodes.new("ShaderNodeValue").outputs[0])
        for i, entry in items:
            e = entry.obj
            w = _weight(nodes, links, gen, i, e)
            from . import field_tags
            if field_tags.has(gen, "MG_WEIGHT"):                       # each clone's weight scales the effector
                w = _math(nodes, "MULTIPLY", w, _attr(nodes, "b4d_weight", "FLOAT"), links)
            if field_tags.has(gen, "MG_SEL") and e.b4d_fx_use_sel:     # Selection: only the selected clones
                w = _math(nodes, "MULTIPLY", w, _attr(nodes, "b4d_sel", "FLOAT"), links)
            geo = APPLY[e["b4d_type"]](nodes, links, geo, gen, i, e, w)
        drop = nodes.new("GeometryNodeDeleteGeometry"); drop.domain = "POINT"
        links.new(geo, drop.inputs["Geometry"]); links.new(_math(nodes, "GREATER_THAN", _attr(nodes, "b4d_hidden", "FLOAT"), 0.5, links), drop.inputs["Selection"])
        return drop.outputs["Geometry"]
    return effect
