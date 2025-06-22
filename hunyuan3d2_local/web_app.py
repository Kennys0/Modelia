import subprocess
import os
import sys
import shutil
import time
from flask import Flask, render_template, jsonify, url_for, Response, request
from pyngrok import ngrok

# --- CONFIGURACIÓN DE LA APLICACIÓN FLASK ---
app = Flask(__name__)
# Desactivar el caché para asegurar que los cambios en los archivos estáticos se reflejen
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0


# --- CONFIGURACIÓN DE RUTAS DEL PROYECTO ---
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
# CORRECCIÓN: Apuntar al ejecutable de Blender en el entorno de Colab
BLENDER_EXECUTABLE = os.path.join(WORKSPACE_DIR, "blender-4.1.1-linux-x64", "blender")
# Restaurar el script principal
BLENDER_SCRIPT = os.path.join(WORKSPACE_DIR, "test_outline_extraction.py") 
BLENDER_LOG_FILE = os.path.join(WORKSPACE_DIR, "blender_log.txt") 

# CORRECCIÓN: Apuntar a la subcarpeta donde Hunyuan realmente guarda el modelo
HUNYUAN_DIR = os.path.join(WORKSPACE_DIR, "hunyuan3d2")
HUNYUAN_SCRIPT = os.path.join(HUNYUAN_DIR, "minimal_demo.py")
BASE_MODEL_NAME = "tigre_mini_clean.obj"
BASE_MODEL_PATH = os.path.join(HUNYUAN_DIR, BASE_MODEL_NAME) # Ruta corregida

STATIC_MODELS_DIR = os.path.join(WORKSPACE_DIR, "static", "models")
STATIC_MATERIALS_DIR = os.path.join(WORKSPACE_DIR, "static", "materials")

# Crear directorios estáticos al inicio
os.makedirs(STATIC_MODELS_DIR, exist_ok=True)
os.makedirs(STATIC_MATERIALS_DIR, exist_ok=True)

# Variable global para no perder la referencia al último modelo
last_processed_model_name = "final_model.obj"

def run_blender_script(model_path, is_reprocessing=False):
    """Ejecuta Blender usando el shell y redirigiendo stderr a stdout para máxima captura de errores."""
    
    # Verificación de ruta
    if not os.path.exists(BLENDER_EXECUTABLE):
        error_msg = f"Error Crítico: No se encontró el ejecutable de Blender en la ruta: '{BLENDER_EXECUTABLE}'."
        with open(BLENDER_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(error_msg)
        raise Exception(error_msg)

    # Construir el comando como una sola cadena de texto
    command_str = f'"{BLENDER_EXECUTABLE}" --background --python "{os.path.abspath(BLENDER_SCRIPT)}" -- --model_filepath "{os.path.abspath(model_path)}"'
    if is_reprocessing:
        command_str += ' --is-reprocessing'

    print(f"Ejecutando Blender con shell: {command_str}")
    
    try:
        # CORRECCIÓN: Quitar 'capture_output' y usar 'stdout=subprocess.PIPE' manualmente.
        process = subprocess.run(
            command_str,
            shell=True,
            text=True,
            encoding='utf-8',
            check=True,
            stdout=subprocess.PIPE,   # Capturar la salida estándar
            stderr=subprocess.STDOUT  # Redirigir la salida de error a la estándar
        )
        # Si todo va bien, la salida se escribe en el log.
        with open(BLENDER_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(process.stdout or "El script de Blender se ejecutó sin errores pero no produjo salida de texto.")
            
    except subprocess.CalledProcessError as e:
        # Con la redirección, toda la salida (normal y de error) estará en e.stdout.
        log_content = f"--- SALIDA COMBINADA DE BLENDER (STDOUT + STDERR) ---\n{e.stdout}"
        with open(BLENDER_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(log_content)
        raise Exception("El script de Blender falló.")


@app.route('/')
def index():
    """Sirve la página principal."""
    return render_template('index.html')


@app.route('/get-log')
def get_log():
    """Endpoint para obtener el contenido del último log de Blender."""
    log_content = "No se encontró el archivo de log o está vacío."
    if os.path.exists(BLENDER_LOG_FILE):
        with open(BLENDER_LOG_FILE, 'r', encoding='utf-8') as f:
            log_content = f.read() or "El archivo de log está vacío."
    return Response(log_content, mimetype='text/plain')


# --- INICIO: IA Stable Diffusion local para generar imagen desde prompt ---
def generar_imagen_ia(prompt, output_path):
    from diffusers import StableDiffusionPipeline
    import torch
    pipe = StableDiffusionPipeline.from_pretrained(
        'stabilityai/sdxl-turbo',
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
    )
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    pipe = pipe.to(device, dtype)
    image = pipe(prompt).images[0]
    image.save(output_path)
    return output_path
# --- FIN IA ---

@app.route('/run-process', methods=['POST'])
def run_process():
    """Ejecuta el flujo COMPLETO: generación y procesamiento."""
    
    # --- NUEVO: Si hay prompt, generar imagen IA ---
    prompt = request.form.get('prompt')
    input_image_path = None
    generated_obj_path = None
    if prompt:
        input_image_path = os.path.join(STATIC_MATERIALS_DIR, 'input_image.png')
        print(f"Generando imagen IA desde prompt: {prompt}")
        generar_imagen_ia(prompt, input_image_path)
        print(f"Imagen IA guardada en {input_image_path}")
        # --- Generar modelo 3D desde la imagen IA ---
        generated_obj_path = os.path.join(WORKSPACE_DIR, 'generated_model.obj')
        minimal_demo_py = os.path.join(HUNYUAN_DIR, 'minimal_demo.py')
        env_python = os.path.join(WORKSPACE_DIR, "env", "Scripts", "python.exe")
        if not os.path.exists(env_python):
            env_python = "python"
        minimal_demo_cmd = f'"{env_python}" "{minimal_demo_py}" --input_image "{input_image_path}" --output_obj "{generated_obj_path}"'
        print(f"Ejecutando minimal_demo.py: {minimal_demo_cmd}")
        try:
            subprocess.run(minimal_demo_cmd, check=True, shell=True, cwd=HUNYUAN_DIR, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: La generación del modelo 3D desde imagen IA falló.\n--- STDOUT ---\n{e.stdout}\n--- STDERR ---\n{e.stderr}")
            return jsonify({'success': False, 'message': 'Falló la generación del modelo 3D desde imagen IA.'})
        model_input_path = generated_obj_path
        # El nombre base para la exportación debe ser el del modelo generado
        output_filename_base = os.path.splitext(os.path.basename(generated_obj_path))[0]
    else:
        model_input_path = BASE_MODEL_PATH
        output_filename_base = os.path.splitext(os.path.basename(BASE_MODEL_PATH))[0]

    # --- PASO 2: Procesar con Blender ---
    try:
        run_blender_script(model_input_path, is_reprocessing=False)
        processed_obj_path = os.path.join(WORKSPACE_DIR, f"{output_filename_base}_Joined.obj")
        if not os.path.exists(processed_obj_path):
             return jsonify({'success': False, 'message': 'Blender terminó pero no se encontró el objeto procesado.'})
        final_static_path = os.path.join(STATIC_MODELS_DIR, "final_model.obj")
        shutil.move(processed_obj_path, final_static_path)
        model_url = url_for('static', filename='models/final_model.obj')
        return jsonify({
            'success': True,
            'message': 'Proceso completado.',
            'model_url': f"{model_url}?v={int(time.time())}"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/reprocess-last', methods=['POST'])
def reprocess_last():
    """Endpoint para REPROCESAR el último objeto generado, saltándose la generación."""
    
    if not os.path.exists(BASE_MODEL_PATH):
        return jsonify({'success': False, 'message': f'No se encontró el modelo para reprocesar en {BASE_MODEL_PATH}.'})

    try:
        run_blender_script(BASE_MODEL_PATH, is_reprocessing=True)

        output_filename_base = os.path.splitext(os.path.basename(BASE_MODEL_PATH))[0]
        processed_obj_path = os.path.join(WORKSPACE_DIR, f"{output_filename_base}_Joined.obj")

        if not os.path.exists(processed_obj_path):
             return jsonify({'success': False, 'message': 'Blender terminó pero no se encontró el objeto reprocesado.'})

        final_static_path = os.path.join(STATIC_MODELS_DIR, last_processed_model_name)
        shutil.move(processed_obj_path, final_static_path)
        
        model_url = url_for('static', filename=f'models/{last_processed_model_name}')
        return jsonify({
            'success': True,
            'message': 'Reproceso completado.',
            'model_url': f"{model_url}?v={int(time.time())}"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


if __name__ == '__main__':
    # Abrir un túnel HTTP en el puerto 5000 con ngrok
    public_url = ngrok.connect(5000)
    print(f" * URL pública de ngrok: {public_url}")
    # Iniciar la aplicación en el puerto 5000
    app.run(port=5000) 