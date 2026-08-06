// Cliente tipado de /api/interpret.
// Reemplaza a js/ia.js: ya no construye el prompt ni limpia la salida con regex —
// eso vive ahora en el backend. Aquí sólo se envía la petición y se renderiza la
// interpretación estructurada (hallazgos, diferenciales con citas, siguientes pruebas
// y el aviso de derivación al veterinario).

import type { Hallazgo, Paciente, Patron } from './tipos.js';

const BACKEND_KEY = 'mx-ia-backend';
const MODELO_LOCAL_KEY = 'mx-ia-modelo-local';

// Modelos locales que el servidor admite. Se pide una vez al arrancar; lista vacía = la
// instancia no tiene Ollama alcanzable y el selector entero se queda oculto.
let modelosLocales: string[] = [];

// Modelo local elegido, o null si se usa la ruta que decide el servidor. Se lee al enviar la
// petición: es lo único que el cliente puede decir sobre qué modelo responde, y aun así el
// servidor lo revalida contra su lista blanca.
function modeloLocalSeleccionado(): string | null {
  const radioLocal = document.getElementById('ia-backend-local') as HTMLInputElement | null;
  if (!radioLocal?.checked) return null;
  const guardado = localStorage.getItem(MODELO_LOCAL_KEY);
  return guardado && modelosLocales.includes(guardado) ? guardado : (modelosLocales[0] ?? null);
}

// Inicializa el panel de ajustes de backend. La ruta ('medgemma' | 'claude') la decide el
// servidor; lo único que el usuario elige aquí es CUÁL de los modelos locales declarados
// responde. No hay campo de URL: la de Ollama vive en la configuración del servidor.
export async function inicializarConfigBackend(): Promise<void> {
  const guardado = localStorage.getItem(BACKEND_KEY);
  if (guardado !== 'claude' && guardado !== 'medgemma') {
    localStorage.setItem(BACKEND_KEY, 'medgemma');
  }

  const contenedor = document.getElementById('ia-backend-config') as HTMLElement | null;
  const radioLocal = document.getElementById('ia-backend-local') as HTMLInputElement | null;
  const radioHF = document.getElementById('ia-backend-hf') as HTMLInputElement | null;
  const camposOllama = document.getElementById('ia-ollama-fields') as HTMLElement | null;
  const selector = document.getElementById('ia-modelo-local') as HTMLSelectElement | null;

  try {
    const res = await fetch('/api/modelos', { credentials: 'same-origin' });
    if (res.ok) modelosLocales = (await res.json()).locales ?? [];
  } catch {
    modelosLocales = [];  // sin lista, el selector no aparece y todo sigue como antes
  }

  if (!modelosLocales.length) return;
  if (contenedor) contenedor.hidden = false;

  if (selector) {
    const previo = localStorage.getItem(MODELO_LOCAL_KEY);
    selector.replaceChildren(
      ...modelosLocales.map((m) => {
        const opcion = document.createElement('option');
        opcion.value = m;
        opcion.textContent = m;
        opcion.selected = m === previo;
        return opcion;
      }),
    );
    selector.addEventListener('change', () => {
      localStorage.setItem(MODELO_LOCAL_KEY, selector.value);
    });
  }

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
  fuera_de_alcance: boolean;
  idioma: string;
}

// Las fuentes las construye el servidor a partir de lo que la recuperación entregó de
// verdad (no las escribe el modelo), así que se pueden mostrar en las tres rutas —incluida
// la del HF Space, que sólo devuelve prosa con marcadores [n].
interface Fuente {
  indice: number;
  libro: string;
  edicion: string;
  capitulo: string;
  pagina: string;
  cita: string;
  citada: boolean;
}

interface RespuestaInterpretacion {
  resultado: InterpretacionClinica;
  modelo: string;
  fuentes_rag: number;
  fuentes: Fuente[];
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
  // El rechazo por alcance lo decide el servidor antes de llamar al modelo, así que se anuncia
  // como tal en vez de dejarlo sólo en la prosa.
  const aviso = r.fuera_de_alcance
    ? '<div class="ia-aviso-alcance">⛔ Caso fuera del alcance de la herramienta (pacientes caninos y felinos)</div>'
    : r.requiere_derivacion
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

  // Se listan todas las fuentes recuperadas y se distingue cuáles sostienen la respuesta:
  // en la ruta de prosa, los marcadores [n] del texto apuntan a esta numeración.
  const listaFuentes = resp.fuentes ?? [];
  const citadas = listaFuentes.filter((f) => f.citada).length;
  const fuentes = listaFuentes.length
    ? `<details class="ia-fuentes"><summary>Literatura consultada (${citadas} de ${listaFuentes.length} citadas)</summary>
        <ol class="ia-fuentes-lista">${listaFuentes
          .map(
            (f) =>
              `<li value="${f.indice}" class="${f.citada ? 'ia-fuente-citada' : 'ia-fuente-no-citada'}">
                <cite>${esc(f.cita)}</cite>${f.capitulo ? ` — ${esc(f.capitulo)}` : ''}
              </li>`,
          )
          .join('')}</ol></details>`
    : '';

  const meta = `<div class="ia-meta">Modelo: ${esc(resp.modelo)} · Fragmentos recuperados: ${resp.fuentes_rag} · Confianza: ${r.confianza}</div>`;

  return `${aviso}
    <p class="ia-interpretacion">${esc(r.interpretacion)}</p>
    ${hallazgos}
    ${diferenciales ? `<h4>Diagnósticos diferenciales</h4>${diferenciales}` : ''}
    ${pruebas}
    ${fuentes}
    ${meta}`;
}

export async function llamarIA(
  obtenerDatosPaciente: () => Paciente,
  getUltimoAnalisis: () => { hallazgos: Hallazgo[]; patrones: Patron[]; medidos?: string[] },
  getImagenes: () => string[],
): Promise<void> {
  const salidaEl = document.getElementById('salida-ia');
  if (!salidaEl) return;

  const backend = (localStorage.getItem(BACKEND_KEY) ?? 'medgemma') === 'claude' ? 'claude' : 'medgemma';
  const paciente = obtenerDatosPaciente();
  const { hallazgos, patrones, medidos } = getUltimoAnalisis();
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
    // El panel COMPLETO, no sólo lo alterado: es lo que le permite al modelo saber que un
    // analito ausente no se ha medido y que uno presente pero sin hallazgo salió en rango.
    analitos_medidos: medidos ?? [],
    signos_clinicos: signos,
    imagenes: getImagenes().slice(0, 4),
    backend,
    modelo_local: modeloLocalSeleccionado(),
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
