// @vitest-environment jsdom
// Red de seguridad del RENDER de la interpretación (`ia.ts:renderizar`).
//
// Este camino no tenía ninguna prueba y pintaba con `innerHTML` a partir de una plantilla de
// cadenas. El texto lo escribe un LLM alimentado con fragmentos del RAG y con los
// `signos_clinicos` que teclea el usuario, así que es entrada NO CONFIABLE aunque llegue por
// nuestro propio backend, y encima entra por un cast (`data as RespuestaInterpretacion`) que no
// comprueba nada en tiempo de ejecución.
//
// Lo que se fija aquí: ningún campo de la respuesta puede convertirse en marcado. La prueba
// falla si alguien vuelve a construir el render concatenando HTML, aunque use un `esc()`: el
// caso de la comilla dentro de un atributo (`probabilidad`, `indice`) lo detecta.

import { describe, it, expect } from 'vitest';
import { renderizar } from '../src/ia.js';
import type { RespuestaInterpretacion } from '../src/ia.js';

// Cargas útiles con las tres formas de escape que importan: etiqueta, ruptura de atributo con
// comilla doble y con comilla simple.
const XSS = '<img src=x onerror="alert(1)">';
const XSS_ATRIBUTO = '" onmouseover="alert(1)" x="';
const XSS_ATRIBUTO_SIMPLE = "' onfocus='alert(1)' x='";

function respuesta(parcial: Record<string, unknown> = {}): RespuestaInterpretacion {
  return {
    resultado: {
      interpretacion: 'Texto normal.',
      hallazgos_clave: [],
      diferenciales: [],
      siguientes_pruebas: [],
      confianza: 'media',
      requiere_derivacion: false,
      fuera_de_alcance: false,
      idioma: 'es',
      ...parcial,
    },
    modelo: 'medgemma:latest',
    fuentes_rag: 3,
    fuentes: [],
  } as RespuestaInterpretacion;
}

function pintar(resp: RespuestaInterpretacion): HTMLElement {
  const host = document.createElement('div');
  host.replaceChildren(renderizar(resp));
  return host;
}

// Todo elemento que un atacante querría materializar. Si aparece alguno, el campo se
// interpretó como marcado.
function elementosInyectados(host: HTMLElement): string[] {
  return [...host.querySelectorAll('img, script, iframe, object, embed, svg, style, link')].map(
    (el) => el.tagName.toLowerCase(),
  );
}

// Cualquier atributo de evento (`onerror`, `onmouseover`, …) en cualquier nodo del árbol.
function atributosDeEvento(host: HTMLElement): string[] {
  const encontrados: string[] = [];
  for (const el of [host, ...host.querySelectorAll('*')]) {
    for (const attr of el.attributes) {
      if (attr.name.startsWith('on')) encontrados.push(`${el.tagName.toLowerCase()}@${attr.name}`);
    }
  }
  return encontrados;
}

describe('renderizar: la salida del modelo nunca se interpreta como marcado', () => {
  it('la interpretación con una etiqueta se muestra como texto literal', () => {
    const host = pintar(respuesta({ interpretacion: `Anemia regenerativa. ${XSS}` }));

    expect(elementosInyectados(host)).toEqual([]);
    expect(atributosDeEvento(host)).toEqual([]);
    // Y el veterinario ve el texto entero, no un hueco: escapar no es descartar.
    expect(host.querySelector('.ia-interpretacion')?.textContent).toContain(XSS);
  });

  it('los hallazgos clave escapan analito, dirección, gravedad y comentario', () => {
    const host = pintar(
      respuesta({
        hallazgos_clave: [
          { analito: XSS, direccion: XSS_ATRIBUTO, gravedad: XSS_ATRIBUTO_SIMPLE, comentario: XSS },
        ],
      }),
    );

    expect(elementosInyectados(host)).toEqual([]);
    expect(atributosDeEvento(host)).toEqual([]);
    expect(host.querySelector('.ia-hallazgos li')?.textContent).toContain(XSS);
  });

  it('un diferencial no puede inyectar por nombre, evidencia ni citas', () => {
    const host = pintar(
      respuesta({
        diferenciales: [
          {
            nombre: XSS,
            probabilidad: 'alta',
            evidencia: [XSS_ATRIBUTO, 'anemia no regenerativa'],
            citas: [XSS, XSS_ATRIBUTO_SIMPLE],
          },
        ],
      }),
    );

    expect(elementosInyectados(host)).toEqual([]);
    expect(atributosDeEvento(host)).toEqual([]);
    expect(host.querySelectorAll('.ia-dif-citas cite')).toHaveLength(2);
    expect(host.querySelector('.ia-dif-nombre')?.textContent).toBe(XSS);
  });

  // Este es el caso que un `esc()` de contexto-texto NO detiene: `probabilidad` iba a un nombre
  // de clase, dentro de un atributo, y sin escapar siquiera.
  it('una probabilidad fuera de la lista blanca no llega al nombre de clase', () => {
    const host = pintar(
      respuesta({
        diferenciales: [
          {
            nombre: 'Hipotiroidismo',
            probabilidad: XSS_ATRIBUTO as 'alta',
            evidencia: [],
            citas: [],
          },
        ],
      }),
    );

    expect(elementosInyectados(host)).toEqual([]);
    expect(atributosDeEvento(host)).toEqual([]);
    const prob = host.querySelector('.ia-dif-prob') as HTMLElement;
    // Cae al valor por defecto en la CLASE, pero el texto crudo sigue visible: se degrada el
    // estilo, no el contenido.
    expect(prob.className).toBe('ia-dif-prob ia-prob-baja');
    expect(prob.textContent).toBe(XSS_ATRIBUTO);
  });

  it('las siguientes pruebas escapan', () => {
    const host = pintar(respuesta({ siguientes_pruebas: [XSS, 'ecografía abdominal'] }));

    expect(elementosInyectados(host)).toEqual([]);
    expect(host.querySelector('.ia-pruebas')?.textContent).toContain(XSS);
  });

  it('las fuentes escapan cita y capítulo, y un índice no numérico no rompe el <li>', () => {
    const resp = respuesta();
    resp.fuentes = [
      {
        indice: '1" onload="alert(1)' as unknown as number,
        libro: 'Fundamentals',
        edicion: '5',
        capitulo: XSS,
        pagina: '204',
        cita: XSS_ATRIBUTO,
        citada: true,
      },
    ];
    const host = pintar(resp);

    expect(elementosInyectados(host)).toEqual([]);
    expect(atributosDeEvento(host)).toEqual([]);
    const li = host.querySelector('.ia-fuentes-lista li') as HTMLLIElement;
    expect(li.className).toBe('ia-fuente-citada');
    expect(li.textContent).toContain(XSS);
  });

  it('el nombre del modelo tampoco es de fiar', () => {
    const resp = respuesta();
    resp.modelo = XSS;
    const host = pintar(resp);

    expect(elementosInyectados(host)).toEqual([]);
    expect(host.querySelector('.ia-meta')?.textContent).toContain(XSS);
  });
});

describe('renderizar: la estructura que espera el CSS y el veterinario', () => {
  it('el aviso de fuera de alcance manda sobre el de derivación', () => {
    const host = pintar(respuesta({ fuera_de_alcance: true, requiere_derivacion: true }));

    expect(host.querySelector('.ia-aviso-alcance')).not.toBeNull();
    expect(host.querySelector('.ia-aviso-derivacion')).toBeNull();
  });

  it('la derivación obligatoria se anuncia cuando el servidor la marca', () => {
    const host = pintar(respuesta({ requiere_derivacion: true }));

    expect(host.querySelector('.ia-aviso-derivacion')?.textContent).toContain('valoración presencial');
  });

  it('sin avisos ni listas sólo queda la interpretación y la meta', () => {
    const host = pintar(respuesta());

    expect(host.querySelector('.ia-aviso-alcance')).toBeNull();
    expect(host.querySelector('.ia-aviso-derivacion')).toBeNull();
    expect(host.querySelector('.ia-hallazgos')).toBeNull();
    expect(host.querySelector('.ia-diferenciales')).toBeNull();
    expect(host.querySelector('.ia-fuentes')).toBeNull();
    expect(host.querySelector('.ia-interpretacion')?.textContent).toBe('Texto normal.');
    expect(host.querySelector('.ia-meta')?.textContent).toContain('Confianza: media');
  });

  it('el resumen de fuentes cuenta las citadas sobre el total', () => {
    const resp = respuesta();
    const fuente = (indice: number, citada: boolean) => ({
      indice,
      libro: 'Fundamentals',
      edicion: '5',
      capitulo: 'Eritrocitos',
      pagina: `${indice}0`,
      cita: `Fundamentals, cap. ${indice}`,
      citada,
    });
    resp.fuentes = [fuente(1, true), fuente(2, false), fuente(3, true)];
    const host = pintar(resp);

    expect(host.querySelector('.ia-fuentes summary')?.textContent).toBe(
      'Literatura consultada (2 de 3 citadas)',
    );
    expect(host.querySelectorAll('.ia-fuente-citada')).toHaveLength(2);
    expect(host.querySelectorAll('.ia-fuente-no-citada')).toHaveLength(1);
    // `value` numérico: es lo que numera la lista en la ruta de prosa, donde los [n] del texto
    // apuntan a esta numeración.
    expect((host.querySelector('.ia-fuentes-lista li') as HTMLLIElement).value).toBe(1);
  });

  it('un hallazgo sin comentario no arrastra el guion', () => {
    const host = pintar(
      respuesta({
        hallazgos_clave: [{ analito: 'ALT', direccion: 'alto', gravedad: 'moderado', comentario: '' }],
      }),
    );

    expect(host.querySelector('.ia-hallazgos li')?.textContent).toBe('ALT: alto · moderado');
  });
});
