# SPDX-License-Identifier: GPL-3.0-or-later
"""The node trees behind the deformers.

Each deformer owns one Geometry Nodes tree. Every object it bends carries a modifier that uses that tree, so its
settings live in one place: value nodes inside the tree, each driven by one of the deformer's own properties (so
keyframes on the deformer's page animate the effect). The tree's inputs say which deformer it serves and whether it
is drawing the deformer's own box.

Box deformers (bend, twist, taper, bulge, shear) work in the deformer's space: its local Z is the height of the box,
v runs from 0 at the bottom of the box to 1 at the top."""
import math

import bpy

SCALE = 0.01                                    # page values are in centimetres, geometry in metres
LIMITED, WITHIN, UNLIMITED = 0, 1, 2            # b4d_def_mode
BOTTOM, CENTER, CENTER_S, TOP = 0, 1, 2, 3      # b4d_def_origin
NEAREST, NORMAL, AXIS = 0, 1, 2                 # b4d_def_wrap_mode
LINEAR, RIPPLE = 0, 1                           # b4d_def_shape
BOX_STEPS = 32                                  # points along each upright edge of the drawn box


class G:
    """A small helper for writing math as nodes."""

    def __init__(self, tree):
        self.t, self.n, self.l = tree, tree.nodes, tree.links

    def put(self, a, sock):
        if isinstance(a, bpy.types.NodeSocket):
            self.l.new(a, sock)
        else:
            sock.default_value = a

    def m(self, op, a, b=None, c=None):
        n = self.n.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.put(v, n.inputs[i])
        return n.outputs[0]

    def add(self, a, b):
        return self.m("ADD", a, b)

    def sub(self, a, b):
        return self.m("SUBTRACT", a, b)

    def mul(self, a, b):
        return self.m("MULTIPLY", a, b)

    def div(self, a, b):
        return self.m("DIVIDE", a, b)

    def sep(self, v):
        n = self.n.new("ShaderNodeSeparateXYZ")
        self.put(v, n.inputs[0])
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def comb(self, x, y, z):
        n = self.n.new("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.put(v, n.inputs[i])
        return n.outputs[0]

    def vec(self, op, a, b=None, scale=None, out=0):
        n = self.n.new("ShaderNodeVectorMath")
        n.operation = op
        self.put(a, n.inputs[0])
        if b is not None:
            self.put(b, n.inputs[1])
        if scale is not None:
            self.put(scale, n.inputs["Scale"])
        return n.outputs[out]

    def eq(self, a, b):
        return self.cmp("EQUAL", a, b)

    def cmp(self, op, a, b):
        n = self.n.new("FunctionNodeCompare")
        n.data_type = "FLOAT"
        n.operation = op
        self.put(a, n.inputs[0])
        self.put(b, n.inputs[1])
        return n.outputs[0]

    def logic(self, op, a, b=None):
        n = self.n.new("FunctionNodeBooleanMath")
        n.operation = op
        self.put(a, n.inputs[0])
        if b is not None:
            self.put(b, n.inputs[1])
        return n.outputs[0]

    def pick(self, cond, no, yes, kind="FLOAT"):
        """yes where cond is true, otherwise no."""
        n = self.n.new("GeometryNodeSwitch")
        n.input_type = kind
        self.put(cond, n.inputs["Switch"])
        self.put(no, n.inputs["False"])
        self.put(yes, n.inputs["True"])
        return n.outputs[0]

    def mix(self, a, b, t):
        n = self.n.new("ShaderNodeMix")
        n.data_type = "VECTOR"
        self.put(t, n.inputs[0])
        self.put(a, n.inputs[4])
        self.put(b, n.inputs[5])
        return n.outputs[1]

    def clamp(self, v, lo, hi):
        return self.m("MINIMUM", self.m("MAXIMUM", v, lo), hi)


def _driven(tree, ob, name, path):
    """A value node whose number follows ob.<path> (a driver, so keyframes on the deformer animate it)."""
    n = tree.nodes.new("ShaderNodeValue")
    n.name = n.label = name
    fc = n.outputs[0].driver_add("default_value")
    d = fc.driver
    d.type = "AVERAGE"
    var = d.variables.new()
    var.name = "v"
    var.type = "SINGLE_PROP"
    var.targets[0].id_type = "OBJECT"
    var.targets[0].id = ob
    key, _, index = path.partition("[")
    var.targets[0].data_path = f'["{key}"]' + ("[" + index if index else "")      # a custom property: works without the add-on
    return n.outputs[0]


def retarget(tree, ob):
    """A copied deformer's tree: point its drivers (and its own-object references) at the copy."""
    if tree.animation_data:
        for fc in tree.animation_data.drivers:
            for var in fc.driver.variables:
                for t in var.targets:
                    t.id = ob


# --- the box deformers, in the deformer's space ------------------------------------------------------------------
def _shape(g, P, v):
    """0 at the bottom to 1 at the top, eased by Soft Ends and bent by Curvature."""
    eased = g.mul(g.mul(v, v), g.sub(3.0, g.mul(v, 2.0)))
    base = g.pick(P["fillet"], v, eased)
    power = g.add(1.0, g.div(P["curvature"], 100.0))
    return g.mul(g.m("SIGN", base), g.m("POWER", g.m("ABSOLUTE", base), power))


def _bend(g, P, x, y, z, h, v):
    T, d = P["angle"], P["direction"]
    cd, sd = g.m("COSINE", d), g.m("SINE", d)
    u = g.add(g.mul(x, cd), g.mul(y, sd))
    w = g.sub(g.mul(y, cd), g.mul(x, sd))
    o = P["origin"]
    half = g.mul(h, 0.5)
    is_bottom, is_top = g.eq(o, BOTTOM), g.eq(o, TOP)
    centred = g.logic("NOR", is_bottom, is_top)
    below = g.cmp("LESS_THAN", z, 0.0)
    # s: which way the bend runs from its start; z0: where it starts; L: how long it is; m: S shape mirrors one half
    s = g.pick(is_top, g.pick(centred, 1.0, g.pick(below, 1.0, -1.0)), -1.0)
    z0 = g.pick(is_bottom, g.pick(is_top, 0.0, half), g.mul(half, -1.0))
    L = g.pick(centred, h, half)
    m = g.pick(g.logic("AND", g.eq(o, CENTER_S), below), 1.0, -1.0)
    t = g.mul(s, g.sub(z, z0))
    um = g.mul(m, u)
    tb = g.pick(g.eq(P["mode"], UNLIMITED), g.clamp(t, 0.0, L), t)
    rest = g.sub(t, tb)
    tiny = g.cmp("LESS_THAN", g.m("ABSOLUTE", T), 1e-5)
    safe = g.pick(tiny, T, 1e-5)
    k = g.div(safe, h)                                  # turn per metre along the bend
    region = g.mul(k, L)                                # how far this part turns in all
    stretch = g.div(g.mul(region, 0.5), g.m("SINE", g.mul(region, 0.5)))      # off: the ends keep their distance
    R = g.mul(g.div(1.0, k), g.pick(P["keep"], stretch, 1.0))
    phi = g.mul(tb, k)
    r = g.sub(R, um)
    cp, sp = g.m("COSINE", phi), g.m("SINE", phi)
    u2 = g.add(g.sub(R, g.mul(r, cp)), g.mul(rest, sp))
    t2 = g.add(g.mul(r, sp), g.mul(rest, cp))
    z2 = g.add(z0, g.mul(s, t2))
    u3 = g.mul(m, u2)
    bent = g.comb(g.sub(g.mul(u3, cd), g.mul(w, sd)), g.add(g.mul(u3, sd), g.mul(w, cd)), z2)
    return g.pick(tiny, bent, g.comb(x, y, z), "VECTOR")


def _twist(g, P, x, y, z, h, v):
    a = g.mul(P["angle"], v)
    c, s = g.m("COSINE", a), g.m("SINE", a)
    return g.comb(g.sub(g.mul(x, c), g.mul(y, s)), g.add(g.mul(x, s), g.mul(y, c)), z)


def _taper(g, P, x, y, z, h, v):
    f = g.sub(1.0, g.mul(g.div(P["strength"], 100.0), _shape(g, P, v)))
    return g.comb(g.mul(x, f), g.mul(y, f), z)


def _bulge(g, P, x, y, z, h, v):
    wave = g.m("SINE", g.mul(v, math.pi))
    wave = g.pick(P["fillet"], wave, g.mul(wave, wave))
    power = g.div(1.0, g.add(1.0, g.div(P["curvature"], 100.0)))
    wave = g.mul(g.m("SIGN", wave), g.m("POWER", g.m("ABSOLUTE", wave), power))
    f = g.add(1.0, g.mul(g.div(P["strength"], 100.0), wave))
    return g.comb(g.mul(x, f), g.mul(y, f), z)


def _shear(g, P, x, y, z, h, v):
    amount = g.mul(g.mul(h, g.div(P["strength"], 100.0)), _shape(g, P, v))
    d = P["direction"]
    return g.comb(g.add(x, g.mul(amount, g.m("COSINE", d))), g.add(y, g.mul(amount, g.m("SINE", d))), z)


def _wave(g, P, pos):
    x, y, z = g.sep(pos)
    dist = g.pick(g.eq(P["shape"], RIPPLE), x, g.vec("LENGTH", g.comb(x, y, 0.0), out=1))
    length = g.m("MAXIMUM", g.mul(P["wavelength"], SCALE), 1e-4)
    time = g.n.new("GeometryNodeInputSceneTime").outputs["Seconds"]
    cycles = g.sub(g.div(dist, length), g.mul(P["speed"], time))
    arg = g.add(g.mul(cycles, 2 * math.pi), P["phase"])
    return g.comb(x, y, g.add(z, g.mul(g.mul(P["height"], SCALE), g.m("SINE", arg))))


BOX = {"bend": _bend, "twist": _twist, "taper": _taper, "bulge": _bulge, "shear": _shear}

# kind -> [(value name in the tree, deformer setting)] ; vectors list each component
_SIZE = [("size_x", "b4d_def_size[0]"), ("size_y", "b4d_def_size[1]"), ("size_z", "b4d_def_size[2]"), ("mode", "b4d_def_mode")]
VALUES = {
    "bend": _SIZE + [("angle", "b4d_def_angle"), ("direction", "b4d_def_direction"), ("keep", "b4d_def_keep"), ("origin", "b4d_def_origin")],
    "twist": _SIZE + [("angle", "b4d_def_angle")],
    "taper": _SIZE + [("strength", "b4d_def_strength"), ("curvature", "b4d_def_curvature"), ("fillet", "b4d_def_fillet")],
    "bulge": _SIZE + [("strength", "b4d_def_strength"), ("curvature", "b4d_def_curvature"), ("fillet", "b4d_def_fillet")],
    "shear": _SIZE + [("strength", "b4d_def_strength"), ("direction", "b4d_def_direction"), ("curvature", "b4d_def_curvature"),
                      ("fillet", "b4d_def_fillet")],
    "wave": [("height", "b4d_def_height"), ("wavelength", "b4d_def_wavelength"), ("speed", "b4d_def_speed"),
             ("phase", "b4d_def_phase"), ("shape", "b4d_def_shape")],
    "displace": [("height", "b4d_def_height"), ("noise_size", "b4d_def_noise_size"), ("detail", "b4d_def_detail"),
                 ("seed", "b4d_def_seed"), ("speed", "b4d_def_speed"), ("along", "b4d_def_along")],
    "shrinkwrap": [("strength", "b4d_def_strength"), ("wrap_mode", "b4d_def_wrap_mode"), ("distance", "b4d_def_distance")],
    "smooth": [("strength", "b4d_def_strength"), ("iterations", "b4d_def_iterations")],
}
DEFORMER_SPACE = ("bend", "twist", "taper", "bulge", "shear", "wave")       # the effect moves with the deformer


def interface(tree):
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Deformer", in_out="INPUT", socket_type="NodeSocketObject")
    tree.interface.new_socket("Own Box", in_out="INPUT", socket_type="NodeSocketBool")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")


def socket_id(tree, name):
    return tree.interface.items_tree[name].identifier


def build(ob, kind, label):
    tree = bpy.data.node_groups.new("Blenda " + label, "GeometryNodeTree")
    tree.is_modifier = True
    tree["b4d_deformer"] = kind
    interface(tree)
    fill(tree, ob, kind)
    from .node_arrange import arrange
    arrange(tree)                                                # readable in the node editor, not a pile
    return tree


def fill(tree, ob, kind):
    from . import moclone_deform
    if kind in moclone_deform.FILL:                  # PolyFX and MoExtrude build their own trees
        moclone_deform.FILL[kind](tree, ob)
        return
    g = G(tree)
    gin, gout = g.n.new("NodeGroupInput"), g.n.new("NodeGroupOutput")
    gout.is_active_output = True
    P = {name: _driven(tree, ob, name, path) for name, path in VALUES[kind]}
    geometry = gin.outputs["Geometry"]
    pos = g.n.new("GeometryNodeInputPosition").outputs[0]
    info = g.n.new("GeometryNodeObjectInfo")
    info.name = "Deformer"
    info.transform_space = "RELATIVE"
    g.l.new(gin.outputs["Deformer"], info.inputs["Object"])
    own = gin.outputs["Own Box"]
    ident = g.n.new("FunctionNodeCombineTransform").outputs[0]
    M = g.pick(own, info.outputs["Transform"], ident, "MATRIX")             # the deformer's space in this object's
    inv = g.n.new("FunctionNodeInvertMatrix")
    g.l.new(M, inv.inputs[0])
    there = g.vec("LENGTH", info.outputs["Scale"], out=1)
    present = g.logic("OR", own, g.cmp("GREATER_THAN", there, 0.0))       # deformer deleted: leave the object alone

    def to_local(p):
        n = g.n.new("FunctionNodeTransformPoint")
        g.put(p, n.inputs["Vector"])
        g.l.new(inv.outputs[0], n.inputs["Transform"])
        return n.outputs[0]

    def to_object(p):
        n = g.n.new("FunctionNodeTransformPoint")
        g.put(p, n.inputs["Vector"])
        g.l.new(M, n.inputs["Transform"])
        return n.outputs[0]

    if kind in BOX:
        size = g.comb(g.mul(P["size_x"], SCALE), g.mul(P["size_y"], SCALE), g.mul(P["size_z"], SCALE))
        local = g.pick(own, to_local(pos), g.vec("MULTIPLY", pos, size), "VECTOR")   # the drawn box is a unit cube
        x, y, z = g.sep(local)
        sx, sy, sz = g.sep(size)
        h = g.m("MAXIMUM", sz, 1e-6)
        raw = g.div(g.add(z, g.mul(h, 0.5)), h)
        v = g.pick(g.eq(P["mode"], UNLIMITED), g.clamp(raw, 0.0, 1.0), raw)
        moved = BOX[kind](g, P, x, y, z, h, v)
        inside = g.logic("AND", g.logic("AND", g.cmp("LESS_EQUAL", g.m("ABSOLUTE", x), g.mul(sx, 0.5001)),
                                        g.cmp("LESS_EQUAL", g.m("ABSOLUTE", y), g.mul(sy, 0.5001))),
                         g.logic("AND", g.cmp("GREATER_EQUAL", raw, -1e-4), g.cmp("LESS_EQUAL", raw, 1.0001)))
        hold = g.logic("AND", g.eq(P["mode"], WITHIN), g.logic("NOT", inside))
        moved = g.pick(hold, moved, local, "VECTOR")
        new = g.pick(own, to_object(moved), moved, "VECTOR")
    elif kind == "wave":
        new = to_object(_wave(g, P, to_local(pos)))
    elif kind == "displace":
        new = _displace(g, P, pos, to_local(pos), M)
    elif kind == "shrinkwrap":
        new = _shrinkwrap(g, P, pos, M, ob)
    elif kind == "smooth":
        new = _smooth(g, P, pos)
    else:
        new = pos
    new = g.pick(present, pos, new, "VECTOR")
    sp = g.n.new("GeometryNodeSetPosition")
    g.l.new(geometry, sp.inputs["Geometry"])
    g.put(new, sp.inputs["Position"])
    g.l.new(sp.outputs[0], gout.inputs[0])
    _arrange(tree)


def _displace(g, P, pos, local, M):
    noise = g.n.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "4D"
    scale = g.m("MAXIMUM", g.mul(P["noise_size"], SCALE), 1e-4)
    g.put(g.vec("DIVIDE", local, g.comb(scale, scale, scale)), noise.inputs["Vector"])
    time = g.n.new("GeometryNodeInputSceneTime").outputs["Seconds"]
    g.put(g.add(g.mul(P["seed"], 7.31), g.mul(P["speed"], time)), noise.inputs["W"])
    noise.inputs["Scale"].default_value = 1.0
    g.put(P["detail"], noise.inputs["Detail"])
    amount = g.mul(g.mul(g.sub(noise.outputs["Factor"], 0.5), 2.0), g.mul(P["height"], SCALE))
    normal = g.n.new("GeometryNodeInputNormal").outputs[0]
    up = g.n.new("FunctionNodeTransformDirection")
    up.inputs["Direction"].default_value = (0.0, 0.0, 1.0)
    g.l.new(M, up.inputs["Transform"])
    axis = g.vec("NORMALIZE", up.outputs[0])
    d = g.pick(g.eq(P["along"], 1), normal, axis, "VECTOR")
    return g.vec("ADD", pos, g.vec("SCALE", d, scale=amount))


def target_info(tree):
    return tree.nodes.get("Target")


def _shrinkwrap(g, P, pos, M, ob):
    info = g.n.new("GeometryNodeObjectInfo")
    info.name = "Target"
    info.transform_space = "RELATIVE"
    t = ob.get("b4d_def_target")
    info.inputs["Object"].default_value = t if isinstance(t, bpy.types.Object) else None
    surface = info.outputs["Geometry"]
    near = g.n.new("GeometryNodeProximity")
    near.target_element = "FACES"
    g.l.new(surface, near.inputs["Geometry"])
    g.put(pos, near.inputs["Sample Position"])
    normal = g.n.new("GeometryNodeInputNormal").outputs[0]
    down = g.n.new("FunctionNodeTransformDirection")
    down.inputs["Direction"].default_value = (0.0, 0.0, -1.0)
    g.l.new(M, down.inputs["Transform"])
    dirn = g.pick(g.eq(P["wrap_mode"], AXIS), normal, g.vec("NORMALIZE", down.outputs[0]), "VECTOR")

    def cast(direction):
        n = g.n.new("GeometryNodeRaycast")
        g.l.new(surface, n.inputs["Target Geometry"])
        g.put(pos, n.inputs["Source Position"])
        g.put(direction, n.inputs["Ray Direction"])
        n.inputs["Ray Length"].default_value = 1e5
        return n
    fwd, back = cast(dirn), cast(g.vec("SCALE", dirn, scale=-1.0))
    fd, bd = fwd.outputs["Hit Distance"], back.outputs["Hit Distance"]
    use_back = g.logic("AND", back.outputs["Is Hit"],
                       g.logic("OR", g.logic("NOT", fwd.outputs["Is Hit"]), g.cmp("LESS_THAN", bd, fd)))
    cast_hit = g.logic("OR", fwd.outputs["Is Hit"], back.outputs["Is Hit"])
    cast_pos = g.pick(use_back, fwd.outputs["Hit Position"], back.outputs["Hit Position"], "VECTOR")
    cast_dist = g.pick(use_back, fd, bd)
    nearest = g.eq(P["wrap_mode"], NEAREST)
    hit = g.pick(nearest, cast_hit, near.outputs["Is Valid"], "BOOLEAN")
    where = g.pick(nearest, cast_pos, near.outputs["Position"], "VECTOR")
    dist = g.pick(nearest, cast_dist, near.outputs["Distance"])
    limit = g.mul(P["distance"], SCALE)
    close = g.logic("OR", g.cmp("LESS_EQUAL", limit, 0.0), g.cmp("LESS_EQUAL", dist, limit))
    go = g.logic("AND", hit, close)
    moved = g.mix(pos, where, g.div(P["strength"], 100.0))
    return g.pick(go, pos, moved, "VECTOR")


def _smooth(g, P, pos):
    blur = g.n.new("GeometryNodeBlurAttribute")
    blur.data_type = "FLOAT_VECTOR"
    g.put(pos, blur.inputs["Value"])
    g.put(P["iterations"], blur.inputs["Iterations"])
    return g.mix(pos, blur.outputs[0], g.div(P["strength"], 100.0))


def _arrange(tree):
    """Lay the nodes out left to right by depth so the tree is readable if someone opens it."""
    depth = {}
    links = {}
    for lk in tree.links:
        links.setdefault(lk.to_node, []).append(lk.from_node)

    def d(n, seen=()):
        if n in depth:
            return depth[n]
        if n in seen:
            return 0
        depth[n] = 1 + max((d(f, seen + (n,)) for f in links.get(n, [])), default=-1)
        return depth[n]
    rows = {}
    for n in tree.nodes:
        k = d(n)
        n.location = (k * 200.0, -rows.get(k, 0) * 120.0)
        rows[k] = rows.get(k, 0) + 1


def box_mesh(name):
    """A unit wire box (-0.5 to 0.5) whose upright edges have many points, so a bend shows in its outline."""
    corners = [(x, y) for x in (-0.5, 0.5) for y in (-0.5, 0.5)]
    verts, edges = [], []
    for x, y in corners:
        base = len(verts)
        for k in range(BOX_STEPS + 1):
            verts.append((x, y, -0.5 + k / BOX_STEPS))
            if k:
                edges.append((base + k - 1, base + k))
    bottom = [i * (BOX_STEPS + 1) for i in range(4)]
    top = [b + BOX_STEPS for b in bottom]
    for ring in (bottom, top):
        a, b, c, d = ring                       # corners: (-,-) (-,+) (+,-) (+,+)
        edges += [(a, b), (b, d), (d, c), (c, a)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    me.update()
    return me
