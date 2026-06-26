HILORAMA CELULAR - FASE 1

OBJETIVO
Esta primera versión móvil funciona como PWA. Se instala desde Chrome en el celular y se conecta a la MISMA base PostgreSQL de Render que usa el programa de PC.

FUNCIONES INCLUIDAS
- Ver notas recientes.
- Filtrar cotizaciones, pendientes y pagadas.
- Buscar clientes.
- Crear cliente rápido.
- Buscar productos por código, marca, hilo o color.
- Crear cotización desde el celular.
- Si no hay internet al guardar, deja la cotización pendiente en el celular e intenta subirla cuando vuelva la conexión.

IMPORTANTE
- Crear cotización NO descuenta stock.
- El stock se descuenta cuando la cotización se convierte a venta desde tu flujo normal de PC.
- No se borra nada de la base.
- Las migraciones son seguras: CREATE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.

ARCHIVOS
- app.py
- requirements.txt
- index.html
- manifest.webmanifest
- sw.js
- icon-192.png
- icon-512.png

RENDER - CONFIGURACIÓN
Crea un Web Service nuevo.

Root Directory:
hilorama_celular

Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app

Environment Variables:
DATABASE_URL = usa el Internal Database URL de hilorama-db
MOBILE_PIN = el PIN que quieras usar para entrar desde el celular

PRUEBA
Cuando Render termine, abre:
https://TU-SERVICIO.onrender.com/api/health

Luego abre:
https://TU-SERVICIO.onrender.com

Si muestra notas, ya está leyendo la misma base que la PC.

INSTALAR EN CELULAR
Abre la URL desde Chrome del celular.
Toca los 3 puntitos.
Elige "Agregar a pantalla principal" o "Instalar app".
