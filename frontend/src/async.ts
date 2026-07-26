// Manejo uniforme de errores en trabajo asíncrono.
//
// El port desde JS heredó dos idioms que tragaban fallos en silencio: handlers `async` pasados
// directamente a `addEventListener` (nadie consume la promesa, así que un rechazo sólo aparece
// como "unhandled rejection" en consola) y llamadas fire-and-forget sin `.catch`. En una
// herramienta de diagnóstico eso significa que un fallo de red al guardar o al analizar no le
// llega al veterinario. Estos dos helpers hacen que todo rechazo acabe en el toast de error.

import { mostrarToast } from './form-inject.js';

function reportarFallo(contexto: string, error: unknown): void {
  const detalle = error instanceof Error ? error.message : String(error);
  // console.error (no log) para no filtrar datos de paciente y respetar la regla no-console.
  console.error(`[${contexto}]`, error);
  mostrarToast(`${contexto}: ${detalle}`, true);
}

/**
 * Envuelve un handler asíncrono para usarlo donde se espera un handler síncrono
 * (`addEventListener`, `onclick`). Consume la promesa y reporta el rechazo.
 */
export function manejadorAsync<E extends Event>(
  contexto: string,
  handler: (evento: E) => Promise<void>,
): (evento: E) => void {
  return (evento: E): void => {
    handler(evento).catch((error: unknown) => reportarFallo(contexto, error));
  };
}

/**
 * Lanza trabajo asíncrono deliberadamente sin esperarlo, pero con el rechazo reportado.
 * Usar sólo cuando no hay nada que esperar (arranque, precargas); si el resultado importa,
 * hacer `await`.
 */
export function sinEsperar(contexto: string, promesa: Promise<unknown>): void {
  promesa.catch((error: unknown) => reportarFallo(contexto, error));
}
