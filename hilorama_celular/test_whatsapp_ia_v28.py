from whatsapp_ia_v27 import procesar_conversacion_v27

PRODUCTOS = [
    {'id':1,'marca':'ALIZE','hilo':'VELLUTO','codigo':'55','color':'BLANCO','stock':30,'precio':59.99},
    {'id':2,'marca':'ALIZE','hilo':'VELLUTO','codigo':'60','color':'NEGRO','stock':76,'precio':59.99},
    {'id':3,'marca':'ALIZE','hilo':'VELLUTO','codigo':'56','color':'ROJO','stock':18,'precio':59.99},
    {'id':4,'marca':'ALIZE','hilo':'VELLUTO','codigo':'429','color':'CAMEL','stock':20,'precio':59.99},
    {'id':5,'marca':'ALIZE','hilo':'VELLUTO','codigo':'532','color':'ARENA','stock':22,'precio':59.99},
    {'id':6,'marca':'ALIZE','hilo':'VELLUTO','codigo':'216','color':'CANARIO','stock':61,'precio':59.99},
    {'id':7,'marca':'ALIZE','hilo':'VELLUTO','codigo':'550','color':'MANDARINA','stock':35,'precio':59.99},
    {'id':8,'marca':'ALIZE','hilo':'VELLUTO','codigo':'493','color':'CAFE OSCURO','stock':79,'precio':59.99},
    {'id':9,'marca':'ALIZE','hilo':'VELLUTO','codigo':'62','color':'HUESO','stock':10,'precio':59.99},
    {'id':10,'marca':'KARINA','hilo':'KOMFY MINI','codigo':'01','color':'BLANCO','stock':12,'precio':26.99},
    {'id':11,'marca':'KARINA','hilo':'KOMFY MINI','codigo':'06','color':'CIELO','stock':7,'precio':26.99},
    {'id':12,'marca':'KARINA','hilo':'KOMFY MINI','codigo':'99','color':'NEGRO','stock':8,'precio':26.99},
    {'id':13,'marca':'KOTTON MILK','hilo':'KOTTON MILK','codigo':'56','color':'ROJO','stock':3,'precio':45.00},
]

def caso(texto, memoria=None):
    r = procesar_conversacion_v27({'texto': texto, 'marca':'', 'hilo':''}, PRODUCTOS, memoria=memoria or {})
    print('\n---', texto.replace('\n',' / '))
    print('INTENCION:', r['intencion']['principal'], '| CONTEXTO:', r['contexto'].get('hilo_actual'))
    print('RESPUESTA:', r['respuesta'])
    print('PEDIDOS:', [(p['hilo'], p['codigo'], p['color'], p['cantidad']) for p in r['resolucion']['pedidos']])
    return r

if __name__ == '__main__':
    mem={}
    tests = [
        '¿Manejan Komfy Mini?',
        '¿Tienen Velluto blanco?',
        'me puede poner 3 del rojo',
        'Me aparta 2 del 429, 3 del 532 y 1 del 56',
        'quiero un blanco que no se vea tan amarillo',
        'hola buenas tardes quiero cotizar un pedido de velluto son 15 madejas\n5 del 55 y 10 del 60',
        'Buenas tardes le paso la lista de colores porfavor\n60\n310\n107\n329\n466\n26\n87\n428\n13\n31',
        '¿Qué colores tiene de Komfy Mini disponibles?',
        'cuanto sale el envío?',
        'ya quedó el pago',
        'manejan la abuelita?',
    ]
    mem_velluto={'hilo_actual':'VELLUTO','marca_actual':'ALIZE','estado_actual':'esperando_lista_de_colores'}
    for t in tests:
        m = mem_velluto if any(x in t.lower() for x in ['rojo','429','blanco que','buenas tardes le paso']) else {}
        caso(t, m)
