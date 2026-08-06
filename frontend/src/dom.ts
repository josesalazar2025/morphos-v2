// Helpers de DOM tipados para reducir el ruido de comprobaciones de nulos en el port a TS.
// `elId` asume que el elemento existe (igual que el JS original que lo usaba sin comprobar);
// `elIdOpt` devuelve null cuando puede faltar.

export function elId<T extends HTMLElement = HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Elemento #${id} no encontrado`);
  return el as T;
}

export function elIdOpt<T extends HTMLElement = HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

export function qs<T extends Element = Element>(sel: string, root: ParentNode = document): T | null {
  return root.querySelector<T>(sel);
}

export function qsa<T extends Element = Element>(sel: string, root: ParentNode = document): T[] {
  return Array.from(root.querySelectorAll<T>(sel));
}

// Punto de corte del grid de escritorio. Vive aquí, en el módulo hoja, porque lo consultan
// varios módulos que no deben depender unos de otros, y debe coincidir con la media query
// `min-width: 1101px` de css/styles.css.
export function esGridEscritorio(): boolean {
  return window.innerWidth > 1100;
}
