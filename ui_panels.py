import bpy
from bpy import context

class FlowTools2(bpy.types.Panel):
    bl_idname = "flow_tools"
    bl_label = "Flow Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_category = "Flow Tools 2"

    def draw(self, context):
        layout = self.layout
        
        col = layout.column()
        col.label("Booleans")
        row = col.row(align = True)
        row.operator("f_tools_2.multi_object_boolean", text = "Add", icon = "MOD_ARRAY").operation = "UNION"
        row.operator("f_tools_2.multi_object_boolean", text = "Sub", icon = "MOD_BOOLEAN").operation = "DIFFERENCE"
        row.operator("f_tools_2.multi_object_boolean", text = "Intersect", icon = "MOD_MULTIRES").operation = "INTERSECT"
        
        box = col.box()
        col1 = box.column(align = True)
        col1.label("Boolean Slash",)
        
        col1.separator()
        row = col1.row(align = True)
        
        row.operator("gpencil.draw", text = "Draw", icon = "GREASEPENCIL")
        row.operator("gpencil.draw", text = "Erase", icon = "FORCE_CURVE").mode = "ERASER"
        row = col1.row(align = True)
        row.operator
        row.operator("gpencil.draw", text = "Line", icon = "LINE_DATA").mode = "DRAW_STRAIGHT"
        row.operator("gpencil.draw", text = "Poly", icon = "MESH_DATA").mode = "DRAW_POLY"

        col1.separator()
        col1.prop(bpy.context.scene, "slash_cut_thickness")
        col1.prop(bpy.context.scene, "slash_cut_distance")
        col1.separator()
        col1.prop(bpy.context.scene, "slash_boolean_solver")
        col1.prop(bpy.context.scene, "slash_is_ciclic")
        
        slash_operator = col1.operator("f_tools_2.slash_bool", icon = "SCULPTMODE_HLT")
        
        slash_operator.cut_thickness = bpy.context.scene.slash_cut_thickness
        slash_operator.cut_distance = bpy.context.scene.slash_cut_distance
        slash_operator.boolean_solver = bpy.context.scene.slash_boolean_solver
        slash_operator.is_ciclic = bpy.context.scene.slash_is_ciclic
        
        col.separator()
        col.label("Remeshing")
        col.operator("f_tools_2.optimized_remesh", icon = "MOD_REMESH")
        
        col.separator()
        col.label("Envelope Builder")
        col.operator("f_tools_2.add_envelope_human", icon = "MOD_ARMATURE")
        col.operator("f_tools_2.add_envelope_armature", icon = "BONE_DATA")
        col.operator("f_tools_2.convert_envelope_to_mesh", icon = "MESH_DATA")