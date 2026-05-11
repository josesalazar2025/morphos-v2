# Uso de inteligencia artificial en el desarrollo de Morphos
## Proyecto final — Curso de Desarrollo Web 2026

---

## Modelo utilizado

Se utilizó exclusivamente Claude Code (Sonnet 4.6) de Anthropic como asistente de desarrollo a lo largo de todo el proyecto.

---

## Enfoque: Spec Driven Development

El uso de IA no consistió en generar código y aceptarlo sin más. Se aplicó un enfoque de desarrollo guiado por especificaciones: en cada paso se definió primero el comportamiento esperado, funciones base, las restricciones de diseño y los criterios de aceptación, y el modelo generó propuestas dentro de ese marco. La arquitectura, la separación de módulos, las decisiones de estructura y el flujo de datos fueron definidos y controlados por mi parte en todo momento gracias a los criterios y conocimientos adquiridos durante el curso.

El modelo actuó como ejecutor de decisiones ya tomadas, no como tomador de decisiones.

---

## Literatura de referencia en patología clínica veterinaria

Para el motor de detección de patrones (`analisis.js`) y los datos de referencia (`valores_referencia.json`, `alteraciones.json`), se proporcionó al modelo literatura especializada en patología clínica veterinaria como contexto de generación.

Los rangos de referencia por especie, los ajustes por edad, raza y sexo, las descripciones clínicas de cada alteración, y la lógica de clasificación de gravedad fueron **validados gracias a mi formación y experiencia profesional en Medicina Veterinaria**, antes de ser incorporados al código. El modelo fue un medio para estructurar y codificar ese conocimiento, no la fuente del mismo.

Textos de referencia utilizados:
- Thrall,  *Veterinary Hematology and Clinical Chemistry*, 3.ª ed. 2022
- Weiss, — *Schalm's Veterinary Hematology*, 7.ª ed. 2022
---

## Afinamiento del prompt y control de salidas del modelo de IA

Morphos utiliza medGemma como modelo de interpretación clínica. Durante el desarrollo se detectó que el modelo producía salidas con problemas recurrentes:

- Respuestas en inglés a pesar de instrucciones en español
- Tokens de control expuestos en la salida (`<start_of_turn>`, `<unused94>`, `<unused95>`)
- Bloques de LaTeX embebidos en la respuesta
- Párrafos repetidos en bucle al acercarse al límite de tokens
- Prefijos de rol visibles al inicio del texto

Se iteró sobre el prompt y se implementó una función de limpieza de salida (`limpiarRespuesta` en `ia.js`) que elimina estos artefactos antes de mostrar el resultado al usuario. El prompt final incluye restricciones explícitas de idioma, alcance clínico y formato de respuesta.

---

## Caché y optimización de rendimiento

Durante las auditorías de rendimiento con Lighthouse se identificó que la carga de fuentes tipográficas locales y librerías (PDF.js) afectaba negativamente las métricas. Se implementaron las siguientes mejoras, asistidas por el modelo:

- Directivas `preload` y `preconnect` en el `<head>` para recursos críticos
- Caché de larga duración para fuentes, CSS y JS en `.htaccess`
- Caché en disco de 30 minutos para las respuestas de la API de PubMed, evitando llamadas repetidas a la misma consulta
- Compresión gzip habilitada por tipo de contenido

---

## Auditoría final de código

Al concluir el desarrollo se realizó una auditoría asistida por IA con los siguientes objetivos:

**Código muerto**
- Identificación y eliminación de exportaciones sin consumidores y código que ya no era necesario o era experimental

**Seguridad**
- Protección de archivos sensibles (`.env`, `setup.php`) mediante `.htaccess`
- Sanitización de datos externos de APIs con `textContent` en lugar de `innerHTML`, eliminando el riesgo de XSS
- Validación de URLs externas antes de usarlas como atributos `href`
- Separación del nombre de usuario del SVG estático al actualizar el botón de sesión, evitando inyección de HTML desde la base de datos

---
