# SPDX-License-Identifier: GPL-3.0-or-later
"""Object handles (handles.py) for every procedural object whose size is a setting: the primitives, the spline
shapes, the box deformers, lights and the Array generator. Plain polygon objects have none: their size is their points.

Positions are in the object's own space, Blender metres; settings are in cm (shown Y up: shown (x, y, z) is
Blender (x, z, y)). A primitive's handles follow its Orientation."""
import math

from mathutils import Euler, Vector

from . import handles
from .handles import Handle

CM = 0.01
X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))


def _cm(v):
    return f"{v:.1f} cm"


# --- primitives ---------------------------------------------------------------------------------------------------

def _prim_mod(ob):
    from .primitives import PRIMS
    if ob.get("b4d_type") not in PRIMS:
        return None
    return next((m for m in ob.modifiers if m.type == "NODES" and m.node_group is not None), None)


def _items(mod):
    return mod.node_group.interface.items_tree


def _pget(mod, name):
    from .primitives import input_slot
    o, a = input_slot(mod, _items(mod)[name].identifier)
    return getattr(o, a)


def _pset(mod, name, v):
    from .primitives import set_input
    set_input(mod, _items(mod)[name].identifier, v)


_ORIENT = {"+X": (0, math.pi / 2, 0), "-X": (0, -math.pi / 2, 0), "+Y": (0, 0, 0), "-Y": (math.pi, 0, 0),
           "+Z": (-math.pi / 2, 0, 0), "-Z": (math.pi / 2, 0, 0)}


def prim_handles(ob):
    mod = _prim_mod(ob)
    if mod is None:
        return None
    k = ob["b4d_type"]
    names = set(it.name for it in _items(mod))
    has = names.__contains__
    get = lambda n: _pget(mod, n)                                     # noqa: E731
    R = Euler(_ORIENT.get(get("Orientation"), (0, 0, 0)) if has("Orientation") else (0, 0, 0)).to_matrix()
    out = []

    def add(label, at, axis, name, index=None, scale=2.0, lo=0.0, readout=None):
        """A handle at `at` (built frame) moving along `axis`; the setting = distance along it / CM * scale."""
        a = (R @ axis).normalized()

        def put(new, start):
            d = max(new.dot(a) - (R @ at - a * (R @ at).dot(a)).dot(a), 0.0)
            val = max(d / CM * scale, lo)
            if index is None:
                _pset(mod, name, val)
            else:
                v = list(get(name)); v[index] = val
                _pset(mod, name, tuple(v))
        out.append(Handle(label, R @ at, put, axis=a,
                          readout=readout or (lambda: _cm(get(name) if index is None else get(name)[index]))))

    def sized(name):                                                  # Size X / Y / Z of a box-shaped primitive
        s = get(name)
        add("Size X", X * s[0] * CM / 2, X, name, 0)
        add("Size Y", Z * s[1] * CM / 2, Z, name, 1)
        add("Size Z", Y * s[2] * CM / 2, Y, name, 2)
    if k == "cube":
        sized("Size")
        if get("Fillet"):
            s, f = get("Size"), get("Fillet Radius")
            at = Vector((s[0] / 2 - f, -s[2] / 2, s[1] / 2)) * CM

            def put(new, start, s=s):
                _pset(mod, "Fillet Radius", min(max(s[0] / 2 - new.dot(R @ X) / CM, 0.0), min(s) / 2))
            out.append(Handle("Fillet Radius", R @ at, put, axis=R @ -X, readout=lambda: _cm(get("Fillet Radius"))))
    elif k in ("sphere", "platonic"):
        add("Radius", X * get("Radius") * CM, X, "Radius", scale=1.0)
    elif k in ("cylinder", "capsule", "oiltank"):
        r, h = get("Radius"), get("Height")
        add("Radius", X * r * CM, X, "Radius", scale=1.0)
        add("Height", Z * h * CM / 2, Z, "Height")
        if k == "oiltank":
            c = get("Cap Height")
            at = Z * (h / 2 - c) * CM

            def put(new, start, h=h):
                _pset(mod, "Cap Height", min(max(h / 2 - new.dot(R @ Z) / CM, 0.0), h / 2))
            out.append(Handle("Cap Height", R @ at, put, axis=R @ -Z, readout=lambda: _cm(get("Cap Height"))))
        if k == "cylinder" and get("Fillet"):
            f = get("Fillet Radius")
            at = Vector((r - f, 0, h / 2)) * CM

            def put(new, start, r=r):
                _pset(mod, "Fillet Radius", min(max(r - new.dot(R @ X) / CM, 0.0), r))
            out.append(Handle("Fillet Radius", R @ at, put, axis=R @ -X, readout=lambda: _cm(get("Fillet Radius"))))
    elif k == "cone":
        h = get("Height")
        out_b = Handle  # noqa: F841
        a_base = Vector((get("Bottom Radius") * CM, 0, -h * CM / 2))
        a_top = Vector((get("Top Radius") * CM, 0, h * CM / 2))

        def put_b(new, start):
            _pset(mod, "Bottom Radius", max(new.dot(R @ X), 0.0) / CM)

        def put_t(new, start):
            _pset(mod, "Top Radius", max(new.dot(R @ X), 0.0) / CM)
        add("Height", Z * h * CM / 2, Z, "Height")
        out.append(Handle("Bottom Radius", R @ a_base, put_b, axis=R @ X, readout=lambda: _cm(get("Bottom Radius"))))
        out.append(Handle("Top Radius", R @ a_top, put_t, axis=R @ X, readout=lambda: _cm(get("Top Radius"))))
    elif k == "torus":
        rr, pr = get("Ring Radius"), get("Pipe Radius")
        add("Ring Radius", X * rr * CM, X, "Ring Radius", scale=1.0)

        def put(new, start):
            _pset(mod, "Pipe Radius", max(new.dot(R @ Z), 0.0) / CM)
        out.append(Handle("Pipe Radius", R @ Vector((rr * CM, 0, pr * CM)), put, axis=R @ Z, readout=lambda: _cm(get("Pipe Radius"))))
    elif k == "plane":
        add("Width", X * get("Width") * CM / 2, X, "Width")
        add("Height", Y * get("Height") * CM / 2, Y, "Height")
    elif k in ("disc", "tube"):
        add("Outer Radius", X * get("Outer Radius") * CM, X, "Outer Radius", scale=1.0)
        add("Inner Radius", -X * get("Inner Radius") * CM, -X, "Inner Radius", scale=1.0)
        if k == "tube":
            add("Height", Z * get("Height") * CM / 2, Z, "Height")
    elif k in ("pyramid", "landscape", "relief"):
        sized("Size")
    elif k == "figure":
        add("Height", Z * get("Height") * CM / 2, Z, "Height")
    return out


# --- spline shapes -------------------------------------------------------------------------------------------------

def spline_handles(ob):
    from . import splines
    k = splines.shape_kind(ob)
    if k is None:
        return None
    s = ob.b4d_spline
    plane = s.plane
    v = lambda n: splines._s(ob, k, n)                                # noqa: E731

    def to_b(p):
        return splines._to_blender(Vector(p), plane)
    out = []

    def add(label, name, at, direction, scale=1.0, when=True):
        if not when:
            return
        pa = to_b(at)
        axis = (to_b(Vector(at) + Vector(direction)) - pa).normalized()
        base = pa - axis * pa.dot(axis)

        def put(new, start):
            setattr(s, splines._attr(k, name), max((new - base).dot(axis), 0.0) / CM * scale)
        out.append(Handle(label, pa, put, axis=axis, readout=lambda: _cm(v(name))))
    if k == "circle":
        add("Radius", "radius", (v("radius"), 0, 0), (1, 0, 0))
        add("Radius Y", "radius_y", (0, v("radius_y"), 0), (0, 1, 0), when=v("ellipse"))
        add("Inner Radius", "inner_radius", (-v("inner_radius"), 0, 0), (-1, 0, 0), when=v("ring"))
    elif k in ("rectangle", "fourside"):
        add("Width", "width", (v("width") / 2, 0, 0), (1, 0, 0), 2.0)
        add("Height", "height", (0, v("height") / 2, 0), (0, 1, 0), 2.0)
    elif k == "arc":
        a = math.radians(v("start_angle"))
        d = (math.cos(a), math.sin(a), 0)
        add("Radius", "radius", tuple(c * v("radius") for c in d), d)
        add("Inner Radius", "inner_radius", tuple(c * v("inner_radius") for c in d), d, when=v("style") == "RING")
    elif k in ("star", "flower"):
        add("Outer Radius", "outer_radius", (0, v("outer_radius"), 0), (0, 1, 0))
        add("Inner Radius", "inner_radius", (0, -v("inner_radius"), 0), (0, -1, 0))
    elif k == "nside":
        add("Radius", "radius", (0, v("radius"), 0), (0, 1, 0))
    elif k == "helix":
        add("Start Radius", "start_radius", (v("start_radius"), 0, 0), (1, 0, 0))
        add("Height", "height", (0, 0, v("height")), (0, 0, 1))
        add("End Radius", "end_radius", (v("end_radius"), 0, v("height")), (1, 0, 0))
    return out


# --- box deformers, lights, the Array generator --------------------------------------------------------------------

def deformer_handles(ob):
    from . import deformers
    try:
        kind = deformers.kind_of(ob)
    except Exception:
        return None
    if kind not in deformers.BOX_KINDS or "b4d_def_size" not in ob:
        return None
    out = []
    for i, (axis, label) in enumerate(((X, "Size X"), (Y, "Size Z"), (Z, "Size Y"))):
        def put(new, start, i=i, axis=axis):
            sz = list(ob["b4d_def_size"]); sz[i] = max(new.dot(axis), 0.0) / CM * 2.0
            ob["b4d_def_size"] = sz
            ob.update_tag()
        out.append(Handle(label, axis * ob["b4d_def_size"][i] * CM / 2, put, axis=axis, readout=lambda i=i: _cm(ob["b4d_def_size"][i])))
    return out


def light_handles(ob):
    if ob.type != "LIGHT":
        return None
    li = ob.data
    out = []
    if li.type == "AREA":
        def put_x(new, start):
            li.size = max(new.x, 0.0) * 2.0

        def put_y(new, start):
            li.size_y = max(new.y, 0.0) * 2.0
        out.append(Handle("Size X" if li.shape in ("RECTANGLE", "ELLIPSE") else "Size", X * li.size / 2, put_x, axis=X,
                          readout=lambda: _cm(li.size / CM)))
        if li.shape in ("RECTANGLE", "ELLIPSE"):
            out.append(Handle("Size Y", Y * li.size_y / 2, put_y, axis=Y, readout=lambda: _cm(li.size_y / CM)))
    elif li.type in ("POINT", "SPOT"):
        def put_r(new, start):
            li.shadow_soft_size = max(new.x, 0.0)
        out.append(Handle("Radius", X * li.shadow_soft_size, put_r, axis=X, readout=lambda: _cm(li.shadow_soft_size / CM)))
    return out


def generator_handles(ob):
    if ob.get("b4d_type") != "array":
        return None
    from . import generators as g

    def put(new, start):
        g.slot(ob, "Radius") and setattr(*g.slot(ob, "Radius"), max(new.x, 0.0) / CM)
        ob.update_tag()
    r = g.gval(ob, "Radius")
    return [Handle("Radius", X * (r or 0.0) * CM, put, axis=X, readout=lambda: _cm(g.gval(ob, "Radius") or 0.0))] if r is not None else None


# --- Escape -------------------------------------------------------------------------------------------------------

def _take(ob):
    st = {}
    mod = _prim_mod(ob)
    if mod is not None:
        from .primitives import input_slot
        for it in _items(mod):
            if it.item_type == "SOCKET" and it.in_out == "INPUT" and it.socket_type in ("NodeSocketFloat", "NodeSocketVector", "NodeSocketInt"):
                try:
                    o, a = input_slot(mod, it.identifier)
                    v = getattr(o, a)
                    st[("prim", it.name)] = tuple(v) if hasattr(v, "__len__") else v
                except Exception:
                    pass
    if ob.type == "CURVE" and hasattr(ob, "b4d_spline"):
        for p in ob.b4d_spline.bl_rna.properties:
            if p.type == "FLOAT" and not p.is_readonly:
                st[("sp", p.identifier)] = getattr(ob.b4d_spline, p.identifier)
    if "b4d_def_size" in ob:
        st[("def", "size")] = list(ob["b4d_def_size"])
    if ob.type == "LIGHT":
        for p in ("size", "size_y", "shadow_soft_size"):
            if hasattr(ob.data, p):
                st[("light", p)] = getattr(ob.data, p)
    return st


def _give(ob, st):
    mod = _prim_mod(ob)
    for (kind, name), v in st.items():
        if kind == "prim" and mod is not None:
            _pset(mod, name, v)
        elif kind == "sp":
            setattr(ob.b4d_spline, name, v)
        elif kind == "def":
            ob["b4d_def_size"] = v
        elif kind == "light":
            setattr(ob.data, name, v)


def register():
    for fn in (prim_handles, spline_handles, deformer_handles, light_handles, generator_handles):
        handles.provide(fn)
    handles.snapshot_with(_take, _give)


def unregister():
    for fn in (prim_handles, spline_handles, deformer_handles, light_handles, generator_handles):
        if fn in handles._providers:
            handles._providers.remove(fn)
