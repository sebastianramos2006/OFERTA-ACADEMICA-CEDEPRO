# construir_f1_vigente.py
#
# Objetivo:
#   F1_VIGENTE tiene EXACTAMENTE las filas de la oferta vigente del CES (≈ 9071),
#   tomadas de OFERTA_ACAD_CES_CLASIFICADA.xlsx,
#   y añade columnas ESTÁTICAS desde
#   OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx.
#
#   PROVINCIA se toma SIEMPRE desde F1_ACT (columna PROVINCIA),
#   no desde CES, porque ahí la tienes bien construída.
#
#   CLAVE_NORM = normalizar(Código IES + PROGRAMA / CARRERA)

import os
import sys
import pandas as pd

DATA_DIR = "data"
F1_ACT_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx")
CES_CLAS_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CES_CLASIFICADA.xlsx")
OUT_VIGENTE_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CEDEPRO_F_1_VIGENTE.xlsx")


def normalize_text(s):
    """Mayúsculas, sin tildes, sin espacios extra."""
    if pd.isna(s):
        return ""
    s = str(s).strip().upper()
    for a, b in [
        ("Á", "A"), ("É", "E"), ("Í", "I"),
        ("Ó", "O"), ("Ú", "U"), ("Ü", "U"),
        ("Ñ", "N"),
    ]:
        s = s.replace(a, b)
    return s


def find_col(df, candidates, label):
    """Devuelve la primera columna de candidates que exista en df.columns."""
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(f"No se encontró columna para {label}. Probé: {candidates}")


def main() -> int:
    print("\n==============================")
    print("CONSTRUIR F1_VIGENTE (CES_CLASIFICADA + estáticos F1_ACT)")
    print("==============================")

    # 1) Cargar bases
    if not os.path.exists(F1_ACT_PATH):
        print(f"ERROR: No existe {F1_ACT_PATH}")
        return 1
    if not os.path.exists(CES_CLAS_PATH):
        print(f"ERROR: No existe {CES_CLAS_PATH}")
        return 1

    print(f"Cargando F1_ACT desde: {F1_ACT_PATH}")
    df_f1 = pd.read_excel(F1_ACT_PATH)
    print(f"Filas F1_ACT: {len(df_f1)}")
    print("Columnas F1_ACT:", list(df_f1.columns))

    print(f"Cargando CES_CLASIFICADA desde: {CES_CLAS_PATH}")
    df_ces = pd.read_excel(CES_CLAS_PATH)
    print(f"Filas CES_CLASIFICADA (crudo): {len(df_ces)}")
    print("Columnas CES_CLASIFICADA:", list(df_ces.columns))

    # 2) CLAVE_NORM en F1_ACT
    col_ies_f1 = find_col(
        df_f1,
        ["CÓDIGO IES", "Codigo IES", "Código IES", "CODIGO IES"],
        "CÓDIGO IES en F1_ACT",
    )
    col_prog_f1 = find_col(
        df_f1,
        ["PROGRAMA / CARRERA", "Programa / Carrera", "PROGRAMA/CARRERA"],
        "PROGRAMA / CARRERA en F1_ACT",
    )

    df_f1["CLAVE_NORM"] = (
        df_f1[col_ies_f1].map(normalize_text)
        + "||"
        + df_f1[col_prog_f1].map(normalize_text)
    )

    # 3) CLAVE_NORM en CES_CLASIFICADA (base vigente)
    col_ies_ces = find_col(
        df_ces,
        ["Código IES", "Codigo IES", "CÓDIGO IES", "CODIGO IES"],
        "Código IES en CES_CLASIFICADA",
    )
    col_prog_ces = find_col(
        df_ces,
        ["PROGRAMA / CARRERA", "Programa / Carrera", "PROGRAMA/CARRERA"],
        "PROGRAMA / CARRERA en CES_CLASIFICADA",
    )

    df_ces["CLAVE_NORM"] = (
        df_ces[col_ies_ces].map(normalize_text)
        + "||"
        + df_ces[col_prog_ces].map(normalize_text)
    )

    print(f"Filas CES_CLASIFICADA (con CLAVE_NORM): {len(df_ces)} (deben ser ~9071)")

    # 4) Definir columnas dinámicas (que NO se copian desde F1_ACT)
    cols_dinamicas = {
        col_ies_f1,
        col_prog_f1,
        # columnas de IES/oferta que vienen bien desde CES
        "INSTITUCIÓN DE EDUCACIÓN SUPERIOR",
        "INSTITUCION DE EDUCACION SUPERIOR",
        "Universidad",
        "TIPO DE FINANCIAMIENTO",
        "Financiamiento",
        "Tipo IES",
        "TIPO DE INSTITUCIÓN",
        "TIPO DE INSTITUCION",
        "TÍTULO QUE OTORGA",
        "Título que otorga",
        # campo detallado "crudo" lo tomamos de CES_CLASIFICADA
        "CAMPO DETALLADO",
        "CAMPO_DETALLADO",
        "CAMPODETALLADO",
        # columnas de matrícula / año que NO queremos en VIGENTE
        "AÑO DE MATRICULACIÓN",
        "ANIO_DE_MATRICULACION",
        "ANIO_MATRICULACION",
        "TOTAL_MATRICULADOS",
        "TOTAL MATRICULADOS",
        # OJO: NO incluimos PROVINCIA ni CANTÓN aquí, porque
        #      queremos usar PROVINCIA de F1_ACT
    }

    # 5) Columnas estáticas (se agregan desde F1_ACT)
    static_cols = []
    for c in df_f1.columns:
        if c == "CLAVE_NORM":
            continue
        if c in cols_dinamicas:
            continue
        static_cols.append(c)

    print("\nColumnas ESTÁTICAS que se usarán desde F1_ACT (incluye PROVINCIA si existe):")
    print(static_cols)

    # 6) Armar diccionario estático: una fila por CLAVE_NORM (primer valor)
    df_static = df_f1[["CLAVE_NORM"] + static_cols].copy()
    df_static = df_static.sort_values("CLAVE_NORM")
    df_static = df_static.drop_duplicates(subset=["CLAVE_NORM"], keep="first")

    # Renombrar PROVINCIA de F1_ACT a PROVINCIA_F1 para distinguirla
    if "PROVINCIA" in df_static.columns:
        df_static = df_static.rename(columns={"PROVINCIA": "PROVINCIA_F1"})
        print("La PROVINCIA de F1_ACT se usará como PROVINCIA_F1.")

    print(f"Filas en diccionario estático F1_ACT: {len(df_static)}")

    # 7) Merge: CES_CLASIFICADA (oferta vigente) + estáticos F1_ACT
    df_vigente = df_ces.merge(
        df_static,
        on="CLAVE_NORM",
        how="left",      # CES manda en filas
        suffixes=("", "_F1"),
    )

    print(f"\nFilas F1_VIGENTE después del merge: {len(df_vigente)} (deben ser = filas CES)")
    print("Columnas F1_VIGENTE DESPUÉS DEL MERGE:")
    print(list(df_vigente.columns))

    # 8) PROVINCIA final: usar siempre la de F1_ACT si existe
    if "PROVINCIA_F1" in df_vigente.columns:
        # Si no existe PROVINCIA, la creamos desde PROVINCIA_F1
        if "PROVINCIA" not in df_vigente.columns:
            df_vigente["PROVINCIA"] = df_vigente["PROVINCIA_F1"]
        else:
            # Sobrescribimos PROVINCIA con lo de F1_ACT
            df_vigente["PROVINCIA"] = df_vigente["PROVINCIA_F1"]

        # ya no necesitamos la auxiliar
        df_vigente = df_vigente.drop(columns=["PROVINCIA_F1"])
        print("Columna PROVINCIA tomada desde F1_ACT y PROVINCIA_F1 eliminada.")

    # 9) Limpiar columnas internas y ordenar columnas
    internal_cols = [
        "CLAVE_NORM",
        "CLAVE_F1",
        "PROGRAMA_REFERENCIA_SIMILITUD",
        "SIMILITUD_REFERENCIA",
        "CLAVE_CES_ORIGEN",
    ]
    for c in internal_cols:
        if c in df_vigente.columns:
            df_vigente = df_vigente.drop(columns=[c])
            print(f"Eliminando columna interna: {c}")

    # 1) columnas originales de CES (excepto CLAVE_NORM)
    ces_cols = [c for c in df_ces.columns if c != "CLAVE_NORM"]
    # 2) columnas extra que vinieron desde F1_ACT
    extra_cols = [c for c in df_vigente.columns if c not in ces_cols]

    ordered_cols = ces_cols + extra_cols
    df_vigente = df_vigente[ordered_cols]

    # 10) Guardar resultado
    print(f"\nGuardando F1_VIGENTE en: {OUT_VIGENTE_PATH}")
    os.makedirs(DATA_DIR, exist_ok=True)
    df_vigente.to_excel(OUT_VIGENTE_PATH, index=False)

    print("CONSTRUIR F1_VIGENTE COMPLETADO.")
    print(f"Filas finales en F1_VIGENTE: {len(df_vigente)} (deben ser ~9071)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
