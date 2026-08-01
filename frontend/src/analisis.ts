// Motor de detección de patrones clínicos.
// Puerto TypeScript fiel de js/analisis.js — la lógica no cambia; sólo se añaden tipos.
// Compara valores contra rangos de referencia ajustados por edad, raza y sexo,
// clasifica gravedad y detecta patrones clínicos.

import type {
  Alteraciones,
  Especie,
  Gravedad,
  Hallazgo,
  Paciente,
  Patron,
  RangoReferencia,
  Referencias,
  ReferenciasEspecie,
  ResultadoAnalisis,
  ValoresFormulario,
} from './tipos.js';

// Gravedad
// La desviación se mide en múltiplos del ancho del rango de referencia.
// Ej: rango WBC 6-17 (ancho = 11). WBC = 28 → desviación = 11/11 = 1.0 → moderado.

const UMBRALES_GRAVEDAD = { leve: 0.5, moderado: 1.5 };

// Cortes clinicos explicitos para el lado BAJO, en la unidad del analito. La regla generica de
// anchos de rango no sabe expresar la gravedad de estos dos: con rango 24-45, un gato
// necesitaria un hematocrito NEGATIVO para llegar a 'grave', y con 200-500 unas plaquetas de
// -250. Es decir, ni una anemia felina ni una trombocitopenia disparaban nunca el suelo de
// derivacion. Anclajes de la literatura (auditoria 2026-07-31):
//   - PCV <= 20% es umbral de transfusion en perro y gato, y <= 12% (Hgb < 4 g/dL) es
//     potencialmente mortal — Thrall 3.a ed., p. 240.
//   - PCV 13 en gato se describe como "markedly anemic" y 24 como "mildly anemic" — p. 800-801.
//   - El riesgo hemorragico por trombocitopenia aparece por debajo de 30x10^3/uL —
//     Fundamentals 3.a ed., p. 310.
// Los cortes interiores del gato (14, 20) siguen la gradacion de uso comun; no estan en estas
// dos obras, que no traen tabla de gradacion.
type CortesBajo = { leveHasta: number; moderadoHasta: number };

const CORTES_GRAVEDAD_BAJO: Record<string, Partial<Record<Especie, CortesBajo>>> = {
  hct: {
    canino: { leveHasta: 30, moderadoHasta: 20 },
    felino: { leveHasta: 20, moderadoHasta: 14 },
  },
  plt: {
    canino: { leveHasta: 100, moderadoHasta: 30 },
    felino: { leveHasta: 100, moderadoHasta: 30 },
  },
};

// Cortes explicitos para el lado ALTO. Los renales salen del estadiaje IRIS de ERC (guia
// modificada en 2026, indexada en el RAG; la misma tabla esta en Fundamentals 3.a ed., p. 573,
// Tabla 8.4). Se mapean los cuatro estadios sobre las tres gravedades del motor:
// estadio 2 -> leve, estadio 3 -> moderado, estadio 4 -> grave.
// El estadio 1 queda dentro del rango de referencia y no genera hallazgo.
const CORTES_GRAVEDAD_ALTO: Record<string, Partial<Record<Especie, CortesBajo>>> = {
  creat: {
    canino: { leveHasta: 2.8, moderadoHasta: 5.0 },
    felino: { leveHasta: 2.8, moderadoHasta: 5.0 },
  },
  sdma: {
    canino: { leveHasta: 35, moderadoHasta: 54 },
    felino: { leveHasta: 25, moderadoHasta: 38 },
  },
  // La proteinuria IRIS no se subestadia mas alla de "proteinurico": nunca llega a 'grave'.
  upc: {
    canino: { leveHasta: 0.5, moderadoHasta: Number.POSITIVE_INFINITY },
    felino: { leveHasta: 0.4, moderadoHasta: Number.POSITIVE_INFINITY },
  },
};

const clasificarGravedad = (
  valor: number,
  ref: RangoReferencia,
  clave?: string,
  especie?: Especie,
): Gravedad => {
  const cortesBajo = clave && especie ? CORTES_GRAVEDAD_BAJO[clave]?.[especie] : undefined;
  if (cortesBajo && valor < ref.inferior) {
    if (valor < cortesBajo.moderadoHasta) return 'grave';
    if (valor < cortesBajo.leveHasta) return 'moderado';
    return 'leve';
  }

  const cortesAlto = clave && especie ? CORTES_GRAVEDAD_ALTO[clave]?.[especie] : undefined;
  if (cortesAlto && valor > ref.superior) {
    if (valor > cortesAlto.moderadoHasta) return 'grave';
    if (valor > cortesAlto.leveHasta) return 'moderado';
    return 'leve';
  }

  // Mide cuantos anchos de rango de referencia se desvia el valor
  const rango = ref.superior - ref.inferior;
  const desviacion = valor > ref.superior
    ? (valor - ref.superior) / rango
    : (ref.inferior - valor) / rango;

  if (desviacion <= UMBRALES_GRAVEDAD.leve) return 'leve';
  if (desviacion <= UMBRALES_GRAVEDAD.moderado) return 'moderado';
  return 'grave';
};

// Edad

const categorizarEdad = (edadMeses: number | null, especie: Especie): string => {
  if (edadMeses === null) return 'adulto';

  if (especie === 'canino') {
    if (edadMeses < 12) return 'cachorro';
    if (edadMeses < 84) return 'adulto';
    if (edadMeses < 120) return 'senior';
    return 'geriatrico';
  }

  // felino
  if (edadMeses < 12) return 'cachorro';
  if (edadMeses < 120) return 'adulto';
  return 'senior';
};

// Factores multiplicativos aplicados a los límites del rango de referencia.
type FactorRango = { inferior?: number; superior?: number };
type TablaAjustes = Record<string, FactorRango>;

// Ajustes por edad

// El fosforo del animal en crecimiento es el hueco que mas falsos positivos generaba: sin el,
// TODO cachorro sale hiperfosforemico y arrastra patrones renales falsos. Fundamentals 3.a ed.,
// p. 831: cachorros < 12 sem 5,7-10,8 mg/dL frente a 2,5-5,5 del adulto; gatitos 5,0-10,0 frente
// a 1,8-6,4. La FAL del gatito se sube de x2,0 a x3,0: gatitos de 4 semanas 97-274 U/L frente a
// 10-80 del adulto (x3,4 el limite superior, Thrall 3.a ed., p. 447), y Fundamentals p. 831 pone
// el techo general del joven en "< 3 veces el limite superior del adulto".
const AJUSTES_EDAD: Record<Especie, Record<string, TablaAjustes>> = {
  canino: {
    cachorro: { fal: { superior: 3.0 }, wbc: { superior: 1.25 }, fosf: { superior: 1.8 } },
    adulto: {},
    senior: { bun: { superior: 1.15 }, creat: { superior: 1.15 } },
    geriatrico: { bun: { superior: 1.25 }, creat: { superior: 1.25 }, fal: { superior: 1.40 } },
  },
  felino: {
    cachorro: { fal: { superior: 3.0 }, wbc: { superior: 1.20 }, fosf: { superior: 1.3 } },
    adulto: {},
    senior: { bun: { superior: 1.20 }, creat: { superior: 1.20 } },
  },
};

// Ajustes por raza

const AJUSTES_RAZA: Partial<Record<Especie, Array<{ razas: string[]; ajustes: TablaAjustes }>>> = {
  canino: [
    {
      // Lebreles. Fundamentals 3.a ed., p. 213-214: los RI de Hct, Hgb y RBC son mas altos en
      // greyhounds, afganos, salukis y whippets. Plaquetas mas bajas en lebreles (p. 307-310).
      // La T4 es la trampa clinica: tT4 y fT4 por debajo del RI canino general en ~90% de los
      // galgos sanos (p. 1065), asi que sin este ajuste un galgo sano sale hipotiroideo.
      razas: ['galgo', 'greyhound', 'whippet', 'lebrel', 'afgano', 'afghan', 'saluki', 'sloughi'],
      ajustes: {
        rbc: { inferior: 1.15, superior: 1.15 },
        hgb: { inferior: 1.12, superior: 1.12 },
        hct: { inferior: 1.12, superior: 1.12 },
        plt: { inferior: 0.75, superior: 0.75 },
        t4_total: { inferior: 0.5, superior: 0.8 },
        t4_libre: { inferior: 0.5, superior: 0.8 },
        creat: { superior: 1.15 },
      },
    },
    {
      // Razas asiaticas con microcitosis fisiologica. Antes se les subia RBC/Hct/Hgb, que no es
      // lo que dice la literatura: Fundamentals p. 221 documenta que "some healthy Akitas,
      // shibas, Jindos, chow-chows, and shar-peis have lower MCV" — VCM bajo SIN anemia. Subir
      // la serie roja generaba falsas anemias; bajar el VCM evita la falsa "anemia microcitica".
      // El shiba inu ademas tiene plaquetas sustancialmente mas bajas (p. 307-310).
      razas: ['shiba', 'akita', 'jindo', 'chow', 'shar pei', 'shar-pei', 'sharpei'],
      ajustes: { vcm: { inferior: 0.85, superior: 0.92 } },
    },
    {
      razas: ['shiba'],
      ajustes: { plt: { inferior: 0.75, superior: 0.9 } },
    },
  ],
  felino: [
    // Fundamentals p. 213-214: los limites inferiores de Hgb y Hct del Maine Coon son
    // sustancialmente mayores que los de las razas felinas tipicas.
    {
      razas: ['maine coon', 'maine'],
      ajustes: { hct: { inferior: 1.15 }, hgb: { inferior: 1.15 } },
    },
    // Fundamentals p. 585: la creatinina de gatos Birman clinicamente sanos puede superar el
    // limite superior de los RI felinos de rutina.
    {
      razas: ['birman', 'sagrado de birmania'],
      ajustes: { creat: { superior: 1.2 } },
    },
  ],
};

// Ajustes por sexo

// Retirado el ajuste que subia un 15% el techo de creatinina en el gato MACHO: no aparece en
// ninguna de las dos obras del corpus. Lo que si esta documentado es la masa muscular (los
// galgos tienen creatinina mas alta, Thrall 3.a ed., p. 363) y la raza Birman (Fundamentals
// 3.a ed., p. 585), y ambos se tratan ahora como ajuste de RAZA. Ademas, la secrecion tubular
// de creatinina es cosa del perro macho —"cats and ponies do not secrete or reabsorb Ct in
// their kidneys" (Thrall p. 363)— y se describe como clinicamente intrascendente. Tolerar un
// 15% mas de creatinina justo en la poblacion con mas ERC era infradeteccion sin respaldo.
//
// Lo unico con respaldo por sexo es menor: en perro las plaquetas son hasta un 10% mayores en
// hembras y en enteros (Fundamentals p. 310). No se implementa: por debajo de la resolucion
// clinica del motor.
const AJUSTES_SEXO: Partial<Record<Especie, Record<string, TablaAjustes>>> = {};

// Combina TODOS los grupos que casan, no solo el primero: un shiba inu pertenece a la vez al
// grupo de microcitosis fisiologica y al de plaquetas bajas, y quedarse con el primero perdia
// el segundo en silencio.
const obtenerAjustesRaza = (raza: string | null, especie: Especie): TablaAjustes => {
  const razaNorm = raza?.toLowerCase().trim() ?? '';
  const grupos = AJUSTES_RAZA[especie] ?? [];
  return grupos
    .filter((g) => g.razas.some((r) => razaNorm.includes(r)))
    .reduce<TablaAjustes>((acc, grupo) => {
      for (const [clave, factor] of Object.entries(grupo.ajustes)) {
        acc[clave] = {
          inferior: (acc[clave]?.inferior ?? 1) * (factor.inferior ?? 1),
          superior: (acc[clave]?.superior ?? 1) * (factor.superior ?? 1),
        };
      }
      return acc;
    }, {});
};

// Ajuste de referencias

const ajustarReferencias = (refsEspecie: ReferenciasEspecie, paciente: Paciente): ReferenciasEspecie => {
  const especie = paciente.especie as Especie;
  const catEdad = categorizarEdad(paciente.edadMeses, especie);
  const ajEdad = AJUSTES_EDAD[especie]?.[catEdad] ?? {};
  const ajRaza = obtenerAjustesRaza(paciente.raza, especie);
  const ajSexo = (paciente.sexo ? AJUSTES_SEXO[especie]?.[paciente.sexo] : undefined) ?? {};

  // Multiplica los limites inferiores y superiores por los factores de edad, raza y sexo
  return Object.entries(refsEspecie).reduce<ReferenciasEspecie>((acc, [clave, ref]) => {
    const factorEdad = ajEdad[clave] ?? {};
    const factorRaza = ajRaza[clave] ?? {};
    const factorSexo = ajSexo[clave] ?? {};

    acc[clave] = {
      ...ref,
      inferior: ref.inferior * (factorEdad.inferior ?? 1) * (factorRaza.inferior ?? 1) * (factorSexo.inferior ?? 1),
      superior: ref.superior * (factorEdad.superior ?? 1) * (factorRaza.superior ?? 1) * (factorSexo.superior ?? 1),
    };
    return acc;
  }, {});
};

// Estadiaje IRIS de la enfermedad renal crónica
//
// Fuente: IRIS Staging of CKD (modificado 2026), indexada en el RAG; la misma tabla aparece en
// Fundamentals 3.a ed., p. 573 (Tabla 8.4). Estadio por creatinina, con la escalada por
// discrepancia con SDMA que describe la propia guía, y subestadio por proteinuria (UP/C).
//
// Limitación deliberada: la guía estadia pacientes YA diagnosticados de ERC, en ayunas y sobre
// muestras seriadas estables. El motor sólo ve una analítica suelta, así que el estadio se
// emite únicamente cuando la creatinina o la SDMA salen del rango de referencia, y se etiqueta
// como orientativo. Un perro con creatinina 1,5 (estadio 2 IRIS pero dentro de nuestro rango)
// no se estadia: haría falta el diagnóstico previo de ERC, que el motor no tiene.
const CORTES_IRIS_CREAT: Record<Especie, number[]> = {
  // Límite superior de los estadios 1, 2 y 3 en mg/dL (por encima del último → estadio 4).
  canino: [1.4, 2.8, 5.0],
  felino: [1.6, 2.8, 5.0],
};

const CORTES_IRIS_SDMA: Record<Especie, number[]> = {
  // SDMA que hace subir de estadio cuando discrepa con la creatinina (µg/dL).
  canino: [18, 35, 54],
  felino: [18, 25, 38],
};

// UP/C: [no proteinúrico por debajo de, proteinúrico por encima de]
const CORTES_IRIS_UPC: Record<Especie, [number, number]> = {
  canino: [0.2, 0.5],
  felino: [0.2, 0.4],
};

type EstadioIris = { estadio: number; subestadio: string; nota: string };

const estadificarIris = (
  creat: number | null,
  sdma: number | null,
  upc: number | null,
  especie: Especie,
): EstadioIris | null => {
  if (creat === null && sdma === null) return null;

  const cortesCreat = CORTES_IRIS_CREAT[especie];
  const cortesSdma = CORTES_IRIS_SDMA[especie];

  const porCreatinina = creat === null
    ? 1
    : cortesCreat.findIndex((techo) => creat <= techo) + 1 || 4;

  // Escalada por SDMA: la guía sube un estadio cuando la SDMA persistente supera el umbral
  // del estadio asignado por creatinina (>18 en el 1, >35/25 en el 2, >54/38 en el 3).
  const umbral = cortesSdma[porCreatinina - 1];
  const escalado = sdma !== null && umbral !== undefined && sdma > umbral
    ? porCreatinina + 1
    : porCreatinina;

  if (escalado < 2) return null; // estadio 1: sin azotemia ni SDMA alta, nada que informar

  const [noProteinurico, proteinurico] = CORTES_IRIS_UPC[especie];
  const subestadio = upc === null
    ? ''
    : upc > proteinurico ? 'proteinúrico'
      : upc >= noProteinurico ? 'proteinúrico limítrofe'
        : 'no proteinúrico';

  const nota = escalado > porCreatinina
    ? `Estadio elevado de ${porCreatinina} a ${escalado} por SDMA discrepante (${sdma} µg/dL).`
    : '';

  return { estadio: escalado, subestadio, nota };
};

// Detección de patrones clínicos

const detectarPatrones = (hallazgos: Hallazgo[], especie: Especie, alt: Alteraciones): Patron[] => {
  const mapa = hallazgos.reduce<Record<string, Hallazgo>>((acc, h) => { acc[h.clave] = h; return acc; }, {});

  const esAlto = (clave: string): boolean => mapa[clave]?.direccion === 'alto';
  const esBajo = (clave: string): boolean => mapa[clave]?.direccion === 'bajo';
  const presente = (clave: string): boolean => clave in mapa;
  const valor = (clave: string): number | null => mapa[clave]?.valor ?? null;

  const gravedadDe = (...claves: string[]): Gravedad => {
    const clave = claves.find((c) => mapa[c]);
    return (clave ? mapa[clave]?.gravedad : undefined) ?? 'leve';
  };

  const patrones: Patron[] = [];
  const agregar = (patron: Patron): number => patrones.push(patron);

  // Serie roja

  if (esBajo('hct') || esBajo('hgb') || esBajo('rbc')) {
    // Clasifica el tipo de anemia segun el VCM para sugerir la etiologia mas probable
    const tipoPorVcm = !presente('vcm') ? '' :
      esBajo('vcm') ? 'microcítica' :
      esAlto('vcm') ? 'macrocítica' : 'normocítica';

    const claveEtiologia = esBajo('vcm') ? 'ferropenia' :
      esAlto('vcm') ? 'macrocitica' :
      tipoPorVcm === 'normocítica' ? 'normocitica' : null;
    const etiologia = claveEtiologia ? alt.anemia.etiologias?.[claveEtiologia] ?? '' : '';

    agregar({
      nombre: `${alt.anemia.nombre}${tipoPorVcm ? ` ${tipoPorVcm}` : ''}`,
      descripcion: [alt.anemia.prefijo, etiologia].filter(Boolean).join(' '),
      gravedad: gravedadDe('hct', 'hgb', 'rbc'),
      parametros: ['hct', 'hgb', 'rbc', 'vcm'].filter(presente),
    });
  }

  if (esAlto('hct') || esAlto('rbc')) agregar({
    nombre: alt.eritrocitosis.nombre,
    descripcion: alt.eritrocitosis.descripcion,
    gravedad: gravedadDe('hct', 'rbc'),
    parametros: ['hct', 'rbc', 'hgb'].filter(presente),
  });

  // Serie blanca

  if (esAlto('wbc')) {
    // Diferencia leucocitosis neutrofilica de linfocitica; si no hay diferencial, informa generico
    const neutrofilia = esAlto('neutro');
    const linfocitosis = esAlto('linfo');

    if (neutrofilia) agregar({
      nombre: alt.leucocitosis_neutrofilica.nombre,
      descripcion: alt.leucocitosis_neutrofilica.descripcion,
      gravedad: gravedadDe('wbc', 'neutro'),
      parametros: ['wbc', 'neutro'].filter(presente),
    });

    if (linfocitosis) agregar({
      nombre: alt.leucocitosis_linfocitica.nombre,
      descripcion: alt.leucocitosis_linfocitica.descripcion,
      gravedad: gravedadDe('wbc', 'linfo'),
      parametros: ['wbc', 'linfo'].filter(presente),
    });

    if (!neutrofilia && !linfocitosis) agregar({
      nombre: alt.leucocitosis.nombre,
      descripcion: alt.leucocitosis.descripcion,
      gravedad: gravedadDe('wbc'),
      parametros: ['wbc'],
    });
  }

  if (esBajo('wbc')) agregar({
    nombre: alt.leucopenia.nombre,
    descripcion: alt.leucopenia.descripcion,
    gravedad: gravedadDe('wbc'),
    parametros: ['wbc'],
  });

  if (esBajo('neutro')) agregar({
    nombre: alt.neutropenia.nombre,
    descripcion: alt.neutropenia.descripcion,
    gravedad: gravedadDe('neutro'),
    parametros: ['neutro'],
  });

  if (esBajo('linfo')) agregar({
    nombre: alt.linfopenia.nombre,
    descripcion: alt.linfopenia.descripcion,
    gravedad: gravedadDe('linfo'),
    parametros: ['linfo'],
  });

  if (esAlto('eosino')) agregar({
    nombre: alt.eosinofilia.nombre,
    descripcion: alt.eosinofilia.descripcion,
    gravedad: gravedadDe('eosino'),
    parametros: ['eosino'],
  });

  // Plaquetas

  if (esBajo('plt')) agregar({
    nombre: alt.trombocitopenia.nombre,
    descripcion: alt.trombocitopenia.descripcion,
    gravedad: gravedadDe('plt'),
    parametros: ['plt'],
  });

  if (esAlto('plt')) agregar({
    nombre: alt.trombocitosis.nombre,
    descripcion: alt.trombocitosis.descripcion,
    gravedad: gravedadDe('plt'),
    parametros: ['plt'],
  });

  // Hígado

  if (esAlto('alt') && esAlto('ast')) agregar({
    nombre: alt.dano_hepatocelular.nombre,
    descripcion: alt.dano_hepatocelular.descripcion,
    gravedad: gravedadDe('alt', 'ast'),
    parametros: ['alt', 'ast'].filter(presente),
  });
  else if (esAlto('alt')) agregar({
    nombre: alt.alt_aislada.nombre,
    descripcion: alt.alt_aislada.descripcion,
    gravedad: gravedadDe('alt'),
    parametros: ['alt'],
  });

  if (esAlto('fal')) agregar({
    nombre: alt.patron_colestasico.nombre,
    descripcion: alt.patron_colestasico.descripcion[especie] ?? alt.patron_colestasico.descripcion.canino,
    gravedad: gravedadDe('fal'),
    parametros: ['fal'],
  });

  if (esAlto('bili')) agregar({
    nombre: alt.hiperbilirrubinemia.nombre,
    descripcion: alt.hiperbilirrubinemia.descripcion,
    gravedad: gravedadDe('bili'),
    parametros: ['bili'],
  });

  // Riñón

  if (esAlto('bun') && esAlto('creat')) agregar({
    nombre: alt.azotemia.nombre,
    descripcion: alt.azotemia.descripcion,
    gravedad: gravedadDe('creat', 'bun'),
    parametros: ['bun', 'creat'].filter(presente),
  });
  else if (esAlto('bun')) agregar({
    nombre: alt.hiperuremia_bun.nombre,
    descripcion: alt.hiperuremia_bun.descripcion,
    gravedad: gravedadDe('bun'),
    parametros: ['bun'],
  });
  else if (esAlto('creat')) agregar({
    nombre: alt.creatinina_aislada.nombre,
    descripcion: alt.creatinina_aislada.descripcion,
    gravedad: gravedadDe('creat'),
    parametros: ['creat'],
  });

  // Estadiaje IRIS. Se emite como patrón aparte de la azotemia porque responde a otra
  // pregunta: la azotemia dice QUÉ está alterado, el estadio dice CUÁNTO y guía el manejo.
  const estadio = estadificarIris(valor('creat'), valor('sdma'), valor('upc'), especie);
  if (estadio) agregar({
    nombre: `${alt.erc_iris.nombre} — estadio ${estadio.estadio}${estadio.subestadio ? `, ${estadio.subestadio}` : ''}`,
    descripcion: `${alt.erc_iris.descripcion} ${estadio.nota}`,
    gravedad: estadio.estadio >= 4 ? 'grave' : estadio.estadio === 3 ? 'moderado' : 'leve',
    parametros: ['creat', 'sdma', 'upc'].filter(presente),
  });

  if (esBajo('bun')) agregar({
    nombre: alt.bun_disminuido.nombre,
    descripcion: alt.bun_disminuido.descripcion,
    gravedad: gravedadDe('bun'),
    parametros: ['bun'],
  });

  // Glucosa

  if (esAlto('gluc')) agregar({
    nombre: alt.hiperglucemia.nombre,
    descripcion: alt.hiperglucemia.descripcion[especie] ?? alt.hiperglucemia.descripcion.canino,
    gravedad: gravedadDe('gluc'),
    parametros: ['gluc'],
  });

  if (esBajo('gluc')) agregar({
    nombre: alt.hipoglucemia.nombre,
    descripcion: alt.hipoglucemia.descripcion,
    gravedad: gravedadDe('gluc'),
    parametros: ['gluc'],
  });

  // Proteínas

  if (esAlto('prot')) agregar({
    nombre: alt.hiperproteinemia.nombre,
    descripcion: alt.hiperproteinemia.descripcion,
    gravedad: gravedadDe('prot'),
    parametros: ['prot'],
  });

  if (esBajo('alb')) {
    const hipoproteinemia = esBajo('prot');
    const claveAlteracion = hipoproteinemia ? 'hipoproteinemia_hipoalbuminemia' : 'hipoalbuminemia';
    agregar({
      nombre: alt[claveAlteracion].nombre,
      descripcion: alt[claveAlteracion].descripcion,
      gravedad: gravedadDe('alb'),
      parametros: ['alb', ...(hipoproteinemia ? ['prot'] : [])].filter(presente),
    });
  }

  // Electrolitos

  const valSodio = valor('sodio');
  const valPotasio = valor('potasio');

  // Ratio Na/K < 27 es sugestivo de hipoadrenocorticismo; la gravedad aumenta a menor ratio
  if (valSodio !== null && valPotasio !== null && valPotasio > 0) {
    const ratioNaK = valSodio / valPotasio;
    if (ratioNaK < 27) agregar({
      nombre: alt.ratio_nak.nombre,
      descripcion: alt.ratio_nak.descripcion.replace('{ratio}', ratioNaK.toFixed(1)),
      gravedad: ratioNaK < 20 ? 'grave' : ratioNaK < 24 ? 'moderado' : 'leve',
      parametros: ['sodio', 'potasio'].filter(presente),
    });
  }

  if (esAlto('sodio')) agregar({
    nombre: alt.hipernatremia.nombre,
    descripcion: alt.hipernatremia.descripcion,
    gravedad: gravedadDe('sodio'),
    parametros: ['sodio'],
  });

  if (esBajo('sodio')) agregar({
    nombre: alt.hiponatremia.nombre,
    descripcion: alt.hiponatremia.descripcion,
    gravedad: gravedadDe('sodio'),
    parametros: ['sodio'],
  });

  // El fosforo es EL discriminador de la hipercalcemia, y sin el se devuelve una lista de
  // diferenciales que no discrimina nada. Thrall 3.a ed., p. 586 y p. 997: con calcio alto y
  // fosforo normal o bajo solo quedan dos diagnosticos probables —hipercalcemia maligna
  // (linfoma el tumor mas frecuente, luego adenocarcinoma de sacos anales) e hiperparatiroidismo
  // primario—, mientras que hipoadrenocorticismo, fallo renal, toxicidad por vitamina D y
  // enfermedad granulomatosa cursan habitualmente con el fosforo ALTO.
  if (esAlto('calc')) {
    // Solo se matiza cuando el fosforo aparece como hallazgo: un fosforo dentro de rango y uno
    // no medido son indistinguibles aqui (a detectarPatrones solo llegan los valores alterados).
    const matizPorFosforo = esBajo('fosf')
      ? ' Con el fósforo bajo, los dos diferenciales probables son hipercalcemia maligna '
        + '(linfoma, adenocarcinoma de sacos anales) e hiperparatiroidismo primario.'
      : esAlto('fosf')
        ? ' Con el fósforo alto, priorizar fallo renal, hipoadrenocorticismo, toxicidad por '
          + 'vitamina D y enfermedad granulomatosa.'
        : '';
    agregar({
      nombre: alt.hipercalcemia.nombre,
      descripcion: alt.hipercalcemia.descripcion + matizPorFosforo,
      gravedad: gravedadDe('calc'),
      parametros: ['calc', ...(presente('fosf') ? ['fosf'] : [])],
    });
  }

  if (esBajo('calc')) agregar({
    nombre: alt.hipocalcemia.nombre,
    descripcion: alt.hipocalcemia.descripcion,
    gravedad: gravedadDe('calc'),
    parametros: ['calc'],
  });

  if (esBajo('potasio')) agregar({
    nombre: alt.hipopotasemia.nombre,
    descripcion: alt.hipopotasemia.descripcion,
    gravedad: gravedadDe('potasio'),
    parametros: ['potasio'],
  });

  if (esAlto('potasio')) agregar({
    nombre: alt.hiperpotasemia.nombre,
    descripcion: alt.hiperpotasemia.descripcion,
    gravedad: gravedadDe('potasio'),
    parametros: ['potasio'],
  });

  if (esAlto('fosf')) agregar({
    nombre: alt.hiperfosforemia.nombre,
    descripcion: alt.hiperfosforemia.descripcion,
    gravedad: gravedadDe('fosf'),
    parametros: ['fosf'],
  });

  // Urianálisis

  // Corte de hiposteinuria en 1,007, no en 1,008: la isosteinuria es 1,007-1,013 en perro y
  // gato (Thrall 3.a ed., Tabla 24.8; Fundamentals 3.a ed., p. 565, que la describe como
  // "similar to the often-used 1.008-1.012"). Con 1,008 un USG de 1,0075 se etiquetaba como
  // hiposteinuria cuando la literatura lo considera isosteinurico.
  const valUsg = valor('usg');
  if (valUsg !== null && valUsg < 1.007) agregar({
    nombre: alt.hiposthenuria.nombre,
    descripcion: alt.hiposthenuria.descripcion,
    gravedad: valUsg < 1.005 ? 'grave' : 'moderado',
    parametros: ['usg'],
  });
  else if (valUsg !== null && valUsg < 1.013) agregar({
    nombre: alt.isosthenuria.nombre,
    descripcion: alt.isosthenuria.descripcion,
    gravedad: 'leve',
    parametros: ['usg'],
  });

  // Tiroides

  if (especie === 'canino' && esBajo('t4_total')) agregar({
    nombre: alt.hipotiroidismo.nombre,
    descripcion: alt.hipotiroidismo.descripcion.canino,
    gravedad: gravedadDe('t4_total'),
    parametros: ['t4_total'].filter(presente),
  });

  if (esAlto('t4_total')) agregar({
    nombre: alt.hipertiroidismo.nombre,
    descripcion: alt.hipertiroidismo.descripcion[especie] ?? alt.hipertiroidismo.descripcion.felino,
    gravedad: gravedadDe('t4_total'),
    parametros: ['t4_total'].filter(presente),
  });

  // Suprarrenal / Cortisol

  if (esAlto('cortisol_acth')) agregar({
    nombre: alt.hiperadrenocorticismo.nombre,
    descripcion: alt.hiperadrenocorticismo.descripcion[especie] ?? alt.hiperadrenocorticismo.descripcion.canino,
    gravedad: gravedadDe('cortisol_acth'),
    parametros: ['cortisol_acth', ...(presente('cortisol_bas') ? ['cortisol_bas'] : [])],
  });

  if (esBajo('cortisol_acth')) agregar({
    nombre: alt.hipoadrenocorticismo_cortisol.nombre,
    descripcion: alt.hipoadrenocorticismo_cortisol.descripcion,
    gravedad: gravedadDe('cortisol_acth'),
    parametros: ['cortisol_acth', ...(presente('cortisol_bas') ? ['cortisol_bas'] : [])],
  });

  if (esBajo('cortisol_bas') && !presente('cortisol_acth')) agregar({
    nombre: alt.cortisol_basal_bajo.nombre,
    descripcion: alt.cortisol_basal_bajo.descripcion,
    gravedad: 'moderado',
    parametros: ['cortisol_bas'],
  });

  // Insulina

  if (esBajo('insulina') && esAlto('gluc')) agregar({
    nombre: alt.deficit_insulina.nombre,
    descripcion: alt.deficit_insulina.descripcion,
    gravedad: 'moderado',
    parametros: ['insulina', 'gluc'].filter(presente),
  });

  // Páncreas exocrino (PLI)

  if (esAlto('pli')) agregar({
    nombre: alt.pancreatitis.nombre,
    descripcion: alt.pancreatitis.descripcion[especie] ?? alt.pancreatitis.descripcion.canino,
    gravedad: gravedadDe('pli'),
    parametros: ['pli', ...(presente('lipasa') ? ['lipasa'] : []), ...(presente('amylasa') ? ['amylasa'] : [])].filter(presente),
  });

  if (esAlto('amylasa') && !presente('pli')) agregar({
    nombre: alt.hiperamylasemia.nombre,
    descripcion: alt.hiperamylasemia.descripcion,
    gravedad: gravedadDe('amylasa'),
    parametros: ['amylasa'],
  });

  // Tiroides — TSH

  if (esAlto('tsh')) agregar({
    nombre: alt.tsh_elevado.nombre,
    descripcion: alt.tsh_elevado.descripcion[especie] ?? alt.tsh_elevado.descripcion.canino,
    gravedad: gravedadDe('tsh'),
    parametros: ['tsh', ...(presente('t4_total') ? ['t4_total'] : []), ...(presente('t4_libre') ? ['t4_libre'] : [])].filter(presente),
  });

  if (esBajo('tsh')) agregar({
    nombre: alt.tsh_suprimido.nombre,
    descripcion: alt.tsh_suprimido.descripcion[especie] ?? alt.tsh_suprimido.descripcion.canino,
    gravedad: gravedadDe('tsh'),
    parametros: ['tsh', ...(presente('t4_total') ? ['t4_total'] : [])].filter(presente),
  });

  if (esBajo('t4_libre') && !presente('tsh')) agregar({
    nombre: alt.t4_libre_baja.nombre,
    descripcion: alt.t4_libre_baja.descripcion[especie] ?? alt.t4_libre_baja.descripcion.canino,
    gravedad: gravedadDe('t4_libre'),
    parametros: ['t4_libre', ...(presente('t4_total') ? ['t4_total'] : [])].filter(presente),
  });

  // Biomarcadores cardíacos

  if (esAlto('ctni')) agregar({
    nombre: alt.dano_miocardico.nombre,
    descripcion: alt.dano_miocardico.descripcion,
    gravedad: gravedadDe('ctni'),
    parametros: ['ctni', ...(presente('nt_probnp') ? ['nt_probnp'] : [])].filter(presente),
  });

  if (esAlto('nt_probnp')) agregar({
    nombre: alt.cardiopatia_bnp.nombre,
    descripcion: alt.cardiopatia_bnp.descripcion[especie] ?? alt.cardiopatia_bnp.descripcion.canino,
    gravedad: gravedadDe('nt_probnp'),
    parametros: ['nt_probnp', ...(presente('ctni') ? ['ctni'] : [])].filter(presente),
  });

  // Proteínas de fase aguda

  if (esAlto('crp') || esAlto('saa')) agregar({
    nombre: alt.inflamacion_aguda.nombre,
    descripcion: alt.inflamacion_aguda.descripcion[especie] ?? alt.inflamacion_aguda.descripcion.canino,
    gravedad: gravedadDe('crp', 'saa'),
    parametros: ['crp', 'saa'].filter(presente),
  });

  // Progesterona

  if (esAlto('progesterona')) agregar({
    nombre: alt.progesterona_elevada.nombre,
    descripcion: alt.progesterona_elevada.descripcion[especie] ?? alt.progesterona_elevada.descripcion.canino,
    gravedad: gravedadDe('progesterona'),
    parametros: ['progesterona'],
  });

  // Magnesio

  if (esBajo('magnesio')) agregar({
    nombre: alt.hipomagnesemia.nombre,
    descripcion: alt.hipomagnesemia.descripcion,
    gravedad: gravedadDe('magnesio'),
    parametros: ['magnesio'],
  });

  if (esAlto('magnesio')) agregar({
    nombre: alt.hipermagnesemia.nombre,
    descripcion: alt.hipermagnesemia.descripcion,
    gravedad: gravedadDe('magnesio'),
    parametros: ['magnesio'],
  });

  // Hierro

  if (esBajo('hierro')) agregar({
    nombre: alt.ferropenia_hierro.nombre,
    descripcion: alt.ferropenia_hierro.descripcion,
    gravedad: gravedadDe('hierro'),
    parametros: ['hierro'],
  });

  // Ácido úrico

  if (esAlto('ac_urico')) agregar({
    nombre: alt.ac_urico_elevado.nombre,
    descripcion: alt.ac_urico_elevado.descripcion,
    gravedad: gravedadDe('ac_urico'),
    parametros: ['ac_urico'],
  });

  // LDH

  if (esAlto('ldh')) agregar({
    nombre: alt.ldh_elevada.nombre,
    descripcion: alt.ldh_elevada.descripcion,
    gravedad: gravedadDe('ldh'),
    parametros: ['ldh'],
  });

  // Monitorización de fármacos (TDM)

  if (esBajo('fenobarbital')) agregar({
    nombre: alt.fenobarbital_subterapeutico.nombre,
    descripcion: alt.fenobarbital_subterapeutico.descripcion,
    gravedad: gravedadDe('fenobarbital'),
    parametros: ['fenobarbital'],
  });

  if (esAlto('fenobarbital')) agregar({
    nombre: alt.fenobarbital_toxico.nombre,
    descripcion: alt.fenobarbital_toxico.descripcion,
    gravedad: gravedadDe('fenobarbital'),
    parametros: ['fenobarbital'],
  });

  if (esBajo('ciclosporina')) agregar({
    nombre: alt.ciclosporina_subterapeutica.nombre,
    descripcion: alt.ciclosporina_subterapeutica.descripcion,
    gravedad: gravedadDe('ciclosporina'),
    parametros: ['ciclosporina'],
  });

  if (esAlto('ciclosporina')) agregar({
    nombre: alt.ciclosporina_toxica.nombre,
    descripcion: alt.ciclosporina_toxica.descripcion,
    gravedad: gravedadDe('ciclosporina'),
    parametros: ['ciclosporina'],
  });

  // Coagulación

  if (esAlto('pt') && !esAlto('aptt')) agregar({
    nombre: alt.coagulopatia_extrinseca.nombre,
    descripcion: alt.coagulopatia_extrinseca.descripcion,
    gravedad: gravedadDe('pt'),
    parametros: ['pt'],
  });

  if (esAlto('aptt') && !esAlto('pt')) agregar({
    nombre: alt.coagulopatia_intrinseca.nombre,
    descripcion: alt.coagulopatia_intrinseca.descripcion,
    gravedad: gravedadDe('aptt'),
    parametros: ['aptt'],
  });

  if (esAlto('pt') && esAlto('aptt')) agregar({
    nombre: alt.coagulopatia_mixta.nombre,
    descripcion: alt.coagulopatia_mixta.descripcion,
    gravedad: gravedadDe('pt', 'aptt', 'act'),
    parametros: ['pt', 'aptt', ...(presente('act') ? ['act'] : [])].filter(presente),
  });

  if ((esAlto('ddimeros') || esAlto('fdp')) && esBajo('fibrinogeno')) agregar({
    nombre: alt.cid.nombre,
    descripcion: alt.cid.descripcion,
    gravedad: 'grave',
    parametros: ['ddimeros', 'fdp', 'fibrinogeno', 'plt'].filter(presente),
  });

  if (esAlto('fibrinogeno') && !esAlto('ddimeros') && !esAlto('fdp')) agregar({
    nombre: alt.hiperfibrinogenemia.nombre,
    descripcion: alt.hiperfibrinogenemia.descripcion,
    gravedad: gravedadDe('fibrinogeno'),
    parametros: ['fibrinogeno'],
  });

  if (esBajo('fibrinogeno') && !esAlto('ddimeros') && !esAlto('fdp')) agregar({
    nombre: alt.hipofibrinogenemia.nombre,
    descripcion: alt.hipofibrinogenemia.descripcion,
    gravedad: gravedadDe('fibrinogeno'),
    parametros: ['fibrinogeno'],
  });

  if (esBajo('vwf')) agregar({
    nombre: alt.deficit_vwf.nombre,
    descripcion: alt.deficit_vwf.descripcion,
    gravedad: gravedadDe('vwf'),
    parametros: ['vwf', ...(presente('aptt') ? ['aptt'] : [])].filter(presente),
  });

  if (esBajo('antitrombina')) agregar({
    nombre: alt.antitrombina_baja.nombre,
    descripcion: alt.antitrombina_baja.descripcion,
    gravedad: gravedadDe('antitrombina'),
    parametros: ['antitrombina'],
  });

  // Urianálisis — sedimento / UPC

  if (esAlto('rbc_uri')) agregar({
    nombre: alt.hematuria_uri.nombre,
    descripcion: alt.hematuria_uri.descripcion,
    gravedad: gravedadDe('rbc_uri'),
    parametros: ['rbc_uri'],
  });

  if (esAlto('wbc_uri')) agregar({
    nombre: alt.piuria.nombre,
    descripcion: alt.piuria.descripcion,
    gravedad: gravedadDe('wbc_uri'),
    parametros: ['wbc_uri'],
  });

  if (esAlto('upc')) agregar({
    nombre: alt.proteinuria_upc.nombre,
    descripcion: alt.proteinuria_upc.descripcion,
    gravedad: gravedadDe('upc'),
    parametros: ['upc'],
  });

  // Gasometría — ácido-base

  if (presente('ph_sangre')) {
    const phBajo = esBajo('ph_sangre');
    const phAlto = esAlto('ph_sangre');
    const hipercarbia = esAlto('pco2');
    const hipocarbia = esBajo('pco2');
    const componenteAcidMet = esBajo('hco3') || esBajo('exceso_base');
    const componenteAlcalMet = esAlto('hco3') || esAlto('exceso_base');

    if (phBajo) {
      if (hipercarbia && componenteAcidMet) {
        agregar({
          nombre: alt.acidosis_respiratoria.nombre + ' + ' + alt.acidosis_metabolica.nombre,
          descripcion: alt.acidosis_metabolica.descripcion,
          gravedad: 'grave',
          parametros: ['ph_sangre', 'pco2', 'hco3', 'exceso_base'].filter(presente),
        });
      } else if (hipercarbia) {
        agregar({
          nombre: alt.acidosis_respiratoria.nombre,
          descripcion: alt.acidosis_respiratoria.descripcion,
          gravedad: gravedadDe('ph_sangre', 'pco2'),
          parametros: ['ph_sangre', 'pco2'].filter(presente),
        });
      } else if (componenteAcidMet) {
        agregar({
          nombre: alt.acidosis_metabolica.nombre,
          descripcion: alt.acidosis_metabolica.descripcion,
          gravedad: gravedadDe('ph_sangre', 'hco3', 'exceso_base'),
          parametros: ['ph_sangre', 'hco3', 'exceso_base', 'anion_gap'].filter(presente),
        });
      }
    }

    if (phAlto) {
      if (hipocarbia && componenteAlcalMet) {
        agregar({
          nombre: alt.alcalosis_respiratoria.nombre + ' + ' + alt.alcalosis_metabolica.nombre,
          descripcion: alt.alcalosis_metabolica.descripcion,
          gravedad: 'grave',
          parametros: ['ph_sangre', 'pco2', 'hco3', 'exceso_base'].filter(presente),
        });
      } else if (hipocarbia) {
        agregar({
          nombre: alt.alcalosis_respiratoria.nombre,
          descripcion: alt.alcalosis_respiratoria.descripcion,
          gravedad: gravedadDe('ph_sangre', 'pco2'),
          parametros: ['ph_sangre', 'pco2'].filter(presente),
        });
      } else if (componenteAlcalMet) {
        agregar({
          nombre: alt.alcalosis_metabolica.nombre,
          descripcion: alt.alcalosis_metabolica.descripcion,
          gravedad: gravedadDe('ph_sangre', 'hco3', 'exceso_base'),
          parametros: ['ph_sangre', 'hco3', 'exceso_base'].filter(presente),
        });
      }
    }
  }

  if (esBajo('po2')) agregar({
    nombre: alt.hipoxemia.nombre,
    descripcion: alt.hipoxemia.descripcion,
    gravedad: gravedadDe('po2', 'so2'),
    parametros: ['po2', ...(presente('so2') ? ['so2'] : [])].filter(presente),
  });

  if (esAlto('lactato')) agregar({
    nombre: alt.hiperlactatemia.nombre,
    descripcion: alt.hiperlactatemia.descripcion,
    gravedad: gravedadDe('lactato'),
    parametros: ['lactato'],
  });

  if (esBajo('ca_ion')) agregar({
    nombre: alt.ca_ionizado_bajo.nombre,
    descripcion: alt.ca_ionizado_bajo.descripcion,
    gravedad: gravedadDe('ca_ion'),
    parametros: ['ca_ion'],
  });

  if (esAlto('ca_ion')) agregar({
    nombre: alt.ca_ionizado_alto.nombre,
    descripcion: alt.ca_ionizado_alto.descripcion,
    gravedad: gravedadDe('ca_ion'),
    parametros: ['ca_ion'],
  });

  if (esAlto('anion_gap')) agregar({
    nombre: alt.anion_gap_elevado.nombre,
    descripcion: alt.anion_gap_elevado.descripcion,
    gravedad: gravedadDe('anion_gap'),
    parametros: ['anion_gap', ...(presente('lactato') ? ['lactato'] : [])].filter(presente),
  });

  return patrones;
};

// Exportación principal

export const analizarResultados = (
  valoresInput: ValoresFormulario,
  paciente: Paciente,
  referencias: Referencias,
  alteraciones: Alteraciones,
): ResultadoAnalisis => {
  const especie = paciente.especie;
  const refsEspecie = especie ? referencias[especie] : undefined;
  if (!refsEspecie || !especie) return { hallazgos: [], patrones: [] };

  // Ajusta los rangos segun edad, raza y sexo antes de comparar
  const refsAjustadas = ajustarReferencias(refsEspecie, paciente);
  const hallazgos: Hallazgo[] = [];

  for (const [clave, ref] of Object.entries(refsAjustadas)) {
    const crudo = valoresInput[clave];
    if (crudo === null || crudo === undefined || crudo === '') continue;

    const valorNum = typeof crudo === 'number' ? crudo : parseFloat(crudo);
    if (isNaN(valorNum)) continue;

    if (valorNum > ref.superior) {
      hallazgos.push({
        clave, nombre: ref.nombre, valor: valorNum, unidad: ref.unidad,
        direccion: 'alto', gravedad: clasificarGravedad(valorNum, ref, clave, especie),
      });
    } else if (valorNum < ref.inferior) {
      hallazgos.push({
        clave, nombre: ref.nombre, valor: valorNum, unidad: ref.unidad,
        direccion: 'bajo', gravedad: clasificarGravedad(valorNum, ref, clave, especie),
      });
    }
  }

  return { hallazgos, patrones: detectarPatrones(hallazgos, especie, alteraciones) };
};

// Exportado para pruebas unitarias del cálculo de gravedad de forma aislada.
export const _internos = { clasificarGravedad, categorizarEdad, ajustarReferencias };
