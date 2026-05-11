
// Gravedad
// La desviación se mide en múltiplos del ancho del rango de referencia.
// Ej: rango WBC 6-17 (ancho = 11). WBC = 28 → desviación = 11/11 = 1.0 → moderado.

const UMBRALES_GRAVEDAD = { leve: 0.5, moderado: 1.5 };

const clasificarGravedad = (valor, ref) => {
    const rango = ref.superior - ref.inferior;
    const desviacion = valor > ref.superior
        ? (valor - ref.superior) / rango
        : (ref.inferior - valor) / rango;

    if (desviacion <= UMBRALES_GRAVEDAD.leve) return 'leve';
    if (desviacion <= UMBRALES_GRAVEDAD.moderado) return 'moderado';
    return 'grave';
};

// Edad

const categorizarEdad = (edadMeses, especie) => {
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


// Ajustes por edad

const AJUSTES_EDAD = {
    canino: {
        cachorro: { fal: { superior: 3.0 }, wbc: { superior: 1.25 } },
        adulto: {},
        senior: { bun: { superior: 1.15 }, creat: { superior: 1.15 } },
        geriatrico: { bun: { superior: 1.25 }, creat: { superior: 1.25 }, fal: { superior: 1.40 } }
    },
    felino: {
        cachorro: { fal: { superior: 2.0 }, wbc: { superior: 1.20 } },
        adulto: {},
        senior: { bun: { superior: 1.20 }, creat: { superior: 1.20 } }
    }
};

// Ajustes por raza

const AJUSTES_RAZA = {
    canino: [
        {
            razas: ['galgo', 'greyhound', 'whippet', 'lebrel'],
            ajustes: {
                rbc: { inferior: 1.15, superior: 1.15 },
                hgb: { inferior: 1.12, superior: 1.12 },
                hct: { inferior: 1.12, superior: 1.12 },
                plt: { inferior: 0.75, superior: 0.75 }
            }
        },
        {
            razas: ['shiba', 'akita'],
            ajustes: {
                rbc: { inferior: 1.10, superior: 1.10 },
                hct: { inferior: 1.08, superior: 1.08 },
                hgb: { inferior: 1.08, superior: 1.08 }
            }
        }
    ]
};


// Ajustes por sexo

const AJUSTES_SEXO = {
    felino: {
        Macho: { creat: { superior: 1.15 } }
    }
};

const obtenerAjustesRaza = (raza, especie) => {
    const razaNorm = raza?.toLowerCase().trim() ?? '';
    const grupos = AJUSTES_RAZA[especie] ?? [];
    return grupos.find(g => g.razas.some(r => razaNorm.includes(r)))?.ajustes ?? {};
};

// Ajuste de referencias

const ajustarReferencias = (refsEspecie, paciente) => {
    const catEdad = categorizarEdad(paciente.edadMeses, paciente.especie);
    const ajEdad = AJUSTES_EDAD[paciente.especie]?.[catEdad] ?? {};
    const ajRaza = obtenerAjustesRaza(paciente.raza, paciente.especie);
    const ajSexo = AJUSTES_SEXO[paciente.especie]?.[paciente.sexo] ?? {};

    return Object.entries(refsEspecie).reduce((acc, [clave, ref]) => {
        const factorEdad = ajEdad[clave] ?? {};
        const factorRaza = ajRaza[clave] ?? {};
        const factorSexo = ajSexo[clave] ?? {};

        acc[clave] = {
            ...ref,
            inferior: ref.inferior * (factorEdad.inferior ?? 1) * (factorRaza.inferior ?? 1) * (factorSexo.inferior ?? 1),
            superior: ref.superior * (factorEdad.superior ?? 1) * (factorRaza.superior ?? 1) * (factorSexo.superior ?? 1)
        };
        return acc;
    }, {});
};

// Detección de patrones clínicos

const detectarPatrones = (hallazgos, especie, alt) => {
    const mapa = hallazgos.reduce((acc, h) => { acc[h.clave] = h; return acc; }, {});

    const esAlto = (clave) => mapa[clave]?.direccion === 'alto';
    const esBajo = (clave) => mapa[clave]?.direccion === 'bajo';
    const presente = (clave) => clave in mapa;
    const valor = (clave) => mapa[clave]?.valor ?? null;

    const gravedadDe = (...claves) => {
        const clave = claves.find(c => mapa[c]);
        return mapa[clave]?.gravedad ?? 'leve';
    };

    const patrones = [];
    const agregar = (patron) => patrones.push(patron);

    // Serie roja

    if (esBajo('hct') || esBajo('hgb') || esBajo('rbc')) {
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
            parametros: ['hct', 'hgb', 'rbc', 'vcm'].filter(presente)
        });
    }

    if (esAlto('hct') || esAlto('rbc')) agregar({
        nombre: alt.eritrocitosis.nombre,
        descripcion: alt.eritrocitosis.descripcion,
        gravedad: gravedadDe('hct', 'rbc'),
        parametros: ['hct', 'rbc', 'hgb'].filter(presente)
    });

    // Serie blanca

    if (esAlto('wbc')) {
        const neutrofilia = esAlto('neutro');
        const linfocitosis = esAlto('linfo');

        if (neutrofilia) agregar({
            nombre: alt.leucocitosis_neutrofilica.nombre,
            descripcion: alt.leucocitosis_neutrofilica.descripcion,
            gravedad: gravedadDe('wbc', 'neutro'),
            parametros: ['wbc', 'neutro'].filter(presente)
        });

        if (linfocitosis) agregar({
            nombre: alt.leucocitosis_linfocitica.nombre,
            descripcion: alt.leucocitosis_linfocitica.descripcion,
            gravedad: gravedadDe('wbc', 'linfo'),
            parametros: ['wbc', 'linfo'].filter(presente)
        });

        if (!neutrofilia && !linfocitosis) agregar({
            nombre: alt.leucocitosis.nombre,
            descripcion: alt.leucocitosis.descripcion,
            gravedad: gravedadDe('wbc'),
            parametros: ['wbc']
        });
    }

    if (esBajo('wbc')) agregar({
        nombre: alt.leucopenia.nombre,
        descripcion: alt.leucopenia.descripcion,
        gravedad: gravedadDe('wbc'),
        parametros: ['wbc']
    });

    if (esBajo('neutro')) agregar({
        nombre: alt.neutropenia.nombre,
        descripcion: alt.neutropenia.descripcion,
        gravedad: gravedadDe('neutro'),
        parametros: ['neutro']
    });

    if (esBajo('linfo')) agregar({
        nombre: alt.linfopenia.nombre,
        descripcion: alt.linfopenia.descripcion,
        gravedad: gravedadDe('linfo'),
        parametros: ['linfo']
    });

    if (esAlto('eosino')) agregar({
        nombre: alt.eosinofilia.nombre,
        descripcion: alt.eosinofilia.descripcion,
        gravedad: gravedadDe('eosino'),
        parametros: ['eosino']
    });


    // Plaquetas

    if (esBajo('plt')) agregar({
        nombre: alt.trombocitopenia.nombre,
        descripcion: alt.trombocitopenia.descripcion,
        gravedad: gravedadDe('plt'),
        parametros: ['plt']
    });

    if (esAlto('plt')) agregar({
        nombre: alt.trombocitosis.nombre,
        descripcion: alt.trombocitosis.descripcion,
        gravedad: gravedadDe('plt'),
        parametros: ['plt']
    });


    // Hígado

    if (esAlto('alt') && esAlto('ast')) agregar({
        nombre: alt.dano_hepatocelular.nombre,
        descripcion: alt.dano_hepatocelular.descripcion,
        gravedad: gravedadDe('alt', 'ast'),
        parametros: ['alt', 'ast'].filter(presente)
    });
    else if (esAlto('alt')) agregar({
        nombre: alt.alt_aislada.nombre,
        descripcion: alt.alt_aislada.descripcion,
        gravedad: gravedadDe('alt'),
        parametros: ['alt']
    });

    if (esAlto('fal')) agregar({
        nombre: alt.patron_colestasico.nombre,
        descripcion: alt.patron_colestasico.descripcion[especie] ?? alt.patron_colestasico.descripcion.canino,
        gravedad: gravedadDe('fal'),
        parametros: ['fal']
    });

    if (esAlto('bili')) agregar({
        nombre: alt.hiperbilirrubinemia.nombre,
        descripcion: alt.hiperbilirrubinemia.descripcion,
        gravedad: gravedadDe('bili'),
        parametros: ['bili']
    });

    // Riñón

    if (esAlto('bun') && esAlto('creat')) agregar({
        nombre: alt.azotemia.nombre,
        descripcion: alt.azotemia.descripcion,
        gravedad: gravedadDe('creat', 'bun'),
        parametros: ['bun', 'creat'].filter(presente)
    });
    else if (esAlto('bun')) agregar({
        nombre: alt.hiperuremia_bun.nombre,
        descripcion: alt.hiperuremia_bun.descripcion,
        gravedad: gravedadDe('bun'),
        parametros: ['bun']
    });
    else if (esAlto('creat')) agregar({
        nombre: alt.creatinina_aislada.nombre,
        descripcion: alt.creatinina_aislada.descripcion,
        gravedad: gravedadDe('creat'),
        parametros: ['creat']
    });

    if (esBajo('bun')) agregar({
        nombre: alt.bun_disminuido.nombre,
        descripcion: alt.bun_disminuido.descripcion,
        gravedad: gravedadDe('bun'),
        parametros: ['bun']
    });

    // Glucosa

    if (esAlto('gluc')) agregar({
        nombre: alt.hiperglucemia.nombre,
        descripcion: alt.hiperglucemia.descripcion[especie] ?? alt.hiperglucemia.descripcion.canino,
        gravedad: gravedadDe('gluc'),
        parametros: ['gluc']
    });

    if (esBajo('gluc')) agregar({
        nombre: alt.hipoglucemia.nombre,
        descripcion: alt.hipoglucemia.descripcion,
        gravedad: gravedadDe('gluc'),
        parametros: ['gluc']
    });

    // Proteínas

    if (esAlto('prot')) agregar({
        nombre: alt.hiperproteinemia.nombre,
        descripcion: alt.hiperproteinemia.descripcion,
        gravedad: gravedadDe('prot'),
        parametros: ['prot']
    });

    if (esBajo('alb')) {
        const hipoproteinemia = esBajo('prot');
        const claveAlteracion = hipoproteinemia ? 'hipoproteinemia_hipoalbuminemia' : 'hipoalbuminemia';
        agregar({
            nombre: alt[claveAlteracion].nombre,
            descripcion: alt[claveAlteracion].descripcion,
            gravedad: gravedadDe('alb'),
            parametros: ['alb', ...(hipoproteinemia ? ['prot'] : [])].filter(presente)
        });
    }

    // Electrolitos

    const valSodio = valor('sodio');
    const valPotasio = valor('potasio');

    if (valSodio !== null && valPotasio !== null && valPotasio > 0) {
        const ratioNaK = valSodio / valPotasio;
        if (ratioNaK < 27) agregar({
            nombre: alt.ratio_nak.nombre,
            descripcion: alt.ratio_nak.descripcion.replace('{ratio}', ratioNaK.toFixed(1)),
            gravedad: ratioNaK < 20 ? 'grave' : ratioNaK < 24 ? 'moderado' : 'leve',
            parametros: ['sodio', 'potasio'].filter(presente)
        });
    }

    if (esAlto('sodio')) agregar({
        nombre: alt.hipernatremia.nombre,
        descripcion: alt.hipernatremia.descripcion,
        gravedad: gravedadDe('sodio'),
        parametros: ['sodio']
    });

    if (esBajo('sodio')) agregar({
        nombre: alt.hiponatremia.nombre,
        descripcion: alt.hiponatremia.descripcion,
        gravedad: gravedadDe('sodio'),
        parametros: ['sodio']
    });

    if (esAlto('calc')) agregar({
        nombre: alt.hipercalcemia.nombre,
        descripcion: alt.hipercalcemia.descripcion,
        gravedad: gravedadDe('calc'),
        parametros: ['calc']
    });

    if (esBajo('calc')) agregar({
        nombre: alt.hipocalcemia.nombre,
        descripcion: alt.hipocalcemia.descripcion,
        gravedad: gravedadDe('calc'),
        parametros: ['calc']
    });

    if (esBajo('potasio')) agregar({
        nombre: alt.hipopotasemia.nombre,
        descripcion: alt.hipopotasemia.descripcion,
        gravedad: gravedadDe('potasio'),
        parametros: ['potasio']
    });

    if (esAlto('potasio')) agregar({
        nombre: alt.hiperpotasemia.nombre,
        descripcion: alt.hiperpotasemia.descripcion,
        gravedad: gravedadDe('potasio'),
        parametros: ['potasio']
    });

    if (esAlto('fosf')) agregar({
        nombre: alt.hiperfosforemia.nombre,
        descripcion: alt.hiperfosforemia.descripcion,
        gravedad: gravedadDe('fosf'),
        parametros: ['fosf']
    });

    // Urianálisis

    const valUsg = valor('usg');
    if (valUsg !== null && valUsg < 1.008) agregar({
        nombre: alt.hiposthenuria.nombre,
        descripcion: alt.hiposthenuria.descripcion,
        gravedad: valUsg < 1.005 ? 'grave' : 'moderado',
        parametros: ['usg']
    });
    else if (valUsg !== null && valUsg < 1.013) agregar({
        nombre: alt.isosthenuria.nombre,
        descripcion: alt.isosthenuria.descripcion,
        gravedad: 'leve',
        parametros: ['usg']
    });

    // Tiroides

    if (especie === 'canino' && esBajo('t4_total')) agregar({
        nombre: alt.hipotiroidismo.nombre,
        descripcion: alt.hipotiroidismo.descripcion.canino,
        gravedad: gravedadDe('t4_total'),
        parametros: ['t4_total'].filter(presente)
    });

    if (esAlto('t4_total')) agregar({
        nombre: alt.hipertiroidismo.nombre,
        descripcion: alt.hipertiroidismo.descripcion[especie] ?? alt.hipertiroidismo.descripcion.felino,
        gravedad: gravedadDe('t4_total'),
        parametros: ['t4_total'].filter(presente)
    });

    // Suprarrenal / Cortisol

    if (esAlto('cortisol_acth')) agregar({
        nombre: alt.hiperadrenocorticismo.nombre,
        descripcion: alt.hiperadrenocorticismo.descripcion[especie] ?? alt.hiperadrenocorticismo.descripcion.canino,
        gravedad: gravedadDe('cortisol_acth'),
        parametros: ['cortisol_acth', ...(presente('cortisol_bas') ? ['cortisol_bas'] : [])]
    });

    if (esBajo('cortisol_acth')) agregar({
        nombre: alt.hipoadrenocorticismo_cortisol.nombre,
        descripcion: alt.hipoadrenocorticismo_cortisol.descripcion,
        gravedad: gravedadDe('cortisol_acth'),
        parametros: ['cortisol_acth', ...(presente('cortisol_bas') ? ['cortisol_bas'] : [])]
    });

    if (esBajo('cortisol_bas') && !presente('cortisol_acth')) agregar({
        nombre: alt.cortisol_basal_bajo.nombre,
        descripcion: alt.cortisol_basal_bajo.descripcion,
        gravedad: 'moderado',
        parametros: ['cortisol_bas']
    });

    // Insulina

    if (esBajo('insulina') && esAlto('gluc')) agregar({
        nombre: alt.deficit_insulina.nombre,
        descripcion: alt.deficit_insulina.descripcion,
        gravedad: 'moderado',
        parametros: ['insulina', 'gluc'].filter(presente)
    });

    return patrones;
};

// Exportación principal

export const analizarResultados = (valoresInput, paciente, referencias, alteraciones) => {
    const refsEspecie = referencias[paciente.especie];
    if (!refsEspecie) return { hallazgos: [], patrones: [] };

    const refsAjustadas = ajustarReferencias(refsEspecie, paciente);
    const hallazgos = [];

    for (const [clave, ref] of Object.entries(refsAjustadas)) {
        const crudo = valoresInput[clave];
        if (crudo === null || crudo === undefined || crudo === '') continue;

        const valorNum = parseFloat(crudo);
        if (isNaN(valorNum)) continue;

        if (valorNum > ref.superior) {
            hallazgos.push({
                clave, nombre: ref.nombre, valor: valorNum, unidad: ref.unidad,
                direccion: 'alto', gravedad: clasificarGravedad(valorNum, ref)
            });
        } else if (valorNum < ref.inferior) {
            hallazgos.push({
                clave, nombre: ref.nombre, valor: valorNum, unidad: ref.unidad,
                direccion: 'bajo', gravedad: clasificarGravedad(valorNum, ref)
            });
        }
    }

    return { hallazgos, patrones: detectarPatrones(hallazgos, paciente.especie, alteraciones) };
};
