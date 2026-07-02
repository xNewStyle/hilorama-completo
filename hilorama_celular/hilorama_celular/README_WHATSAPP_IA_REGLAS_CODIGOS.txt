Fix WhatsApp IA - reglas de códigos existentes y dudas reales

Archivos modificados:
- app.py

Qué corrige:
- Si el cliente escribe un código que existe en almacén, por ejemplo "un 429", el agente lo toma como producto confirmado y no pregunta por él.
- Si un color tiene una sola coincidencia clara, por ejemplo negro -> código 60, el agente no pregunta si deseas usarlo; lo agrega directo.
- Si hay una duda real, por ejemplo blanco puede ser 55 o 62, el agente pregunta solo por ese color y no vuelve a pedir confirmación de los demás productos.
- Para pedidos detectados, la respuesta se arma con reglas internas de Hilorama y no se deja a OpenAI inventar confirmaciones innecesarias.

Ejemplo esperado:
Mensaje: Hola dame 3 vellutos blanco, 2 negros y un 429
Si blanco tiene varias coincidencias:
Claro 😊 ya tengo claro:
- VELLUTO 60 NEGRO x2
- VELLUTO 429 ... x1

Solo para confirmar 😊 Confírmame el color 'blanco': coincide con varios códigos (55, 62).

Si blanco queda con una sola coincidencia o se configura como predeterminado, confirmará todo directo.
