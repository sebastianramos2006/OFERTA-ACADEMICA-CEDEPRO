# integrar_titulos_10y.py
"""
Integra el NRO. TITULOS REGISTRADOS (últimos 10 años)
desde '2025-10-07_Nro_titulos_10y.xlsx'
a la base final 'OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx'.

Cruce SOLO por IES:
- COD UNIVERSIDAD  <->  CÓDIGO IES

Se agregan variables a nivel IES:
- NRO_TITULOS_10Y
- ANIO_ACTA_MIN_10Y, ANIO_ACTA_MAX_10Y
- ANIO_REG_MIN_10Y,  ANIO_REG_MAX_10Y
"""

import pandas as pd
import unicodedata
import os
import shutil

# ----------------------------------------
# RUTAS
# ----------------------------------------
BASE_ACT_PATH = "data/OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx"
TITULOS_PATH = "data/2025-10-07_Nro_titulos_10y.xlsx"   # ajusta si el archivo tiene otro nombre

# ----------------------------------------
# HELPERS (misma lógica que en app.py)
# ----------------------------------------

def clean_str(s):
    if pd.isna(s):
        return ""
    s = str(s).strip().replace("\xa0", " ").replace("\u200b", "")
    return s.upper()

def norm_search(s):
    if pd.isna(s):
        return ""
    s = str(s).strip().replace("\xa0", " ").replace("\u200b", "")
    s = "".join(
        ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)
    )
    return s.upper()

def norm_col_key(s):
    return norm_search(s).replace(" ", "").replace("-", "").replace("_", "")

def find_column(df_cols, candidates):
    cols = list(df_cols)
    normalized = {norm_col_key(c): c for c in cols}

    # coincidencia exacta
    for cand in candidates:
        k = norm_col_key(cand)
        if k in normalized:
            return normalized[k]

    # coincidencia parcial
    for cand in candidates:
        k = norm_col_key(cand)
        for nk, orig in normalized.items():
            if k in nk or nk in k:
                return orig
    return None

def clean_code(s):
    """
    Deja solo dígitos y quita ceros a la izquierda.
    '0017' -> '17', '17 ' -> '17'
    """
    if pd.isna(s):
        return ""
    s = "".join(ch for ch in str(s) if ch.isdigit())
    return s.lstrip("0") or "0" if s else ""

# ----------------------------------------
# 1) CARGAR BASE ACT
# ----------------------------------------

if not os.path.exists(BASE_ACT_PATH):
    raise FileNotFoundError(f"No se encontró la base ACT: {BASE_ACT_PATH}")

print(f"📂 Leyendo base ACT desde: {BASE_ACT_PATH}")
base = pd.read_excel(BASE_ACT_PATH, dtype=str)

# Limpiar posibles columnas viejas de títulos/años
cols_to_drop_prev = [c for c in base.columns if c.startswith("NRO_TITULOS_10Y")]
if cols_to_drop_prev:
    print(f"ℹ️ Eliminando columnas previas de títulos: {cols_to_drop_prev}")
    base = base.drop(columns=cols_to_drop_prev)

cols_year_old = [
    "ANIO_ACTA_MIN_10Y",
    "ANIO_ACTA_MAX_10Y",
    "ANIO_REG_MIN_10Y",
    "ANIO_REG_MAX_10Y",
]
cols_year_old = [c for c in cols_year_old if c in base.columns]
if cols_year_old:
    print(f"ℹ️ Eliminando columnas previas de años: {cols_year_old}")
    base = base.drop(columns=cols_year_old)

# Detectar columna de código IES en la base ACT
col_cod_ies = find_column(
    base.columns,
    ["CÓDIGO IES", "CODIGO IES", "COD IES", "CODIGO_IES", "CODIGOIES"]
)

if not col_cod_ies:
    raise ValueError(
        f"No se pudo detectar CÓDIGO IES en la base ACT.\n"
        f"Detectado col_cod_ies={col_cod_ies}"
    )

print(f"✅ Columna código IES en ACT: {col_cod_ies}")

# Clave limpia en base ACT (nivel IES)
base["COD_IES_CLEAN"] = base[col_cod_ies].map(clean_code)

print("🔹 Ejemplo claves base ACT:")
print(base[[col_cod_ies, "COD_IES_CLEAN"]].head())

# ----------------------------------------
# 2) CARGAR ARCHIVO DE TITULADOS (10 AÑOS)
# ----------------------------------------

if not os.path.exists(TITULOS_PATH):
    raise FileNotFoundError(f"No se encontró el archivo de titulados: {TITULOS_PATH}")

print(f"📂 Leyendo archivo de titulados desde: {TITULOS_PATH}")

# CES suele tener encabezado real en la fila 13 (index 12)
raw_tit = pd.read_excel(TITULOS_PATH, header=12, dtype=str)

# La primera fila de raw_tit suele tener los verdaderos nombres de columnas
header = raw_tit.iloc[0].tolist()
tit = raw_tit[1:].copy()
tit.columns = header

# Quitar fila de TOTAL GENERAL si aparece
if "AÑO ACTA GRADO" in tit.columns:
    tit = tit[tit["AÑO ACTA GRADO"] != "TOTAL GENERAL"]

required_cols = [
    "COD UNIVERSIDAD",
    "NRO. TITULOS REGISTRADOS",
    "AÑO ACTA GRADO",
    "AÑO REGISTRO",
]
for c in required_cols:
    if c not in tit.columns:
        raise ValueError(f"No se encontró la columna '{c}' en el archivo de titulados.")

# Clave limpia en titulados (solo código universidad)
tit["COD_UNI_CLEAN"] = tit["COD UNIVERSIDAD"].map(clean_code)

print("🔹 Ejemplo claves titulados:")
print(tit[["COD UNIVERSIDAD", "COD_UNI_CLEAN"]].head())

# Años numéricos
tit["ANIO_ACTA"] = pd.to_numeric(tit["AÑO ACTA GRADO"], errors="coerce")
tit["ANIO_REG"]  = pd.to_numeric(tit["AÑO REGISTRO"], errors="coerce")

# Año de referencia: mínimo entre ACTA y REGISTRO
tit["ANIO_REF"] = tit[["ANIO_ACTA", "ANIO_REG"]].min(axis=1)

# Filtrar a los ÚLTIMOS 10 AÑOS según los datos
if tit["ANIO_REF"].notna().any():
    max_year = int(tit["ANIO_REF"].max())
    min_year = max_year - 9
    print(f"📆 Rango de años usado para el cálculo: {min_year}–{max_year}")
    tit = tit[(tit["ANIO_REF"] >= min_year) & (tit["ANIO_REF"] <= max_year)]
else:
    print("⚠ No se pudo determinar ANIO_REF; se usan todos los registros sin filtrar por año.")

# NRO. TITULOS REGISTRADOS -> numérico
tit["NRO_TITULOS"] = (
    pd.to_numeric(tit["NRO. TITULOS REGISTRADOS"], errors="coerce")
    .fillna(0)
    .astype(int)
)

# ----------------------------------------
# 3) AGREGAR TITULADOS Y AÑOS A NIVEL IES (COD_UNI_CLEAN)
# ----------------------------------------

agg_tit = (
    tit.groupby("COD_UNI_CLEAN")
    .agg(
        NRO_TITULOS_10Y=("NRO_TITULOS", "sum"),
        ANIO_ACTA_MIN_10Y=("ANIO_ACTA", "min"),
        ANIO_ACTA_MAX_10Y=("ANIO_ACTA", "max"),
        ANIO_REG_MIN_10Y=("ANIO_REG", "min"),
        ANIO_REG_MAX_10Y=("ANIO_REG", "max"),
    )
    .reset_index()
)

print(f"✅ Registros agrupados de titulados (10y, nivel IES): {len(agg_tit)}")
print(
    agg_tit[
        [
            "COD_UNI_CLEAN",
            "NRO_TITULOS_10Y",
            "ANIO_ACTA_MIN_10Y",
            "ANIO_ACTA_MAX_10Y",
            "ANIO_REG_MIN_10Y",
            "ANIO_REG_MAX_10Y",
        ]
    ].head()
)

# ----------------------------------------
# 4) MERGE CON LA BASE ACT (POR CÓDIGO IES)
# ----------------------------------------

base_merged = base.merge(
    agg_tit,
    how="left",
    left_on="COD_IES_CLEAN",
    right_on="COD_UNI_CLEAN",
)

# Asegurarnos de tener la columna NRO_TITULOS_10Y
if "NRO_TITULOS_10Y" not in base_merged.columns:
    base_merged["NRO_TITULOS_10Y"] = 0

base_merged["NRO_TITULOS_10Y"] = (
    pd.to_numeric(base_merged["NRO_TITULOS_10Y"], errors="coerce")
    .fillna(0)
    .astype(int)
)

# Convertir años a enteros "bonitos" (pero permitiendo NaN)
for col in [
    "ANIO_ACTA_MIN_10Y",
    "ANIO_ACTA_MAX_10Y",
    "ANIO_REG_MIN_10Y",
    "ANIO_REG_MAX_10Y",
]:
    if col in base_merged.columns:
        base_merged[col] = pd.to_numeric(base_merged[col], errors="coerce").astype("Int64")

# Columnas auxiliares fuera
base_merged = base_merged.drop(columns=["COD_UNI_CLEAN", "COD_IES_CLEAN"], errors="ignore")

# Resumen
total_con_titulos = (base_merged["NRO_TITULOS_10Y"] > 0).sum()
print(f"📊 Filas con NRO_TITULOS_10Y > 0: {total_con_titulos} de {len(base_merged)}")

# ----------------------------------------
# 5) GUARDAR RESULTADO CON BACKUP
# ----------------------------------------

backup_path = BASE_ACT_PATH.replace(".xlsx", "_backup_before_titles.xlsx")
print(f"💾 Haciendo backup de la base original en: {backup_path}")
shutil.copy2(BASE_ACT_PATH, backup_path)

print("💾 Guardando base ACT actualizada (con NRO_TITULOS_10Y + años a nivel IES)...")
base_merged.to_excel(BASE_ACT_PATH, index=False)

print("✅ Proceso terminado. La base ACT ahora tiene NRO_TITULOS_10Y y columnas de años a nivel de IES.")
