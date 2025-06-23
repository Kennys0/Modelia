import bpy
import os
from mathutils import Vector
import math
import addon_utils
import sys

# --- MODO DE OPERACIÓN ---
# Elige solo UNA de estas opciones y ponla en True.
USE_TEST_SPHERE = False     # Opción 1: Genera una esfera de prueba.
USE_EXISTING_OBJECT = False # Opción 2: Usa un objeto ya existente en la escena.
USE_FILE_IMPORT = True      # Opción 3: Importa un modelo desde un archivo.

# --- PARÁMETROS ---
# N_x = 4  # Número de cortes en X  # Eliminado, ahora se calcula automáticamente
N_y = 10  # Número de cortes en Y (predeterminado)
N_x = 7  # Se calculará automáticamente
material_thickness_mm = 3.0  # Grosor del material (mm)
clearance_mm = 0.05          # Holgura para encastre (mm)
slot_margin_mm = 0.05        # Margen para no cortar el centro

offset_x_m = 0.00            # Desplazamiento final en X

existing_object_name = "Buho"
# model_filepath = "D:/Ifurniture/IA nueva/hunyuan3d2_local/tigre_mini_clean.obj" # <-- Ya no se usa, se pasa por argumento
sphere_radius_m = 0.1
rescale_target_size_m = 0.2  # Tamaño objetivo en metros

material_thickness = material_thickness_mm / 1000.0
clearance = clearance_mm / 1000.0
slot_margin = slot_margin_mm / 1000.0

def ensure_obj_io_enabled(operator_type='import'):
    """Habilita el addon de importación/exportación OBJ y verifica los operadores"""
    if operator_type == 'import':
        if hasattr(bpy.ops.wm, 'obj_import') or hasattr(bpy.ops.import_scene, 'obj'):
            return True
    elif operator_type == 'export':
        if hasattr(bpy.ops.export_scene, 'obj'):
            return True
    
    if not addon_utils.check("io_scene_obj")[1]:
        addon_utils.enable("io_scene_obj", default_set=True, persistent=True)
        if operator_type == 'import':
            if hasattr(bpy.ops.wm, 'obj_import') or hasattr(bpy.ops.import_scene, 'obj'):
                return True
        elif operator_type == 'export':
            if hasattr(bpy.ops.export_scene, 'obj'):
                return True
    
    print(f"ERROR: Operador OBJ de {operator_type} no disponible. Habilita manualmente el addon 'Import-Export: Wavefront OBJ format'")
    return False

def clean_scene():
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

def create_cube_slab(name, location, dimensions):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.mesh.primitive_cube_add(size=1, enter_editmode=False, align='WORLD', location=location)
    slab = bpy.context.active_object
    slab.name = name
    slab.scale = dimensions
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return slab

def extract_and_extrude_outline(obj, axis, material_thickness, outline_prefix="Outline_"):
    if obj.name not in bpy.data.objects:
        return None
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    mesh = obj.data
    max_area = 0
    best_face_idx = -1
    axis_index = 0 if axis.upper()=='X' else 1 if axis.upper()=='Y' else 2
    for i, face in enumerate(mesh.polygons):
        if abs(face.normal[axis_index])>0.99 and face.area>max_area:
            max_area = face.area
            best_face_idx = i
    if best_face_idx<0:
        return None
    face_normal = mesh.polygons[best_face_idx].normal.copy()
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh.polygons[best_face_idx].select = True
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.region_to_loop()
    bpy.ops.mesh.duplicate_move()
    bpy.ops.mesh.separate(type='SELECTED')
    bpy.ops.object.mode_set(mode='OBJECT')
    new_objs = [o for o in bpy.context.selected_objects if o.name!=obj.name]
    outline_obj=None
    if new_objs:
        outline_obj=new_objs[0]
        outline_obj.name=f"{outline_prefix}{obj.name}"
        bpy.context.view_layer.objects.active=outline_obj
        outline_obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        extrusion_vector = -face_normal*material_thickness
        bpy.ops.mesh.extrude_edges_move(TRANSFORM_OT_translate={"value": extrusion_vector})
        bpy.ops.mesh.fill()
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    return outline_obj

def apply_boolean_modifier(obj, target_obj, operation='INTERSECT', solver='EXACT'):
    if obj.name not in bpy.data.objects or target_obj.name not in bpy.data.objects:
        return False
    mod=obj.modifiers.new(name="Boolean", type='BOOLEAN')
    mod.operation=operation
    mod.object=target_obj
    mod.solver=solver
    try:
        bpy.context.view_layer.objects.active=obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
        return True
    except RuntimeError:
        obj.modifiers.remove(mod)
        return False

def get_bounding_box_info(obj):
    if obj.name not in bpy.data.objects:
        return (0,0,0,0,0,0,Vector((0,0,0)),Vector((0,0,0)))
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active=obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    min_x=min(v.x for v in bbox); max_x=max(v.x for v in bbox)
    min_y=min(v.y for v in bbox); max_y=max(v.y for v in bbox)
    min_z=min(v.z for v in bbox); max_z=max(v.z for v in bbox)
    dims=Vector((max_x-min_x, max_y-min_y, max_z-min_z))
    center=Vector(((min_x+max_x)/2, (min_y+max_y)/2, (min_z+max_z)/2))
    return min_x, max_x, min_y, max_y, min_z, max_z, dims, center

def trim_and_filter_pieces(x_pieces_in, y_pieces_in, material_thickness):
    """
    Recorta solo en vertical (eje Z) las extensiones más allá de la última intersección real,
    y elimina piezas sin intersección. Evita 'piezas extendidas' y 'ranuras fantasma'.
    """
    trimmed_y = []
    # Filtrar Y-pieces
    for y in y_pieces_in:
        if y.name not in bpy.data.objects:
            continue
        # Recoger intersecciones reales con X: verificar solapamiento XY sustancial (> clearance)
        intersections = []
        bbox_y = [y.matrix_world @ Vector(c) for c in y.bound_box]
        y_min_x = min(v.x for v in bbox_y); y_max_x = max(v.x for v in bbox_y)
        y_min_y = min(v.y for v in bbox_y); y_max_y = max(v.y for v in bbox_y)
        for x in x_pieces_in:
            if x.name not in bpy.data.objects:
                continue
            bbox_x = [x.matrix_world @ Vector(c) for c in x.bound_box]
            x_min_x = min(v.x for v in bbox_x); x_max_x = max(v.x for v in bbox_x)
            x_min_y = min(v.y for v in bbox_x); x_max_y = max(v.y for v in bbox_x)
            # Calcular overlap en X e Y
            overlap_wx = min(y_max_x, x_max_x) - max(y_min_x, x_min_x)
            overlap_wy = min(y_max_y, x_max_y) - max(y_min_y, x_min_y)
            # Umbral: al menos clearance en ambas dimensiones para considerar cruce real
            if overlap_wx > clearance and overlap_wy > clearance:
                # Verificar solapamiento en Z sustancial
                y_min_z = min(v.z for v in bbox_y); y_max_z = max(v.z for v in bbox_y)
                x_min_z = min(v.z for v in bbox_x); x_max_z = max(v.z for v in bbox_x)
                overlap_hz = min(y_max_z, x_max_z) - max(y_min_z, x_min_z)
                if overlap_hz > material_thickness * 0.02:
                    intersections.append((x, overlap_hz, max(y_min_x, x_min_x), min(y_max_x, x_max_x),
                                          max(y_min_y, x_min_y), min(y_max_y, x_max_y),
                                          max(y_min_z, x_min_z), min(y_max_z, x_max_z)))
        if not intersections:
            # No intersecciones reales: eliminar pieza
            bpy.data.objects.remove(y, do_unlink=True)
            continue
        # Determinar Z bounds de última intersección real:
        z_min_bound = min(item[6] for item in intersections)
        z_max_bound = max(item[7] for item in intersections)
        # Obtener centro XY y dimensiones XY de la propia pieza
        center_y = Vector(((y_min_x+y_max_x)/2, (y_min_y+y_max_y)/2, 0))
        size_x = (y_max_x - y_min_x)
        size_y = (y_max_y - y_min_y)
        # Recortar arriba (por encima de z_max_bound)
        bbox_y = [y.matrix_world @ Vector(c) for c in y.bound_box]
        y_max_z = max(v.z for v in bbox_y)
        if y_max_z > z_max_bound + 1e-4:
            height = y_max_z - z_max_bound
            center_z = (y_max_z + z_max_bound) / 2
            cutter = create_cube_slab("CutterTrimYTop",
                                     (center_y.x, center_y.y, center_z),
                                     (size_x/2 + material_thickness, size_y/2 + material_thickness, height/2 + 0.001))
            apply_boolean_modifier(y, cutter, operation='DIFFERENCE')
            if cutter.name in bpy.data.objects:
                bpy.data.objects.remove(cutter, do_unlink=True)
        # Recortar abajo (por debajo de z_min_bound)
        y_min_z = min(v.z for v in bbox_y)
        if y_min_z < z_min_bound - 1e-4:
            height = z_min_bound - y_min_z
            center_z = (y_min_z + z_min_bound) / 2
            cutter = create_cube_slab("CutterTrimYBot",
                                     (center_y.x, center_y.y, center_z),
                                     (size_x/2 + material_thickness, size_y/2 + material_thickness, height/2 + 0.001))
            apply_boolean_modifier(y, cutter, operation='DIFFERENCE')
            if cutter.name in bpy.data.objects:
                bpy.data.objects.remove(cutter, do_unlink=True)
        trimmed_y.append(y)

    trimmed_x = []
    # Filtrar X-pieces
    for x in x_pieces_in:
        if x.name not in bpy.data.objects:
            continue
        intersections = []
        bbox_x = [x.matrix_world @ Vector(c) for c in x.bound_box]
        x_min_x = min(v.x for v in bbox_x); x_max_x = max(v.x for v in bbox_x)
        x_min_y = min(v.y for v in bbox_x); x_max_y = max(v.y for v in bbox_x)
        for y in trimmed_y:
            if y.name not in bpy.data.objects:
                continue
            bbox_y = [y.matrix_world @ Vector(c) for c in y.bound_box]
            y_min_x = min(v.x for v in bbox_y); y_max_x = max(v.x for v in bbox_y)
            y_min_y = min(v.y for v in bbox_y); y_max_y = max(v.y for v in bbox_y)
            overlap_wx = min(x_max_x, y_max_x) - max(x_min_x, y_min_x)
            overlap_wy = min(x_max_y, y_max_y) - max(x_min_y, y_min_y)
            if overlap_wx > clearance and overlap_wy > clearance:
                x_min_z = min(v.z for v in bbox_x); x_max_z = max(v.z for v in bbox_x)
                y_min_z = min(v.z for v in bbox_y); y_max_z = max(v.z for v in bbox_y)
                overlap_hz = min(x_max_z, y_max_z) - max(x_min_z, y_min_z)
                if overlap_hz > material_thickness * 0.02:
                    intersections.append((y, overlap_hz,
                                          max(x_min_x, y_min_x), min(x_max_x, y_max_x),
                                          max(x_min_y, y_min_y), min(x_max_y, y_max_y),
                                          max(x_min_z, y_min_z), min(x_max_z, y_max_z)))
        if not intersections:
            bpy.data.objects.remove(x, do_unlink=True)
            continue
        # Determinar Z bounds de intersección real
        z_min_bound = min(item[6] for item in intersections)
        z_max_bound = max(item[7] for item in intersections)
        # Centro XY y dimensiones XY de la pieza
        center_x = Vector(((x_min_x+x_max_x)/2, (x_min_y+x_max_y)/2, 0))
        size_x = (x_max_x - x_min_x)
        size_y = (x_max_y - x_min_y)
        # Recortar arriba
        bbox_x = [x.matrix_world @ Vector(c) for c in x.bound_box]
        x_max_z = max(v.z for v in bbox_x)
        if x_max_z > z_max_bound + 1e-4:
            height = x_max_z - z_max_bound
            center_z = (x_max_z + z_max_bound) / 2
            cutter = create_cube_slab("CutterTrimXTop",
                                     (center_x.x, center_x.y, center_z),
                                     (size_x/2 + material_thickness, size_y/2 + material_thickness, height/2 + 0.001))
            apply_boolean_modifier(x, cutter, operation='DIFFERENCE')
            if cutter.name in bpy.data.objects:
                bpy.data.objects.remove(cutter, do_unlink=True)
        # Recortar abajo
        x_min_z = min(v.z for v in bbox_x)
        if x_min_z < z_min_bound - 1e-4:
            height = z_min_bound - x_min_z
            center_z = (x_min_z + z_min_bound) / 2
            cutter = create_cube_slab("CutterTrimXBot",
                                     (center_x.x, center_x.y, center_z),
                                     (size_x/2 + material_thickness, size_y/2 + material_thickness, height/2 + 0.001))
            apply_boolean_modifier(x, cutter, operation='DIFFERENCE')
            if cutter.name in bpy.data.objects:
                bpy.data.objects.remove(cutter, do_unlink=True)
        trimmed_x.append(x)

    return trimmed_x, trimmed_y

def export_objects_to_obj(objects, filepath):
    """Exporta manualmente los objetos a formato OBJ"""
    with open(filepath, 'w') as f:
        f.write("# Exported by custom OBJ exporter\n")
        f.write("mtllib custom.mtl\n")
        
        vertex_offset = 1
        for obj in objects:
            if obj.type != 'MESH':
                continue
                
            mesh = obj.data
            matrix = obj.matrix_world
            
            # Escribir vértices
            for vert in mesh.vertices:
                global_vert = matrix @ vert.co
                f.write(f"v {global_vert.x:.6f} {global_vert.y:.6f} {global_vert.z:.6f}\n")
            
            # Escribir normales
            for poly in mesh.polygons:
                normal = poly.normal.normalized()
                f.write(f"vn {normal.x:.6f} {normal.y:.6f} {normal.z:.6f}\n")
            
            # Escribir caras
            f.write(f"g {obj.name}\n")
            f.write(f"o {obj.name}\n")
            f.write("usemtl diffuse_0\n")
            
            for poly in mesh.polygons:
                face_indices = []
                for vert_idx, loop_idx in zip(poly.vertices, poly.loop_indices):
                    # Índices son 1-based en OBJ
                    v_idx = vertex_offset + vert_idx
                    n_idx = poly.index 
                    face_indices.append(f"{v_idx}//{n_idx}")
                
                f.write(f"f {' '.join(face_indices)}\n")
            
            vertex_offset += len(mesh.vertices)

def remove_floating_pieces(pieces, material_thickness):
    """
    Elimina piezas que no tengan intersección real con ninguna otra pieza:
    definimos intersección real si hay solapamiento > clearance en X y Y, y solapamiento en Z > un umbral.
    """
    to_remove = []
    for i, p in enumerate(pieces):
        if p.name not in bpy.data.objects:
            continue
        bbox_p = [p.matrix_world @ Vector(c) for c in p.bound_box]
        p_min_x = min(v.x for v in bbox_p); p_max_x = max(v.x for v in bbox_p)
        p_min_y = min(v.y for v in bbox_p); p_max_y = max(v.y for v in bbox_p)
        p_min_z = min(v.z for v in bbox_p); p_max_z = max(v.z for v in bbox_p)
        has_intersection = False
        for j, q in enumerate(pieces):
            if i == j: continue
            if q.name not in bpy.data.objects:
                continue
            bbox_q = [q.matrix_world @ Vector(c) for c in q.bound_box]
            q_min_x = min(v.x for v in bbox_q); q_max_x = max(v.x for v in bbox_q)
            q_min_y = min(v.y for v in bbox_q); q_max_y = max(v.y for v in bbox_q)
            q_min_z = min(v.z for v in bbox_q); q_max_z = max(v.z for v in bbox_q)
            # Chequear solapamiento en X y Y
            overlap_wx = min(p_max_x, q_max_x) - max(p_min_x, q_min_x)
            overlap_wy = min(p_max_y, q_max_y) - max(p_min_y, q_min_y)
            if overlap_wx > clearance and overlap_wy > clearance:
                # Chequear solapamiento en Z
                overlap_hz = min(p_max_z, q_max_z) - max(p_min_z, q_min_z)
                # Umbral: algo pequeño, por ejemplo 1% de grosor o material_thickness*0.01
                if overlap_hz > material_thickness * 0.01:
                    has_intersection = True
                    break
        if not has_intersection:
            to_remove.append(p)
    # Eliminar las piezas aisladas
    for p in to_remove:
        if p.name in bpy.data.objects:
            print(f"Eliminando pieza flotante/aislada: {p.name}")
            bpy.data.objects.remove(p, do_unlink=True)
    # Retornar lista filtrada
    return [p for p in pieces if p.name in bpy.data.objects]


def run_slicer(model_filepath):
    original_model = None
    if USE_TEST_SPHERE:
        clean_scene()
        bpy.ops.mesh.primitive_uv_sphere_add(radius=sphere_radius_m, enter_editmode=False, align='WORLD', location=(0,0,0))
        original_model = bpy.context.active_object
        original_model.name="TestSphere"
    elif USE_EXISTING_OBJECT:
        if existing_object_name in bpy.data.objects:
            original_model = bpy.data.objects[existing_object_name]
        else:
            print(f"ERROR: No se encontró '{existing_object_name}'")
            return
    elif USE_FILE_IMPORT:
        clean_scene()
        if not ensure_obj_io_enabled('import'):  # Cambiado aquí
            print("ERROR import OBJ")
            return
        if not os.path.exists(model_filepath):
            print(f"ERROR: archivo no existe '{model_filepath}'")
            return
        try:
            if hasattr(bpy.ops.wm, 'obj_import'):
                bpy.ops.wm.obj_import(filepath=model_filepath)
            else:
                bpy.ops.import_scene.obj(filepath=model_filepath)
        except Exception as e:
            print("ERROR import:", e)
            return
        if bpy.context.selected_objects:
            if len(bpy.context.selected_objects)>1:
                bpy.ops.object.join()
            original_model = bpy.context.active_object
            base_name = os.path.splitext(os.path.basename(model_filepath))[0]
            original_model.name = base_name
            # original_model.rotation_euler=(0,0,0)
            # bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        else:
            print("ERROR: No se pudo importar.")
            return
    else:
        print("Selecciona modo de operación")
        return

    bpy.ops.object.select_all(action='DESELECT')
    original_model.select_set(True)
    bpy.context.view_layer.objects.active=original_model
    processing_model = original_model.copy()
    processing_model.data = original_model.data.copy()
    processing_model.name="ProcessingClone"
    bpy.context.collection.objects.link(processing_model)
    bpy.context.view_layer.objects.active=processing_model

    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    processing_model.location=(0,0,0)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    min_x, max_x, min_y, max_y, min_z, max_z, dims, center = get_bounding_box_info(processing_model)
    if any(d==0 for d in dims):
        print("ERROR: dimensiones cero")
        bpy.data.objects.remove(processing_model, do_unlink=True)
        return
    scale_factor = rescale_target_size_m / max(dims)
    processing_model.scale=(scale_factor,scale_factor,scale_factor)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    if offset_x_m!=0:
        processing_model.location.x += offset_x_m
        bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    min_x, max_x, min_y, max_y, min_z, max_z, model_dims, model_center = get_bounding_box_info(processing_model)
    slab_buffer_xy = max(model_dims.x, model_dims.y)*2
    slab_buffer_z = model_dims.z*2

    x_pieces = []
    y_pieces = []

    # Calcular N_x proporcionalmente a N_y y a la relación ancho/alto
    global N_x
    if N_x is None:
        ancho = model_dims.x
        alto = model_dims.y
        if alto > 0:
            N_x = max(1, round(N_y * (ancho / alto)))
        else:
            N_x = 1
        print(f"Número de cortes en X calculado automáticamente: {N_x}")

    # Rebanado en X
    slice_step_x = model_dims.x / N_x
    for i in range(N_x):
        slab_center_x = min_x + (i+0.5)*slice_step_x
        slab = create_cube_slab(f"Slab_X_{i}", (slab_center_x, model_center.y, model_center.z),
                                (material_thickness, slab_buffer_xy, slab_buffer_z))
        slice_obj = processing_model.copy()
        slice_obj.data = processing_model.data.copy()
        slice_obj.name=f"Slice_X_{i}"
        bpy.context.collection.objects.link(slice_obj)
        success = apply_boolean_modifier(slice_obj, slab, 'INTERSECT')
        if slab.name in bpy.data.objects: bpy.data.objects.remove(slab, do_unlink=True)
        if not success:
            if slice_obj.name in bpy.data.objects: bpy.data.objects.remove(slice_obj, do_unlink=True)
            continue
        bpy.ops.object.select_all(action='DESELECT')
        if slice_obj.name not in bpy.data.objects: continue
        slice_obj = bpy.data.objects.get(slice_obj.name)
        slice_obj.select_set(True)
        bpy.context.view_layer.objects.active=slice_obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type='LOOSE')
        bpy.ops.object.mode_set(mode='OBJECT')
        parts=[o for o in bpy.context.selected_objects if o.name.startswith("Slice_X_")]
        if not parts:
            parts=[o for o in bpy.context.selected_objects if o.type=='MESH' and o.name!=processing_model.name]
        for idx, part in enumerate(parts):
            if part.name not in bpy.data.objects: continue
            new_name=f"Piece_X_{i}_{idx}"
            part.name=new_name
            solid=extract_and_extrude_outline(part, 'X', material_thickness, outline_prefix=f"{new_name}_Outline_")
            if solid: x_pieces.append(solid)
        for part in parts:
            if part.name in bpy.data.objects:
                try: bpy.data.objects.remove(part, do_unlink=True)
                except: pass

    # Rebanado en Y
    slice_step_y = model_dims.y / N_y
    for j in range(N_y):
        slab_center_y = min_y + (j+0.5)*slice_step_y
        slab = create_cube_slab(f"Slab_Y_{j}", (model_center.x, slab_center_y, model_center.z),
                                (slab_buffer_xy, material_thickness, slab_buffer_z))
        slice_obj = processing_model.copy()
        slice_obj.data = processing_model.data.copy()
        slice_obj.name=f"Slice_Y_{j}"
        bpy.context.collection.objects.link(slice_obj)
        success = apply_boolean_modifier(slice_obj, slab, 'INTERSECT')
        if slab.name in bpy.data.objects: bpy.data.objects.remove(slab, do_unlink=True)
        if not success:
            if slice_obj.name in bpy.data.objects: bpy.data.objects.remove(slice_obj, do_unlink=True)
            continue
        bpy.ops.object.select_all(action='DESELECT')
        if slice_obj.name not in bpy.data.objects: continue
        slice_obj = bpy.data.objects.get(slice_obj.name)
        slice_obj.select_set(True)
        bpy.context.view_layer.objects.active=slice_obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type='LOOSE')
        bpy.ops.object.mode_set(mode='OBJECT')
        parts=[o for o in bpy.context.selected_objects if o.name.startswith("Slice_Y_")]
        if not parts:
            parts=[o for o in bpy.context.selected_objects if o.type=='MESH' and o.name!=processing_model.name]
        for idx, part in enumerate(parts):
            if part.name not in bpy.data.objects: continue
            new_name=f"Piece_Y_{j}_{idx}"
            part.name=new_name
            solid=extract_and_extrude_outline(part, 'Y', material_thickness, outline_prefix=f"{new_name}_Outline_")
            if solid: y_pieces.append(solid)
        for part in parts:
            if part.name in bpy.data.objects:
                try: bpy.data.objects.remove(part, do_unlink=True)
                except: pass

    # Eliminar clon principal
    if processing_model.name in bpy.data.objects:
        bpy.data.objects.remove(processing_model, do_unlink=True)

    # Recortar piezas extendidas verticalmente y filtrar aisladas
    x_pieces, y_pieces = trim_and_filter_pieces(x_pieces, y_pieces, material_thickness)

    # Creación de ranuras con verificación de cruce real (evita 'ranuras fantasma')
    print("Creando ranuras en intersecciones reales...")
    slot_width_cut = material_thickness + (clearance*2)
    for i, x_piece in enumerate(list(x_pieces)):
        if x_piece.name not in bpy.data.objects: continue
        bbox_x = [x_piece.matrix_world @ Vector(c) for c in x_piece.bound_box]
        x_min_x = min(v.x for v in bbox_x); x_max_x = max(v.x for v in bbox_x)
        x_min_y = min(v.y for v in bbox_x); x_max_y = max(v.y for v in bbox_x)
        x_min_z = min(v.z for v in bbox_x); x_max_z = max(v.z for v in bbox_x)
        for j, y_piece in enumerate(list(y_pieces)):
            if y_piece.name not in bpy.data.objects: continue
            bbox_y = [y_piece.matrix_world @ Vector(c) for c in y_piece.bound_box]
            y_min_x = min(v.x for v in bbox_y); y_max_x = max(v.x for v in bbox_y)
            y_min_y = min(v.y for v in bbox_y); y_max_y = max(v.y for v in bbox_y)
            y_min_z = min(v.z for v in bbox_y); y_max_z = max(v.z for v in bbox_y)
            # Verificar solapamiento XY sustancial (> clearance)
            overlap_wx = min(x_max_x, y_max_x) - max(x_min_x, y_min_x)
            overlap_wy = min(x_max_y, y_max_y) - max(x_min_y, y_min_y)
            if overlap_wx <= clearance or overlap_wy <= clearance:
                continue
            # Verificar solapamiento Z sustancial
            z_min_ov = max(x_min_z, y_min_z)
            z_max_ov = min(x_max_z, y_max_z)
            overlap_hz = z_max_ov - z_min_ov
            if overlap_hz <= material_thickness * 0.02:
                continue
            cx = (max(x_min_x, y_min_x) + min(x_max_x, y_max_x)) / 2
            cy = (max(x_min_y, y_min_y) + min(x_max_y, y_max_y)) / 2
            # Profundidad de ranura: no exceder la mitad del grosor menos clearance, ni la mitad del solapamiento menos margen
            depth_candidate = (overlap_hz / 2.0) - slot_margin
            max_depth = (material_thickness / 2.0) - clearance
            slot_depth = min(depth_candidate, max_depth)
            if slot_depth <= 0:
                continue
            # Ranura en X: cortar mitad inferior
            cutter_dims_x = (slot_width_cut, slot_width_cut, slot_depth + clearance)
            center_z_x = z_min_ov + slot_depth/2
            cutter_x = create_cube_slab(f"Cutter_X_{i}_{j}", (cx, cy, center_z_x), cutter_dims_x)
            ok_x = apply_boolean_modifier(x_piece, cutter_x, operation='DIFFERENCE')
            if cutter_x.name in bpy.data.objects: bpy.data.objects.remove(cutter_x, do_unlink=True)
            # Ranura en Y: cortar mitad superior
            cutter_dims_y = (slot_width_cut, slot_width_cut, slot_depth + clearance)
            center_z_y = z_max_ov - slot_depth/2
            cutter_y = create_cube_slab(f"Cutter_Y_{i}_{j}", (cx, cy, center_z_y), cutter_dims_y)
            ok_y = apply_boolean_modifier(y_piece, cutter_y, operation='DIFFERENCE')
            if cutter_y.name in bpy.data.objects: bpy.data.objects.remove(cutter_y, do_unlink=True)
            # Si alguna boolean falla, mostrar aviso
            if not ok_x or not ok_y:
                print(f"Aviso: boolean falló en ranura entre Piece_X_{i} y Piece_Y_{j}")

    # Antes de eliminar el objeto original
    nombre_objeto_export = original_model.name if original_model else "resultado_exportado"

    # Limpieza final
    if not USE_EXISTING_OBJECT and original_model and original_model.name in bpy.data.objects:
        bpy.data.objects.remove(original_model, do_unlink=True)
    all_pieces = [p for p in x_pieces + y_pieces if p.name in bpy.data.objects]
    print(f"Proceso completado antes de limpieza: {len(all_pieces)} piezas con ranuras.")

    # --- NUEVO: Eliminar piezas flotantes/aisladas tras ranuras ---
    all_pieces = remove_floating_pieces(all_pieces, material_thickness)
    print(f"Piezas restantes tras eliminar flotantes: {len(all_pieces)}")

    bpy.ops.object.select_all(action='DESELECT')
    for piece in all_pieces:
        piece.select_set(True)

    # --- Limpieza de Geometría antes de Exportar ---
    print("Limpiando geometría de las piezas finales para eliminar artefactos...")
    bpy.ops.object.select_all(action='DESELECT')
    for piece in list(all_pieces):
        if piece.name in bpy.data.objects and piece.type == 'MESH':
            bpy.context.view_layer.objects.active = piece
            piece.select_set(True)
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            # Elimina vértices, aristas y caras que no están conectados a la malla principal.
            bpy.ops.mesh.delete_loose()
            bpy.ops.object.mode_set(mode='OBJECT')
            piece.select_set(False)

            bpy.context.view_layer.objects.active = piece
            remesh_mod = piece.modifiers.new(name="Remesh", type='REMESH')
            remesh_mod.mode = 'VOXEL'
            # Voxel size más pequeño para fidelidad
            remesh_mod.voxel_size = material_thickness / 8.0 
            remesh_mod.use_remove_disconnected = True
            
            try:
                bpy.ops.object.modifier_apply(modifier=remesh_mod.name)
            except RuntimeError:
                piece.modifiers.remove(remesh_mod)

    # --- Unir todas las piezas en un solo objeto antes de exportar ---
    if all_pieces:
        # Filtrar solo piezas que realmente existen
        valid_pieces = [p for p in all_pieces if p.name in bpy.data.objects]
        
        if valid_pieces:
            print("Uniendo todas las piezas en un solo objeto...")
            bpy.ops.object.select_all(action='DESELECT')
            for piece in valid_pieces:
                piece.select_set(True)
            
            # Se necesita un objeto activo para la operación de unión
            bpy.context.view_layer.objects.active = valid_pieces[0]
            bpy.ops.object.join()
            
            # Después de unir, el objeto activo es el resultado
            final_object = bpy.context.active_object
            # Renombrar el objeto final
            base_name = os.path.splitext(os.path.basename(model_filepath))[0]
            final_object.name = f"{base_name}_Joined"
            all_pieces = [final_object]
        else:
            print("Advertencia: No se encontraron piezas válidas para unir.")
            all_pieces = []

    # --- Definir ruta de exportación ---
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    base_name = os.path.splitext(os.path.basename(model_filepath))[0]
    output_filename = f"{base_name}_Joined.obj"
    output_obj_filepath = os.path.join(workspace_dir, output_filename)

    # --- Exportar como .obj con solución manual ---
    if all_pieces and all_pieces[0].name in bpy.data.objects:
        print(f"Exportando objeto final a: {output_obj_filepath}")
        export_objects_to_obj(all_pieces, output_obj_filepath)

        # Rotar 90 grados en X para que se vea "parado" en la interfaz
        final_object = all_pieces[0]
        final_object.rotation_euler = (math.radians(90), 0, 0)
        bpy.context.view_layer.objects.active = final_object
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    else:
        print("ERROR: No se pudo exportar. No quedan piezas válidas.")

if __name__ == "__main__":
    # --- Lógica para recibir argumentos desde la línea de comandos ---
    model_path_arg = None
    try:
        args = sys.argv
        if '--' in args:
            script_args = args[args.index('--') + 1:]
            if '--model_filepath' in script_args:
                try:
                    index = script_args.index('--model_filepath')
                    model_path_arg = script_args[index + 1]
                    print(f"Argumento de ruta de modelo recibido: {model_path_arg}")
                except IndexError:
                    print("Error: El argumento --model_filepath fue proporcionado pero sin una ruta.")
            elif len(script_args) > 0:
                model_path_arg = script_args[0]
                print(f"Argumento posicional de ruta de modelo recibido: {model_path_arg}")
            else:
                print("Advertencia: No se proporcionó la ruta del modelo como argumento.")
        else:
            print("Advertencia: Ejecutando sin argumentos. Usa 'blender -b -P script.py -- /ruta/a/modelo.obj'")
    except Exception as e:
        print(f"Error al procesar argumentos: {e}")

    if model_path_arg:
        run_slicer(model_path_arg)
    else:
        print("Ejecutando con ruta de fallback (si está definida).")
        # fallback_path = "D:/Ifurniture/IA nueva/hunyuan3d2_local/alpaki_clean.obj"
        # run_slicer(fallback_path)
        pass
