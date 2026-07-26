// Importación de resultados desde un analizador de laboratorio. El veterinario introduce
// (o escanea) el ID de muestra; se consulta el backend, que ya devuelve los analitos con las
// claves canónicas mapeadas, y se inyectan en el formulario reutilizando form-inject.ts.
//
// El puente local (bridge/) es quien habla con las máquinas; el navegador sólo consulta
// /api/lab/resultados del mismo origen con la cookie de sesión (sin CSRF en GET).

import {
  aplicarValoresAFormulario,
  aplicarPacienteAFormulario,
  mostrarToast,
  type ValoresInyectables,
  type PacienteInyectable,
} from './form-inject.js';
import { manejadorAsync } from './async.js';

interface ValorAnalitoResp {
  clave: string;
  valor: number | string;
  es_semicuantitativo?: boolean;
}

interface PacientePistasResp {
  nombre_mascota?: string | null;
  especie_texto?: string | null;
  raza?: string | null;
  sexo?: string | null;
  edad_texto?: string | null;
}

interface ResultadoMapeadoResp {
  muestra_id: string;
  instrumento_id: string;
  momento: string;
  analitos: Record<string, ValorAnalitoResp>;
  paciente?: PacientePistasResp | null;
  no_mapeados: string[];
}

interface ResumenPendiente {
  muestra_id: string;
  instrumento_id: string;
  momento: string;
  analitos: number;
  no_mapeados: number;
}

const INTERVALO_MS = 3000;
const MAX_INTENTOS = 30; // ~90 s de espera
const TEXTO_IMPORTAR = 'Importar del analizador';
const TEXTO_CANCELAR = 'Cancelar búsqueda';

// Normaliza las pistas de paciente (texto libre del equipo) al formato del formulario.
function pistasAPaciente(p?: PacientePistasResp | null): PacienteInyectable {
  const out: PacienteInyectable = {};
  if (!p) return out;
  const esp = (p.especie_texto || '').toLowerCase();
  if (/can|perro|dog/.test(esp)) out.especie = 'Canino';
  else if (/fel|gat|cat/.test(esp)) out.especie = 'Felino';
  if (p.raza) out.raza = p.raza;
  const sx = (p.sexo || '').toLowerCase();
  if (/macho|male/.test(sx)) out.sexo = 'Macho';
  else if (/hembra|female/.test(sx)) out.sexo = 'Hembra';
  const edad = (p.edad_texto || '').match(/(\d+(?:[.,]\d+)?)\s*(mes|month|a|y)/i);
  if (edad) {
    out.edad = parseFloat(edad[1].replace(',', '.'));
    out.edadUnidad = /^m/i.test(edad[2]) ? 'meses' : 'anyos';
  }
  return out;
}

// Aplica un resultado ya mapeado al formulario y avisa (incluyendo códigos sin reconocer).
function aplicarResultado(data: ResultadoMapeadoResp, evaluar: () => void): void {
  const resultados: ValoresInyectables = {};
  for (const [clave, va] of Object.entries(data.analitos)) resultados[clave] = va.valor;
  const n = aplicarValoresAFormulario(resultados, evaluar, { resaltar: true });
  aplicarPacienteAFormulario(pistasAPaciente(data.paciente));

  let extra = '';
  if (data.no_mapeados.length) {
    const muestra = data.no_mapeados.slice(0, 3).join(', ');
    const mas = data.no_mapeados.length > 3 ? '…' : '';
    extra = ` (${data.no_mapeados.length} sin reconocer: ${muestra}${mas})`;
  }
  mostrarToast(
    n > 0
      ? `${n} valor${n !== 1 ? 'es' : ''} importado${n !== 1 ? 's' : ''} del analizador${extra}. Verifica antes de interpretar.`
      : 'El resultado no contenía valores reconocibles.',
    n === 0,
  );
}

export function inicializarImportLab(evaluar: () => void): void {
  const btn = document.getElementById('btn-importar-lab');
  const input = document.getElementById('lab-muestra-id') as HTMLInputElement | null;
  if (!btn || !input) return;

  let buscando = false;
  let cancelar = false;

  const detener = (): void => {
    cancelar = true;
    buscando = false;
    btn.textContent = TEXTO_IMPORTAR;
    btn.classList.remove('buscando');
  };

  // Descarga un resultado concreto por ID y lo aplica. Devuelve el estado HTTP relevante.
  const cargarYAplicar = async (muestra: string): Promise<'ok' | '404' | '401' | 'error'> => {
    try {
      const resp = await fetch(`/api/lab/resultados?muestra=${encodeURIComponent(muestra)}`, {
        credentials: 'same-origin',
      });
      if (resp.status === 200) {
        aplicarResultado((await resp.json()) as ResultadoMapeadoResp, evaluar);
        return 'ok';
      }
      if (resp.status === 404) return '404';
      if (resp.status === 401) return '401';
      return 'error';
    } catch {
      return 'error';
    }
  };

  const buscar = async (): Promise<void> => {
    if (buscando) {
      detener();
      return;
    }
    const muestra = input.value.trim();
    if (!muestra) {
      mostrarToast('Introduce el ID de muestra.', true);
      return;
    }
    buscando = true;
    cancelar = false;
    btn.textContent = TEXTO_CANCELAR;
    btn.classList.add('buscando');

    for (let intento = 0; intento < MAX_INTENTOS && !cancelar; intento++) {
      const estado = await cargarYAplicar(muestra);
      if (estado === 'ok') {
        detener();
        return;
      }
      if (estado === '401') {
        detener();
        mostrarToast('Inicia sesión para importar resultados.', true);
        return;
      }
      if (estado === 'error') {
        detener();
        mostrarToast('Error al consultar el analizador.', true);
        return;
      }
      // '404' → el resultado aún no ha llegado; espera y reintenta.
      await new Promise((r) => setTimeout(r, INTERVALO_MS));
    }

    if (!cancelar) {
      detener();
      mostrarToast('No llegó ningún resultado para esa muestra (tiempo agotado).', true);
    }
  };

  btn.addEventListener('click', manejadorAsync('Búsqueda de muestra', buscar));
  // Un lector de código de barras teclea el ID y pulsa Enter: eso dispara la búsqueda.
  input.addEventListener('keydown', manejadorAsync('Búsqueda de muestra', async (e: Event) => {
    if ((e as KeyboardEvent).key === 'Enter') {
      e.preventDefault();
      await buscar();
    }
  }));

  inicializarCola(cargarYAplicar, detener);
}

// Cola de resultados recibidos: lista para elegir sin teclear el ID de muestra.
function inicializarCola(
  cargarYAplicar: (muestra: string) => Promise<'ok' | '404' | '401' | 'error'>,
  detenerBusqueda: () => void,
): void {
  const btn = document.getElementById('btn-pendientes-lab');
  const lista = document.getElementById('lab-pendientes');
  if (!btn || !lista) return;

  const formatearHora = (iso: string): string => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
  };

  const render = (pendientes: ResumenPendiente[]): void => {
    lista.innerHTML = '';
    if (pendientes.length === 0) {
      const vacio = document.createElement('li');
      vacio.className = 'lab-pendientes-vacio';
      vacio.textContent = 'No hay resultados recibidos.';
      lista.appendChild(vacio);
      lista.hidden = false;
      return;
    }
    for (const p of pendientes) {
      const li = document.createElement('li');
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'lab-pendiente-item';
      const noMap = p.no_mapeados ? ` · ${p.no_mapeados} sin reconocer` : '';
      item.textContent = `${p.muestra_id} · ${p.instrumento_id} · ${formatearHora(p.momento)} · ${p.analitos} valores${noMap}`;
      item.addEventListener('click', manejadorAsync('Importar resultado', async () => {
        detenerBusqueda();
        const estado = await cargarYAplicar(p.muestra_id);
        if (estado === '401') mostrarToast('Inicia sesión para importar resultados.', true);
        else if (estado !== 'ok') mostrarToast('No se pudo cargar ese resultado.', true);
        else lista.hidden = true;
      }));
      li.appendChild(item);
      lista.appendChild(li);
    }
    lista.hidden = false;
  };

  btn.addEventListener('click', manejadorAsync('Resultados pendientes', async () => {
    if (!lista.hidden) {
      lista.hidden = true;
      return;
    }
    try {
      const resp = await fetch('/api/lab/pendientes', { credentials: 'same-origin' });
      if (resp.status === 401) {
        mostrarToast('Inicia sesión para ver los resultados recibidos.', true);
        return;
      }
      if (!resp.ok) {
        mostrarToast('Error al consultar los resultados recibidos.', true);
        return;
      }
      render((await resp.json()) as ResumenPendiente[]);
    } catch {
      mostrarToast('Sin conexión con el servidor.', true);
    }
  }));
}
