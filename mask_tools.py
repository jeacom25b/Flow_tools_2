import bpy
import bmesh
import numpy as np
from mathutils import Vector
from os import path
from .multifile import register_class
from .draw_2d import VerticalSlider, Draw2D

DEFORM_RIG_PATH = path.join(path.dirname(path.realpath(__file__)), "Mask Deform Rig.blend")


def create_object_from_bm(bm, matrix_world, name="new_mesh", set_active=False):
    mesh = bpy.data.meshes.new(name=name)
    bm.to_mesh(mesh)
    obj = bpy.data.objects.new(name=name, object_data=mesh)
    obj.matrix_world = matrix_world
    bpy.context.collection.objects.link(obj)
    if set_active:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    return obj


def get_bm_and_mask(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    layer = bm.verts.layers.paint_mask.verify()

    return bm, layer


def boundary_loops_create(bm, loops=2, smoothing=6, smooth_depth=3):
    edges = [e for e in bm.edges if e.is_boundary]
    for _ in range(loops):
        geom = bmesh.ops.extrude_edge_only(bm, edges=edges)["geom"]
        edges = [e for e in geom if isinstance(e, bmesh.types.BMEdge)]
    boundary_verts = set(v for v in geom if isinstance(v, bmesh.types.BMVert))
    seen_verts = boundary_verts.copy()
    curr_layer = boundary_verts
    new_layer = set()
    choosen_ones = set()
    for _ in range(smooth_depth + loops):
        for vert in curr_layer:
            for other in (e.other_vert(vert) for e in vert.link_edges):
                if other not in seen_verts:
                    new_layer.add(other)
                    seen_verts.add(other)
                    choosen_ones.add(other)
        curr_layer.clear()
        new_layer, curr_layer = curr_layer, new_layer
    choosen_ones = list(choosen_ones)
    while smooth_depth > 0:
        factor = min(smooth_depth, 0.5)
        smooth_depth -= 0.5
        bmesh.ops.smooth_vert(bm, verts=choosen_ones, use_axis_x=True,
                              use_axis_y=True,
                              use_axis_z=True,
                              factor=factor)


class BoundaryPolish:
    def __init__(self, bm):
        bm.verts.ensure_lookup_table()

        class NeighborData:
            def __init__(self, vert, others):
                self.vert = vert
                self.others = others
                self.disp_vec = Vector()

            def update_vec(self):
                self.disp_vec *= 0
                for other in self.others:
                    self.disp_vec += other.co
                self.disp_vec /= len(self.others)
                self.disp_vec = self.vert.co - self.disp_vec
                self.disp_vec -= self.vert.normal.dot(self.disp_vec) * self.vert.normal

        self.boundary_mapping = {}
        for vert in bm.verts:
            if vert.is_boundary:
                others = []
                for other in (edge.other_vert(vert) for edge in vert.link_edges if edge.is_boundary):
                    if other.is_boundary:
                        others.append(other)
                self.boundary_mapping[vert] = NeighborData(vert, others)

        self.original_coords = [vert.co.copy() for vert in self.boundary_mapping.keys()]

    def reset(self):
        for vert, co in zip(self.boundary_mapping.keys(), self.original_coords):
            vert.co.xyz = co.xyz

    def polish(self, iterations=30):
        for _ in range(iterations):
            for dt in self.boundary_mapping.values():
                dt.update_vec()

            for vert, dt in self.boundary_mapping.items():
                avg_vec = Vector()
                avg_vec -= dt.disp_vec * 0.5
                for other in dt.others:
                    avg_vec += self.boundary_mapping[other].disp_vec * 0.25
                vert.co += avg_vec * 0.5

    def back_to_mesh(self, mesh):
        for vert in self.boundary_mapping.keys():
            mesh.vertices[vert.index].co = vert.co


@register_class
class MaskExtract(bpy.types.Operator):
    bl_idname = "sculpt_tool_kit.mask_extract"
    bl_label = "Extract Mask"
    bl_description = "Extract and solidify Masked region as a new object"
    bl_options = {"REGISTER"}
    obj = None
    solidify = None
    smooth = None
    polish_iterations = 5
    last_mouse = 0
    click_count = 0

    @classmethod
    def poll(cls, context):
        if context.active_object:
            return context.active_object.type == "MESH"

    def execute(self, context):
        self.last_mode = context.active_object.mode
        self.click_count = 0
        bpy.ops.object.mode_set(mode="OBJECT")
        bm, mask = get_bm_and_mask(context.active_object.data)

        self.slider = VerticalSlider(center=None)
        self.slider.setup_handler()

        for face in bm.faces:
            avg = sum(vert[mask] for vert in face.verts) / len(face.verts)
            if avg < 0.5:
                bm.faces.remove(face)
        remove = []
        dissolve = []
        for vert in bm.verts:
            if len(vert.link_faces) < 1:
                remove.append(vert)
            elif len(vert.link_faces) == 1:
                dissolve.append(vert)
        for vert in remove:
            bm.verts.remove(vert)

        bmesh.ops.dissolve_verts(bm, verts=dissolve)

        BoundaryPolish(bm).polish(iterations=50)
        # boundary_loops_create(bm, loops=1, smoothing=6)

        self.obj = create_object_from_bm(bm,
                                         context.active_object.matrix_world,
                                         context.active_object.name + "_Shell")
        self.bm = bm
        self.obj.select_set(True)
        context.view_layer.objects.active = self.obj

        self.displace = self.obj.modifiers.new(type="DISPLACE", name="DISPLACE")
        self.displace.strength = 0
        self.solidify = self.obj.modifiers.new(type="SOLIDIFY", name="Solidify")
        self.solidify.offset = 1
        self.solidify.thickness = 0
        self.smooth = self.obj.modifiers.new(type="SMOOTH", name="SMOOTH")
        self.smooth.iterations = 5
        self.smooth.factor = 0

        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):

        mouse_co = Vector((event.mouse_region_x, event.mouse_region_y))
        if not self.slider.center:
            self.slider.center = mouse_co

        dist = context.region_data.view_distance

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self.click_count += 1
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            self.click_count = 4

        if event.type == "MOUSEMOVE":

            delta = self.last_mouse - event.mouse_y
            self.last_mouse = event.mouse_y
            if self.click_count == 0:
                scale = 700 / dist if not event.shift else 1400 / dist
                self.solidify.thickness = self.slider.eval(mouse_co, "Thickness", unit_scale=scale)
                self.solidify.thickness = max(self.solidify.thickness, 0)

            elif self.click_count == 1:
                scale = 100 if not event.shift else 300
                self.smooth.factor = self.slider.eval(mouse_co, "Smooth", unit_scale=scale)
                self.smooth.factor = max(self.smooth.factor, 0)

            elif self.click_count == 2:
                scale = 700 / dist if not event.shift else 1400 / dist
                self.displace.strength = self.slider.eval(mouse_co, "Displace", unit_scale=scale)

            elif self.click_count >= 3:
                if self.displace.strength != 0:
                    bpy.ops.object.modifier_apply(modifier=self.displace.name)
                else:
                    self.obj.modifiers.remove(self.displace)
                if self.solidify.thickness > 0:
                    bpy.ops.object.modifier_apply(modifier=self.solidify.name)
                else:
                    self.obj.modifiers.remove(self.solidify)
                if self.smooth.factor > 0:
                    bpy.ops.object.modifier_apply(modifier=self.smooth.name)
                else:
                    self.obj.modifiers.remove(self.smooth)
                self.bm.free()
                self.slider.remove_handler()
                return {"FINISHED"}

        return {"RUNNING_MODAL"}


@register_class
class MaskSplit(bpy.types.Operator):
    bl_idname = "sculpt_tool_kit.mask_split"
    bl_label = "Mask Split"
    bl_description = "Split masked and unmasked areas away."
    bl_options = {"REGISTER", "UNDO"}

    keep: bpy.props.EnumProperty(
        name="Keep",
        items=(("MASKED", "Masked", "Keep darkened parts"),
               ("UNMASKED", "Unmasked", "Keep light parts"),
               ("BOTH", "Both", "Keep both sides in separate objects")),
        default="BOTH"
    )

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == "MESH"

    def invoke(self, context, event):
        bpy.ops.ed.undo_push()
        bpy.ops.object.mode_set(mode="OBJECT")
        return context.window_manager.invoke_props_dialog(self)

    def remove_half(self, bm, invert=False):
        for face in bm.faces:
            if (face.select and not invert) or (not face.select and invert):
                bm.faces.remove(face)
        for vert in bm.verts:
            if len(vert.link_faces) == 0:
                bm.verts.remove(vert)
        bmesh.ops.holes_fill(bm, edges=bm.edges)
        bmesh.ops.triangulate(bm, faces=[face for face in bm.faces if len(face.verts) > 4])

    def execute(self, context):
        ob = context.active_object
        bm, mask = get_bm_and_mask(ob.data)
        bm.faces.ensure_lookup_table()
        face_mask = []

        for face in bm.faces:
            mask_sum = 0
            for vert in face.verts:
                mask_sum += vert[mask]
            face_mask.append(mask_sum / len(face.verts))

        geom1 = []

        for face in bm.faces:
            if face_mask[face.index] > 0.5:
                geom1.append(face)
                face.select = True
            else:
                face.select = False

        bm1 = bm.copy()

        invert = False
        if self.keep == "MASKED":
            invert = True

        self.remove_half(bm, invert=invert)
        bm.to_mesh(ob.data)

        if self.keep == "BOTH":
            bpy.ops.object.duplicate()
            self.remove_half(bm1, invert=True)
            bm1.to_mesh(context.active_object.data)
            self.remove_half(bm)
            bm.to_mesh(ob.data)

        return {"FINISHED"}


@register_class
class MaskDeformRemove(bpy.types.Operator):
    bl_idname = "sculpt_tool_kit.mask_deform_remove"
    bl_label = "Remove Mask Deform"
    bl_description = "Remove Mask Rig"
    bl_options = {"REGISTER", "UNDO"}

    apply: bpy.props.BoolProperty(
        name="Apply",
        description="Apply Mask deform before remove",
        default=True
    )

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == "MESH"

    def execute(self, context):
        if not context.active_object.get("MASK_RIG", False):
            return {"CANCELLED"}

        if self.apply:
            bpy.ops.object.convert(target="MESH")

        for item in context.active_object["MASK_RIG"]:
            if type(item) == str:
                for md in context.active_object.modifiers:
                    if md.name == md:
                        if self.apply:
                            bpy.ops.object.modifier_apply(modifier=md.name)
                        else:
                            context.active_object.modifiers.remove(md)

            elif type(item) == bpy.types.Object:
                bpy.data.objects.remove(item)
        del context.active_object["MASK_RIG"]
        context.area.tag_redraw()
        return {"FINISHED"}


@register_class
class MaskDeformAdd(bpy.types.Operator):
    bl_idname = "sculpt_tool_kit.mask_deform_add"
    bl_label = "Add Mask Deform"
    bl_description = "Add a rig to deform masked region"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.active_object:
            return context.active_object.type == "MESH"

    def create_rig(self, context, ob, vg, location, radius=1):

        md = ob.modifiers.new(type="LATTICE", name="MASK_DEFORM")
        md.vertex_group = vg.name
        with bpy.types.BlendDataLibraries.load(DEFORM_RIG_PATH) as (data_from, data_to):
            data_to.objects = ["Lattice", "DeformPivot", "DeformManipulator"]
        for d_ob in data_to.objects:
            context.collection.objects.link(d_ob)
        md.object = data_to.objects[0]
        data_to.objects[0].hide_viewport = True
        data_to.objects[1].location = location
        data_to.objects[1].scale = (radius,) * 3
        ob["MASK_RIG"] = list(data_to.objects) + [md.name]

    def execute(self, context):
        bpy.ops.object.mode_set(mode="OBJECT")
        self.ob = context.active_object
        bm, mask = get_bm_and_mask(self.ob.data)
        vg = self.ob.vertex_groups.new(name="MASK_TO_VG")
        avg_location = Vector()
        total = 0
        for vert in bm.verts:
            vg.add([vert.index], weight=vert[mask], type="REPLACE")
            f = vert[mask]
            f = max(0, f * (1 - f)) + 0.001 * f
            avg_location += vert.co * f
            total += f
        radius = 0

        try:
            avg_location /= total
            for vert in bm.verts:
                f = vert[mask]
                f = max(0, f * (1 - f)) + 0.001 * f
                radius += (vert.co - avg_location).length * f
            radius /= total
            radius *= sum(self.ob.scale) / 3 * 1.5
            avg_location = self.ob.matrix_world @ avg_location
            self.create_rig(context, self.ob, vg, avg_location, radius)
            self.draw_callback_px = Draw2D()
            self.draw_callback_px.setup_handler()
            self.draw_callback_px.add_text("[Return] = Finish, [ESC] = Cancell",
                                           location=Vector((50, 50)),
                                           size=15,
                                           color=(1, 0.5, 0, 1))
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}

        except ZeroDivisionError:
            self.report(type={"ERROR"}, message="Object does not contain any mask")
            return {"CANCELLED"}

    def modal(self, context, event):
        if event.type == "RET":
            if self.remove_rig(context, apply=True):
                self.draw_callback_px.remove_handler()
                return {"FINISHED"}

        if event.type == "ESC":
            if self.remove_rig(context, apply=False):
                self.draw_callback_px.remove_handler()
                return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def remove_rig(self, context, apply):
        context.view_layer.objects.active = self.ob
        self.ob.select_set(True)
        bpy.ops.sculpt_tool_kit.mask_deform_remove(apply=apply)
        return True



@register_class
class MaskDecimate(bpy.types.Operator):
    bl_idname = "sculpt_tool_kit.mask_decimate"
    bl_label = "Mask Decimate"
    bl_description = "Decimate masked region"
    bl_options = {"REGISTER", "UNDO"}

    ratio: bpy.props.FloatProperty(
        name="Ratio",
        description="Amount of decimation",
        default=0.7
    )

    @classmethod
    def poll(cls, context):
        if context.active_object:
            return context.active_object.type == "MESH"

    def invoke(self, context, event):
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.ed.undo_push()
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.ed.undo_push()
        ob = context.active_object
        vg = ob.vertex_groups.new(name="DECIMATION_VG")

        bm, mask = get_bm_and_mask(ob.data)
        for vert in bm.verts:
            vg.add([vert.index], weight=vert[mask], type="REPLACE")
        ob.vertex_groups.active_index = vg.index
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.decimate(ratio=self.ratio, use_vertex_group=True, vertex_group_factor=10)
        bpy.ops.object.mode_set(mode="OBJECT")
        ob.vertex_groups.remove(vg)
        context.area.tag_redraw()
        return {"FINISHED"}
