V10 - Biblioteca IA: prioridad a tono individual por código exacto

Corrige casos como:
- "me podrías mostrar el tono del Velluto 56"
- "foto del 56"
- "cómo se ve el color 56"

Antes podía mandar la gama completa porque detectaba la palabra "tono/colores".
Ahora, si hay un número y existe una foto individual en:
static/recursos_ia/Velluto Colores/<codigo>.webp
la IA debe mostrar esa foto individual antes que la gama.

Si el recurso no está en la base de datos pero el archivo físico existe, usa el archivo como respaldo.
