HILORAMA WHATSAPP IA V40 - FIX FINAL OJOS/GANCHOS

Resultado base recibido:
- V39 pasó 49/50 (98%).
- Falló solo v39_accesorio_ojo_followup porque la respuesta decía "Ojo Negro" pero no incluía la palabra "seguridad".
- También se reforzó un fallo escondido: cuando la clienta decía "ocupo del 4.5 y del 5" después de hablar de ganchos, la IA podía tratar 4 y 5 como códigos de hilo y responder "Si x5".

Cambios V40:
1) En ojos: siempre responder como "ojos de seguridad" si el cliente preguntó por ojo/ojos/seguridad.
2) En seguimiento de accesorios: "bolsa de 100 cuánto" conserva el contexto de ojos de seguridad.
3) En ganchos/agujas: medidas como 4.5, 5, 7 mm ya no se tratan como códigos de hilo.
4) El tester V40 mantiene los 50 casos y endurece el caso de ganchos para detectar respuestas tipo "Si x5".

Cómo probar local o Render:
python hilorama_celular/tools/whatsapp_ia_human_tester_v40.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 50 --sleep 0.2

Los reportes salen en:
wa_tester_reports
