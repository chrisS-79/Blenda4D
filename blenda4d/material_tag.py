# SPDX-License-Identifier: GPL-3.0-or-later
"""Material tags: each material slot of an object shows as a tag in the Object Manager, with its own settings.

Clicking the material's swatch in an object's row makes that tag the Attribute Manager's subject: "Material Tag
[material]" with Basic, Tag and Coordinates pages. The settings belong to the object, not the material, so objects that
share one material can each tile, shift and project it their own way:

- every slot keeps a settings row on the object (ob.b4d_mat_tags), and _push() writes it as a few vectors in the
  object's custom properties, named after the material (b4d_tag_<material>_a ...);
- the material gets one small node group ("Blenda Tag Mapping") in front of each texture that is laid on the surface
  (image, checker, brick, gradient, wave, magic, and noise-like textures in 1D / 2D); Attribute nodes read the
  vectors from whichever object is being drawn and feed the group;
- an object with no values of its own reads zeros, and zeros change nothing: a material looks the same until a tag's
  numbers change.

Seamless turns on hex tiling for the material's images (material_tag_hex.py), driven per object the same way.
Nodes are added the first time a tag changes; nothing is added for a tag that is only looked at."""
import math
import re

import bpy

from . import material_tag_hex as hexes

MAP_GROUP = "Blenda Tag Mapping"
MARK = "b4d_tag"                 # on every node this module adds to a material
SUBJECT = "TAG"                  # wm.b4d_am_subject = "TAG:<object>:<slot>" while a tag is shown

PROJECTIONS = (("UV", "UV Mapping", "Use the object's own UV map", 0),
               ("FLAT", "Flat", "Project straight along the tag's Z axis, like a slide projector", 1),
               ("SPHERICAL", "Spherical", "Wrap the texture around a ball", 2),
               ("CYLINDRICAL", "Cylindrical", "Wrap the texture around a tube standing on the tag's Z axis", 3),
               ("CUBIC", "Cubic", "Project from six sides; each face takes the side it faces most", 4))
CODE = {p[0]: p[3] for p in PROJECTIONS}

# textures laid on the surface follow the tag; noise-like textures follow it only in 1D or 2D, in 3D / 4D they fill space
FLAT_TEXTURES = {"TEX_IMAGE", "TEX_CHECKER", "TEX_BRICK", "TEX_GRADIENT", "TEX_WAVE", "TEX_MAGIC"}
SPACE_TEXTURES = {"TEX_NOISE": "noise_dimensions", "TEX_VORONOI": "voronoi_dimensions",
                  "TEX_WHITE_NOISE": "noise_dimensions", "TEX_GABOR": "gabor_type"}


def follows_tag(n):
    vec = n.inputs.get("Vector")
    if vec is None or vec.type != "VECTOR" or not vec.enabled or n.get(MARK) or n.get(hexes.MARK):
        return False
    if n.type in FLAT_TEXTURES:
        return True
    if n.type in SPACE_TEXTURES:
        return getattr(n, SPACE_TEXTURES[n.type], "3D") in ("1D", "2D")
    return n.type == "GROUP" and n.node_tree is not None and any(o.type in ("SHADER", "RGBA") for o in n.outputs)


def _key(mat):
    return re.sub(r"\W", "_", mat.name)


def prefix(mat):
    return "b4d_tag_" + _key(mat)


# --- the per-object values ------------------------------------------------------------------------------------
def _push(ob, index):
    """Write tag `index` of `ob` into the object's custom properties the material's nodes read."""
    if index >= len(ob.b4d_mat_tags) or index >= len(ob.material_slots):
        return
    mat = ob.material_slots[index].material
    if mat is None:
        return
    t = ob.b4d_mat_tags[index]
    p = prefix(mat)
    ob[p + "_a"] = [t.offset_u * 0.01, t.offset_v * 0.01, 0.0 if t.tile else 1.0]
    ob[p + "_b"] = [100.0 / max(t.length_u, 1e-3) - 1.0, 100.0 / max(t.length_v, 1e-3) - 1.0, 0.0]
    ob[p + "_c"] = [float(CODE[t.projection]), 0.0, 0.0]
    ob[p + "_p"] = list(t.position)
    ob[p + "_r"] = list(t.rotation)
    ob[p + "_s"] = list(t.size)
    if t.seamless:
        ob[p + "_hx"] = [t.hex_turn, t.hex_shift * 0.01, t.hex_size * 0.01]
        ob[p + "_hy"] = [t.hex_blend * 0.01, t.hex_sharpness * 0.01, float(t.hex_seed)]
        ob[p + "_hz"] = [t.hex_patch * 0.01, 0.0, 0.0]
    else:
        ob[p + "_hx"] = [0.0, 0.0, 0.0]
        ob[p + "_hy"] = [0.15, 0.7, 0.0]
        ob[p + "_hz"] = [1.0, 0.0, 0.0]
    t.wired = mat.name
    ob.update_tag()


def _tag_users(mat):
    """(object, slot index) of every touched tag that uses this material."""
    out = []
    for ob in bpy.data.objects:
        tags = getattr(ob, "b4d_mat_tags", ())
        for i, sl in enumerate(ob.material_slots):
            if sl.material == mat and i < len(tags) and tags[i].wired:
                out.append((ob, i))
    return out


# --- the material's nodes -------------------------------------------------------------------------------------
def _mapping_group():
    tree = bpy.data.node_groups.get(MAP_GROUP)
    if tree is not None:
        return tree
    vec = "NodeSocketVector"
    g, i, o = hexes._new_group(MAP_GROUP, [(n, vec, None, None, None) for n in (
        "Coordinates", "Object", "Normal", "Offset Tile", "Tiles", "Projection", "Position", "Rotation", "Size")],
        [("Vector", vec), ("Mask", "NodeSocketFloat")])
    i = {s.name: s for s in i if s.name}
    rel = g.v("SUBTRACT", i["Object"], i["Position"])
    turn = g.node("ShaderNodeVectorRotate", rotation_type="EULER_XYZ", invert=True)
    g.put(turn.inputs["Vector"], rel)
    g.put(turn.inputs["Rotation"], i["Rotation"])
    q = g.v("DIVIDE", turn.outputs[0], g.v("MAXIMUM", i["Size"], 1e-4))
    nturn = g.node("ShaderNodeVectorRotate", rotation_type="EULER_XYZ", invert=True)
    g.put(nturn.inputs["Vector"], i["Normal"])
    g.put(nturn.inputs["Rotation"], i["Rotation"])
    qx, qy, qz = g.sep(q)
    flat = g.comb(g.m("ADD", qx, 0.5), g.m("ADD", qy, 0.5))
    around = g.m("MULTIPLY_ADD", g.m("ARCTAN2", qy, qx), 1.0 / (2 * math.pi), 0.5)
    up = g.m("DIVIDE", qz, g.m("MAXIMUM", g.v("LENGTH", q), 1e-6))
    up = g.m("MINIMUM", g.m("MAXIMUM", up, -1.0), 1.0)
    sph = g.comb(around, g.m("MULTIPLY_ADD", g.m("ARCSINE", up), 1.0 / math.pi, 0.5))
    cyl = g.comb(around, g.m("ADD", qz, 0.5))
    ax, ay, az = g.sep(g.v("ABSOLUTE", nturn.outputs[0]))
    wx = g.m("MULTIPLY", g.m("SUBTRACT", 1.0, g.m("LESS_THAN", ax, ay)), g.m("SUBTRACT", 1.0, g.m("LESS_THAN", ax, az)))
    wy = g.m("MULTIPLY", g.m("SUBTRACT", 1.0, wx), g.m("SUBTRACT", 1.0, g.m("LESS_THAN", ay, az)))
    wz = g.m("SUBTRACT", g.m("SUBTRACT", 1.0, wx), wy)
    cu = g.m("MULTIPLY_ADD", wx, g.m("SUBTRACT", qy, qx), qx)                  # x side: (y, z); y and z sides: x
    cv = g.m("MULTIPLY_ADD", wz, g.m("SUBTRACT", qy, qz), qz)                  # z side: y; x and y sides: z
    cub = g.comb(g.m("ADD", cu, 0.5), g.m("ADD", cv, 0.5))
    code, _y, _z = g.sep(i["Projection"])
    proj = g.v("SCALE", i["Coordinates"], scale=g.m("LESS_THAN", code, 0.5))
    for k, vec_k in ((1, flat), (2, sph), (3, cyl), (4, cub)):
        proj = g.v("ADD", proj, g.v("SCALE", vec_k, scale=g.m("COMPARE", code, float(k), 0.5)))
    ou, ov, notile = g.sep(i["Offset Tile"])
    tu, tv, _t = g.sep(i["Tiles"])
    t = g.v("MULTIPLY", g.v("SUBTRACT", proj, g.comb(ou, ov)), g.comb(g.m("ADD", tu, 1.0), g.m("ADD", tv, 1.0), 1.0))
    g.put(o["Vector"], t)
    tx, ty, _z = g.sep(t)
    inside = g.m("MULTIPLY", g.m("MULTIPLY", g.m("GREATER_THAN", tx, -1e-6), g.m("LESS_THAN", tx, 1.000001)),
                 g.m("MULTIPLY", g.m("GREATER_THAN", ty, -1e-6), g.m("LESS_THAN", ty, 1.000001)))
    g.put(o["Mask"], g.m("MAXIMUM", g.m("SUBTRACT", 1.0, notile), inside))
    return g.tree


ATTRS = (("Offset Tile", "a"), ("Tiles", "b"), ("Projection", "c"), ("Position", "p"), ("Rotation", "r"), ("Size", "s"))


def _rename_keys(mat):
    """A renamed or copied material reads values named after its new name."""
    old, new = mat.get("b4d_tag_key"), prefix(mat)
    if old and old != new:
        for n in mat.node_tree.nodes:
            if n.type == "ATTRIBUTE" and n.attribute_name.startswith(old + "_"):
                n.attribute_name = new + n.attribute_name[len(old):]
    mat["b4d_tag_key"] = new


def _shared_nodes(mat):
    """The material's one Texture Coordinate and Attribute nodes all its tag groups read."""
    nt = mat.node_tree
    found = {n.get(MARK): n for n in nt.nodes if isinstance(n.get(MARK), str)}
    p = prefix(mat)
    if "coords" not in found:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        tc[MARK], tc.label, tc.location = "coords", "Tag Coordinates", (-900, 300)
        found["coords"] = tc
    for k, (_name, part) in enumerate(ATTRS):
        if part not in found:
            a = nt.nodes.new("ShaderNodeAttribute")
            a.attribute_type, a.attribute_name = "OBJECT", f"{p}_{part}"
            a[MARK], a.label, a.location = part, "Tag " + _name, (-900, 100 - 120 * k)
            found[part] = a
    return found


def _mapped(sock):
    return sock.links and (sock.links[0].from_node.get(MARK) or sock.links[0].from_node.get(hexes.MARK))


def _ensure_nodes(mat, need_mask):
    nt = mat.node_tree
    _rename_keys(mat)
    shared = None
    group = _mapping_group()
    for n in [n for n in nt.nodes if follows_tag(n)]:
        sock = n.inputs["Vector"]
        if not _mapped(sock):
            shared = shared or _shared_nodes(mat)
            tc = shared["coords"]
            src = sock.links[0].from_socket if sock.links else tc.outputs["UV" if n.type in ("TEX_IMAGE", "GROUP") else "Generated"]
            m = nt.nodes.new("ShaderNodeGroup")
            m.node_tree, m[MARK], m.label = group, "map", "Tag Mapping"
            m.location = (n.location.x - 220, n.location.y)
            nt.links.new(src, m.inputs["Coordinates"])
            nt.links.new(tc.outputs["Object"], m.inputs["Object"])
            nt.links.new(tc.outputs["Normal"], m.inputs["Normal"])
            for name, part in ATTRS:
                nt.links.new(shared[part].outputs["Vector"], m.inputs[name])
            nt.links.new(m.outputs["Vector"], sock)
            if n.type == "TEX_IMAGE":
                n.extension = "REPEAT"
        if need_mask:
            _mask_outputs(nt, n)


def _map_of(n):
    """The tag group in front of texture n (through the seamless nodes, if any)."""
    sock = n.inputs["Vector"]
    for _ in range(4):
        if not sock.links:
            return None
        src = sock.links[0].from_node
        if src.get(MARK) == "map":
            return src
        if not src.get(hexes.MARK) or "Vector" not in src.inputs:
            return None
        sock = src.inputs["Vector"]
    return None


def _mask_outputs(nt, n):
    """Tile off: the texture shows once; outside its square the texture's outputs read 0 for this object."""
    m = _map_of(n)
    if m is None:
        return
    for out in n.outputs:
        if out.type not in ("RGBA", "VALUE", "VECTOR"):
            continue
        for lk in list(out.links):
            to = lk.to_node
            if to.get(MARK) == "mask" or to.get(hexes.MARK):
                continue
            if out.type == "VALUE":
                k = nt.nodes.new("ShaderNodeMath")
                k.operation = "MULTIPLY"
                nt.links.new(out, k.inputs[0])
                nt.links.new(m.outputs["Mask"], k.inputs[1])
            else:
                k = nt.nodes.new("ShaderNodeVectorMath")
                k.operation = "SCALE"
                nt.links.new(out, k.inputs[0])
                nt.links.new(m.outputs["Mask"], k.inputs["Scale"])
            k[MARK], k.label = "mask", "Tag Tile Off"
            k.location = (n.location.x + 260, n.location.y)
            nt.links.new(k.outputs[0], lk.to_socket)


def wire(mat):
    """Bring the material's nodes and every object's values up to date with the tags that use it."""
    if mat is None or mat.node_tree is None:
        return
    users = _tag_users(mat)
    for ob, i in users:
        _push(ob, i)
    nt = mat.node_tree
    if not nt.is_editable or mat.library is not None:
        return
    tags = [ob.b4d_mat_tags[i] for ob, i in users]
    _ensure_nodes(mat, need_mask=any(not t.tile for t in tags))
    seamless = any(t.seamless for t in tags)
    if seamless and not hexes.built(mat):
        hexes.apply(mat, prefix(mat))
    elif not seamless and hexes.built(mat):
        hexes.remove(mat)
    elif seamless:
        hexes.sync(mat, prefix(mat))
    mat.update_tag()


def _owner(tag):
    ob = tag.id_data
    m = re.search(r"\[(\d+)\]", tag.path_from_id())
    return ob, int(m.group(1)) if m else 0


def _changed(self, context):
    ob, i = _owner(self)
    if i < len(ob.material_slots) and ob.material_slots[i].material is not None:
        self.wired = ob.material_slots[i].material.name
        wire(ob.material_slots[i].material)


def _tiles_get(axis):
    return lambda self: 100.0 / max(getattr(self, "length_" + axis), 1e-3)


def _tiles_set(axis):
    def put(self, v):
        setattr(self, "length_" + axis, 100.0 / max(v, 1e-3))
    return put


def _pct(name, default, desc, lo=None, hi=None, soft=(None, None)):
    kw = {k: v for k, v in (("min", lo), ("max", hi), ("soft_min", soft[0]), ("soft_max", soft[1])) if v is not None}
    return bpy.props.FloatProperty(name=name, default=default, subtype="PERCENTAGE", precision=1, description=desc,
                                   update=_changed, **kw)


class BLENDA4D_PG_mat_tag(bpy.types.PropertyGroup):
    wired: bpy.props.StringProperty(options={"HIDDEN"})          # the material the values were last written for
    tile: bpy.props.BoolProperty(name="Tile", default=True, update=_changed,
                                 description="Repeat the texture across the surface; off shows it once and the texture reads black around it")
    seamless: bpy.props.BoolProperty(name="Seamless", default=False, update=_changed,
                                     description="Hide the repeats: the image is laid in randomly turned, softly blended patches")
    offset_u: _pct("Offset U", 0.0, "Move the texture sideways, in percent of its width", soft=(-100.0, 100.0))
    offset_v: _pct("Offset V", 0.0, "Move the texture up or down, in percent of its height", soft=(-100.0, 100.0))
    length_u: _pct("Length U", 100.0, "How wide one copy of the texture is, in percent of the surface: 50 % fits two across",
                   lo=0.01, soft=(1.0, 200.0))
    length_v: _pct("Length V", 100.0, "How tall one copy of the texture is, in percent of the surface: 50 % fits two",
                   lo=0.01, soft=(1.0, 200.0))
    tiles_u: bpy.props.FloatProperty(name="Tiles U", get=_tiles_get("u"), set=_tiles_set("u"), min=0.01, soft_max=100.0,
                                     description="How many copies fit across: the same setting as Length U, counted")
    tiles_v: bpy.props.FloatProperty(name="Tiles V", get=_tiles_get("v"), set=_tiles_set("v"), min=0.01, soft_max=100.0,
                                     description="How many copies fit from bottom to top: the same setting as Length V, counted")
    projection: bpy.props.EnumProperty(name="Projection", items=PROJECTIONS, default="UV", update=_changed,
                                       description="How the texture is laid onto the object")
    position: bpy.props.FloatVectorProperty(name="Position", subtype="TRANSLATION", size=3, update=_changed,
                                            description="Centre of the projection, in the object's own space")
    rotation: bpy.props.FloatVectorProperty(name="Rotation", subtype="EULER", size=3, update=_changed,
                                            description="Turn of the projection, in the object's own space")
    size: bpy.props.FloatVectorProperty(name="Size", subtype="XYZ_LENGTH", size=3, default=(2.0, 2.0, 2.0), min=1e-4,
                                        update=_changed, description="How big the projection is: one copy of the texture spans it")
    hex_blend: _pct("Blend", 15.0, "How wide the soft edge between patches is", lo=0.0, hi=100.0)
    hex_sharpness: _pct("Blend Sharpness", 70.0, "Higher makes the edge between patches crisper", lo=0.0, hi=99.0)
    hex_patch: _pct("Patch Size", 100.0, "Size of one patch, in percent of one copy of the texture", lo=5.0, hi=2000.0,
                    soft=(5.0, 400.0))
    hex_turn: bpy.props.FloatProperty(name="Random Turn", default=180.0, min=0.0, max=180.0, precision=0, update=_changed,
                                      description="How far each patch may be turned, in degrees either way")
    hex_shift: _pct("Random Shift", 100.0, "How far each patch may be moved", lo=0.0, hi=100.0)
    hex_size: _pct("Random Size", 0.0, "How much each patch's size may vary", lo=0.0, hi=100.0)
    hex_seed: bpy.props.IntProperty(name="Seed", default=0, min=0, max=100000, update=_changed,
                                    description="Another number gives another random layout")


def ensure(ob):
    """Writes data: call it from an operator, handler or timer, never while drawing."""
    while len(ob.b4d_mat_tags) < len(ob.material_slots):
        ob.b4d_mat_tags.add()


# --- what the Attribute Manager shows ---------------------------------------------------------------------------
def subject(context):
    """(object, slot index) of the tag the Attribute Manager shows, or None."""
    s = getattr(context.window_manager, "b4d_am_subject", "")
    if not s.startswith(SUBJECT + ":"):
        return None
    name, _sep, idx = s[len(SUBJECT) + 1:].rpartition(":")
    ob = bpy.data.objects.get(name)
    if ob is None or ob != context.view_layer.objects.active or not idx.isdigit() or int(idx) >= len(ob.material_slots):
        return None
    return ob, int(idx)


def is_picked(context, ob, index):
    return subject(context) == (ob, index)


def om_tag_button(layout, ob, index, mat):
    """The swatch after an object's row in the Object Manager: a button that shows this tag's settings."""
    picked = is_picked(bpy.context, ob, index)
    from . import matman
    iv = matman.tile_icon(mat, False, 64, layout) if any(fn(mat) is not None for fn in matman.BALLS) else layout.icon(mat)
    op = layout.operator("blenda4d.mat_tag_pick", text="", icon_value=iv, emboss=picked, depress=picked)
    op.name, op.slot = ob.name, index


class BLENDA4D_OT_mat_tag_pick(bpy.types.Operator):
    bl_idname = "blenda4d.mat_tag_pick"
    bl_label = "Material Tag"
    bl_description = "Show this material tag's settings in the Attribute Manager"
    bl_options = {"UNDO"}
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})
    slot: bpy.props.IntProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None or self.slot >= len(ob.material_slots):
            return {"CANCELLED"}
        if context.mode != "OBJECT" and context.view_layer.objects.active != ob:
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in context.view_layer.objects.selected:
            if o != ob:
                o.select_set(False)
        try:
            ob.select_set(True)
        except RuntimeError:
            return {"CANCELLED"}
        context.view_layer.objects.active = ob
        ensure(ob)
        context.window_manager.b4d_am_subject = f"{SUBJECT}:{ob.name}:{self.slot}"
        for a in context.screen.areas if context.screen else ():
            a.tag_redraw()
        return {"FINISHED"}


class BLENDA4D_OT_mat_tag_fit(bpy.types.Operator):
    bl_idname = "blenda4d.mat_tag_fit"
    bl_label = "Fit to Object"
    bl_description = "Centre the projection on the object and make it as big as the object"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})
    slot: bpy.props.IntProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None or ob.type != "MESH" or not len(ob.data.vertices):
            return {"CANCELLED"}
        ensure(ob)
        t = ob.b4d_mat_tags[self.slot]
        n = len(ob.data.vertices)
        co = [0.0] * (n * 3)
        ob.data.vertices.foreach_get("co", co)
        lo = [min(co[k::3]) for k in range(3)]
        hi = [max(co[k::3]) for k in range(3)]
        t.rotation = (0.0, 0.0, 0.0)
        t.position = [(a + b) / 2 for a, b in zip(lo, hi)]
        t.size = [max(b - a, 1e-3) for a, b in zip(lo, hi)]
        return {"FINISHED"}


TABS = [("BASIC", "Basic", "The tag's name and material"), ("TAG", "Tag", "Tiling and seamless"),
        ("COORD", "Coordinates", "How the texture is projected onto the object")]
HEX_ROWS = ("hex_blend", "hex_sharpness", "hex_patch", "hex_turn", "hex_shift", "hex_size", "hex_seed")


def page_basic(col, ob, index, tag):
    slot = ob.material_slots[index]
    if slot.material is not None:
        col.prop(slot.material, "name", text="Name")
    col.prop(slot, "material", text="Material")


def page_tag(col, ob, index, tag):
    col.prop(tag, "tile")
    col.prop(tag, "seamless")
    if tag.seamless:
        sub = col.column(align=True)
        for p in HEX_ROWS:
            sub.prop(tag, p)
    col.separator()
    sub = col.column(align=True)
    sub.prop(tag, "offset_u")
    sub.prop(tag, "offset_v")
    col.separator()
    sub = col.column(align=True)
    sub.prop(tag, "length_u")
    sub.prop(tag, "length_v")
    sub = col.column(align=True)
    sub.prop(tag, "tiles_u")
    sub.prop(tag, "tiles_v")


def page_coord(col, ob, index, tag):
    col.prop(tag, "projection")
    sub = col.column()
    sub.active = tag.projection != "UV"
    sub.prop(tag, "position")
    sub.prop(tag, "rotation")
    sub.prop(tag, "size")
    row = sub.row()
    op = row.operator("blenda4d.mat_tag_fit", icon="PIVOT_BOUNDBOX")
    op.name, op.slot = ob.name, index
    row.enabled = ob.type == "MESH"


PAGES = {"BASIC": page_basic, "TAG": page_tag, "COORD": page_coord}
TITLES = {"BASIC": "Basic Properties", "TAG": "Tag Properties", "COORD": "Coordinates"}


def draw_subject(layout, context, ob):
    """The Attribute Manager's page while a material tag is its subject. True when it drew."""
    found = subject(context)
    if found is None or found[0] != ob:
        return False
    ob, index = found
    mat = ob.material_slots[index].material
    head = layout.row(align=True)
    name = mat.name if mat else "Empty"
    if mat is not None:
        head.label(text=f"Material Tag [{name}]", icon_value=layout.icon(mat))
    else:
        head.label(text=f"Material Tag [{name}]", icon="MATERIAL")
    wm = context.window_manager
    layout.row(align=True).prop(wm, "b4d_tag_tab", expand=True)
    tab = wm.b4d_tag_tab
    layout.separator(factor=0.5)
    layout.label(text=TITLES[tab])
    if index >= len(ob.b4d_mat_tags):         # new data cannot be made while drawing: make it right after
        bpy.app.timers.register(lambda o=ob.name: (ensure(bpy.data.objects[o]) if o in bpy.data.objects else None), first_interval=0.01)
        return True
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = True
    if mat is not None and (mat.library is not None or (mat.node_tree is not None and not mat.node_tree.is_editable)) and tab != "BASIC":
        col.label(text="This material comes from a library file and cannot change", icon="LIBRARY_DATA_DIRECT")
    PAGES[tab](col, ob, index, ob.b4d_mat_tags[index])
    return True


# --- keeping things current -------------------------------------------------------------------------------------
@bpy.app.handlers.persistent
def _after_update(scene, depsgraph=None):
    """A slot that got another material: the tag's values follow it. A tag whose object lost the selection: the
    Attribute Manager goes back to the object."""
    wm = bpy.context.window_manager
    s = getattr(wm, "b4d_am_subject", "")
    if s.startswith(SUBJECT + ":"):
        name = s[len(SUBJECT) + 1:].rpartition(":")[0]
        active = bpy.context.view_layer.objects.active if bpy.context.view_layer else None
        if active is None or active.name != name:
            wm.b4d_am_subject = ""
    for ob in scene.objects:
        tags = getattr(ob, "b4d_mat_tags", ())
        for i, t in enumerate(tags):
            if t.wired and i < len(ob.material_slots):
                mat = ob.material_slots[i].material
                if mat is not None and mat.name != t.wired:
                    wire(mat)


def _animated(ob):
    ad = ob.animation_data
    return ad is not None and ad.action is not None and any(
        fc.data_path.startswith("b4d_mat_tags") for fc in getattr(ad.action, "fcurves", ()))


@bpy.app.handlers.persistent
def _frame(scene, *_a):
    """Keyframed tag settings: their values reach the nodes on every frame."""
    for ob in scene.objects:
        if len(getattr(ob, "b4d_mat_tags", ())) and _animated(ob):
            for i, t in enumerate(ob.b4d_mat_tags):
                if t.wired:
                    _push(ob, i)


classes = (BLENDA4D_PG_mat_tag, BLENDA4D_OT_mat_tag_pick, BLENDA4D_OT_mat_tag_fit)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.b4d_mat_tags = bpy.props.CollectionProperty(description="The object's material tags", type=BLENDA4D_PG_mat_tag)
    bpy.types.WindowManager.b4d_tag_tab = bpy.props.EnumProperty(description="The page of the tag's settings that is shown", items=TABS, default="TAG", name="Page")
    from . import managers
    managers.AM_SUBJECTS[SUBJECT] = draw_subject
    managers.OM_TAG_BUTTON[:] = [om_tag_button]
    for h, fn in ((bpy.app.handlers.depsgraph_update_post, _after_update), (bpy.app.handlers.frame_change_post, _frame)):
        if fn not in h:
            h.append(fn)


def unregister():
    for h, fn in ((bpy.app.handlers.depsgraph_update_post, _after_update), (bpy.app.handlers.frame_change_post, _frame)):
        if fn in h:
            h.remove(fn)
    from . import managers
    managers.AM_SUBJECTS.pop(SUBJECT, None)
    managers.OM_TAG_BUTTON.clear()
    del bpy.types.WindowManager.b4d_tag_tab
    del bpy.types.Object.b4d_mat_tags
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
