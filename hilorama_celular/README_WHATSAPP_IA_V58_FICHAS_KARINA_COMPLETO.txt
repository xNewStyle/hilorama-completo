V58 - Fichas técnicas locales Karina completas por estructura

Qué trae:
- karina_productos.json con todos los productos visibles del catálogo de Estambres Karina páginas 1-9.
- ficha_tecnica.json dentro de cada carpeta de producto.
- fichas confirmadas para Velluto, Komfy Mini, Komfy Plus, Kurumi, Kotton Milk y Cristy Liso.
- Komfy queda creado con datos parciales y marcado como pendiente para no inventar metraje/composición si falta confirmar.
- Los demás productos quedan creados como ficha pendiente: la IA sabe que existen, pero no debe inventar composición, metraje, gancho o agujas.

Cómo completar una ficha:
1) Abre static/recursos_ia/repositorio_visual/hilos/KARINA/LINEA/PRODUCTO/ficha/ficha_tecnica.json
2) Llena composicion, peso_bola, metraje, gancho_recomendado, agujas_recomendadas y usos_recomendados.
3) Cambia datos_tecnicos_confirmados a true.
4) Corre:
   python hilorama_celular/tools/hilorama_reindexar_fichas_tecnicas.py
   python hilorama_celular/tools/hilorama_reindexar_repositorio_visual.py

Importante:
Si datos_tecnicos_confirmados=false, la IA debe responder que la ficha técnica está pendiente y no inventar.
