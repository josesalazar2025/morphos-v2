"""Contrato de adaptador.

Un adaptador toma una trama cruda (ya desframeada por la capa de transporte) y devuelve
cero o más `Resultado`. La separación transporte↔adaptador permite que Abaxis/Horiba/Bionote
reusen el mismo transporte (serie o MLLP) y difieran sólo en el parseo.
"""

from __future__ import annotations

from typing import Callable

from ..modelo import Resultado

# Un parser es simplemente: (trama: str) -> list[Resultado].
Parser = Callable[[str], list[Resultado]]
