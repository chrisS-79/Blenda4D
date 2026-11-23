# SPDX-License-Identifier: GPL-3.0-or-later
"""Tags that fields can drive: Vertex Map, Vertex Color, Point / Edge / Polygon Selection and Normal (Other
Tags, with Transfer: Off or Fields), MoClone Weightmap and MoClone Selection (MoClone Tags, with Use Fields) and Field
Driver (Animation Tags, always fields).

Each tag is an entry in the object's b4d_ftags list with its own Fields list. On a mesh, one Geometry Nodes modifier at
the top of the stack ("Blenda Field Tags") writes what the tags give, so the modifiers after it and the materials can
use it:
  Vertex Map         a vertex group named after the tag (its weight per point), for cloth pinning, deformers, masks
  Vertex Color       a colour attribute named after the tag (the tag's colour times the field, the field as alpha)
  Point / Edge / Polygon Selection  a true/false attribute named after the tag, true where the field reaches Threshold
  Normal             custom normals bent away from the first field's centre as strongly as the field
On a Cloner, MoClone Weightmap sets each clone's weight (effectors work that much on it) and MoClone Selection marks the
clones the effectors and the clone bodies use. Field Driver sets one setting of its object from the fields' strength at
the object, between Minimum and Maximum."""
import bpy

from . import gen_caps as gc
from . import kinds
from .primitives import _math

MOD = "Blenda Field Tags"
# key: (menu, name, icon, what it is in Blender, Transfer-style (True) or Use Fields (False), what it needs)
SPECS = {
    "VERTEX_MAP": ("Other", "Vertex Map", "GROUP_VERTEX", "Vertex group", True, "MESH"),
    "VERTEX_COLOR": ("Other", "Vertex Color", "GROUP_VCOL", "Color attribute", True, "MESH"),
    "POINT_SEL": ("Other", "Point Selection", "VERTEXSEL", "Point attribute (true/false)", True, "MESH"),
    "EDGE_SEL": ("Other", "Edge Selection", "EDGESEL", "Edge attribute (true/false)", True, "MESH"),
    "POLY_SEL": ("Other", "Polygon Selection", "FACESEL", "Face attribute (true/false)", True, "MESH"),
    "NORMAL": ("Other", "Normal", "NORMALS_VERTEX_FACE", "Custom normals", True, "MESH"),
    "MG_WEIGHT": ("MoClone", "MoClone Weightmap", "MOD_VERTEX_WEIGHT", "Clone weights", False, "CLONER"),
    "MG_SEL": ("MoClone", "MoClone Selection", "RESTRICT_SELECT_OFF", "Clone selection", False, "CLONER"),
    "FIELD_DRIVER": ("Animation", "Field Driver", "DRIVER", "Sets one setting from the fields", False, "ANY"),
}
MESH_KEYS = ("VERTEX_MAP", "VERTEX_COLOR", "POINT_SEL", "EDGE_SEL", "POLY_SEL", "NORMAL")
DOMAIN = {"POINT_SEL": "POINT", "EDGE_SEL": "EDGE", "POLY_SEL": "FACE"}
TRANSFER = [("OFF", "Off", "The tag keeps the values you set or paint"), ("FIELDS", "Fields", "The fields in the Fields list set the values")]
TARGETS = [("location.x", "Position X", ""), ("location.y", "Position Z", ""), ("location.z", "Position Y", ""),
           ("rotation_euler.x", "Rotation X", ""), ("rotation_euler.y", "Rotation Z", ""), ("rotation_euler.z", "Rotation Y", ""),
           ("scale.x", "Scale X", ""), ("scale.y", "Scale Z", ""), ("scale.z", "Scale Y", ""), ("UNIFORM", "Scale (all)", ""),
           ("CUSTOM", "Other Setting...", "Any setting of this object, by its Blender path (for example data.energy)")]


def entries(ob, key=None):
    return [(i, t) for i, t in enumerate(getattr(ob, "b4d_ftags", [])) if key is None or t.kind == key]


def entry(ob, key):
    e = entries(ob, key)
    return e[0] if e else (None, None)


def using(t):
    return t.use_fields if not SPECS[t.kind][4] else t.transfer == "FIELDS"


def _fits(ob, key):
    need = SPECS[key][5]
    if need == "ANY":
        return True
    if need == "CLONER":
        return ob.get("b4d_type") == "cloner"
    return ob.type == "MESH" and ob.get("b4d_type") is None          # a plain polygon object, not a generator


def has(ob, key):
    return entry(ob, key)[1] is not None


def add(context, ob, key):
    if not _fits(ob, key) or has(ob, key):
        return False
    t = ob.b4d_ftags.add()
    t.kind = key
    t.name = SPECS[key][1]
    if key == "VERTEX_MAP" and t.name not in ob.vertex_groups:
        ob.vertex_groups.new(name=t.name)
    if key == "FIELD_DRIVER":
        t.use_fields = True
    _touch(ob)
    return True


def remove(context, ob, key):
    i, t = entry(ob, key)
    if t is None:
        return
    if key == "VERTEX_MAP" and t.name in ob.vertex_groups:
        ob.vertex_groups.remove(ob.vertex_groups[t.name])
    ob.b4d_ftags.remove(i)
    _touch(ob)


# --- the nodes -------------------------------------------------------------------------------------------------------

def value(nodes, links, ob, i, t):
    """The tag's fields combined at each element: the strongest wins (the field-layer stack comes later)."""
    from . import moclone_fx as fx
    v = 0.0
    for j, f in enumerate(t.fields):
        if f.obj is None or not fx.is_field(f.obj):
            continue
        on = fx._driven(nodes, ob, f"b4d_ftags[{i}].fields[{j}].on")
        op = fx._driven(nodes, ob, f"b4d_ftags[{i}].fields[{j}].opacity", "var*0.01")
        v = _math(nodes, "MAXIMUM", v, _math(nodes, "MULTIPLY", fx.field_value(nodes, links, f.obj), _math(nodes, "MULTIPLY", on, op, links), links), links)
    if not hasattr(v, "is_output"):
        n = nodes.new("ShaderNodeValue"); n.outputs[0].default_value = 0.0
        v = n.outputs[0]
    return v


def _store(nodes, links, geo, name, typ, domain, val):
    st = nodes.new("GeometryNodeStoreNamedAttribute"); st.data_type = typ; st.domain = domain
    links.new(geo, st.inputs["Geometry"]); st.inputs["Name"].default_value = name
    links.new(val, st.inputs["Value"])
    return st.outputs["Geometry"]


def _mesh_tag(nodes, links, geo, ob, i, t):
    from . import moclone_fx as fx
    v = value(nodes, links, ob, i, t)
    k = t.kind
    if k == "VERTEX_MAP":
        return _store(nodes, links, geo, t.name, "FLOAT", "POINT", v)
    if k == "VERTEX_COLOR":
        c = nodes.new("FunctionNodeCombineColor")
        for ch, idx in (("Red", 0), ("Green", 1), ("Blue", 2)):
            links.new(_math(nodes, "MULTIPLY", fx._driven(nodes, ob, f"b4d_ftags[{i}].color[{idx}]"), v, links), c.inputs[ch])
        links.new(v, c.inputs["Alpha"])
        return _store(nodes, links, geo, t.name, "FLOAT_COLOR", "POINT", c.outputs[0])
    if k in DOMAIN:
        sel = _math(nodes, "GREATER_THAN", v, _math(nodes, "SUBTRACT", fx._driven(nodes, ob, f"b4d_ftags[{i}].threshold", "var*0.01"), 1e-6, links), links)
        return _store(nodes, links, geo, t.name, "BOOLEAN", DOMAIN[k], sel)
    if k == "NORMAL":
        first = next((f.obj for f in t.fields if f.obj is not None), None)
        info = nodes.new("GeometryNodeObjectInfo"); info.transform_space = "RELATIVE"
        if first is not None:
            info.inputs["Object"].default_value = first
        away = gc.vmath(nodes, links, "NORMALIZE", gc.vmath(nodes, links, "SUBTRACT", gc.position(nodes), info.outputs["Location"]))
        normal = nodes.new("GeometryNodeInputNormal").outputs[0]
        mix = fx._mix(nodes, links, "VECTOR", _math(nodes, "MINIMUM", v, 1.0, links), normal, away)
        sn = nodes.new("GeometryNodeSetMeshNormal"); sn.mode = "FREE"; sn.domain = "POINT"
        links.new(geo, sn.inputs["Mesh"]); links.new(gc.vmath(nodes, links, "NORMALIZE", mix), sn.inputs["Custom Normal"])
        return sn.outputs[0]
    return geo


def signature(ob):
    return [f"{t.kind}:{t.name}:{using(t)}:" + ",".join(f.obj.name for f in t.fields if f.obj is not None) for _i, t in entries(ob)]


def _build(ob):
    """The mesh's field-tag modifier, first in the stack; none when no mesh tag uses fields."""
    want = [(i, t) for i, t in entries(ob) if t.kind in MESH_KEYS and using(t)]
    mod = ob.modifiers.get(MOD)
    if not want:
        if mod is not None:
            ob.modifiers.remove(mod)
        ob["b4d_ftag_sig"] = signature(ob)
        return
    name = f"Blenda Field Tags [{ob.name}]"
    old = bpy.data.node_groups.get(name)
    if old is not None:
        bpy.data.node_groups.remove(old)
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.is_modifier = True
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    gin, gout = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    geo = gin.outputs[0]
    for i, t in want:
        geo = _mesh_tag(nodes, links, geo, ob, i, t)
    links.new(geo, gout.inputs[0])
    if mod is None:
        mod = ob.modifiers.new(MOD, "NODES")
    mod.node_group = tree
    idx = list(ob.modifiers).index(mod)
    if idx != 0:
        ob.modifiers.move(idx, 0)                       # first: the modifiers after it see the tags' values
    ob["b4d_ftag_sig"] = signature(ob)


def _touch(ob):
    ob.pop("b4d_ftag_sig", None)
    if ob.get("b4d_type") == "cloner":                  # the Cloner's nodes read its MoClone tags
        ob["b4d_fx_sig"] = []
        from . import generators
        generators.sync_all()
    _sync(bpy.context.scene)


# --- MoClone tags inside a Cloner's nodes (called by moclone_fx.effect_fn) --------------------------------------------

def clone_tags(nodes, links, gen, geo):
    """MoClone Weightmap sets b4d_weight, MoClone Selection sets b4d_sel (1 in, 0 out), from their fields."""
    from . import moclone_fx as fx
    i, w = entry(gen, "MG_WEIGHT")
    if w is not None and using(w):
        geo = fx._store(nodes, links, geo, "b4d_weight", "FLOAT", value(nodes, links, gen, i, w))
    i, s = entry(gen, "MG_SEL")
    if s is not None:
        if using(s):
            th = fx._driven(nodes, gen, f"b4d_ftags[{i}].threshold", "var*0.01")
            sel = _math(nodes, "GREATER_THAN", value(nodes, links, gen, i, s), _math(nodes, "SUBTRACT", th, 1e-6, links), links)
        else:
            sel = nodes.new("ShaderNodeValue"); sel.outputs[0].default_value = 1.0; sel = sel.outputs[0]
        geo = fx._store(nodes, links, geo, "b4d_sel", "FLOAT", sel)
    return geo


def clone_tag_signature(gen):
    return signature(gen)


# --- Field Driver --------------------------------------------------------------------------------------------------

def _drive(ob, t):
    from . import moclone_dyn as dyn
    from . import moclone_fx as fx
    p = ob.matrix_world.translation
    v = 0.0
    for f in t.fields:
        if f.on and f.obj is not None and fx.is_field(f.obj):
            v = max(v, dyn.field_value(f.obj, f.obj.matrix_world, p) * f.opacity / 100.0)
    out = t.minimum + (t.maximum - t.minimum) * min(max(v, 0.0), 1.0)
    path = t.custom_path if t.target == "CUSTOM" else t.target
    try:
        if path == "UNIFORM":
            if tuple(ob.scale) != (out, out, out):
                ob.scale = (out, out, out)
            return
        owner_path, _dot, attr = path.rpartition(".")
        owner = ob.path_resolve(owner_path) if owner_path else ob
        if attr in ("x", "y", "z") and hasattr(owner, "__len__"):
            k = "xyz".index(attr)
            if abs(owner[k] - out) > 1e-7:
                owner[k] = out
        elif abs(getattr(owner, attr) - out) > 1e-7:
            setattr(owner, attr, out)
    except (ValueError, AttributeError, TypeError):
        pass


_busy = [False]


@bpy.app.handlers.persistent
def _sync(scene, depsgraph=None):
    if _busy[0] or scene is None:
        return
    _busy[0] = True
    try:
        for ob in scene.objects:
            tags = getattr(ob, "b4d_ftags", None)
            if not tags:
                if ob.get("b4d_ftag_sig") is not None and ob.modifiers.get(MOD) is not None:
                    _build(ob)
                continue
            if ob.type == "MESH" and ob.get("b4d_type") is None and ob.get("b4d_ftag_sig") != signature(ob):
                _build(ob)
            for _i, t in entries(ob, "FIELD_DRIVER"):
                _drive(ob, t)
    finally:
        _busy[0] = False


_pending = [False]


@bpy.app.handlers.persistent
def _on_update(scene, depsgraph=None):
    """Blender's update handlers must not add objects or evaluate the scene (Blender 5.2 crashes): the work is done
    from a timer, right after the update."""
    if _pending[0] or _busy[0]:
        return
    _pending[0] = True

    def run():
        _pending[0] = False
        try:
            _sync(bpy.context.scene)
        except Exception as ex:
            print("Blenda 4D:", __name__, ex)
        return None
    bpy.app.timers.register(run, first_interval=0.0)


# --- pages -----------------------------------------------------------------------------------------------------------

def page(col, ob, key):
    i, t = entry(ob, key)
    if t is None:
        return
    c = col.column()
    if key not in ("FIELD_DRIVER",):
        if key not in ("MG_WEIGHT", "MG_SEL"):
            c.prop(t, "name", text="Name")
        if SPECS[key][4]:
            c.prop(t, "transfer", text="Transfer")
        else:
            c.prop(t, "use_fields", text="Use Fields")
    if key == "VERTEX_COLOR":
        c.prop(t, "color", text="Color")
    if key in DOMAIN or key == "MG_SEL":
        c.prop(t, "threshold", text="Threshold")
    if key == "FIELD_DRIVER":
        c.prop(t, "target", text="Drive")
        if t.target == "CUSTOM":
            c.prop(t, "custom_path", text="Setting")
        c.prop(t, "minimum", text="Minimum"); c.prop(t, "maximum", text="Maximum")
    if key == "VERTEX_MAP" and not using(t):
        c.label(text="Paint it in Weight Paint, or set Transfer to Fields", icon="INFO")
    if using(t):
        c.separator()
        c.label(text="Fields")
        _field_list(c, ob, i, t)


def _field_list(col, ob, i, t):
    from . import icons
    from . import moclone_fx as fx
    box = col.column(align=True)
    box.use_property_split = False
    if not len(t.fields):
        box.label(text="Drag fields here from the Object Manager", icon="INFO")
    col.menu("BLENDA4D_MT_field_add", text="Add Field", icon="ADD")
    for j, it in enumerate(t.fields):
        line = box.row(align=True)
        split = line.split(factor=0.62, align=True)
        left, row = split.row(align=True), split.row(align=True)
        left.alignment = "LEFT"
        if it.obj is None:
            left.label(text="(gone)", icon="ERROR")
        else:
            left.prop(it, "on", text="")
            op = left.operator("blenda4d.fx_select", text=it.obj.name, emboss=False, **icons.kw(fx.ICONS.get(it.obj.get("b4d_type"), "DOT"), "fields"))
            op.name = it.obj.name
            row.prop(it, "opacity", text="")
        r = row.operator("blenda4d.ftag_field_remove", text="", icon="X", emboss=False)
        r.name, r.tag, r.index = ob.name, i, j


class BLENDA4D_OT_ftag_field_remove(bpy.types.Operator):
    """Take this field out of the tag's list (the field stays in the scene)"""
    bl_idname = "blenda4d.ftag_field_remove"
    bl_label = "Remove Field"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty()
    tag: bpy.props.IntProperty()
    index: bpy.props.IntProperty()

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        if ob is None or not 0 <= self.tag < len(ob.b4d_ftags):
            return {"CANCELLED"}
        fl = ob.b4d_ftags[self.tag].fields
        if 0 <= self.index < len(fl):
            fl.remove(self.index)
        _touch(ob)
        return {"FINISHED"}


def drop(context, objs, event):
    """Fields let go over a field tag's page join that tag's Fields list."""
    from . import roles
    from . import moclone_fx as fx
    s = getattr(context.window_manager, "b4d_am_subject", "")
    if not s.startswith("OTAG:"):
        return False
    name, _sep, key = s[5:].rpartition(":")
    if key not in SPECS:
        return False
    over = next((a for a in context.window.screen.areas if roles.role(a) == "ATTRIBUTES"
                 and a.x <= event.mouse_x < a.x + a.width and a.y <= event.mouse_y < a.y + a.height), None)
    ob = bpy.data.objects.get(name)
    if over is None or ob is None:
        return False
    _i, t = entry(ob, key)
    if t is None:
        return False
    took = False
    for o in objs:
        if fx.is_field(o) and all(f.obj != o for f in t.fields):
            it = t.fields.add(); it.obj = o; took = True
    if took:
        if SPECS[key][4]:
            t.transfer = "FIELDS"
        else:
            t.use_fields = True
        _touch(ob)
        over.tag_redraw()
    return took


# --- registration ----------------------------------------------------------------------------------------------------

def _changed(self, context):
    ob = self.id_data
    if isinstance(ob, bpy.types.Object):
        _touch(ob)


def _live(self, context):
    ob = self.id_data
    if isinstance(ob, bpy.types.Object):
        ob.update_tag()
        _sync(context.scene)


class B4DTagField(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object, update=_changed)
    on: bpy.props.BoolProperty(name="On", default=True, update=_live)
    opacity: bpy.props.FloatProperty(name="Opacity", default=100.0, min=0.0, max=100.0, subtype="PERCENTAGE", update=_live)


class B4DFieldTag(bpy.types.PropertyGroup):
    kind: bpy.props.StringProperty()
    name: bpy.props.StringProperty(name="Name", default="Tag", update=_changed, description="The name materials and other tools find it by")
    transfer: bpy.props.EnumProperty(name="Transfer", items=TRANSFER, default="OFF", update=_changed)
    use_fields: bpy.props.BoolProperty(name="Use Fields", default=False, update=_changed, description="The fields in the list set the values")
    fields: bpy.props.CollectionProperty(type=B4DTagField)
    color: bpy.props.FloatVectorProperty(name="Color", size=3, subtype="COLOR", min=0.0, max=1.0, default=(1.0, 1.0, 1.0), update=_live)
    threshold: bpy.props.FloatProperty(name="Threshold", default=50.0, min=0.0, max=100.0, subtype="PERCENTAGE", update=_live,
                                       description="In the selection where the fields reach at least this")
    target: bpy.props.EnumProperty(name="Drive", items=TARGETS, default="location.z", update=_live, description="The setting the fields drive")
    custom_path: bpy.props.StringProperty(name="Setting", default="", update=_live)
    minimum: bpy.props.FloatProperty(name="Minimum", default=0.0, update=_live, description="The setting where the fields give nothing")
    maximum: bpy.props.FloatProperty(name="Maximum", default=1.0, update=_live, description="The setting where the fields give full strength")


classes = (B4DTagField, B4DFieldTag, BLENDA4D_OT_ftag_field_remove)


def register():
    from . import managers, om_menu, tag_pages
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.b4d_ftags = bpy.props.CollectionProperty(type=B4DFieldTag)
    for key, sp in SPECS.items():
        om_menu.TAGS[key] = sp[:4]
        om_menu.HOOKS[key] = (has, add, remove)
        tag_pages.EXTRA_PAGES[key] = (lambda key: lambda col, ob: page(col, ob, key))(key)
    if drop not in managers.OM_DROP:
        managers.OM_DROP.insert(0, drop)
    if _on_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_update)
    for h in (bpy.app.handlers.frame_change_post, bpy.app.handlers.load_post):
        if _sync not in h:
            h.append(_sync)


def unregister():
    from . import managers, om_menu, tag_pages
    for h in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post, bpy.app.handlers.load_post):
        for fn in (_sync, _on_update):
            if fn in h:
                h.remove(fn)
    if drop in managers.OM_DROP:
        managers.OM_DROP.remove(drop)
    for key in SPECS:
        om_menu.TAGS.pop(key, None)
        om_menu.HOOKS.pop(key, None)
        tag_pages.EXTRA_PAGES.pop(key, None)
    if hasattr(bpy.types.Object, "b4d_ftags"):
        del bpy.types.Object.b4d_ftags
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
