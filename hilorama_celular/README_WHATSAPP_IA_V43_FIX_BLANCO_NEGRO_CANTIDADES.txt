# WhatsApp IA V43 - Fix blanco/negro con cantidades separadas

Resultado V42: 29/30.

Fallo corregido:
- "ocupo blanco y negro, 2 y 4, de velluto" ya no toma 2 y 4 como códigos.
- Debe interpretar: Blanco x2 y Negro x4 en Velluto.

Uso:
1. Copiar la carpeta hilorama_celular encima de la actual.
2. Subir a GitHub/Render.
3. Probar:

python hilorama_celular/tools/whatsapp_ia_human_tester_v43.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 30 --sleep 0.3

Luego:
python hilorama_celular/tools/whatsapp_ia_human_tester_v43.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 150 --sleep 0.3
