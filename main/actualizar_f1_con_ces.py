import os
from difflib import SequenceMatcher

import pandas as pd

F1_ORIG_PATH = "data/OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS.xlsx"
CES_PATH = "data/OFERTA_ACAD_CES_RAW.xlsx"

OUT_F1_ACT = "data/OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx"
OUT_NUEVOS = "data/OFERTA_ACAD_CEDEPRO_NUEVOS_DESDE_CES.xlsx"


def similitud(a, b) -> float:
    return SequenceMatcher(
        None,
        str(a).strip().lower(),
        str(b).strip().lower()
    ).ratio()


def construir_clave(df: pd.DataFrame, col_ies: str, col_prog: str, nueva_col: str) -> None:
    df[nueva_col] = (
        df[col_ies].astype(str).str.strip()
        + "||"
        + df[col_prog].astype(str).str.strip()
    )


def eliminar_duplicados_ces(df: pd.DataFrame, col_ies: str, col_prog: str) -> pd.DataFrame:
    df = df.copy()
    df["CLAVE_TMP"] = (
        df[col_ies].astype(str).str.strip()
        + "||"
        + df[col_prog].astype(str).str.strip()
    )
    df = df.drop_duplicates(subset=["CLAVE_TMP"], keep="first").copy()
    df.drop(columns=["CLAVE_TMP"], inplace=True)
    return df


def validar_columnas(df: pd.DataFrame, columnas_necesarias, nombre_df: str) -> None:
    faltan = [c for c in columnas_necesarias if c not in df.columns]
    if faltan:
        raise KeyError(
            f"Faltan columnas en {nombre_df}: {faltan}. "
            f"Columnas disponibles: {list(df.columns)}"
        )


# Columnas que se deben tomar desde CES y desde F1 al crear un nuevo registro
COLUMNAS_DESDE_CES = {
    "CÓDIGO IES",
    "INSTITUCIÓN DE EDUCACIÓN SUPERIOR",
    "TIPO DE INSTITUCIÓN",
    "TIPO DE FINANCIAMIENTO",
    "PROGRAMA / CARRERA",
    "TÍTULO QUE OTORGA",
}

COLUMNAS_DESDE_F1 = {
    "CAMPO AMPLIO",
    "CAMPO DETALLADO",
    "PROVINCIA",
    "CANTÓN",
    "ESTRUCTURA INSTITUCIONAL",
    "CLÚSTER ACADÉMICO",
    "MODALIDAD",
    "CAMPO_DETALLADO_P",
    "FECHA DE APROBACIÓN CES",
    "CODIFICACIÓN",
    "SIGLAS",
    "ACREDITACIÓN",
    "NRO. DE RESOLUCIÓN DEL CES",
    "TIPO DE PROGRAMA",
    "AÑO DE MATRICULACIÓN",
    "TOTAL_MATRICULADOS",
}


def clasificar_y_completar_fila_ces(
    fila_ces: pd.Series,
    df_f1_match: pd.DataFrame,
    columnas_f1: list[str],
) -> dict:
    codigo_ies = fila_ces["CÓDIGO IES"]
    programa_ces = fila_ces["PROGRAMA / CARRERA"]

    base = df_f1_match[df_f1_match["CÓDIGO IES"] == codigo_ies]
    if base.empty:
        base = df_f1_match

    mejor_sim = -1.0
    mejor_row = None

    for _, r in base.iterrows():
        sim = similitud(programa_ces, r["PROGRAMA / CARRERA"])
        if sim > mejor_sim:
            mejor_sim = sim
            mejor_row = r

    nuevo = {}

    for col in columnas_f1:
        if col == "NRO.":
            nuevo[col] = None
            continue

        # 1) Reglas de columnas
        if col in COLUMNAS_DESDE_CES and col in fila_ces.index:
            nuevo[col] = fila_ces[col]
            continue

        if mejor_row is not None and col in COLUMNAS_DESDE_F1 and col in mejor_row.index:
            # Para AÑO DE MATRICULACIÓN y TOTAL_MATRICULADOS no copiamos nada
            if col in ["AÑO DE MATRICULACIÓN", "TOTAL_MATRICULADOS"]:
                nuevo[col] = None
            else:
                nuevo[col] = mejor_row[col]
            continue

        # 2) Intentar desde mejor_row
        if mejor_row is not None and col in mejor_row.index:
            nuevo[col] = mejor_row[col]
            continue

        # 3) Intentar desde fila_ces
        if col in fila_ces.index:
            nuevo[col] = fila_ces[col]
            continue

        # 4) Si no hay de dónde, None
        nuevo[col] = None

    nuevo["PROGRAMA_REFERENCIA_SIMILITUD"] = (
        mejor_row["PROGRAMA / CARRERA"] if mejor_row is not None else None
    )
    nuevo["SIMILITUD_REFERENCIA"] = mejor_sim if mejor_row is not None else None
    nuevo["CLAVE_CES_ORIGEN"] = (
        f"{fila_ces.get('CÓDIGO IES', '')}||{fila_ces.get('PROGRAMA / CARRERA', '')}"
    )

    return nuevo


def main():
    print("Cargando F1 original...")
    if not os.path.exists(F1_ORIG_PATH):
        raise FileNotFoundError(f"No se encontró {F1_ORIG_PATH}")

    df_f1 = pd.read_excel(F1_ORIG_PATH)

    print("Cargando CES RAW...")
    if not os.path.exists(CES_PATH):
        raise FileNotFoundError(f"No se encontró {CES_PATH}")

    df_ces = pd.read_excel(CES_PATH)

    df_ces = df_ces.rename(
        columns={
            "Código IES": "CÓDIGO IES",
            "Universidad": "INSTITUCIÓN DE EDUCACIÓN SUPERIOR",
            "Financiamiento": "TIPO DE FINANCIAMIENTO",
            "Tipo IES": "TIPO DE INSTITUCIÓN",
            "Título que otorga": "TÍTULO QUE OTORGA",
        }
    )

    validar_columnas(
        df_f1,
        ["NRO.", "CÓDIGO IES", "PROGRAMA / CARRERA"],
        "F1_ORIGINAL",
    )
    validar_columnas(
        df_ces,
        ["CÓDIGO IES", "PROGRAMA / CARRERA"],
        "CES_RAW",
    )

    columnas_importantes = [
        "CAMPO DETALLADO",
        "PROVINCIA",
        "CANTÓN",
        "TÍTULO QUE OTORGA",
        "CODIFICACIÓN",
        "ESTRUCTURA INSTITUCIONAL",
        "CLÚSTER ACADÉMICO",
        "MODALIDAD",
        "CAMPO_DETALLADO_P",
        "AÑO DE MATRICULACIÓN",
        "TOTAL_MATRICULADOS",
        "FECHA DE APROBACIÓN CES",
        "ACREDITACIÓN",
        "NRO. DE RESOLUCIÓN DEL CES",
        "TIPO DE PROGRAMA",
        "CAMPO AMPLIO",
        "PROGRAMA / CARRERA",
    ]
    faltan_imp = [c for c in columnas_importantes if c not in df_f1.columns]
    if faltan_imp:
        raise KeyError(
            "La F1 de origen no tiene todas las columnas importantes. "
            f"Faltan: {faltan_imp}"
        )

    print("Eliminando duplicados solo en CES...")
    df_ces = eliminar_duplicados_ces(df_ces, "CÓDIGO IES", "PROGRAMA / CARRERA")

    print("Construyendo claves...")
    construir_clave(df_f1, "CÓDIGO IES", "PROGRAMA / CARRERA", "CLAVE_F1")
    construir_clave(df_ces, "CÓDIGO IES", "PROGRAMA / CARRERA", "CLAVE_CES")

    claves_f1 = set(df_f1["CLAVE_F1"])
    claves_ces = set(df_ces["CLAVE_CES"])

    nuevas_claves = sorted(claves_ces - claves_f1)
    print("Nuevos programas detectados:", len(nuevas_claves))

    if not nuevas_claves:
        print("No hay programas nuevos. Se copia F1 original a F1_ACT.")
        df_f1_sin_clave = df_f1.drop(columns=["CLAVE_F1"])
        os.makedirs("data", exist_ok=True)
        df_f1_sin_clave.to_excel(OUT_F1_ACT, index=False)
        pd.DataFrame(columns=df_f1_sin_clave.columns).to_excel(OUT_NUEVOS, index=False)
        print("Archivos guardados sin cambios en la estructura.")
        return

    df_nuevos_ces = df_ces[df_ces["CLAVE_CES"].isin(nuevas_claves)].copy()
    columnas_f1 = list(df_f1.columns)

    df_f1_match = df_f1.drop_duplicates(
        subset=["CÓDIGO IES", "PROGRAMA / CARRERA"]
    ).copy()

    print("Clasificando y completando nuevos registros desde CES...")
    registros_nuevos = []
    for _, fila in df_nuevos_ces.iterrows():
        registros_nuevos.append(
            clasificar_y_completar_fila_ces(fila, df_f1_match, columnas_f1)
        )

    df_nuevos = pd.DataFrame(registros_nuevos)

    max_nro = pd.to_numeric(df_f1["NRO."], errors="coerce").max()
    max_nro = int(max_nro) if pd.notna(max_nro) else 0
    df_nuevos["NRO."] = range(max_nro + 1, max_nro + 1 + len(df_nuevos))

    columnas_f1_sin_clave = [c for c in df_f1.columns if c != "CLAVE_F1"]
    extras = [c for c in df_nuevos.columns if c not in columnas_f1_sin_clave]
    df_nuevos = df_nuevos[columnas_f1_sin_clave + extras]

    df_f1_final = pd.concat(
        [df_f1.drop(columns=["CLAVE_F1"]), df_nuevos],
        ignore_index=True,
    )

    os.makedirs("data", exist_ok=True)
    print("Guardando resultados...")
    df_nuevos.to_excel(OUT_NUEVOS, index=False)
    df_f1_final.to_excel(OUT_F1_ACT, index=False)

    print("Proceso COMPLETADO.")
    print("Nuevos guardados en:", OUT_NUEVOS)
    print("F1 actualizada en:", OUT_F1_ACT)
    print("Total filas F1_ACT:", len(df_f1_final))


if __name__ == "__main__":
    main()
