import pandas as pd
import json

archivo_excel = r"C:\Users\jorge\OneDrive\Escritorio\Hilorama\Datos\CPdescarga.xls"
salida_json = r"C:\Users\jorge\OneDrive\Escritorio\Hilorama\Datos\cp_offline.json"

# Leer TODAS las hojas
hojas = pd.read_excel(archivo_excel, sheet_name=None)

cp_data = {}

for nombre_hoja, df in hojas.items():
    # Saltar la hoja de NOTA
    if nombre_hoja.lower().startswith("nota"):
        continue

    print(f"Procesando hoja: {nombre_hoja}")

    # Normalizar nombres de columnas
    df.columns = [c.strip() for c in df.columns]

    # Verificar columnas necesarias
    columnas_necesarias = {"d_codigo", "d_asenta", "D_mnpio", "d_estado"}
    if not columnas_necesarias.issubset(set(df.columns)):
        print(f"⚠️ Columnas faltantes en {nombre_hoja}: {df.columns.tolist()}")
        continue

    for _, fila in df.iterrows():
        cp = str(fila["d_codigo"]).zfill(5)
        colonia = str(fila["d_asenta"]).strip()
        municipio = str(fila["D_mnpio"]).strip()
        estado = str(fila["d_estado"]).strip()

        if cp not in cp_data:
            cp_data[cp] = {
                "estado": estado,
                "municipio": municipio,
                "colonias": []
            }

        if colonia not in cp_data[cp]["colonias"]:
            cp_data[cp]["colonias"].append(colonia)

# Guardar JSON
with open(salida_json, "w", encoding="utf-8") as f:
    json.dump(cp_data, f, ensure_ascii=False, indent=2)

print("✅ cp_offline.json generado correctamente")
print(f"Total de códigos postales: {len(cp_data)}")
