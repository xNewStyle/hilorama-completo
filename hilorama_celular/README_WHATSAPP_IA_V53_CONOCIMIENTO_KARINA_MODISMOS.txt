V53 - Conocimiento Karina + modismos mexicanos + tester humano

Qué agrega:
1. Base de conocimiento editable en:
   hilorama_celular/data/conocimiento_hilos/

Archivos principales:
- karina_productos.json
  Fichas técnicas iniciales de Velluto, Komfy Mini, Komfy Plus, Kurumi y Kotton Milk.
  Incluye composición, gramos, metraje, ganchos/agujas, usos recomendados y colores.

- modismos_ventas_mexico.json
  Frases mexicanas de venta y reglas para interpretar intención.

- respuestas_humanas_ventas.json
  Plantillas editables de respuesta.

- karina_recursos_descargados.json
  Índice que se llena cuando se descargan imágenes oficiales.

2. La IA ahora puede responder preguntas como:
   - con qué gancho se teje Velluto?
   - de qué está hecho Komfy Mini?
   - cuántos metros trae Kurumi?
   - Velluto o Kurumi para amigurumi?
   - me muestras el 56, 429 y 550?

3. Herramientas nuevas:
   Descargar recursos oficiales de Karina:
   python hilorama_celular/tools/karina_descargar_recursos.py --producto velluto --limite 20

   Solo crear índice sin descargar:
   python hilorama_celular/tools/karina_descargar_recursos.py --producto velluto --limite 20 --solo-indice

   Anexar un hilo manualmente:
   python hilorama_celular/tools/karina_anexar_producto.py

4. Tester nuevo:
   python hilorama_celular/tools/whatsapp_ia_human_tester_v53.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100 --sleep 0.3

   Casos externos:
   hilorama_celular/tools/casos_tester_v53_conocimiento_karina_humano.json
   Tiene 1000 conversaciones con preguntas técnicas, modismos, fotos, recomendaciones y pedidos.

Notas:
- Jorge indicó que como distribuidor puede usar imágenes de Karina como referencia de color.
- Las fichas quedan como base editable; lo que no esté en Karina se puede anexar manualmente.
- Las imágenes se guardan en static/recursos_ia/karina/<producto>/ cuando se ejecuta el script.
- La IA conserva el fix de envíos en hilo/conversación de V52.
