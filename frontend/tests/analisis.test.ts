// Suite de regresión del motor clínico. Fija el comportamiento actual de analizarResultados
// para que la migración (y cualquier cambio futuro) no altere la lógica validada por el veterinario.
// Carga los datos reales de data/*.json como única fuente de verdad.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { analizarResultados, _internos } from '../src/analisis.js';
import type { Alteraciones, Paciente, Referencias } from '../src/tipos.js';

const aquí = dirname(fileURLToPath(import.meta.url));
const raízDatos = resolve(aquí, '../../data');

const referencias = JSON.parse(
  readFileSync(resolve(raízDatos, 'valores_referencia.json'), 'utf8'),
) as Referencias;
const alteraciones = JSON.parse(
  readFileSync(resolve(raízDatos, 'alteraciones.json'), 'utf8'),
) as Alteraciones;

const paciente = (over: Partial<Paciente> = {}): Paciente => ({
  especie: 'canino',
  raza: null,
  edadMeses: null,
  sexo: null,
  ...over,
});

const nombresPatrones = (valores: Record<string, number>, p = paciente()): string[] =>
  analizarResultados(valores, p, referencias, alteraciones).patrones.map((x) => x.nombre);

describe('datos de referencia', () => {
  it('cubre ambas especies', () => {
    expect(referencias.canino).toBeDefined();
    expect(referencias.felino).toBeDefined();
  });

  it('canino define 90 analitos', () => {
    expect(Object.keys(referencias.canino).length).toBe(90);
  });
});

describe('guardas de entrada', () => {
  it('sin especie devuelve vacío', () => {
    const r = analizarResultados({ wbc: 30 }, paciente({ especie: null }), referencias, alteraciones);
    expect(r).toEqual({ hallazgos: [], patrones: [] });
  });

  it('ignora valores vacíos, null y no numéricos', () => {
    const r = analizarResultados(
      { wbc: '', hct: null, rbc: 'abc' as unknown as number },
      paciente(),
      referencias,
      alteraciones,
    );
    expect(r.hallazgos).toHaveLength(0);
  });

  it('un valor dentro de rango no genera hallazgos', () => {
    // WBC canino ref 6-17 → 10 está dentro
    const r = analizarResultados({ wbc: 10 }, paciente(), referencias, alteraciones);
    expect(r.hallazgos).toHaveLength(0);
    expect(r.patrones).toHaveLength(0);
  });
});

describe('clasificación de gravedad', () => {
  const ref = { inferior: 6, superior: 17, unidad: 'x10³/μL', nombre: 'WBC' };

  it('desviación ≤ 0.5 anchos → leve', () => {
    // ancho 11; 17 + 5 = 22 → 5/11 ≈ 0.45
    expect(_internos.clasificarGravedad(22, ref)).toBe('leve');
  });

  it('desviación ≤ 1.5 anchos → moderado', () => {
    // 17 + 11 = 28 → 11/11 = 1.0
    expect(_internos.clasificarGravedad(28, ref)).toBe('moderado');
  });

  it('desviación > 1.5 anchos → grave', () => {
    // 17 + 22 = 39 → 22/11 = 2.0
    expect(_internos.clasificarGravedad(39, ref)).toBe('grave');
  });

  it('aplica igual por debajo del límite inferior', () => {
    // 6 - 6 = 0 → 6/11 ≈ 0.55 → moderado
    expect(_internos.clasificarGravedad(0, ref)).toBe('moderado');
  });
});

describe('ajustes por edad', () => {
  it('cachorro canino eleva el techo de FAL (x3)', () => {
    // FAL canino base: superior típico ~150; con cachorro x3 no se marca a valores moderados
    const base = referencias.canino.fal.superior;
    const adulto = analizarResultados({ fal: base * 2 }, paciente({ edadMeses: 6 }), referencias, alteraciones);
    // A los 6 meses el techo es x3, así que base*2 queda dentro de rango → sin patrón colestásico
    expect(adulto.patrones.map((p) => p.nombre)).not.toContain(alteraciones.patron_colestasico.nombre);
  });

  it('geriátrico canino eleva el techo de creatinina', () => {
    const sup = referencias.canino.creat.superior;
    // Valor justo por encima del techo adulto pero dentro del geriátrico (x1.25)
    const valor = sup * 1.2;
    const adulto = analizarResultados({ creat: valor }, paciente({ edadMeses: 60 }), referencias, alteraciones);
    const geriatrico = analizarResultados({ creat: valor }, paciente({ edadMeses: 130 }), referencias, alteraciones);
    expect(adulto.hallazgos.some((h) => h.clave === 'creat')).toBe(true);
    expect(geriatrico.hallazgos.some((h) => h.clave === 'creat')).toBe(false);
  });
});

describe('ajustes por raza', () => {
  it('el galgo tolera hematocrito más alto sin marcar eritrocitosis', () => {
    const sup = referencias.canino.hct.superior;
    const valor = sup * 1.1; // dentro del +12% del galgo, fuera para un mestizo
    const mestizo = nombresPatrones({ hct: valor });
    const galgo = nombresPatrones({ hct: valor }, paciente({ raza: 'Galgo Español' }));
    expect(mestizo).toContain(alteraciones.eritrocitosis.nombre);
    expect(galgo).not.toContain(alteraciones.eritrocitosis.nombre);
  });

  it('el galgo tiene menor umbral de trombocitopenia (plaquetas normales más bajas)', () => {
    const inf = referencias.canino.plt.inferior;
    const valor = inf * 0.8; // bajo para mestizo; el galgo baja el piso a x0.75
    const mestizo = nombresPatrones({ plt: valor });
    const galgo = nombresPatrones({ plt: valor }, paciente({ raza: 'greyhound' }));
    expect(mestizo).toContain(alteraciones.trombocitopenia.nombre);
    expect(galgo).not.toContain(alteraciones.trombocitopenia.nombre);
  });
});

describe('ajustes por sexo', () => {
  it('el macho felino tolera mayor creatinina', () => {
    const sup = referencias.felino.creat.superior;
    const valor = sup * 1.1;
    const hembra = analizarResultados({ creat: valor }, paciente({ especie: 'felino', sexo: 'Hembra' }), referencias, alteraciones);
    const macho = analizarResultados({ creat: valor }, paciente({ especie: 'felino', sexo: 'Macho' }), referencias, alteraciones);
    expect(hembra.hallazgos.some((h) => h.clave === 'creat')).toBe(true);
    expect(macho.hallazgos.some((h) => h.clave === 'creat')).toBe(false);
  });
});

describe('patrones — serie roja', () => {
  it('anemia microcítica cuando HCT y VCM bajos', () => {
    const patrones = analizarResultados(
      { hct: 25, vcm: 55 },
      paciente(),
      referencias,
      alteraciones,
    ).patrones;
    const anemia = patrones.find((p) => p.nombre.startsWith('Anemia'));
    expect(anemia?.nombre).toBe('Anemia microcítica');
    expect(anemia?.descripcion).toContain(alteraciones.anemia.prefijo);
  });

  it('anemia macrocítica cuando HCT bajo y VCM alto', () => {
    expect(nombresPatrones({ hct: 25, vcm: 85 })).toContain('Anemia macrocítica');
  });

  it('eritrocitosis cuando HCT alto', () => {
    expect(nombresPatrones({ hct: 70 })).toContain(alteraciones.eritrocitosis.nombre);
  });
});

describe('patrones — serie blanca', () => {
  it('leucocitosis neutrofílica cuando WBC y neutrófilos altos', () => {
    expect(nombresPatrones({ wbc: 30, neutro: 90 })).toContain(alteraciones.leucocitosis_neutrofilica.nombre);
  });

  it('leucocitosis genérica cuando sólo WBC alto', () => {
    expect(nombresPatrones({ wbc: 30 })).toContain(alteraciones.leucocitosis.nombre);
  });

  it('leucopenia cuando WBC bajo', () => {
    expect(nombresPatrones({ wbc: 2 })).toContain(alteraciones.leucopenia.nombre);
  });
});

describe('patrones — riñón e hígado', () => {
  it('azotemia cuando BUN y creatinina altos', () => {
    expect(nombresPatrones({ bun: 80, creat: 5 })).toContain(alteraciones.azotemia.nombre);
  });

  it('daño hepatocelular cuando ALT y AST altos', () => {
    expect(nombresPatrones({ alt: 300, ast: 300 })).toContain(alteraciones.dano_hepatocelular.nombre);
  });

  it('ALT aislada cuando sólo ALT alta', () => {
    expect(nombresPatrones({ alt: 300 })).toContain(alteraciones.alt_aislada.nombre);
  });
});

describe('patrones — electrolitos y ácido-base', () => {
  it('ratio Na/K bajo dispara sospecha de hipoadrenocorticismo con gravedad escalada', () => {
    const patrones = analizarResultados({ sodio: 130, potasio: 7 }, paciente(), referencias, alteraciones).patrones;
    const ratio = patrones.find((p) => p.nombre === alteraciones.ratio_nak.nombre);
    expect(ratio).toBeDefined();
    // 130/7 ≈ 18.6 < 20 → grave
    expect(ratio?.gravedad).toBe('grave');
    expect(ratio?.descripcion).toContain('18.6');
  });

  it('acidosis mixta (respiratoria + metabólica) cuando pH bajo, pCO2 alto y HCO3 bajo', () => {
    const nombres = nombresPatrones({ ph_sangre: 7.1, pco2: 60, hco3: 12 });
    expect(nombres.some((n) => n.includes(alteraciones.acidosis_metabolica.nombre) && n.includes(alteraciones.acidosis_respiratoria.nombre))).toBe(true);
  });
});

describe('patrones — coagulación', () => {
  it('CID cuando D-dímeros altos y fibrinógeno bajo (gravedad grave)', () => {
    const patrones = analizarResultados({ ddimeros: 5000, fibrinogeno: 50 }, paciente(), referencias, alteraciones).patrones;
    const cid = patrones.find((p) => p.nombre === alteraciones.cid.nombre);
    expect(cid?.gravedad).toBe('grave');
  });

  it('coagulopatía mixta cuando PT y aPTT altos', () => {
    expect(nombresPatrones({ pt: 30, aptt: 120 })).toContain(alteraciones.coagulopatia_mixta.nombre);
  });
});
