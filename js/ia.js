import { imagenesDataUrl, capturasMicroscopio } from './ui.js';

const BACKEND_KEY = 'mx-ia-backend';
const OLLAMA_URL_KEY = 'mx-ia-ollama-url';
const OLLAMA_MOD_KEY = 'mx-ia-ollama-model';

export function inicializarConfigBackend() {
    const radioLocal = document.getElementById('ia-backend-local');
    const radioHF = document.getElementById('ia-backend-hf');
    const urlInput = document.getElementById('ia-ollama-url');
    const modelInput = document.getElementById('ia-ollama-model');
    const camposOllama = document.getElementById('ia-ollama-fields');

    const backendGuardado = localStorage.getItem(BACKEND_KEY) ?? 'hf';
    if (backendGuardado === 'local') radioLocal.checked = true;
    else radioHF.checked = true;

    const urlGuardada = localStorage.getItem(OLLAMA_URL_KEY);
    let modeloGuardado = localStorage.getItem(OLLAMA_MOD_KEY);
    if (modeloGuardado === 'medgemma:latest') {
        modeloGuardado = 'medgemma1.5:latest';
        localStorage.setItem(OLLAMA_MOD_KEY, modeloGuardado);
    }
    if (urlGuardada) urlInput.value = urlGuardada;
    if (modeloGuardado) modelInput.value = modeloGuardado;

    function aplicarBackend(val) {
        camposOllama.hidden = val !== 'local';
    }
    aplicarBackend(backendGuardado);

    [radioLocal, radioHF].forEach(r => r.addEventListener('change', () => {
        const val = document.querySelector('input[name="ia-backend"]:checked').value;
        localStorage.setItem(BACKEND_KEY, val);
        aplicarBackend(val);
    }));

    urlInput.addEventListener('input', () => localStorage.setItem(OLLAMA_URL_KEY, urlInput.value.trim()));
    modelInput.addEventListener('input', () => localStorage.setItem(OLLAMA_MOD_KEY, modelInput.value.trim()));
}

// Prompt

function construirPrompt(obtenerDatosPaciente, obtenerValoresFormulario, getUltimoAnalisis, getReferencias) {
    const paciente = obtenerDatosPaciente();
    const valores = obtenerValoresFormulario();
    const { hallazgos, patrones } = getUltimoAnalisis();
    const signosText = document.getElementById('signos-clinicos').value.trim();
    const refEspecie = paciente.especie ? (getReferencias()[paciente.especie] || {}) : {};

    const totalImagenes = imagenesDataUrl.filter(Boolean).length + capturasMicroscopio.length;
    const hayImagenes = totalImagenes > 0;

    const lineasValores = Object.entries(valores).map(([clave, valor]) => {
        const ref = refEspecie[clave];
        const nombre = ref?.nombre || clave;
        const unidad = ref?.unidad || '';
        const rango = ref ? ` [ref: ${ref.inferior}-${ref.superior}]` : '';
        const h = hallazgos.find(h => h.clave === clave);
        const flag = h ? ` ← ${h.direccion === 'alto' ? 'ELEVADO' : 'BAJO'} (${h.gravedad})` : '';
        return `  ${nombre}: ${valor} ${unidad}${rango}${flag}`;
    }).join('\n') || 'Sin valores ingresados';

    const lineasPatrones = patrones.length > 0
        ? patrones.map(p => `  - ${p.nombre}: ${p.descripcion}`).join('\n')
        : '  Ninguno detectado';

    const edadTexto = paciente.edadMeses != null
        ? (paciente.edadMeses < 24 ? `${Math.round(paciente.edadMeses)} meses` : `${(paciente.edadMeses / 12).toFixed(1)} años`)
        : 'desconocida';

    if (hayImagenes) {
        const lineasHallazgos = hallazgos.length > 0
            ? hallazgos.map(h => `  ${h.nombre}: ${h.valor} ${h.unidad || ''} (${h.direccion} · ${h.gravedad})`).join('\n')
            : '  Todos los valores normales';

        return `Eres médico veterinario especialista en patología clínica.

Paciente: ${paciente.especie || 'desconocido'}, ${paciente.raza || 'raza desconocida'}, ${edadTexto}, ${paciente.sexo || 'sexo desconocido'}

Hallazgos de laboratorio:
${lineasHallazgos}
${signosText ? `\nSignos clínicos: ${signosText}` : ''}

DATOS ADJUNTOS: ${totalImagenes} imagen${totalImagenes > 1 ? 'es' : ''} de citología.

¿Qué observas en las imágenes? Describe la morfología celular, identifica lesiones, patrones anormales, hemoparásitos (Anaplasma, Babesia, Ehrlichia, Hepatozoon, Piroplasma, Mycoplasma) e inclusiones citoplasmáticas. Luego integra con los datos de laboratorio. Responde en español.`;
    }

    const lineasHallazgos = hallazgos.length > 0
        ? hallazgos.map(h => `  ${h.nombre}: ${h.valor} ${h.unidad || ''} (${h.direccion} · ${h.gravedad})`).join('\n')
        : '  Todos los valores dentro de rangos normales';

    return `Responde en español.

Eres médico veterinario especialista en patología clínica.

Paciente: ${paciente.especie || 'desconocido'}, raza: ${paciente.raza || 'NE'}, edad: ${edadTexto}, sexo: ${paciente.sexo || 'NE'}

Hallazgos de laboratorio:
${lineasHallazgos}
${signosText ? `\nSignos clínicos: ${signosText}` : ''}

Proporciona una interpretación clínica breve (6-8 oraciones) destacando los hallazgos más significativos y las recomendaciones diagnósticas inmediatas.`;
}

function limpiarRespuesta(text) {
    if (text.includes('<start_of_turn>model')) {
        text = text.split('<start_of_turn>model').pop();
    }
    if (text.includes('<end_of_turn>')) {
        text = text.slice(0, text.indexOf('<end_of_turn>'));
    }
    if (text.includes('<unused95>')) {
        // Formato normal: <unused94>pensamiento<unused95>respuesta
        text = text.split('<unused95>').pop();
    } else if (text.includes('<unused94>')) {
        // El modelo agotó tokens en el razonamiento — mostrar el pensamiento como respuesta
        text = text.split('<unused94>').slice(1).join('').trim();
    }
    text = text.replace(/<unused\d+>/g, '');
    text = text.replace(/<start_of_turn>\w+\n?/g, '');

    // Quitar prefijos de rol que el modelo a veces antepone
    text = text.replace(/^\d+\s+(medical assistant|assistant|model)\s*/i, '');

    // Quitar bloques de razonamiento / thinking process
    text = text.replace(/^thought\s*\n?/i, '');

    // Detectar si el modelo solo generó razonamiento en inglés sin respuesta clínica
    const tieneRazonamiento = /Here'?s a thinking process|Understand the Role|Analyze the Request|Review the Lab Results|Synthesize Findings|Formulate Clinical Interpretation/i.test(text);
    const tieneEspanol = /[áéíóúñÁÉÍÓÚÑ]{2,}/.test(text) || /\b(paciente|hallazgos|interpretación|recomendaciones|análisis|resultados|clínica|diagnóstico|evaluación|hepatopatía|nefropatía|anemia|leucocitosis|neutrofilia|linfopenia|hiperglucemia|hipoglucemia|pancreatitis|hepatitis|cirrosis|insuficiencia)\b/i.test(text);
    if (tieneRazonamiento && !tieneEspanol) {
        return 'El modelo generó un proceso de razonamiento interno en lugar de una interpretación clínica. Esto suele deberse a que el modelo está configurado en modo "pensamiento". Intenta nuevamente o contacta al administrador del espacio para desactivar el modo de razonamiento.';
    }

    // Si hay razonamiento mezclado con español, intentar extraer solo la respuesta
    if (tieneRazonamiento) {
        // Buscar la primera línea que parezca español clínico
        const lineas = text.split('\n');
        let inicioRespuesta = -1;
        for (let i = 0; i < lineas.length; i++) {
            const linea = lineas[i].trim();
            if (linea.length > 20 && /[áéíóúñÁÉÍÓÚÑ]/.test(linea) && !/\*\*[^*]+\*\*/.test(linea) && !/^\d+\./.test(linea) && !/Here'?s a thinking process/i.test(linea)) {
                inicioRespuesta = i;
                break;
            }
        }
        if (inicioRespuesta > 0) {
            text = lineas.slice(inicioRespuesta).join('\n');
        }
    }

    // Quitar LaTeX
    text = text.replace(/\$\\boxed\{[^}]*\}\$/g, '');
    text = text.replace(/\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\}/g, '');
    text = text.replace(/\\[a-zA-Z]+(\{[^}]*\})?/g, '');
    text = text.replace(/\$[^$]*\$/g, '');

    // Colapsar líneas vacías múltiples
    text = text.replace(/\n{3,}/g, '\n\n').trim();

    // Cortar al primer párrafo que se repite (loop del modelo)
    const parrafos = text.split(/\n\n+/);
    const vistos = new Set();
    const sinRepetidos = [];
    for (const p of parrafos) {
        const clave = p.trim().slice(0, 80);
        if (vistos.has(clave)) break;
        vistos.add(clave);
        sinRepetidos.push(p);
    }
    text = sinRepetidos.join('\n\n');

    return text.trim() || 'Sin respuesta del modelo.';
}

// Llamado a IA

export async function llamarIA(obtenerDatosPaciente, obtenerValoresFormulario, getUltimoAnalisis, getReferencias) {
    const salidaEl = document.getElementById('salida-ia');
    const backend = document.querySelector('input[name="ia-backend"]:checked')?.value ?? 'hf';

    salidaEl.textContent = 'Consultando al modelo de I.A…';
    salidaEl.classList.add('cargando');

    try {
        if (backend === 'local') {
            await _llamarOllama(salidaEl, obtenerDatosPaciente, obtenerValoresFormulario, getUltimoAnalisis, getReferencias);
        } else {
            await _llamarSpace(salidaEl, obtenerDatosPaciente, obtenerValoresFormulario, getUltimoAnalisis, getReferencias);
        }
    } finally {
        salidaEl.classList.remove('cargando');
    }
}

// Ollama

async function _llamarOllama(salidaEl, obtenerDatosPaciente, obtenerValoresFormulario, getUltimoAnalisis, getReferencias) {
    const urlBase = (document.getElementById('ia-ollama-url')?.value ?? 'http://localhost:11434').replace(/\/$/, '');
    const model = document.getElementById('ia-ollama-model')?.value?.trim() || 'medgemma1.5:latest';
    const prompt = construirPrompt(obtenerDatosPaciente, obtenerValoresFormulario, getUltimoAnalisis, getReferencias);
    const imagenes = [...imagenesDataUrl.filter(Boolean), ...capturasMicroscopio];

    const contenido = [];
    for (const img of imagenes) {
        if (typeof img === 'string' && img.startsWith('data:image/'))
            contenido.push({ type: 'image_url', image_url: { url: img } });
    }
    contenido.push({ type: 'text', text: prompt });

    try {
        const res = await fetch(`${urlBase}/v1/chat/completions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model,
                messages: [{ role: 'user', content: contenido.length === 1 ? prompt : contenido }],
                max_tokens: imagenes.length > 0 ? 1200 : 600,
                stream: false,
                think: false,
            }),
        });

        let data;
        try { data = await res.json(); } catch {
            salidaEl.textContent = `Error del servidor Ollama (HTTP ${res.status}). Verifica que esté ejecutándose.`;
            return;
        }

        if (!res.ok) {
            salidaEl.textContent = `Error Ollama: ${data?.error?.message ?? data?.error ?? `HTTP ${res.status}`}`;
        } else {
            salidaEl.textContent = limpiarRespuesta(data?.choices?.[0]?.message?.content ?? 'Sin respuesta del modelo.');
        }
    } catch {
        salidaEl.textContent = `No se pudo conectar con Ollama en ${urlBase}. Verifica que esté ejecutándose con "ollama serve".`;
    }
}

// Morphos AI Space

async function _llamarSpace(salidaEl, obtenerDatosPaciente, obtenerValoresFormulario, getUltimoAnalisis, getReferencias) {
    let prompt = construirPrompt(obtenerDatosPaciente, obtenerValoresFormulario, getUltimoAnalisis, getReferencias);
    
    // HACK: Prepend <unused95> to force medGemma to skip thinking phase and output response directly
    if (!prompt.includes('<unused95>')) {
        prompt = '<unused95>' + prompt;
    }
    
    const imagenes = [...imagenesDataUrl.filter(Boolean), ...capturasMicroscopio]
        .filter(img => typeof img === 'string' && /^data:image\/(jpeg|png|gif|webp);base64,/.test(img))
        .slice(0, 4);

    // DEBUG: Log exact payload for desktop vs mobile comparison
    console.log('=== MORPHOS AI REQUEST ===');
    console.log('Images count:', imagenes.length);
    console.log('Prompt length:', prompt.length);
    console.log('Prompt preview:', prompt.substring(0, 200) + '...');
    console.log('==========================');

    try {
        const res = await fetch('api/hf_proxy.php', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ images: imagenes, prompt }),
        });

        const data = await res.json();
        
        // DEBUG: Log raw response
        console.log('=== MORPHOS AI RESPONSE ===');
        console.log('Status:', res.status);
        console.log('Raw text preview:', (data.text ?? 'NO TEXT').substring(0, 300));
        console.log('===========================');
        
        if (!res.ok) {
            salidaEl.textContent = `Error: ${data?.error ?? `HTTP ${res.status}`}`;
        } else {
            salidaEl.textContent = limpiarRespuesta(data.text ?? 'Sin respuesta del modelo.');
        }
    } catch (e) {
        console.error('Network error:', e);
        salidaEl.textContent = `Error de red: ${e.message}`;
    }
}
