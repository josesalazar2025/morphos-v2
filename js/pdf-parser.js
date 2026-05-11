// Extracción de texto de PDF y parseo de valores de laboratorio en el cliente (ningún dato sale del navegador)

const PDFJS_WORKER = 'assets/lib/pdfjs/pdf.worker.min.js';

// Cada entrada: nombre de campo (coincide con input[name="…"]) → regex + claveConv opcional
// claveConv → sobreescribe la clave de conversión (permite reglas distintas para el mismo campo)
const DEFS_ANALITOS = [
    // Hematología: Serie Roja
    { campo: 'rbc', re: /\b(?:eritrocit\w*|gl[oó]bulos?\s+rojos?|r\.?b\.?c\.?|eri)\b/i },
    { campo: 'hgb', re: /\b(?:hemoglobin[ao]?\w*|hgb|hb)\b(?!a\d)/i },
    { campo: 'hct', re: /\b(?:hematocrit[oo]?\w*|hct|pcv)\b/i },
    { campo: 'vcm', re: /\b(?:v\.?c\.?m\.?|m\.?c\.?v\.?|vol(?:umen)?\s+corp\w*)\b/i },
    // CHCM debe ir antes que HCM para evitar que MCH coincida con MCHC
    { campo: 'chcm', re: /\b(?:c\.?h\.?c\.?m\.?|m\.?c\.?h\.?c\.?|concentr\w+\s+hem\w+\s+corp\w*)\b/i },
    { campo: 'hcm', re: /\b(?:h\.?c\.?m\.?|m\.?c\.?h\.?)(?![cC]\.?)\b/i },
    { campo: 'rdw', re: /\b(?:r\.?d\.?w\.?(?:-cv)?|anch\w+\s+distrib\w+)\b/i },
    { campo: 'reti', re: /\b(?:reti\w*\s*%|ret\.?\s*%|ret[eé])\b/i },
    { campo: 'reti_abs', re: /\b(?:reti\w*\s*#|ret\.?\s*#)\b/i },
    { campo: 'nrbc', re: /\b(?:n\.?r\.?b\.?c\.?|eritrocit\w+\s+nucle\w+|nucleat\w+\s+r\.?b\.?c\.?|nrbc)\b/i },

    // Hematología: Serie Blanca
    { campo: 'wbc', re: /\b(?:leucocit\w*|w\.?b\.?c\.?|white\s+blood\s+cell|leu)\b/i },
    { campo: 'neutro_abs', re: /\bgran?#/i },
    // gran?(?!#) y similares: evitan coincidir con abreviaturas "GRA#"/"LYM#"/"EOS#"
    // cuando se busca la forma porcentual — éstas aparecen antes en informes
    // que listan conteos absolutos en una página y porcentajes en otra
    { campo: 'neutro', re: /\b(?:neutr[oó]fil\w*|neut\b|neu\b|gran?(?!#))\b/i },
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
    { campo: 'bili', re: /\b(?:bilirrub\w*|bilirubin\w*|bili\b)\b/i },   // alternativa si no hubo coincidencia previa
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
    { campo: 'ck', re: /\b(?:c\.?k\.?\b|creatina?\s+kinas[ae]|creatine\s+kinas[ae])\b/i },

    // Perfil Endocrino
    { campo: 'cortisol_bas', re: /\b(?:cortisol\s+bas[ae]?l?)\b/i },
    { campo: 'cortisol_acth', re: /\b(?:cortisol\s+(?:post[-\s]?acth|post)\b)/i },
    { campo: 't4_total', re: /\b(?:t4\s+total|t4\s+libre|tiroxin\w*|thyroxin\w*)\b/i },
    { campo: 'insulina', re: /\b(?:insulin[ao]?\w*)\b/i },

    // Urianálisis
    { campo: 'usg', re: /\b(?:usg\b|densidad\s+(?:urin|orin)\w*|gravedad\s+esp\w*)\b/i },
    { campo: 'ph', re: /\b(?:ph\s+(?:urin|orin)\w*|ph\s+orina)\b/i },
];

// Campos select semicuantitativos
const DEFS_SEMICUANTITATIVOS = [
    { campo: 'uri-prot', re: /\b(?:prote[íi]nas?\s*(?:en\s*orina?|urin\w*)?|proteinuria)\b/i },
    { campo: 'uri-gluc', re: /\b(?:glucosuria\b|glucosa\s+(?:en\s*)?orina\w*)\b/i },
];

// Reglas de conversión de unidades por campo (o claveConv).
// Cada regla: { re → se evalúa contra los ~50 caracteres tras el valor, factor → número o fn(v)=>v }
// Gana la primera coincidencia. Sin coincidencia = valor usado tal cual (se asume unidad nativa de la app).
//
// Unidades de referencia de la app:
//   rbc x10⁶/μL | hgb g/dL | hct % | vcm fL | chcm g/dL | hcm pg | rdw %
//   wbc x10³/μL | plt x10³/μL | mpv fL | pct %
//   reti % | reti_abs x10³/μL | nrbc /100WBC
//   alt/ast/fal/ggt/lipasa/ck U/L
//   bun mg/dL | creat mg/dL | sdma μg/dL
//   gluc mg/dL | prot/alb/glob g/dL | bili/bili_dir mg/dL | fosf mg/dL | calc mg/dL
//   fruc μmol/L | acidos_bil μmol/L
//   sodio/potasio/cloro/tco2 mEq/L | colest/trigli mg/dL
//   cortisol μg/dL | t4_total nmol/L | insulina μIU/mL
const CONVERSIONES_UNIDADES = {
    hgb: [
        { re: /\bg\/L\b/i, factor: v => v / 10 },
        { re: /\bmmol\/L\b/i, factor: v => v * 1.6113 },
    ],
    hct: [
        { re: /\bL\/L\b/i, factor: v => v < 1.5 ? v * 100 : v },
    ],
    chcm: [
        { re: /\bg\/L\b/i, factor: v => v / 10 },
        { re: /\bmmol\/L\b/i, factor: v => v * 0.6206 },
    ],
    pct: [
        { re: /\bL\/L\b/i, factor: v => v < 1.5 ? v * 100 : v },
    ],
    wbc: [
        // "/μL" sin prefijo ×10³ = conteo absoluto → dividir entre 1000
        { re: /^[\s]*\/[μuµ]?[Ll]\b/, factor: v => v > 100 ? v / 1000 : v },
    ],
    plt: [
        { re: /^[\s]*\/[μuµ]?[Ll]\b/, factor: v => v > 1000 ? v / 1000 : v },
    ],
    // claveConv "bun": etiquetado como BUN o nitrógeno ureico → ya es fracción nitrogenada
    bun: [
        { re: /\bmmol\/L\b/i, factor: v => v * 2.8 },
    ],
    // claveConv "urea": etiquetado como "Urea" → puede ser urea total, no fracción nitrogenada
    urea: [
        { re: /\bmmol\/L\b/i, factor: v => v * 2.8 },
        { re: /\bmg\/dL\b/i, factor: v => v * 0.467 },  // urea total → BUN
    ],
    creat: [
        { re: /\b[μuµ]mol\/L\b/i, factor: v => v / 88.4 },
    ],
    sdma: [
        { re: /\bnmol\/L\b/i, factor: v => v / 5.899 },
        { re: /\b[μuµ]g\/L\b/i, factor: v => v / 10 },
    ],
    gluc: [
        { re: /\bmmol\/L\b/i, factor: v => v * 18.016 },
    ],
    prot: [
        { re: /\bg\/L\b/i, factor: v => v / 10 },
    ],
    alb: [
        { re: /\bg\/L\b/i, factor: v => v / 10 },
    ],
    glob: [
        { re: /\bg\/L\b/i, factor: v => v / 10 },
    ],
    bili: [
        { re: /\b[μuµ]mol\/L\b/i, factor: v => v / 17.1 },
    ],
    bili_dir: [
        { re: /\b[μuµ]mol\/L\b/i, factor: v => v / 17.1 },
    ],
    fosf: [
        { re: /\bmmol\/L\b/i, factor: v => v * 3.097 },
    ],
    calc: [
        { re: /\bmmol\/L\b/i, factor: v => v * 4.008 },
        { re: /\bm[Ee]q\/L\b/, factor: v => v * 2.004 },
    ],
    colest: [
        { re: /\bmmol\/L\b/i, factor: v => v * 38.67 },
    ],
    trigli: [
        { re: /\bmmol\/L\b/i, factor: v => v * 88.57 },
    ],
    cortisol_bas: [
        { re: /\bnmol\/L\b/i, factor: v => v / 27.59 },
    ],
    cortisol_acth: [
        { re: /\bnmol\/L\b/i, factor: v => v / 27.59 },
    ],
    t4_total: [
        // Unidad de la app: nmol/L
        { re: /\b[μuµ]g\/dL\b/i, factor: v => v * 12.87 },
        { re: /\bng\/dL\b/i, factor: v => v * 0.01287 },
        { re: /\bng\/mL\b/i, factor: v => v * 0.1287 },
    ],
    insulina: [
        { re: /\bpmol\/L\b/i, factor: v => v / 6.945 },
    ],
};

function aplicarConversion(campo, claveConv, value, cadenaUnidad) {
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

// Retorna { num, unit } donde unit es la cadena de ~50 caracteres tras el valor numérico.
// Las reglas de conversión evalúan su regex contra esta cadena.
function extraerValorYUnidad(contexto) {
    const m = contexto.match(/[<>≤≥]?\s*(\d+(?:[.,]\d+)?)([\s\S]*)/);
    if (!m) return { num: null, unit: '' };
    const v = parseFloat(m[1].replace(',', '.'));
    if (!isFinite(v) || v <= 0) return { num: null, unit: '' };
    return { num: v, unit: m[2].slice(0, 50) };
}

function parsearSemiCuantitativo(text) {
    const t = text.toLowerCase();
    if (/negati|nég|neg\b|ausente|absent|no\s+detect/.test(t)) return 'neg';
    if (/\+{3}/.test(t)) return '+++';
    if (/\+{2}/.test(t)) return '++';
    if (/\+/.test(t)) return '+';
    if (/traz|trace/.test(t)) return '+';
    return null;
}

function parsearTextoLab(textoCrudo) {
    const resultados = {};

    for (const def of DEFS_ANALITOS) {
        if (resultados[def.campo] !== undefined) continue;
        const match = def.re.exec(textoCrudo);
        if (!match) continue;
        const contexto = textoCrudo.slice(match.index + match[0].length, match.index + match[0].length + 150);
        const { num, unit } = extraerValorYUnidad(contexto);
        if (num === null) continue;
        resultados[def.campo] = aplicarConversion(def.campo, def.claveConv, num, unit);
    }

    // Derivar % desde conteos absolutos si el % no se encontró directamente y se conoce el WBC
    if (resultados.wbc && resultados.wbc > 0) {
        for (const f of ['neutro', 'linfo', 'mono', 'eosino', 'baso']) {
            if (resultados[f] === undefined && resultados[`${f}_abs`] !== undefined) {
                const pct = Math.round((resultados[`${f}_abs`] / resultados.wbc) * 100);
                if (pct >= 0 && pct <= 100) resultados[f] = pct;
            }
        }
    }

    // Derivar % de reticulocitos desde el conteo absoluto y RBC si no se encontró directamente
    // reti_abs (x10³/μL) ÷ (rbc (x10⁶/μL) × 10) = reti%
    if (resultados.rbc && resultados.rbc > 0 && resultados.reti === undefined && resultados.reti_abs !== undefined) {
        const pct = resultados.reti_abs / (resultados.rbc * 10);
        if (pct >= 0 && pct <= 20) resultados.reti = Math.round(pct * 100) / 100;
    }

    for (const def of DEFS_SEMICUANTITATIVOS) {
        if (resultados[def.campo] !== undefined) continue;
        const match = def.re.exec(textoCrudo);
        if (!match) continue;
        const contexto = textoCrudo.slice(match.index, match.index + 80);
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

// Palabras clave de etiqueta que marcan el inicio de un nuevo campo (para detener la captura de raza)
const SIGUIENTE_ETIQUETA = /\b(?:edad|age|sexo|sex|g[eé]nero|gender|especie|species|dueño|owner|propietario|doctor|vet|fecha|date|n[uú]m|caso|case|id|muestra|sample|peso|weight)\b/i;

function inferEspecie(raza) {
    const r = raza.toLowerCase();
    if (RAZAS_CANINO.some(b => r.includes(b))) return 'Canino';
    if (RAZAS_FELINO.some(b => r.includes(b))) return 'Felino';
    return null;
}

function parsearTextoPaciente(textoCrudo) {
    const p = {};

    // Especie — "Especie: Canino" / "Species: Dog" / "Tipo: Felino"
    const coincEsp = textoCrudo.match(/\b(?:especies?|species|tipo(?:\s+de)?\s+animal)\s*:?\s{0,4}([A-Za-záéíóúÁÉÍÓÚñÑ]{3,20})/i);
    if (coincEsp) {
        const v = coincEsp[1].toLowerCase();
        if (/can[io]|perro|dog/.test(v)) p.especie = 'Canino';
        else if (/fel[io]|gat[ao]|cat/.test(v)) p.especie = 'Felino';
    }

    // Raza — "Raza: Labrador Retriever" / "Breed: Mixed"
    const coincRaza = textoCrudo.match(/\b(?:raza|breed|race|cruce)\s*:?\s{0,4}([^\n\r;:]{2,60})/i);
    if (coincRaza) {
        const crudo = coincRaza[1];
        // Detener en la siguiente palabra clave de etiqueta o 2+ espacios consecutivos (diseño tabular)
        const indiceParo = crudo.search(SIGUIENTE_ETIQUETA);
        const limpiado = (indiceParo > 0 ? crudo.slice(0, indiceParo) : crudo)
            .split(/\s{2,}/)[0]
            .trim();
        if (limpiado.length >= 2) p.raza = limpiado.length > 40 ? limpiado.slice(0, 40).trim() : limpiado;
    }

    if (!p.especie && p.raza) p.especie = inferEspecie(p.raza);

    // Sexo — "Sexo: Macho" / "Sex: F" / "Género: Hembra Esterilizada"
    const coincSex = textoCrudo.match(/\b(?:sexo|sex[ou]?|g[eé]nero|gender)\s*:?\s{0,4}([^\n\r;:]{1,30})/i);
    if (coincSex) {
        const v = coincSex[1].trim();
        if (/\b(?:macho|male|castrado|neutered)\b/i.test(v) || /^m\.?\s*$/i.test(v)) p.sexo = 'Macho';
        else if (/\b(?:hembra|female|esterilizada?|spayed)\b/i.test(v) || /^[fh]\.?\s*$/i.test(v)) p.sexo = 'Hembra';
    }

    // Edad — "Edad: 5 años" / "Age: 6 months" / "Edad: 2.5 años"
    const coincEdad = textoCrudo.match(/\b(?:edad|age)\s*:?\s{0,4}(\d+(?:[.,]\d+)?)\s*(a[ñn]os?|years?|yr?s?|meses?|months?)\b/i);
    if (coincEdad) {
        p.edad = parseFloat(coincEdad[1].replace(',', '.'));
        p.edadUnidad = /^m/i.test(coincEdad[2]) ? 'meses' : 'anyos';
    }

    return p;
}

function aplicarPacienteAFormulario(patient) {
    const MAPA = [
        { id: 'pt-especie', mobId: 'mob-pt-especie', key: 'especie', evt: 'change' },
        { id: 'pt-raza', mobId: 'mob-pt-raza', key: 'raza', evt: 'input' },
        { id: 'pt-edad', mobId: 'mob-pt-edad', key: 'edad', evt: 'input' },
        { id: 'pt-edad-unidad', mobId: 'mob-pt-edad-unidad', key: 'edadUnidad', evt: 'change' },
        { id: 'pt-sexo', mobId: 'mob-pt-sexo', key: 'sexo', evt: 'change' },
    ];
    let contador = 0;
    for (const { id, mobId, key, evt } of MAPA) {
        const val = patient[key];
        if (val === undefined) continue;
        const el = document.getElementById(id);
        const mob = document.getElementById(mobId);
        if (!el) continue;
        const valorCadena = String(val);
        if (el.tagName === 'SELECT') {
            const opcion = [...el.options].find(o => o.value === valorCadena || o.text === valorCadena);
            if (!opcion) continue;
            el.value = opcion.value;
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

async function cargarPdfJs() {
    if (window.pdfjsLib) return window.pdfjsLib;
    await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'assets/lib/pdfjs/pdf.min.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
    return window.pdfjsLib;
}

async function extraerTextoPdf(file) {
    const pdfjs = await cargarPdfJs();
    if (!pdfjs) throw new Error('PDF.js no cargado');
    pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;

    const buf = await file.arrayBuffer();
    const pdf = await pdfjs.getDocument({ data: buf }).promise;
    const paginas = [];
    for (let p = 1; p <= pdf.numPages; p++) {
        const page = await pdf.getPage(p);
        const content = await page.getTextContent();
        paginas.push(content.items.map(i => i.str + (i.hasEOL ? '\n' : ' ')).join(''));
    }
    return paginas.join('\n');
}

function aplicarAFormulario(resultados, evaluar) {
    let contador = 0;
    for (const [campo, value] of Object.entries(resultados)) {
        const el = document.querySelector(`[name="${campo}"]`);
        if (!el) continue;
        if (el.tagName === 'SELECT') {
            if ([...el.options].some(o => o.value === value)) {
                el.value = value;
                contador++;
            }
        } else {
            el.value = value;
            contador++;
        }
    }
    if (contador > 0) evaluar();
    return contador;
}

function mostrarToast(mensaje, error = false) {
    let el = document.getElementById('pdf-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'pdf-toast';
        document.body.appendChild(el);
    }
    el.textContent = mensaje;
    el.className = 'pdf-toast' + (error ? ' pdf-toast--error' : '');
    el.classList.add('pdf-toast--show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('pdf-toast--show'), 3500);
}

export function inicializarParserPdf(evaluar) {
    document.querySelectorAll('.btn-importar-pdf').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            document.getElementById(`pdf-input-${btn.dataset.panel}`)?.click();
        });
    });

    document.querySelectorAll('.pdf-input').forEach(input => {
        input.addEventListener('change', async () => {
            const file = input.files[0];
            if (!file) return;
            input.value = '';
            try {
                const textoCrudo = await extraerTextoPdf(file);
                const resultados = parsearTextoLab(textoCrudo);
                const contadorLab = aplicarAFormulario(resultados, evaluar);
                const patient = parsearTextoPaciente(textoCrudo);
                const contadorPac = aplicarPacienteAFormulario(patient);
                const partes = [];
                if (contadorLab > 0) partes.push(`${contadorLab} valor${contadorLab !== 1 ? 'es' : ''}`);
                if (contadorPac > 0) partes.push('datos del paciente');
                mostrarToast(partes.length > 0
                    ? `${partes.join(' y ')} importados del PDF.`
                    : 'No se encontraron datos reconocibles en el PDF.', partes.length === 0);
            } catch {
                mostrarToast('Error al leer el PDF. ¿Es un PDF con texto (no escaneado)?', true);
            }
        });
    });
}
