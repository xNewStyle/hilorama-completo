V21 - WhatsApp IA agente de ventas más humano

Correcciones:
- No toma frases como "me puede poner esta lista" como si fueran color.
- "me puede poner esta lista 550 x2" se interpreta como 550 x2.
- Si la clienta aclara "todo sería Velluto", reintenta la lista anterior sin arrastrar encabezados.
- Si hay código + color y se contradicen, prioriza el color escrito por la clienta dentro del hilo confirmado.
  Ejemplo: "Hueso 26 - 1" en Velluto no debe agregar Café Chocolate 26 si Hueso existe como otro código.
- Respuestas más humanas de agente de ventas. Las dudas técnicas quedan internas y al cliente se le pregunta de forma amable.

Prueba sugerida:
1) me puede poner esta lista 550 x2
493
216 canario - 4
Blanco 01- 2
Rojo escolar- 2
Hueso 26- 1

2) a disculpe, todo seria velluto

Esperado: lista como Velluto, sin tomar encabezado como color y sin convertir Hueso en Café Chocolate.
