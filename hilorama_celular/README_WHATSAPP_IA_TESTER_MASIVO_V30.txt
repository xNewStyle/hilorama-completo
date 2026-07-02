Hilorama WhatsApp IA - Tester masivo V30
========================================

Esta versión adapta el tester masivo a la versión reciente ajustada por Codex.

Qué agrega:
- tester_mode / dry_run en /api/whatsapp-ia/simular.
- No guarda conversaciones falsas.
- No altera memoria real.
- No programa cierres diferidos reales.
- No crea decisiones pendientes reales durante pruebas.
- Permite simular varios turnos pasando memoria en el JSON.
- Incluye script: tools/whatsapp_ia_mass_tester_v30.py

Uso recomendado después de subir a Render:

1) Probar 50 o 100 casos:
python tools\whatsapp_ia_mass_tester_v30.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100

2) Si todo responde bien, probar 500:
python tools\whatsapp_ia_mass_tester_v30.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 500 --sleep 0.15

3) Luego 1000:
python tools\whatsapp_ia_mass_tester_v30.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 1000 --sleep 0.15

4) Solo cuando esté estable, 10000:
python tools\whatsapp_ia_mass_tester_v30.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 10000 --sleep 0.1

Reportes:
- wa_tester_reports/wa_test_report_*.html
- wa_tester_reports/wa_test_failures_*.csv
- wa_tester_reports/wa_test_results_*.json

Mándale a ChatGPT el CSV de fallos para corregir el agente con evidencia.

Notas:
- El tester puede gastar OpenAI porque consulta tu agente real.
- Empieza con 100, no con 10000.
- Si el servidor no devuelve tester_mode=true, el script se detiene para no ensuciar datos.
