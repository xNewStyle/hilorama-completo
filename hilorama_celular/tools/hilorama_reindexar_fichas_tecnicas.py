# -*- coding: utf-8 -*-
"""
V58 - Reindexa fichas técnicas locales Hilorama/Karina.
Escanea repositorio_visual/**/ficha/ y genera data/conocimiento_hilos/fichas_tecnicas_hilorama.json
"""
from pathlib import Path
import json, re, datetime, unicodedata
ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'static' / 'recursos_ia' / 'repositorio_visual'
OUT = ROOT / 'data' / 'conocimiento_hilos' / 'fichas_tecnicas_hilorama.json'
TEXT_EXTS = {'.txt', '.md'}
JSON_EXTS = {'.json'}
IGNORAR = {'LEEME_PONER_IMAGENES_AQUI.txt','NOMBRES_DE_ARCHIVO_RECOMENDADOS.txt','LEEME_FICHA_TECNICA.txt'}
def norm_key(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii','ignore').decode('ascii')
    s = re.sub(r'[^A-Za-z0-9]+','_', s.upper()).strip('_')
    return re.sub(r'__+','_',s)
def human(s): return norm_key(s).replace('_',' ').title()
def parse_kv_text(txt):
    out={}
    aliases={'composicion':['composicion','composición','material','fibra'],'peso_bola':['peso','gramos','presentacion','presentación','gr'],'metraje':['metraje','metros','m'],'gancho_recomendado':['gancho','crochet','ganchillo'],'agujas_recomendadas':['agujas','aguja'],'origen':['origen','pais','país'],'descripcion':['descripcion','descripción','tipo','textura'],'cuando_recomendar':['recomendar','usos','ideal para','sirve para'],'cuando_no_recomendar':['no recomendar','no ideal','evitar']}
    for raw in txt.splitlines():
        line=raw.strip().strip('-').strip('*').strip()
        if not line or ':' not in line: continue
        k,v=line.split(':',1); kk=norm_key(k).lower(); vv=v.strip()
        if not vv: continue
        for field, keys in aliases.items():
            if any(norm_key(a).lower() in kk for a in keys):
                if field=='cuando_recomendar': out.setdefault('usos_recomendados',[]); out['usos_recomendados'].extend([x.strip() for x in re.split(r',|;|/',vv) if x.strip()])
                else: out[field]=vv
                break
    return out
def infer_from_path(ficha_dir: Path):
    rel=ficha_dir.relative_to(BASE); parts=list(rel.parts); low=[p.lower() for p in parts]
    meta={'clave':'','nombre':'','marca':'','linea':'','tipo_repositorio':'ficha_tecnica_local'}
    if len(parts)>=5 and low[0]=='hilos':
        proveedor=parts[1]; linea=parts[2]; producto=parts[3]
        meta['linea']=linea; meta['proveedor_fuente']=proveedor; meta['marca']='Alize' if proveedor.upper()=='KARINA' and linea.upper()=='ALIZE' else proveedor.title(); meta['clave']=producto.upper(); meta['nombre']=human(producto)
    elif len(parts)>=3 and low[0]=='accesorios':
        meta['proveedor_fuente']=parts[1] if len(parts)>1 else 'Hilorama'; prod=parts[-2] if len(parts)>=2 else 'ACCESORIO'; meta['marca']='Accesorios'; meta['clave']=human(prod).upper(); meta['nombre']=human(prod)
    return meta
def normalizar_producto(obj,ficha_dir):
    meta=infer_from_path(ficha_dir); obj=obj if isinstance(obj,dict) else {}; prod=dict(meta)
    prod.update({k:v for k,v in obj.items() if v not in (None,'')})
    if not prod.get('clave'): prod['clave']=norm_key(prod.get('nombre') or ficha_dir.parent.name)
    if not prod.get('nombre'): prod['nombre']=human(prod['clave'])
    for k in ('usos_recomendados','colores','alias'):
        if isinstance(prod.get(k),str): prod[k]=[x.strip() for x in re.split(r',|;|\n',prod[k]) if x.strip()]
    prod['archivo_relativo']=str(ficha_dir.relative_to(ROOT)).replace('\\','/')
    prod['fuente_local']=str(ficha_dir.relative_to(ROOT)).replace('\\','/')
    return prod
def main():
    productos=[]; errores=[]
    if not BASE.exists(): print('No existe repositorio_visual:',BASE); return
    for ficha_dir in sorted(BASE.rglob('ficha')):
        if not ficha_dir.is_dir(): continue
        acumulado={}; textos=[]; archivos=[]
        for f in sorted(ficha_dir.iterdir()):
            if not f.is_file() or f.name in IGNORAR or f.name.startswith('.'): continue
            if f.suffix.lower() in JSON_EXTS:
                try:
                    obj=json.loads(f.read_text(encoding='utf-8'))
                    if isinstance(obj,dict): acumulado.update(obj); archivos.append(f.name)
                except Exception as e: errores.append({'archivo':str(f.relative_to(ROOT)),'error':str(e)})
            elif f.suffix.lower() in TEXT_EXTS:
                try:
                    txt=f.read_text(encoding='utf-8',errors='ignore').strip()
                    if txt: textos.append(txt); acumulado.update(parse_kv_text(txt)); archivos.append(f.name)
                except Exception as e: errores.append({'archivo':str(f.relative_to(ROOT)),'error':str(e)})
        if acumulado or textos:
            if textos and not acumulado.get('texto_libre'): acumulado['texto_libre']='\n\n'.join(textos)[:6000]
            prod=normalizar_producto(acumulado,ficha_dir); prod['archivos_ficha']=archivos; productos.append(prod)
    by_key={}
    for p in productos:
        k=norm_key(p.get('clave') or p.get('nombre')); old=by_key.get(k,{})
        merged=dict(old); merged.update({kk:vv for kk,vv in p.items() if vv not in (None,'',[],{})}); by_key[k]=merged
    productos=list(by_key.values())
    OUT.parent.mkdir(parents=True,exist_ok=True)
    data={'version':'v58_fichas_tecnicas_locales','actualizado':datetime.datetime.now().isoformat(timespec='seconds'),'nota':'Fichas técnicas locales. Si datos_tecnicos_confirmados=false, la IA no debe inventar datos técnicos.','total_productos':len(productos),'productos':productos,'errores':errores}
    OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'OK: {len(productos)} fichas técnicas indexadas')
    print(f'Archivo: {OUT}')
    if errores: print(f'Errores: {len(errores)}')
if __name__=='__main__': main()
