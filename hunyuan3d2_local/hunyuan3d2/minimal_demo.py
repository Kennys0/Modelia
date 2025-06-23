import argparse
from PIL import Image
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline, FloaterRemover
import torch
import os
from hy3dgen.rembg import BackgroundRemover

print("Iniciando demo (versión mini)...")

parser = argparse.ArgumentParser(description="Generador 3D desde imagen IA")
parser.add_argument('--input_image', type=str, default=None, help='Ruta de la imagen de entrada')
parser.add_argument('--output_obj', type=str, default=None, help='Ruta de salida del modelo OBJ')
args = parser.parse_args()

# INSTRUCCIONES DE DESCARGA:
# 1. Ve a https://huggingface.co/tencent/Hunyuan3D-2mv
# 2. Haz clic en "Download" o usa el siguiente comando (requiere huggingface-cli):
#    huggingface-cli download tencent/Hunyuan3D-2mv --local-dir ./models/Hunyuan3D-2mv
# 3. El pipeline descargará automáticamente los archivos si tienes conexión a internet.

# Usa el modelo mini, mucho más ligero y rápido en CPU
pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    "tencent/Hunyuan3D-2mini",
    subfolder="hunyuan3d-dit-v2-mini",
    use_safetensors=True
)
print("Pipeline mini cargado.")

pipeline.to("cpu", torch.float32)
print("Pipeline movido a CPU.")

# Carga la imagen de entrada
input_image_path = args.input_image if args.input_image else "input_image.png"  # Ruta relativa para Colab/Kaggle
image = Image.open(input_image_path).convert("RGBA")
print(f"Imagen cargada: {input_image_path}")

print("Eliminando fondo de la imagen...")
remover = BackgroundRemover()
image = remover(image)
print("Fondo eliminado.")

# Genera el mesh 3D (ajusta los parámetros según tu PC)
print("Generando mesh (mini, calidad media)...")
mesh = pipeline(image=image, num_inference_steps=15, octree_resolution=120)[0]
print("Mesh generado.")

# Determina la ruta de salida
output_obj_path = args.output_obj if args.output_obj else "modelo_generado.obj"  # Ruta relativa para Colab/Kaggle

print(f"Exportando solo geometría 3D a {output_obj_path}...")
mesh.export(output_obj_path)
print(f"Exportado como {output_obj_path} (versión mini, solo geometría)")

mesh_clean = FloaterRemover()(mesh)
clean_path = os.path.splitext(output_obj_path)[0] + "_clean.obj"
mesh_clean.export(clean_path)
print(f"Exportado limpio como {clean_path}")
