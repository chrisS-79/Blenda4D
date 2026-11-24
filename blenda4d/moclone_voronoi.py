# SPDX-License-Identifier: GPL-3.0-or-later
"""Voronoi Fracture: the objects under it are cut into cells around seed points (its Sources), and each cell is a
clone the effectors move.

The cutting is done here in Python when what it depends on changes (the children's shape and place, the sources, the
settings); the pieces go into the Voronoi Fracture's own mesh, each point marked with its piece number, and its node
group hands them to the effectors (moclone_pieces.py). Faces made by a cut are kept in a face selection "Inside"."""
import hashlib
import math
import random

import bpy
import bmesh
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

DIST_TYPES = [("UNIFORM", "Uniform", "Spread evenly through the box", 0), ("NORMAL", "Normal", "Gathered toward the middle", 1),
              ("INVERSE", "Inverse Normal", "Gathered toward the sides", 2), ("EXPONENTIAL", "Exponential", "Gathered toward the chosen sides", 3)]
AXIS_PULL = [("OFF", "Off", "", 0), ("PLUS", "+", "", 1), ("MINUS", "-", "", 2)]
SOURCE_KINDS = [("DISTRIBUTION", "Distribution Source", "Points scattered through the objects' box", 0),
                ("OBJECT", "Object", "The points of another object", 1)]
SORT_BY = [("NONE", "None", "", 0), ("X", "+X", "", 1), ("Y", "+Y", "", 2), ("Z", "+Z", "", 3), ("DIRECTION", "User Direction", "", 4),
           ("OBJECT", "Distance to Object", "", 5)]


def _rebuild(self, context):
    from . import generators
    generators.sync_all()


class B4DVorSource(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(default="Distribution Source")
    kind: bpy.props.EnumProperty(name="Type", items=SOURCE_KINDS, default="DISTRIBUTION", update=_rebuild)
    obj: bpy.props.PointerProperty(name="Object", type=bpy.types.Object, update=_rebuild, description="The object whose points are seeds")
    dist: bpy.props.EnumProperty(name="Distribution Type", items=DIST_TYPES, default="UNIFORM", update=_rebuild)
    deviation: bpy.props.FloatProperty(name="Standard Deviation", default=0.2, min=0.01, max=0.7, update=_rebuild)
    amount: bpy.props.IntProperty(name="Point Amount", default=20, min=2, max=200000, update=_rebuild)
    seed: bpy.props.IntProperty(name="Seed", default=1234567, min=0, update=_rebuild)
    inside: bpy.props.BoolProperty(name="Inside", default=True, update=_rebuild, description="Only seeds inside the objects")
    per_object: bpy.props.BoolProperty(name="Create Points Per Object", default=False, update=_rebuild,
                                       description="Each object gets its own box and Point Amount")
    pull_x: bpy.props.EnumProperty(name="X-Axis Affection", items=AXIS_PULL, default="PLUS", update=_rebuild)
    pull_y: bpy.props.EnumProperty(name="Y-Axis Affection", items=AXIS_PULL, default="OFF", update=_rebuild)
    pull_z: bpy.props.EnumProperty(name="Z-Axis Affection", items=AXIS_PULL, default="OFF", update=_rebuild)
    pos: bpy.props.FloatVectorProperty(name="P", size=3, default=(0.0, 0.0, 0.0), update=_rebuild, description="Moves the box (cm)")
    scale: bpy.props.FloatVectorProperty(name="S", size=3, default=(1.0, 1.0, 1.0), update=_rebuild, description="Sizes the box")


def props():
    for c in (B4DVorSource,):
        if not getattr(c, "is_registered", False):
            bpy.utils.register_class(c)
    O, P = bpy.types.Object, bpy.props
    O.b4d_vor_sources = P.CollectionProperty(type=B4DVorSource)
    O.b4d_vor_source_index = P.IntProperty()
    O.b4d_vor_colorize = P.BoolProperty(name="Colorize Fragments", default=True, update=_rebuild)
    O.b4d_vor_ngons = P.BoolProperty(name="Create N-gon Surfaces", default=False, update=_rebuild,
                                     description="Join the triangles of each cut face into one face")
    O.b4d_vor_offset = P.FloatProperty(name="Offset Fragments", default=0.0, min=0.0, update=_rebuild,
                                       description="Each piece shrinks back from its cut faces (cm): the gap is twice this")
    O.b4d_vor_hull = P.BoolProperty(name="Hull Only", default=False, update=_rebuild, description="Cut the surface only, like an eggshell")
    O.b4d_vor_thickness = P.FloatProperty(name="Thickness", default=0.0, update=_rebuild, description="Hull Only pieces get this thickness (cm)")
    O.b4d_vor_optimize = P.BoolProperty(name="Optimize and Close Holes", default=True, update=_rebuild,
                                        description="Join loose points and close open objects before cutting")
    O.b4d_vor_cell_scale = P.FloatVectorProperty(name="Scale Cells", size=3, default=(1.0, 1.0, 1.0), min=0.01, update=_rebuild,
                                                 description="Stretch the cells: above 1 longer, below 1 flatter")
    O.b4d_vor_sort = P.BoolProperty(name="Sort Result", default=False, update=_rebuild, description="Number the pieces in an order")
    O.b4d_vor_sort_by = P.EnumProperty(name="Sort Result by", items=SORT_BY[1:], default="X", update=_rebuild)
    O.b4d_vor_sort_dir = P.FloatVectorProperty(name="Direction", size=3, default=(0.0, 1.0, 0.0), update=_rebuild)
    O.b4d_vor_sort_obj = P.PointerProperty(name="Object", type=bpy.types.Object, update=_rebuild,
                                           description="Pieces farther from it get lower numbers")
    O.b4d_vor_invert = P.BoolProperty(name="Invert Sort", default=False, update=_rebuild)


PROPS = ("b4d_vor_colorize", "b4d_vor_ngons", "b4d_vor_offset", "b4d_vor_hull", "b4d_vor_thickness", "b4d_vor_optimize",
         "b4d_vor_cell_scale", "b4d_vor_sort", "b4d_vor_sort_by", "b4d_vor_sort_dir", "b4d_vor_sort_obj", "b4d_vor_invert")


# --- what the cut depends on ---------------------------------------------------------------------------------------

def _shown(v):
    """Shown (Y up) -> Blender."""
    return Vector((v[0], v[2], v[1]))


def _kid_meshes(gen):
    """[(child, bmesh in the Voronoi Fracture's space)] for each mesh child as it shows."""
    from . import generators as g
    dg = bpy.context.evaluated_depsgraph_get()
    inv = gen.matrix_world.inverted()
    out = []
    for c in g.kids_of(gen):
        if c.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT"):
            continue
        ev = c.evaluated_get(dg)
        try:
            me = ev.to_mesh()
        except RuntimeError:
            continue
        bm = bmesh.new(); bm.from_mesh(me)
        bm.transform(inv @ c.matrix_world)
        ev.to_mesh_clear()
        out.append((c, bm))
    return out


def signature(gen):
    from . import generators as g
    h = hashlib.md5()
    for c in g.kids_of(gen):
        h.update(c.name.encode())
        h.update(repr([round(x, 5) for row in (gen.matrix_world.inverted() @ c.matrix_world) for x in row]).encode())
        if c.type == "MESH":
            me = c.data
            h.update(f"{len(me.vertices)}:{len(me.polygons)}".encode())
            co = [0.0] * (len(me.vertices) * 3)
            me.vertices.foreach_get("co", co)
            h.update(repr([round(x, 5) for x in co[:3000]]).encode())
            h.update(repr([m.name if m else "" for m in me.materials]).encode())
    for s in gen.b4d_vor_sources:
        h.update(repr((s.kind, s.obj.name if s.obj else "", s.dist, s.deviation, s.amount, s.seed, s.inside, s.per_object,
                       s.pull_x, s.pull_y, s.pull_z, tuple(s.pos), tuple(s.scale))).encode())
        if s.kind == "OBJECT" and s.obj is not None:
            h.update(repr([round(x, 5) for row in s.obj.matrix_world for x in row]).encode())
    for p in PROPS:
        v = getattr(gen, p)
        h.update(repr(v.name if hasattr(v, "name") else (tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v)).encode())
    if gen.b4d_vor_sort_obj is not None:
        h.update(repr([round(x, 5) for x in gen.b4d_vor_sort_obj.matrix_world.translation]).encode())
    return h.hexdigest()[:16]


# --- seeds ---------------------------------------------------------------------------------------------------------

def _bounds(bms):
    lo = Vector((1e9, 1e9, 1e9)); hi = Vector((-1e9, -1e9, -1e9))
    for bm in bms:
        for v in bm.verts:
            lo = Vector(map(min, lo, v.co)); hi = Vector(map(max, hi, v.co))
    return lo, hi


def _inside(trees, p):
    """Inside a closed object: a ray out crosses its surface an odd number of times (two rays agree)."""
    for tree in trees:
        votes = 0
        for d in (Vector((0.3, 0.2, 1.0)).normalized(), Vector((-0.4, 0.9, -0.2)).normalized()):
            n, o = 0, p.copy()
            for _ in range(64):
                hit = tree.ray_cast(o, d)
                if hit[0] is None:
                    break
                n += 1
                o = hit[0] + d * 1e-5
            votes += n % 2
        if votes == 2:
            return True
    return False


def _scatter(s, lo, hi, trees, rng):
    size = (hi - lo)
    centre = (lo + hi) * 0.5 + _shown(s.pos) * 0.01
    size = Vector((size.x * s.scale[0], size.y * s.scale[2], size.z * s.scale[1]))
    pts = []
    tries = 0
    while len(pts) < s.amount and tries < s.amount * 60:
        tries += 1
        u = []
        for k in range(3):
            if s.dist == "UNIFORM":
                x = rng.random()
            elif s.dist == "NORMAL":
                x = min(max(rng.gauss(0.5, s.deviation), 0.0), 1.0)
            elif s.dist == "INVERSE":
                g = rng.gauss(0.0, s.deviation)
                x = min(max((0.0 if g < 0 else 1.0) - g, 0.0), 1.0)
            else:
                pull = (s.pull_x, s.pull_z, s.pull_y)[k]          # shown X, Y, Z -> Blender X, Z, Y
                e = min(rng.expovariate(1.0 / max(s.deviation, 1e-3)), 1.0)
                x = e if pull == "MINUS" else (1.0 - e if pull == "PLUS" else rng.random())
            u.append(x)
        p = Vector((centre.x + (u[0] - 0.5) * size.x, centre.y + (u[1] - 0.5) * size.y, centre.z + (u[2] - 0.5) * size.z))
        if s.inside and trees and not _inside(trees, p):
            continue
        pts.append(p)
    return pts


def _seeds(gen, kids):
    inv = gen.matrix_world.inverted()
    trees = [BVHTree.FromBMesh(bm) for _c, bm in kids]
    seeds = []
    for n, s in enumerate(gen.b4d_vor_sources):
        rng = random.Random(s.seed + 7919 * n)
        if s.kind == "OBJECT":
            if s.obj is None:
                continue
            m = inv @ s.obj.matrix_world
            if s.obj.type == "MESH":
                seeds += [m @ v.co for v in s.obj.data.vertices]
            else:
                seeds.append(m.translation.copy())
        elif s.per_object:
            for (_c, bm), tree in zip(kids, trees):
                lo, hi = _bounds([bm])
                seeds += _scatter(s, lo, hi, [tree], rng)
        else:
            lo, hi = _bounds([bm for _c, bm in kids])
            seeds += _scatter(s, lo, hi, trees, rng)
    return seeds


# --- cutting -------------------------------------------------------------------------------------------------------

INSIDE = "Inside"


def _cut_cell(src, i, seeds, kd, scale, offset, hull):
    """The part of src nearer to seeds[i] than to any other seed (in the stretched cell space), with its cut faces
    filled (not with Hull Only). Faces made here get the Inside mark."""
    bm = src.copy()
    lay = bm.faces.layers.int.get(INSIDE) or bm.faces.layers.int.new(INSIDE)
    p = seeds[i]
    near = kd.find_n(p, min(len(seeds), 48))
    for _co, j, _d in near:
        if j == i:
            continue
        q = seeds[j]
        # the bisecting plane in stretched space, back in real space
        ps, qs = Vector(p[k] / scale[k] for k in range(3)), Vector(q[k] / scale[k] for k in range(3))
        n_s = (qs - ps)
        if n_s.length < 1e-9:
            continue
        mid_s = (ps + qs) * 0.5 - n_s.normalized() * offset
        no = Vector(n_s[k] / scale[k] for k in range(3)).normalized()
        co = Vector(mid_s[k] * scale[k] for k in range(3))
        if all((v.co - co).dot(no) <= 0.0 for v in bm.verts):
            continue                                                   # wholly on this cell's side
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        res = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6, plane_co=co, plane_no=no, clear_outer=True)
        if not bm.verts:
            break
        if not hull:
            cut = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge) and e.is_boundary]
            if cut:
                made = bmesh.ops.holes_fill(bm, edges=cut, sides=0)
                for f in made["faces"]:
                    f[lay] = 1
    return bm


def compute(gen):
    """Cut the children into cells and write the pieces into the Voronoi Fracture's own mesh. The generators' sync
    is held off meanwhile: reading the children as they show updates the scene, which would start it again."""
    from . import generators as g
    held = g._busy[0]
    g._busy[0] = True
    try:
        _compute(gen)
    finally:
        g._busy[0] = held


def _compute(gen):
    kids = _kid_meshes(gen)
    me = gen.data
    out = bmesh.new()
    pl = out.verts.layers.int.new("b4d_piece")
    ol = out.faces.layers.int.new(INSIDE)
    mats = []
    for c, _bm in kids:
        for m in getattr(c.data, "materials", []):
            if m is not None and m not in mats:
                mats.append(m)
    if kids and not mats:
        from .moclone_pieces import piece_color_material
        mats = [piece_color_material()]
    scale = Vector((gen.b4d_vor_cell_scale[0], gen.b4d_vor_cell_scale[2], gen.b4d_vor_cell_scale[1]))
    offset = gen.b4d_vor_offset * 0.01
    hull = gen.b4d_vor_hull
    pieces = []                                                       # (centre, bmesh)
    if kids:
        seeds = _seeds(gen, kids)
        for c, bm in kids:
            if gen.b4d_vor_optimize:
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
                if not hull:
                    edges = [e for e in bm.edges if e.is_boundary]
                    if edges:
                        bmesh.ops.holes_fill(bm, edges=edges, sides=0)
            remap = {i: mats.index(m) for i, m in enumerate(getattr(c.data, "materials", [])) if m in mats}
            for f in bm.faces:
                f.material_index = remap.get(f.material_index, 0)
            if not seeds:
                pieces.append((Vector(), bm.copy()))
                continue
            kd = KDTree(len(seeds))
            for k, s in enumerate(seeds):
                kd.insert(s, k)
            kd.balance()
            for i in range(len(seeds)):
                cell = _cut_cell(bm, i, seeds, kd, scale, offset, hull)
                if cell.verts:
                    ctr = sum((v.co for v in cell.verts), Vector()) / len(cell.verts)
                    pieces.append((ctr, cell))
                else:
                    cell.free()
            bm.free()
    # Sorting: the order the pieces are numbered in
    if gen.b4d_vor_sort and pieces:
        by = gen.b4d_vor_sort_by
        if by == "OBJECT" and gen.b4d_vor_sort_obj is not None:
            t = gen.matrix_world.inverted() @ gen.b4d_vor_sort_obj.matrix_world.translation
            key = lambda pc: -(pc[0] - t).length
        else:
            d = {"X": Vector((1, 0, 0)), "Y": Vector((0, 0, 1)), "Z": Vector((0, 1, 0))}.get(by, _shown(gen.b4d_vor_sort_dir))
            key = lambda pc: pc[0].dot(d)
        pieces.sort(key=key, reverse=gen.b4d_vor_invert)
    elif gen.b4d_vor_invert:
        pieces.reverse()
    thick = gen.b4d_vor_thickness * 0.01
    for n, (_ctr, cell) in enumerate(pieces):
        if gen.b4d_vor_ngons and not hull:
            lay = cell.faces.layers.int.get(INSIDE)
            inner = [f for f in cell.faces if lay is not None and f[lay]]
            if inner:
                bmesh.ops.dissolve_limit(cell, angle_limit=0.0175, verts=[], edges=list({e for f in inner for e in f.edges}), delimit={"MATERIAL"})
        if hull and abs(thick) > 1e-9:
            bmesh.ops.solidify(cell, geom=cell.faces[:], thickness=thick)
        tmp = bpy.data.meshes.new(".b4d_vor_piece")
        cell.to_mesh(tmp)
        cell.free()
        base = len(out.verts)
        out.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        out.verts.ensure_lookup_table()
        for v in out.verts[base:]:
            v[pl] = n
    out.to_mesh(me)
    out.free()
    me.materials.clear()
    for m in mats:
        me.materials.append(m)
    # the cut faces as a face selection named Inside, the rest as Outside
    att = me.attributes.get(INSIDE)
    if att is not None and att.data_type != "BOOLEAN":
        vals = [0] * len(me.polygons)
        att.data.foreach_get("value", vals)
        me.attributes.remove(att)
        b = me.attributes.new(INSIDE, "BOOLEAN", "FACE"); b.data.foreach_set("value", [bool(x) for x in vals])
        o = me.attributes.new("Outside", "BOOLEAN", "FACE"); o.data.foreach_set("value", [not x for x in vals])
    gen["b4d_vor_sig"] = signature(gen)
    me.update()
