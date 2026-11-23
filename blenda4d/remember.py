# SPDX-License-Identifier: GPL-3.0-or-later
"""Choices kept between files and sessions, in Blenda 4D's own small files beside Blender's preferences."""
import bpy

_data = {}                   # file name -> what it holds
_dirty = set()


def get(name):
    if name not in _data:
        from . import layouts
        _data[name] = layouts._read(name)
    return _data[name]


def put(name, key, value):
    data = get(name)
    if data.get(key) == value:
        return
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    _dirty.add(name)
    if not bpy.app.timers.is_registered(flush):            # a slider being dragged is one write, not hundreds
        bpy.app.timers.register(flush, first_interval=0.5, persistent=True)


def flush():
    from . import layouts
    for name in list(_dirty):
        _dirty.discard(name)
        try:
            layouts._write(name, get(name))
        except OSError as ex:
            print("Blenda 4D: could not write", name, ex)
    return None


def stop():
    if bpy.app.timers.is_registered(flush):
        bpy.app.timers.unregister(flush)
    flush()
