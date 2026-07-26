"""Limitación de tasa (slowapi) por IP.

Cubre el agujero de la versión PHP (sin rate limiting en ningún sitio): el endpoint de
IA (costoso, quema la cuota HF), el login (fuerza bruta) y papers (abuso de PubMed).
Los límites concretos son configurables en config.py.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
