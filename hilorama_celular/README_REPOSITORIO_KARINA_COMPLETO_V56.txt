V56 - Repositorio visual Karina más completo

Ahora no se considera que Karina solo maneje Velluto/Komfy/Kurumi.
Se crearon carpetas locales para los productos visibles en el catálogo público de Estambres Karina, agrupados por línea aproximada:

- ALIZE
- BASICOS
- CALIDA
- DECORA
- FANTASIA
- PREMIUM
- NUEVOS_Y_SIN_CLASIFICAR

Cada producto tiene:
  gama/  = cartas de color o catálogo completo
  tonos/ = fotos individuales por código o tono
  ficha/ = imagen o ficha técnica del hilo

IMPORTANTE:
La IA NO debe usar carpetas vacías. El indexador solo registra archivos de imagen reales:
.png .jpg .jpeg .webp .jfif .gif

Flujo para Jorge:
1. Descargar o guardar las imágenes permitidas como distribuidor.
2. Pegarlas en la carpeta correcta.
3. Ejecutar:
   python hilorama_celular/tools/hilorama_reindexar_repositorio_visual.py
4. Subir a GitHub y en Render importar recursos si aplica.

Archivo índice de catálogo creado:
  hilorama_celular/data/conocimiento_hilos/karina_catalogo_completo_v56.json

No depende de URLs externas. Las imágenes deben vivir localmente en static/recursos_ia/repositorio_visual/.
