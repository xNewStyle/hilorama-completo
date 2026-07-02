V48 - Fix tester largo y contexto humano

Corrige:
- Preguntas como "gracias, y el 429?" ya no generan pedido fantasma.
- Frases como "tienes otros tonos más claritos" ya no se cotizan como producto inventado.
- Frases como "busco algo para peluche, no quiero que quede duro" se tratan como recomendación, no pedido.
- Código inválido tipo "4299 o será 429" no truena el motor y no inventa producto.
- El modo tester devuelve tester_mode=true también si ocurre un error controlado, para no caer al simulador viejo.

También conserva el fix V47 de Envia.com payload / Render.

Comando sugerido:
python hilorama_celular/tools/whatsapp_ia_human_tester_v48.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 1000 --sleep 0.3
