FIX CLIENTE / NOMBRE EN NOTAS

Problema corregido:
- Al editar el cliente desde una nota, el nombre se actualizaba en la tabla clientes,
  pero la nota seguía mostrando la copia vieja guardada en notas.cliente_nombre.
- Por eso al guardar y volver a entrar parecía que no se había cambiado.

Cambios:
- /api/clientes/<id> ahora actualiza también notas.cliente_nombre para todas las notas del cliente.
- El listado de notas prefiere el nombre actual de clientes cuando existe.
- El detalle de nota prefiere cliente_nombre_real.
- Después de guardar el cliente desde el detalle, se recarga detalle y lista de notas.
