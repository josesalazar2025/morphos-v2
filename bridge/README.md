# Puente local Morphos (bridge)

Lee los analizadores de laboratorio en la LAN de la clínica y reenvía los resultados
normalizados a la API de Morphos (que corre en HF Spaces) por HTTPS autenticado. Es un
proyecto **uv independiente** del backend: sus dependencias de serie/HL7 no entran en la
imagen desplegada.

```
analizador → transporte (serie/MLLP) → parser (ASTM/HL7) → normalizador → reenviador → POST /api/lab/ingesta
```

## Instalar y ejecutar

```bash
cd bridge
uv sync
cp .env.example .env      # edita MORPHOS_BRIDGE_URL, API_KEY y el transporte
uv run python -m bridge.main
```

La `API_KEY` debe ser una de las claves configuradas en el backend (`MORPHOS_LAB_API_KEYS`).

Ejecutar como servicio: envuelve `uv run python -m bridge.main` en una unidad systemd (o un
contenedor) en un equipo de la clínica que esté en la misma red que el analizador.

### Conectar varios equipos a la vez

Declara `MORPHOS_BRIDGE_INSTRUMENTOS` como una lista JSON (una línea) — un puente atiende a
todos en paralelo, cada uno con su parser por fabricante:

```
MORPHOS_BRIDGE_INSTRUMENTOS=[
  {"fabricante":"bionote","transporte":"mllp","instrumento_id":"vcheck-1","puerto":2575},
  {"fabricante":"abaxis","transporte":"serie","instrumento_id":"vetscan-1","serie_puerto":"/dev/ttyUSB0"},
  {"fabricante":"horiba","transporte":"serie","instrumento_id":"micros-1","serie_puerto":"/dev/ttyUSB1"}
]
```

El `fabricante` selecciona automáticamente el adaptador (Bionote→HL7, Abaxis/Horiba→ASTM) y,
en el backend, la tabla `data/lab_mapeos/<fabricante>.json`. En el analizador, configura el
destino: los de MLLP apuntan a `IP-del-puente:puerto`; los de serie se cablean al puerto USB/RS-232.

## Equipos soportados (alcance actual)

| Equipo | Protocolo | Transporte | Adaptador |
|--------|-----------|------------|-----------|
| Bionote Vcheck V200 | HL7 v2.6 PCD-01 | MLLP/TCP | `adaptadores/hl7v2.py` |
| Abaxis VetScan (VS2) | ASTM E1394 (configurar salida **ASTM**, no ASCII/XML) | serie | `adaptadores/astm_generico.py` |
| Scil / Horiba | ASTM E1394 | serie | `adaptadores/astm_generico.py` |

IDEXX queda fuera de alcance por ahora.

## Checklist de validación con el equipo real (por analizador)

El parseo genérico y las tablas de mapeo se **finalizan con capturas reales** — no se puede
cerrar sólo desde código:

1. Capturar 3–5 corridas reales (log del puerto serie, o pcap del MLLP).
2. Confirmar los parámetros: **serie** → baudios/paridad/bits; **MLLP** → IP/puerto y que el
   equipo espera ACK.
3. Confirmar **qué campo lleva el ID de muestra** (OBR-3 en HL7; O-3 en ASTM) y que coincide
   con lo que el veterinario teclea/escanea en Morphos.
4. Confirmar las **unidades** reportadas y los **códigos de prueba** (OBX-3 / R-3); añadir los
   que falten a `data/lab_mapeos/<fabricante>.json` en el backend (mira los `no_mapeados` que
   devuelve la ingesta).

## Pruebas

```bash
uv run pytest        # parsers (HL7/ASTM) + fiabilidad del reenviador (spool/retry)
```

Las pruebas usan fixtures capturadas; la corrección final contra el hardware es manual (ver
checklist).
