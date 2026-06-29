FIX PAGO / TRANSACCION ABORTADA

Problema corregido:
- Al marcar una nota como pagada podía aparecer:
  current transaction is aborted, commands ignored until end of transaction block

Causa probable:
- El historial opcional de movimientos_almacen podía fallar en una tabla creada por una versión anterior.
- En PostgreSQL, aunque el error se atrape con try/except, la transacción queda abortada si no se hace rollback o savepoint.
- Después de eso, el UPDATE de la nota pagada fallaba.

Cambios:
- movimientos_almacen ahora se actualiza con ALTER TABLE ADD COLUMN IF NOT EXISTS para columnas faltantes.
- pagos también se protege con columnas faltantes.
- _registrar_movimiento_almacen usa SAVEPOINT para que si falla el historial, no rompa el pago/venta.
- El pago debe continuar aunque no se pueda registrar el historial opcional.
