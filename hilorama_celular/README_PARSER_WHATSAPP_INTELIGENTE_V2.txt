Mejoras parser WhatsApp V2

- Prioriza códigos existentes del catálogo cuando el cliente escribe códigos.
- Valida código + color: si el código no coincide con el color mencionado, pide confirmación.
- Colores en español/inglés y variantes: blanco/white/whit, negro/black/blk, etc.
- Lee cantidades por color: "3 blancos", "tres negros", "2 de blanco", "blanco 2", "whit 3".
- Lee secuencias compactas:
  * "55 1 56 2 16" = 55x1, 56x2, 16x1.
  * "un 55 1 56 2 16" = 55x1, 56x1, 16x2.
  * "16 550" = 16 piezas del código 550 si 550 existe.
  * "55 56 429" = 1 de cada código.
- Si hay duda real como "2 4", pregunta si son dos códigos o cantidad+código.
- Evita cantidades absurdas como 550 piezas cuando 550 parece código.
- El frontend muestra "Confirmar antes de agregar" cuando el parser necesita revisión.
