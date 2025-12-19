# debug_conteos.py
import os
import pandas as pd
import unicodedata

F1_ACT = "data/OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx"
CES_RAW = "data/OFERTA_ACAD_CES_RAW.xlsx"


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
    raise KeyError(f"No se encontró ninguna columna que coincida con: {keywords}")


def main():
    if not os.path.exists(F1_ACT):
        raise FileNotFoundError(f"No se encontró {F1_ACT}")
    if not os.path.exists(CES_RAW):
        raise FileNotFoundError(f"No se encontró {CES_RAW}")

    df_f1 = pd.read_excel(F1_ACT, dtype=str)
    df_f1.columns = df_f1.columns.astype(str).str.strip()

    df_ces = pd.read_excel(CES_RAW, dtype=str)
    df_ces.columns = df_ces.columns.astype(str).str.strip()

    print("Columnas F1_ACT:")
    print(list(df_f1.columns))
    print("\nColumnas CES_RAW:")
    print(list(df_ces.columns))
    print("\n--- Conteos ---")

    # Conteos base F1_ACT
    print(f"Filas F1_ACT: {len(df_f1)}")

    col_ies_f1 = encontrar_columna(
        df_f1,
        ["CÓDIGO IES", "Codigo IES", "Código IES", "IES"]
    )
    col_prog_f1 = encontrar_columna(
        df_f1,
        ["PROGRAMA / CARRERA", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )

    df_f1["CLAVE"] = (
        df_f1[col_ies_f1].astype(str).str.strip()
        + "||"
        + df_f1[col_prog_f1].astype(str).str.strip()
    )

    print(f"Claves únicas IES+PROGRAMA en F1_ACT: {df_f1['CLAVE'].nunique()}")

    # Conteos base CES_RAW
    print(f"\nFilas CES_RAW: {len(df_ces)}")

    col_ies_ces = encontrar_columna(
        df_ces,
        ["CÓDIGO IES", "Codigo IES", "Código IES", "IES"]
    )
    col_prog_ces = encontrar_columna(
        df_ces,
        ["PROGRAMA / CARRERA", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )

    df_ces["CLAVE"] = (
        df_ces[col_ies_ces].astype(str).str.strip()
        + "||"
        + df_ces[col_prog_ces].astype(str).str.strip()
    )

    print(f"Claves únicas IES+PROGRAMA en CES_RAW: {df_ces['CLAVE'].nunique()}")


if __name__ == "__main__":
    main()
