V53 - Base de conocimiento Hilorama/Karina

Archivos:
- karina_productos.json: fichas técnicas y colores.
- modismos_ventas_mexico.json: frases mexicanas y reglas de intención.
- respuestas_humanas_ventas.json: plantillas editables.
- karina_recursos_descargados.json: índice de imágenes descargadas por el script.

Para anexar datos que falten:
python hilorama_celular/tools/karina_anexar_producto.py

Para descargar imágenes oficiales de Karina a static/recursos_ia/karina:
python hilorama_celular/tools/karina_descargar_recursos.py --producto velluto --limite 10

Nota: Jorge indicó que, como distribuidor, puede usar imágenes de Karina como referencia de color. Aun así, el script conserva la URL fuente para auditoría.
