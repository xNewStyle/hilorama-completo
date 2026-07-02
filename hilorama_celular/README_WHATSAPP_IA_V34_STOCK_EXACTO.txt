Hilorama WhatsApp IA V34 - Stock exacto por color

Corrige los 5 fallos restantes del tester V33/V34:

- En consultas exactas de stock como "¿Tiene Komfy Mini lila?" ya no ofrece tonos parecidos automáticamente.
- Separa colores específicos como cielo, turquesa y lila de familias amplias como azul/morado.
- Evita responder "Cielo" cuando la clienta pidió "Turquesa".
- Si un color exacto está sin stock, responde de forma humana y directa: "Por el momento no me aparece disponible...".
- No cambia precios, no genera guías, no usa apartados.

Prueba sugerida:
python tools\whatsapp_ia_mass_tester_v34.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100
