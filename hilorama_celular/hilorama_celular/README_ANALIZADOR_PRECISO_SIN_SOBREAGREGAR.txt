Corrección del analizador visual:

- Se desactivó el rescate automático de marcas rojas cuando OpenAI/IA ya devolvió productos.
- El respaldo geométrico local ahora queda solo como diagnóstico, porque podía agregar códigos vecinos por error.
- El fallback solo se usa si la IA no devuelve ningún producto.
- Esto evita sobreagregar códigos como 1, 14, 25, 61 o 73 cuando la clienta no los pidió.
- Se conserva el analizador preciso con detail=high y mayor calidad de imagen.

Si quieres activar el rescate para pruebas de administrador, agrega variable:
ALLOW_VISUAL_RESCUE=1
Pero no se recomienda para ventas reales.
