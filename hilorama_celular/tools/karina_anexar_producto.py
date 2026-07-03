import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'conocimiento_hilos'/'karina_productos.json'

def ask(c):
    return input(c).strip()

data=json.loads(DATA.read_text(encoding='utf-8'))
p={}
p['clave']=ask('Clave del hilo (ej. BABY BEST): ').upper()
p['nombre']=ask('Nombre: ')
p['marca']=ask('Marca: ')
p['source_url']=ask('URL fuente o vacío: ')
p['descripcion']=ask('Descripción corta: ')
p['peso_bola']=ask('Peso por bola/madeja: ')
p['metraje']=ask('Metraje: ')
p['composicion']=ask('Composición: ')
p['origen']=ask('Origen: ')
p['gancho_recomendado']=ask('Gancho recomendado: ')
p['agujas_recomendadas']=ask('Agujas recomendadas: ')
p['usos_recomendados']=[x.strip() for x in ask('Usos recomendados separados por coma: ').split(',') if x.strip()]
p['colores']=[x.strip() for x in ask('Colores/códigos separados por coma: ').split(',') if x.strip()]
data.setdefault('productos',[]).append(p)
DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Agregado:', p['nombre'])
