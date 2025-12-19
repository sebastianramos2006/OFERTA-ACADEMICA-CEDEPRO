# debug_conteos_v2.py
import os
import pandas as pd
import unicodedata

DATA_DIR = "data"
F1_ACT_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx")
CES_RAW_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CES_RAW.xlsx")
OUT_ONLY_CES = os.path.join(DATA_DIR, "PROGRAMAS_SOLO_EN_CES.xlsx")


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
    cols_norm = {norm_colname(c): c for c in df.columns}
    for k in keywords:
        nk = norm_colname(k)
        for cnorm, original in cols_norm.items():
            if nk in cnorm:
                return original
    raise Exception(f"No se encontró ninguna columna que coincida con: {keywords}")


def main():
    if not os.path.exists(F1_ACT_PATH):
        raise FileNotFoundError(f"No se encontró {F1_ACT_PATH}")

    if not os.path.exists(CES_RAW_PATH):
        raise FileNotFoundError(f"No se encontró {CES_RAW_PATH}")

    print("Cargando F1_ACT...")
    df_f1 = pd.read_excel(F1_ACT_PATH, dtype=str)
    df_f1.columns = df_f1.columns.astype(str).str.strip()

    print("Cargando CES_RAW...")
    df_ces = pd.read_excel(CES_RAW_PATH, dtype=str)
    df_ces.columns = df_ces.columns.astype(str).str.strip()

    print("\nColumnas F1_ACT:")
    print(list(df_f1.columns))

    print("\nColumnas CES_RAW:")
    print(list(df_ces.columns))

    # Buscar columnas de IES y PROGRAMA en cada base
    col_ies_f1 = encontrar_columna(
        df_f1,
        ["CÓDIGO IES", "Codigo IES", "Código IES"]
    )
    col_prog_f1 = encontrar_columna(
        df_f1,
        ["PROGRAMA / CARRERA", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )

    col_ies_ces = encontrar_columna(
        df_ces,
        ["CÓDIGO IES", "Codigo IES", "Código IES"]
    )
    col_prog_ces = encontrar_columna(
        df_ces,
        ["PROGRAMA / CARRERA", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )

    print("\n--- Columnas detectadas ---")
    print(f"F1_ACT  -> IES: {col_ies_f1}, PROGRAMA: {col_prog_f1}")
    print(f"CES_RAW -> IES: {col_ies_ces}, PROGRAMA: {col_prog_ces}")

    # Construir claves normalizadas IES||PROG
    df_f1["CLAVE_DEBUG"] = (
        df_f1[col_ies_f1].fillna("").astype(str).str.strip().map(normalizar_texto)
        + "||"
        + df_f1[col_prog_f1].fillna("").astype(str).str.strip().map(normalizar_texto)
    )

    df_ces["CLAVE_DEBUG"] = (
        df_ces[col_ies_ces].fillna("").astype(str).str.strip().map(normalizar_texto)
        + "||"
        + df_ces[col_prog_ces].fillna("").astype(str).str.strip().map(normalizar_texto)
    )

    claves_f1 = set(df_f1["CLAVE_DEBUG"])
    claves_ces = set(df_ces["CLAVE_DEBUG"])

    print("\n--- Conteos ---")
    print(f"Filas F1_ACT: {len(df_f1)}")
    print(f"Claves únicas IES+PROG en F1_ACT: {len(claves_f1)}")

    print(f"\nFilas CES_RAW: {len(df_ces)}")
    print(f"Claves únicas IES+PROG en CES_RAW: {len(claves_ces)}")

    solo_ces = sorted(claves_ces - claves_f1)
    solo_f1 = sorted(claves_f1 - claves_ces)

    print(f"\nClaves que están en CES_RAW pero NO en F1_ACT: {len(solo_ces)}")
    print(f"Claves que están en F1_ACT pero NO en CES_RAW: {len(solo_f1)}")

    # Guardar detalle de "solo en CES" para revisarlos en Excel
    if solo_ces:
        df_solo_ces = df_ces[df_ces["CLAVE_DEBUG"].isin(solo_ces)].copy()
        df_solo_ces.to_excel(OUT_ONLY_CES, index=False)
        print(f"\nSe guardaron los programas SOLO_EN_CES en: {OUT_ONLY_CES}")
    else:
        print("\nNo hay programas que estén solo en CES_RAW.")

    # Opcional: mostrar algunas claves de ejemplo
    print("\nEjemplo de claves SOLO_EN_CES (máx 10):")
    for clave in solo_ces[:10]:
        print("  ", clave)

    print("\nEjemplo de claves SOLO_EN_F1_ACT (máx 10):")
    for clave in solo_f1[:10]:
        print("  ", clave)


if __name__ == "__main__":
    main()
