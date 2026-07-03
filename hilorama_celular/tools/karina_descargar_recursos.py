import argparse, json, re, sys
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'conocimiento_hilos' / 'karina_productos.json'
OUT = ROOT / 'static' / 'recursos_ia' / 'karina'
IDX = ROOT / 'data' / 'conocimiento_hilos' / 'karina_recursos_descargados.json'
UA = 'Mozilla/5.0 HiloramaBot/1.0 (distribuidor; referencia de color)'

def slug(s):
    import unicodedata
    t = unicodedata.normalize('NFKD', s or '').encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',t).strip('-') or 'producto'

def fetch(url):
    req=Request(url,headers={'User-Agent':UA})
    with urlopen(req,timeout=30) as r:
        return r.read()

def image_urls_from_html(html, base):
    text=html.decode('utf-8','ignore')
    urls=set()
    for m in re.finditer(r'https?://[^"\']+?\.(?:jpg|jpeg|png|webp)', text, re.I):
        urls.add(m.group(0))
    for m in re.finditer(r'(?:src|data-src|data-large_image)=["\']([^"\']+?\.(?:jpg|jpeg|png|webp))', text, re.I):
        urls.add(urljoin(base,m.group(1)))
    return sorted(urls)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--producto', default='', help='clave o nombre: velluto, komfy-mini, kurumi...')
    ap.add_argument('--limite', type=int, default=0, help='0 = sin límite')
    ap.add_argument('--solo-indice', action='store_true')
    args=ap.parse_args()
    data=json.loads(DATA.read_text(encoding='utf-8'))
    prods=data.get('productos',[])
    if args.producto:
        q=slug(args.producto)
        prods=[p for p in prods if q in slug(p.get('clave') or p.get('nombre'))]
    idx={"version":"v53","imagenes":[]}
    if IDX.exists():
        try: idx=json.loads(IDX.read_text(encoding='utf-8'))
        except Exception: pass
    existentes={(x.get('producto'),x.get('url')) for x in idx.get('imagenes',[])}
    for p in prods:
        url=p.get('source_url')
        if not url: continue
        print('Leyendo', p.get('nombre'), url)
        html=fetch(url)
        urls=image_urls_from_html(html,url)
        if args.limite:
            urls=urls[:args.limite]
        folder=OUT/slug(p.get('nombre'))
        folder.mkdir(parents=True,exist_ok=True)
        for u in urls:
            name=u.split('/')[-1].split('?')[0]
            dest=folder/name
            rec={"producto":p.get('nombre'),"url":u,"path":str(dest.relative_to(ROOT)).replace('\\','/')}
            if (rec['producto'],u) in existentes:
                continue
            if not args.solo_indice:
                try:
                    dest.write_bytes(fetch(u))
                    print('  OK', dest)
                except Exception as e:
                    print('  ERROR', u, e)
                    continue
            idx.setdefault('imagenes',[]).append(rec)
            existentes.add((rec['producto'],u))
    IDX.write_text(json.dumps(idx,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Índice actualizado:', IDX)

if __name__=='__main__':
    main()
