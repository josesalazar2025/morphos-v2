// Cliente tipado de /api/interpret.
// Reemplaza a js/ia.js: ya no construye el prompt ni limpia la salida con regex —
// eso vive ahora en el backend. Aquí sólo se envía la petición y se renderiza la
// interpretación estructurada (hallazgos, diferenciales con citas, siguientes pruebas
// y el aviso de derivación al veterinario).

import type { Hallazgo, Paciente, Patron, ValoresFormulario } from './tipos.js';

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

export interface Diferencial {
  nombre: string;
  probabilidad: 'alta' | 'media' | 'baja';
  evidencia: string[];
  citas: string[];
}

export interface InterpretacionClinica {
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
export interface Fuente {
  indice: number;
  libro: string;
  edicion: string;
  capitulo: string;
  pagina: string;
  cita: string;
  citada: boolean;
}

export interface RespuestaInterpretacion {
  resultado: InterpretacionClinica;
  modelo: string;
  fuentes_rag: number;
  fuentes: Fuente[];
}

function leerCookie(nombre: string): string | null {
  const par = document.cookie.split('; ').find((c) => c.startsWith(`${nombre}=`));
  return par ? decodeURIComponent(par.split('=')[1]) : null;
}

// --- Render sin HTML como texto -----------------------------------------------------------
//
// Todo lo que sale de aquí se construye con nodos del DOM y `textContent`, NUNCA concatenando
// cadenas para `innerHTML`. El texto que se pinta lo escribe un LLM alimentado con fragmentos
// del RAG y con los `signos_clinicos` que teclea el usuario: es entrada no confiable, aunque
// venga de nuestro propio backend.
//
// Antes esto era una plantilla con un helper `esc()`. Se eliminó a propósito y no debe volver:
// `esc()` escapaba contexto de TEXTO (dejaba pasar `"` y `'`), pero la plantilla interpolaba
// valores también dentro de ATRIBUTOS —`class="ia-prob-${d.probabilidad}"`,
// `<li value="${f.indice}">`— y ahí ni siquiera se llamaba. Bastaba una comilla en uno de esos
// campos para salirse del atributo y añadir un `onerror`. El tipo TypeScript no protegía: la
// respuesta entra por `data as RespuestaInterpretacion`, un cast sin comprobación.
//
// Construir nodos elimina la clase entera de fallo: `textContent` no interpreta marcado y no
// existe contexto de atributo que romper.

const PROBABILIDADES = new Set(['alta', 'media', 'baja']);

function crear(tag: string, clase?: string, texto?: string): HTMLElement {
  const el = document.createElement(tag);
  if (clase) el.className = clase;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

export function renderizar(resp: RespuestaInterpretacion): DocumentFragment {
  const r = resp.resultado;
  const frag = document.createDocumentFragment();

  // El rechazo por alcance lo decide el servidor antes de llamar al modelo, así que se anuncia
  // como tal en vez de dejarlo sólo en la prosa.
  if (r.fuera_de_alcance) {
    frag.append(
      crear('div', 'ia-aviso-alcance', '⛔ Caso fuera del alcance de la herramienta (pacientes caninos y felinos)'),
    );
  } else if (r.requiere_derivacion) {
    frag.append(crear('div', 'ia-aviso-derivacion', '⚠ Requiere valoración presencial del veterinario'));
  }

  frag.append(crear('p', 'ia-interpretacion', r.interpretacion ?? ''));

  if (r.hallazgos_clave?.length) {
    const ul = crear('ul', 'ia-hallazgos');
    for (const h of r.hallazgos_clave) {
      const base = `${h.analito}: ${h.direccion} · ${h.gravedad}`;
      ul.append(crear('li', undefined, h.comentario ? `${base} — ${h.comentario}` : base));
    }
    frag.append(ul);
  }

  if (r.diferenciales?.length) {
    frag.append(crear('h4', undefined, 'Diagnósticos diferenciales'));
    const ol = crear('ol', 'ia-diferenciales');
    for (const d of r.diferenciales) {
      const li = crear('li');
      li.append(crear('span', 'ia-dif-nombre', d.nombre));
      // Lista blanca: la probabilidad viaja a un NOMBRE DE CLASE, así que un valor arbitrario
      // sería el único hueco que queda para inyectar en un atributo. El esquema del servidor la
      // restringe a estas tres, pero aquí llega tras un cast sin validar.
      const prob = PROBABILIDADES.has(d.probabilidad) ? d.probabilidad : 'baja';
      li.append(crear('span', `ia-dif-prob ia-prob-${prob}`, d.probabilidad));
      if (d.evidencia?.length) li.append(crear('div', 'ia-dif-evidencia', d.evidencia.join('; ')));
      if (d.citas?.length) {
        const divCitas = crear('div', 'ia-dif-citas');
        d.citas.forEach((c, i) => {
          if (i > 0) divCitas.append(' ');
          divCitas.append(crear('cite', undefined, c));
        });
        li.append(divCitas);
      }
      ol.append(li);
    }
    frag.append(ol);
  }

  if (r.siguientes_pruebas?.length) {
    const div = crear('div', 'ia-pruebas');
    div.append(crear('strong', undefined, 'Siguientes pruebas:'), ` ${r.siguientes_pruebas.join(', ')}`);
    frag.append(div);
  }

  // Se listan todas las fuentes recuperadas y se distingue cuáles sostienen la respuesta:
  // en la ruta de prosa, los marcadores [n] del texto apuntan a esta numeración.
  const listaFuentes = resp.fuentes ?? [];
  if (listaFuentes.length) {
    const citadas = listaFuentes.filter((f) => f.citada).length;
    const details = crear('details', 'ia-fuentes');
    details.append(
      crear('summary', undefined, `Literatura consultada (${citadas} de ${listaFuentes.length} citadas)`),
    );
    const ol = crear('ol', 'ia-fuentes-lista') as HTMLOListElement;
    for (const f of listaFuentes) {
      const li = crear('li', f.citada ? 'ia-fuente-citada' : 'ia-fuente-no-citada') as HTMLLIElement;
      // `value` es una propiedad numérica del DOM: asignarla no pasa por el parseo de atributos.
      if (Number.isInteger(f.indice)) li.value = f.indice;
      li.append(crear('cite', undefined, f.cita));
      if (f.capitulo) li.append(` — ${f.capitulo}`);
      ol.append(li);
    }
    details.append(ol);
    frag.append(details);
  }

  frag.append(
    crear(
      'div',
      'ia-meta',
      `Modelo: ${resp.modelo} · Fragmentos recuperados: ${resp.fuentes_rag} · Confianza: ${r.confianza}`,
    ),
  );

  return frag;
}

export async function llamarIA(
  obtenerDatosPaciente: () => Paciente,
  getUltimoAnalisis: () => { hallazgos: Hallazgo[]; patrones: Patron[]; valores?: ValoresFormulario },
  getImagenes: () => string[],
): Promise<void> {
  const salidaEl = document.getElementById('salida-ia');
  if (!salidaEl) return;

  const backend = (localStorage.getItem(BACKEND_KEY) ?? 'medgemma') === 'claude' ? 'claude' : 'medgemma';
  const paciente = obtenerDatosPaciente();
  const { hallazgos, patrones, valores } = getUltimoAnalisis();
  // El formulario entrega texto; el backend espera números. Se descarta lo que no lo sea en vez
  // de mandarlo: un campo vacío no es un valor medido, y colarlo como 0 sería inventar un dato.
  const numericos: Record<string, number> = {};
  for (const [clave, crudo] of Object.entries(valores ?? {})) {
    const n = typeof crudo === 'number' ? crudo : parseFloat(String(crudo ?? ''));
    if (Number.isFinite(n)) numericos[clave] = n;
  }
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
    // Valores CRUDOS: es lo que permite al backend recalcular hallazgos y gravedad por su
    // cuenta en vez de fiarse de los de aquí (ARCHITECTURE_REVIEW §1.1). `analitos_medidos` se
    // sigue enviando por compatibilidad, pero el servidor lo deriva de `valores`.
    valores: numericos,
    analitos_medidos: Object.keys(numericos),
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
      // `replaceChildren` con un fragmento, no `innerHTML`: ver la nota sobre el render.
      salidaEl.replaceChildren(renderizar(data as RespuestaInterpretacion));
    }
  } catch (e) {
    salidaEl.textContent = `Error de red: ${(e as Error).message}`;
  } finally {
    salidaEl.classList.remove('cargando');
  }
}
