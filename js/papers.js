const PROXY_URL = 'api/papers_proxy.php';
const POR_PAGINA = 10;

let todosLosPapers = [];
let paginaActual = 0;
let consultaActual = '';


//Esto nos permite hacer búsquedas en la API de PubMed, sólo recibe texto en inglés

const TERMINOS_EN = {
    'Anemia': 'anemia',
    'Eritrocitosis': 'erythrocytosis polycythemia',
    'Leucocitosis': 'leukocytosis',
    'Leucocitosis neutrofílica': 'neutrophilic leukocytosis',
    'Leucocitosis linfocítica': 'lymphocytic leukocytosis',
    'Leucopenia': 'leukopenia',
    'Eosinofilia': 'eosinophilia',
    'Neutropenia': 'neutropenia',
    'Linfopenia': 'lymphopenia',
    'Trombocitopenia': 'thrombocytopenia',
    'Trombocitosis': 'thrombocytosis',
    'Daño hepatocelular': 'hepatocellular damage liver injury',
    'Elevación de ALT aislada': 'ALT elevation liver',
    'Patrón colestásico': 'cholestasis',
    'Hiperbilirrubinemia': 'hyperbilirubinemia jaundice',
    'Azotemia': 'azotemia renal failure',
    'Hiperuremia aislada (BUN)': 'elevated BUN prerenal azotemia',
    'BUN disminuido': 'low BUN hepatic failure',
    'Creatinina elevada (BUN normal)': 'elevated creatinine kidney',
    'Hiperglucemia': 'hyperglycemia diabetes mellitus',
    'Hipoglucemia': 'hypoglycemia',
    'Hiperproteinemia': 'hyperproteinemia',
    'Hipoproteinemia / Hipoalbuminemia': 'hypoproteinemia hypoalbuminemia',
    'Hipoalbuminemia': 'hypoalbuminemia',
    'Hipercalcemia': 'hypercalcemia',
    'Hipocalcemia': 'hypocalcemia',
    'Hipernatremia': 'hypernatremia',
    'Hiponatremia': 'hyponatremia',
    'Hiperpotasemia': 'hyperkalemia',
    'Hipopotasemia': 'hypokalemia',
    'Hiperfosforemia': 'hyperphosphatemia',
    'Hipotiroidismo': 'hypothyroidism',
    'Hipertiroidismo': 'hyperthyroidism',
    'Hiperadrenocorticismo (Cushing)': 'hyperadrenocorticism Cushing',
    'Hipoadrenocorticismo (Addison)': 'hypoadrenocorticism Addison',
    'Ratio Na:K reducido — sospecha de hipoadrenocorticismo': 'hypoadrenocorticism sodium potassium ratio',
    'Cortisol basal bajo — posible hipoadrenocorticismo': 'low basal cortisol hypoadrenocorticism',
    'Hiposthenuria': 'hyposthenuria urine specific gravity',
    'Isosthenuria': 'isosthenuria urine concentration renal',
    'Posible déficit de insulina': 'insulin deficiency hyperglycemia diabetes mellitus',
};

const traducirPatron = (nombre) => {
    for (const [es, en] of Object.entries(TERMINOS_EN)) {
        if (nombre.startsWith(es)) return en;
    }
    return nombre.replace(/[áéíóúñ]/g, c => ({á:'a',é:'e',í:'i',ó:'o',ú:'u',ñ:'n'})[c] || c);
};

const construirQuery = (patrones) => {
    if (!patrones || patrones.length === 0) return 'veterinary clinical laboratory diagnosis canine feline';
    const terminos = [...new Set(patrones.map(p => traducirPatron(p.nombre)))].slice(0, 3);
    return `${terminos.join(' ')} canine OR feline veterinary`;
};

const buscarPapers = async (query) => {
    const respuesta = await fetch(`${PROXY_URL}?query=${encodeURIComponent(query)}`);
    if (!respuesta.ok) {
        const detalle = await respuesta.json().catch(() => ({}));
        throw new Error(detalle.error || `Error ${respuesta.status}`);
    }
    const datos = await respuesta.json();
    return datos.data || [];
};

const renderizarTarjetaPaper = (paper) => {
    const titulo = paper.title || 'Sin título';
    const autores = paper.authors?.slice(0, 3).map(a => a.name).join(', ') || 'Autores desconocidos';
    const masAutores = (paper.authors?.length || 0) > 3 ? ' et al.' : '';
    const anio = paper.year || '—';
    const revista = paper.journal || '';

    const urlDoi = paper.doi ? `https://doi.org/${paper.doi}` : null;
    const urlPubmed = paper.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${paper.pmid}/` : null;
    const urlPrincipal = urlDoi || urlPubmed;

    const articulo = document.createElement('article');
    articulo.className = 'paper-tarjeta';

    const meta = document.createElement('div');
    meta.className = 'paper-meta';

    const spanAnio = document.createElement('span');
    spanAnio.className = 'paper-anio';
    spanAnio.textContent = anio;
    meta.append(spanAnio);

    if (revista) {
        const spanRevista = document.createElement('span');
        spanRevista.className = 'paper-revista';
        spanRevista.textContent = revista;
        meta.append(spanRevista);
    }

    articulo.append(meta);

    const h3 = document.createElement('h3');
    h3.className = 'paper-titulo';

    if (urlPrincipal) {
        const link = document.createElement('a');
        link.href = urlPrincipal;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = titulo;
        h3.append(link);
    } else {
        h3.textContent = titulo;
    }

    articulo.append(h3);

    const pAutores = document.createElement('p');
    pAutores.className = 'paper-autores';
    pAutores.textContent = autores + masAutores;
    articulo.append(pAutores);

    return articulo;
};

const renderizarPaginacion = () => {
    const totalPaginas = Math.ceil(todosLosPapers.length / POR_PAGINA);
    const contenedor = document.getElementById('papers-paginacion');
    if (!contenedor) return;

    if (totalPaginas <= 1) {
        contenedor.innerHTML = '';
        return;
    }

    const inicio = Math.max(0, paginaActual - 2);
    const fin = Math.min(totalPaginas, inicio + 5);

    let html = `<button class="papers-pag-btn" data-pagina="${paginaActual - 1}" ${paginaActual === 0 ? 'disabled' : ''} aria-label="Página anterior"><img src="assets/icons/anterior.svg" alt="" aria-hidden="true" width="16" height="16"></button>`;
    for (let i = inicio; i < fin; i++) {
        html += `<button class="papers-pag-btn ${i === paginaActual ? 'activo' : ''}" data-pagina="${i}">${i + 1}</button>`;
    }
    html += `<button class="papers-pag-btn" data-pagina="${paginaActual + 1}" ${paginaActual >= totalPaginas - 1 ? 'disabled' : ''} aria-label="Página siguiente"><img src="assets/icons/siguiente.svg" alt="" aria-hidden="true" width="16" height="16"></button>`;

    contenedor.innerHTML = html;
};

const renderizarPaginaActual = () => {
    const lista = document.getElementById('papers-lista');
    if (!lista) return;

    const inicio = paginaActual * POR_PAGINA;
    const pagina = todosLosPapers.slice(inicio, inicio + POR_PAGINA);

    lista.replaceChildren();

    if (pagina.length === 0) {
        const vacio = document.createElement('p');
        vacio.className = 'papers-vacio';
        vacio.textContent = 'No se encontraron artículos para esta búsqueda.';
        lista.append(vacio);
    } else {
        lista.append(...pagina.map(renderizarTarjetaPaper));
    }

    renderizarPaginacion();
    lista.scrollTop = 0;
};

const irAPagina = (numeroPagina) => {
    const totalPaginas = Math.ceil(todosLosPapers.length / POR_PAGINA);
    if (numeroPagina < 0 || numeroPagina >= totalPaginas) return;
    paginaActual = numeroPagina;
    renderizarPaginaActual();
};

const mostrarEstadoCarga = () => {
    const lista = document.getElementById('papers-lista');
    if (lista) lista.innerHTML = '<p class="papers-cargando">Buscando artículos científicos…</p>';
    const paginacion = document.getElementById('papers-paginacion');
    if (paginacion) paginacion.innerHTML = '';
};

const mostrarError = (mensaje) => {
    const lista = document.getElementById('papers-lista');
    if (!lista) return;
    const p = document.createElement('p');
    p.className = 'papers-error';
    p.textContent = mensaje;
    lista.replaceChildren(p);
};

export const abrirModalPapers = async (patrones) => {
    const modal = document.getElementById('modal-papers');
    const overlay = document.getElementById('modal-papers-overlay');
    if (!modal || !overlay) return;

    const nuevaConsulta = construirQuery(patrones);

    modal.removeAttribute('hidden');
    overlay.classList.add('activo');
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(() => modal.classList.add('visible'));

    const etiquetaConsulta = document.getElementById('papers-consulta');
    if (etiquetaConsulta) etiquetaConsulta.textContent = `"${nuevaConsulta}"`;

    if (nuevaConsulta === consultaActual && todosLosPapers.length > 0) {
        renderizarPaginaActual();
        return;
    }

    consultaActual = nuevaConsulta;
    todosLosPapers = [];
    paginaActual = 0;
    mostrarEstadoCarga();

    try {
        todosLosPapers = await buscarPapers(nuevaConsulta);
        renderizarPaginaActual();
    } catch (error) {
        mostrarError(error.message || 'No se pudo conectar con PubMed. Intenta de nuevo más tarde.');
        console.error('Error buscando papers:', error);
    }
};

const cerrarModalPapers = () => {
    const modal = document.getElementById('modal-papers');
    const overlay = document.getElementById('modal-papers-overlay');
    if (!modal || !overlay) return;

    modal.classList.remove('visible');
    overlay.classList.remove('activo');
    document.body.style.overflow = '';
    setTimeout(() => modal.setAttribute('hidden', ''), 250);
};

export const inicializarModalPapers = () => {
    document.getElementById('modal-papers-cerrar')?.addEventListener('click', cerrarModalPapers);
    document.getElementById('modal-papers-overlay')?.addEventListener('click', cerrarModalPapers);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('modal-papers');
            if (modal && !modal.hidden) cerrarModalPapers();
        }
    });

    document.getElementById('papers-paginacion')?.addEventListener('click', (e) => {
        const btn = e.target.closest('.papers-pag-btn');
        if (!btn || btn.disabled) return;
        irAPagina(parseInt(btn.dataset.pagina, 10));
    });

    document.getElementById('papers-busqueda-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const input = document.getElementById('papers-busqueda-input');
        const termino = input?.value.trim();
        if (!termino) return;

        const etiquetaConsulta = document.getElementById('papers-consulta');
        if (etiquetaConsulta) etiquetaConsulta.textContent = `"${termino}"`;

        consultaActual = termino;
        todosLosPapers = [];
        paginaActual = 0;
        mostrarEstadoCarga();

        try {
            todosLosPapers = await buscarPapers(termino);
            renderizarPaginaActual();
        } catch (error) {
            mostrarError(error.message || 'No se pudo conectar con PubMed. Intenta de nuevo más tarde.');
            console.error('Error buscando papers:', error);
        }
    });
};
