# SPDX-License-Identifier: GPL-3.0-or-later
"""Render settings are remembered: what is changed in Render Settings (or anywhere else in Blender) is what the next
new file starts with, and after a restart too, without saving anything by hand. An opened file always keeps its own.

Only what was changed is remembered, one value at a time, so opening an old project and changing its samples does not
carry its size along. What belongs to one project is left out: where it is saved, its notes, its material override, its
render region and the scene's frame rate. The page Render Settings shows and its Advanced part are remembered too."""
import bpy

from . import remember, render_settings

FILE = "render_last.json"
EVERY = 0.5
NOT = {"render.filepath", "rs.annotations", "rs.material_override", "rs.override_material", "render.use_border",
       "render.use_crop_to_border", "render.border_min_x", "render.border_max_x", "render.border_min_y",
       "render.border_max_y", "render.fps", "render.fps_base"}
_base = {}                   # scene name -> its values when they were last looked at


def values(scene):
    return {k: v for k, v in render_settings.capture(scene).items() if k not in NOT}


def look():
    """What has been changed since the last look is remembered."""
    if render_settings._stash or bpy.app.is_job_running("RENDER"):     # a render has set some for itself
        return
    wm = bpy.context.window_manager
    for scene in {w.scene for w in wm.windows} if wm else ():
        now, before = values(scene), _base.get(scene.name)
        _base[scene.name] = now
        if before is None or before == now:
            continue
        for k, v in now.items():
            if before.get(k, v) != v:
                remember.put(FILE, k, v)
    if wm and len(wm.b4d_rs_pages):
        remember.put(FILE, "page", wm.b4d_rs_pages[min(wm.b4d_rs_page, len(wm.b4d_rs_pages) - 1)].key)
        remember.put(FILE, "advanced", wm.b4d_rs_advanced)


def _tick():
    try:
        look()
    except (AttributeError, ReferenceError, RuntimeError) as ex:
        print("Blenda 4D: render settings not looked at:", ex)
    return EVERY


def put_on():
    """A new file: every scene in it takes the remembered values."""
    last = {k: v for k, v in remember.get(FILE).items() if "." in k and k not in NOT}
    for scene in bpy.data.scenes:
        render_settings.apply_values(scene, last)
        _base[scene.name] = values(scene)
        if len(render_settings.sets(scene)):
            render_settings.commit(scene)


def _pages():
    wm, last = bpy.context.window_manager, remember.get(FILE)
    keys = [p[0] for p in render_settings.PAGES]
    if last.get("page") in keys:
        wm.b4d_rs_page = keys.index(last["page"])
    wm.b4d_rs_advanced = bool(last.get("advanced", False))


@bpy.app.handlers.persistent
def _leaving(*_args):
    """Before another file comes: the last changes in this one."""
    try:
        look()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    _base.clear()


@bpy.app.handlers.persistent
def _loaded(path, *_args):
    _base.clear()
    if not path:
        put_on()
    try:
        render_settings.ensure_pages(bpy.context.window_manager)      # another file starts with an empty page list
        _pages()
    except (AttributeError, TypeError):
        pass


def _start():
    """Blenda mode comes on after Blender has opened its first file: a new one nobody has touched yet."""
    try:
        render_settings.ensure_pages(bpy.context.window_manager)
        _pages()
        if not bpy.data.filepath and not bpy.data.is_dirty:
            put_on()
            from . import camview
            camview._loaded("")
    except AttributeError:
        return 0.2
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=EVERY, persistent=True)
    return None


HANDLERS = (("load_pre", _leaving), ("load_post", _loaded))


def register():
    _base.clear()
    for name, fn in HANDLERS:
        h = getattr(bpy.app.handlers, name)
        if fn not in h:
            h.append(fn)
    bpy.app.timers.register(_start, first_interval=0.0, persistent=True)


def unregister():
    for t in (_start, _tick):
        if bpy.app.timers.is_registered(t):
            bpy.app.timers.unregister(t)
    for name, fn in HANDLERS:
        h = getattr(bpy.app.handlers, name)
        if fn in h:
            h.remove(fn)
    try:
        look()                                             # changed and quit at once
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    remember.stop()
    _base.clear()
