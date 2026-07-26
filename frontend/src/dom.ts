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
