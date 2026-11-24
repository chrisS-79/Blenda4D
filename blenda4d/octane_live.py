# SPDX-License-Identifier: GPL-3.0-or-later
"""Works with the Octane add-on when you have installed it; without it nothing here shows. Nothing of Octane is part of
Blenda 4D: every setting is the add-on's own, read from it while it runs.

With it, the Render Viewer has Octane's row: the live picture, pause, clay, region, the focus, material and white balance
pickers, the kernel and the pass. Octane's settings show where Blenda keeps settings: Render Settings, and an Octane page
for cameras, lights and objects. Create > Octane makes its camera, lights, objects and materials."""
import bpy

from . import build, managers, matman, matpage, roles
from . import viewer as V

NAME = "octane"
ROW_PX = 28
KERNELS = [("OctaneDirectLightingKernel", "Direct Lighting"), ("OctanePathTracingKernel", "Path Tracing"),
           ("OctanePhotonTracingKernel", "Photon Tracing"), ("OctanePMCKernel", "PMC"), ("OctaneInfoChannelsKernel", "Info Channels")]
MATERIALS = [("OctaneUniversalMaterial", "Universal"), ("OctaneDiffuseMaterial", "Diffuse"), ("OctaneGlossyMaterial", "Glossy"),
             ("OctaneSpecularMaterial", "Specular"), ("OctaneMetallicMaterial", "Metallic"), ("OctaneStandardSurfaceMaterial", "Standard Surface"),
             ("OctaneMixMaterial", "Mix"), ("OctaneLayeredMaterial", "Layered"), ("OctaneToonMaterial", "Toon"), ("OctaneHairMaterial", "Hair"),
             ("OctaneCompositeMaterial", "Composite"), ("OctaneOpenPBRSurfaceMaterial", "OpenPBR Surface"), ("OctaneClippingMaterial", "Clipping"),
             ("OctanePortalMaterial", "Portal"), ("OctaneShadowCatcherMaterial", "Shadow Catcher"), ("OctaneNullMaterial", "Null")]
LIGHTS = [("octane.quick_add_octane_area_light", "Area Light", "LIGHT_AREA"), ("octane.quick_add_octane_sphere_light", "Sphere Light", "LIGHT_POINT"),
          ("octane.quick_add_octane_spot_light", "Spot Light", "LIGHT_SPOT"), ("octane.quick_add_octane_directional_light", "Directional Light", "LIGHT_SUN"),
          ("octane.quick_add_octane_mesh_light", "Mesh Light", "MESH_DATA"), ("octane.quick_add_octane_analytical_light", "Analytic Light", "LIGHT"),
          ("octane.quick_add_octane_toon_point_light", "Toon Point Light", "LIGHT_POINT"),
          ("octane.quick_add_octane_toon_directional_light", "Toon Directional Light", "LIGHT_SUN")]
SHAPES = [("octane.quick_add_octane_vectron", "Vectron", "MESH_DATA"), ("octane.quick_add_octane_box", "Box", "MESH_CUBE"),
          ("octane.quick_add_octane_sphere", "Sphere", "MESH_UVSPHERE"), ("octane.quick_add_octane_capsule", "Capsule", "MESH_CAPSULE"),
          ("octane.quick_add_octane_cylinder", "Cylinder", "MESH_CYLINDER"), ("octane.quick_add_octane_prism", "Prism", "MESH_CONE"),
          ("octane.quick_add_octane_torus", "Torus", "MESH_TORUS"), ("octane.quick_add_octane_tube", "Tube", "MESH_CYLINDER")]
_kept = {}                   # the viewport as it was before the live picture took its place
_was = [None]


# --- is it there? ------------------------------------------------------------------------------------------------------------
def installed():
    return NAME in bpy.context.preferences.addons and any(getattr(c, "bl_idname", "") == NAME for c in bpy.types.RenderEngine.__subclasses__())


def used(scene=None):
    return (scene or bpy.context.scene).render.engine == NAME


def _props(owner):
    return getattr(owner, NAME, None)


def _has_op(idname):
    mod, name = idname.split(".")
    try:
        getattr(getattr(bpy.ops, mod), name).get_rna_type()
        return True
    except (KeyError, AttributeError):
        return False


# --- the kernel -----------------------------------------------------------------------------------------------------------------
def kernel_tree(scene):
    p = _props(scene)
    return p.kernel_node_graph_property.node_tree if p is not None else None


def kernel_node(scene):
    tree = kernel_tree(scene)
    out = next((n for n in tree.nodes if n.bl_idname == "OctaneKernelOutputNode"), None) if tree is not None else None
    return out.inputs[0].links[0].from_node if out is not None and out.inputs[0].links else None


def _new_kernel(scene, idname):
    """The kernel's nodes: an output and the kernel. One that was there before stays in its tree, unlinked."""
    tree = kernel_tree(scene)
    if tree is None:
        tree = bpy.data.node_groups.new("Octane Kernel", "octane_kernel_nodes")
        tree.use_fake_user = True
    out = next((n for n in tree.nodes if n.bl_idname == "OctaneKernelOutputNode"), None) or tree.nodes.new("OctaneKernelOutputNode")
    out.location = (0, 0)
    node = next((n for n in tree.nodes if n.bl_idname == idname), None)
    if node is None:
        node = tree.nodes.new(idname)
        node.location = (-320, -60 * len(tree.nodes))
    tree.links.new(node.outputs[0], out.inputs[0])
    p = _props(scene)
    p.kernel_data_mode = "NODETREE"
    p.kernel_node_graph_property.node_tree = tree
    scene.update_tag()


def _ready(scene):
    """What a scene needs before Octane can show it."""
    if kernel_node(scene) is None:
        _new_kernel(scene, KERNELS[0][0])


# --- the live picture --------------------------------------------------------------------------------------------------------------
KEEP = ("show_gizmo", "show_region_header", "show_region_tool_header", "show_region_toolbar", "show_region_ui", "show_region_hud",
        "show_region_asset_shelf", "use_render_border")


def area():
    """The area that shows the live picture, or None."""
    a = V.editor()
    return a if a is not None and a.type == "VIEW_3D" and _kept else None


def live():
    return area() is not None


def _flag(sp, attr, v):
    try:
        if getattr(sp, attr) != v:
            setattr(sp, attr, v)
    except AttributeError:                                 # this one cannot be switched here
        pass


def start():
    a = V.editor()
    if a is None or a.type != "IMAGE_EDITOR" or not used() or build.busy():
        return
    _ready(bpy.context.scene)
    a.type = "VIEW_3D"
    sp = a.spaces.active
    _kept.clear()
    _kept.update(shading=sp.shading.type, overlays=sp.overlay.show_overlays, text=sp.overlay.show_text, flags={k: getattr(sp, k) for k in KEEP if hasattr(sp, k)},
                 view=None)
    for k in _kept["flags"]:
        if k != "use_render_border":
            _flag(sp, k, False)
    sp.overlay.show_overlays = False
    sp.shading.type = "RENDERED"
    win = V.window()
    if bpy.context.scene.camera is not None:
        bpy.app.timers.register(lambda: _camera(win, a), first_interval=0.05)
    V.redraw()


def _camera(win, a):
    """Through the camera, filling the picture's area."""
    try:
        r3 = a.spaces.active.region_3d
        if r3 is None or not _kept:
            return None
        _kept["view"] = (r3.view_perspective, r3.view_location.copy(), r3.view_rotation.copy(), r3.view_distance, r3.view_camera_zoom, tuple(r3.view_camera_offset))
        r3.view_perspective = "CAMERA"
        region = next(r for r in a.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=win, screen=win.screen, area=a, region=region):
            bpy.ops.view3d.view_center_camera()
    except (ReferenceError, RuntimeError):
        pass
    return None


def stop():
    """The picture's area is the Image Editor again; its viewport gets back all that was changed."""
    a = area()
    if a is None:
        _kept.clear()
        return
    sp = a.spaces.active
    sp.shading.type = _kept["shading"]
    sp.overlay.show_overlays, sp.overlay.show_text = _kept["overlays"], _kept["text"]
    for k, v in _kept["flags"].items():
        _flag(sp, k, v)
    if _kept["view"] is not None and sp.region_3d is not None:
        r3 = sp.region_3d
        r3.view_perspective, r3.view_location, r3.view_rotation, r3.view_distance, r3.view_camera_zoom, r3.view_camera_offset = _kept["view"]
    _kept.clear()
    a.type = "IMAGE_EDITOR"
    a.ui_type = "IMAGE_EDITOR"
    V._dress(a)
    V.redraw()


def restart():
    a = area()
    if a is None:
        return start()
    a.spaces.active.shading.type = "SOLID"

    def again():
        b = area()
        if b is not None:
            b.spaces.active.shading.type = "RENDERED"
        return None
    bpy.app.timers.register(again, first_interval=0.1)


def _label():
    p = _props(bpy.context.scene)
    return "Live" + (" (paused)" if live() and p is not None and p.preview_pause else "")


ROW = {"on": live, "start": start, "stop": stop, "label": _label}


def _in_view(fn, **kw):
    a, win = area(), V.window()
    if a is None:
        return
    region = next(r for r in a.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=win, screen=win.screen, area=a, region=region):
        fn("INVOKE_DEFAULT", **kw)


def _pause():
    p = _props(bpy.context.scene)
    p.preview_pause = not p.preview_pause


def _clay():
    p = _props(bpy.context.scene)
    items = [i.identifier for i in p.bl_rna.properties["clay_mode"].enum_items]
    p.clay_mode = items[0] if p.clay_mode != items[0] else items[1]


def _clay_on():
    p = _props(bpy.context.scene)
    return p.clay_mode != p.bl_rna.properties["clay_mode"].enum_items[0].identifier


def _region():
    a = area()
    sp = a.spaces.active
    sc = bpy.context.scene
    if sp.use_render_border or (sp.region_3d.view_perspective == "CAMERA" and sc.render.use_border):
        sp.use_render_border = sc.render.use_border = False
    else:
        _in_view(bpy.ops.view3d.render_border)


def _region_on():
    a = area()
    return a is not None and (a.spaces.active.use_render_border or (a.spaces.active.region_3d.view_perspective == "CAMERA" and
                                                                      bpy.context.scene.render.use_border))


def _settings():
    win = V.window()
    main = next((w for w in bpy.context.window_manager.windows if roles.areas(w.screen, "OBJECTS")), win)
    bar = next(iter(roles.areas(main.screen, "DOC_TABS")), main.screen.areas[0])
    with bpy.context.temp_override(window=main, screen=main.screen, area=bar, region=bar.regions[-1]):
        from . import render_settings as rs
        rs.ensure_pages(bpy.context.window_manager)
        wm = bpy.context.window_manager
        wm.b4d_rs_page = next((i for i, p in enumerate(wm.b4d_rs_pages) if p.key == "ENGINE"), wm.b4d_rs_page)
        bpy.ops.blenda4d.render_settings()


# key: (name, icon, function, can it be used, is it on, what it does)
C = {
    "LIVE": ("Live", "PLAY", lambda: stop() if live() else start(), None, live, "Show the scene as Octane renders it, and keep it up to date"),
    "RESTART": ("Restart", "FILE_REFRESH", restart, live, None, "Start the live picture again from the beginning"),
    "PAUSE": ("Pause", "PAUSE", _pause, live, lambda: bool(_props(bpy.context.scene).preview_pause), "Hold the live picture, and go on again"),
    "SETTINGS": ("Render Settings", "PREFERENCES", _settings, None, None, "Octane's page in Render Settings"),
    "CLAY": ("Clay", "SHADING_SOLID", _clay, None, _clay_on, "Show every surface as plain clay"),
    "REGION": ("Render Region", "SELECT_SET", _region, live, _region_on, "Draw a box: only that part is rendered. Click again for the whole picture"),
    "FOCUS": ("Focus Picker", "CON_CAMERASOLVER", lambda: _in_view(bpy.ops.octane.focus_picker), live, None, "Click in the live picture where the camera should focus"),
    "MATERIAL": ("Material Picker", "EYEDROPPER", lambda: _in_view(bpy.ops.octane.material_picker), live, None, "Click an object in the live picture to pick its material"),
    "WHITE": ("White Balance Picker", "COLOR", lambda: _in_view(bpy.ops.octane.whitebalance_picker), live, None, "Click what should be white in the live picture"),
}
GROUPS = (("LIVE", "RESTART", "PAUSE"), ("SETTINGS", "CLAY"), ("REGION", "FOCUS", "MATERIAL", "WHITE"))


class BLENDA4D_OT_octane_cmd(bpy.types.Operator):
    bl_idname = "blenda4d.octane_cmd"
    bl_label = "Octane"
    bl_options = {"INTERNAL"}
    cmd: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        c = C.get(props.cmd)
        return f"{c[0]}: {c[5]}" if c else cls.bl_label

    def execute(self, context):
        c = C.get(self.cmd)
        if c is None or not used(context.scene) or (c[3] is not None and not c[3]()):
            return {"CANCELLED"}
        c[2]()
        for a in context.screen.areas:
            a.tag_redraw()
        return {"FINISHED"}


class BLENDA4D_OT_octane_kernel(bpy.types.Operator):
    bl_idname = "blenda4d.octane_kernel"
    bl_label = "Kernel"
    bl_description = "How Octane works the light out"
    bl_options = {"REGISTER", "UNDO"}
    kind: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        try:
            _new_kernel(context.scene, self.kind)
        except RuntimeError as ex:
            self.report({"WARNING"}, str(ex))
            return {"CANCELLED"}
        return {"FINISHED"}


class BLENDA4D_MT_octane_kernel(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_octane_kernel"
    bl_label = "Kernel"
    bl_description = "How Octane works the light out"

    def draw(self, context):
        now = kernel_node(context.scene)
        for idname, name in KERNELS:
            self.layout.operator("blenda4d.octane_kernel", text=name, icon="RADIOBUT_ON" if now is not None and now.bl_idname == idname
                                 else "RADIOBUT_OFF").kind = idname


def kernel_name(scene):
    n = kernel_node(scene)
    return dict(KERNELS).get(n.bl_idname, n.name) if n is not None else "Kernel"


def draw_row(col, context):
    """Octane's row under the Render Viewer's buttons. It stays, dimmed, while another renderer is picked."""
    from . import bars, fitzoom
    region, s = context.region, context.preferences.system.ui_scale
    free = (region.width / max(0.1, fitzoom.zoom_of(region)) - 2 * bars.PANEL_MARGIN * s) / (24 * s)
    row = col.row(align=True)
    row.alignment = "LEFT"
    row.scale_x = row.scale_y = 1.2
    on = used(context.scene)
    for n, group in enumerate(GROUPS):
        need = len(group) + (0.7 if n else 0)
        if need > free:
            return
        free -= need
        if n:
            row.separator(factor=1.4)
        for k in group:
            c = C[k]
            b = row.row(align=True)
            b.alignment = "LEFT"
            b.enabled = on and (c[3] is None or bool(c[3]()))
            b.operator("blenda4d.octane_cmd", text="", icon=c[1], depress=bool(on and c[4] is not None and c[4]())).cmd = k
    rest = row.row(align=True)
    rest.enabled = on
    if free > 6:
        rest.separator(factor=1.4)
        b = rest.row(align=True)
        b.ui_units_x = 5
        b.menu(BLENDA4D_MT_octane_kernel.bl_idname, text=kernel_name(context.scene))
    vl = _props(context.view_layer)
    if free > 12 and vl is not None and hasattr(vl, "current_preview_pass_type"):
        rest.separator(factor=0.8)
        b = rest.row(align=True)
        b.ui_units_x = 5
        b.prop(vl, "current_preview_pass_type", text="")
    if not on and free > 12:
        rest.separator(factor=1.0)
        rest.label(text="Octane is not the renderer")


# --- the add-on's own settings, drawn into Blenda's pages -----------------------------------------------------------------------------
class _Ctx:
    """The context the add-on's panels expect, with what Blenda shows put in."""

    def __init__(self, **own):
        self.__dict__["_own"] = own

    def __getattr__(self, name):
        own = self.__dict__["_own"]
        if name in own:
            return own[name]
        return getattr(bpy.context, name, None)


class _Panel:
    def __init__(self, layout, cls):
        self.layout, self._cls, self.is_popover, self.use_pin = layout, cls, False, False

    def __getattr__(self, name):
        import inspect
        v = getattr(self._cls, name)
        return (lambda *a, **k: v(self, *a, **k)) if inspect.isfunction(v) and not isinstance(inspect.getattr_static(self._cls, name), staticmethod) else v


def _panels(where):
    """The add-on's panels for one of Blender's pages, in its order: (top one, those inside it)."""
    mine = [c for c in _all_panels() if c.__module__.split(".")[0] == NAME and getattr(c, "bl_space_type", "") == "PROPERTIES" and
            getattr(c, "bl_context", None) in {None, where}]
    inside = {}
    for c in mine:
        parent = getattr(c, "bl_parent_id", "")
        if parent:
            inside.setdefault(parent, []).append(c)
    return [c for c in mine if not getattr(c, "bl_parent_id", "") and getattr(c, "bl_context", "") == where], inside


def _all_panels():
    out, todo = [], list(bpy.types.Panel.__subclasses__())
    while todo:
        c = todo.pop(0)
        out.append(c)
        todo += c.__subclasses__()
    return sorted((c for c in dict.fromkeys(out) if getattr(c, "bl_rna", None) is not None), key=lambda c: getattr(c, "bl_order", 0))


_told = set()


def draw_panels(layout, where, only=None, **own):
    """The add-on's panels for this page, each one under a heading that folds."""
    ctx = _Ctx(engine=NAME, **own)
    tops, inside = _panels(where)

    def one(lay, cls):
        try:
            if hasattr(cls, "poll") and not cls.poll(ctx):
                return
        except Exception:
            return
        head, body = lay.panel(f"B4D_{cls.__name__}", default_closed="DEFAULT_CLOSED" in getattr(cls, "bl_options", set()) or bool(getattr(cls, "bl_parent_id", "")))
        if hasattr(cls, "draw_header"):
            _run(cls.draw_header, head, cls, ctx)
        head.label(text=cls.bl_label.replace("Octane ", ""))
        if body is None:
            return
        body.use_property_split = True
        _run(cls.draw, body, cls, ctx)
        for sub in inside.get(cls.__name__, ()):
            one(body, sub)
    for c in tops:
        if only is None or c.__name__ in only or any(c.__name__.startswith(o) for o in only):
            one(layout, c)


def _run(fn, layout, cls, ctx):
    try:
        fn(_Panel(layout, cls), ctx)
    except Exception as ex:                                # a panel that needs Blender's own editor: the rest still shows
        key = (cls.__name__, str(ex))
        if key not in _told:
            _told.add(key)
            print("Blenda 4D: Octane page", *key)


def page(col, ob):
    """The Octane page in the Attribute Manager."""
    d = ob.data
    own = {"object": ob, "active_object": ob}
    kind = {"CAMERA": "camera", "LIGHT": "light", "MESH": "mesh", "CURVE": "curve", "VOLUME": "volume", "FONT": "curve", "CURVES": "curves",
            "POINTCLOUD": "pointcloud"}.get(ob.type)
    if kind:
        own[kind] = d
        draw_panels(col, "data", **own)
    draw_panels(col, "object", **own)


def draw_settings(col, scene):
    """Octane's page in Render Settings."""
    _raw = getattr(col, "_layout", col)
    lay = _raw.column()
    row = lay.row(align=True)
    row.label(text="Kernel")
    row.menu(BLENDA4D_MT_octane_kernel.bl_idname, text=kernel_name(scene))
    node = kernel_node(scene)
    if node is not None:
        body = lay.column()
        try:
            matpage.draw_node(body, bpy.context, node)
        except Exception as ex:
            if str(ex) not in _told:
                _told.add(str(ex))
                print("Blenda 4D: Octane kernel", ex)
    else:
        lay.operator("blenda4d.octane_kernel", text="New Kernel", icon="ADD").kind = KERNELS[0][0]
    for where in ("render", "view_layer", "output"):
        draw_panels(lay, where, scene=scene)


# --- Create > Octane -----------------------------------------------------------------------------------------------------------------
class BLENDA4D_OT_octane_add(bpy.types.Operator):
    bl_idname = "blenda4d.octane_add"
    bl_label = "Add"
    bl_options = {"REGISTER", "UNDO"}
    what: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        n = next((x[1] for x in (*LIGHTS, *SHAPES) if x[0] == props.what), None)
        return f"Add an Octane {n or 'camera'}"

    def execute(self, context):
        if not installed():
            return {"CANCELLED"}
        context.scene.render.engine = NAME
        _ready(context.scene)
        win = context.window
        view = build.biggest_view(win.screen) if any(a.type == "VIEW_3D" for a in win.screen.areas) else None
        if view is None:
            self.report({"INFO"}, "Open the viewport first")
            return {"CANCELLED"}
        region = next(r for r in view.regions if r.type == "WINDOW")
        with context.temp_override(window=win, area=view, region=region):
            if self.what == "CAMERA":
                r = bpy.ops.blenda4d.add_camera()
            else:
                mod, name = self.what.split(".")
                r = getattr(getattr(bpy.ops, mod), name)("EXEC_DEFAULT")
        return {"FINISHED"} if "FINISHED" in r else {"CANCELLED"}


class BLENDA4D_OT_octane_material(bpy.types.Operator):
    bl_idname = "blenda4d.octane_material"
    bl_label = "Octane Material"
    bl_description = "Make a new Octane material of this kind"
    bl_options = {"REGISTER", "UNDO"}
    kind: bpy.props.StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        context.scene.render.engine = NAME
        name = dict(MATERIALS).get(self.kind, "Octane")
        mat = bpy.data.materials.new(f"Octane {name}")
        if not mat.use_nodes:
            mat.use_nodes = True
        tree = mat.node_tree
        tree.nodes.clear()
        try:
            out = tree.nodes.new("ShaderNodeOutputMaterial")
            node = tree.nodes.new(self.kind)
        except RuntimeError as ex:
            bpy.data.materials.remove(mat)
            self.report({"WARNING"}, str(ex))
            return {"CANCELLED"}
        out.location, node.location = (300, 0), (0, 0)
        tree.links.new(node.outputs[0], out.inputs[0])
        context.window_manager.b4d_material = mat.name
        return {"FINISHED"}


class BLENDA4D_MT_octane_materials(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_octane_materials"
    bl_label = "Octane Material"
    bl_description = "Make a new Octane material"

    def draw(self, context):
        for idname, name in MATERIALS:
            if bpy.types.Node.bl_rna_get_subclass_py(idname) is not None:
                self.layout.operator("blenda4d.octane_material", text=name, icon="MATERIAL").kind = idname
        self.layout.separator()
        if _has_op("octane.convert_to_octane_material"):
            self.layout.operator("octane.convert_to_octane_material", text="Convert to Octane Material")


class BLENDA4D_MT_octane_create(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_octane_create"
    bl_label = "Octane"
    bl_description = "Octane's camera, lights, objects and materials"

    def draw(self, context):
        lay = self.layout
        lay.operator("blenda4d.octane_add", text="Octane Camera", icon="OUTLINER_OB_CAMERA").what = "CAMERA"
        for group in (LIGHTS, SHAPES):
            lay.separator()
            for idname, name, icon in group:
                if _has_op(idname):
                    lay.operator("blenda4d.octane_add", text=name, icon=icon).what = idname
        lay.separator()
        lay.menu(BLENDA4D_MT_octane_materials.bl_idname, icon="MATERIAL")
        if _has_op("octane.open_octanedb"):
            lay.operator("octane.open_octanedb", text="Live Database...", icon="URL")


def _create_menu(self, context):
    if installed():
        self.layout.separator()
        self.layout.menu(BLENDA4D_MT_octane_create.bl_idname, icon="SHADING_RENDERED")


def _material_menu(self, context):
    if installed():
        self.layout.separator()
        self.layout.menu(BLENDA4D_MT_octane_materials.bl_idname, icon="MATERIAL")


# --- materials: their names in the Shader field, and a picture where Octane makes none --------------------------------------------------
def _shaders(scene):
    return [m for m in MATERIALS if bpy.types.Node.bl_rna_get_subclass_py(m[0]) is not None] if used(scene) and installed() else []


_balls = {}


def _value(node, *names):
    for n in names:
        sock = node.inputs.get(n)
        if sock is not None and hasattr(sock, "default_value"):
            src = sock
            if sock.is_linked:
                up = sock.links[0].from_node
                src = next((i for i in up.inputs if hasattr(i, "default_value") and hasattr(i.default_value, "__len__")), None) or sock
            v = src.default_value
            return tuple(v)[:3] if hasattr(v, "__len__") and not isinstance(v, str) else v
    return None


def ball(mat):
    """A shaded ball in the material's main color: Octane renders no material pictures in Blender."""
    if not used() or not installed() or mat.node_tree is None:
        return None
    out = next((n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    sock = out.inputs[0] if out is not None else None
    node = sock.links[0].from_node if sock is not None and sock.is_linked else None
    if node is None or not node.bl_idname.startswith("Octane"):
        return None
    base = _value(node, "Albedo", "Diffuse", "Base color", "Specular", "Transmission", "Color", "Reflection") or (0.7, 0.7, 0.7)
    if not hasattr(base, "__len__") or len(base) != 3:
        base = (0.7, 0.7, 0.7)
    rough, metal = _value(node, "Roughness"), _value(node, "Metallic")
    rough = float(rough) if isinstance(rough, (int, float)) else 0.3
    metal = 1.0 if node.bl_idname == "OctaneMetallicMaterial" else float(metal) if isinstance(metal, (int, float)) else 0.0
    key = (tuple(round(float(c), 3) for c in base), round(rough, 2), round(metal, 2))
    if key not in _balls:
        import numpy as np
        n = 96
        yy, xx = np.mgrid[0:n, 0:n]
        x, y = (xx + 0.5 - n / 2) / (n * 0.45), (yy + 0.5 - n / 2) / (n * 0.45)
        r2 = x * x + y * y
        z = np.sqrt(np.clip(1 - r2, 0, 1))
        light = np.array((-0.45, 0.6, 0.66))
        lam = np.clip(x * light[0] + y * light[1] + z * light[2], 0, 1)
        half = np.clip(x * -0.25 + y * 0.34 + z * 0.91, 0, 1)
        shine = half ** (4 + 220 * (1 - min(1.0, rough)) ** 2) * (0.9 - 0.6 * min(1.0, rough))
        edge = (1 - z) ** 4 * 0.25
        col = np.array(key[0])[None, None, :] * ((0.12 + 0.88 * lam) * (1 - 0.55 * key[2]))[..., None]
        col = col + (shine + edge)[..., None] * (np.array(key[0]) * key[2] + (1 - key[2]))[None, None, :]
        col = np.clip(col, 0, 1) ** (1 / 2.2)
        a = np.clip((1 - np.sqrt(r2)) * n * 0.45, 0, 1)
        _balls[key] = np.concatenate([col, a[..., None]], axis=-1).astype(np.float32)
    return _balls[key]


# --- coming and going ------------------------------------------------------------------------------------------------------------------
EXTRA = (ROW_PX, draw_row)


def _sync():
    """The add-on was switched on or off: its row and pages come or go."""
    try:
        now = installed()
    except AttributeError:
        return 2.0
    if now != _was[0]:
        first = _was[0] is None
        _was[0] = now
        if now:
            if EXTRA not in V.EXTRA:
                V.EXTRA.append(EXTRA)
            if ROW not in V.LIVE:
                V.LIVE.append(ROW)
            from . import render_settings
            render_settings.ENGINE_DRAW[NAME] = draw_settings
            managers.OCTANE_PAGE[:] = [page]
            matpage.MORE[:] = [_shaders]
            matman.BALLS[:] = [ball]
        else:
            _gone()
        win = V.window()
        if not first and win is not None and V.docked(win) and not build.busy():      # the row needs its place
            def again():
                yield from V.leave_steps(win)
                yield from V.dock_steps(win)
            build.run_steps(again())
    return 2.0


def _gone():
    if live():
        stop()
    if EXTRA in V.EXTRA:
        V.EXTRA.remove(EXTRA)
    if ROW in V.LIVE:
        V.LIVE.remove(ROW)
    from . import render_settings
    render_settings.ENGINE_DRAW.pop(NAME, None)
    managers.OCTANE_PAGE.clear()
    matpage.MORE.clear()
    matman.BALLS.clear()


@bpy.app.handlers.persistent
def _loaded(*_args):
    _kept.clear()


classes = (BLENDA4D_OT_octane_cmd, BLENDA4D_OT_octane_kernel, BLENDA4D_MT_octane_kernel, BLENDA4D_OT_octane_add, BLENDA4D_OT_octane_material,
           BLENDA4D_MT_octane_materials, BLENDA4D_MT_octane_create)
_menus = []


def register():
    _was[0] = None
    for c in classes:
        bpy.utils.register_class(c)
    for idname, fn in (("BLENDA4D_MT_main_create", _create_menu), ("BLENDA4D_MT_mm_create", _material_menu)):
        cls = getattr(bpy.types, idname, None)
        if cls is not None:
            cls.append(fn)
            _menus.append((cls, fn))
    bpy.app.handlers.load_post.append(_loaded)
    _sync()
    if not bpy.app.background:
        bpy.app.timers.register(_sync, first_interval=2.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_sync):
        bpy.app.timers.unregister(_sync)
    _gone()
    _was[0] = None
    if _loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_loaded)
    for cls, fn in _menus:
        try:
            cls.remove(fn)
        except (ValueError, RuntimeError):
            pass
    _menus.clear()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
