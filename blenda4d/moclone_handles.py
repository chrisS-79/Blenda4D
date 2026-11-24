# SPDX-License-Identifier: GPL-3.0-or-later
"""MoClone's object handles (handles.py): drag them in the viewport.

Cloner and Matrix, by mode:
  Linear     one handle on the last clone: where it goes sets Position (each step's move)
  Radial     Radius, on the first clone
  Grid       Size along X, Y and Z; with Per Step the spacing stays and clones are added or taken away, with End Point
             the grid stretches
  Honeycomb  Width, Height and a corner handle for both; Per Step changes the counts, End Point the size
  Object     no handles
Fields: Radius, Size (Box), Height, Length (Linear), Ring Radius (Torus), and Inner Offset in purple.

Shown values are Y up and in cm: shown (x, y, z) = Blender (x, z, y), 1 cm = 0.01 m."""
import math

from mathutils import Vector

from . import generators as g
from . import handles
from .handles import Handle, INNER
from .primitives import set_input

CM = 0.01


def _get(ob, name):
    return g.gval(ob, name)


def _put(ob, name, value):
    mod = g.gen_mod(ob)
    if mod is None or mod.node_group is None or name not in mod.node_group.interface.items_tree:
        return
    set_input(mod, mod.node_group.interface.items_tree[name].identifier, value)


def _shown(v):
    return Vector((v[0], v[2], v[1]))


def _blender(v):
    return Vector((v[0], v[2], v[1]))


def _cm(x):
    return f"{x:.1f} cm"


def _linear(ob):
    n = max(int(_get(ob, "Count")), 1)
    per = _get(ob, "Linear Mode") == "Per Step"
    steps = (n - 1 if per else 1) or 1
    amount = _get(ob, "Amount") / 100.0 * _get(ob, "Step Size") / 100.0 or 1e-6
    p = Vector(_get(ob, "Position"))
    end = _blender(p) * CM * amount * steps

    def put(new, start):
        _put(ob, "Position", tuple(_shown(new) / CM / amount / steps))
    return [Handle("Position", end, put, readout=lambda: "{:.1f}, {:.1f}, {:.1f} cm".format(*_get(ob, "Position")))]


_PLANE = {"XY": (Vector((1, 0, 0)), Vector((0, 0, 1))), "ZY": (Vector((0, 1, 0)), Vector((0, 0, 1))), "XZ": (Vector((1, 0, 0)), Vector((0, 1, 0)))}


def _radial(ob):
    a = math.radians(_get(ob, "Start Angle") + _get(ob, "Radial Offset"))
    u, v = _PLANE.get(_get(ob, "Plane"), _PLANE["XY"])
    d = (u * math.cos(a) + v * math.sin(a)).normalized()
    r = _get(ob, "Radius") * CM

    def put(new, start):
        _put(ob, "Radius", max(new.dot(d), 0.0) / CM)
    return [Handle("Radius", d * r, put, axis=d, readout=lambda: _cm(_get(ob, "Radius")))]


def _grid(ob):
    per = _get(ob, "Grid Mode") == "Per Step"
    size = Vector(_get(ob, "Grid Size"))
    out = []
    for k, (axis_s, axis_b) in enumerate((("X", Vector((1, 0, 0))), ("Y", Vector((0, 0, 1))), ("Z", Vector((0, 1, 0))))):
        n = max(int(_get(ob, "Grid Count " + axis_s)), 1)
        total = size[k] * (n - 1) if per else size[k]
        half = total / 2.0 * CM

        def put(new, start, k=k, axis_s=axis_s, axis_b=axis_b):
            d = max(new.dot(axis_b), 0.0) / CM * 2.0
            if per:                                     # the spacing stays: clones are added or taken away
                _put(ob, "Grid Count " + axis_s, max(int(round(d / max(size[k], 1e-6))) + 1, 1))
            else:
                s = list(_get(ob, "Grid Size")); s[k] = d
                _put(ob, "Grid Size", tuple(s))
        out.append(Handle(f"Size {axis_s}" if not per else f"Count {axis_s}", axis_b * half, put, axis=axis_b,
                          readout=(lambda axis_s=axis_s: str(_get(ob, "Grid Count " + axis_s))) if per else
                          (lambda k=k: _cm(_get(ob, "Grid Size")[k]))))
    return out


def _honeycomb(ob):
    per = _get(ob, "Honeycomb Mode") == "Per Step"
    u, v = _PLANE.get(_get(ob, "Honeycomb Plane"), _PLANE["XY"])
    wc, hc = max(int(_get(ob, "Width Count")), 1), max(int(_get(ob, "Height Count")), 1)
    w, h = _get(ob, "Width"), _get(ob, "Height")
    half_w = (w * (wc - 1) if per else w) / 2.0 * CM
    half_h = (h * (hc - 1) if per else h) / 2.0 * CM

    def set_w(d):
        if per:
            _put(ob, "Width Count", max(int(round(d / max(w, 1e-6))) + 1, 1))
        else:
            _put(ob, "Width", d)

    def set_h(d):
        if per:
            _put(ob, "Height Count", max(int(round(d / max(h, 1e-6))) + 1, 1))
        else:
            _put(ob, "Height", d)

    def put_w(new, start):
        set_w(max(new.dot(u), 0.0) / CM * 2.0)

    def put_h(new, start):
        set_h(max(new.dot(v), 0.0) / CM * 2.0)

    def put_c(new, start):
        put_w(new, start); put_h(new, start)
    wl, hl = ("Width Count", "Height Count") if per else ("Width", "Height")
    rw = (lambda: str(_get(ob, "Width Count"))) if per else (lambda: _cm(_get(ob, "Width")))
    rh = (lambda: str(_get(ob, "Height Count"))) if per else (lambda: _cm(_get(ob, "Height")))
    return [Handle(wl, u * half_w, put_w, axis=u, readout=rw), Handle(hl, v * half_h, put_h, axis=v, readout=rh),
            Handle(f"{wl} and {hl}", u * half_w + v * half_h, put_c, readout=lambda: f"{rw()} x {rh()}")]


def cloner_handles(ob):
    if ob.get("b4d_type") not in ("cloner", "matrix") or g.gen_mod(ob) is None:
        return None
    mode = _get(ob, "Mode")
    return {"Linear": _linear, "Radial": _radial, "Grid": _grid, "Honeycomb": _honeycomb}.get(mode, lambda o: [])(ob)


# --- fields -----------------------------------------------------------------------------------------------------------

_SIZES = ("b4d_fd_radius", "b4d_fd_height", "b4d_fd_tube", "b4d_fd_length", "b4d_fd_size")


def field_handles(ob):
    """One yellow dot scales the whole field evenly (its radius, height, size... together); a field is made uneven
    with the Scale tool. Inner Offset has its own purple dot."""
    k = ob.get("b4d_type", "")
    if not k.startswith("fd_") or k in ("fd_radial", "fd_random"):
        return None
    X, Y = Vector((1, 0, 0)), Vector((0, 1, 0))
    if k == "fd_linear":
        axis, reach = Y, ob.b4d_fd_length / 2.0
    elif k == "fd_box":
        axis, reach = X, ob.b4d_fd_size[0] / 2.0
    else:
        axis, reach = X, ob.b4d_fd_radius
    here = axis * reach * CM
    if k == "fd_cone":                                    # the cone's widest part is its base
        here = here + Vector((0, 0, -ob.b4d_fd_height * CM / 2.0))

    def put(new, start):
        now = max(reach, 1e-6)
        d = max(new.dot(axis), 0.0) / CM
        f = max(d / now, 0.0)
        for name in _SIZES:
            v = getattr(ob, name)
            setattr(ob, name, [c * f for c in v] if hasattr(v, "__len__") else v * f)
    label = "Length" if k == "fd_linear" else "Size" if k == "fd_box" else "Radius"
    out = [Handle(label, here, put, axis=axis, readout=lambda: _cm(ob.b4d_fd_length if k == "fd_linear" else
                                                                     ob.b4d_fd_size[0] if k == "fd_box" else ob.b4d_fd_radius))]
    if k not in ("fd_linear", "fd_torus"):
        # Inner Offset: full strength out to this share of the size, a purple dot along -X
        def put_in(new, start):
            ob.b4d_fd_inner = min(max(-new.x / CM / max(reach, 1e-6) * 100.0, 0.0), 100.0)
        out.append(Handle("Inner Offset", -X * reach * CM * ob.b4d_fd_inner / 100.0, put_in, axis=-X, colour=INNER,
                          readout=lambda: f"{ob.b4d_fd_inner:.0f} %"))
    return out


# --- Escape puts the values back ----------------------------------------------------------------------------------

_FIELD_PROPS = ("b4d_fd_radius", "b4d_fd_height", "b4d_fd_length", "b4d_fd_tube", "b4d_fd_inner", "b4d_fd_size")


def _take(ob):
    state = {}
    mod = g.gen_mod(ob) if ob.get("b4d_type") in ("cloner", "matrix") else None
    if mod is not None and mod.node_group is not None:
        from .primitives import input_slot
        for it in mod.node_group.interface.items_tree:
            if it.item_type == "SOCKET" and it.in_out == "INPUT" and it.socket_type != "NodeSocketObject":
                try:
                    o, a = input_slot(mod, it.identifier)
                    v = getattr(o, a)
                    state[("in", it.name)] = tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
                except Exception:
                    pass
    if ob.get("b4d_type", "").startswith("fd_"):
        for p in _FIELD_PROPS:
            v = getattr(ob, p)
            state[("p", p)] = tuple(v) if hasattr(v, "__len__") else v
    return state


def _give(ob, state):
    for (kind, name), v in state.items():
        if kind == "in":
            _put(ob, name, v)
        else:
            setattr(ob, name, v)


def register():
    handles.provide(cloner_handles)
    handles.provide(field_handles)
    handles.snapshot_with(_take, _give)


def unregister():
    for fn in (cloner_handles, field_handles):
        if fn in handles._providers:
            handles._providers.remove(fn)
