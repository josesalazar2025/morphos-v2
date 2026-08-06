// Inyección de valores en el formulario, compartida por el importador de PDF (pdf-parser.ts)
// y el de analizadores (lab-import.ts). La clave de unión es el atributo `name` del input
// (== clave canónica de valores_referencia.json). Fuente única para no duplicar la lógica.

import { revelarPanelDeCampo } from './panel-vacio.js';

export type ValoresInyectables = Record<string, number | string>;

export interface PacienteInyectable {
  especie?: string;
  raza?: string;
  sexo?: string;
  edad?: number | string;
  edadUnidad?: string;
}

interface OpcionesInyeccion {
  resaltar?: boolean; // marca los campos rellenados con un destello transitorio
}

function resaltarCampo(el: HTMLElement): void {
  el.classList.add('campo-importado');
  setTimeout(() => el.classList.remove('campo-importado'), 2500);
}

// Rellena los inputs numéricos y los <select> semicuantitativos (uri-*) por su `name`.
// Dispara `evaluar()` una sola vez si se rellenó algo, igual que el importador de PDF.
export function aplicarValoresAFormulario(
  resultados: ValoresInyectables,
  evaluar: () => void,
  opciones: OpcionesInyeccion = {},
): number {
  let contador = 0;
  for (const [campo, value] of Object.entries(resultados)) {
    const el = document.querySelector(`[name="${campo}"]`) as HTMLInputElement | HTMLSelectElement | null;
    if (!el) continue;
    // Un valor importado a un panel en estado vacío quedaría escondido tras la zona de arrastre.
    revelarPanelDeCampo(el);
    const valorCadena = String(value);
    if (el.tagName === 'SELECT') {
      const select = el as HTMLSelectElement;
      if ([...select.options].some((o) => o.value === valorCadena)) {
        select.value = valorCadena;
        contador++;
        if (opciones.resaltar) resaltarCampo(select);
      }
    } else {
      el.value = valorCadena;
      contador++;
      if (opciones.resaltar) resaltarCampo(el);
    }
  }
  if (contador > 0) evaluar();
  return contador;
}

// Rellena los campos de paciente (pt-*) y sus espejos móviles (mob-pt-*), disparando el
// evento que reactiva el análisis.
export function aplicarPacienteAFormulario(patient: PacienteInyectable): number {
  const MAPA = [
    { id: 'pt-especie', mobId: 'mob-pt-especie', key: 'especie', evt: 'change' },
    { id: 'pt-raza', mobId: 'mob-pt-raza', key: 'raza', evt: 'input' },
    { id: 'pt-edad', mobId: 'mob-pt-edad', key: 'edad', evt: 'input' },
    { id: 'pt-edad-unidad', mobId: 'mob-pt-edad-unidad', key: 'edadUnidad', evt: 'change' },
    { id: 'pt-sexo', mobId: 'mob-pt-sexo', key: 'sexo', evt: 'change' },
  ] as const;
  let contador = 0;
  for (const { id, mobId, key, evt } of MAPA) {
    const val = patient[key];
    if (val === undefined) continue;
    const el = document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null;
    const mob = document.getElementById(mobId) as HTMLInputElement | HTMLSelectElement | null;
    if (!el) continue;
    const valorCadena = String(val);
    if (el.tagName === 'SELECT') {
      const select = el as HTMLSelectElement;
      const opcion = [...select.options].find((o) => o.value === valorCadena || o.text === valorCadena);
      if (!opcion) continue;
      select.value = opcion.value;
      if (mob) mob.value = opcion.value;
    } else {
      el.value = valorCadena;
      if (mob) mob.value = valorCadena;
    }
    el.dispatchEvent(new Event(evt, { bubbles: true }));
    contador++;
  }
  return contador;
}

// Toast ligero reutilizado por ambos importadores.
export function mostrarToast(mensaje: string, error = false): void {
  let el = document.getElementById('pdf-toast') as (HTMLElement & { _t?: ReturnType<typeof setTimeout> }) | null;
  if (!el) {
    el = document.createElement('div');
    el.id = 'pdf-toast';
    document.body.appendChild(el);
  }
  el.textContent = mensaje;
  el.className = 'pdf-toast' + (error ? ' pdf-toast--error' : '');
  el.classList.add('pdf-toast--show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el!.classList.remove('pdf-toast--show'), 3500);
}
