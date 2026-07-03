Repositorio visual local V55

Qué cambió:
- Se crearon carpetas por línea/tipo de Karina: BASICOS, ALIZE, PREMIUM, CALIDA, FANTASIA, DECORA.
- También se crearon carpetas para accesorios Karina.
- Las imágenes viejas de Velluto se copiaron a: hilos/KARINA/ALIZE/VELLUTO/.
- La IA NO usa carpetas vacías. Solo importa archivos de imagen reales.

Cómo agregar imágenes:
1) Mete carta de colores en gama/.
2) Mete fotos individuales en tonos/ usando código al inicio. Ejemplo: 429_tabaco_claro.webp
3) Mete fichas técnicas en ficha/.
4) Ejecuta:
   python hilorama_celular/tools/hilorama_reindexar_repositorio_visual.py
5) En Render importa a biblioteca IA:
   POST /api/ia/recursos/importar-static?pin=TU_PIN

Archivo de auditoría:
- data/conocimiento_hilos/karina_catalogo_investigado_v55.json
