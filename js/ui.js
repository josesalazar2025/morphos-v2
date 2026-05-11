// Navegación-Pestañas

const tabs = document.querySelectorAll('.tab-nav');
const paneles = document.querySelectorAll('main > .panel, .col3-wrapper > .panel');
const examenesSubtabsBar = document.getElementById('examenes-subtabs-bar');

const EXAMENES_SUBTAB_PANELS = new Set(['panel-hema', 'panel-bioquim', 'panel-uri', 'panel-endo']);
let panelExamenActivo = 'panel-hema';
let panelActivo = 'panel-flujo';

const SWIPE_ORDER = ['panel-flujo', 'panel-paciente', 'panel-hema', 'panel-bioquim', 'panel-uri', 'panel-endo', 'panel-imagenes', 'panel-resultados'];

export function activarTab(targetId) {
    const esSubpanelExamenes = EXAMENES_SUBTAB_PANELS.has(targetId);
    const esTabExamenes = targetId === 'examenes';
    const mostrarExamenes = esTabExamenes || esSubpanelExamenes;

    let idPanelActual;
    if (esTabExamenes) {
        idPanelActual = panelExamenActivo;
    } else if (esSubpanelExamenes) {
        panelExamenActivo = targetId;
        idPanelActual = targetId;
    } else {
        idPanelActual = targetId;
    }

    tabs.forEach(tab => {
        const estaActivo = mostrarExamenes
            ? tab.dataset.target === 'examenes'
            : tab.dataset.target === targetId;
        tab.classList.toggle('activo', estaActivo);
        tab.setAttribute('aria-current', estaActivo ? 'true' : 'false');
    });

    if (examenesSubtabsBar) examenesSubtabsBar.hidden = !mostrarExamenes;

    if (mostrarExamenes) {
        document.querySelectorAll('.tab-examenes').forEach(btn => {
            btn.classList.toggle('activo', btn.dataset.subtabTarget === panelExamenActivo);
        });
    }

    paneles.forEach(panel => {
        panel.classList.toggle('activo', panel.id === idPanelActual);
    });

    panelActivo = idPanelActual;
    if (targetId === 'panel-paciente') sincronizarPacienteMob();
}

tabs.forEach(tab => {
    tab.addEventListener('click', () => activarTab(tab.dataset.target));
});

document.querySelectorAll('.tab-examenes').forEach(btn => {
    btn.addEventListener('click', () => activarTab(btn.dataset.subtabTarget));
});

// Swipe para navegar entre secciones

let inicioSwipeX = 0;
let inicioSwipeY = 0;

document.querySelector('main').addEventListener('touchstart', e => {
    inicioSwipeX = e.touches[0].clientX;
    inicioSwipeY = e.touches[0].clientY;
}, { passive: true });

document.querySelector('main').addEventListener('touchend', e => {
    const dx = e.changedTouches[0].clientX - inicioSwipeX;
    const dy = e.changedTouches[0].clientY - inicioSwipeY;
    if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy)) return;
    const indice = SWIPE_ORDER.indexOf(panelActivo);
    const siguiente = dx < 0 ? SWIPE_ORDER[indice + 1] : SWIPE_ORDER[indice - 1];
    if (siguiente) activarTab(siguiente);
}, { passive: true });

// Sincronizacón de datos de pacientes en mobile

const MAPA_MOB_CANON = {
    'mob-pt-especie': 'pt-especie',
    'mob-pt-raza': 'pt-raza',
    'mob-pt-edad': 'pt-edad',
    'mob-pt-edad-unidad': 'pt-edad-unidad',
    'mob-pt-sexo': 'pt-sexo'
};

function sincronizarPacienteMob() {
    Object.entries(MAPA_MOB_CANON).forEach(([mobId, canonId]) => {
        const mobEl = document.getElementById(mobId);
        const canonEl = document.getElementById(canonId);
        if (mobEl && canonEl) mobEl.value = canonEl.value;
    });
}

export function inicializarSincMob(evaluar) {
    Object.entries(MAPA_MOB_CANON).forEach(([mobId, canonId]) => {
        const mobEl = document.getElementById(mobId);
        if (!mobEl) return;
        const tipoEvento = mobEl.tagName === 'SELECT' ? 'change' : 'input';
        mobEl.addEventListener(tipoEvento, () => {
            const canonEl = document.getElementById(canonId);
            if (canonEl) canonEl.value = mobEl.value;
            evaluar();
        });
    });
}

// Filas de grid

const panelFlujo = document.getElementById('panel-flujo');
const btnColapsar = document.getElementById('btn-colapsar-flujo');
const mainEl = document.querySelector('main');

let filaColapsada = '';
let filaExpandida = '';

const esGridEscritorio = () => window.innerWidth > 1100;

function inicializarFilasGrid() {
    if (!esGridEscritorio()) return;
    mainEl.style.gridTemplateRows = '1fr auto auto';

    const alturaPanel = panelFlujo.getBoundingClientRect().height;
    const alturaEncabezado = panelFlujo.querySelector('.panel-cabecera').getBoundingClientRect().height;
    if (alturaPanel > 0) filaExpandida = `${alturaPanel}px`;
    if (alturaEncabezado > 0) filaColapsada = `${alturaEncabezado}px`;

    mainEl.style.gridTemplateRows = `1fr auto ${filaExpandida || 'auto'}`;
}

function establecerFilasGrid(colapsado, animar) {
    if (!esGridEscritorio()) return;
    if (!animar) mainEl.style.transition = 'none';
    mainEl.style.gridTemplateRows = colapsado
        ? `1fr auto ${filaColapsada}`
        : `1fr auto ${filaExpandida}`;
    if (!animar) {
        mainEl.offsetHeight;
        mainEl.style.transition = '';
    }
}

inicializarFilasGrid();

const inicioColapsado = localStorage.getItem('mx-flujo-collapsed') === '1';
if (inicioColapsado) {
    panelFlujo.classList.add('collapsed');
    btnColapsar.setAttribute('aria-expanded', 'false');
    establecerFilasGrid(true, false);
}

btnColapsar.addEventListener('click', () => {
    const colapsado = panelFlujo.classList.toggle('collapsed');
    btnColapsar.setAttribute('aria-expanded', String(!colapsado));
    establecerFilasGrid(colapsado, true);
    localStorage.setItem('mx-flujo-collapsed', colapsado ? '1' : '0');
    if (!colapsado) {
        ['panel-endo', 'panel-uri'].forEach(id => {
            const sp = document.getElementById(id);
            if (sp) establecerSubpanelColapsado(sp, true);
        });
    }
});

window.addEventListener('resize', () => {
    if (esGridEscritorio()) {
        if (!panelFlujo.classList.contains('collapsed')) inicializarFilasGrid();
    } else {
        document.querySelectorAll('.subpanel-anim').forEach(animEl => {
            animEl.style.height = '';
            animEl.style.transition = '';
        });
        document.getElementById('subpanel-citologia')
            ?.querySelector('.subpanel-anim')
            ?.style.setProperty('height', '');
    }
});

// Paneles colapsables

function establecerSubpanelColapsado(subpanel, debeColapsar) {
    if (!esGridEscritorio()) return;
    const animEl = subpanel.querySelector('.subpanel-anim');
    const btn = subpanel.querySelector('.btn-colapsar-subpanel');
    const esRelleno = subpanel.id === 'subpanel-citologia';
    if (debeColapsar === subpanel.classList.contains('collapsed')) return;
    subpanel.classList.toggle('collapsed', debeColapsar);
    if (btn) btn.setAttribute('aria-expanded', String(!debeColapsar));
    if (debeColapsar) {
        animEl.style.height = `${animEl.offsetHeight}px`;
        animEl.offsetHeight;
        animEl.style.height = '0px';
    } else {
        animEl.style.height = `${animEl.scrollHeight}px`;
        if (esRelleno) {
            animEl.addEventListener('transitionend', () => {
                animEl.style.height = '';
            }, { once: true });
        }
    }
    localStorage.setItem(`mx-${subpanel.id}-collapsed`, debeColapsar ? '1' : '0');
}

const GRUPOS_VINCULADOS = [
    ['panel-endo', 'panel-uri'],
];

document.querySelectorAll('.btn-colapsar-subpanel').forEach(btn => {
    const subpanel = btn.closest('.subpanel');
    const animEl = subpanel.querySelector('.subpanel-anim');
    const claveAlmacenamiento = `mx-${subpanel.id}-collapsed`;
    const esRelleno = subpanel.id === 'subpanel-citologia';

    if (esGridEscritorio()) {
        if (!esRelleno) {
            animEl.style.transition = 'none';
            animEl.style.height = `${animEl.scrollHeight}px`;
        }

        if (localStorage.getItem(claveAlmacenamiento) === '1') {
            subpanel.classList.add('collapsed');
            btn.setAttribute('aria-expanded', 'false');
            if (esRelleno) animEl.style.transition = 'none';
            animEl.style.height = '0px';
            if (esRelleno) { animEl.offsetHeight; animEl.style.transition = ''; }
        }

        if (!esRelleno) { animEl.offsetHeight; animEl.style.transition = ''; }
    }

    btn.addEventListener('click', () => {
        if (!esGridEscritorio()) return;
        const colapsado = subpanel.classList.toggle('collapsed');
        btn.setAttribute('aria-expanded', String(!colapsado));
        if (colapsado) {
            animEl.style.height = `${animEl.offsetHeight}px`;
            animEl.offsetHeight;
            animEl.style.height = '0px';
        } else {
            animEl.style.height = `${animEl.scrollHeight}px`;
            if (esRelleno) {
                animEl.addEventListener('transitionend', () => {
                    animEl.style.height = '';
                }, { once: true });
            }
        }
        localStorage.setItem(claveAlmacenamiento, colapsado ? '1' : '0');

        const grupo = GRUPOS_VINCULADOS.find(g => g.includes(subpanel.id));
        if (grupo) {
            grupo.forEach(id => {
                if (id !== subpanel.id) {
                    const asociado = document.getElementById(id);
                    if (asociado) establecerSubpanelColapsado(asociado, colapsado);
                }
            });
        }
    });
});

// Patrones de paneles colapsables

const btnColapsarPatrones = document.getElementById('btn-colapsar-patrones');
const patronesAnim = document.getElementById('patrones-anim');

export function colapsarPatrones(debeColapsar) {
    const estaExpandido = btnColapsarPatrones.getAttribute('aria-expanded') === 'true';
    const colapsado = debeColapsar ?? estaExpandido;

    if (colapsado && estaExpandido) {
        patronesAnim.style.height = `${patronesAnim.scrollHeight}px`;
        patronesAnim.offsetHeight;
        patronesAnim.style.height = '0px';
        btnColapsarPatrones.setAttribute('aria-expanded', 'false');
    } else if (!colapsado && !estaExpandido) {
        patronesAnim.style.height = `${patronesAnim.scrollHeight}px`;
        patronesAnim.addEventListener('transitionend', () => {
            if (btnColapsarPatrones.getAttribute('aria-expanded') === 'true') {
                patronesAnim.style.height = '';
            }
        }, { once: true });
        btnColapsarPatrones.setAttribute('aria-expanded', 'true');
    }
}

btnColapsarPatrones.addEventListener('click', () => colapsarPatrones());

// Imágenes

export const imagenesDataUrl = [null, null];
export const capturasMicroscopio = [];

const MAX_CAPTURAS_MICRO = 4;

document.querySelectorAll('.zona-imagen').forEach(zona => {
    const indice = parseInt(zona.dataset.zona);
    const input = zona.querySelector('.input-zona');
    const vacia = zona.querySelector('.zona-vacia');
    const btnQuitar = zona.querySelector('.btn-quitar-zona');
    const vistaPrevia = document.createElement('img');
    vistaPrevia.className = 'zona-img-preview';
    vistaPrevia.alt = `Citología ${indice + 1}`;
    vistaPrevia.hidden = true;
    btnQuitar.before(vistaPrevia);

    zona.addEventListener('click', e => {
        if (btnQuitar.contains(e.target)) return;
        input.click();
    });

    input.addEventListener('change', () => {
        const file = input.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = ev => {
            imagenesDataUrl[indice] = ev.target.result;
            vistaPrevia.src = ev.target.result;
            vistaPrevia.hidden = false;
            btnQuitar.hidden = false;
            vacia.hidden = true;
            zona.classList.add('con-imagen');
        };
        reader.readAsDataURL(file);
    });

    btnQuitar.addEventListener('click', e => {
        e.stopPropagation();
        imagenesDataUrl[indice] = null;
        vistaPrevia.src = '';
        vistaPrevia.hidden = true;
        btnQuitar.hidden = true;
        vacia.hidden = false;
        zona.classList.remove('con-imagen');
        input.value = '';
    });
});

// Captura de microscopio

(function () {
    const zona = document.querySelector('.zona-microscopio');
    if (!zona) return;

    const micVacia = zona.querySelector('.micro-vacia');
    const video = zona.querySelector('.micro-video');
    const controles = zona.querySelector('.micro-controles');
    const btnGaleria = zona.querySelector('.micro-btn-galeria');
    const badge = zona.querySelector('.micro-badge');
    const btnCapturar = zona.querySelector('.micro-btn-capturar');
    const btnCerrar = zona.querySelector('.micro-btn-cerrar');
    const galeriaEl = zona.querySelector('.micro-galeria');

    let stream = null;
    let galeriaEsVisible = false;

    function detenerStream() {
        if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    }

    function actualizarInsignia() {
        const n = capturasMicroscopio.length;
        badge.textContent = n;
        badge.hidden = n === 0;
        btnCapturar.disabled = n >= MAX_CAPTURAS_MICRO;
    }

    function renderizarGaleria() {
        if (capturasMicroscopio.length === 0) {
            galeriaEl.innerHTML = '<span class="micro-galeria-vacia">Sin capturas</span>';
            return;
        }
        galeriaEl.innerHTML = capturasMicroscopio.map((src, i) => `
            <div class="micro-thumb">
                <img src="${src}" alt="Captura ${i + 1}">
                <button class="micro-thumb-quitar" type="button" data-capture-idx="${i}" aria-label="Eliminar captura ${i + 1}">
                    <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>`).join('');

        galeriaEl.querySelectorAll('.micro-thumb-quitar').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                const i = parseInt(btn.dataset.captureIdx);
                capturasMicroscopio.splice(i, 1);
                actualizarInsignia();
                renderizarGaleria();
                if (capturasMicroscopio.length === 0 && galeriaEsVisible) alternarGaleria();
            });
        });
    }

    function alternarGaleria() {
        galeriaEsVisible = !galeriaEsVisible;
        galeriaEl.hidden = !galeriaEsVisible;
        if (galeriaEsVisible) renderizarGaleria();
        btnGaleria.style.color = galeriaEsVisible ? 'var(--accent)' : '';
    }

    async function abrirCamara() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 } }
            });
            video.srcObject = stream;
            video.hidden = false;
            micVacia.hidden = true;
            controles.hidden = false;
            actualizarInsignia();
        } catch {
            // Permiso denegado o cámara no disponible — no se requiere fallback
        }
    }

    zona.addEventListener('click', e => {
        if (controles.contains(e.target) || galeriaEl.contains(e.target)) return;
        if (!stream) abrirCamara();
    });

    btnGaleria.addEventListener('click', e => {
        e.stopPropagation();
        alternarGaleria();
    });

    btnCapturar.addEventListener('click', e => {
        e.stopPropagation();
        if (capturasMicroscopio.length >= MAX_CAPTURAS_MICRO) return;
        const canvas = document.createElement('canvas');
        const MAX_PIXELES = 1024;
        const scale = Math.min(MAX_PIXELES / video.videoWidth, MAX_PIXELES / video.videoHeight, 1);
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        capturasMicroscopio.push(canvas.toDataURL('image/jpeg', 0.85));
        actualizarInsignia();
        if (galeriaEsVisible) renderizarGaleria();
    });

    btnCerrar.addEventListener('click', e => {
        e.stopPropagation();
        detenerStream();
        video.hidden = true;
        video.srcObject = null;
        controles.hidden = true;
        galeriaEl.hidden = true;
        galeriaEsVisible = false;
        micVacia.hidden = false;
    });
})();

