// Extracción de texto de PDF y parseo de valores de laboratorio en el cliente
// (ningún dato sale del navegador). Puerto TS de js/pdf-parser.js.

import { aplicarValoresAFormulario, aplicarPacienteAFormulario, mostrarToast } from './form-inject.js';
import { manejadorAsync } from './async.js';

const PDFJS_MODULO = 'assets/lib/pdfjs/pdf.min.mjs';
const PDFJS_WORKER = 'assets/lib/pdfjs/pdf.worker.min.mjs';

interface AnalitoDef { campo: string; re: RegExp; claveConv?: string }
interface ConversionRegla { re: RegExp; factor: number | ((v: number) => number) }
type Resultados = Record<string, number | string>;

interface PdfjsLib {
  GlobalWorkerOptions: { workerSrc: string };
  getDocument(opts: { data: ArrayBuffer | Uint8Array }): { promise: Promise<PdfDoc> };
}
interface PdfDoc { numPages: number; getPage(n: number): Promise<PdfPage> }
interface PdfPage { getTextContent(): Promise<{ items: Array<{ str: string; hasEOL?: boolean }> }> }

const DEFS_ANALITOS: AnalitoDef[] = [
  // Hematología: Serie Roja
  // `hematies` es como lo etiquetan los laboratorios españoles (el texto llega ya sin acentos,
  // ver `sinAcentos`).
  { campo: 'rbc', re: /\b(?:eritrocit\w*|hematies|gl[oó]bulos?\s+rojos?|r\.?b\.?c\.?|eri)\b/i },
  { campo: 'hgb', re: /\b(?:hemoglobin[ao]?\w*|hgb|hb)\b(?!a\d)/i },
  { campo: 'hct', re: /\b(?:hematocrit[oo]?\w*|hct|pcv)\b/i },
  { campo: 'vcm', re: /\b(?:v\.?c\.?m\.?|m\.?c\.?v\.?|vol(?:umen)?\s+corp\w*)\b/i },
  // CHCM debe ir antes que HCM para evitar que MCH coincida con MCHC al usar lookahead negativo
  { campo: 'chcm', re: /\b(?:c\.?h\.?c\.?m\.?|m\.?c\.?h\.?c\.?|concentr\w+\s+hem\w+\s+corp\w*)\b/i },
  { campo: 'hcm', re: /\b(?:h\.?c\.?m\.?|m\.?c\.?h\.?)(?![cC]\.?)\b/i },
  { campo: 'rdw', re: /\b(?:r\.?d\.?w\.?(?:-cv)?|anch\w+\s+distrib\w+)\b/i },
  { campo: 'reti', re: /\b(?:reti\w*\s*%|ret\.?\s*%|ret[eé])\b/i },
  { campo: 'reti_abs', re: /\b(?:reti\w*\s*#|ret\.?\s*#)\b/i },
  { campo: 'nrbc', re: /\b(?:n\.?r\.?b\.?c\.?|eritrocit\w+\s+nucle\w+|nucleat\w+\s+r\.?b\.?c\.?|nrbc)\b/i },

  // Hematología: Serie Blanca
  { campo: 'wbc', re: /\b(?:leucocit\w*|w\.?b\.?c\.?|white\s+blood\s+cell|leu)\b/i },
  { campo: 'neutro_abs', re: /\bgran?#/i },
  // «SEGMENTADOS» es como los informes españoles nombran a los neutrófilos maduros; sin él la
  // fórmula leucocitaria de esos informes se importaba sin neutrófilos, que es el dato que más
  // pesa en la detección de inflamación.
  { campo: 'neutro', re: /\b(?:neutr[oó]fil\w*|segmentad\w*|neut\b|neu\b|gran?(?!#))\b/i },
  { campo: 'linfo_abs', re: /\blymp?#/i },
  { campo: 'linfo', re: /\b(?:linf[oa]cit\w*|lymph\w*|linf\b|lym(?!#))\b/i },
  { campo: 'mono_abs', re: /\bmon\w*#/i },
  { campo: 'mono', re: /\b(?:monocit\w*|mono\b|mon(?!#))\b/i },
  { campo: 'eosino_abs', re: /\beos\w*#/i },
  { campo: 'eosino', re: /\b(?:eosino\w*|eos(?!#))\b/i },
  { campo: 'baso_abs', re: /\bbas\w*#/i },
  { campo: 'baso', re: /\b(?:bas[oó]fil\w*|bas(?!#))\b/i },

  // Hematología: Plaquetas
  { campo: 'plt', re: /\b(?:plaqueta\w*|platelet\w*|plt\b|trc\b)\b/i },
  { campo: 'mpv', re: /\b(?:m\.?p\.?v\.?|vol(?:umen)?\s+plaquetario\s+medio)\b/i },
  { campo: 'pct', re: /\b(?:p\.?c\.?t\.?\b|plaquetocrit\w*)\b/i },

  // Bioquímica: Enzimas Hepáticas
  { campo: 'alt', re: /\b(?:alt\b|gpt\b|alanin[ao]?\s+amino\w*)\b/i },
  { campo: 'ast', re: /\b(?:ast\b|got\b|aspart\w*)\b/i },
  { campo: 'fal', re: /\b(?:fal\b|alp\b|fosfatasa\s+alcalin\w*|alkaline\s+phosph\w*)\b/i },
  { campo: 'ggt', re: /\b(?:g\.?g\.?t\.?|gamma\s*glutamil\w*|gama\s*glutamil\w*)\b/i },

  // Bioquímica: Función Hepática
  { campo: 'bili', re: /\b(?:bilirrub\w*\s+total|total\s+bilirubin\w*|tbil\b)\b/i },
  { campo: 'bili', re: /\b(?:bilirrub\w*|bilirubin\w*|bili\b)\b/i },
  { campo: 'bili_dir', re: /\b(?:bilirrub\w*\s+direct\w*|direct\w*\s+bilirubin\w*|bili\s*dir\b)\b/i },
  { campo: 'acidos_bil', re: /\b(?:[aá]cid\w*\s+biliares?|bile\s+acids?|ácidos?\s+bil\w*)\b/i },

  // Bioquímica: Función Renal
  { campo: 'bun', claveConv: 'bun', re: /\b(?:bun\b|nitr[oó]geno\s+ureico)\b/i },
  { campo: 'bun', claveConv: 'urea', re: /\burea\b/i },
  { campo: 'creat', re: /\b(?:creatinin[ao]?\w*|crea\b)\b/i },
  { campo: 'sdma', re: /\b(?:sdma\b|dimetilargin\w*|symmetric\s+dime\w*)\b/i },

  // Bioquímica: Metabolitos
  { campo: 'gluc', re: /\b(?:gluco(?:sa|se)\b|glucemia\b|glu\b)\b/i },
  { campo: 'prot', re: /\b(?:prote[íi]nas?\s+totales?|prot\s+total|tp)\b/i },
  { campo: 'alb', re: /\b(?:alb[úu]min[ao]?\w*|alb\b)\b/i },
  { campo: 'glob', re: /\b(?:globulin\w*|glob\b)\b/i },
  { campo: 'fosf', re: /\b(?:f[oó]sforo\b|phosph\w*|phos\b)\b/i },
  { campo: 'calc', re: /\b(?:calcio\b|calcium\b|ca\b)\b/i },
  { campo: 'fruc', re: /\b(?:fructosamina\b|fructosamine\b|fruc\b)\b/i },

  // Bioquímica: Electrolitos
  { campo: 'sodio', re: /\b(?:sodio\b|sodium\b)\b/i },
  { campo: 'potasio', re: /\b(?:potasio\b|potassium\b)\b/i },
  { campo: 'cloro', re: /\b(?:clor[ou]\w*|chloride\w*)\b/i },
  { campo: 'tco2', re: /\b(?:tco2\b|t\.?co\.?2\b|bicarbonat\w*|co2\s+total)\b/i },

  // Bioquímica: Lípidos
  { campo: 'colest', re: /\b(?:colesterol\b|cholesterol\b|chol\b)\b/i },
  { campo: 'trigli', re: /\b(?:triglicérid\w*|triglic[eé]rid\w*|trig\b)\b/i },

  // Bioquímica: Enzimas
  { campo: 'lipasa', re: /\b(?:lipas[ae]\b|lipa\b)\b/i },
  // «CREATINKINASA», en una palabra, es como la etiquetan los informes españoles.
  { campo: 'ck', re: /\b(?:c\.?k\.?\b|creatin[ae]?\s*kinas[ae]|creatine\s+kinas[ae])\b/i },

  // Perfil Endocrino
  { campo: 'cortisol_bas', re: /\b(?:cortisol\s+bas[ae]?l?)\b/i },
  { campo: 'cortisol_acth', re: /\b(?:cortisol\s+(?:post[-\s]?acth|post)\b)/i },
  { campo: 't4_total', re: /\b(?:t4(?:\s+(?:total|libre))?|tiroxin\w*|thyroxin\w*)\b/i },
  { campo: 'insulina', re: /\b(?:insulin[ao]?\w*)\b/i },

  // Urianálisis
  { campo: 'usg', re: /\b(?:usg\b|densidad\s+(?:urin|orin)\w*|gravedad\s+esp\w*)\b/i },
  { campo: 'ph', re: /\b(?:ph\s+(?:urin|orin)\w*|ph\s+orina)\b/i },
];

// Campos select semicuantitativos
const DEFS_SEMICUANTITATIVOS: AnalitoDef[] = [
  { campo: 'uri-prot', re: /\b(?:prote[íi]nas?\s*(?:en\s*orina?|urin\w*)?|proteinuria)\b/i },
  { campo: 'uri-gluc', re: /\b(?:glucosuria\b|glucosa\s+(?:en\s*)?orina\w*)\b/i },
];

const CONVERSIONES_UNIDADES: Record<string, ConversionRegla[]> = {
  hgb: [
    { re: /\bg\/L\b/i, factor: (v) => v / 10 },
    { re: /\bmmol\/L\b/i, factor: (v) => v * 1.6113 },
  ],
  hct: [{ re: /\bL\/L\b/i, factor: (v) => (v < 1.5 ? v * 100 : v) }],
  chcm: [
    { re: /\bg\/L\b/i, factor: (v) => v / 10 },
    { re: /\bmmol\/L\b/i, factor: (v) => v * 0.6206 },
  ],
  pct: [{ re: /\bL\/L\b/i, factor: (v) => (v < 1.5 ? v * 100 : v) }],
  wbc: [{ re: /^[\s]*\/[μuµ]?[Ll]\b/, factor: (v) => (v > 100 ? v / 1000 : v) }],
  plt: [{ re: /^[\s]*\/[μuµ]?[Ll]\b/, factor: (v) => (v > 1000 ? v / 1000 : v) }],
  bun: [{ re: /\bmmol\/L\b/i, factor: (v) => v * 2.8 }],
  urea: [
    { re: /\bmmol\/L\b/i, factor: (v) => v * 2.8 },
    { re: /\bmg\/dL\b/i, factor: (v) => v * 0.467 },
  ],
  creat: [{ re: /\b[μuµ]mol\/L\b/i, factor: (v) => v / 88.4 }],
  sdma: [
    { re: /\bnmol\/L\b/i, factor: (v) => v / 5.899 },
    { re: /\b[μuµ]g\/L\b/i, factor: (v) => v / 10 },
  ],
  gluc: [{ re: /\bmmol\/L\b/i, factor: (v) => v * 18.016 }],
  prot: [{ re: /\bg\/L\b/i, factor: (v) => v / 10 }],
  alb: [{ re: /\bg\/L\b/i, factor: (v) => v / 10 }],
  glob: [{ re: /\bg\/L\b/i, factor: (v) => v / 10 }],
  bili: [{ re: /\b[μuµ]mol\/L\b/i, factor: (v) => v / 17.1 }],
  bili_dir: [{ re: /\b[μuµ]mol\/L\b/i, factor: (v) => v / 17.1 }],
  fosf: [{ re: /\bmmol\/L\b/i, factor: (v) => v * 3.097 }],
  calc: [
    { re: /\bmmol\/L\b/i, factor: (v) => v * 4.008 },
    { re: /\bm[Ee]q\/L\b/, factor: (v) => v * 2.004 },
  ],
  colest: [{ re: /\bmmol\/L\b/i, factor: (v) => v * 38.67 }],
  trigli: [{ re: /\bmmol\/L\b/i, factor: (v) => v * 88.57 }],
  cortisol_bas: [{ re: /\bnmol\/L\b/i, factor: (v) => v / 27.59 }],
  cortisol_acth: [{ re: /\bnmol\/L\b/i, factor: (v) => v / 27.59 }],
  t4_total: [
    { re: /\b[μuµ]g\/dL\b/i, factor: (v) => v * 12.87 },
    { re: /\bng\/dL\b/i, factor: (v) => v * 0.01287 },
    { re: /\bng\/mL\b/i, factor: (v) => v * 0.1287 },
  ],
  insulina: [{ re: /\bpmol\/L\b/i, factor: (v) => v / 6.945 }],
};

function aplicarConversion(campo: string, claveConv: string | undefined, value: number, cadenaUnidad: string): number {
  const key = claveConv || campo;
  const reglas = CONVERSIONES_UNIDADES[key];
  if (!reglas) return value;
  for (const regla of reglas) {
    if (regla.re.test(cadenaUnidad)) {
      const f = regla.factor;
      const convertido = typeof f === 'function' ? f(value) : value * f;
      return Math.round(convertido * 10000) / 10000;
    }
  }
  return value;
}

// Campos donde 0 es un resultado clínico legítimo y no ruido de parseo. En el resto se sigue
// descartando: un 0 suelto suele venir de una fecha o un número de página, no de una medición.
// «BASÓFILOS 0 %» es la lectura normal de un hemograma sano y se estaba tirando.
const PERMITEN_CERO = new Set([
  'neutro', 'neutro_abs', 'linfo', 'linfo_abs', 'mono', 'mono_abs',
  'eosino', 'eosino_abs', 'baso', 'baso_abs', 'reti', 'reti_abs', 'nrbc',
]);

function extraerValorYUnidad(contexto: string, campo = ''): { num: number | null; unit: string } {
  const m = contexto.match(/[<>≤≥]?\s*(\d+(?:[.,]\d+)?)([\s\S]*)/);
  if (!m) return { num: null, unit: '' };
  const v = parseFloat(m[1].replace(',', '.'));
  const minimo = PERMITEN_CERO.has(campo) ? 0 : Number.MIN_VALUE;
  if (!isFinite(v) || v < minimo) return { num: null, unit: '' };
  return { num: v, unit: m[2].slice(0, 50) };
}

function parsearSemiCuantitativo(text: string): string | null {
  const t = text.toLowerCase();
  if (/negati|nég|neg\b|ausente|absent|no\s+detect/.test(t)) return 'neg';
  if (/\+{3}/.test(t)) return '+++';
  if (/\+{2}/.test(t)) return '++';
  if (/\+/.test(t)) return '+';
  if (/traz|trace/.test(t)) return '+';
  return null;
}

// Los informes españoles escriben los analitos en mayúsculas Y acentuados (EOSINÓFILOS,
// BASÓFILOS, HEMATÍES). `\w` no cubre 'Ó', así que `eosino\w*` no casa con «EOSINÓFILOS» y toda
// la fórmula leucocitaria se perdía. Se quitan los diacríticos ANTES de buscar; las posiciones
// se conservan porque NFD + borrado de marcas no cambia el número de caracteres base.
function sinAcentos(texto: string): string {
  return texto.normalize('NFD').replace(/\p{M}/gu, '');
}

// Dónde puede estar el valor de una etiqueta. Antes era una ventana ciega de 150 caracteres, que
// se saltaba líneas y secciones enteras: medido con un informe real, «densidad urinaria» —citada
// de pasada en el párrafo interpretativo del SDMA— capturaba el resultado de la CREATINKINASA
// dos líneas más abajo e importaba una densidad urinaria de 90 en una analítica sin orina. Un
// valor equivocado es peor que un valor ausente: el que falta se ve, el que sobra se interpreta.
//
// Las dos disposiciones reales son:
//   1. En la misma línea:  `HEMATOCRITO....... 48,1 %`
//   2. Bajo una cabecera:  `CREATININA / SUERO` / `Química seca - …` / `RESULTADO....... 1,73`
// Así que se lee el resto de la línea y, si no hay número, se avanza hasta una línea RESULTADO,
// parando en cuanto aparece otra cabecera en mayúsculas (es decir, otro analito).
const MAX_LINEAS_BUSCADAS = 6;
const RE_LINEA_RESULTADO = /^\s*(?:resultado|result)\b/i;

function esCabecera(linea: string): boolean {
  const letras = linea.replace(/[^A-Za-zÁÉÍÓÚÑáéíóúñ]/g, '');
  if (letras.length < 3) return false;
  return letras === letras.toUpperCase();
}

// Se prueban TODAS las apariciones de la etiqueta, no sólo la primera, y gana la primera que
// venga acompañada de un número. Los informes nombran el analito antes de medirlo —«FÓRMULA
// LEUCOCITARIA» es el título de la sección y «LEUCOCITOS....... 7.510» el dato—, así que quedarse
// con la primera aparición perdía el valor. El orden importa: si la primera sí trae número, es la
// que se usa, igual que antes.
const MAX_APARICIONES = 5;
const globales = new Map<RegExp, RegExp>();

function comoGlobal(re: RegExp): RegExp {
  let g = globales.get(re);
  if (!g) {
    g = new RegExp(re.source, re.flags.includes('g') ? re.flags : re.flags + 'g');
    globales.set(re, g);
  }
  g.lastIndex = 0;
  return g;
}

function primerValorDe(texto: string, def: AnalitoDef): number | null {
  const re = comoGlobal(def.re);
  for (let i = 0; i < MAX_APARICIONES; i++) {
    const match = re.exec(texto);
    if (!match) return null;
    const contexto = contextoDeValor(texto, match.index + match[0].length);
    const { num, unit } = extraerValorYUnidad(contexto, def.campo);
    if (num !== null) return aplicarConversion(def.campo, def.claveConv, num, unit);
  }
  return null;
}

function contextoDeValor(texto: string, desde: number): string {
  const lineas = texto.slice(desde, desde + 600).split('\n');
  const resto = lineas[0] ?? '';
  if (/\d/.test(resto)) return resto;

  for (const linea of lineas.slice(1, MAX_LINEAS_BUSCADAS)) {
    if (RE_LINEA_RESULTADO.test(linea)) return linea;
    // Otra cabecera en mayúsculas o una línea que YA trae un número: en ambos casos lo que
    // viene después pertenece a otro analito. Sin la segunda condición, «COCIENTE ALBÚMINA /
    // GLOBULINA» se saltaba la línea `ALBUMINA... 40 g/L` y se quedaba con el RESULTADO de
    // debajo, que es el cociente A/G (1,11) y no la albúmina.
    if (esCabecera(linea) || /\d/.test(linea)) break;
  }
  return '';
}

// Exportadas para las pruebas: son puras (texto → datos) y concentran toda la lógica de
// reconocimiento, que es donde han estado los fallos.
export function parsearTextoLab(textoCrudo: string): Resultados {
  const resultados: Resultados = {};
  const texto = sinAcentos(textoCrudo);

  for (const def of DEFS_ANALITOS) {
    if (resultados[def.campo] !== undefined) continue;
    const encontrado = primerValorDe(texto, def);
    if (encontrado === null) continue;
    resultados[def.campo] = encontrado;
  }

  // Derivar % desde conteos absolutos si el % no se encontro directamente y se conoce el WBC
  const wbc = resultados.wbc;
  if (typeof wbc === 'number' && wbc > 0) {
    for (const f of ['neutro', 'linfo', 'mono', 'eosino', 'baso']) {
      const abs = resultados[`${f}_abs`];
      if (resultados[f] === undefined && typeof abs === 'number') {
        const pct = Math.round((abs / wbc) * 100);
        if (pct >= 0 && pct <= 100) resultados[f] = pct;
      }
    }
  }

  // Derivar % de reticulocitos desde el conteo absoluto y RBC si no se encontro directamente
  const rbc = resultados.rbc;
  const retiAbs = resultados.reti_abs;
  if (typeof rbc === 'number' && rbc > 0 && resultados.reti === undefined && typeof retiAbs === 'number') {
    const pct = retiAbs / (rbc * 10);
    if (pct >= 0 && pct <= 20) resultados.reti = Math.round(pct * 100) / 100;
  }

  for (const def of DEFS_SEMICUANTITATIVOS) {
    if (resultados[def.campo] !== undefined) continue;
    const match = def.re.exec(texto);
    if (!match) continue;
    const contexto = texto.slice(match.index, match.index + 80);
    const val = parsearSemiCuantitativo(contexto);
    if (val) resultados[def.campo] = val;
  }

  return resultados;
}

// Detección de información del paciente

const RAZAS_CANINO = [
  'labrador', 'golden retriever', 'golden', 'pastor alemán', 'pastor aleman', 'pastor',
  'poodle', 'caniche', 'beagle', 'bulldog', 'dachshund', 'salchicha', 'teckel',
  'husky', 'chihuahu', 'maltés', 'maltes', 'yorkshire', 'terrier', 'doberman',
  'rottweiler', 'boxer', 'bóxer', 'schnauzer', 'cocker', 'spaniel',
  'border collie', 'border', 'dálmata', 'dalmatian', 'pitbull', 'pit bull',
  'american staffordshire', 'samoyedo', 'akita', 'shiba', 'galgo', 'greyhound',
  'whippet', 'bichón', 'bichon', 'weimaraner', 'setter', 'pointer', 'vizsla',
  'basset', 'mastín', 'mastin', 'mastiff', 'bullmastiff', 'dogo', 'cane corso',
  'pomerania', 'pomeran', 'pequinés', 'pekinese', 'chow chow', 'shar pei',
  'gran danés', 'great dane', 'san bernardo', 'saint bernard', 'bernese',
  'spitz', 'pinscher', 'shih tzu', 'lhasa', 'basenji', 'rhodesian',
];

const RAZAS_FELINO = [
  'persa', 'persian', 'siamés', 'siames', 'siamese', 'bengala', 'bengal',
  'maine coon', 'ragdoll', 'abisinio', 'abyssinian', 'birmano', 'burmese',
  'angora', 'sphynx', 'esfinge', 'scottish fold', 'scottish', 'munchkin',
  'tonkinés', 'cornish rex', 'devon rex', 'noruego', 'norwegian',
  'british shorthair', 'british', 'russian blue', 'azul ruso', 'ocicat',
  'exótico', 'exotic shorthair', 'ragamuffin', 'balinés', 'balinese',
];

const SIGUIENTE_ETIQUETA = /\b(?:edad|age|sexo|sex|g[eé]nero|gender|especie|species|dueño|owner|propietario|doctor|vet|fecha|date|n[uú]m|caso|case|id|muestra|sample|peso|weight)\b/i;

interface PacientePdf { especie?: string; raza?: string; sexo?: string; edad?: number; edadUnidad?: string }

function inferEspecie(raza: string): string | null {
  const r = raza.toLowerCase();
  if (RAZAS_CANINO.some((b) => r.includes(b))) return 'Canino';
  if (RAZAS_FELINO.some((b) => r.includes(b))) return 'Felino';
  return null;
}

export function parsearTextoPaciente(textoCrudo: string): PacientePdf {
  const p: PacientePdf = {};

  const coincEsp = textoCrudo.match(/\b(?:especies?|species|tipo(?:\s+de)?\s+animal)\s*:?\s{0,4}([A-Za-záéíóúÁÉÍÓÚñÑ]{3,20})/i);
  if (coincEsp) {
    const v = coincEsp[1].toLowerCase();
    if (/can[io]|perro|dog/.test(v)) p.especie = 'Canino';
    else if (/fel[io]|gat[ao]|cat/.test(v)) p.especie = 'Felino';
  }

  // Muchos informes no rotulan «Especie:»: escriben el nombre científico o el común junto al
  // nombre del animal («EDNA / Perra, Canis lupus familiaris»). Se busca sólo si la etiqueta
  // explícita no dio nada, para que ésta siga mandando.
  if (!p.especie) {
    if (/\bcanis\s+(?:lupus\s+)?familiaris\b|\bperr[ao]\b/i.test(textoCrudo)) p.especie = 'Canino';
    else if (/\bfelis\s+(?:silvestris\s+)?catus\b|\bgat[ao]\b/i.test(textoCrudo)) p.especie = 'Felino';
  }

  // Y el sexo se deduce del mismo sitio: «Perra»/«Gata» sólo existen en femenino.
  if (/\b(?:perra|gata)\b/i.test(textoCrudo)) p.sexo = 'Hembra';

  const coincRaza = textoCrudo.match(/\b(?:raza|breed|race|cruce)\s*:?\s{0,4}([^\n\r;:]{2,60})/i);
  if (coincRaza) {
    const crudo = coincRaza[1];
    const indiceParo = crudo.search(SIGUIENTE_ETIQUETA);
    const limpiado = (indiceParo > 0 ? crudo.slice(0, indiceParo) : crudo)
      .split(/\s{2,}/)[0]
      .trim();
    if (limpiado.length >= 2) p.raza = limpiado.length > 40 ? limpiado.slice(0, 40).trim() : limpiado;
  }

  if (!p.especie && p.raza) {
    const inferida = inferEspecie(p.raza);
    if (inferida) p.especie = inferida;
  }

  const coincSex = textoCrudo.match(/\b(?:sexo|sex[ou]?|g[eé]nero|gender)\s*:?\s{0,4}([^\n\r;:]{1,30})/i);
  if (coincSex) {
    const v = coincSex[1].trim();
    if (/\b(?:macho|male|castrado|neutered)\b/i.test(v) || /^m\.?\s*$/i.test(v)) p.sexo = 'Macho';
    else if (/\b(?:hembra|female|esterilizada?|spayed)\b/i.test(v) || /^[fh]\.?\s*$/i.test(v)) p.sexo = 'Hembra';
  }

  const coincEdad = textoCrudo.match(/\b(?:edad|age)\s*:?\s{0,4}(\d+(?:[.,]\d+)?)\s*(a[ñn]os?|years?|yr?s?|meses?|months?)\b/i);
  if (coincEdad) {
    p.edad = parseFloat(coincEdad[1].replace(',', '.'));
    p.edadUnidad = /^m/i.test(coincEdad[2]) ? 'meses' : 'anyos';
  }

  return p;
}

class ErrorTextoIlegible extends Error {
  constructor() {
    super('el texto del PDF no se pudo decodificar de forma fiable');
    this.name = 'ErrorTextoIlegible';
  }
}

let pdfjsCargado: PdfjsLib | undefined;

// pdf.js 4+ se distribuye como módulo ES y ya no publica `window.pdfjsLib`, así que se carga
// con import() dinámico en vez de inyectar un <script>. Sigue siendo perezoso a propósito:
// son ~1,7 MB entre módulo y worker, y sólo hacen falta si el usuario adjunta un PDF.
//
// La versión importa. La 3.11 leía mal los CMap `ToUnicode` con destinos de UN byte —fuera de
// especificación, pero los emiten productores reales (informes de laboratorio generados con
// Ghostscript)— y devolvía cada carácter desplazado 8 bits: 'H' (0x48) salía como U+4800. El
// texto extraído no casaba con ningún analito y la importación fallaba entera. Ver
// `frontend/tests/pdf-parser.test.ts`, que fija el caso con un PDF de ese tipo.
async function cargarPdfJs(): Promise<PdfjsLib> {
  if (pdfjsCargado) return pdfjsCargado;
  // @vite-ignore: es un asset vendorizado que se resuelve en tiempo de ejecución; la build no
  // debe intentar empaquetarlo.
  const modulo = (await import(
    /* @vite-ignore */ new URL(PDFJS_MODULO, document.baseURI).href
  )) as unknown as PdfjsLib;
  modulo.GlobalWorkerOptions.workerSrc = new URL(PDFJS_WORKER, document.baseURI).href;
  pdfjsCargado = modulo;
  return modulo;
}

/** Texto que salió del extractor con los bytes descolocados (ver `cargarPdfJs`).
 *
 * No se intenta reparar aunque la transformación sea reversible sobre el papel: el extractor
 * normaliza a espacio los códigos que caen en un espacio Unicode, y '0' (0x30) desplazado es
 * U+3000 (espacio ideográfico). Los ceros se pierden ANTES de que este código vea el texto, así
 * que «reparar» convertiría una ALT de 260 U/L en 26. Vale más no importar nada que importar un
 * número equivocado en una analítica.
 */
function textoIlegible(texto: string): boolean {
  let noAscii = 0;
  let desplazados = 0;
  for (const ch of texto) {
    const c = ch.codePointAt(0) as number;
    if (c <= 0x7f) continue;
    noAscii++;
    if ((c & 0xff) === 0 && c >>> 8 >= 0x20) desplazados++;
  }
  return noAscii >= 20 && desplazados / noAscii > 0.5;
}

async function extraerTextoPdf(file: File): Promise<string> {
  const pdfjs = await cargarPdfJs();

  const buf = await file.arrayBuffer();
  const pdf = await pdfjs.getDocument({ data: buf }).promise;
  const paginas: string[] = [];
  for (let p = 1; p <= pdf.numPages; p++) {
    const page = await pdf.getPage(p);
    const content = await page.getTextContent();
    paginas.push(content.items.map((i) => i.str + (i.hasEOL ? '\n' : ' ')).join(''));
  }
  const texto = paginas.join('\n');
  if (textoIlegible(texto)) throw new ErrorTextoIlegible();
  return texto;
}

// Lee un PDF y vuelca lo que reconozca en el formulario. El PDF se parsea entero, sin importar
// desde qué panel se haya adjuntado: los valores caen en el panel al que pertenece cada analito.
async function importarPdf(file: File, evaluar: () => void): Promise<void> {
  try {
    const textoCrudo = await extraerTextoPdf(file);
    const resultados = parsearTextoLab(textoCrudo);
    const contadorLab = aplicarValoresAFormulario(resultados, evaluar);
    const patient = parsearTextoPaciente(textoCrudo);
    const contadorPac = aplicarPacienteAFormulario(patient);
    const partes: string[] = [];
    if (contadorLab > 0) partes.push(`${contadorLab} valor${contadorLab !== 1 ? 'es' : ''}`);
    if (contadorPac > 0) partes.push('datos del paciente');
    mostrarToast(partes.length > 0
      ? `${partes.join(' y ')} importados del PDF.`
      : 'No se encontraron datos reconocibles en el PDF.', partes.length === 0);
  } catch {
    mostrarToast('Error al leer el PDF. ¿Es un PDF con texto (no escaneado)?', true);
  }
}

// Arrastrar y soltar sobre un panel de exámenes. Se escucha en el <section> entero y no sólo en
// la zona vacía: una vez el panel muestra el formulario la zona desaparece, y soltar otro PDF
// encima del panel debe seguir funcionando.
function inicializarArrastre(evaluar: () => void): void {
  document.querySelectorAll<HTMLElement>('.subpanel[id^="panel-"]').forEach((panel) => {
    if (!panel.querySelector('.panel-vacio')) return;

    // `dragover` con preventDefault es lo que le dice al navegador que aquí se puede soltar;
    // sin él, el drop lo captura la ventana y navega al fichero.
    panel.addEventListener('dragover', (e) => {
      e.preventDefault();
      panel.classList.add('arrastrando');
    });
    // `dragleave` salta también al pasar sobre un hijo; sólo cuenta salir del panel de verdad.
    panel.addEventListener('dragleave', (e) => {
      if (!panel.contains((e as DragEvent).relatedTarget as Node | null)) {
        panel.classList.remove('arrastrando');
      }
    });
    panel.addEventListener('drop', manejadorAsync('Importar PDF', async (e: Event) => {
      e.preventDefault();
      panel.classList.remove('arrastrando');
      const file = (e as DragEvent).dataTransfer?.files?.[0];
      if (!file) return;
      if (file.type !== 'application/pdf' && !/\.pdf$/i.test(file.name)) {
        mostrarToast('Sólo se pueden adjuntar archivos PDF.', true);
        return;
      }
      await importarPdf(file, evaluar);
    }));
  });

  // Soltar FUERA de un panel no debe abrir el PDF sustituyendo la aplicación (con el formulario
  // a medio rellenar, eso es perder el trabajo por un gesto impreciso).
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => e.preventDefault());
}

export function inicializarParserPdf(evaluar: () => void): void {
  document.querySelectorAll<HTMLElement>('.btn-importar-pdf').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      (document.getElementById(`pdf-input-${btn.dataset.panel}`) as HTMLInputElement | null)?.click();
    });
  });

  document.querySelectorAll<HTMLInputElement>('.pdf-input').forEach((input) => {
    input.addEventListener('change', manejadorAsync('Importar PDF', async () => {
      const file = input.files?.[0];
      if (!file) return;
      input.value = '';
      await importarPdf(file, evaluar);
    }));
  });

  inicializarArrastre(evaluar);
}
