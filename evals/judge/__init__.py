"""Jueces LLM de la suite de evals (rúbrica clínica y relevancia de recuperación)."""

from __future__ import annotations


class ErrorJuez(Exception):
    """Fallo al invocar un juez o al validar su salida.

    Vive aquí, y no en el módulo de un transporte concreto, para que el runner pueda
    capturar por igual el fallo del juez local, el del CLI y el del SDK: para las evals,
    «el juez no pudo puntuar este caso» es la misma situación venga de donde venga.
    """
