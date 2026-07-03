# -*- coding: utf-8 -*-
"""
V54 - Reindexa repositorio visual local Hilorama.

Escanea:
  hilorama_celular/static/recursos_ia/repositorio_visual/

y genera:
  hilorama_celular/data/conocimiento_hilos/repositorio_visual_hilorama.json

No descarga nada de internet. Solo registra imágenes locales que Jorge pegue en las carpetas.
"""
from pathlib import Path
import json
import re
import datetime

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'
BASE = STATIC / 'recursos_ia' / 'repositorio_visual'
OUT = ROOT / 'data' / 'conocimiento_hilos' / 'repositorio_visual_hilorama.json'
IMG_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.jfif', '.gif'}


def clean(s: str) -> str:
    s = str(s or '').strip().replace('-', '_').replace(' ', '_')
    s = re.sub(r'__+', '_', s)
    return s.strip('_')


def human(s: str) -> str:
    return clean(s).replace('_', ' ').title()


def static_url(path: Path) -> str:
    rel = path.relative_to(STATIC).as_posix()
    parts = [p for p in rel.split('/') if p and p not in ('.', '..')]
    return '/static/' + '/'.join(parts)


def code_from_name(path: Path) -> str:
    stem = path.stem.strip()
    m = re.search(r'(?<!\d)(\d{1,5})(?!\d)', stem)
    return m.group(1) if m else ''


def category_from_parts(parts):
    low = [p.lower() for p in parts]
    if 'tonos' in low or 'tono' in low:
        return 'foto_tono'
    if 'gama' in low or 'catalogos' in low or 'catalogo' in low:
        return 'carta_colores'
    if 'ficha' in low or 'fichas' in low:
        return 'ficha_producto'
    if 'envios' in low or 'envíos' in low:
        return 'envio'
    if 'pagos' in low or 'pago' in low:
        return 'pago'
    if 'promociones' in low or 'promocion' in low or 'promoción' in low:
        return 'promocion'
    if 'accesorios' in low:
        return 'accesorio'
    return 'recurso_visual'


def infer_meta(path: Path):
    rel = path.relative_to(BASE)
    parts = list(rel.parts)
    low = [p.lower() for p in parts]
    categoria = category_from_parts(parts)
    marca = ''
    hilo = ''
    familia = ''

    if len(parts) >= 4 and low[0] == 'hilos':
        marca = parts[1].upper().replace(' ', '_')
        # Soporta V54: hilos/MARCA/HILO/tonos/img
        # y V55: hilos/MARCA/LINEA/HILO/tonos/img
        if len(parts) >= 6 and low[2] not in ('gama', 'tonos', 'tono', 'ficha', 'fichas'):
            familia = parts[2].lower().replace(' ', '_')  # línea/tipo: BASICOS, ALIZE, CALIDA...
            hilo = parts[3].upper().replace(' ', '_')
            # Si el producto está en la línea ALIZE de Karina, mantener marca real ALIZE para no romper contexto Velluto.
            if low[1] == 'karina' and low[2] == 'alize':
                marca = 'ALIZE'
                familia = 'karina_alize'
        else:
            hilo = parts[2].upper().replace(' ', '_')
    elif len(parts) >= 3 and low[0] == 'accesorios':
        marca = 'ACCESORIOS'
        if len(parts) >= 5 and low[1] == 'karina':
            familia = (parts[2] + '_' + parts[3]).lower().replace(' ', '_')
            hilo = parts[3].upper().replace(' ', '_')
        else:
            familia = parts[1].lower().replace(' ', '_')
            hilo = familia.upper()
    elif len(parts) >= 2 and low[0] == 'catalogos':
        marca = parts[1].upper().replace(' ', '_')
        familia = 'catalogo'
    elif len(parts) >= 2 and low[0] in ('envios', 'pagos', 'promociones'):
        familia = parts[0].lower()

    codigo = code_from_name(path) if categoria == 'foto_tono' else ''

    base_tags = []
    for token in [marca, hilo, familia, codigo, path.stem]:
        if token:
            base_tags.append(token.replace('_', ' '))
            base_tags.append(token)

    if categoria == 'foto_tono':
        grupo = f"tono_{clean(marca).lower()}_{clean(hilo).lower()}_{codigo or clean(path.stem).lower()}"
        nombre = f"Foto tono {human(hilo)} {codigo or human(path.stem)}"
        respuesta = f"Claro 😊 le comparto la foto del tono {codigo or human(path.stem)} de {human(hilo)}."
        enviar_junto = False
        prioridad = 82
        extra_tags = ['foto', 'imagen', 'tono', 'color', 'codigo', 'código']
    elif categoria == 'carta_colores':
        grupo = f"gama_{clean(marca).lower()}_{clean(hilo or familia or 'catalogo').lower()}"
        nombre = f"Gama {human(hilo or marca or familia)} {human(path.stem)}"
        respuesta = f"Claro 😊 le comparto la gama de colores de {human(hilo or marca or familia)}. Si le gusta algún código o tono, me lo indica y le reviso disponibilidad."
        enviar_junto = True
        prioridad = 90
        extra_tags = ['gama', 'carta', 'catálogo', 'catalogo', 'colores', 'tonos', 'disponibilidad']
    elif categoria == 'ficha_producto':
        grupo = f"ficha_{clean(marca).lower()}_{clean(hilo or familia or path.stem).lower()}"
        nombre = f"Ficha {human(hilo or marca or path.stem)}"
        respuesta = f"Claro 😊 le comparto la información técnica de {human(hilo or marca or path.stem)}."
        enviar_junto = False
        prioridad = 76
        extra_tags = ['ficha', 'composición', 'composicion', 'gancho', 'aguja', 'metraje', 'gramos']
    elif categoria == 'accesorio':
        grupo = f"accesorio_{clean(familia or path.parent.name).lower()}"
        nombre = f"Accesorio {human(familia or path.stem)}"
        respuesta = f"Claro 😊 le comparto imagen de {human(familia or path.stem)}."
        enviar_junto = 'gama' in low
        prioridad = 70
        extra_tags = ['accesorio', 'gancho', 'aguja', 'ojos', 'relleno', 'medida']
    elif categoria == 'envio':
        grupo = f"envios_{clean(path.parent.name).lower()}"
        nombre = f"Envíos {human(path.stem)}"
        respuesta = "Claro 😊 le comparto la información de envíos. Para costo exacto también necesito su código postal."
        enviar_junto = False
        prioridad = 74
        extra_tags = ['envio', 'envío', 'paqueteria', 'paquetería', 'correos', 'estafeta', 'fedex', 'dhl', 'reexpedicion', 'reexpedición']
    elif categoria == 'pago':
        grupo = f"pagos_{clean(path.parent.name).lower()}"
        nombre = f"Pagos {human(path.stem)}"
        respuesta = "Claro 😊 le comparto la información de pago. Cuando realice el pago me manda su comprobante para revisarlo."
        enviar_junto = False
        prioridad = 74
        extra_tags = ['pago', 'transferencia', 'datos de pago', 'cuenta', 'clabe', 'comprobante']
    elif categoria == 'promocion':
        grupo = f"promocion_{clean(path.parent.name).lower()}"
        nombre = f"Promoción {human(path.stem)}"
        respuesta = "Claro 😊 le comparto la promoción disponible."
        enviar_junto = False
        prioridad = 72
        extra_tags = ['promocion', 'promoción', 'descuento', 'oferta', 'remate']
    else:
        grupo = f"recurso_{clean(path.parent.name).lower()}"
        nombre = f"Recurso visual {human(path.stem)}"
        respuesta = "Claro 😊 le comparto la imagen de referencia."
        enviar_junto = False
        prioridad = 60
        extra_tags = []

    triggers = []
    for t in base_tags + extra_tags:
        t = str(t or '').strip()
        if t and t.lower() not in [x.lower() for x in triggers]:
            triggers.append(t)

    return {
        'nombre': nombre,
        'categoria': categoria,
        'marca': marca,
        'hilo': hilo,
        'familia': familia,
        'codigo': codigo,
        'archivo_url': static_url(path),
        'archivo_relativo': path.relative_to(ROOT).as_posix(),
        'grupo': grupo,
        'enviar_junto': enviar_junto,
        'prioridad': prioridad,
        'triggers': ', '.join(triggers),
        'respuesta': respuesta,
        'notas': 'Generado desde repositorio_visual local V55. No es URL externa. Solo se indexa si existe imagen real.'
    }


def main():
    BASE.mkdir(parents=True, exist_ok=True)
    imagenes = []
    for f in sorted(BASE.rglob('*'), key=lambda p: p.as_posix().lower()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in IMG_EXTS:
            continue
        imagenes.append(infer_meta(f))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'version': 'v55_repositorio_visual_local_lineas_karina',
        'actualizado': datetime.datetime.now().isoformat(timespec='seconds'),
        'total_imagenes': len(imagenes),
        'raiz': 'hilorama_celular/static/recursos_ia/repositorio_visual',
        'nota': 'Índice de imágenes locales. No contiene URLs externas; archivo_url es ruta local /static/... del servidor.',
        'imagenes': imagenes,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'OK: {len(imagenes)} imágenes indexadas')
    print(f'Archivo: {OUT}')


if __name__ == '__main__':
    main()
