# comparar_bases.py
# Compara programas entre:
#  - OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS.xlsx (base F1)
#  - OFERTA_ACAD_CES_RAW.xlsx (oferta descargada del CES)

import pandas as pd
import os
import unicodedata

DATA_DIR = "data"
F1_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS.xlsx")
CES_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CES_RAW.xlsx")
OUT_PATH = os.path.join(DATA_DIR, "COMPARACION_PROGRAMAS.xlsx")


# ─────────────────────────────
#  Utilidades de normalización
# ─────────────────────────────

def normalizar_texto(s: str) -> str:
    if pd.isna(s):
        return ""
    s = str(s).strip().lower()
    s = "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )
    while "  " in s:
        s = s.replace("  ", " ")
    return s


def norm_colname(col: str) -> str:
    if col is None:
        return ""
    s = normalizar_texto(col)
    return s.replace(" ", "").replace("_", "").replace("/", "")


def encontrar_columna(df: pd.DataFrame, keywords) -> str:
    """
    Busca una columna en df cuyas palabras clave (keywords)
    aparezcan en el nombre normalizado.
    """
    cols_norm = {norm_colname(c): c for c in df.columns}
    for k in keywords:
        nk = norm_colname(k)
        for cnorm, original in cols_norm.items():
            if nk in cnorm:
                return original
    raise Exception(f"No se encontró ninguna columna que coincida con: {keywords}")


# ─────────────────────────────
#  Comparación de bases
# ─────────────────────────────

def comparar_bases():
    print("Cargando base F1...")
    if not os.path.exists(F1_PATH):
        raise FileNotFoundError(f"No se encontró {F1_PATH}")

    df_old = pd.read_excel(F1_PATH, dtype=str)
    df_old.columns = df_old.columns.astype(str).str.strip()

    print("Cargando base CES RAW...")
    if not os.path.exists(CES_PATH):
        raise FileNotFoundError(f"No se encontró {CES_PATH}")

    df_new = pd.read_excel(CES_PATH, dtype=str)
    df_new.columns = df_new.columns.astype(str).str.strip()

    # Buscar columna de programa en cada base
    col_old = encontrar_columna(
        df_old,
        ["PROGRAMA / CARRERA", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )
    col_new = encontrar_columna(
        df_new,
        ["PROGRAMA / CARRERA", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )

    print(f"Columna programa F1: {col_old}")
    print(f"Columna programa CES RAW: {col_new}")

    programas_old = set(df_old[col_old].dropna().unique())
    programas_new = set(df_new[col_new].dropna().unique())

    nuevos = sorted(list(programas_new - programas_old))
    eliminados = sorted(list(programas_old - programas_new))
    coincidencias = sorted(list(programas_new & programas_old))

    print("Programas nuevos en CES:", len(nuevos))
    print("Programas eliminados por CES:", len(eliminados))
    print("Coincidencias exactas:", len(coincidencias))

    os.makedirs(DATA_DIR, exist_ok=True)
    with pd.ExcelWriter(OUT_PATH) as writer:
        pd.DataFrame({"PROGRAMAS NUEVOS": nuevos}).to_excel(
            writer, sheet_name="NUEVOS_EN_CES", index=False
        )
        pd.DataFrame({"PROGRAMAS ELIMINADOS": eliminados}).to_excel(
            writer, sheet_name="ELIMINADOS_EN_CES", index=False
        )
        pd.DataFrame({"COINCIDENCIAS": coincidencias}).to_excel(
            writer, sheet_name="COINCIDENCIAS", index=False
        )

    print("Archivo generado:", OUT_PATH)


if __name__ == "__main__":
    comparar_bases()
