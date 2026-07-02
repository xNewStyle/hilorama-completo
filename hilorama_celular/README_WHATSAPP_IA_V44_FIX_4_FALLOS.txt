Hilorama WhatsApp IA V44 - fix 4 fallos V43

Esta version corrige los 4 fallos que salieron en el tester dificil V43 de 150 casos:

1) Preguntas comerciales tipo "cuanto es lo menos por 50 madejas" ya no responden precio directo.
   Responde que se revisa/confirma para decision humana.

2) Mensajes de foto/ver tono, como "quiero ver el color 60 antes de pedir", no generan pedidos fantasma.

3) Foto de accesorios, como "quiero foto de los ojos 14mm", ahora responde con lenguaje de foto/imagen y mantiene contexto de ojos de seguridad.

4) Nariz flock + ojos negros se entiende como accesorios. Si despues dicen "para amigurumi chico", no cambia a recomendar Komfy Mini; conserva el contexto de nariz/ojos.

Prueba recomendada:
python hilorama_celular/tools/whatsapp_ia_human_tester_v44.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 150 --sleep 0.3
