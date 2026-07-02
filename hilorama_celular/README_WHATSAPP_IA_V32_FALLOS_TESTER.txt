Hilorama WhatsApp IA V32 - Corrección con fallos del tester masivo

Cambios principales:
- Se analizaron 92 fallos del CSV wa_test_failures_20260702_022850.csv.
- La mayoría eran respuestas genéricas: “déjeme revisarlo”, sobre todo con Komfy Mini/Konfy/Komfi/Comfy, colores y pedidos por código.
- Ahora las dudas normales de producto ya no se mandan directo a decisión humana. Primero se hace una pregunta o respuesta humana y específica.
- Se agregaron mapas comerciales seguros para Komfy Mini y Velluto para redactar mejor cuando el almacén no resuelve perfecto.
- Se mejoró la inferencia de hilo por códigos: 06/99/20/14/01 se interpretan como Komfy Mini cuando no hay otro contexto claro.
- Se mejoró “quiero 11 blanco de Komfi Mini”, “¿Tiene Konfy Mini lila?”, “Me cotiza 3 del 06 y 6 del 99” y listas de códigos.
- Se mantiene la regla de no usar “apartar”.
- Los casos de descuentos, pagos, reclamos, envío especial y stock insuficiente siguen siendo para revisión humana.

Archivo principal modificado:
- whatsapp_ia_v27.py

Tester agregado:
- tools/whatsapp_ia_mass_tester_v32.py

Prueba recomendada después de deploy:
python tools\whatsapp_ia_mass_tester_v32.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 100

Si bajan los fallos, probar con 500:
python tools\whatsapp_ia_mass_tester_v32.py --base-url https://hilorama-celular.onrender.com --pin TU_PIN --limit 500 --sleep 0.15
