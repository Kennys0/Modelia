import subprocess
import os
import sys
import shutil
import time
from flask import Flask, render_template, jsonify, url_for, Response, request
# from pyngrok import ngrok  # Comentado para uso local

# --- CONFIGURACIÓN DE LA APLICACIÓN FLASK ---
app = Flask(__name__)
# Desactivar el caché para asegurar que los cambios en los archivos estáticos se reflejen
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0


# --- CONFIGURACIÓN DE RUTAS DEL PROYECTO ---
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
# CORRECCIÓN: Apuntar al ejecutable de Blender en el entorno de Colab
BLENDER_EXECUTABLE = "blender"
# Restaurar el script principal
BLENDER_SCRIPT = os.path.join(WORKSPACE_DIR, "test_outline_extraction.py") 
BLENDER_LOG_FILE = os.path.join(WORKSPACE_DIR, "blender_log.txt") 

# CORRECCIÓN: Apuntar a la subcarpeta donde Hunyuan realmente guarda el modelo
HUNYUAN_DIR = os.path.join(WORKSPACE_DIR, "hunyuan3d2")
HUNYUAN_SCRIPT = os.path.join(HUNYUAN_DIR, "minimal_demo.py")
BASE_MODEL_NAME = "perry_clean.obj"
BASE_MODEL_PATH = os.path.join(HUNYUAN_DIR, BASE_MODEL_NAME)  # Ruta corregida

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
        'stabilityai/stable-diffusion-2-1-base',  # Modelo más ligero que SDXL-Turbo
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
    )
    pipe = pipe.to('cuda' if torch.cuda.is_available() else 'cpu')
    image = pipe(prompt).images[0]
    image.save(output_path)
    return output_path
# --- FIN IA ---

@app.route('/run-process', methods=['POST'])
def run_process():
    """Ejecuta el flujo COMPLETO: generación y procesamiento."""

    # Permite recibir la ruta de la imagen desde el frontend o usar una imagen específica
    input_image_path = request.form.get('input_image_path')
    prompt = request.form.get('prompt')
    generated_obj_path = None

    if input_image_path:
        # Usar la imagen subida por el usuario
        print(f"Usando imagen subida: {input_image_path}")
        generated_obj_path = os.path.join(WORKSPACE_DIR, 'generated_model.obj')  # <-- Aquí se genera el modelo
        minimal_demo_py = os.path.join(HUNYUAN_DIR, 'minimal_demo.py')
        env_python = os.path.join(WORKSPACE_DIR, "env", "Scripts", "python.exe")
        if not os.path.exists(env_python):
            env_python = "python"
        minimal_demo_cmd = f'"{env_python}" "{minimal_demo_py}" --input_image "{input_image_path}" --output_obj "{generated_obj_path}"'
        print(f"Ejecutando minimal_demo.py: {minimal_demo_cmd}")
        try:
            subprocess.run(minimal_demo_cmd, check=True, shell=True, cwd=HUNYUAN_DIR, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: La generación del modelo 3D desde imagen falló.\n--- STDOUT ---\n{e.stdout}\n--- STDERR ---\n{e.stderr}")
            return jsonify({'success': False, 'message': 'Falló la generación del modelo 3D desde imagen.'})
        # Aquí determinamos si existe un archivo *_clean.obj generado
        clean_obj_path = os.path.join(WORKSPACE_DIR, 'generated_model_clean.obj')
        if os.path.exists(clean_obj_path):
            print(f"Usando archivo clean: {clean_obj_path}")
            model_input_path = clean_obj_path
            output_filename_base = os.path.splitext(os.path.basename(clean_obj_path))[0]
        else:
            model_input_path = generated_obj_path
            output_filename_base = os.path.splitext(os.path.basename(generated_obj_path))[0]
    elif prompt:
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
        # Aquí determinamos si existe un archivo *_clean.obj generado
        clean_obj_path = os.path.join(WORKSPACE_DIR, 'generated_model_clean.obj')
        if os.path.exists(clean_obj_path):
            print(f"Usando archivo clean: {clean_obj_path}")
            model_input_path = clean_obj_path
            output_filename_base = os.path.splitext(os.path.basename(clean_obj_path))[0]
        else:
            model_input_path = generated_obj_path
            output_filename_base = os.path.splitext(os.path.basename(generated_obj_path))[0]
    else:
        # Por defecto, usa el modelo base (que ya debe tener la extensión _clean.obj si corresponde)
        model_input_path = BASE_MODEL_PATH
        output_filename_base = os.path.splitext(os.path.basename(BASE_MODEL_PATH))[0]

    # --- PASO 2: Procesar con Blender ---
    try:
        run_blender_script(model_input_path, is_reprocessing=False)
        processed_obj_path = os.path.join(WORKSPACE_DIR, f"{output_filename_base}_Joined.obj")
        print(f"DEBUG: Buscando archivo procesado en: {processed_obj_path}")
        print(f"DEBUG: Archivos en WORKSPACE_DIR: {os.listdir(WORKSPACE_DIR)}")
        if not os.path.exists(processed_obj_path):
             return jsonify({'success': False, 'message': f'Blender terminó pero no se encontró el objeto procesado en {processed_obj_path}.'})
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
    # Comentado para uso local sin ngrok
    public_url = ngrok.connect(5000)
    print(f" * URL pública de ngrok: {public_url}")
    
    print("🚀 Iniciando aplicación Flask localmente...")
    print("📱 Accede a: http://localhost:5000")
    print("💡 Para hacer público, instala pyngrok: pip install pyngrok")
    
    # Iniciar la aplicación en el puerto 5000
    app.run(host='0.0.0.0', port=5000, debug=True)