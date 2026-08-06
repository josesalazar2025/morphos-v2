// Suite de regresión del motor clínico. Fija el comportamiento actual de analizarResultados
// para que la migración (y cualquier cambio futuro) no altere la lógica validada por el veterinario.
// Carga los datos reales de data/*.json como única fuente de verdad.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { analizarResultados, _internos } from '../src/analisis.js';
import type { AjustesClinicos, Alteraciones, Paciente, Referencias } from '../src/tipos.js';

const aquí = dirname(fileURLToPath(import.meta.url));
const raízDatos = resolve(aquí, '../../data');

const referencias = JSON.parse(
  readFileSync(resolve(raízDatos, 'valores_referencia.json'), 'utf8'),
) as Referencias;
const alteraciones = JSON.parse(
  readFileSync(resolve(raízDatos, 'alteraciones.json'), 'utf8'),
) as Alteraciones;
const ajustes = JSON.parse(
  readFileSync(resolve(raízDatos, 'ajustes_clinicos.json'), 'utf8'),
) as AjustesClinicos;

const paciente = (over: Partial<Paciente> = {}): Paciente => ({
  especie: 'canino',
  raza: null,
  edadMeses: null,
  sexo: null,
  ...over,
});

const nombresPatrones = (valores: Record<string, number>, p = paciente()): string[] =>
  analizarResultados(valores, p, referencias, alteraciones, ajustes).patrones.map((x) => x.nombre);

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
    const r = analizarResultados({ wbc: 30 }, paciente({ especie: null }), referencias, alteraciones, ajustes);
    expect(r).toEqual({ hallazgos: [], patrones: [] });
  });

  it('ignora valores vacíos, null y no numéricos', () => {
    const r = analizarResultados(
      { wbc: '', hct: null, rbc: 'abc' as unknown as number },
      paciente(),
      referencias,
      alteraciones,
      ajustes,
    );
    expect(r.hallazgos).toHaveLength(0);
  });

  it('un valor dentro de rango no genera hallazgos', () => {
    // WBC canino ref 6-17 → 10 está dentro
    const r = analizarResultados({ wbc: 10 }, paciente(), referencias, alteraciones, ajustes);
    expect(r.hallazgos).toHaveLength(0);
    expect(r.patrones).toHaveLength(0);
  });
});

describe('clasificación de gravedad', () => {
  const ref = { inferior: 6, superior: 17, unidad: 'x10³/μL', nombre: 'WBC' };

  it('desviación ≤ 0.5 anchos → leve', () => {
    // ancho 11; 17 + 5 = 22 → 5/11 ≈ 0.45
    expect(_internos.clasificarGravedad(22, ref, ajustes)).toBe('leve');
  });

  it('desviación ≤ 1.5 anchos → moderado', () => {
    // 17 + 11 = 28 → 11/11 = 1.0
    expect(_internos.clasificarGravedad(28, ref, ajustes)).toBe('moderado');
  });

  it('desviación > 1.5 anchos → grave', () => {
    // 17 + 22 = 39 → 22/11 = 2.0
    expect(_internos.clasificarGravedad(39, ref, ajustes)).toBe('grave');
  });

  it('aplica igual por debajo del límite inferior', () => {
    // 6 - 6 = 0 → 6/11 ≈ 0.55 → moderado
    expect(_internos.clasificarGravedad(0, ref, ajustes)).toBe('moderado');
  });
});

describe('ajustes por edad', () => {
  it('cachorro canino eleva el techo de FAL (x3)', () => {
    // FAL canino base: superior típico ~150; con cachorro x3 no se marca a valores moderados
    const base = referencias.canino.fal.superior;
    const adulto = analizarResultados({ fal: base * 2 }, paciente({ edadMeses: 6 }), referencias, alteraciones, ajustes);
    // A los 6 meses el techo es x3, así que base*2 queda dentro de rango → sin patrón colestásico
    expect(adulto.patrones.map((p) => p.nombre)).not.toContain(alteraciones.patron_colestasico.nombre);
  });

  it('geriátrico canino eleva el techo de creatinina', () => {
    const sup = referencias.canino.creat.superior;
    // Valor justo por encima del techo adulto pero dentro del geriátrico (x1.25)
    const valor = sup * 1.2;
    const adulto = analizarResultados({ creat: valor }, paciente({ edadMeses: 60 }), referencias, alteraciones, ajustes);
    const geriatrico = analizarResultados({ creat: valor }, paciente({ edadMeses: 130 }), referencias, alteraciones, ajustes);
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
  // Antes el gato MACHO toleraba un 15% más de creatinina. Se retiró en la auditoría del
  // 2026-07-31: no aparece en ninguna de las dos obras del corpus, y toleraba azotemia justo
  // en la población con más ERC. Lo documentado (masa muscular en lebreles, raza Birman) es
  // ajuste de raza, no de sexo.
  it('el sexo ya no altera el umbral de creatinina en el gato', () => {
    const valor = referencias.felino.creat.superior * 1.1;
    const hembra = analizarResultados({ creat: valor }, paciente({ especie: 'felino', sexo: 'Hembra' }), referencias, alteraciones, ajustes);
    const macho = analizarResultados({ creat: valor }, paciente({ especie: 'felino', sexo: 'Macho' }), referencias, alteraciones, ajustes);
    expect(hembra.hallazgos.some((h) => h.clave === 'creat')).toBe(true);
    expect(macho.hallazgos.some((h) => h.clave === 'creat')).toBe(true);
  });

  it('el gato Birman sí tolera mayor creatinina (Fundamentals p. 585)', () => {
    const valor = referencias.felino.creat.superior * 1.1;
    const comun = analizarResultados({ creat: valor }, paciente({ especie: 'felino', raza: 'Común Europeo' }), referencias, alteraciones, ajustes);
    const birman = analizarResultados({ creat: valor }, paciente({ especie: 'felino', raza: 'Birman' }), referencias, alteraciones, ajustes);
    expect(comun.hallazgos.some((h) => h.clave === 'creat')).toBe(true);
    expect(birman.hallazgos.some((h) => h.clave === 'creat')).toBe(false);
  });
});

describe('cortes clínicos de gravedad (auditoría 2026-07-31)', () => {
  const gravedadDe = (valores: Record<string, number>, p = paciente(), clave = 'hct') =>
    analizarResultados(valores, p, referencias, alteraciones, ajustes)
      .hallazgos.find((h) => h.clave === clave)?.gravedad;

  it('una anemia felina puede ser grave (antes era imposible por construcción)', () => {
    // Con la regla genérica de anchos de rango, 'grave' en un gato exigía un Hct NEGATIVO.
    expect(gravedadDe({ hct: 12 }, paciente({ especie: 'felino' }))).toBe('grave');
    expect(gravedadDe({ hct: 16 }, paciente({ especie: 'felino' }))).toBe('moderado');
    expect(gravedadDe({ hct: 22 }, paciente({ especie: 'felino' }))).toBe('leve');
  });

  it('el Hct canino se gradúa por el umbral de transfusión (PCV ≤ 20%)', () => {
    expect(gravedadDe({ hct: 18 })).toBe('grave');
    expect(gravedadDe({ hct: 25 })).toBe('moderado');
    expect(gravedadDe({ hct: 33 })).toBe('leve');
  });

  it('la trombocitopenia es grave por debajo del umbral hemorrágico (30x10³/µL)', () => {
    expect(gravedadDe({ plt: 25 }, paciente(), 'plt')).toBe('grave');
    expect(gravedadDe({ plt: 60 }, paciente(), 'plt')).toBe('moderado');
    expect(gravedadDe({ plt: 150 }, paciente(), 'plt')).toBe('leve');
  });

  it('el lado alto sigue con la regla genérica de anchos de rango', () => {
    // No hay umbrales publicados para eritrocitosis en el corpus: no se inventan.
    expect(gravedadDe({ hct: 60 })).toBe('leve');
  });
});

describe('patrones — serie roja', () => {
  it('anemia microcítica cuando HCT y VCM bajos', () => {
    const patrones = analizarResultados(
      { hct: 25, vcm: 55 },
      paciente(),
      referencias,
      alteraciones,
      ajustes,
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
    const patrones = analizarResultados({ sodio: 130, potasio: 7 }, paciente(), referencias, alteraciones, ajustes).patrones;
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
    const patrones = analizarResultados({ ddimeros: 5000, fibrinogeno: 50 }, paciente(), referencias, alteraciones, ajustes).patrones;
    const cid = patrones.find((p) => p.nombre === alteraciones.cid.nombre);
    expect(cid?.gravedad).toBe('grave');
  });

  it('coagulopatía mixta cuando PT y aPTT altos', () => {
    expect(nombresPatrones({ pt: 30, aptt: 120 })).toContain(alteraciones.coagulopatia_mixta.nombre);
  });
});

describe('ajustes por raza (auditoría 2026-07-31)', () => {
  it('las razas asiáticas tienen VCM fisiológicamente bajo, no serie roja alta', () => {
    // Fundamentals p. 221: "some healthy Akitas, shibas, Jindos, chow-chows, and shar-peis
    // have lower MCV". Antes se les subía RBC/Hct/Hgb, que no es lo que dice la literatura.
    const valor = referencias.canino.vcm.inferior * 0.95;
    const mestizo = analizarResultados({ vcm: valor }, paciente(), referencias, alteraciones, ajustes);
    const akita = analizarResultados({ vcm: valor }, paciente({ raza: 'Akita Inu' }), referencias, alteraciones, ajustes);
    expect(mestizo.hallazgos.some((h) => h.clave === 'vcm')).toBe(true);
    expect(akita.hallazgos.some((h) => h.clave === 'vcm')).toBe(false);
  });

  it('el shiba acumula microcitosis y plaquetas bajas (dos grupos de raza a la vez)', () => {
    const plt = referencias.canino.plt.inferior * 0.8;
    const mestizo = nombresPatrones({ plt });
    const shiba = nombresPatrones({ plt }, paciente({ raza: 'Shiba Inu' }));
    expect(mestizo).toContain(alteraciones.trombocitopenia.nombre);
    expect(shiba).not.toContain(alteraciones.trombocitopenia.nombre);
  });

  it('el galgo sano no sale hipotiroideo', () => {
    // Fundamentals p. 1065: ~90% de los galgos sanos por debajo del límite inferior de tT4.
    const valor = referencias.canino.t4_total.inferior * 0.7;
    const mestizo = analizarResultados({ t4_total: valor }, paciente(), referencias, alteraciones, ajustes);
    const galgo = analizarResultados({ t4_total: valor }, paciente({ raza: 'Galgo español' }), referencias, alteraciones, ajustes);
    expect(mestizo.hallazgos.some((h) => h.clave === 't4_total')).toBe(true);
    expect(galgo.hallazgos.some((h) => h.clave === 't4_total')).toBe(false);
  });
});

describe('ajustes por edad (auditoría 2026-07-31)', () => {
  it('el cachorro no sale hiperfosforémico con un fósforo propio de su edad', () => {
    // Fundamentals p. 831: cachorros < 12 sem 5,7–10,8 mg/dL frente a 2,5–5,5 del adulto.
    const valor = referencias.canino.fosf.superior * 1.5;
    const adulto = analizarResultados({ fosf: valor }, paciente({ edadMeses: 48 }), referencias, alteraciones, ajustes);
    const cachorro = analizarResultados({ fosf: valor }, paciente({ edadMeses: 3 }), referencias, alteraciones, ajustes);
    expect(adulto.hallazgos.some((h) => h.clave === 'fosf')).toBe(true);
    expect(cachorro.hallazgos.some((h) => h.clave === 'fosf')).toBe(false);
  });
});

describe('correlación calcio-fósforo (auditoría 2026-07-31)', () => {
  const descripcionHipercalcemia = (valores: Record<string, number>) =>
    analizarResultados(valores, paciente(), referencias, alteraciones, ajustes)
      .patrones.find((p) => p.nombre === alteraciones.hipercalcemia.nombre)?.descripcion ?? '';

  it('con fósforo bajo prioriza malignidad e hiperparatiroidismo primario', () => {
    const d = descripcionHipercalcemia({ calc: referencias.canino.calc.superior * 1.4, fosf: 1.5 });
    // La entidad explica la regla; el patrón añade la conclusión APLICADA a este paciente.
    expect(d).toContain('Con el fósforo bajo, los dos diferenciales probables');
    expect(d).not.toContain('Con el fósforo alto');
  });

  it('con fósforo alto prioriza fallo renal y las causas que cursan con fósforo alto', () => {
    const d = descripcionHipercalcemia({ calc: referencias.canino.calc.superior * 1.4, fosf: 12 });
    expect(d).toContain('Con el fósforo alto, priorizar fallo renal');
    expect(d).not.toContain('Con el fósforo bajo');
  });
});

describe('estadiaje IRIS de ERC (guía IRIS 2026 + Fundamentals Tabla 8.4)', () => {
  const patronIris = (valores: Record<string, number>, p = paciente()) =>
    analizarResultados(valores, p, referencias, alteraciones, ajustes)
      .patrones.find((x) => x.nombre.startsWith(alteraciones.erc_iris.nombre));

  it('estadia por creatinina y escala la gravedad con el estadio', () => {
    // Gato: estadio 2 = 1,6–2,8 · estadio 3 = 2,9–5,0 · estadio 4 = > 5,0 mg/dL
    const felino = paciente({ especie: 'felino' });
    expect(patronIris({ creat: 2.5 }, felino)?.gravedad).toBe('leve');
    expect(patronIris({ creat: 4.8 }, felino)?.nombre).toContain('estadio 3');
    expect(patronIris({ creat: 6.0 }, felino)?.gravedad).toBe('grave');
  });

  it('una creatinina dentro de rango no genera estadio', () => {
    // La guía estadia pacientes YA diagnosticados: sin hallazgo no se inventa un estadio.
    expect(patronIris({ creat: 1.2 })).toBeUndefined();
  });

  it('la SDMA discrepante sube de estadio y lo deja dicho', () => {
    // Perro en estadio 2 por creatinina (1,4–2,8) con SDMA > 35 → tratar como estadio 3.
    const p = patronIris({ creat: 2.0, sdma: 40 });
    expect(p?.nombre).toContain('estadio 3');
    expect(p?.descripcion).toContain('SDMA discrepante');
  });

  it('subestadia la proteinuria con los cortes de cada especie', () => {
    // Perro: proteinúrico > 0,5 · limítrofe 0,2–0,5 || Gato: proteinúrico > 0,4
    expect(patronIris({ creat: 3.0, upc: 0.8 })?.nombre).toContain('proteinúrico');
    expect(patronIris({ creat: 3.0, upc: 0.3 })?.nombre).toContain('limítrofe');
    expect(patronIris({ creat: 3.0, upc: 0.45 }, paciente({ especie: 'felino' }))?.nombre)
      .toContain('proteinúrico');
  });

  it('la gravedad de la creatinina sigue los estadios IRIS, no el ancho de rango', () => {
    const grav = (v: number, p = paciente()) =>
      analizarResultados({ creat: v }, p, referencias, alteraciones, ajustes)
        .hallazgos.find((h) => h.clave === 'creat')?.gravedad;
    expect(grav(2.0)).toBe('leve');
    expect(grav(4.0)).toBe('moderado');
    expect(grav(6.0)).toBe('grave');
  });
});

describe('las reglas clínicas son datos, no código', () => {
  // Simétrico de test_gravedad_servidor.py: si alguien volviera a incrustar los umbrales en el
  // código, estos dos seguirían dando el veredicto viejo y fallarían.
  const conAjustes = (mutar: (a: AjustesClinicos) => void): AjustesClinicos => {
    const copia = JSON.parse(JSON.stringify(ajustes)) as AjustesClinicos;
    mutar(copia);
    return copia;
  };

  it('los cortes de gravedad salen del JSON', () => {
    const relajado = conAjustes((a) => {
      a.cortes_gravedad_bajo.hct.canino = { leve_hasta: 5, moderado_hasta: 1 };
    });
    const r = analizarResultados({ hct: 12 }, paciente(), referencias, alteraciones, relajado);
    expect(r.hallazgos.find((h) => h.clave === 'hct')?.gravedad).toBe('leve');
  });

  it('los límites de edad salen del JSON', () => {
    const adelantado = conAjustes((a) => {
      a.limites_edad_meses.canino!.cachorro = 1;
    });
    const cachorro = paciente({ edadMeses: 4 });
    // Con el límite en 1 mes ya es adulto y pierde el ajuste de fósforo del animal en crecimiento.
    const r = analizarResultados({ fosf: 8 }, cachorro, referencias, alteraciones, adelantado);
    expect(r.hallazgos.map((h) => h.clave)).toContain('fosf');
  });
});
