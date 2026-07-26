"""Parser ASTM E1381/E1394 (LIS2-A2) genérico — Abaxis VetScan, Scil/Horiba.

Estructura de registros (delimitados por CR), campos por `|`, componentes por `^`:
  H = cabecera (instrumento)
  P = paciente
  O = orden/petición  → O-3 lleva el ID de muestra (accesión)
  R = resultado       → R-3 `^^^CODIGO`, R-4 valor, R-5 unidad, R-7 bandera anormal
  L = terminador

Cada registro O abre un Resultado; los R siguientes se le adjuntan. Puede haber varios O por
mensaje (varias muestras). Los dialectos exactos se afinan con capturas del equipo real.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from ..modelo import Observacion, PistasPaciente, Resultado


def _campos(registro: str) -> list[str]:
    return registro.split("|")


def _ultimo_componente(campo: str) -> str:
    # `^^^GLU` → `GLU`; `GLU` → `GLU`.
    partes = [p for p in campo.split("^") if p]
    return partes[-1] if partes else campo.strip()


def _primer_componente(campo: str) -> str:
    return campo.split("^", 1)[0].strip()


def _bandera(campo: str) -> Optional[str]:
    # Sólo interesan las banderas ANORMALES; 'N' (normal) o vacío → None.
    v = campo.strip().upper()
    return v if v and v != "N" else None


def _parsear_fecha(cadena: str) -> datetime:
    # ASTM: AAAAMMDDHHMMSS (longitud variable). Si falla, ahora().
    digitos = re.sub(r"\D", "", cadena or "")
    for fmt, n in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)):
        if len(digitos) >= n:
            try:
                return datetime.strptime(digitos[:n], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def parsear_astm(trama: str, instrumento_id: str = "astm", fabricante: Optional[str] = None) -> list[Resultado]:
    registros = [r for r in trama.replace("\r\n", "\r").replace("\n", "\r").split("\r") if r.strip()]

    resultados: list[Resultado] = []
    modelo: Optional[str] = None
    momento = datetime.now(timezone.utc)
    pistas = PistasPaciente()
    actual: Optional[Resultado] = None

    for registro in registros:
        tipo = registro[:1].upper()
        campos = _campos(registro)

        if tipo == "H":
            # H-5 suele ser `Nombre^Version` del instrumento; si no, H-4.
            crudo = (campos[4] if len(campos) > 4 else "") or (campos[3] if len(campos) > 3 else "")
            modelo = _primer_componente(crudo) or None
            if len(campos) > 13 and campos[13].strip():
                momento = _parsear_fecha(campos[13])

        elif tipo == "P":
            if len(campos) > 5 and campos[5].strip():
                pistas.nombre_mascota = campos[5].replace("^", " ").strip() or None
            if len(campos) > 8 and campos[8].strip():
                pistas.sexo = campos[8].strip()
            # La especie en veterinaria suele ir en un campo no estándar (P-13 relación/atributo).
            if len(campos) > 12 and campos[12].strip():
                pistas.especie_texto = _ultimo_componente(campos[12])

        elif tipo == "O":
            # O-3 (índice 2) = ID de muestra/espécimen; O-4 como respaldo.
            muestra = ""
            if len(campos) > 2 and campos[2].strip():
                muestra = _ultimo_componente(campos[2])
            elif len(campos) > 3 and campos[3].strip():
                muestra = _ultimo_componente(campos[3])
            actual = Resultado(
                muestra_id=muestra or (pistas.nombre_mascota or "SIN-ID"),
                instrumento_id=instrumento_id,
                observaciones=[],
                momento=momento,
                fabricante=fabricante,
                instrumento_modelo=modelo,
                pistas_paciente=pistas,
                formato_origen="astm",
            )
            resultados.append(actual)

        elif tipo == "R" and actual is not None:
            codigo = _ultimo_componente(campos[2]) if len(campos) > 2 else ""
            valor = _primer_componente(campos[3]) if len(campos) > 3 else ""
            unidad = campos[4].strip() if len(campos) > 4 else ""
            bandera = _bandera(campos[6]) if len(campos) > 6 else None
            if codigo and valor:
                actual.observaciones.append(
                    Observacion(codigo_prueba=codigo, valor=valor, unidad=unidad, bandera=bandera)
                )

    # Descarta órdenes sin observaciones.
    return [r for r in resultados if r.observaciones]
