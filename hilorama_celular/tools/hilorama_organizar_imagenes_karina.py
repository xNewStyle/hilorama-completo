# -*- coding: utf-8 -*-
"""
V56 - Organizador local de imágenes Karina/Hilorama.

Escanea imágenes existentes en static/recursos_ia/ (excepto repositorio_visual)
y copia las que parezcan pertenecer a un hilo hacia:
  static/recursos_ia/repositorio_visual/hilos/KARINA/<LINEA>/<PRODUCTO>/(gama|tonos|ficha)

No descarga nada de internet y no borra archivos. Es una ayuda para acomodar material viejo.
Después ejecuta:
  python hilorama_celular/tools/hilorama_reindexar_repositorio_visual.py
"""
from pathlib import Path
import re, shutil, unicodedata, json, datetime

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'
SRC_BASE = STATIC / 'recursos_ia'
DST_BASE = SRC_BASE / 'repositorio_visual' / 'hilos' / 'KARINA'
IMG_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.jfif', '.gif'}

PRODUCTOS = {
    'ALIZE': {
        'VELLUTO': ['velluto','veluto','belluto','alize velluto'],
        'VELLUTO_MINI_COLORS': ['velluto mini colors','mini colors'],
        'DIVA': ['diva'], 'DIVA_FINE': ['diva fine'], 'DIVA_BATIK': ['diva batik'], 'DIVA_OMBRE_BATIK': ['diva ombre'],
        'BABY_BEST': ['baby best'], 'BABY_BEST_BATIK': ['baby best batik'],
        'COTTON_GOLD': ['cotton gold'], 'COTTON_GOLD_BATIK': ['cotton gold batik'],
        'SOFTY_MEGA': ['softy mega'], 'SOFTY_PLUS': ['softy plus'],
        'SUPERLANA_MAXI': ['superlana maxi'], 'SUPERLANA_MAXI_BATIK': ['superlana maxi batik'],
        'SUPERLANA_MEGAFIL': ['superlana megafil'], 'SUPERLANA_MIDI_OMBRE': ['superlana midi ombre'], 'SUPERLANA_KLASIK': ['superlana klasik'],
        'VERONA': ['verona'], 'SEKERIM_BEBE': ['sekerim bebe'], 'SEKERIM_BEBE_BATIK': ['sekerim bebe batik'],
        'PUFFY_MORE': ['puffy more'], 'PUFFY_FINE': ['puffy fine'], 'PUFFY_FINE_COLOR': ['puffy fine color'], 'PUFFY_FINE_OMBRE_BATIK': ['puffy fine ombre'],
        'BURCUM_KLASIK': ['burcum klasik'], 'BURCUM_BATIK': ['burcum batik'], 'BURCUM_BEBE_BATIK': ['burcum bebe batik'],
        'ANGORA_GOLD_SIM': ['angora gold sim'], 'ANGORA_GOLD_BATIK': ['angora gold batik'], 'ANGORA_GOLD_OMBRE_BATIK': ['angora gold ombre'],
    },
    'CALIDA': {
        'KOMFY': ['komfy'], 'KOMFY_MINI': ['komfy mini'], 'KOMFY_PLUS': ['komfy plus'], 'KURUMI': ['kurumi'],
        'KOI': ['koi'], 'KAIRO': ['kairo'], 'KENAI': ['kenai'], 'FOSFO': ['fosfo'],
    },
    'BASICOS': {
        'KOTTON_MILK': ['kotton milk','cotton milk'], 'CRISTY_LISO': ['cristy liso','cristy'],
        'CRISTY_FM_MATIZADO': ['cristy fm'], 'CRISTY_METALICO': ['cristy metalico','cristy metálico'],
        'KIWI': ['kiwi'], 'KARIME': ['karime'], 'RIO': ['rio','río'], 'RIO_MATIZADO': ['rio matizado','río matizado'],
        'LIRIO': ['lirio'], 'TAMATZ': ['tamatz'], 'HOLANDES': ['holandes','holandés'],
        'CARICIA': ['caricia'], 'ALASKA': ['alaska'], 'ANGORITA': ['angorita'], 'FIORentino'.upper(): ['fiorentino'],
        'FIORENTINO_MAXI': ['fiorentino maxi'], 'BEBEFIL': ['bebefil'], 'BEBITO': ['bebito'],
        'KARINETA': ['karineta'], 'MADEJON': ['madejon','madejón'], 'KARIBU': ['karibu','karibú'], 'ACRILAN_3_HEBRAS': ['acrilan','acrilán'],
    },
    'DECORA': {'TRAPILLO_KRAFT':['trapillo kraft','trapillo'], 'KRAME_3MM':['kramé 3','krame 3'], 'KRAME_4MM':['kramé 4','krame 4'], 'KORDONCILLO':['kordoncillo']},
    'FANTASIA': {'LENTEJUELA':['lentejuela'], 'METALICO_CROCHET':['metalico crochet','metálico crochet'], 'HILO_POLIESTER_METALICO_MX':['poliester metalico','poliéster metálico'], 'FLOR_DE_KACTUS':['flor de kactus'], 'BREZZA':['brezza'], 'FRIVOLO_NACARADO':['frivolo','frívolo'], 'NEBIA':['nebia'], 'PEPITA':['pepita'], 'BORREGUITO':['borreguito'], 'BRUJAS':['brujas'], 'ELISSE':['elisse'], 'FASHION':['fashion']},
    'PREMIUM': {'FASHION_BOUCLE':['fashion boucle'], 'MADONA_BRIZNA':['madona','brizna'], 'COUNTRY':['country']},
}

# Prioridad: claves más largas primero para evitar que "komfy" capture "komfy mini".
MATCHERS = []
for linea, productos in PRODUCTOS.items():
    for prod, aliases in productos.items():
        for a in aliases:
            MATCHERS.append((len(a), linea, prod, a.lower()))
MATCHERS.sort(reverse=True)

def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii','ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()

def tipo_destino(path: Path):
    t = norm(' '.join(path.parts[-5:]) + ' ' + path.stem)
    if any(w in t for w in ['gama','carta','catalogo','catalogo colores','colores']):
        return 'gama'
    if any(w in t for w in ['ficha','tecnica','composicion','gancho','aguja','metraje']):
        return 'ficha'
    # si el nombre trae un código numérico, lo más probable es tono individual
    if re.search(r'(?<!\d)\d{1,5}(?!\d)', path.stem):
        return 'tonos'
    return 'gama'

def detectar(path: Path):
    t = norm(' '.join(path.parts[-8:]) + ' ' + path.stem)
    for _, linea, prod, alias in MATCHERS:
        if norm(alias) in t:
            return linea, prod
    # Respaldo especial: si está en carpeta de Velluto Carta/Colores aunque archivo sea solo 429.webp
    joined = norm(str(path))
    if 'velluto carta' in joined or 'velluto colores' in joined or 'alize velluto' in joined:
        return 'ALIZE', 'VELLUTO'
    return None, None

def safe_copy(src: Path, dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        # no sobrescribir: crear copia numerada si el archivo es diferente por tamaño
        if dst.stat().st_size == src.stat().st_size:
            return dst, False
        stem, ext = src.stem, src.suffix
        i = 2
        while (dst_dir / f"{stem}_{i}{ext}").exists():
            i += 1
        dst = dst_dir / f"{stem}_{i}{ext}"
    shutil.copy2(src, dst)
    return dst, True

def main():
    movidos=[]; revisa=[]
    for f in sorted(SRC_BASE.rglob('*')):
        if not f.is_file() or f.suffix.lower() not in IMG_EXTS:
            continue
        if 'repositorio_visual' in [p.lower() for p in f.parts]:
            continue
        linea, prod = detectar(f)
        if not linea:
            revisa.append(str(f.relative_to(ROOT)))
            continue
        sub = tipo_destino(f)
        dst, copied = safe_copy(f, DST_BASE / linea / prod / sub)
        if copied:
            movidos.append({'origen':str(f.relative_to(ROOT)), 'destino':str(dst.relative_to(ROOT)), 'linea':linea, 'producto':prod, 'tipo':sub})
    report = ROOT / 'data' / 'conocimiento_hilos' / 'organizacion_imagenes_karina_v56.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        'version':'V56',
        'fecha':datetime.datetime.now(datetime.UTC).isoformat(),
        'copiados':len(movidos),
        'sin_detectar':len(revisa),
        'movidos':movidos,
        'sin_detectar_muestra':revisa[:300]
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Copiados: {len(movidos)}')
    print(f'Sin detectar: {len(revisa)}')
    print(f'Reporte: {report}')

if __name__ == '__main__':
    main()
