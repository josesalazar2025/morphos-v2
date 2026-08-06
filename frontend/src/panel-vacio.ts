// Estado vacío de los paneles de exámenes (sólo escritorio).
//
// Cada panel arranca con `.sin-datos`: en vez del formulario muestra una zona para soltar el
// PDF y un botón que devuelve al modo de captura manual. La entrada manual no desaparece, sólo
// deja de ser lo primero que se ve: en la mayoría de los casos el veterinario llega con un PDF
// del laboratorio, y teclear 90 analitos a mano es la excepción.
//
// El estado vive en una clase del <section>, no en JS, para que el CSS decida cuándo aplica
// (el móvil lo ignora entero: allí los paneles son pestañas y el formulario va directo).

// Sólo depende de `dom.ts` a propósito: `form-inject.ts` importa este módulo, y form-inject es
// la base compartida de los dos importadores. Colgar de aquí a `ui.ts` —que toca el DOM al
// cargarse— arrastraría esa dependencia hasta ellos y hasta sus tests.
import { esGridEscritorio } from './dom.js';

// Saca un panel del estado vacío. Idempotente: se llama tanto desde el botón como desde cada
// valor inyectado por los importadores, que pueden ser decenas en una sola importación.
export function revelarPanel(panel: HTMLElement | null): void {
  if (!panel || !panel.classList.contains('sin-datos')) return;
  panel.classList.remove('sin-datos');
  reajustarAltura(panel);
}

// Los cuatro paneles colapsables llevan la altura de su animación fijada en píxeles inline (ver
// ui.ts); sin reajustarla al cambiar el contenido, el formulario recién mostrado sale recortado.
// No toca los colapsados —su altura debe seguir siendo 0— ni el móvil, donde no hay animación.
function reajustarAltura(panel: HTMLElement): void {
  if (!esGridEscritorio() || panel.classList.contains('collapsed')) return;
  const animEl = panel.querySelector<HTMLElement>('.subpanel-anim');
  if (!animEl || !animEl.style.height) return;
  animEl.style.height = `${animEl.scrollHeight}px`;
}

// Revela el panel al que pertenece un campo. La usan los importadores (PDF y analizador) para
// que un valor inyectado nunca quede escondido detrás del estado vacío.
export function revelarPanelDeCampo(el: Element): void {
  revelarPanel(el.closest<HTMLElement>('.subpanel'));
}

export function inicializarPanelesVacios(): void {
  document.querySelectorAll<HTMLElement>('.panel-vacio-manual').forEach((btn) => {
    btn.addEventListener('click', () => {
      const panel = btn.closest<HTMLElement>('.subpanel');
      revelarPanel(panel);
      // El foco salta al primer campo: quien pulsa "manual" viene a teclear.
      panel?.querySelector<HTMLInputElement>('.fila-campo input, .fila-campo select')?.focus();
    });
  });

  document.querySelectorAll<HTMLElement>('.panel-vacio-explorar').forEach((btn) => {
    btn.addEventListener('click', () => {
      (document.getElementById(`pdf-input-${btn.dataset.panel}`) as HTMLInputElement | null)?.click();
    });
  });
}
