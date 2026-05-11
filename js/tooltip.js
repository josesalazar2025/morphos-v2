const burbuja = document.createElement('div');
burbuja.id = 'tooltip-global';
document.body.appendChild(burbuja);

const MARGEN = 8;

const posicionar = (el) => {
    const rect = el.getBoundingClientRect();
    const enFooter = el.closest('.nav-inferior') !== null;

    burbuja.style.left = '';
    burbuja.style.right = '';

    let top, left;

    if (enFooter) {
        top = rect.top - burbuja.offsetHeight - MARGEN;
    } else {
        top = rect.bottom + MARGEN;
    }

    left = rect.left + rect.width / 2 - burbuja.offsetWidth / 2;

    const margenLateral = 6;
    if (left < margenLateral) left = margenLateral;
    if (left + burbuja.offsetWidth > window.innerWidth - margenLateral) {
        left = window.innerWidth - burbuja.offsetWidth - margenLateral;
    }

    burbuja.style.top = `${top + window.scrollY}px`;
    burbuja.style.left = `${left}px`;
};

let temporizador;

document.addEventListener('mouseover', (e) => {
    const el = e.target.closest('[data-tooltip]');
    if (!el) return;

    clearTimeout(temporizador);
    temporizador = setTimeout(() => {
        burbuja.textContent = el.dataset.tooltip;
        burbuja.classList.add('visible');
        posicionar(el);
    }, 400);
});

document.addEventListener('mouseout', (e) => {
    const el = e.target.closest('[data-tooltip]');
    if (!el) return;

    clearTimeout(temporizador);
    burbuja.classList.remove('visible');
});

document.addEventListener('click', () => {
    clearTimeout(temporizador);
    burbuja.classList.remove('visible');
});
