# SPDX-License-Identifier: GPL-3.0-or-later
"""The timeline under the viewport, three rows tall.

  1 Open Timeline, transport, playback, the current frame, Record and Autokeying, and which channels they key.
  2 The ruler. Its numbers scrub (Shift: from key to key). Under them, the selected objects' keys: drag a key to move
    it, drag over empty space for a range, drag the range to move its keys and its ends to scale them (Alt: about the
    middle). Ctrl kept down at the end of a drag leaves the original keys. Ctrl+click makes a key.
  3 The scene's first and last frame, and the slider between them: the preview range the ruler shows. Drag it or
    its ends (Alt: both); a double-click shows the whole scene, and the next one goes back.

Rows 1 and 3 are Blender's own buttons and fields. Keys, playback and ranges are Blender's own too."""
import math

import bpy

from . import anim as A, build, roles

ROLE = "TIMELINE"
MARGIN, ROW, TOP, GAP = 8, 20, 25, 36  # px at scale 1: Blender's panel inset, its button height, row 1, the ruler
FIELD = 3.8                            # the width of the first and last frame fields, in button units

_layout = {}                           # area -> where things were drawn
_range = {}                            # the selected range while there is one: {"a": frame, "b": frame}
_handles = []
_keymaps = []
_last = [None]


# --- playback -----------------------------------------------------------------------------------------------------------
PLAY_MODES = (("SIMPLE", "Simple", "FORWARD", "Play once and stop"), ("CYCLE", "Cycle", "FILE_REFRESH", "Play again from the start"),
              ("PINGPONG", "Ping-Pong", "ARROW_LEFTRIGHT", "Play forwards, then backwards"))


def play_mode(scene):
    m = scene.get("b4d_play_mode", "CYCLE")
    return m if m in {p[0] for p in PLAY_MODES} else "CYCLE"


@bpy.app.handlers.persistent
def _playback(scene, *_args):
    mode = play_mode(scene)
    screen = bpy.context.screen
    if mode == "CYCLE" or screen is None or not screen.is_animation_playing:
        _last[0] = None
        return
    a, b = (scene.frame_preview_start, scene.frame_preview_end) if scene.use_preview_range else (scene.frame_start, scene.frame_end)
    f, last = scene.frame_current, _last[0]
    _last[0] = f
    if last is None:
        return
    jumped = abs(f - last) > (b - a) / 2
    forward = (f < last) if jumped else (f > last)
    if not jumped and not (f >= b if forward else f <= a):
        return

    def later():
        try:
            bpy.ops.screen.animation_cancel(restore_frame=False)
            scene.frame_current = b if forward else a
            if mode == "PINGPONG":
                bpy.ops.screen.animation_play(reverse=forward)
        except RuntimeError:
            pass
        return None
    bpy.app.timers.register(later, first_interval=0.0)


class BLENDA4D_OT_play_mode(bpy.types.Operator):
    bl_idname = "blenda4d.play_mode"
    bl_label = "Playback Mode"
    bl_options = {"INTERNAL"}
    mode: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, props):
        return next((d for k, _l, _i, d in PLAY_MODES if k == props.mode), cls.bl_label)

    def execute(self, context):
        context.scene["b4d_play_mode"] = self.mode
        A.redraw()
        return {"FINISHED"}


class BLENDA4D_MT_play_mode(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_play_mode"
    bl_label = "Playback Mode"
    bl_description = "How the animation plays when it reaches the end"

    def draw(self, context):
        lay, now = self.layout, play_mode(context.scene)
        lay.prop(context.scene, "use_preview_range", text="Preview Range")
        lay.separator()
        for key, label, icon, _d in PLAY_MODES:
            lay.operator("blenda4d.play_mode", text=label + ("  (on)" if key == now else ""), icon=icon).mode = key


class BLENDA4D_MT_frame_rate(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_frame_rate"
    bl_label = "Frame Rate"
    bl_description = "How fast the animation plays"

    def draw(self, context):
        lay, sc = self.layout, context.scene
        for val, label, icon in (("NONE", "All Frames", "RENDER_ANIMATION"), ("FRAME_DROP", "Scene", "TIME")):
            op = lay.operator("wm.context_set_enum", text=label + ("  (on)" if sc.sync_mode == val else ""), icon=icon)
            op.data_path, op.value = "scene.sync_mode", val
        lay.separator()
        for fps in (12, 15, 18, 24, 25, 30, 50, 60, 120):
            op = lay.operator("wm.context_set_int", text=str(fps) + ("  (on)" if sc.render.fps == fps else ""), icon="BLANK1")
            op.data_path, op.value = "scene.render.fps", fps


# --- buttons ---------------------------------------------------------------------------------------------------------------
class BLENDA4D_OT_tl_go(bpy.types.Operator):
    bl_idname = "blenda4d.tl_go"
    bl_label = "Go to Frame"
    bl_options = {"INTERNAL"}
    to: bpy.props.StringProperty()
    TIPS = {"START": "Go to Start. Alt: the preview range's start", "END": "Go to End. Alt: the preview range's end",
            "PREV": "Go to Previous Frame", "NEXT": "Go to Next Frame",
            "PREV_KEY": "Go to Previous Key", "NEXT_KEY": "Go to Next Key"}

    @classmethod
    def description(cls, context, props):
        return cls.TIPS.get(props.to, cls.bl_label)

    def invoke(self, context, event):
        self.alt = event.alt
        return self.execute(context)

    def execute(self, context):
        sc, preview = context.scene, A.view_range(context.scene) if getattr(self, "alt", False) else None
        if self.to == "START":
            sc.frame_current = preview[0] if preview else sc.frame_start
        elif self.to == "END":
            sc.frame_current = preview[1] if preview else sc.frame_end
        elif self.to in {"PREV", "NEXT"}:
            sc.frame_current += 1 if self.to == "NEXT" else -1
        else:
            keys = sorted(A.key_frames(context))
            after = self.to == "NEXT_KEY"
            on = [k for k in keys if (k > sc.frame_current if after else k < sc.frame_current)]
            if on:
                sc.frame_current = min(on) if after else max(on)
        A.redraw()
        return {"FINISHED"}


class BLENDA4D_OT_tl_record(bpy.types.Operator):
    bl_idname = "blenda4d.tl_record"
    bl_label = "Record Active Objects"
    bl_description = "Make keys on the selected objects at the current frame, for the channels that are switched on"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(A.objects(context))

    def execute(self, context):
        if not A.record(context):
            self.report({"INFO"}, "No keys made: switch on Position, Rotation or Scale")
            return {"CANCELLED"}
        return {"FINISHED"}


class BLENDA4D_OT_tl_autokey(bpy.types.Operator):
    bl_idname = "blenda4d.tl_autokey"
    bl_label = "Autokeying"
    bl_description = "Make a key whenever you change the selected objects"

    def execute(self, context):
        ts = context.tool_settings
        ts.use_keyframe_insert_auto = not ts.use_keyframe_insert_auto
        A.apply_channels(context)
        A.redraw()
        return {"FINISHED"}


class BLENDA4D_OT_tl_dock(bpy.types.Operator):
    bl_idname = "blenda4d.tl_dock"
    bl_label = "Timeline"
    bl_options = {"INTERNAL"}
    mode: bpy.props.StringProperty(default="KEYS")

    @classmethod
    def description(cls, context, props):
        name = "F-Curves (Graph Editor)" if props.mode == "CURVES" else "Dope Sheet"
        return f"Open the Timeline on its {name}, above this strip, or fold it away"

    @classmethod
    def poll(cls, context):
        return not build.busy()

    def execute(self, context):
        from . import timeline_edit
        open_now = bool(roles.areas(context.screen, "TL_EDIT"))
        if open_now and timeline_edit.mode(context.workspace) != self.mode:
            timeline_edit.set_mode(context.workspace, self.mode)
        else:
            timeline_edit.set_mode(context.workspace, self.mode)
            build.run_steps(build.dock_steps(context.window, not open_now))
        A.redraw()
        return {"FINISHED"}


def _groups(context):
    """Row 1: [(name, width in buttons, draw(row, words))] left to right; `words` writes the names too (the menu)."""
    sc, ts, screen = context.scene, context.tool_settings, context.screen
    playing = bool(screen and screen.is_animation_playing)

    def go(row, words, to, icon):
        row.operator("blenda4d.tl_go", text=BLENDA4D_OT_tl_go.TIPS[to].split(".")[0] if words else "", icon=icon).to = to

    def transport(row, words):
        go(row, words, "START", "REW")
        go(row, words, "PREV_KEY", "PREV_KEYFRAME")
        go(row, words, "PREV", "FRAME_PREV")
        row.operator("screen.animation_play", text=("Stop" if playing else "Play Forwards") if words else "",
                     icon="PAUSE" if playing else "PLAY", depress=playing)
        go(row, words, "NEXT", "FRAME_NEXT")
        go(row, words, "NEXT_KEY", "NEXT_KEYFRAME")
        go(row, words, "END", "FF")

    def playback(row, words):
        icon = next(i for k, _l, i, _d in PLAY_MODES if k == play_mode(sc))
        row.menu("BLENDA4D_MT_play_mode", text="Playback Mode" if words else "", icon=icon)
        row.menu("BLENDA4D_MT_frame_rate", text="Frame Rate" if words else "", icon="TIME")
        row.prop(sc, "use_audio", text="Play Sound" if words else "", icon="PLAY_SOUND")

    def frame(row, words):
        row.prop(sc, "frame_current", text="Current Frame" if words else "")

    def rec(row, words):
        row.operator("blenda4d.tl_record", text="Record Active Objects" if words else "", icon="KEYFRAME_HLT")
        sub = row.row(align=True)
        sub.alert = ts.use_keyframe_insert_auto
        sub.operator("blenda4d.tl_autokey", text="Autokeying" if words else "", icon="REC", depress=ts.use_keyframe_insert_auto)

    def channels(row, words):
        for ch, label, icon in A.CHANNELS:
            row.prop(context.window_manager, f"b4d_rec_{ch}", text=label if words else "", icon=icon, toggle=not words)
    return [("transport", 7, transport), ("playback", 4.6, playback), ("frame", 3.6, frame), ("record", 2, rec),
            ("channels", 4, channels)]


DROP_FIRST = ("playback", "channels", "record", "frame")


def fit(context):
    """(groups that fit, groups for the > menu): buttons keep their size, whole groups step aside."""
    from . import bars, fitzoom
    region = context.region
    u = 20.0 * context.preferences.system.ui_scale
    free = region.width / max(0.1, fitzoom.zoom_of(region)) / u - 2 * bars.PANEL_MARGIN / 20.0 - 2 * 1.2
    groups, rest = _groups(context), []
    for name in DROP_FIRST:
        if sum(g[1] for g in groups) * 1.2 + 0.8 * len(groups) + (1.2 if rest else 0) <= free:
            break
        rest += [g for g in groups if g[0] == name]
        groups = [g for g in groups if g[0] != name]
    return groups, rest


class BLENDA4D_MT_tl_more(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_tl_more"
    bl_label = "More"
    bl_description = "The timeline buttons that do not fit in this window"

    def draw(self, context):
        area = next(iter(roles.areas(context.screen, ROLE)), None)
        region = next((r for r in area.regions if r.type == "WINDOW"), None) if area else None
        if region is None:
            return
        with context.temp_override(area=area, region=region):
            rest = fit(bpy.context)[1]
        for n, (_name, _w, draw) in enumerate(rest):
            if n:
                self.layout.separator()
            draw(self.layout, True)


class BLENDA4D_PT_timeline(roles.RolePanel, bpy.types.Panel):
    bl_label = "Timeline"
    role = ROLE

    def draw(self, context):
        from . import timeline_edit
        sc = context.scene
        col = self.layout.column(align=True)
        whole = col.row(align=False)
        whole.scale_y = TOP / ROW
        groups, rest = fit(context)
        open_now = bool(roles.areas(context.screen, "TL_EDIT"))
        mode = timeline_edit.mode(context.workspace)
        left = whole.row(align=True)
        left.alignment = "LEFT"
        left.scale_x = 1.2
        left.operator("blenda4d.tl_dock", text="", icon="ACTION", depress=open_now and mode == "KEYS").mode = "KEYS"
        mid = whole.row(align=True)
        mid.alignment = "CENTER"
        mid.scale_x = 1.2
        for n, (name, w, draw) in enumerate(groups):
            if n:
                mid.separator(factor=1.6)
            row = mid.row(align=True)
            if name == "frame":
                row.ui_units_x = w * 1.2
            draw(row, False)
        if rest:
            mid.separator(factor=1.0)
            mid.menu("BLENDA4D_MT_tl_more", text="", icon="RIGHTARROW_THIN")
        right = whole.row(align=True)
        right.alignment = "RIGHT"
        right.scale_x = 1.2
        right.operator("blenda4d.tl_dock", text="", icon="FCURVE", depress=open_now and mode == "CURVES").mode = "CURVES"
        gap = col.row()                                   # the ruler is drawn here
        gap.scale_y = GAP / 20.0
        gap.label(text="")
        ends = col.row(align=False)
        a = ends.row(align=True)
        a.alignment = "LEFT"
        a.ui_units_x = FIELD
        a.prop(sc, "frame_start", text="")
        ends.label(text="")
        b = ends.row(align=True)
        b.alignment = "RIGHT"
        b.ui_units_x = FIELD
        b.prop(sc, "frame_end", text="")


# --- drawing ------------------------------------------------------------------------------------------------------------
def frame_x(lay, f):
    x0, x1 = lay["x"]
    a, b = lay["view"]
    return x0 + (f - a) / (b - a) * (x1 - x0)


def x_frame(lay, x):
    x0, x1 = lay["x"]
    a, b = lay["view"]
    return a + (x - x0) / max(1.0, x1 - x0) * (b - a)


def _draw():
    context = bpy.context
    area, region = context.area, context.region
    if region is None or roles.role(area) != ROLE:
        return
    from . import fitzoom
    sc = context.scene
    z = fitzoom.zoom_of(region)
    s = context.preferences.system.ui_scale * z
    W = region.width
    top = region.view2d.view_to_region(0, 0, clip=False)[1]
    y1 = top - (MARGIN + TOP + 1) * s
    y0 = y1 - (GAP - 2) * s
    ymid = y0 + (y1 - y0) * 0.5
    lay = {"x": (14 * s, W - 14 * s), "view": A.view_range(sc), "numbers": (ymid, y1), "strip": (y0, ymid), "s": s}
    _layout[area.as_pointer()] = lay
    a, b = lay["view"]
    ppf = (lay["x"][1] - lay["x"][0]) / (b - a)
    A.rect(0, y0, W, y1, A.BAND)
    A.rect(0, y0, W, ymid, A.DARK)
    step = A.step_for(ppf, 38 * s)
    small = max(1, step // 5 if step % 5 == 0 else step // 2)
    ticks = []
    f = math.ceil(a / small) * small
    while f <= b:
        x = frame_x(lay, f)
        ticks += [(x, ymid), (x, ymid + (5 if f % step == 0 else 3) * s)]
        if f % step == 0:
            A.text(x, ymid + 6 * s, str(f), A.DIM, 10 * s, "CENTER")
        f += small
    A.lines(ticks, A.TICK)
    half = max(1.5 * s, min((ppf - 1) / 2, 4 * s))
    for fr, sel in sorted(A.key_frames(context).items(), key=lambda t: t[1]):
        if a - 1 <= fr <= b + 1:
            x = frame_x(lay, fr)
            A.rect(x - half, y0 + 3 * s, x + half, ymid - 3 * s, A.KEY_SEL if sel else A.KEY)
    if _range:
        ra, rb = sorted((_range["a"], _range["b"]))
        xa, xb = frame_x(lay, ra), frame_x(lay, rb)
        A.rect(xa, y0 + 1 * s, xb, ymid - 1 * s, A.RANGE)
        for x in (xa, xb):
            A.rect(x - 2 * s, y0 + 1 * s, x + 2 * s, ymid - 1 * s, A.RANGE_EDGE)
        lay["range"] = (xa, xb)
    now_tag(sc.frame_current, frame_x(lay, sc.frame_current), y0, ymid, y1, s, 0, W)
    _draw_slider(context, lay, s, W, y0 - 1 * s, y0 - (ROW + 1) * s)


def now_tag(frame, x, y0, ymid, y1, s, left, right):
    """The current frame: its number in a tag, and a line down."""
    if not left - 20 * s <= x <= right + 20 * s:
        return
    w = A.text_width(str(frame), 10 * s) + 8 * s
    A.rect(x - w / 2, ymid + 1 * s, x + w / 2, y1 - 1 * s, A.NOW)
    A.text(x, ymid + 6 * s, str(frame), (1, 1, 1, 1), 10 * s, "CENTER")
    A.rect(x - 0.7 * s, y0, x + 0.7 * s, ymid + 1 * s, A.NOW)


def _draw_slider(context, lay, s, W, y1, y0):
    sc = context.scene
    from . import bars
    side = (bars.PANEL_MARGIN + FIELD * 20 + 6) * s
    x0, x1 = side, W - side
    if x1 - x0 < 40 * s:
        return
    A.rect(x0, y0 + 2 * s, x1, y1 - 2 * s, A.FIELD)
    span = max(1, sc.frame_end - sc.frame_start)
    a, b = A.view_range(sc)
    xa = x0 + (a - sc.frame_start) / span * (x1 - x0)
    xb = x0 + (b - sc.frame_start) / span * (x1 - x0)
    xa, xb = max(x0, min(x1, xa)), max(x0, min(x1, xb))
    A.rect(xa, y0 + 2 * s, xb, y1 - 2 * s, (0.27, 0.27, 0.27, 1.0))
    ym = (y0 + y1) / 2
    for x, d in ((xa, 1), (xb, -1)):                      # the ends: small arrows
        A.tris([(x + d * 2 * s, ym), (x + d * 7 * s, ym + 4 * s), (x + d * 7 * s, ym - 4 * s)], A.DIM)
    if xb - xa > 110 * s:
        A.text(xa + 11 * s, ym - 4 * s, str(a), A.TEXT, 10 * s)
        A.text(xb - 11 * s, ym - 4 * s, str(b), A.TEXT, 10 * s, "RIGHT")
    lay["slider"] = (x0, y0, x1, y1)
    lay["ends"] = (xa, xb)


# --- input ------------------------------------------------------------------------------------------------------------------
def _hit(lay, x, y):
    if "slider" in lay:
        x0, y0, x1, y1 = lay["slider"]
        if x0 <= x <= x1 and y0 <= y <= y1:
            return "slider"
    for name in ("strip", "numbers"):
        y0, y1 = lay[name]
        if y0 <= y < y1:
            return name
    return None


class BLENDA4D_OT_tl_press(bpy.types.Operator):
    bl_idname = "blenda4d.tl_press"
    bl_label = "Timeline"
    bl_description = "Scrub, and move keys, in the timeline"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return roles.role(context.area) == ROLE

    def invoke(self, context, event):
        lay = _layout.get(context.area.as_pointer())
        hit = _hit(lay, event.mouse_region_x, event.mouse_region_y) if lay else None
        if hit is None:
            return {"PASS_THROUGH"}
        if event.type == "RIGHTMOUSE":
            bpy.ops.wm.call_menu(name="BLENDA4D_MT_tl_context")
            return {"FINISHED"}
        sc, x = context.scene, event.mouse_region_x
        ctrl = event.ctrl or event.oskey
        self.lay, self.x0, self.moved, self.saved = lay, x, False, []
        f = x_frame(lay, x)
        if hit == "numbers" and ctrl and event.shift:
            m = sc.timeline_markers.new(f"F_{round(f)}", frame=round(f))
            m.select = True
            A.push("Add Marker")
            A.redraw()
            return {"FINISHED"}
        if hit == "numbers" or (hit == "strip" and ctrl and not _range):
            if ctrl:
                if A.record(context, round(f)):
                    A.push("Add Keys")
                return {"FINISHED"}
            self.what = "scrub"
            self._scrub(context, event, f)
        elif hit == "strip":
            self._press_keys(context, event, f, x)
        else:
            if event.value == "DOUBLE_CLICK":
                self._whole(sc)
                return {"FINISHED"}
            xa, xb = lay["ends"]
            r = 8 * lay["s"]
            self.view0 = A.view_range(sc)
            self.what = "a" if abs(x - xa) <= r else "b" if abs(x - xb) <= r else "both" if xa < x < xb else None
            if self.what is None:
                return {"FINISHED"}
        self.token = A.new_token()
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _press_keys(self, context, event, f, x):
        lay = self.lay
        r = 6 * lay["s"]
        rng = lay.get("range")
        keys = A.key_frames(context)
        near = min(keys, key=lambda k: abs(frame_x(lay, k) - x), default=None)
        ppf = frame_x(lay, 1) - frame_x(lay, 0)
        if rng and min(abs(x - rng[0]), abs(x - rng[1])) <= r:
            lo, hi = sorted((_range["a"], _range["b"]))
            first = abs(x - rng[0]) <= abs(x - rng[1])
            self.what, self.fixed, self.grabbed = "scale", hi if first else lo, lo if first else hi
        elif rng and rng[0] < x < rng[1]:
            self.what = "move"
        elif near is not None and abs(frame_x(lay, near) - x) <= max(5 * lay["s"], ppf / 2):
            if not keys[near] or event.shift:
                A.select_between(context, near, near, extend=event.shift)
            _range.clear()
            self.what = "move"
        else:
            _range.clear()
            self.what, self.f0 = "range", round(f)
            A.select_between(context, 1e9, 1e9)
        self.saved = A.remember(A.selected_points(context))
        self.range0, self.f_start = dict(_range), f
        A.redraw()

    def _scrub(self, context, event, f):
        f = round(f)
        if event.shift:
            keys = A.key_frames(context)
            f = min(keys, key=lambda k: abs(k - f), default=f)
        context.scene.frame_current = f
        A.redraw()

    @staticmethod
    def _whole(sc):
        now, whole = A.view_range(sc), (sc.frame_start, sc.frame_end)
        if now == whole and "b4d_preview" in sc:
            A.set_view_range(sc, *sc["b4d_preview"])
        else:
            sc["b4d_preview"] = list(now)
            A.set_view_range(sc, *whole)
        A.redraw()

    def modal(self, context, event):
        lay, sc, w = self.lay, context.scene, self.what
        if self.token != A.token():
            return {"CANCELLED"}
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            x = event.mouse_region_x
            self.moved = self.moved or abs(x - self.x0) > 2
            f = x_frame(lay, x)
            if w == "scrub":
                self._scrub(context, event, f)
            elif not self.moved:
                pass
            elif w == "range":
                _range.update(a=self.f0, b=round(f))
                A.select_between(context, *sorted((self.f0, round(f))))
            elif w == "move":
                d = round(f - self.f_start)
                A.retime(context, self.saved, lambda t: t + d)
                if self.range0:
                    _range.update(a=self.range0["a"] + d, b=self.range0["b"] + d)
            elif w == "scale":
                pivot = (self.range0["a"] + self.range0["b"]) / 2 if event.alt else self.fixed
                k = (f - pivot) / ((self.grabbed - pivot) or 1e-6)
                A.retime(context, self.saved, lambda t: pivot + (t - pivot) * k)
                _range.update({n: round(pivot + (self.range0[n] - pivot) * k) for n in ("a", "b")})
            else:
                x0, _y0, x1, _y1 = lay["slider"]
                d = (x - self.x0) / max(1.0, x1 - x0) * max(1, sc.frame_end - sc.frame_start)
                a, b = self.view0
                if w == "a":
                    A.set_view_range(sc, a + d, b - d if event.alt else b)
                elif w == "b":
                    A.set_view_range(sc, a - d if event.alt else a, b + d)
                else:
                    d = max(sc.frame_start - a, min(sc.frame_end - b, round(d)))
                    A.set_view_range(sc, a + d, b + d)
            A.redraw()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if w in {"move", "scale"} and self.moved:
                if event.ctrl or event.oskey:
                    A.keep_copies(self.saved)
                else:
                    A.drop_overlaid(self.saved)
                A.update(context, {t[0] for t in self.saved})
                A.push("Scale Keys" if w == "scale" else "Move Keys")
            elif w == "range":
                sel = sorted(round(kp.co.x) for _fc, kp in A.selected_points(context))
                _range.clear()
                if self.moved and sel and sel[-1] > sel[0]:
                    _range.update(a=sel[0], b=sel[-1])
            A.redraw()
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            if w in {"move", "scale"}:
                A.retime(context, self.saved, lambda t: t)
                _range.clear()
                _range.update(self.range0)
            elif w in {"a", "b", "both"}:
                A.set_view_range(sc, *self.view0)
            A.redraw()
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


classes = (BLENDA4D_OT_play_mode, BLENDA4D_MT_play_mode, BLENDA4D_MT_frame_rate, BLENDA4D_OT_tl_go, BLENDA4D_OT_tl_record,
           BLENDA4D_OT_tl_autokey, BLENDA4D_OT_tl_dock, BLENDA4D_MT_tl_more, BLENDA4D_PT_timeline, BLENDA4D_OT_tl_press)


@bpy.app.handlers.persistent
def _loaded(_file):
    _range.clear()
    A.new_token()


def register():
    A.register()
    for c in classes:
        bpy.utils.register_class(c)
    _handles.append(bpy.types.SpaceProperties.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL"))
    for h, fn in ((bpy.app.handlers.frame_change_post, _playback), (bpy.app.handlers.load_post, _loaded)):
        if fn not in h:
            h.append(fn)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Property Editor", space_type="PROPERTIES", region_type="WINDOW")
        for kind, value in (("LEFTMOUSE", "PRESS"), ("LEFTMOUSE", "DOUBLE_CLICK"), ("RIGHTMOUSE", "PRESS")):
            _keymaps.append((km, km.keymap_items.new(BLENDA4D_OT_tl_press.bl_idname, kind, value, any=True, head=True)))


def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    for h, fn in ((bpy.app.handlers.frame_change_post, _playback), (bpy.app.handlers.load_post, _loaded)):
        if fn in h:
            h.remove(fn)
    while _handles:
        bpy.types.SpaceProperties.draw_handler_remove(_handles.pop(), "WINDOW")
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    A.unregister()
