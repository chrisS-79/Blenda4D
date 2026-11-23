# SPDX-License-Identifier: GPL-3.0-or-later
"""The viewport's menus: View, Cameras, Display, Options, Filter, Panel. Each item is one of Blender's own viewport
operators or settings (settings show their check mark), named in plain words; Blender shows its own shortcut beside
each operator. Settings Blender has no equivalent for are left out."""
import bpy


def _space(context):
    sp = context.space_data
    if sp is not None and sp.type == "VIEW_3D":
        return sp
    area = next((a for a in context.screen.areas if a.type == "VIEW_3D"), None)
    return area.spaces.active if area else None


def _heading(layout, text):
    layout.label(text=text)


# Display presets: (key, name, Blender equivalent for the tooltip). "(Lines)" adds every edge over the shading.
PRESETS = (
    ("SMOOTH", "Smooth Shading", "Solid, Studio lighting, material colours"),
    ("SMOOTH_LINES", "Smooth Shading (Lines)", "Solid, Studio lighting, material colours, wireframe overlay"),
    ("QUICK", "Quick Shading", "Solid, Studio lighting, one plain colour"),
    ("QUICK_LINES", "Quick Shading (Lines)", "Solid, Studio lighting, one plain colour, wireframe overlay"),
    ("FLAT", "Flat Shading", "Solid, Flat lighting, material colours"),
    ("FLAT_LINES", "Flat Shading (Lines)", "Solid, Flat lighting, material colours, wireframe overlay"),
    ("HIDDEN", "Hidden Line", "Solid in the background colour with a wireframe overlay: only the edges you can see"),
    ("LINES", "Lines", "Wireframe"),
)
QUICK_GREY = (0.8, 0.8, 0.8)


def _background():
    """The viewport's background colour, in the linear colour the shading uses (the theme stores display colour)."""
    try:
        c = tuple(bpy.context.preferences.themes[0].view_3d.space.gradients.high_gradient)
    except (AttributeError, IndexError):
        c = (0.24, 0.24, 0.24)
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


def current_preset(sp):
    sh, ov = sp.shading, sp.overlay
    if sh.type == "WIREFRAME":
        return "LINES"
    if sh.type != "SOLID":
        return None
    lines = ov.show_wireframes
    if sh.light == "FLAT" and sh.color_type == "SINGLE":
        return "HIDDEN" if lines else None
    base = "FLAT" if sh.light == "FLAT" else "QUICK" if sh.color_type == "SINGLE" else "SMOOTH"
    return base + ("_LINES" if lines else "")


class BLENDA4D_OT_display_preset(bpy.types.Operator):
    bl_idname = "blenda4d.display_preset"
    bl_label = "Display"
    bl_description = "How the viewport draws the scene"
    kind: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        row = next((p for p in PRESETS if p[0] == properties.kind), None)
        return f"{row[1]} (Blender: {row[2]})" if row else cls.bl_description

    def execute(self, context):
        sp = _space(context)
        if sp is None:
            return {"CANCELLED"}
        sh, ov = sp.shading, sp.overlay
        k = self.kind
        # lines over shaded objects are dark (the theme's wire colour); Lines and Hidden Line draw light lines
        sh.wireframe_color_type = "OBJECT" if k in ("LINES", "HIDDEN") else "THEME"
        if k == "LINES":
            sh.type = "WIREFRAME"
            ov.show_wireframes = False
        else:
            sh.type = "SOLID"
            sh.show_xray = False
            base = k.replace("_LINES", "")
            sh.light = "FLAT" if base in ("FLAT", "HIDDEN") else "STUDIO"
            if base in ("QUICK", "HIDDEN"):
                sh.color_type = "SINGLE"
                sh.single_color = _background() if base == "HIDDEN" else QUICK_GREY
            else:
                sh.color_type = "MATERIAL"
            ov.show_wireframes = k.endswith("_LINES") or base == "HIDDEN"
            if ov.show_wireframes:
                ov.wireframe_threshold = 1.0                   # every edge, as a lines display shows them
                ov.wireframe_opacity = 1.0
        for a in context.screen.areas:
            if a.type == "VIEW_3D":
                a.tag_redraw()
        return {"FINISHED"}


_editor_view = {}           # viewport -> where its own (editor) camera was before a scene camera took over


def look_through(area, sp, cam):
    """Look through a scene camera: the editor camera's place is kept for the way back, and orbit / pan / zoom then
    move the scene camera itself (Lock Camera to View)."""
    from . import magnify
    magnify.leave(area)
    rv = sp.region_3d
    if rv.view_perspective != "CAMERA":
        _editor_view[area.as_pointer()] = {"rot": rv.view_rotation.copy(), "loc": rv.view_location.copy(),
                                           "dist": rv.view_distance, "persp": rv.view_perspective, "lens": sp.lens}
    bpy.context.scene.camera = cam
    rv.view_perspective = "CAMERA"
    sp.lock_camera = True


def back_to_editor(area, sp):
    """Back to the viewport's own camera, where it was left."""
    rv = sp.region_3d
    st = _editor_view.pop(area.as_pointer(), None)
    rv.view_perspective = st["persp"] if st else "PERSP"
    if st:
        rv.view_rotation, rv.view_location, rv.view_distance = st["rot"], st["loc"], st["dist"]
        sp.lens = st["lens"]


def _area_of(context, sp):
    return next((a for a in context.screen.areas if a.type == "VIEW_3D" and len(a.spaces) and a.spaces.active == sp),
                None)


class BLENDA4D_OT_render_still(bpy.types.Operator):
    bl_idname = "blenda4d.render_still"
    bl_label = "Render"
    bl_description = "Render the current frame and show it in the Render Viewer"
    use_viewport: bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        if properties.use_viewport:
            return "Render the current frame as this viewport sees it, and show it in the Render Viewer"
        return "Render the current frame through the scene camera, and show it in the Render Viewer"

    def execute(self, context):
        from . import viewer
        if bpy.app.is_job_running("RENDER"):
            return {"CANCELLED"}
        scene = context.scene
        viewer.begin(scene, scene.frame_current, scene.frame_current, False)
        try:
            return bpy.ops.render.render("INVOKE_DEFAULT", use_viewport=self.use_viewport, write_still=True)
        except RuntimeError as ex:
            viewer.failed()
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}


class BLENDA4D_OT_use_camera(bpy.types.Operator):
    bl_idname = "blenda4d.use_camera"
    bl_label = "Use Camera"
    bl_description = "Look through this camera (it becomes the scene camera)"
    name: bpy.props.StringProperty()

    def execute(self, context):
        ob = bpy.data.objects.get(self.name)
        sp = _space(context)
        if ob is None or ob.type != "CAMERA" or sp is None:
            return {"CANCELLED"}
        area = _area_of(context, sp)
        if area is not None:
            look_through(area, sp, ob)
        return {"FINISHED"}


class BLENDA4D_OT_default_camera(bpy.types.Operator):
    bl_idname = "blenda4d.default_camera"
    bl_label = "Default Camera"
    bl_description = "Leave the scene camera and look through the viewport's own camera"

    def execute(self, context):
        sp = _space(context)
        if sp is None:
            return {"CANCELLED"}
        area = _area_of(context, sp)
        from . import magnify
        magnify.leave(area)
        if sp.region_3d.view_perspective == "CAMERA" and area is not None:
            back_to_editor(area, sp)
        return {"FINISHED"}


class BLENDA4D_OT_projection(bpy.types.Operator):
    bl_idname = "blenda4d.projection"
    bl_label = "Projection"
    bl_description = "Perspective or parallel (orthographic) projection"
    kind: bpy.props.EnumProperty(items=[("PERSP", "Perspective", ""), ("ORTHO", "Parallel", "")])

    def execute(self, context):
        sp = _space(context)
        if sp is None:
            return {"CANCELLED"}
        from . import magnify
        magnify.leave(_area_of(context, sp))
        sp.region_3d.view_perspective = self.kind
        return {"FINISHED"}


class BLENDA4D_OT_show_types(bpy.types.Operator):
    bl_idname = "blenda4d.show_types"
    bl_label = "Show Object Types"
    bl_description = "Show every kind of object, or only geometry"
    only_geometry: bpy.props.BoolProperty()

    def execute(self, context):
        sp = _space(context)
        if sp is None:
            return {"CANCELLED"}
        for attr, _label in FILTER_TYPES:
            setattr(sp, attr, (not self.only_geometry) or attr in GEOMETRY)
        return {"FINISHED"}


class BLENDA4D_MT_view_view(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_view_view"
    bl_label = "View"
    bl_description = "Frame, zoom and turn the view"

    def draw(self, context):
        layout = self.layout
        sp = _space(context)
        from . import viewhistory
        for op, text, icon, redo in (("blenda4d.view_undo", "Undo View", "LOOP_BACK", False),
                                     ("blenda4d.view_redo", "Redo View", "LOOP_FORWARDS", True)):
            row = layout.row()
            row.enabled = viewhistory.available(context, redo)
            row.operator(op, text=text, icon=icon)
        layout.separator()
        _heading(layout, "Frame")
        layout.operator("view3d.view_all", text="Frame All", icon="ZOOM_ALL").center = False
        layout.operator("view3d.view_selected", text="Frame Selected", icon="ZOOM_SELECTED")
        layout.operator("view3d.view_all", text="Frame All and Center Cursor").center = True
        layout.operator("view3d.view_center_cursor", text="Center on 3D Cursor")
        layout.separator()
        layout.operator("view3d.zoom_border", text="Zoom Region")
        layout.operator("view3d.zoom", text="Zoom In").delta = 1
        layout.operator("view3d.zoom", text="Zoom Out").delta = -1
        layout.separator()
        _heading(layout, "Magnify")
        layout.operator_context = "EXEC_DEFAULT"
        layout.operator("blenda4d.magnify_in", text="Magnify In", icon="ZOOM_IN")
        layout.operator("blenda4d.magnify_out", text="Magnify Out", icon="ZOOM_OUT")
        layout.operator("blenda4d.magnify_reset", text="Reset Magnify", icon="LOOP_BACK")
        layout.operator_context = "INVOKE_DEFAULT"
        layout.separator()
        _heading(layout, "Render")
        layout.operator("view3d.render_border", text="Render Region", icon="SELECT_SET")
        layout.operator("blenda4d.region_resume", icon="PLAY")
        layout.operator("blenda4d.region_pause", icon="PAUSE")
        layout.operator("blenda4d.region_close", icon="X")
        layout.operator("render.opengl", text="Viewport Render Image", icon="RENDER_STILL")
        layout.operator("blenda4d.render_still", text="Render Image", icon="RENDER_STILL").use_viewport = True
        layout.separator()
        if sp is not None:
            layout.prop(sp, "lock_camera", text="Lock Camera to View")
        layout.operator("view3d.camera_to_view", text="Align Camera to View")
        layout.separator()
        layout.operator("screen.screen_full_area", text="Maximize Viewport")
        layout.operator("blenda4d.quad_view", text="Four Views / Full Size", icon="FULLSCREEN_ENTER")


class BLENDA4D_MT_view_cameras(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_view_cameras"
    bl_label = "Cameras"
    bl_description = "Look through a camera or the viewport's own"

    def draw(self, context):
        layout = self.layout
        sp = _space(context)
        _heading(layout, "Camera")
        from . import magnify
        in_cam = sp is not None and sp.region_3d.view_perspective == "CAMERA" and not magnify.on(sp)
        layout.operator("blenda4d.default_camera", text="Default Camera", icon="CHECKMARK" if not in_cam else "BLANK1")
        cams = sorted((o for o in context.scene.objects if o.type == "CAMERA"), key=lambda o: o.name)
        for ob in cams:
            on = in_cam and context.scene.camera == ob
            layout.operator("blenda4d.use_camera", text=ob.name, icon="CHECKMARK" if on else "OUTLINER_OB_CAMERA").name = ob.name
        if not cams:
            col = layout.column()
            col.enabled = False
            col.label(text="No cameras in the scene")
        if sp is not None:
            layout.separator()
            layout.prop(sp, "lock_camera", text="Lock Camera to View")
        cam = context.scene.camera
        if cam is not None and cam.type == "CAMERA":
            layout.prop(cam.data, "show_safe_areas", text="Safe Frames")
            layout.prop(cam.data, "show_passepartout", text="Darken Outside the Frame")
        layout.separator()
        _heading(layout, "Projection")
        persp = sp is not None and sp.region_3d.view_perspective == "PERSP"
        ortho = sp is not None and sp.region_3d.view_perspective == "ORTHO"
        layout.operator("blenda4d.projection", text="Perspective", icon="CHECKMARK" if persp else "BLANK1").kind = "PERSP"
        layout.operator("blenda4d.projection", text="Parallel", icon="CHECKMARK" if ortho else "BLANK1").kind = "ORTHO"
        layout.separator()
        _heading(layout, "Views")                       # F1 to F4: each view comes back where it was left (views.py)
        for op, label, icon in (("persp", "Perspective", "VIEW_PERSPECTIVE"), ("top", "Top", "AXIS_TOP"),
                                ("right", "Right", "AXIS_SIDE"), ("front", "Front", "AXIS_FRONT")):
            layout.operator("blenda4d.view_" + op, text=label, icon=icon)
        for axis, label, icon in (("LEFT", "Left", "AXIS_SIDE"), ("BACK", "Back", "AXIS_FRONT"), ("BOTTOM", "Bottom", "AXIS_TOP")):
            layout.operator("view3d.view_axis", text=label, icon=icon).type = axis
        if sp is not None:
            layout.separator()
            layout.prop(sp, "lens", text="Viewport Focal Length")


class BLENDA4D_MT_view_display(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_view_display"
    bl_label = "Display"
    bl_description = "How the viewport draws the scene"

    def draw(self, context):
        layout = self.layout
        sp = _space(context)
        if sp is None:
            return
        sh = sp.shading
        _heading(layout, "Shading")
        now = current_preset(sp)
        for key, label, _b in PRESETS:
            layout.operator("blenda4d.display_preset", text=label,
                            icon="RADIOBUT_ON" if now == key else "RADIOBUT_OFF").kind = key
        layout.separator()
        for kind, label in (("MATERIAL", "Material Preview"), ("RENDERED", "Rendered")):
            layout.prop_enum(sh, "type", kind, text=label)
        layout.separator()
        if sh.type == "SOLID":
            _heading(layout, "Solid")
            for kind, label in (("STUDIO", "Studio Lighting"), ("MATCAP", "MatCap"), ("FLAT", "Flat")):
                layout.prop_enum(sh, "light", kind, text=label)
            layout.separator()
            for kind, label in (("MATERIAL", "Material Color"), ("OBJECT", "Object Color"), ("RANDOM", "Random Color"),
                                ("SINGLE", "Single Color")):
                layout.prop_enum(sh, "color_type", kind, text=label)
            layout.separator()
            layout.prop(sh, "show_cavity", text="Cavity")
            layout.prop(sh, "show_shadows", text="Shadows")
            layout.prop(sh, "show_object_outline", text="Outline")
        if sh.type in {"MATERIAL", "RENDERED"}:
            layout.prop(sh, "use_scene_lights" if sh.type == "MATERIAL" else "use_scene_lights_render", text="Scene Lights")
            layout.prop(sh, "use_scene_world" if sh.type == "MATERIAL" else "use_scene_world_render", text="Scene World")
        layout.separator()
        _heading(layout, "Wire")
        layout.prop(sp.overlay, "show_wireframes", text="Wireframe on Shaded")
        layout.prop(sh, "show_xray", text="X-Ray")
        layout.prop(sh, "show_backface_culling", text="Backface Culling")


class BLENDA4D_MT_view_options(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_view_options"
    bl_label = "Options"
    bl_description = "Grid, axes and other things the viewport shows"

    def draw(self, context):
        layout = self.layout
        sp = _space(context)
        if sp is None:
            return
        ov = sp.overlay
        layout.prop(ov, "show_overlays", text="Overlays")
        layout.prop(sp, "show_gizmo", text="Gizmos")
        layout.separator()
        _heading(layout, "Viewport")
        layout.prop(ov, "show_floor", text="Grid")
        layout.prop(ov, "show_axis_x", text="X Axis")
        layout.prop(ov, "show_axis_z", text="Y Axis")     # Blenda shows Blender's Z as Y
        layout.prop(ov, "show_axis_y", text="Z Axis")
        layout.prop(ov, "show_cursor", text="3D Cursor")
        layout.prop(ov, "show_stats", text="Statistics")
        layout.prop(ov, "show_text", text="View Name")
        layout.separator()
        _heading(layout, "Objects")
        layout.prop(ov, "show_outline_selected", text="Selection Outline")
        layout.prop(ov, "show_object_origins", text="Object Origins")
        layout.prop(ov, "show_relationship_lines", text="Relationship Lines")
        layout.prop(ov, "show_face_orientation", text="Face Orientation")
        layout.prop(ov, "show_motion_paths", text="Motion Paths")
        layout.prop(ov, "show_bones", text="Joints")
        layout.prop(ov, "show_extras", text="Lights, Cameras and Helpers")
        layout.prop(ov, "show_fade_inactive", text="Fade Inactive Objects")
        layout.separator()
        _heading(layout, "Clipping")
        layout.prop(sp, "clip_start", text="Near")
        layout.prop(sp, "clip_end", text="Far")


FILTER_TYPES = (("show_object_viewport_mesh", "Polygon"), ("show_object_viewport_curve", "Spline"),
                ("show_object_viewport_surf", "Surface"), ("show_object_viewport_meta", "Metaball"),
                ("show_object_viewport_font", "Text"), ("show_object_viewport_volume", "Volume"),
                ("show_object_viewport_pointcloud", "Point Cloud"), ("show_object_viewport_curves", "Hair"),
                ("show_object_viewport_grease_pencil", "Grease Pencil"),
                ("show_object_viewport_armature", "Joint"), ("show_object_viewport_lattice", "Lattice"),
                ("show_object_viewport_empty", "Null"), ("show_object_viewport_light", "Light"),
                ("show_object_viewport_light_probe", "Light Probe"), ("show_object_viewport_camera", "Camera"),
                ("show_object_viewport_speaker", "Speaker"))
GEOMETRY = {"show_object_viewport_mesh", "show_object_viewport_curve", "show_object_viewport_surf",
            "show_object_viewport_meta", "show_object_viewport_font", "show_object_viewport_volume",
            "show_object_viewport_pointcloud"}


class BLENDA4D_MT_view_filter(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_view_filter"
    bl_label = "Filter"
    bl_description = "Which kinds of objects the viewport shows"

    def draw(self, context):
        layout = self.layout
        sp = _space(context)
        if sp is None:
            return
        layout.operator("blenda4d.show_types", text="Show Everything").only_geometry = False
        layout.operator("blenda4d.show_types", text="Geometry Only").only_geometry = True
        layout.separator()
        _heading(layout, "Objects")
        for attr, label in FILTER_TYPES:
            if hasattr(sp, attr):
                layout.prop(sp, attr, text=label)


class BLENDA4D_MT_view_panel(bpy.types.Menu):
    bl_idname = "BLENDA4D_MT_view_panel"
    bl_label = "Panel"
    bl_description = "Viewport layouts: one view or four"

    def draw(self, context):
        layout = self.layout
        sp = _space(context)
        quad = sp is not None and len(sp.region_quadviews) > 0
        layout.operator("screen.region_quadview", text="Single View" if quad else "Four Views", icon="VIEW_ORTHO")
        layout.operator("screen.screen_full_area", text="Maximize Viewport")
        layout.separator()
        layout.operator("wm.window_new", text="New Window")


VIEW_CLASSES = [BLENDA4D_MT_view_view, BLENDA4D_MT_view_cameras, BLENDA4D_MT_view_display, BLENDA4D_MT_view_options,
                BLENDA4D_MT_view_filter, BLENDA4D_MT_view_panel]
OPS = (BLENDA4D_OT_render_still, BLENDA4D_OT_display_preset, BLENDA4D_OT_use_camera, BLENDA4D_OT_default_camera, BLENDA4D_OT_projection, BLENDA4D_OT_show_types)
