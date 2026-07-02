# WhatsApp IA V33 - correcciones de tester y coherencia

Esta versión corrige fallos vistos en el tester V32:

- Confirmaciones como "todo sería Velluto" ahora reutilizan el pedido en proceso y no preguntan otra vez.
- Listas de códigos con algún tono sin stock ya no se convierten en respuesta genérica; el agente muestra lo que sí puede cotizar y avisa qué tono no aparece disponible o qué cantidad falta.
- Komfy Mini se resuelve mejor contra el almacén real, evitando tomar paquetes/surtidos de HILORAMA como si fueran tonos normales.
- La memoria ya no borra el pedido en proceso cuando el último mensaje solo confirma contexto.
- Se agrega `tools/whatsapp_ia_mass_tester_v33.py`.

Sigue sin usar la palabra "apartar" y no genera guías de envío.
