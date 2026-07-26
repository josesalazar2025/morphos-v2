// Cliente tipado de /api/interpret.
// Reemplaza a js/ia.js: ya no construye el prompt ni limpia la salida con regex —
// eso vive ahora en el backend. Aquí sólo se envía la petición y se renderiza la
// interpretación estructurada (hallazgos, diferenciales con citas, siguientes pruebas
// y el aviso de derivación al veterinario).

import type { Hallazgo, Paciente, Patron } from './tipos.js';

const BACKEND_KEY = 'mx-ia-backend';

// Inicializa el panel de ajustes de backend. En el nuevo diseño el servidor decide la
// ruta self-hosted concreta (Ollama vs Space) por configuración, así que las opciones
// "local"/"hf" del formulario se colapsan en 'medgemma'; 'claude' queda como ruta híbrida.
export function inicializarConfigBackend(): void {
  const guardado = localStorage.getItem(BACKEND_KEY);
  if (guardado !== 'claude' && guardado !== 'medgemma') {
    localStorage.setItem(BACKEND_KEY, 'medgemma');
  }

  const radioLocal = document.getElementById('ia-backend-local') as HTMLInputElement | null;
  const radioHF = document.getElementById('ia-backend-hf') as HTMLInputElement | null;
  const camposOllama = document.getElementById('ia-ollama-fields') as HTMLElement | null;

  const aplicar = () => {
    if (camposOllama) camposOllama.hidden = !(radioLocal?.checked);
  };
  aplicar();
  [radioLocal, radioHF].forEach((r) => r?.addEventListener('change', aplicar));
}

interface Diferencial {
  nombre: string;
  probabilidad: 'alta' | 'media' | 'baja';
  evidencia: string[];
  citas: string[];
}

interface InterpretacionClinica {
  interpretacion: string;
  hallazgos_clave: Array<{ analito: string; direccion: string; gravedad: string; comentario: string }>;
  diferenciales: Diferencial[];
  siguientes_pruebas: string[];
  confianza: 'alta' | 'media' | 'baja';
  requiere_derivacion: boolean;
  idioma: string;
}

interface RespuestaInterpretacion {
  resultado: InterpretacionClinica;
  modelo: string;
  fuentes_rag: number;
}

function leerCookie(nombre: string): string | null {
  const par = document.cookie.split('; ').find((c) => c.startsWith(`${nombre}=`));
  return par ? decodeURIComponent(par.split('=')[1]) : null;
}

// Escapado mínimo: los datos vienen del modelo, se insertan como texto.
function esc(texto: string): string {
  const div = document.createElement('div');
  div.textContent = texto;
  return div.innerHTML;
}

function renderizar(resp: RespuestaInterpretacion): string {
  const r = resp.resultado;
  const aviso = r.requiere_derivacion
    ? '<div class="ia-aviso-derivacion">⚠ Requiere valoración presencial del veterinario</div>'
    : '';

  const hallazgos = r.hallazgos_clave.length
    ? `<ul class="ia-hallazgos">${r.hallazgos_clave
        .map((h) => `<li>${esc(h.analito)}: ${esc(h.direccion)} · ${esc(h.gravedad)}${h.comentario ? ` — ${esc(h.comentario)}` : ''}</li>`)
        .join('')}</ul>`
    : '';

  const diferenciales = r.diferenciales.length
    ? `<ol class="ia-diferenciales">${r.diferenciales
        .map(
          (d) => `<li>
            <span class="ia-dif-nombre">${esc(d.nombre)}</span>
            <span class="ia-dif-prob ia-prob-${d.probabilidad}">${d.probabilidad}</span>
            ${d.evidencia.length ? `<div class="ia-dif-evidencia">${esc(d.evidencia.join('; '))}</div>` : ''}
            ${d.citas.length ? `<div class="ia-dif-citas">${d.citas.map((c) => `<cite>${esc(c)}</cite>`).join(' ')}</div>` : ''}
          </li>`,
        )
        .join('')}</ol>`
    : '';

  const pruebas = r.siguientes_pruebas.length
    ? `<div class="ia-pruebas"><strong>Siguientes pruebas:</strong> ${esc(r.siguientes_pruebas.join(', '))}</div>`
    : '';

  const meta = `<div class="ia-meta">Modelo: ${esc(resp.modelo)} · Fuentes citadas: ${resp.fuentes_rag} · Confianza: ${r.confianza}</div>`;

  return `${aviso}
    <p class="ia-interpretacion">${esc(r.interpretacion)}</p>
    ${hallazgos}
    ${diferenciales ? `<h4>Diagnósticos diferenciales</h4>${diferenciales}` : ''}
    ${pruebas}
    ${meta}`;
}

export async function llamarIA(
  obtenerDatosPaciente: () => Paciente,
  getUltimoAnalisis: () => { hallazgos: Hallazgo[]; patrones: Patron[] },
  getImagenes: () => string[],
): Promise<void> {
  const salidaEl = document.getElementById('salida-ia');
  if (!salidaEl) return;

  const backend = (localStorage.getItem(BACKEND_KEY) ?? 'medgemma') === 'claude' ? 'claude' : 'medgemma';
  const paciente = obtenerDatosPaciente();
  const { hallazgos, patrones } = getUltimoAnalisis();
  const signos = (document.getElementById('signos-clinicos') as HTMLTextAreaElement | null)?.value.trim() ?? '';

  salidaEl.textContent = 'Consultando al modelo de I.A…';
  salidaEl.classList.add('cargando');

  const cuerpo = {
    paciente: {
      especie: paciente.especie,
      raza: paciente.raza,
      edad_meses: paciente.edadMeses,
      sexo: paciente.sexo,
    },
    hallazgos,
    patrones,
    signos_clinicos: signos,
    imagenes: getImagenes().slice(0, 4),
    backend,
  };

  try {
    const res = await fetch('/api/interpret', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': leerCookie('morphos_csrf') ?? '',
      },
      body: JSON.stringify(cuerpo),
    });

    const data = await res.json();
    if (!res.ok) {
      salidaEl.textContent = data?.error ?? data?.detail ?? `Error HTTP ${res.status}`;
    } else {
      salidaEl.innerHTML = renderizar(data as RespuestaInterpretacion);
    }
  } catch (e) {
    salidaEl.textContent = `Error de red: ${(e as Error).message}`;
  } finally {
    salidaEl.classList.remove('cargando');
  }
}
