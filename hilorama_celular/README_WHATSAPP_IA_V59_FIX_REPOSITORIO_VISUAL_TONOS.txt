V59 - Fix repositorio visual local para fotos de tonos

Problema detectado:
- La IA sí detectaba la intención pide_foto_tono cuando el cliente decía: "me muestras el 56, 429 y 550".
- Pero el buscador de recurso exacto todavía usaba reglas viejas:
  1) No reconocía bien la palabra "muestras" en app.py.
  2) Buscaba principalmente el grupo viejo tono_velluto_56 y la carpeta vieja /Velluto Colores/.
  3) El repositorio nuevo genera grupos como tono_alize_velluto_56 y rutas /repositorio_visual/.../tonos/56.webp.
  4) Si no se había importado la tabla ia_recursos en Render, no tenía fallback directo al repositorio_visual.
  5) Solo estaba preparado para regresar 1 tono, no varios tonos juntos.

Qué corrige:
- Reconoce frases: muestra, muestras, muestres, muestrame, mándame, mandas, enséñame, etc.
- Busca tonos en ia_recursos y también directamente en:
  static/recursos_ia/repositorio_visual/hilos/**/tonos/<codigo>.*
- Soporta varios códigos en una sola respuesta.
- Agrega endpoint de debug:
  /api/ia/recursos/debug-tonos?texto=me%20muestras%20el%2056,%20429%20y%20550&pin=TU_PIN

Resultado esperado:
Cliente: me muestras el 56, 429 y 550?
IA: Claro 😊 le comparto fotos/imágenes de los tonos 56, 429, 550.
📎 Recursos para enviar
1. /static/recursos_ia/repositorio_visual/hilos/KARINA/ALIZE/VELLUTO/tonos/56.webp
2. /static/recursos_ia/repositorio_visual/hilos/KARINA/ALIZE/VELLUTO/tonos/429.webp
3. /static/recursos_ia/repositorio_visual/hilos/KARINA/ALIZE/VELLUTO/tonos/550.webp
