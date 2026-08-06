// @vitest-environment jsdom
// Regresión del importador de PDF. Cubre las dos capas donde ha fallado:
//
//   1. La DECODIFICACIÓN del texto (pdf.js). Un informe real de laboratorio no se pudo importar
//      —«No se encontraron datos reconocibles en el PDF»— porque su CMap `ToUnicode` declara
//      destinos de UN byte (fuera de especificación, pero lo emiten productores reales tipo
//      Ghostscript) y pdf.js 3.11 los leía de dos en dos: cada carácter salía desplazado 8 bits,
//      'H' (0x48) como U+4800. Aquí se construye un PDF con esa misma anomalía y se fija que la
//      versión de pdf.js que vendorizamos lo decodifica bien.
//
//   2. El RECONOCIMIENTO sobre el texto ya decodificado (parsearTextoLab / parsearTextoPaciente).
//
// El texto de las pruebas de la capa 2 reproduce la MAQUETA del informe real (dot leaders,
// cabecera de sección + línea RESULTADO, párrafos interpretativos) con datos inventados: el
// informe original lleva nombre de propietario, clínica, dirección y nº de chip, y no tiene por
// qué entrar en el repositorio para fijar una regresión de parseo.

import { describe, it, expect } from 'vitest';
import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs';
import { parsearTextoLab, parsearTextoPaciente } from '../src/pdf-parser.js';

// --- Capa 1: decodificación -----------------------------------------------------------------

/** PDF mínimo cuyo `ToUnicode` usa destinos de un byte (`<48><48><48>` en vez de `<48><48><0048>`). */
function pdfConToUnicodeDefectuoso(lineas: string[]): Uint8Array {
  const usados = [...new Set(lineas.join('').split(''))].filter((c) => c !== ' ');
  const bfchar = usados
    .map((c) => {
      const hex = c.charCodeAt(0).toString(16).padStart(2, '0');
      return `<${hex}><${hex}>`;  // ← destino de UN byte: la anomalía que se quiere reproducir
    })
    .join('\n');
  const cmap = `/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CMapType 2 def
1 begincodespacerange
<00><ff>
endcodespacerange
${usados.length} beginbfchar
${bfchar}
endbfchar
endcmap
CMapName currentdict /CMap defineresource pop
end end`;

  const escapar = (s: string) => s.replace(/[\\()]/g, (c) => `\\${c}`);
  const contenido = `BT /F1 10 Tf 40 750 Td 14 TL\n${lineas
    .map((l) => `(${escapar(l)}) Tj T*`)
    .join('\n')}\nET`;

  const objetos = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
      + '/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>',
    `<< /Length ${contenido.length} >>\nstream\n${contenido}\nendstream`,
    `<< /Length ${cmap.length} >>\nstream\n${cmap}\nendstream`,
  ];

  let pdf = '%PDF-1.4\n';
  const offsets: number[] = [];
  objetos.forEach((cuerpo, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${cuerpo}\nendobj\n`;
  });
  const inicioXref = pdf.length;
  pdf += `xref\n0 ${objetos.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) pdf += `${String(off).padStart(10, '0')} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objetos.length + 1} /Root 1 0 R >>\nstartxref\n${inicioXref}\n%%EOF\n`;

  return Uint8Array.from(pdf, (c) => c.charCodeAt(0));
}

async function extraer(datos: Uint8Array): Promise<string> {
  const doc = await pdfjs.getDocument({ data: datos }).promise;
  const paginas: string[] = [];
  for (let p = 1; p <= doc.numPages; p++) {
    const contenido = await (await doc.getPage(p)).getTextContent();
    // Mismo ensamblado que `extraerTextoPdf` en src/pdf-parser.ts.
    paginas.push(
      contenido.items
        .map((i) => ('str' in i ? i.str + (i.hasEOL ? '\n' : ' ') : ''))
        .join(''),
    );
  }
  return paginas.join('\n');
}

describe('decodificación de PDF con ToUnicode defectuoso', () => {
  it('lee los caracteres sin desplazarlos 8 bits', async () => {
    const texto = await extraer(
      pdfConToUnicodeDefectuoso(['HEMATOCRITO...... 48,1 %', 'ALT-GPT......... 260 U/L']),
    );

    expect(texto).toContain('HEMATOCRITO');
    expect(texto).toContain('ALT-GPT');
    // El síntoma exacto de la regresión: 'H' saliendo como U+4800 y ',' como U+2C00.
    expect(texto).not.toContain('䠀');
    expect(texto).not.toContain('Ⰰ');
  });

  it('conserva los ceros (el 0 desplazado caía en U+3000 y se normalizaba a espacio)', async () => {
    const texto = await extraer(pdfConToUnicodeDefectuoso(['ALT-GPT......... 260 U/L']));

    // Este es el motivo por el que el desplazamiento NO se repara a posteriori: perder los ceros
    // convierte una ALT de 260 U/L en 26, que es un resultado normal.
    expect(texto).toContain('260');
    expect(parsearTextoLab(texto).alt).toBe(260);
  });
});

// --- Capa 2: reconocimiento -----------------------------------------------------------------

// Maqueta del informe: etiqueta + líderes de puntos con el valor en la misma línea (hemograma) o
// cabecera de sección con el valor en una línea RESULTADO posterior (bioquímica).
const INFORME = `Datos personales
LUNA
Perra, Canis lupus familiaris
PRUEBA RESULTADO UNIDADES VAL.DE REFERENCIA
HEMOGRAMA
Contaje y Fórmula Electrónico
HEMATOCRITO...................... 48,1 % (37,0-55,0)
HEMOGLOBINA...................... 17,7 g/dL (12,0-20,0)
HEMATÍES......................... 7.300.000 /µL (5.100.000-8.000.000)
PLAQUETAS........................ 171.000 /µL (200.000-500.000)
FÓRMULA LEUCOCITARIA
LEUCOCITOS....................... 7.510 /µL (4.900-21.700)
EOSINÓFILOS...................... 5 %
BASÓFILOS........................ 0 %
LINFOCITOS....................... 29 %
SEGMENTADOS...................... 59 %
UREA / SUERO
Química seca - Espectrofotometría Ultravioleta-Visible
RESULTADO........................ 67 mg/dL (11-53)
CREATININA / SUERO
Química seca - Espectrofotometría Ultravioleta-Visible
RESULTADO........................ 1,73 mg/dL (0,50-1,60)
PROTEÍNAS TOTALES / SUERO
Química seca - Espectrofotometría Ultravioleta-Visible
RESULTADO........................ 76 g/L (47-68)
COCIENTE ALBÚMINA / GLOBULINA
Química seca - Espectrofotometría Ultravioleta-Visible
ALBUMINA......................... 40 g/L (24-40)
GLOBULINAS TOTALES............... 36,00 g/L (21,00-35,00)
RESULTADO........................ 1,11 (0,70-1,50)
ALT-GPT
Química seca - Espectrofotometría Ultravioleta-Visible
RESULTADO........................ 260 U/L (21-79)
SDMA (Dimetilarginina simétrica)
Inmunoturbidimetría
RESULTADO........................ 12,6 µg/dL (<15,0)
Interpretación:
El aumento de SDMA en suero o plasma es un indicador temprano de reducción de la
funcionalidad renal. IRIS recomienda valorar los resultados de SDMA junto a otros
parámetros; entre ellos UPC, Creatinina, presión arterial y densidad urinaria.
CREATINKINASA
Química seca - Espectrofotometría Ultravioleta-Visible
RESULTADO........................ 90 U/L (<300)
`;

describe('parsearTextoLab sobre la maqueta de informe español', () => {
  const r = parsearTextoLab(INFORME);

  it('lee los valores de la misma línea', () => {
    expect(r.hct).toBe(48.1);
    expect(r.hgb).toBe(17.7);
    expect(r.wbc).toBe(7.51);
    expect(r.plt).toBe(171);
  });

  it('lee los valores que van en la línea RESULTADO bajo su cabecera', () => {
    expect(r.creat).toBe(1.73);
    expect(r.alt).toBe(260);
    expect(r.sdma).toBe(12.6);
    expect(r.prot).toBe(7.6);              // 76 g/L → g/dL
    expect(r.bun).toBeCloseTo(31.29, 1);   // urea 67 mg/dL → BUN
  });

  it('reconoce los nombres acentuados en mayúsculas', () => {
    expect(r.rbc).toBe(7.3);      // HEMATÍES
    expect(r.eosino).toBe(5);     // EOSINÓFILOS
    expect(r.linfo).toBe(29);
  });

  it('reconoce SEGMENTADOS como neutrófilos', () => {
    expect(r.neutro).toBe(59);
  });

  it('conserva un 0 legítimo de la fórmula leucocitaria', () => {
    expect(r.baso).toBe(0);
  });

  it('no confunde el analito con el cociente calculado a partir de él', () => {
    // Bajo «COCIENTE ALBÚMINA / GLOBULINA» la línea RESULTADO es el cociente A/G (1,11); la
    // albúmina y las globulinas están en sus propias líneas, encima.
    expect(r.alb).toBe(4);        // 40 g/L → g/dL
    expect(r.glob).toBe(3.6);     // 36 g/L → g/dL
  });

  it('no inventa un analito citado de pasada en un párrafo interpretativo', () => {
    // «densidad urinaria» aparece en la interpretación del SDMA. El valor más cercano es el de
    // la CREATINKINASA, dos líneas más abajo: importarlo daría una densidad urinaria de 90 en
    // una analítica que no incluye orina.
    expect(r.usg).toBeUndefined();
  });
});

describe('parsearTextoPaciente', () => {
  it('deduce especie y sexo del nombre científico y del género gramatical', () => {
    expect(parsearTextoPaciente(INFORME)).toMatchObject({ especie: 'Canino', sexo: 'Hembra' });
  });

  it('la etiqueta explícita manda sobre la deducción', () => {
    const p = parsearTextoPaciente('Especie: Felino\nSexo: Macho\nEl perro del vecino');
    expect(p).toMatchObject({ especie: 'Felino', sexo: 'Macho' });
  });
});
