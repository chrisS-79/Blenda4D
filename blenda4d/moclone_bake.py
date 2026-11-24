# SPDX-License-Identifier: GPL-3.0-or-later
"""Things the clone nodes can't read live, kept as small float images the nodes sample: an object's keyframed motion
(Inheritance, Animation mode) and a sound's loudness per pitch range (Sound effector). The images are made again when
what they hold changes, and when a file is opened (an image made in Blender keeps no pixels in the file)."""
import hashlib
import os

import bpy

_fresh = set()          # images filled since Blender started or the file was opened
_errors = {}            # effector name -> why its sound could not be read

CHANNELS = (("location", 3), ("rotation_euler", 3), ("scale", 3))
COLS = 32               # pitch steps per probe for Step sampling


def _image(name, w, h):
    img = bpy.data.images.get(name)
    if img is not None and (img.size[0] != w or img.size[1] != h):
        bpy.data.images.remove(img); img = None
    if img is None:
        img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=True)
        img.colorspace_settings.is_data = True
    return img


def _fill(img, rows):
    """rows: one list of (r, g, b, a) per image row, bottom row first."""
    flat = [c for row in rows for px in row for c in px]
    img.pixels.foreach_set(flat)
    img.update()
    _fresh.add(img.name)


# --- keyframed motion ------------------------------------------------------------------------------------------------

def motion_curves(src):
    ad = getattr(src, "animation_data", None)
    if ad is None or ad.action is None:
        return {}
    curves = None
    try:
        from bpy_extras import anim_utils
        bag = anim_utils.action_get_channelbag_for_slot(ad.action, ad.action_slot)
        curves = list(bag.fcurves) if bag is not None else []
    except Exception:
        curves = list(getattr(ad.action, "fcurves", []))
    want = {p for p, _n in CHANNELS}
    return {(fc.data_path, fc.array_index): fc for fc in curves if fc.data_path in want}


def motion_key(e):
    src = getattr(e, "b4d_fx_inherit", None)
    if src is None or e.b4d_fx_inh_mode != "ANIMATION":
        return ""
    h = hashlib.md5()
    for (path, i), fc in sorted(motion_curves(src).items()):
        h.update(f"{path}{i}".encode())
        for k in fc.keyframe_points:
            h.update(repr((tuple(k.co), tuple(k.handle_left), tuple(k.handle_right), k.interpolation)).encode())
    return h.hexdigest()[:12]


def motion_image(e):
    """(image, 0, columns - 1): one column per frame of the keyframed range; rows: place, rotation, scale."""
    src = e.b4d_fx_inherit
    curves = motion_curves(src) if src is not None else {}
    if not curves:
        return None, 0, 0
    a0 = min(min(k.co[0] for k in fc.keyframe_points) for fc in curves.values() if len(fc.keyframe_points))
    a1 = max(max(k.co[0] for k in fc.keyframe_points) for fc in curves.values() if len(fc.keyframe_points))
    n = max(2, min(int(round(a1 - a0)) + 1, 2048))
    name = f".b4d_motion_{e.name}"
    key = motion_key(e)
    img = bpy.data.images.get(name)
    if img is not None and img.get("b4d_key") == key and name in _fresh and img.size[0] == n:
        return img, 0, n - 1
    img = _image(name, n, 3)
    rows = []
    for path, size in CHANNELS:
        row = []
        for c in range(n):
            f = a0 + (a1 - a0) * c / (n - 1)
            v = [curves[(path, i)].evaluate(f) if (path, i) in curves else getattr(src, path)[i] for i in range(size)]
            row.append((v[0], v[1], v[2], 1.0))
        rows.append(row)
    _fill(img, rows)
    img["b4d_key"] = key
    return img, 0, n - 1


# --- sound -----------------------------------------------------------------------------------------------------------

def _path(e):
    p = getattr(e, "b4d_fx_sound", "")
    return bpy.path.abspath(p) if p else ""


def sound_key(e):
    p = _path(e)
    if not p:
        return ""
    try:
        st = os.stat(p); stamp = f"{st.st_mtime}:{st.st_size}"
    except OSError:
        stamp = "missing"
    sc = bpy.context.scene
    probes = [(q.low_freq, q.high_freq, q.low_loud, q.high_loud, q.sampling, q.decay, q.strength, q.clamp, q.color_mode, tuple(q.color))
              for q in e.b4d_fx_probes]
    raw = repr((p, stamp, e.b4d_fx_snd_channels, probes, sc.render.fps, sc.render.fps_base, sc.frame_start, sc.frame_end))
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def sound_error(e):
    return _errors.get(e.name)


def _decode(path, channels):
    import aud
    import numpy as np
    snd = aud.Sound(path)
    rate = int(snd.specs[0])
    data = np.asarray(snd.data(), dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    if channels == "LEFT":
        mono = data[:, 0]
    elif channels == "RIGHT":
        mono = data[:, min(1, data.shape[1] - 1)]
    else:
        mono = data.mean(axis=1)
    return mono, rate


def _spectra(mono, rate, first, frames, fps):
    """Loudness (0..100) per frame and frequency, with the frequencies."""
    import numpy as np
    N = 4096
    win = np.hanning(N).astype(np.float32)
    centres = ((np.arange(frames) / fps) * rate).astype(np.int64)
    padded = np.concatenate([np.zeros(N // 2, np.float32), mono, np.zeros(N, np.float32)])
    out = np.empty((frames, N // 2 + 1), np.float32)
    for s in range(0, frames, 256):
        idx = centres[s:s + 256, None] + np.arange(N)[None, :]
        idx = np.clip(idx, 0, len(padded) - 1)
        out[s:s + 256] = np.abs(np.fft.rfft(padded[idx] * win, axis=1))
    ref = max(float(out.max()), 1e-9)
    db = 20.0 * np.log10(out / ref + 1e-9)
    loud = np.clip((db + 80.0) / 80.0, 0.0, 1.0) * 100.0
    return loud, np.fft.rfftfreq(N, 1.0 / rate)


def sound_image(e):
    """(image, probes, columns per probe, frames, first frame) or (None, ...) without a readable sound or probes."""
    import numpy as np
    _errors.pop(e.name, None)
    path, probes = _path(e), list(e.b4d_fx_probes)
    if not path or not probes:
        return None, 0, COLS, 1, 1
    sc = bpy.context.scene
    first, frames = sc.frame_start, max(1, min(sc.frame_end - sc.frame_start + 1, 50000))
    name = f".b4d_sound_{e.name}"
    key = sound_key(e)
    P = len(probes)
    img = bpy.data.images.get(name)
    if img is not None and img.get("b4d_key") == key and name in _fresh and img.size[0] == frames:
        return img, P, COLS, frames, first
    try:
        mono, rate = _decode(path, e.b4d_fx_snd_channels)
    except Exception as ex:
        _errors[e.name] = f"The sound could not be read: {ex}"[:120]
        return None, 0, COLS, 1, 1
    fps = sc.render.fps / sc.render.fps_base
    loud, freqs = _spectra(mono, rate, first, frames, fps)
    rows = np.zeros((P * COLS + P, frames, 4), np.float32)
    rows[..., 3] = 1.0
    for p, q in enumerate(probes):
        lo, hi = sorted((q.low_freq, q.high_freq))
        span = max(q.high_loud - q.low_loud, 1e-3)
        val = (loud - q.low_loud) / span
        val = np.clip(val, 0.0, 1.0) if q.clamp else np.maximum(val, 0.0)

        def band(a, b):
            m = (freqs >= a) & (freqs <= b)
            if not m.any():
                m = np.zeros_like(freqs, bool); m[int(np.argmin(np.abs(freqs - (a + b) / 2)))] = True
            return val[:, m]

        if q.sampling == "STEP":
            edges = np.geomspace(max(lo, 1.0), max(hi, lo + 1.0), COLS + 1)
            cols = np.stack([band(edges[k], edges[k + 1]).max(axis=1) for k in range(COLS)], axis=1)
        else:
            b = band(lo, hi)
            v = b.max(axis=1) if q.sampling == "PEAK" else b.mean(axis=1)
            cols = np.repeat(v[:, None], COLS, axis=1)
        if q.decay > 0:
            k = q.decay / 100.0
            for t in range(1, frames):
                cols[t] = np.maximum(cols[t], cols[t - 1] * k)
        cols = cols * (q.strength / 100.0)
        for c in range(COLS):
            rows[p * COLS + c, :, 0] = cols[:, c]
        rows[P * COLS + p, :, :3] = q.color
        rows[P * COLS + p, :, 3] = 1.0 if q.color_mode == "CUSTOM" else 0.0
    img = _image(name, frames, P * COLS + P)
    img.pixels.foreach_set(rows.reshape(-1))
    img.update()
    _fresh.add(img.name)
    img["b4d_key"] = key
    return img, P, COLS, frames, first


def refresh_all():
    """After a file opens: fill the images again (their pixels aren't saved), then let the Cloners update."""
    _fresh.clear()
    from . import moclone_fx as fx
    for ob in bpy.data.objects:
        k = ob.get("b4d_type")
        try:
            if k == "fx_inherit" and ob.b4d_fx_inh_mode == "ANIMATION":
                motion_image(ob)
            elif k == "fx_sound":
                sound_image(ob)
        except Exception as ex:
            print("Blenda 4D: could not refill", ob.name, ex)
    for ob in bpy.data.objects:
        from .moclone_gens import FX_GENS
        if ob.get("b4d_type") in FX_GENS:
            ob.update_tag()
