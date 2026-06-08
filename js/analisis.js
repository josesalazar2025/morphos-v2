
// Gravedad
// La desviación se mide en múltiplos del ancho del rango de referencia.
// Ej: rango WBC 6-17 (ancho = 11). WBC = 28 → desviación = 11/11 = 1.0 → moderado.

const UMBRALES_GRAVEDAD = { leve: 0.5, moderado: 1.5 };

const clasificarGravedad = (valor, ref) => {
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

    // Multiplica los limites inferiores y superiores por los factores de edad, raza y sexo
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
        // Diferencia leucocitosis neutrofilica de linfocitica; si no hay diferencial, informa generico
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

    // Ratio Na/K < 27 es sugestivo de hipoadrenocorticismo; la gravedad aumenta a menor ratio
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

    // Páncreas exocrino (PLI)

    if (esAlto('pli')) agregar({
        nombre: alt.pancreatitis.nombre,
        descripcion: alt.pancreatitis.descripcion[especie] ?? alt.pancreatitis.descripcion.canino,
        gravedad: gravedadDe('pli'),
        parametros: ['pli', ...(presente('lipasa') ? ['lipasa'] : []), ...(presente('amylasa') ? ['amylasa'] : [])].filter(presente)
    });

    if (esAlto('amylasa') && !presente('pli')) agregar({
        nombre: alt.hiperamylasemia.nombre,
        descripcion: alt.hiperamylasemia.descripcion,
        gravedad: gravedadDe('amylasa'),
        parametros: ['amylasa']
    });

    // Tiroides — TSH

    if (esAlto('tsh')) agregar({
        nombre: alt.tsh_elevado.nombre,
        descripcion: alt.tsh_elevado.descripcion[especie] ?? alt.tsh_elevado.descripcion.canino,
        gravedad: gravedadDe('tsh'),
        parametros: ['tsh', ...(presente('t4_total') ? ['t4_total'] : []), ...(presente('t4_libre') ? ['t4_libre'] : [])].filter(presente)
    });

    if (esBajo('tsh')) agregar({
        nombre: alt.tsh_suprimido.nombre,
        descripcion: alt.tsh_suprimido.descripcion[especie] ?? alt.tsh_suprimido.descripcion.canino,
        gravedad: gravedadDe('tsh'),
        parametros: ['tsh', ...(presente('t4_total') ? ['t4_total'] : [])].filter(presente)
    });

    if (esBajo('t4_libre') && !presente('tsh')) agregar({
        nombre: alt.t4_libre_baja.nombre,
        descripcion: alt.t4_libre_baja.descripcion[especie] ?? alt.t4_libre_baja.descripcion.canino,
        gravedad: gravedadDe('t4_libre'),
        parametros: ['t4_libre', ...(presente('t4_total') ? ['t4_total'] : [])].filter(presente)
    });

    // Biomarcadores cardíacos

    if (esAlto('ctni')) agregar({
        nombre: alt.dano_miocardico.nombre,
        descripcion: alt.dano_miocardico.descripcion,
        gravedad: gravedadDe('ctni'),
        parametros: ['ctni', ...(presente('nt_probnp') ? ['nt_probnp'] : [])].filter(presente)
    });

    if (esAlto('nt_probnp')) agregar({
        nombre: alt.cardiopatia_bnp.nombre,
        descripcion: alt.cardiopatia_bnp.descripcion[especie] ?? alt.cardiopatia_bnp.descripcion.canino,
        gravedad: gravedadDe('nt_probnp'),
        parametros: ['nt_probnp', ...(presente('ctni') ? ['ctni'] : [])].filter(presente)
    });

    // Proteínas de fase aguda

    if (esAlto('crp') || esAlto('saa')) agregar({
        nombre: alt.inflamacion_aguda.nombre,
        descripcion: alt.inflamacion_aguda.descripcion[especie] ?? alt.inflamacion_aguda.descripcion.canino,
        gravedad: gravedadDe('crp', 'saa'),
        parametros: ['crp', 'saa'].filter(presente)
    });

    // Progesterona

    if (esAlto('progesterona')) agregar({
        nombre: alt.progesterona_elevada.nombre,
        descripcion: alt.progesterona_elevada.descripcion[especie] ?? alt.progesterona_elevada.descripcion.canino,
        gravedad: gravedadDe('progesterona'),
        parametros: ['progesterona']
    });

    // Magnesio

    if (esBajo('magnesio')) agregar({
        nombre: alt.hipomagnesemia.nombre,
        descripcion: alt.hipomagnesemia.descripcion,
        gravedad: gravedadDe('magnesio'),
        parametros: ['magnesio']
    });

    if (esAlto('magnesio')) agregar({
        nombre: alt.hipermagnesemia.nombre,
        descripcion: alt.hipermagnesemia.descripcion,
        gravedad: gravedadDe('magnesio'),
        parametros: ['magnesio']
    });

    // Hierro

    if (esBajo('hierro')) agregar({
        nombre: alt.ferropenia_hierro.nombre,
        descripcion: alt.ferropenia_hierro.descripcion,
        gravedad: gravedadDe('hierro'),
        parametros: ['hierro']
    });

    // Ácido úrico

    if (esAlto('ac_urico')) agregar({
        nombre: alt.ac_urico_elevado.nombre,
        descripcion: alt.ac_urico_elevado.descripcion,
        gravedad: gravedadDe('ac_urico'),
        parametros: ['ac_urico']
    });

    // LDH

    if (esAlto('ldh')) agregar({
        nombre: alt.ldh_elevada.nombre,
        descripcion: alt.ldh_elevada.descripcion,
        gravedad: gravedadDe('ldh'),
        parametros: ['ldh']
    });

    // Monitorización de fármacos (TDM)

    if (esBajo('fenobarbital')) agregar({
        nombre: alt.fenobarbital_subterapeutico.nombre,
        descripcion: alt.fenobarbital_subterapeutico.descripcion,
        gravedad: gravedadDe('fenobarbital'),
        parametros: ['fenobarbital']
    });

    if (esAlto('fenobarbital')) agregar({
        nombre: alt.fenobarbital_toxico.nombre,
        descripcion: alt.fenobarbital_toxico.descripcion,
        gravedad: gravedadDe('fenobarbital'),
        parametros: ['fenobarbital']
    });

    if (esBajo('ciclosporina')) agregar({
        nombre: alt.ciclosporina_subterapeutica.nombre,
        descripcion: alt.ciclosporina_subterapeutica.descripcion,
        gravedad: gravedadDe('ciclosporina'),
        parametros: ['ciclosporina']
    });

    if (esAlto('ciclosporina')) agregar({
        nombre: alt.ciclosporina_toxica.nombre,
        descripcion: alt.ciclosporina_toxica.descripcion,
        gravedad: gravedadDe('ciclosporina'),
        parametros: ['ciclosporina']
    });

    // Coagulación

    if (esAlto('pt') && !esAlto('aptt')) agregar({
        nombre: alt.coagulopatia_extrinseca.nombre,
        descripcion: alt.coagulopatia_extrinseca.descripcion,
        gravedad: gravedadDe('pt'),
        parametros: ['pt']
    });

    if (esAlto('aptt') && !esAlto('pt')) agregar({
        nombre: alt.coagulopatia_intrinseca.nombre,
        descripcion: alt.coagulopatia_intrinseca.descripcion,
        gravedad: gravedadDe('aptt'),
        parametros: ['aptt']
    });

    if (esAlto('pt') && esAlto('aptt')) agregar({
        nombre: alt.coagulopatia_mixta.nombre,
        descripcion: alt.coagulopatia_mixta.descripcion,
        gravedad: gravedadDe('pt', 'aptt', 'act'),
        parametros: ['pt', 'aptt', ...(presente('act') ? ['act'] : [])].filter(presente)
    });

    if ((esAlto('ddimeros') || esAlto('fdp')) && esBajo('fibrinogeno')) agregar({
        nombre: alt.cid.nombre,
        descripcion: alt.cid.descripcion,
        gravedad: 'grave',
        parametros: ['ddimeros', 'fdp', 'fibrinogeno', 'plt'].filter(presente)
    });

    if (esAlto('fibrinogeno') && !esAlto('ddimeros') && !esAlto('fdp')) agregar({
        nombre: alt.hiperfibrinogenemia.nombre,
        descripcion: alt.hiperfibrinogenemia.descripcion,
        gravedad: gravedadDe('fibrinogeno'),
        parametros: ['fibrinogeno']
    });

    if (esBajo('fibrinogeno') && !esAlto('ddimeros') && !esAlto('fdp')) agregar({
        nombre: alt.hipofibrinogenemia.nombre,
        descripcion: alt.hipofibrinogenemia.descripcion,
        gravedad: gravedadDe('fibrinogeno'),
        parametros: ['fibrinogeno']
    });

    if (esBajo('vwf')) agregar({
        nombre: alt.deficit_vwf.nombre,
        descripcion: alt.deficit_vwf.descripcion,
        gravedad: gravedadDe('vwf'),
        parametros: ['vwf', ...(presente('aptt') ? ['aptt'] : [])].filter(presente)
    });

    if (esBajo('antitrombina')) agregar({
        nombre: alt.antitrombina_baja.nombre,
        descripcion: alt.antitrombina_baja.descripcion,
        gravedad: gravedadDe('antitrombina'),
        parametros: ['antitrombina']
    });

    // Urianálisis — sedimento / UPC

    if (esAlto('rbc_uri')) agregar({
        nombre: alt.hematuria_uri.nombre,
        descripcion: alt.hematuria_uri.descripcion,
        gravedad: gravedadDe('rbc_uri'),
        parametros: ['rbc_uri']
    });

    if (esAlto('wbc_uri')) agregar({
        nombre: alt.piuria.nombre,
        descripcion: alt.piuria.descripcion,
        gravedad: gravedadDe('wbc_uri'),
        parametros: ['wbc_uri']
    });

    if (esAlto('upc')) agregar({
        nombre: alt.proteinuria_upc.nombre,
        descripcion: alt.proteinuria_upc.descripcion,
        gravedad: gravedadDe('upc'),
        parametros: ['upc']
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
                    parametros: ['ph_sangre', 'pco2', 'hco3', 'exceso_base'].filter(presente)
                });
            } else if (hipercarbia) {
                agregar({
                    nombre: alt.acidosis_respiratoria.nombre,
                    descripcion: alt.acidosis_respiratoria.descripcion,
                    gravedad: gravedadDe('ph_sangre', 'pco2'),
                    parametros: ['ph_sangre', 'pco2'].filter(presente)
                });
            } else if (componenteAcidMet) {
                agregar({
                    nombre: alt.acidosis_metabolica.nombre,
                    descripcion: alt.acidosis_metabolica.descripcion,
                    gravedad: gravedadDe('ph_sangre', 'hco3', 'exceso_base'),
                    parametros: ['ph_sangre', 'hco3', 'exceso_base', 'anion_gap'].filter(presente)
                });
            }
        }

        if (phAlto) {
            if (hipocarbia && componenteAlcalMet) {
                agregar({
                    nombre: alt.alcalosis_respiratoria.nombre + ' + ' + alt.alcalosis_metabolica.nombre,
                    descripcion: alt.alcalosis_metabolica.descripcion,
                    gravedad: 'grave',
                    parametros: ['ph_sangre', 'pco2', 'hco3', 'exceso_base'].filter(presente)
                });
            } else if (hipocarbia) {
                agregar({
                    nombre: alt.alcalosis_respiratoria.nombre,
                    descripcion: alt.alcalosis_respiratoria.descripcion,
                    gravedad: gravedadDe('ph_sangre', 'pco2'),
                    parametros: ['ph_sangre', 'pco2'].filter(presente)
                });
            } else if (componenteAlcalMet) {
                agregar({
                    nombre: alt.alcalosis_metabolica.nombre,
                    descripcion: alt.alcalosis_metabolica.descripcion,
                    gravedad: gravedadDe('ph_sangre', 'hco3', 'exceso_base'),
                    parametros: ['ph_sangre', 'hco3', 'exceso_base'].filter(presente)
                });
            }
        }
    }

    if (esBajo('po2')) agregar({
        nombre: alt.hipoxemia.nombre,
        descripcion: alt.hipoxemia.descripcion,
        gravedad: gravedadDe('po2', 'so2'),
        parametros: ['po2', ...(presente('so2') ? ['so2'] : [])].filter(presente)
    });

    if (esAlto('lactato')) agregar({
        nombre: alt.hiperlactatemia.nombre,
        descripcion: alt.hiperlactatemia.descripcion,
        gravedad: gravedadDe('lactato'),
        parametros: ['lactato']
    });

    if (esBajo('ca_ion')) agregar({
        nombre: alt.ca_ionizado_bajo.nombre,
        descripcion: alt.ca_ionizado_bajo.descripcion,
        gravedad: gravedadDe('ca_ion'),
        parametros: ['ca_ion']
    });

    if (esAlto('ca_ion')) agregar({
        nombre: alt.ca_ionizado_alto.nombre,
        descripcion: alt.ca_ionizado_alto.descripcion,
        gravedad: gravedadDe('ca_ion'),
        parametros: ['ca_ion']
    });

    if (esAlto('anion_gap')) agregar({
        nombre: alt.anion_gap_elevado.nombre,
        descripcion: alt.anion_gap_elevado.descripcion,
        gravedad: gravedadDe('anion_gap'),
        parametros: ['anion_gap', ...(presente('lactato') ? ['lactato'] : [])].filter(presente)
    });

    return patrones;
};

// Exportación principal

export const analizarResultados = (valoresInput, paciente, referencias, alteraciones) => {
    const refsEspecie = referencias[paciente.especie];
    if (!refsEspecie) return { hallazgos: [], patrones: [] };

    // Ajusta los rangos segun edad, raza y sexo antes de comparar
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
