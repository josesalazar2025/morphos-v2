# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Morphos is a veterinary diagnostic support tool — a single-page application (SPA) that performs real-time clinical pattern detection from lab values and optionally calls an AI model (HuggingFace or local Ollama) for clinical interpretation. It targets Canino and Felino patients.

## Running the App

This is a static frontend with a PHP proxy backend. No build step required.

Serve it locally with PHP's built-in server from the project root:
```bash
php -S localhost:8000
```

Then open `http://localhost:8000` in a browser. The PHP proxy (`api/hf_proxy.php`) requires the API key in `api/.env`:
```
HF_API_KEY=<your_key>
```

For local AI inference, Ollama must be running at `http://localhost:11434` with `medgemma:latest` pulled.

## Architecture

### Data Flow

```
User form input
  → analisis.js (real-time pattern detection, no server)
  → UI updates (color-coded fields, pattern cards)

User clicks "Análisis IA"
  → ia.js (constructs prompt with patient data + flagged values)
  → [HF route]    → api/hf_proxy.php → HF Space Gradio API (SSE response)
  → [Local route] → Ollama chat completions API
  → Display AI output in #salida-ia
```

### Key Files and Their Roles

- **`js/analisis.js`** — Core engine (505 lines). Compares values against species-specific reference ranges, classifies severity (mild/moderate/severe), applies age/breed/sex adjustments, and identifies 50+ clinical patterns (anemia types, hepatic, renal, endocrine, etc.).
- **`js/ia.js`** — AI abstraction layer. Builds the clinical prompt in Spanish, calls either HF Proxy or Ollama, and strips model-specific tokens from the response.
- **`js/main.js`** — Orchestration: loads JSON data files, wires form events, triggers analysis, handles PDF export.
- **`js/ui.js`** — Tab navigation (8 panels, 4 exam sub-tabs), swipe gestures, mobile/desktop field sync, collapsible panels.
- **`js/pdf-parser.js`** — Client-side PDF extraction using PDF.js. 47 regex patterns to identify analytes in Spanish/English. Runs fully in the browser.
- **`api/hf_proxy.php`** — PHP proxy that reads `api/.env`, forwards requests to HugginFace Space (`blackmistcode-morphos-medgemma.hf.space/gradio_api`), handles SSE polling, and returns `{text: ...}`.
- **`data/valores_referencia.json`** — Reference ranges for 34 analytes per species.
- **`data/alteraciones.json`** — 100+ clinical entities used to enrich AI prompts with etiologic context.

### AI Backend Configuration

Stored in `localStorage`:
- `mx-ia-backend`: `"hf"` (default) or `"local"`
- `mx-ia-ollama-url`: custom Ollama endpoint
- `mx-ia-ollama-model`: custom model name (default `medgemma:latest`)

The HF route supports up to 4 images (vision model). The local route uses Ollama's OpenAI-compatible chat completions API, also with vision support.

### Pattern Detection Logic (`analisis.js`)

Severity thresholds are based on deviation from the reference range. Reference ranges are dynamically adjusted for:
- **Age**: puppies, adults, seniors, geriatric (age in months)
- **Breed**: Greyhounds (lower platelets normal), Akita/Shiba (different RBC ranges), etc.
- **Sex**: Male felines have a higher creatinine tolerance

The `analizarResultados()` function is called on every `input` event and returns flagged findings + matched clinical patterns.

### CSS Notes

Do not use `!important` — use specificity or cascade ordering instead. The stylesheet is `css/styles.css` (1796 lines). The desktop grid breakpoint is `>1100px`.

### Coding notes

All variables should be named in spanish unless they're referencing common technical names like tab, input, output, etc.
Always use descriptive names for variables and functions keeping legibility as a priority.
Don't use aligment spaces.
