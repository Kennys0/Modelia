import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { MTLLoader } from 'three/addons/loaders/MTLLoader.js';

// --- ELEMENTOS DEL DOM ---
const generateBtn = document.getElementById('generate-btn');
const reprocessBtn = document.getElementById('reprocess-btn');
const statusText = document.getElementById('status');
const viewerContainer = document.getElementById('viewer-container');
const promptInput = document.getElementById('prompt-input');

// --- ESTADO DE LA APP ---
let scene, camera, renderer, controls;
let modelLoaded = false;

// --- FUNCIÓN PRINCIPAL DE VISUALIZACIÓN ---
function initViewer(modelUrl) {
    // Limpiar el contenedor antes de inicializar
    viewerContainer.innerHTML = '';
    viewerContainer.classList.remove('loader');

    // 1. Escena
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xffffff);

    // 2. Cámara (con 'near' ajustado para evitar el recorte)
    camera = new THREE.PerspectiveCamera(75, viewerContainer.clientWidth / viewerContainer.clientHeight, 0.01, 1000);
    camera.position.set(0, 0.5, 2);

    // 3. Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(viewerContainer.clientWidth, viewerContainer.clientHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    viewerContainer.appendChild(renderer.domElement);

    // 4. Controles de órbita
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;

    // 5. Luces
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);
    
    const mainLight = new THREE.DirectionalLight(0xffffff, 1.5);
    mainLight.position.set(8, 10, 5);
    mainLight.castShadow = true;
    scene.add(mainLight);

    mainLight.shadow.mapSize.width = 2048;
    mainLight.shadow.mapSize.height = 2048;

    const fillLight = new THREE.DirectionalLight(0xffffff, 0.2);
    fillLight.position.set(-5, -5, -5);
    scene.add(fillLight);

    // 6. Cargar el material (.mtl) y luego el modelo (.obj)
    const mtlLoader = new MTLLoader();
    mtlLoader.setPath('/static/materials/');
    mtlLoader.load('custom.mtl', 
        (materials) => {
            materials.preload();
            
            const objLoader = new OBJLoader();
            objLoader.setMaterials(materials);
            objLoader.load(modelUrl, (object) => {
                loadObject(object);
            }, undefined, (error) => {
                handleLoadError(error, 'OBJ con material');
            });
        },
        undefined,
        (error) => {
            console.warn('No se pudo cargar el archivo MTL personalizado. Usando material por defecto.');
            const objLoader = new OBJLoader();
            objLoader.load(modelUrl, (object) => {
                loadObject(object);
            }, undefined, (error) => {
                handleLoadError(error, 'OBJ sin material');
            });
        }
    );

    function loadObject(object) {
        const cleanGroup = new THREE.Group();
        object.traverse((child) => {
            if (child instanceof THREE.Mesh) {
                const meshClone = child.clone();
                meshClone.castShadow = true;
                meshClone.receiveShadow = true;

                if (!child.material || Array.isArray(child.material) && child.material.length === 0) {
                     meshClone.material = new THREE.MeshStandardMaterial({
                        color: 0xcccccc,
                        metalness: 0.1,
                        roughness: 0.8
                    });
                }
                cleanGroup.add(meshClone);
            }
        });

        const box = new THREE.Box3().setFromObject(cleanGroup);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        cleanGroup.position.sub(center);

        const maxDim = Math.max(size.x, size.y, size.z);
        mainLight.shadow.camera.left = -maxDim;
        mainLight.shadow.camera.right = maxDim;
        mainLight.shadow.camera.top = maxDim;
        mainLight.shadow.camera.bottom = -maxDim;
        mainLight.shadow.camera.updateProjectionMatrix();

        scene.add(cleanGroup);
        modelLoaded = true;
        statusText.textContent = '¡Modelo cargado! Usa el ratón para explorar.';
    }
    
    function handleLoadError(error, context) {
        console.error(`Error al cargar el modelo (${context}):`, error);
        statusText.textContent = 'Error al cargar el modelo.';
        viewerContainer.innerHTML = '<p>No se pudo cargar el modelo 3D.</p>';
    }

    function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
        camera.aspect = viewerContainer.clientWidth / viewerContainer.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(viewerContainer.clientWidth, viewerContainer.clientHeight);
    });
}


// --- LÓGICA DE LA INTERACCIÓN ---

// Función auxiliar para manejar las peticiones y la UI
async function handleProcessRequest(endpoint, processType) {
    // Deshabilitar botones y mostrar estado de carga
    generateBtn.disabled = true;
    reprocessBtn.disabled = true;
    statusText.textContent = `Iniciando ${processType}... Esto puede tardar.`;
    viewerContainer.classList.add('loader');
    viewerContainer.innerHTML = '';

    try {
        let response;
        // Si hay un prompt, enviarlo como parte del FormData
        const prompt = promptInput ? promptInput.value.trim() : '';
        if (prompt) {
            const formData = new FormData();
            formData.append('prompt', prompt);
            response = await fetch(endpoint, {
                method: 'POST',
                body: formData
            });
        } else {
            response = await fetch(endpoint, {
                method: 'POST',
            });
        }

        const data = await response.json();

        if (data.success) {
            statusText.textContent = 'Proceso completado. Cargando modelo 3D...';
            initViewer(data.model_url);
        } else {
            throw new Error(data.message || 'Ocurrió un error desconocido en el servidor.');
        }

    } catch (error) {
        console.error('Error en la petición principal:', error);
        
        const mainMessage = error.message;
        statusText.innerHTML = `
            <div style="text-align: left;">
                <strong>Error: ${mainMessage}</strong>
                <pre id="log-details" style="white-space: pre-wrap; word-wrap: break-word; text-align: left; background-color: #eee; padding: 10px; border-radius: 5px; margin-top: 10px;">Cargando log...</pre>
            </div>`;
        
        try {
            const logResponse = await fetch('/get-log');
            const logText = await logResponse.text();
            document.getElementById('log-details').textContent = logText;
        } catch (logError) {
            console.error('Error al obtener el log:', logError);
            document.getElementById('log-details').textContent = 'No se pudo cargar el log del servidor.';
        }

        viewerContainer.classList.remove('loader');
        viewerContainer.innerHTML = '<p>El proceso falló. Revisa el log de arriba.</p>';
        
        generateBtn.disabled = false;
        reprocessBtn.disabled = false;
    }
}

generateBtn.addEventListener('click', () => {
    handleProcessRequest('/run-process', 'generación completa');
});

reprocessBtn.addEventListener('click', () => {
    handleProcessRequest('/reprocess-last', 'reprocesamiento');
}); 