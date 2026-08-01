// Orquestación de la app. Puerto TS de js/main.js, adaptado a la nueva capa de IA
// (llamarIA envía hallazgos/patrones + imágenes al backend /api/interpret).

import './tooltip.js';
import { analizarResultados } from './analisis.js';
import { colapsarPatrones, inicializarSincMob, imagenesDataUrl, capturasMicroscopio } from './ui.js';
import { llamarIA, inicializarConfigBackend } from './ia.js';
import { inicializarParserPdf } from './pdf-parser.js';
import { inicializarImportLab } from './lab-import.js';
import { verificarAuth, abrirModalAuth } from './auth.js';
import { abrirModalPapers, inicializarModalPapers } from './papers.js';
import { elId } from './dom.js';
import { manejadorAsync, sinEsperar } from './async.js';
import type { Alteraciones, Gravedad, Hallazgo, Paciente, Referencias, ResultadoAnalisis } from './tipos.js';

// Tema oscuro/claro

const temaGuardado = localStorage.getItem('mx-theme');
const temaPreferido = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
document.documentElement.dataset.theme = temaGuardado || temaPreferido;

const btnTema = document.getElementById('btn-tema');
if (btnTema) {
  btnTema.addEventListener('click', () => {
    const siguienteTema = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = siguienteTema;
    localStorage.setItem('mx-theme', siguienteTema);
  });
}

// Data

let referencias: Referencias = {};
let alteraciones: Alteraciones = {};
let ultimoAnalisis: ResultadoAnalisis = { hallazgos: [], patrones: [] };

const cargarReferencias = async (): Promise<void> => {
  try {
    const response = await fetch('data/valores_referencia.json');
    if (!response.ok) throw new Error(`Error HTTP: ${response.status}`);
    referencias = await response.json();
  } catch (error) {
    console.error('Error cargando valores de referencia:', error);
  }
};

const cargarAlteraciones = async (): Promise<void> => {
  try {
    const response = await fetch('data/alteraciones.json');
    if (!response.ok) throw new Error(`Error HTTP: ${response.status}`);
    alteraciones = await response.json();
  } catch (error) {
    console.error('Error cargando alteraciones:', error);
  }
};

// Precargas de arranque: nada que esperar aquí, pero un fallo no puede quedar en silencio
// (sin rangos de referencia el motor no puede clasificar nada).
sinEsperar('Carga de rangos de referencia', cargarReferencias());
sinEsperar('Carga de alteraciones', cargarAlteraciones());

// Colección de datos de formulario

const obtenerDatosPaciente = (): Paciente => {
  const especieCruda = (document.getElementById('pt-especie') as HTMLSelectElement).value;
  const valorEdad = (document.getElementById('pt-edad') as HTMLInputElement).value;
  const edadUnidad = (document.getElementById('pt-edad-unidad') as HTMLSelectElement).value;
  // Normaliza la edad siempre a meses para que analisis.ts aplique ajustes por edad
  const edadMeses = valorEdad === '' ? null
    : edadUnidad === 'meses' ? parseFloat(valorEdad)
      : parseFloat(valorEdad) * 12;
  return {
    especie: especieCruda === 'Canino' ? 'canino' : especieCruda === 'Felino' ? 'felino' : null,
    raza: (document.getElementById('pt-raza') as HTMLInputElement).value,
    edadMeses,
    sexo: (document.getElementById('pt-sexo') as HTMLSelectElement).value,
  };
};

const obtenerValoresFormulario = (): Record<string, number> => {
  const valores: Record<string, number> = {};
  document.querySelectorAll<HTMLInputElement>('input[type="number"]').forEach((input) => {
    if (input.name && input.value !== '') valores[input.name] = parseFloat(input.value);
  });
  return valores;
};

// Renderizado

const ETIQUETA_GRAVEDAD: Record<Gravedad, string> = { leve: 'Leve', moderado: 'Moderado', grave: 'Grave' };

document.querySelectorAll<HTMLInputElement>('.fila-campo input[type="number"]').forEach((input) => {
  const span = document.createElement('span');
  span.className = 'estado-campo';
  input.before(span);
});

const actualizarClasesInputs = (hallazgos: Hallazgo[]): void => {
  document.querySelectorAll<HTMLInputElement>('input[type="number"]').forEach((input) => {
    input.classList.remove('alto', 'bajo');
    const span = input.previousElementSibling;
    if (span?.classList.contains('estado-campo')) {
      span.textContent = '';
      span.className = 'estado-campo';
    }
  });
  hallazgos.forEach((h) => {
    const input = document.querySelector<HTMLInputElement>(`input[name="${h.clave}"]`);
    if (!input) return;
    input.classList.add(h.direccion);
    const span = input.previousElementSibling;
    if (span?.classList.contains('estado-campo')) {
      span.textContent = `${h.direccion === 'alto' ? 'Alto' : 'Bajo'} · ${ETIQUETA_GRAVEDAD[h.gravedad]}`;
      span.className = `estado-campo estado-campo--${h.direccion}`;
    }
  });
};

const renderizarPatrones = (patrones: ResultadoAnalisis['patrones']): void => {
  const contenedor = document.getElementById('patrones-lista');
  if (!contenedor) return;

  contenedor.innerHTML = patrones.length === 0
    ? '<p class="sin-hallazgos">Sin patrones detectados.</p>'
    : patrones.map((p) => `
      <div class="elemento-patron gravedad-${p.gravedad}">
        <div class="titulo-patron">${p.nombre}</div>
        <div class="cuerpo-patron">${p.descripcion}</div>
      </div>`).join('');
};

// Evaluación

const evaluar = (): void => {
  const paciente = obtenerDatosPaciente();

  // Si no hay especie o aun no cargaron las referencias, limpia la UI para evitar falsos positivos
  if (!paciente.especie || !referencias[paciente.especie]) {
    actualizarClasesInputs([]);
    renderizarPatrones([]);
    return;
  }

  const valores = obtenerValoresFormulario();
  const { hallazgos, patrones } = analizarResultados(valores, paciente, referencias, alteraciones);
  ultimoAnalisis = { hallazgos, patrones };

  actualizarClasesInputs(hallazgos);
  renderizarPatrones(patrones);
};

// Eventos

document.addEventListener('input', (e) => {
  const target = e.target as HTMLInputElement;
  if (target.type !== 'number') return;
  // Impide valores por debajo del mínimo del campo; permite negativos cuando min lo indica
  const minPermitido = target.min !== '' ? parseFloat(target.min) : 0;
  if (parseFloat(target.value) < minPermitido) target.value = String(minPermitido);
  if (target.value.replace('.', '').length > 4) target.value = target.value.slice(0, 4);
  target.classList.toggle('max-chars', target.value.replace('.', '').length >= 4);
  evaluar();
});

elId<HTMLSelectElement>('pt-especie').addEventListener('change', evaluar);
elId<HTMLInputElement>('pt-raza').addEventListener('input', evaluar);
elId<HTMLInputElement>('pt-edad').addEventListener('input', evaluar);
elId<HTMLSelectElement>('pt-edad-unidad').addEventListener('change', evaluar);
elId<HTMLSelectElement>('pt-sexo').addEventListener('change', evaluar);

inicializarSincMob(evaluar);
void inicializarConfigBackend();  // pide la lista de modelos al servidor; no bloquea el arranque
inicializarParserPdf(evaluar);
inicializarImportLab(evaluar);
inicializarModalPapers();

document.addEventListener('click', (e) => {
  const btn = (e.target as Element).closest<HTMLElement>('.btn-limpiar-panel');
  if (!btn) return;
  const panel = document.getElementById(`panel-${btn.dataset.panel}`);
  if (!panel) return;
  // Recorre todos los campos editables del panel y los resetea, incluyendo indicadores de estado
  panel.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input[type="number"], input[type="text"], input[type="url"], select').forEach((el) => {
    if (el.tagName === 'SELECT') {
      (el as HTMLSelectElement).selectedIndex = 0;
    } else {
      el.value = '';
      el.classList.remove('alto', 'bajo', 'max-chars');
      const span = el.previousElementSibling;
      if (span?.classList.contains('estado-campo')) {
        span.textContent = '';
        span.className = 'estado-campo';
      }
    }
  });
  evaluar();
});

const imagenesActuales = (): string[] =>
  [...imagenesDataUrl.filter((x): x is string => Boolean(x)), ...capturasMicroscopio];

const dispararIA = (): void => {
  colapsarPatrones(true);
  // Se encola desde un callback síncrono (abrirModalAuth), así que no se puede await aquí.
  sinEsperar('Análisis IA', llamarIA(obtenerDatosPaciente, () => ultimoAnalisis, imagenesActuales));
};

const botonAnalizar = document.querySelector<HTMLElement>('.boton-analizar');
botonAnalizar?.addEventListener('click', manejadorAsync('Análisis IA', async () => {
  // Si el usuario no esta logueado, abre el modal de auth y encola la llamada a IA como callback
  const autenticado = await verificarAuth();
  if (!autenticado) {
    abrirModalAuth(dispararIA);
    return;
  }
  dispararIA();
}));

const botonPapers = document.querySelector<HTMLElement>('.boton-papers');
botonPapers?.addEventListener('click', () => {
  sinEsperar('Literatura', abrirModalPapers(ultimoAnalisis.patrones));
});

// obtenerValoresFormulario se conserva para depuración/consumidores futuros del formulario.
void obtenerValoresFormulario;
