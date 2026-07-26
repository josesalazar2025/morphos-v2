// Navegación, gestos, paneles colapsables, sincronización móvil, imágenes y cámara.
// Puerto TS de js/ui.js — comportamiento idéntico; sólo tipado + helpers de DOM.

import { elId, qs, qsa } from './dom.js';

// Navegación-Pestañas

const tabs = qsa<HTMLElement>('.tab-nav');
const paneles = qsa<HTMLElement>('main > .panel, .col3-wrapper > .panel');
const examenesSubtabsBar = document.getElementById('examenes-subtabs-bar');

const EXAMENES_SUBTAB_PANELS = new Set(['panel-hema', 'panel-bioquim', 'panel-uri', 'panel-endo', 'panel-coag', 'panel-gas']);
let panelExamenActivo = 'panel-hema';
let panelActivo = 'panel-flujo';

const SWIPE_ORDER = ['panel-flujo', 'panel-paciente', 'panel-hema', 'panel-bioquim', 'panel-uri', 'panel-endo', 'panel-coag', 'panel-gas', 'panel-imagenes', 'panel-resultados'];

export function activarTab(targetId: string): void {
  const esSubpanelExamenes = EXAMENES_SUBTAB_PANELS.has(targetId);
  const esTabExamenes = targetId === 'examenes';
  const mostrarExamenes = esTabExamenes || esSubpanelExamenes;

  // Si se clickea la tab generica "Examenes", muestra el ultimo subtab activo; si es un subtab, lo guarda
  let idPanelActual: string;
  if (esTabExamenes) {
    idPanelActual = panelExamenActivo;
  } else if (esSubpanelExamenes) {
    panelExamenActivo = targetId;
    idPanelActual = targetId;
  } else {
    idPanelActual = targetId;
  }

  tabs.forEach((tab) => {
    const estaActivo = mostrarExamenes
      ? tab.dataset.target === 'examenes'
      : tab.dataset.target === targetId;
    tab.classList.toggle('activo', estaActivo);
    tab.setAttribute('aria-current', estaActivo ? 'true' : 'false');
  });

  if (examenesSubtabsBar) (examenesSubtabsBar as HTMLElement).hidden = !mostrarExamenes;

  if (mostrarExamenes) {
    qsa<HTMLElement>('.tab-examenes').forEach((btn) => {
      btn.classList.toggle('activo', btn.dataset.subtabTarget === panelExamenActivo);
    });
  }

  paneles.forEach((panel) => {
    panel.classList.toggle('activo', panel.id === idPanelActual);
  });

  panelActivo = idPanelActual;
  if (targetId === 'panel-paciente') sincronizarPacienteMob();
}

tabs.forEach((tab) => {
  tab.addEventListener('click', () => activarTab(tab.dataset.target ?? ''));
});

qsa<HTMLElement>('.tab-examenes').forEach((btn) => {
  btn.addEventListener('click', () => activarTab(btn.dataset.subtabTarget ?? ''));
});

// Swipe para navegar entre secciones

let inicioSwipeX = 0;
let inicioSwipeY = 0;

const mainNav = qs<HTMLElement>('main');
mainNav?.addEventListener('touchstart', (e) => {
  const te = e as TouchEvent;
  inicioSwipeX = te.touches[0].clientX;
  inicioSwipeY = te.touches[0].clientY;
}, { passive: true });

mainNav?.addEventListener('touchend', (e) => {
  const te = e as TouchEvent;
  const dx = te.changedTouches[0].clientX - inicioSwipeX;
  const dy = te.changedTouches[0].clientY - inicioSwipeY;
  // Ignora gestos cortos o verticales para no interferir con scroll
  if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy)) return;
  const indice = SWIPE_ORDER.indexOf(panelActivo);
  const siguiente = dx < 0 ? SWIPE_ORDER[indice + 1] : SWIPE_ORDER[indice - 1];
  if (siguiente) activarTab(siguiente);
}, { passive: true });

// Sincronizacón de datos de pacientes en mobile

const MAPA_MOB_CANON: Record<string, string> = {
  'mob-pt-especie': 'pt-especie',
  'mob-pt-raza': 'pt-raza',
  'mob-pt-edad': 'pt-edad',
  'mob-pt-edad-unidad': 'pt-edad-unidad',
  'mob-pt-sexo': 'pt-sexo',
};

function sincronizarPacienteMob(): void {
  Object.entries(MAPA_MOB_CANON).forEach(([mobId, canonId]) => {
    const mobEl = document.getElementById(mobId) as HTMLInputElement | HTMLSelectElement | null;
    const canonEl = document.getElementById(canonId) as HTMLInputElement | HTMLSelectElement | null;
    if (mobEl && canonEl) mobEl.value = canonEl.value;
  });
}

export function inicializarSincMob(evaluar: () => void): void {
  Object.entries(MAPA_MOB_CANON).forEach(([mobId, canonId]) => {
    const mobEl = document.getElementById(mobId) as HTMLInputElement | HTMLSelectElement | null;
    if (!mobEl) return;
    const tipoEvento = mobEl.tagName === 'SELECT' ? 'change' : 'input';
    mobEl.addEventListener(tipoEvento, () => {
      const canonEl = document.getElementById(canonId) as HTMLInputElement | HTMLSelectElement | null;
      if (canonEl) canonEl.value = mobEl.value;
      evaluar();
    });
  });
}

// Filas de grid

const panelFlujo = elId('panel-flujo');
const btnColapsar = elId('btn-colapsar-flujo');
const mainEl = qs<HTMLElement>('main')!;

let filaColapsada = '';
let filaExpandida = '';

const esGridEscritorio = (): boolean => window.innerWidth > 1100;

function inicializarFilasGrid(): void {
  if (!esGridEscritorio()) return;
  mainEl.style.gridTemplateRows = '1fr auto auto auto';

  // Mide el panel de flujo expandido y colapsado para animar grid-template-rows con precision
  const alturaPanel = panelFlujo.getBoundingClientRect().height;
  const cabecera = panelFlujo.querySelector('.panel-cabecera');
  const alturaEncabezado = cabecera ? cabecera.getBoundingClientRect().height : 0;
  if (alturaPanel > 0) filaExpandida = `${alturaPanel}px`;
  if (alturaEncabezado > 0) filaColapsada = `${alturaEncabezado}px`;

  mainEl.style.gridTemplateRows = `1fr auto auto ${filaExpandida || 'auto'}`;
}

function establecerFilasGrid(colapsado: boolean, animar: boolean): void {
  if (!esGridEscritorio()) return;
  if (!animar) mainEl.style.transition = 'none';
  mainEl.style.gridTemplateRows = colapsado
    ? `1fr auto auto ${filaColapsada}`
    : `1fr auto auto ${filaExpandida}`;
  if (!animar) {
    void mainEl.offsetHeight;
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
    ['panel-endo', 'panel-uri', 'panel-coag', 'panel-gas'].forEach((id) => {
      const sp = document.getElementById(id);
      if (sp) establecerSubpanelColapsado(sp, true);
    });
  }
});

window.addEventListener('resize', () => {
  if (esGridEscritorio()) {
    if (!panelFlujo.classList.contains('collapsed')) inicializarFilasGrid();
  } else {
    qsa<HTMLElement>('.subpanel-anim').forEach((animEl) => {
      animEl.style.height = '';
      animEl.style.transition = '';
    });
    qs<HTMLElement>('.subpanel-anim', document.getElementById('subpanel-citologia') ?? document)
      ?.style.setProperty('height', '');
  }
});

// Paneles colapsables

function establecerSubpanelColapsado(subpanel: HTMLElement, debeColapsar: boolean): void {
  if (!esGridEscritorio()) return;
  const animEl = subpanel.querySelector<HTMLElement>('.subpanel-anim');
  const btn = subpanel.querySelector('.btn-colapsar-subpanel');
  const esRelleno = subpanel.id === 'subpanel-citologia';
  if (!animEl) return;
  if (debeColapsar === subpanel.classList.contains('collapsed')) return;
  subpanel.classList.toggle('collapsed', debeColapsar);
  if (btn) btn.setAttribute('aria-expanded', String(!debeColapsar));
  // Forzar reflujo antes de cambiar height permite que CSS transition anime correctamente
  if (debeColapsar) {
    animEl.style.height = `${animEl.offsetHeight}px`;
    void animEl.offsetHeight;
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
  ['panel-coag', 'panel-gas'],
];

const PANELES_COLAPSADOS_POR_DEFECTO = new Set(['panel-uri', 'panel-endo', 'panel-coag', 'panel-gas']);

qsa<HTMLElement>('.btn-colapsar-subpanel').forEach((btn) => {
  const subpanel = btn.closest<HTMLElement>('.subpanel');
  if (!subpanel) return;
  const animEl = subpanel.querySelector<HTMLElement>('.subpanel-anim');
  if (!animEl) return;
  const claveAlmacenamiento = `mx-${subpanel.id}-collapsed`;
  const esRelleno = subpanel.id === 'subpanel-citologia';

  if (esGridEscritorio()) {
    if (!esRelleno) {
      animEl.style.transition = 'none';
      animEl.style.height = `${animEl.scrollHeight}px`;
    }

    const valorGuardado = localStorage.getItem(claveAlmacenamiento);
    const debeColapsar = valorGuardado !== null
      ? valorGuardado === '1'
      : PANELES_COLAPSADOS_POR_DEFECTO.has(subpanel.id);

    if (debeColapsar) {
      subpanel.classList.add('collapsed');
      btn.setAttribute('aria-expanded', 'false');
      if (esRelleno) animEl.style.transition = 'none';
      animEl.style.height = '0px';
      if (esRelleno) { void animEl.offsetHeight; animEl.style.transition = ''; }
    }

    if (!esRelleno) { void animEl.offsetHeight; animEl.style.transition = ''; }
  }

  btn.addEventListener('click', () => {
    if (!esGridEscritorio()) return;
    const colapsado = subpanel.classList.toggle('collapsed');
    btn.setAttribute('aria-expanded', String(!colapsado));
    if (colapsado) {
      animEl.style.height = `${animEl.offsetHeight}px`;
      void animEl.offsetHeight;
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

    const grupo = GRUPOS_VINCULADOS.find((g) => g.includes(subpanel.id));
    if (grupo) {
      grupo.forEach((id) => {
        if (id !== subpanel.id) {
          const asociado = document.getElementById(id);
          if (asociado) establecerSubpanelColapsado(asociado, colapsado);
        }
      });
    }
  });
});

// Patrones de paneles colapsables

const btnColapsarPatrones = elId('btn-colapsar-patrones');
const patronesAnim = elId('patrones-anim');

export function colapsarPatrones(debeColapsar?: boolean): void {
  const estaExpandido = btnColapsarPatrones.getAttribute('aria-expanded') === 'true';
  const colapsado = debeColapsar ?? estaExpandido;

  if (colapsado && estaExpandido) {
    patronesAnim.style.height = `${patronesAnim.scrollHeight}px`;
    void patronesAnim.offsetHeight;
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

export const imagenesDataUrl: (string | null)[] = [null, null];
export const capturasMicroscopio: string[] = [];

const MAX_CAPTURAS_MICRO = 4;

qsa<HTMLElement>('.zona-imagen').forEach((zona) => {
  const indice = parseInt(zona.dataset.zona ?? '0');
  const input = zona.querySelector<HTMLInputElement>('.input-zona')!;
  const vacia = zona.querySelector<HTMLElement>('.zona-vacia')!;
  const btnQuitar = zona.querySelector<HTMLElement>('.btn-quitar-zona')!;
  const vistaPrevia = document.createElement('img');
  vistaPrevia.className = 'zona-img-preview';
  vistaPrevia.alt = `Citología ${indice + 1}`;
  vistaPrevia.hidden = true;
  btnQuitar.before(vistaPrevia);

  zona.addEventListener('click', (e) => {
    if (btnQuitar.contains(e.target as Node)) return;
    input.click();
  });

  input.addEventListener('change', () => {
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const img = new Image();
      img.onload = () => {
        // Reduce la imagen a max 1024px en su lado mayor para no saturar la memoria ni la API
        const MAX_PIXELES = 1024;
        const scale = Math.min(MAX_PIXELES / img.width, MAX_PIXELES / img.height, 1);
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        imagenesDataUrl[indice] = dataUrl;
        vistaPrevia.src = dataUrl;
        vistaPrevia.hidden = false;
        btnQuitar.hidden = false;
        vacia.hidden = true;
        zona.classList.add('con-imagen');
      };
      img.src = ev.target?.result as string;
    };
    reader.readAsDataURL(file);
  });

  btnQuitar.addEventListener('click', (e) => {
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
  const zona = qs<HTMLElement>('.zona-microscopio');
  if (!zona) return;

  const micVacia = zona.querySelector<HTMLElement>('.micro-vacia')!;
  const video = zona.querySelector<HTMLVideoElement>('.micro-video')!;
  const controles = zona.querySelector<HTMLElement>('.micro-controles')!;
  const btnGaleria = zona.querySelector<HTMLElement>('.micro-btn-galeria')!;
  const badge = zona.querySelector<HTMLElement>('.micro-badge')!;
  const btnCapturar = zona.querySelector<HTMLButtonElement>('.micro-btn-capturar')!;
  const btnCerrar = zona.querySelector<HTMLElement>('.micro-btn-cerrar')!;
  const galeriaEl = zona.querySelector<HTMLElement>('.micro-galeria')!;

  let stream: MediaStream | null = null;
  let galeriaEsVisible = false;

  function detenerStream(): void {
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
  }

  function actualizarInsignia(): void {
    const n = capturasMicroscopio.length;
    badge.textContent = String(n);
    badge.hidden = n === 0;
    btnCapturar.disabled = n >= MAX_CAPTURAS_MICRO;
  }

  function renderizarGaleria(): void {
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

    galeriaEl.querySelectorAll<HTMLElement>('.micro-thumb-quitar').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const i = parseInt(btn.dataset.captureIdx ?? '0');
        capturasMicroscopio.splice(i, 1);
        actualizarInsignia();
        renderizarGaleria();
        if (capturasMicroscopio.length === 0 && galeriaEsVisible) alternarGaleria();
      });
    });
  }

  function alternarGaleria(): void {
    galeriaEsVisible = !galeriaEsVisible;
    galeriaEl.hidden = !galeriaEsVisible;
    if (galeriaEsVisible) renderizarGaleria();
    btnGaleria.style.color = galeriaEsVisible ? 'var(--accent)' : '';
  }

  async function abrirCamara(): Promise<void> {
    try {
      // Preferencia por camara trasera (microscopio o movil apuntando a la muestra)
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 } },
      });
      video.srcObject = stream;
      video.hidden = false;
      micVacia.hidden = true;
      controles.hidden = false;
      actualizarInsignia();
    } catch {
      // Permiso denegado o camara no disponible; no se requiere fallback
    }
  }

  zona.addEventListener('click', (e) => {
    if (controles.contains(e.target as Node) || galeriaEl.contains(e.target as Node)) return;
    // `void` y no el helper de reporte: abrirCamara ya absorbe su propio error a propósito
    // (permiso denegado es un caso esperado, no algo que deba salir en un toast), así que
    // nunca rechaza. El `void` marca el fire-and-forget como deliberado.
    if (!stream) void abrirCamara();
  });

  btnGaleria.addEventListener('click', (e) => {
    e.stopPropagation();
    alternarGaleria();
  });

  btnCapturar.addEventListener('click', (e) => {
    e.stopPropagation();
    if (capturasMicroscopio.length >= MAX_CAPTURAS_MICRO) return;
    const canvas = document.createElement('canvas');
    // Escala el fotograma de video para mantener un tamano razonable antes de enviarlo al modelo
    const MAX_PIXELES = 1024;
    const scale = Math.min(MAX_PIXELES / video.videoWidth, MAX_PIXELES / video.videoHeight, 1);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext('2d')!.drawImage(video, 0, 0, canvas.width, canvas.height);
    capturasMicroscopio.push(canvas.toDataURL('image/jpeg', 0.85));
    actualizarInsignia();
    if (galeriaEsVisible) renderizarGaleria();
  });

  btnCerrar.addEventListener('click', (e) => {
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
