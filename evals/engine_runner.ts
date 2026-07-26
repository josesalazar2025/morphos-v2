// Puente al motor determinista (única fuente de verdad: frontend/src/analisis.ts).
// Lee un JSON {valores, paciente} por stdin y emite {hallazgos, patrones} por stdout.
// Se ejecuta con: node --experimental-strip-types engine_runner.ts
// Usado por evals/run_evals.py para generar los hallazgos/patrones en modo --modelo.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { analizarResultados } from '../frontend/src/analisis.ts';
import type { Alteraciones, Paciente, Referencias } from '../frontend/src/tipos.ts';

const aquí = dirname(fileURLToPath(import.meta.url));
const datos = resolve(aquí, '../data');
const referencias = JSON.parse(readFileSync(resolve(datos, 'valores_referencia.json'), 'utf8')) as Referencias;
const alteraciones = JSON.parse(readFileSync(resolve(datos, 'alteraciones.json'), 'utf8')) as Alteraciones;

const entrada = JSON.parse(readFileSync(0, 'utf8')) as {
  valores: Record<string, number>;
  paciente: { especie: string | null; raza?: string; edad_meses?: number | null; sexo?: string };
};

const paciente: Paciente = {
  especie: (entrada.paciente.especie as Paciente['especie']) ?? null,
  raza: entrada.paciente.raza ?? null,
  edadMeses: entrada.paciente.edad_meses ?? null,
  sexo: entrada.paciente.sexo ?? null,
};

const { hallazgos, patrones } = analizarResultados(entrada.valores, paciente, referencias, alteraciones);
process.stdout.write(JSON.stringify({ hallazgos, patrones }));
