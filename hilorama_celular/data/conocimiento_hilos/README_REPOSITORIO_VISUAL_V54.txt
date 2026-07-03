
REPOSITORIO VISUAL HILORAMA V54

Objetivo:
Que la IA use imágenes locales como base de datos visual: gamas de colores, tonos individuales, fichas técnicas, accesorios, envíos, pagos y promociones.

Ruta principal:
hilorama_celular/static/recursos_ia/repositorio_visual/

Qué debes hacer:
1. Pega tus imágenes dentro de la carpeta correspondiente.
2. Ejecuta:
   python hilorama_celular/tools/hilorama_reindexar_repositorio_visual.py
3. Sube cambios a GitHub/Render.
4. En el sistema, ejecuta el importador de static:
   /api/ia/recursos/importar-static?pin=TU_PIN

La IA registrará:
- gamas como carta_colores y grupo enviar_junto=True
- tonos como foto_tono individual
- fichas como ficha_producto
- accesorios como accesorio
- envíos como envio
- pagos como pago
- promociones como promocion

Nombres recomendados:
- tonos: 429.webp, 60_negro.jpg, 55_blanco.png
- gamas: gama_01.png, gama_02.png
- fichas: ficha_tecnica.png, composicion.png

Nota:
Aunque internamente el sistema guarda archivo_url, no es URL externa; es ruta local del servidor tipo /static/recursos_ia/...
