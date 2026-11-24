# SPDX-License-Identifier: GPL-3.0-or-later
"""The material's controls in the Attribute Manager, shown while a material is selected in the Material Manager.

A hybrid of the classic material editor and Blender's material properties: the live preview ball, name and shader
type on top, then the channels one under another in a long column (Color, Diffusion, Luminance ...), each one a
fold-out with its switch in the header. Every control is Blender's own socket control (template_node_view), so a
value, a texture or a node plugged in here is the node tree's own, and Open Node Editor... shows that same tree."""
import bpy

SUBJECT = "MAT"            # wm.b4d_am_subject = "MAT:<material>" while a material is shown

# Principled BSDF channels: (key, title, switch, [(socket, label)]); a switch is (socket, value on, value off):
# the channel is on while the socket is not at its "off" value
CHANNELS = (
    ("COLOR", "Color", None, [("Base Color", "Color")]),
    ("DIFFUSION", "Diffusion", None, [("Diffuse Roughness", "Diffuse Roughness"), ("Roughness", "Roughness")]),
    ("LUMINANCE", "Luminance", ("Emission Strength", 1.0, 0.0),
     [("Emission Color", "Color"), ("Emission Strength", "Strength")]),
    ("TRANSPARENCY", "Transparency", ("Transmission Weight", 1.0, 0.0),
     [("Transmission Weight", "Amount"), ("IOR", "Refraction (IOR)")]),
    ("REFLECTANCE", "Reflectance", ("Specular IOR Level", 0.5, 0.0),
     [("Metallic", "Metallic"), ("Roughness", "Roughness"), ("Specular IOR Level", "Specular"),
      ("Specular Tint", "Tint"), ("Anisotropic", "Anisotropic"), ("Anisotropic Rotation", "Anisotropic Rotation"),
      ("Tangent", "Tangent")]),
    ("COAT", "Coat", ("Coat Weight", 1.0, 0.0),
     [("Coat Weight", "Amount"), ("Coat Roughness", "Roughness"), ("Coat IOR", "IOR"), ("Coat Tint", "Tint"),
      ("Coat Normal", "Normal")]),
    ("SHEEN", "Sheen", ("Sheen Weight", 1.0, 0.0),
     [("Sheen Weight", "Amount"), ("Sheen Roughness", "Roughness"), ("Sheen Tint", "Tint")]),
    ("SUBSURFACE", "Subsurface", ("Subsurface Weight", 1.0, 0.0),
     [("Subsurface Weight", "Amount"), ("Subsurface Radius", "Radius"), ("Subsurface Scale", "Scale"),
      ("Subsurface IOR", "IOR"), ("Subsurface Anisotropy", "Anisotropy")]),
    ("NORMAL", "Normal", None, [("Normal", "Normal")]),
    ("ALPHA", "Alpha", None, [("Alpha", "Alpha")]),
    ("THINFILM", "Thin Film", ("Thin Film Thickness", 500.0, 0.0),
     [("Thin Film Thickness", "Thickness"), ("Thin Film IOR", "IOR")]),
)
SHADERS = (("ShaderNodeBsdfPrincipled", "Principled BSDF"), ("ShaderNodeBsdfDiffuse", "Diffuse BSDF"),
           ("ShaderNodeEmission", "Emission"), ("ShaderNodeBsdfMetallic", "Metallic BSDF"),
           ("ShaderNodeBsdfGlass", "Glass BSDF"), ("ShaderNodeBsdfRefraction", "Refraction BSDF"),
           ("ShaderNodeBsdfTranslucent", "Translucent BSDF"), ("ShaderNodeBsdfTransparent", "Transparent BSDF"),
           ("ShaderNodeBsdfSheen", "Sheen BSDF"), ("ShaderNodeSubsurfaceScattering", "Subsurface Scattering"),
           ("ShaderNodeBsdfToon", "Toon BSDF"), ("ShaderNodeBsdfHair", "Hair BSDF"),
           ("ShaderNodeBsdfHairPrincipled", "Principled Hair BSDF"), ("ShaderNodeEeveeSpecular", "Specular BSDF"),
           ("ShaderNodeBsdfRayPortal", "Ray Portal BSDF"), ("ShaderNodeHoldout", "Holdout"),
           ("ShaderNodeMixShader", "Mix Shader"), ("ShaderNodeAddShader", "Add Shader"))
SHADERS = tuple(sh for sh in SHADERS if hasattr(bpy.types, sh[0]))     # what this Blender has


def show(context, mat):
    """Make the Attribute Manager show this material."""
    wm = context.window_manager
    wm.b4d_am_subject = f"{SUBJECT}:{mat.name}"
    if getattr(wm, "b4d_right_tab", "ATTRIBUTES") != "ATTRIBUTES":
        wm.b4d_right_tab = "ATTRIBUTES"


def shown(context):
    s = getattr(context.window_manager, "b4d_am_subject", "")
    if not s.startswith(SUBJECT + ":"):
        return None
    return bpy.data.materials.get(s[len(SUBJECT) + 1:])


def _output(mat):
    tree = mat.node_tree
    if tree is None:
        return None
    outs = [n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"]
    return next((n for n in outs if n.is_active_output), outs[0] if outs else None)


def _surface(mat):
    """The node plugged into the output's Surface, or None."""
    out = _output(mat)
    if out is None or not out.inputs["Surface"].is_linked:
        return None
    return out.inputs["Surface"].links[0].from_node


def _principled(mat):
    node = _surface(mat)
    return node if node is not None and node.type == "BSDF_PRINCIPLED" else None


# --- channel switches and the shader type, read from and written to the nodes ------------------------------------
def _switch_get(key):
    sw = next(c[2] for c in CHANNELS if c[0] == key)

    def get(self):
        node = _principled(self)
        sock = node.inputs.get(sw[0]) if node else None
        return bool(sock is not None and (sock.is_linked or abs(float(sock.default_value) - sw[2]) > 1e-6))
    return get


def _switch_set(key):
    sw = next(c[2] for c in CHANNELS if c[0] == key)

    def put(self, on):
        node = _principled(self)
        sock = node.inputs.get(sw[0]) if node else None
        if sock is not None and not sock.is_linked:
            sock.default_value = sw[1] if on else sw[2]
    return put


MORE = []                    # fn(scene) -> [(node, label)]: another renderer's own materials, before Blender's
_item_text = []


def _shaders():
    out = [sh for fn in MORE for sh in fn(bpy.context.scene)] + list(SHADERS)
    if out != _item_text:
        _item_text[:] = out                                # Blender needs the texts kept
    return _item_text


def _shader_items(self, context):
    return [(idname, label, "") for idname, label in _shaders()]


def _shader_get(self):
    node = _surface(self)
    ids = [s[0] for s in _shaders()]
    return ids.index(node.bl_idname) if node is not None and node.bl_idname in ids else 0


def _shader_set(self, i):
    """Put another shader where the Surface comes from, as Blender's own Surface menu does."""
    if not self.use_nodes:
        self.use_nodes = True
    tree, out = self.node_tree, _output(self)
    if out is None:
        out = tree.nodes.new("ShaderNodeOutputMaterial")
    old = _surface(self)
    idname = _shaders()[i][0]
    if old is not None and old.bl_idname == idname:
        return
    new = tree.nodes.new(idname)
    if old is not None:
        new.location = old.location
        for name in ("Color", "Base Color"):          # keep the colour where both have one
            a, b = old.inputs.get(name), next((new.inputs.get(n) for n in ("Color", "Base Color") if new.inputs.get(n)), None)
            if a is not None and b is not None and not a.is_linked and len(a.default_value) == len(b.default_value):
                b.default_value = a.default_value
                break
        tree.nodes.remove(old)
    else:
        new.location = (out.location.x - 300, out.location.y)
    tree.links.new(new.outputs[0], out.inputs["Surface"])


# --- drawing -------------------------------------------------------------------------------------------------------
def _socket(col, mat, node, name):
    sock = node.inputs.get(name)
    if sock is not None and getattr(sock, "enabled", True):
        col.template_node_view(mat.node_tree, node, sock)


def _section(layout, key, title, mat=None, switch=None, closed=True):
    head, body = layout.panel("b4d_mat_" + key.lower(), default_closed=closed)
    if switch:
        head.prop(mat, "b4d_ch_" + key.lower(), text="")
    head.label(text=title)
    node = _principled(mat) if switch else None
    sock = node.inputs.get(switch[0]) if node is not None else None
    if sock is not None and not sock.is_linked:
        dot = head.row()
        dot.alignment = "RIGHT"
        dot.prop_decorator(sock, "default_value")             # the switch's own value: keyframe it on and off
    if body is not None:
        body.use_property_split = True
        body.use_property_decorate = True
    return body


# --- one node's settings (the Node Editor's right panel) -----------------------------------------------------------
IMAGES = {"TEX_IMAGE", "TEX_ENVIRONMENT"}                     # Blender's longer settings: the image and its sequence


def draw_node(layout, context, node):
    """A node's settings and inputs, every one with its keyframe dot."""
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = True
    if node.type in IMAGES:
        node.draw_buttons_ext(context, col.column())
        col.separator()
    col.template_node_inputs(node)                            # Blender's own: the node's settings, then its inputs
    if getattr(node, "color_ramp", None) is not None:
        draw_knots(layout, node.color_ramp)


def draw_knots(layout, ramp):
    """Every knot of a gradient, to keyframe its place and its color."""
    head, body = layout.panel("b4d_node_knots", default_closed=False)
    head.label(text="Gradient Knots")
    if body is None:
        return
    body.use_property_split = True
    body.use_property_decorate = True
    for i, e in enumerate(ramp.elements):
        col = body.column(align=True)
        col.prop(e, "position", text=f"Knot {i + 1} Position", slider=True)
        col.prop(e, "color", text="Color")
        body.separator(factor=0.4)


def draw_subject(layout, context, _ob=None):
    """The Attribute Manager's page while a material is its subject. True when it drew."""
    mat = shown(context)
    if mat is None:
        return False
    return draw_material(layout, context, mat)


def draw_material(layout, context, mat, head=True):
    """A material's page: the Attribute Manager's, and the Node Editor window's when no node is picked."""
    if head:
        row = layout.row(align=True)
        row.label(text=f"Material [{mat.name}]", icon_value=layout.icon(mat))
        tools = row.row(align=True)
        tools.alignment = "RIGHT"
        tools.operator("blenda4d.mat_node_editor", text="Open Node Editor...", icon="NODETREE").name = mat.name
        layout.template_preview(mat, show_buttons=False)      # the live ball: re-renders as values change
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = True
    top = col.column()
    top.use_property_decorate = False                         # a name and a shader type are not values over time
    top.prop(mat, "name", text="Name")
    if not mat.use_nodes:
        col.operator("blenda4d.mat_use_nodes", text="Use Nodes", icon="NODETREE").name = mat.name
        return True
    top.prop(mat, "b4d_shader", text="Shader")
    node = _principled(mat)
    if node is not None:
        for key, title, sw, sockets in CHANNELS:
            if not any(node.inputs.get(s) for s, _l in sockets):
                continue
            body = _section(layout, key, title, mat, sw, closed=key != "COLOR")
            if body is not None:
                sub = body.column()
                sub.active = sw is None or getattr(mat, "b4d_ch_" + key.lower())
                for name, _label in sockets:
                    _socket(sub, mat, node, name)
    else:                                                     # another shader: Blender's own control for all of it
        body = _section(layout, "SURFACE", "Surface", closed=False)
        if body is not None:
            out = _output(mat)
            if out is not None:
                body.template_node_view(mat.node_tree, out, out.inputs["Surface"])
    out = _output(mat)
    if out is not None and out.inputs.get("Volume") is not None:   # smoke, clouds, fog: a volume shader
        vol_in = out.inputs["Volume"]
        body = _section(layout, "VOLUME", "Volume", closed=not vol_in.is_linked)
        if body is not None:
            body.template_node_view(mat.node_tree, out, vol_in)
    if out is not None:
        body = _section(layout, "DISPLACEMENT", "Displacement")
        if body is not None:
            body.template_node_view(mat.node_tree, out, out.inputs["Displacement"])
            if hasattr(mat, "displacement_method"):
                body.prop(mat, "displacement_method", text="Method")
    body = _section(layout, "VIEWPORT", "Viewport")
    if body is not None:
        for attr, label in (("diffuse_color", "Color"), ("metallic", "Metallic"), ("roughness", "Roughness")):
            body.prop(mat, attr, text=label)
    body = _section(layout, "ILLUMINATION", "Illumination")
    if body is not None:
        for attr, label in (("surface_render_method", "Render Method"), ("blend_method", "Blend Mode"),
                            ("use_backface_culling", "Backface Culling"),
                            ("use_backface_culling_shadow", "Backface Culling Shadow"),
                            ("use_transparency_overlap", "Transparency Overlap"),
                            ("use_raytrace_refraction", "Raytraced Transmission"), ("pass_index", "Pass Index")):
            if hasattr(mat, attr):
                body.prop(mat, attr, text=label)
    body = _section(layout, "ASSIGNMENT", "Assignment")
    if body is not None:
        users = [ob for ob in context.scene.objects if any(s.material == mat for s in getattr(ob, "material_slots", ()))]
        for ob in users:
            body.label(text=ob.name, icon="OBJECT_DATA")
        if not users:
            body.label(text="Not used by any object")
    return True


class BLENDA4D_OT_mat_use_nodes(bpy.types.Operator):
    bl_idname = "blenda4d.mat_use_nodes"
    bl_label = "Use Nodes"
    bl_description = "Make this material from nodes, so its channels can be edited here"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        mat = bpy.data.materials.get(self.name)
        if mat is not None:
            mat.use_nodes = True
        return {"FINISHED"}


class BLENDA4D_OT_mat_node_editor(bpy.types.Operator):
    bl_idname = "blenda4d.mat_node_editor"
    bl_label = "Open Node Editor"
    bl_description = "Open this material's nodes in the Node Editor window: what changes there changes here"
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        mat = bpy.data.materials.get(self.name)
        if mat is None:
            return {"CANCELLED"}
        from . import nodewin
        return {"FINISHED"} if nodewin.open_window(context, mat) else {"CANCELLED"}


classes = (BLENDA4D_OT_mat_use_nodes, BLENDA4D_OT_mat_node_editor)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    M = bpy.types.Material
    M.b4d_shader = bpy.props.EnumProperty(name="Shader", items=_shader_items, get=_shader_get, set=_shader_set,
                                          description="The shader the surface is made of (Blender: the node in Surface)")
    for key, title, sw, _s in CHANNELS:
        if sw:
            setattr(M, "b4d_ch_" + key.lower(), bpy.props.BoolProperty(
                name=title, get=_switch_get(key), set=_switch_set(key),
                description=f"Switch {title} on or off (Blender: {sw[0]})"))
    from . import managers
    managers.AM_SUBJECTS[SUBJECT] = draw_subject


def unregister():
    from . import managers
    managers.AM_SUBJECTS.pop(SUBJECT, None)
    M = bpy.types.Material
    for key, _t, sw, _s in CHANNELS:
        if sw and hasattr(M, "b4d_ch_" + key.lower()):
            delattr(M, "b4d_ch_" + key.lower())
    if hasattr(M, "b4d_shader"):
        del M.b4d_shader
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
