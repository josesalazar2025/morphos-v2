// Tipos compartidos del motor de análisis clínico.
// Nombres en español por convención del proyecto (ver CLAUDE.md).

export type Especie = 'canino' | 'felino';
export type Direccion = 'alto' | 'bajo';
export type Gravedad = 'leve' | 'moderado' | 'grave';

export interface Paciente {
  especie: Especie | null;
  raza: string | null;
  edadMeses: number | null;
  sexo: string | null;
}

export interface RangoReferencia {
  inferior: number;
  superior: number;
  unidad: string;
  nombre: string;
}

// Referencias por especie: cada analito se identifica por su clave (rbc, hgb, alt…).
export type ReferenciasEspecie = Record<string, RangoReferencia>;
export type Referencias = Record<string, ReferenciasEspecie>;

// El catálogo de alteraciones tiene forma heterogénea (descripciones planas,
// anidadas por especie, con etiologías o placeholders {ratio}); se tipa laxo.
export type Alteraciones = Record<string, any>;

export interface Hallazgo {
  clave: string;
  nombre: string;
  valor: number;
  unidad: string;
  direccion: Direccion;
  gravedad: Gravedad;
}

export interface Patron {
  nombre: string;
  descripcion: string;
  gravedad: Gravedad;
  parametros: string[];
}

export interface ResultadoAnalisis {
  hallazgos: Hallazgo[];
  patrones: Patron[];
}

// Los valores del formulario llegan como número o string (input HTML) o vacíos.
export type ValoresFormulario = Record<string, number | string | null | undefined>;

// Reglas clínicas compartidas con el motor del servidor: data/ajustes_clinicos.json.
// Los campos que empiezan por `_` son documentación (procedencia bibliográfica) y se ignoran.
export type FactorRango = { inferior?: number; superior?: number };
export type TablaAjustes = Record<string, FactorRango>;
export type CortesGravedad = { leve_hasta: number; moderado_hasta: number | null };
export type GrupoRaza = { razas: string[]; ajustes: TablaAjustes };

export interface AjustesClinicos {
  umbrales_gravedad: { leve: number; moderado: number };
  limites_edad_meses: Partial<Record<Especie, Record<string, number>>>;
  cortes_gravedad_bajo: Record<string, Partial<Record<Especie, CortesGravedad>>>;
  cortes_gravedad_alto: Record<string, Partial<Record<Especie, CortesGravedad>>>;
  ajustes_edad: Partial<Record<Especie, Record<string, TablaAjustes>>>;
  ajustes_raza: Partial<Record<Especie, GrupoRaza[]>>;
  ajustes_sexo: Partial<Record<Especie, Record<string, TablaAjustes>>>;
  iris: {
    cortes_creatinina: Partial<Record<Especie, number[]>>;
    cortes_sdma: Partial<Record<Especie, number[]>>;
    cortes_upc: Partial<Record<Especie, number[]>>;
  };
}
