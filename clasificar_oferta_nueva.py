# clasificar_oferta_nueva.py
# Clasifica OFERTA_ACAD_CES_RAW.xlsx usando como verdad:
#  - Primero: DICCIONARIO_MAESTRO.xlsx (si existe)
#  - Si no: CAMPO DETALLADO de OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx
#
# Además:
#  - Copia PROVINCIA (y CANTON si existe) desde F1_ACT,
#    emparejando por (Código IES + PROGRAMA / CARRERA).
#
# REGLA: NUNCA deja "SIN CLASIFICAR", ni vacíos, ni "OTROS PROGRAMAS"
# en CAMPO DETALLADO. En el peor caso, asigna el CAMPO DETALLADO del
# programa más parecido (nearest neighbour por similitud de texto).

import pandas as pd
import unicodedata
import difflib
import os

DATA_DIR = "data"

F1_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS_ACT.xlsx")
RAW_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CES_RAW.xlsx")

OUT_CLASIF = os.path.join(DATA_DIR, "OFERTA_ACAD_CES_CLASIFICADA.xlsx")
OUT_DICC_AUTO = os.path.join(DATA_DIR, "DICCIONARIO_MAESTRO_AUTO.xlsx")
OUT_DICC_MAESTRO = os.path.join(DATA_DIR, "DICCIONARIO_MAESTRO.xlsx")


# ─────────────────────────────
#  Utilidades de normalización
# ─────────────────────────────

def normalizar_texto(s: str) -> str:
    """
    Texto normalizado para comparación: minúsculas, sin tildes, sin doble espacio.
    """
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
    """
    Normaliza nombre de columna para buscarla por palabras clave.
    """
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


def construir_clave_ies_prog(cod_ies: pd.Series, programa: pd.Series) -> pd.Series:
    """
    Construye una clave de emparejamiento por IES + PROGRAMA:
      CLAVE_IES_PROG = normalizar_texto(cod_ies) + '||' + normalizar_texto(programa)
    """
    return cod_ies.fillna("").astype(str).map(normalizar_texto) + "||" + \
           programa.fillna("").astype(str).map(normalizar_texto)


# ─────────────────────────────
#  Construir o cargar diccionario maestro (solo campo)
# ─────────────────────────────

def cargar_diccionario_desde_excel(path: str) -> dict:
    """
    Carga un diccionario maestro desde un Excel con columnas tipo:
      - PROGRAMA_NORMALIZADO / PROG_NORM / etc.
      - CAMPO_DETALLADO / CAMPO DETALLADO / etc.
    Devuelve: dict[prog_norm] = campo_detallado
    """
    print(f"Cargando diccionario maestro desde: {path}")
    df_dicc = pd.read_excel(path, dtype=str)
    df_dicc.columns = df_dicc.columns.astype(str).str.strip()

    if df_dicc.empty:
        print("  El diccionario está vacío.")
        return {}

    col_prog_norm = encontrar_columna(
        df_dicc,
        ["PROGRAMA_NORMALIZADO", "PROG_NORM", "PROG NORMALIZADO", "PROGRAMA_NORM"]
    )
    col_campo = encontrar_columna(
        df_dicc,
        ["CAMPO_DETALLADO", "CAMPO DETALLADO", "CAMPODETALLADO"]
    )

    df_dicc[col_prog_norm] = df_dicc[col_prog_norm].fillna("").astype(str).map(normalizar_texto)
    df_dicc[col_campo] = df_dicc[col_campo].fillna("").astype(str)

    dicc = dict(zip(df_dicc[col_prog_norm], df_dicc[col_campo]))

    print(f"  Entradas cargadas desde diccionario maestro: {len(dicc)}")
    return dicc


def construir_diccionario_maestro_auto() -> dict:
    """
    Construye un diccionario maestro a partir de F1_ACT:
      PROG_NORM -> CAMPO DETALLADO más frecuente.
    """
    print("Cargando base clasificada (F_1_MATRICULADOS_ACT)...")
    if not os.path.exists(F1_PATH):
        raise FileNotFoundError(f"No se encontró {F1_PATH}")

    df_old = pd.read_excel(F1_PATH, dtype=str)
    df_old.columns = df_old.columns.astype(str).str.strip()

    col_prog_old = encontrar_columna(
        df_old,
        ["PROGRAMA / CARRERA", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )
    col_campo_old = encontrar_columna(
        df_old,
        ["CAMPO DETALLADO", "CAMPO_DETALLADO", "CAMPODETALLADO"]
    )

    print(f"   Columna programa base F1: {col_prog_old}")
    print(f"   Columna campo detallado base F1: {col_campo_old}")

    tmp = df_old[[col_prog_old, col_campo_old]].dropna()
    tmp[col_prog_old] = tmp[col_prog_old].astype(str)
    tmp[col_campo_old] = tmp[col_campo_old].astype(str)

    tmp["PROG_NORM"] = tmp[col_prog_old].apply(normalizar_texto)

    grupo = (
        tmp.groupby(["PROG_NORM", col_campo_old])
        .size()
        .reset_index(name="n")
    )

    grupo = grupo.sort_values(["PROG_NORM", "n"], ascending=[True, False])
    grupo_unico = grupo.drop_duplicates(subset=["PROG_NORM"], keep="first")

    dicc = dict(zip(grupo_unico["PROG_NORM"], grupo_unico[col_campo_old]))

    print(f"   Entradas en diccionario maestro AUTO: {len(dicc)}")

    dicc_df = grupo_unico[["PROG_NORM", col_campo_old]].rename(
        columns={
            "PROG_NORM": "PROGRAMA_NORMALIZADO",
            col_campo_old: "CAMPO_DETALLADO"
        }
    )
    os.makedirs(DATA_DIR, exist_ok=True)
    dicc_df.to_excel(OUT_DICC_AUTO, index=False)
    print(f"DICCIONARIO_MAESTRO_AUTO guardado en: {OUT_DICC_AUTO}")

    return dicc


def obtener_diccionario_maestro() -> dict:
    """
    Prioridad:
      1) Si existe DICCIONARIO_MAESTRO.xlsx y tiene datos, usarlo.
      2) Si no, construir DICCIONARIO_MAESTRO_AUTO desde F1_ACT.
    """
    if os.path.exists(OUT_DICC_MAESTRO):
        dicc = cargar_diccionario_desde_excel(OUT_DICC_MAESTRO)
        if dicc:
            print("Usando DICCIONARIO_MAESTRO.xlsx como fuente principal.")
            return dicc
        else:
            print("DICCIONARIO_MAESTRO.xlsx está vacío. Se intentará construir AUTO.")

    dicc_auto = construir_diccionario_maestro_auto()
    if dicc_auto:
        return dicc_auto

    raise RuntimeError(
        "No se pudo construir un diccionario maestro con datos. "
        "No es posible clasificar la oferta CES."
    )


# ─────────────────────────────
#  Clasificar la nueva oferta CES RAW
# ─────────────────────────────

def clasificar_nueva_oferta():
    print("Cargando base CES RAW...")
    if not os.path.exists(RAW_PATH):
        raise FileNotFoundError(f"No se encontró {RAW_PATH}")

    df_new = pd.read_excel(RAW_PATH, dtype=str)
    df_new.columns = df_new.columns.astype(str).str.strip()

    # Columnas básicas en CES_RAW
    col_prog_new = encontrar_columna(
        df_new,
        ["PROGRAMA / CARRERA", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )
    col_ies_new = encontrar_columna(
        df_new,
        ["Código IES", "CÓDIGO IES", "Codigo IES", "CODIGO IES"]
    )

    print(f"   Columna programa base nueva (CES_RAW): {col_prog_new}")
    print(f"   Columna Código IES base nueva (CES_RAW): {col_ies_new}")

    dicc = obtener_diccionario_maestro()

    # Normalizar programa en CES (para CAMPO DETALLADO)
    df_new["PROG_NORM"] = df_new[col_prog_new].apply(normalizar_texto)

    # Asignación directa mediante diccionario
    df_new["CAMPO DETALLADO"] = df_new["PROG_NORM"].map(dicc)

    sin_clasif = df_new["CAMPO DETALLADO"].isna().sum()
    print(f"   Programas sin coincidencia exacta: {sin_clasif}")

    base_keys = list(dicc.keys())

    # 1) Fuzzy matching con cortes "rigurosos"
    if sin_clasif > 0:
        print("Aplicando fuzzy matching (cortes 0.9 → 0.5)...")

        def asignar_por_fuzzy(prog_norm: str) -> str | None:
            if not prog_norm:
                return None
            for cutoff in [0.9, 0.8, 0.7, 0.6, 0.5]:
                matches = difflib.get_close_matches(
                    prog_norm, base_keys, n=1, cutoff=cutoff
                )
                if matches:
                    elegido = matches[0]
                    return dicc[elegido]
            return None

        mask_nan = df_new["CAMPO DETALLADO"].isna()
        df_new["CAMPO DETALLADO"] = df_new["CAMPO DETALLADO"].astype(object)
        df_new.loc[mask_nan, "CAMPO DETALLADO"] = df_new.loc[
            mask_nan, "PROG_NORM"
        ].apply(asignar_por_fuzzy)

    # 2) Fuzzy "forzado": si aún queda algo vacío, se asigna al más parecido SIN cutoff
    mask_restante = df_new["CAMPO DETALLADO"].isna() | (
        df_new["CAMPO DETALLADO"].astype(str).str.strip() == ""
    )
    restantes = mask_restante.sum()
    print(f"   Programas aún sin campo después del fuzzy normal: {restantes}")

    if restantes > 0:
        print("Aplicando fuzzy FORZADO (cutoff=0.0, siempre asigna al vecino más cercano)...")

        # campo detallado más frecuente (por si algún programa viene vacío)
        valores_campo = list(dicc.values())
        if valores_campo:
            campo_mas_frecuente = pd.Series(valores_campo).mode()[0]
        else:
            campo_mas_frecuente = "CAMPO NO ESPECIFICADO"

        def asignar_por_fuzzy_forzado(prog_norm: str) -> str:
            if not prog_norm:
                # si ni siquiera hay texto, usa el campo más frecuente
                return campo_mas_frecuente
            matches = difflib.get_close_matches(
                prog_norm, base_keys, n=1, cutoff=0.0
            )
            if matches:
                elegido = matches[0]
                return dicc[elegido]
            else:
                # caso ultra extremo: sin keys en diccionario
                return campo_mas_frecuente

        df_new.loc[mask_restante, "CAMPO DETALLADO"] = df_new.loc[
            mask_restante, "PROG_NORM"
        ].apply(asignar_por_fuzzy_forzado)

    # 3) Limpieza final: CAMPO DETALLADO sin vacíos ni "OTROS"
    df_new["CAMPO DETALLADO"] = df_new["CAMPO DETALLADO"].astype(str).str.strip()

    valores_campo = df_new["CAMPO DETALLADO"].tolist()
    if valores_campo:
        campo_mas_frecuente_global = pd.Series(valores_campo).mode()[0]
    else:
        campo_mas_frecuente_global = "CAMPO NO ESPECIFICADO"

    df_new.loc[
        df_new["CAMPO DETALLADO"].str.upper().isin(
            ["SIN CLASIFICAR", "OTROS", "OTROS PROGRAMAS"]
        ),
        "CAMPO DETALLADO"
    ] = campo_mas_frecuente_global

    n_final_vacios = (
        df_new["CAMPO DETALLADO"].isna()
        | (df_new["CAMPO DETALLADO"].astype(str).str.strip() == "")
    ).sum()

    if n_final_vacios > 0:
        print(
            f"⚠ Advertencia: quedaron {n_final_vacios} campos vacíos, "
            f"se rellenan con '{campo_mas_frecuente_global}'"
        )
        df_new.loc[
            df_new["CAMPO DETALLADO"].isna()
            | (df_new["CAMPO DETALLADO"].astype(str).str.strip() == ""),
            "CAMPO DETALLADO"
        ] = campo_mas_frecuente_global

    # ──────────────────────────────────────────────
    # 4) Inyectar PROVINCIA y CANTON desde F1_ACT
    # ──────────────────────────────────────────────
    print("Inyectando PROVINCIA (y CANTON si existe) desde F1_ACT...")

    if not os.path.exists(F1_PATH):
        raise FileNotFoundError(f"No se encontró {F1_PATH} para copiar PROVINCIA/CANTON")

    df_f1 = pd.read_excel(F1_PATH, dtype=str)
    df_f1.columns = df_f1.columns.astype(str).str.strip()

    col_ies_f1 = encontrar_columna(
        df_f1,
        ["CÓDIGO IES", "Codigo IES", "Código IES", "CODIGO IES"]
    )
    col_prog_f1 = encontrar_columna(
        df_f1,
        ["PROGRAMA / CARRERA", "Programa / Carrera", "PROGRAMA/CARRERA", "PROGRAMA", "CARRERA"]
    )

    # Provincia (obligatoria en tu F1_ACT)
    col_prov_f1 = encontrar_columna(
        df_f1,
        ["PROVINCIA", "Provincia"]
    )

    # Cantón (opcional)
    try:
        col_cant_f1 = encontrar_columna(
            df_f1,
            ["CANTON", "CANTÓN", "Cantón", "Canton"]
        )
    except Exception:
        col_cant_f1 = None

    # Clave IES+PROG en ambos dataframes
    df_f1["CLAVE_IES_PROG"] = construir_clave_ies_prog(
        df_f1[col_ies_f1], df_f1[col_prog_f1]
    )
    df_new["CLAVE_IES_PROG"] = construir_clave_ies_prog(
        df_new[col_ies_new], df_new[col_prog_new]
    )

    # Diccionario territorial desde F1_ACT
    cols_terr = ["CLAVE_IES_PROG", col_prov_f1]
    if col_cant_f1 is not None:
        cols_terr.append(col_cant_f1)

    df_terr = df_f1[cols_terr].dropna(subset=["CLAVE_IES_PROG"])
    df_terr = df_terr.drop_duplicates(subset=["CLAVE_IES_PROG"], keep="first")

    dicc_prov = dict(zip(df_terr["CLAVE_IES_PROG"], df_terr[col_prov_f1]))
    df_new["Provincia"] = df_new["CLAVE_IES_PROG"].map(dicc_prov)

    if col_cant_f1 is not None:
        dicc_cant = dict(zip(df_terr["CLAVE_IES_PROG"], df_terr[col_cant_f1]))
        df_new["Cantón"] = df_new["CLAVE_IES_PROG"].map(dicc_cant)

    # ── Normalizar nombres territoriales (Provincia / Cantón) ──
    if "Provincia" in df_new.columns and "PROVINCIA" not in df_new.columns:
        df_new = df_new.rename(columns={"Provincia": "PROVINCIA"})

    if "Cantón" in df_new.columns and "CANTON" not in df_new.columns:
        df_new = df_new.rename(columns={"Cantón": "CANTON"})

    # (CLAVE_IES_PROG y PROG_NORM se pueden dejar como columnas técnicas o quitarlas si quieres)
    # df_new = df_new.drop(columns=["CLAVE_IES_PROG", "PROG_NORM"], errors="ignore")

    # Guardar
    os.makedirs(DATA_DIR, exist_ok=True)
    df_new.to_excel(OUT_CLASIF, index=False)

    print("Clasificación completada. NO hay 'SIN CLASIFICAR' ni campos vacíos en CAMPO DETALLADO.")
    print("PROVINCIA (y CANTON si aplica) copiados desde F1_ACT.")
    print(f"Archivo clasificado guardado en: {OUT_CLASIF}")

    resumen = df_new["CAMPO DETALLADO"].value_counts().head(10)
    print("Top 10 campos detallados (conteo):")
    print(resumen)


if __name__ == "__main__":
    clasificar_nueva_oferta()
