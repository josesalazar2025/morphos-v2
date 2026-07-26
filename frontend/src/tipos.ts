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
