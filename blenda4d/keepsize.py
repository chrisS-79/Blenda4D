# SPDX-License-Identifier: GPL-3.0-or-later
"""When the window changes size, the strips keep their height and the columns their width; the viewport and the managers'
lists take what is gained or lost. (Blender itself scales every panel with the window.)

It happens in the frame the window changes: Blender lays its panels out from the corners of the panels, and Blenda puts
those corners where they belong right after Blender has scaled them. Python has no function for that, so the corners are
written where Blender keeps them. That is done only when everything read there agrees with what Blender says about every
panel; otherwise Blender's own command to move an edge is used, which is a moment later and less exact.

A strip's height is its own (build.py). A column's width is the one it had before, so a column you have dragged keeps
the width you gave it. An edge dragged by hand is never put back: only a new window size, interface scale or file makes
the sizes be looked at."""
import ctypes
import time

import bpy

from . import build, roles

#          strip: (its height, the edge that moves): the one towards the panel that may grow
STRIPS = (("DOC_TABS", build.DOC_TABS_PX, "BOTTOM"), ("PALETTE", build.PALETTE_PX, "BOTTOM"), ("VIEW_TABS", build.VIEW_TABS_PX, "BOTTOM"),
          ("PV_TOP", None, "BOTTOM"), ("TIMELINE", build.TIMELINE_PX, "TOP"), ("PV_BOTTOM", None, "TOP"), ("TL_BAR", None, "BOTTOM"),
          ("OM_HEAD", build.OM_HEAD_PX, "BOTTOM"), ("OM_BAR", build.MM_BAR_PX, "TOP"), ("MM_BAR", build.MM_BAR_PX, "TOP"), ("AB_BAR", build.MM_BAR_PX, "TOP"), ("UV_BAR", build.UV_BAR_PX, "TOP"))
#          column: (its width when fixed, the edge that moves), from the window's edges inwards
COLUMNS = (("OBJECTS", 0, "LEFT"), ("CREATE", build.CREATE_PX, "LEFT"), ("MATERIALS", 0, "LEFT"), ("MODES", None, "RIGHT"),
           ("ASSETS", 0, "RIGHT"), ("ND_LIST", 0, "RIGHT"), ("PV_SIDE", 0, "LEFT"))
LISTEN = 0.5                 # seconds after a new size in which the next one is expected
LEAST = 90                   # pixels at scale 1: the least that is left of a panel that gives way
_seen = {}                   # window -> {"state", "widths"}
_later = {}
_handles = []


def _columns(screen):
    """COLUMNS outermost first, by where they are now: a column's own edge is moved only after the ones outside it
    (the create column and the Material Manager change places with four views)."""
    def key(entry):
        name, _px, edge = entry
        a = _one(screen, name)
        if a is None:
            return (2, 0)
        return (0, -a.x) if edge == "LEFT" else (1, a.x)
    return sorted(COLUMNS, key=key)


def _height(name, px):
    if px is not None:
        return px
    from . import timeline_edit, viewer
    return {"PV_TOP": viewer.top_px(), "PV_BOTTOM": viewer.BOTTOM_PX, "TL_BAR": timeline_edit.BAR_PX}[name]


def _one(screen, name):
    return next(iter(roles.areas(screen, name)), None)


def _state(win):
    return win.width, win.height, round(build._scale(), 3), win.screen.as_pointer()


def _widths(win):
    """The columns' widths from corner to corner, in unscaled pixels."""
    s, c = build._scale(), Corners(win)
    return {name: (c.size(a)[0] if c.ok else a.width + build.EDGE) / s for name, _px, _e in COLUMNS
            if (a := _one(win.screen, name)) is not None}


# --- the corners of the panels, as Blender keeps them -----------------------------------------------------------------------
class _Vert(ctypes.Structure):
    _fields_ = [("next", ctypes.c_void_p), ("prev", ctypes.c_void_p), ("newv", ctypes.c_void_p), ("x", ctypes.c_short), ("y", ctypes.c_short)]


class _Area(ctypes.Structure):
    _fields_ = [("next", ctypes.c_void_p), ("prev", ctypes.c_void_p)] + [(f"v{i}", ctypes.c_void_p) for i in (1, 2, 3, 4)]


class Corners:
    """The panels of a window by their corners: v1 bottom left, v2 top left, v3 top right, v4 bottom right. `ok` only when
    all of it agrees with the panels' places and sizes as Blender tells them."""

    def __init__(self, win, check=True, size=None):
        self.ok, self.at, self.areas, self.win = False, {}, {}, win
        areas = list(win.screen.areas)
        width, height = size or (win.width, win.height)
        ptrs = {a.as_pointer() for a in areas}
        if ctypes.sizeof(ctypes.c_void_p) != 8 or len(areas) < 4:
            return
        gap = 8 + 8 * build._scale()
        for a in areas:
            raw = _Area.from_address(a.as_pointer())
            vs = (raw.v1, raw.v2, raw.v3, raw.v4)
            if any(p and p not in ptrs for p in (raw.next, raw.prev)) or not all(vs) or len(set(vs)) != 4 or any(v % 8 for v in vs):
                return
            for v in vs:
                if v not in self.at:
                    c = _Vert.from_address(v)
                    self.at[v] = [c.x, c.y]
            (x1, y1), (x2, y2), (x3, y3), (x4, y4) = (self.at[v] for v in vs)
            if x1 != x2 or x3 != x4 or y1 != y4 or y2 != y3 or x3 <= x1 or y2 <= y1:
                return
            if check and (abs(x1 - a.x) > gap or abs(y1 - a.y) > gap or abs(x3 - a.x - a.width) > gap or abs(y3 - a.y - a.height) > gap):
                return
            self.areas[a.as_pointer()] = vs
        if not self._others(4 * len(areas) + 32):
            return
        xs, ys = [p[0] for p in self.at.values()], [p[1] for p in self.at.values()]
        if not (-8 <= min(xs) <= 8 and -8 <= min(ys) < height and max(xs) <= width + 8 and max(ys) <= height + 8) and check:
            return
        self.box = (min(xs), min(ys), max(xs), max(ys))
        self.ok = True

    def _others(self, most):
        """Corners no panel uses (any more): Blender measures with them too."""
        corners, start = set(self.at), next(iter(self.at))
        for link in ("next", "prev"):
            v, came = getattr(_Vert.from_address(start), link), start
            while v:
                if v % 8 or len(self.at) > most:
                    return False
                c = _Vert.from_address(v)
                if getattr(c, "prev" if link == "next" else "next") != came:
                    return False
                if v not in self.at:
                    self.at[v] = [c.x, c.y]
                corners.discard(v)
                v, came = getattr(c, link), v
        return corners <= {start}                          # every panel's corner is in Blender's list

    def line(self, area, edge):
        """The corners that move together when this edge moves: the whole line it is part of."""
        vs = self.areas[area.as_pointer()]
        pick = {"BOTTOM": (0, 3), "TOP": (1, 2), "LEFT": (0, 1), "RIGHT": (2, 3)}[edge]
        k = 1 if edge in ("BOTTOM", "TOP") else 0
        out = {vs[pick[0]], vs[pick[1]]}
        here = self.at[vs[pick[0]]][k]
        pairs = ((0, 3), (1, 2)) if k == 1 else ((0, 1), (2, 3))
        grown = True
        while grown:
            grown = False
            for other in self.areas.values():
                for a, b in pairs:
                    va, vb = other[a], other[b]
                    if self.at[va][k] == here and (va in out) != (vb in out):
                        out |= {va, vb}
                        grown = True
        return out, k, here

    def size(self, area):
        vs = self.areas[area.as_pointer()]
        return self.at[vs[2]][0] - self.at[vs[0]][0], self.at[vs[2]][1] - self.at[vs[0]][1]

    def move(self, area, edge, by):
        out, k, here = self.line(area, edge)
        for v in out:
            self.at[v][k] = here + by

    def fits(self, strips):
        """Nothing is turned inside out, and what gives way keeps some room."""
        least = LEAST * build._scale()
        for p, vs in self.areas.items():
            w, h = self.at[vs[2]][0] - self.at[vs[0]][0], self.at[vs[2]][1] - self.at[vs[0]][1]
            if w < 20 or h < 20 or (p not in strips and (w < least * 0.6 or h < least * 0.5)):
                return False
        return True

    def write(self):
        """Put the corners where they are meant to be: only while Blender still keeps exactly these corners. One that
        Blender has freed since they were read (a panel was joined or tidied away) must never be written to."""
        try:
            now = Corners(self.win, check=False)
        except ReferenceError:
            return False
        if not now.ok or set(now.at) != set(self.at) or now.areas != self.areas:
            return False
        used = [self.at[v] for vs in self.areas.values() for v in vs]
        x0, x1, y0, y1 = min(p[0] for p in used), max(p[0] for p in used), min(p[1] for p in used), max(p[1] for p in used)
        for v, (x, y) in self.at.items():
            x, y = min(max(x, x0), x1), min(max(y, y0), y1)
            c = _Vert.from_address(v)
            c.x, c.y = int(round(x)), int(round(y))
        return True

    def scale_to(self, dx, dy):
        """The panels scaled to a window that is wider and higher by pixels, as Blender does it."""
        x0, y0, x1, y1 = self.box
        fx, fy = (x1 - x0 + dx) / max(1, x1 - x0), (y1 - y0 + dy) / max(1, y1 - y0)
        for p in self.at.values():
            p[0], p[1] = round(x0 + (p[0] - x0) * fx), round(y0 + (p[1] - y0) * fy)


def _solve(win, c, widths):
    """Put every strip and column at its own size. True when something moved."""
    s, screen, moved, fixed = build._scale(), win.screen, False, set()
    for name, px, edge in STRIPS:
        a = _one(screen, name)
        if a is None:
            continue
        fixed.add(a.as_pointer())
        want = build.px(_height(name, px)) + build.EDGE
        by = c.size(a)[1] - want
        if by:
            c.move(a, edge, by if edge == "BOTTOM" else -by)
            moved = True
    for name, px, edge in _columns(screen):
        a = _one(screen, name)
        if a is None:
            continue
        want = build.side_px() if name == "MODES" else build.px(px) + build.EDGE if px else round(widths.get(name, 0) * s)
        if not px and name != "MODES" and not widths.get(name):
            continue
        fixed.add(a.as_pointer())
        by = c.size(a)[0] - want
        if by:
            c.move(a, edge, by if edge == "LEFT" else -by)
            moved = True
    return moved and c.fits(fixed)


def _refresh(win):
    """Make Blender lay the panels out again from their corners, as they are now."""
    keep = Corners(win, check=False)
    a = _one(win.screen, "OBJECTS")
    if not keep.ok or a is None:
        return
    vs = keep.areas[a.as_pointer()]
    (x, y0), (_x, y1) = keep.at[vs[0]], keep.at[vs[1]]
    try:                                                   # any move will do: the corners are put right after it
        with bpy.context.temp_override(window=win, screen=win.screen):
            bpy.ops.screen.area_move(x=int(x), y=int((y0 + y1) // 2), delta=-12, snap=False)
    except (RuntimeError, TypeError):
        pass
    if not keep.write():                                   # the panels changed under the move: Blender's own command instead
        build.run_steps(steps(win, _seen.get(win.as_pointer(), {}).get("widths", {})))
    for b in win.screen.areas:
        b.tag_redraw()


# --- Blender's own command, when the corners cannot be used -------------------------------------------------------------------
def _move(win, area, edge, by):
    x, y = area.x + area.width // 2, area.y + area.height // 2
    x, y = {"TOP": (x, area.y + area.height), "BOTTOM": (x, area.y - 1), "LEFT": (area.x - 1, y), "RIGHT": (area.x + area.width, y)}[edge]
    try:
        with bpy.context.temp_override(window=win, screen=win.screen):
            return "FINISHED" in bpy.ops.screen.area_move(x=x, y=y, delta=int(round(by)), snap=False)
    except (RuntimeError, TypeError):
        return False


def _wrong(win, widths):
    s, screen = build._scale(), win.screen
    for name, px, edge in STRIPS:
        a = _one(screen, name)
        if a is not None and abs(a.height - build.px(_height(name, px)) - 1) > 8:
            by = a.height - build.px(_height(name, px)) - 1
            yield a, edge, by if edge == "BOTTOM" else -by
    for name, px, edge in _columns(screen):
        a = _one(screen, name)
        want = 0 if a is None else build.side_px() if name == "MODES" else build.px(px) if px else widths.get(name, 0) * s - build.EDGE
        if want > 0 and abs(a.width - want) > 8:
            by = a.width - want
            yield a, edge, by if edge == "LEFT" else -by


def steps(win, widths):
    tried = {}
    for _ in range(40):
        todo = next(((a, e, by) for a, e, by in _wrong(win, widths) if tried.get(roles.role(a), 0) < 2), None)
        if todo is None:
            return
        tried[roles.role(todo[0])] = tried.get(roles.role(todo[0]), 0) + 1
        _move(win, *todo)
        yield


# --- when -----------------------------------------------------------------------------------------------------------------------
def _ours(win):
    sc = win.screen
    return sc is not None and not sc.show_fullscreen and not sc.is_temporary and _one(sc, "OBJECTS") is not None and _one(sc, "DOC_TABS") is not None


def _margin(win, c):
    return (win.width - c.box[2], win.height - c.box[3]) if c.ok else None


def _draw():
    """A panel of Blenda's is drawn. Blender has just scaled the panels to a new window size: the corners go where they
    belong, for the next frame. While a window is dragged that is the next step of the drag."""
    ctx = bpy.context
    area, win = ctx.area, ctx.window
    if area is None or win is None or ctx.region.type != "WINDOW" or roles.role(area) != "DOC_TABS" or build.busy() or not _ours(win):
        return
    key, now = win.as_pointer(), _state(win)
    old = _seen.get(key)
    if old is not None and old["state"] == now:
        _listen(ctx, area, old)
        if not _later:
            old["margin"] = _margin(win, Corners(win))
            old["widths"] = _widths(win)                   # nothing changed: the widths as they are now are the ones to keep
        return
    same = old is not None and old["state"][3] == now[3]
    old_until = {"until": time.monotonic() + LISTEN}
    _listen(ctx, area, old_until)
    widths = old["widths"] if same else {}
    _seen[key] = {"state": now, "widths": widths or _widths(win), "margin": old["margin"] if same else None, **old_until}
    c = Corners(win)
    if c.ok:
        if _solve(win, c, widths):
            c.write()
            _ask(win, "REFRESH", widths)
    elif any(True for _ in _wrong(win, widths)):
        _ask(win, "STEPS", widths)


def _ask(win, what, widths):
    _later.update(win=win, what=what, widths=widths)
    if not bpy.app.timers.is_registered(_do_later):
        bpy.app.timers.register(_do_later, first_interval=0.0)


def _do_later():
    win, what, widths = _later.get("win"), _later.get("what"), _later.get("widths", {})
    _later.clear()
    try:
        if win is None or build.busy() or not _ours(win):
            return None
        if what == "REFRESH":
            _refresh(win)
        else:
            build.run_steps(steps(win, widths))
    except ReferenceError:
        pass
    return None


def _listen(ctx, area, old):
    """A window is being resized. While its edge is dragged no timer runs (macOS, Windows), but Blender does update a
    scene that was changed before it draws again, and then calls _before()."""
    if time.monotonic() < old.get("until", 0) and ctx.scene is not None:
        ctx.scene.update_tag()
        area.tag_redraw()


@bpy.app.handlers.persistent
def _before(*_args):
    _catch()


def _tick():
    _catch()
    return 0.0


def _catch():
    """Between Blender's events: a window that has another size but is not drawn yet gets its panels' corners for that
    size, and Blender finds nothing left to scale."""
    try:
        wm = bpy.context.window_manager
        for win in wm.windows:
            old = _seen.get(win.as_pointer())
            if old is None or build.busy() or not _ours(win):
                continue
            now, was = _state(win), old["state"]
            if now == was or now[2:] != was[2:]:
                continue
            c = Corners(win, size=(max(now[0], was[0]), max(now[1], was[1])))
            if not c.ok or not old["margin"]:
                continue
            mx, my = old["margin"]                         # Blender may have scaled the panels already, or not yet
            c.scale_to(now[0] - mx - c.box[2], now[1] - my - c.box[3])
            before = {v: tuple(p) for v, p in c.at.items()}
            if not _solve(win, c, old["widths"]) and c.at != before and not c.fits(set()):
                continue
            c.write()
            old["state"], old["until"] = now, time.monotonic() + LISTEN
            for a in win.screen.areas:
                a.tag_redraw()
    except (AttributeError, ReferenceError):
        pass


@bpy.app.handlers.persistent
def _loaded(*_args):
    _seen.clear()
    _later.clear()


def register():
    _loaded()
    _handles.append(bpy.types.SpaceProperties.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL"))
    bpy.app.handlers.load_post.append(_loaded)
    if not bpy.app.background:
        bpy.app.handlers.depsgraph_update_post.append(_before)
    if not bpy.app.background:
        bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)


def unregister():
    while _handles:
        bpy.types.SpaceProperties.draw_handler_remove(_handles.pop(), "WINDOW")
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    if _before in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_before)
    for t in (_tick, _do_later):
        if bpy.app.timers.is_registered(t):
            bpy.app.timers.unregister(t)
    _loaded()
