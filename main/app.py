# app.py — CEDEPRO Matriculados + Titulados (compatible con tu matriculas.js)
# ✅ Mantiene EXACTAMENTE las rutas que tu JS ya llama
# ✅ Oferta SIEMPRE sale de OFERTA VIGENTE (no de F1)
# ✅ Matriculados salen de F1 (TOTAL_MATRICULADOS)
# ✅ Titulados salen de F1 (TITULADOS_TOTALES)
# ✅ Cohorte: si seleccionas anio=2020 => titulados del anio_titulacion=2024 (cohorte+4)
# ✅ Merge por CAMPO_KEY (sin tildes) para NO perder oferta aunque matriculados/titulados sean 0
# ✅ Arregla tus errores: paths Windows con \U, os.path.joi, FileNotFoundError por rutas rígidas

import os
import re
import io
import csv
import unicodedata
import logging
import subprocess
from datetime import datetime

import pandas as pd
from flask import (
    Flask,
    jsonify,
    request,
    render_template,
    send_file,
    current_app,
)

# ───────────────────────────── Config ─────────────────────────────

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Puedes sobreescribir por variables de entorno si quieres (Render / local)
# Ej:
#   set CEDEPRO_OFERTA_VIGENTE_PATH="C:\...\OFERTA_ACAD_CEDEPRO_F_1_VIGENTE.xlsx"
#   set CEDEPRO_F1_PATH="C:\...\OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS.xlsx"
ENV_OFERTA = os.environ.get("CEDEPRO_OFERTA_VIGENTE_PATH")
ENV_F1 = os.environ.get("CEDEPRO_F1_PATH")

# Nombres típicos (tu proyecto los usa así)
DEFAULT_OFERTA_FILENAME = "OFERTA_ACAD_CEDEPRO_F_1_VIGENTE.xlsx"
DEFAULT_F1_FILENAME = "OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS.xlsx"

# Rutas finales (robustas: si no hay env, usa /data/...)
OFERTA_VIGENTE_PATH = ENV_OFERTA or os.path.join(DATA_DIR, DEFAULT_OFERTA_FILENAME)
F1_PATH = ENV_F1 or os.path.join(DATA_DIR, DEFAULT_F1_FILENAME)

# Pipeline (si lo usas)
PIPELINE_SCRIPT = os.path.join(BASE_DIR, "pipeline_update.py")  # ajusta si se llama distinto

# ───────────────────────────── Utils ─────────────────────────────

def clean_str(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def strip_accents(s: str) -> str:
    s = clean_str(s)
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

def norm_search(s: str) -> str:
    # clave de comparación (sin tildes, mayúsculas, sin dobles espacios)
    s = strip_accents(s).upper()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def to_int_safe(x) -> int:
    try:
        if pd.isna(x):
            return 0
        if isinstance(x, (int, float)):
            return int(x)
        s = re.sub(r"[^\d\-]", "", str(x))
        return int(s) if s not in ("", "-", None) else 0
    except Exception:
        return 0

def parse_year(x):
    try:
        if pd.isna(x):
            return None
        if isinstance(x, (int, float)):
            y = int(x)
            return y if 1900 <= y <= 2100 else None
        s = clean_str(x)
        m = re.search(r"(19\d{2}|20\d{2})", s)
        return int(m.group(1)) if m else None
    except Exception:
        return None

def find_column(columns, candidates):
    cols = list(columns)
    # match exact
    for c in candidates:
        if c in cols:
            return c
    # match normalized
    norm_map = {norm_search(c): c for c in cols}
    for cand in candidates:
        k = norm_search(cand)
        if k in norm_map:
            return norm_map[k]
    return None

def normalize_campo_p(v: str) -> str:
    # Mantiene tildes en display (no toca letras), pero arregla espacios y separador "_"
    v = clean_str(v)
    v = v.replace(" - ", " ")
    v = re.sub(r"\s+", " ", v).strip()
    return v

def split_campo_p(v: str):
    """
    Entrada:
      - "TURISMO Y HOTELERÍA_PICHINCHA"
      - "TURISMO Y HOTELERÍA _ PICHINCHA"
    Retorna: (campo_base, provincia_display)
    """
    s = normalize_campo_p(v)
    if "_" in s:
        parts = [p.strip() for p in s.split("_", 1)]
        if len(parts) == 2:
            return parts[0], parts[1]
    return s, ""

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def try_autofind_in_data_dir(preferred_path: str, fallback_keywords: list[str]) -> str:
    """
    Si el archivo preferido no existe, intenta encontrar uno dentro de /data
    por keywords (por si el nombre cambió: VIGENTE, MATRICULADOS, etc.)
    """
    if os.path.exists(preferred_path):
        return preferred_path

    if not os.path.isdir(DATA_DIR):
        return preferred_path

    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith((".xlsx", ".xls"))]
    if not files:
        return preferred_path

    # primero: intenta match exact por nombre por defecto
    pref_name = os.path.basename(preferred_path).lower()
    for f in files:
        if f.lower() == pref_name:
            return os.path.join(DATA_DIR, f)

    # luego: busca por keywords
    best = None
    best_score = -1
    for f in files:
        name = f.lower()
        score = 0
        for kw in fallback_keywords:
            if kw.lower() in name:
                score += 1
        if score > best_score:
            best_score = score
            best = f
    if best and best_score > 0:
        return os.path.join(DATA_DIR, best)

    return preferred_path

# ───────────────────────────── Globals ─────────────────────────────

df_of_raw = None   # oferta vigente raw
df_of = None       # oferta vigente normalizada (con keys)
df_mat_raw = None  # F1 raw
df_mat = None      # matriculados normalizada
df_tit = None      # titulados normalizada

# Columnas detectadas OFERTA
COL_PROV_OF = None
COL_CAMPO_OF = None
COL_IES_OF = None
COL_TIPO_PROG_OF = None

# Columnas detectadas MATRICULADOS (F1)
COL_MAT_ANIO = None
COL_MAT_NIVEL = None
COL_MAT_CAMPO_P = None
COL_MAT_PROV = None
COL_MAT_MAT = None

# Columnas detectadas TITULADOS (F1)
COL_TIT_P = None
COL_TIT_ANIO = None
COL_TIT_TOTAL = None

# Provincias (normalizadas -> display oficial)
PROV_MAP = {
    "GALAPAGOS": "GALÁPAGOS",
}

candidates_map = {
    # OFERTA VIGENTE
    "provincia_of": ["PROVINCIA", "Provincia"],
    "campo_of": ["CAMPO DETALLADO", "CAMPO_DETALLADO", "CAMPO_DETALLADO_P", "CAMPO DETALLADO P"],
    "ies_of": ["Universidad", "INSTITUCIÓN DE EDUCACIÓN SUPERIOR", "INSTITUCION DE EDUCACION SUPERIOR", "IES"],
    "tipo_prog_of": ["TIPO DE PROGRAMA", "TIPO_PROGRAMA", "TIPO PROGRAMA", "NIVEL"],

    # MATRICULADOS (F1)
    "anio_mat": ["AÑO DE MATRICULACIÓN", "AÑO_MATRICULACIÓN", "AÑO", "ANIO", "AÑO DE MATRICULACION", "ANIO DE MATRICULACION"],
    "nivel_mat": ["TIPO DE PROGRAMA", "NIVEL_FORMACION", "NIVEL FORMACION", "NIVEL DE FORMACIÓN", "NIVEL DE FORMACION"],
    "campo_p": ["CAMPO_DETALLADO_P", "CAMPO DETALLADO P", "CAMPO DETALLADO", "CAMPO_DETALLADO"],
    "prov_mat": ["PROVINCIA", "Provincia"],
    "matriculados": ["TOTAL_MATRICULADOS", "MATRICULADOS", "TOTAL DE MATRICULADOS", "TOTAL MATRICULADOS"],

    # TITULADOS (F1)
    "titulados_p": ["TITULADOS_P", "TITULADOS P"],
    "anio_titulados": ["AÑO_DE_TITULADOS", "ANIO_DE_TITULADOS", "AÑO TITULADOS", "ANIO TITULADOS"],
    "titulados_totales": ["TITULADOS_TOTALES", "TOTAL_TITULADOS", "TOTAL DE TITULADOS", "TITULADOS TOTALES"],
}

# ───────────────────────────── Loaders ─────────────────────────────

def load_base():
    """
    Carga:
      - OFERTA VIGENTE desde OFERTA_VIGENTE_PATH
      - MATRICULADOS + TITULADOS desde F1_PATH
    OJO: No revienta tu servidor si falta algo; deja DF vacíos y loggea.
    """
    global df_of_raw, df_of, df_mat_raw, df_mat, df_tit
    global COL_PROV_OF, COL_CAMPO_OF, COL_IES_OF, COL_TIPO_PROG_OF
    global COL_MAT_ANIO, COL_MAT_NIVEL, COL_MAT_CAMPO_P, COL_MAT_PROV, COL_MAT_MAT
    global COL_TIT_P, COL_TIT_ANIO, COL_TIT_TOTAL
    global OFERTA_VIGENTE_PATH, F1_PATH

    ensure_dir(DATA_DIR)

    # re-intenta autodescubrimiento si el nombre cambió
    OFERTA_VIGENTE_PATH = try_autofind_in_data_dir(
        OFERTA_VIGENTE_PATH,
        fallback_keywords=["vigente", "f_1_vigente", "f1_vigente", "oferta"]
    )
    F1_PATH = try_autofind_in_data_dir(
        F1_PATH,
        fallback_keywords=["matriculados", "f_1_matriculados", "f1_matriculados", "f1"]
    )

    # ── OFERTA VIGENTE ──────────────────────────────
    try:
        if not os.path.exists(OFERTA_VIGENTE_PATH):
            raise FileNotFoundError(f"No existe OFERTA VIGENTE en: {OFERTA_VIGENTE_PATH}")

        df_of_raw_local = pd.read_excel(OFERTA_VIGENTE_PATH)

        COL_PROV_OF = find_column(df_of_raw_local.columns, candidates_map["provincia_of"])
        COL_CAMPO_OF = find_column(df_of_raw_local.columns, candidates_map["campo_of"])
        COL_IES_OF = find_column(df_of_raw_local.columns, candidates_map["ies_of"])
        COL_TIPO_PROG_OF = find_column(df_of_raw_local.columns, candidates_map["tipo_prog_of"])

        df_of_local = df_of_raw_local.copy()

        # Provincia (display)
        if COL_PROV_OF and COL_PROV_OF in df_of_local.columns:
            df_of_local["PROV_DISPLAY"] = df_of_local[COL_PROV_OF].fillna("").map(clean_str)
            df_of_local["PROV_DISPLAY"] = df_of_local["PROV_DISPLAY"].map(
                lambda p: PROV_MAP.get(norm_search(p), p)
            )
        else:
            df_of_local["PROV_DISPLAY"] = ""

        # Campo detallado (display)
        if COL_CAMPO_OF and COL_CAMPO_OF in df_of_local.columns:
            df_of_local["CAMPO_DETALLADO"] = df_of_local[COL_CAMPO_OF].fillna("").map(clean_str)
        else:
            df_of_local["CAMPO_DETALLADO"] = ""

        df_of_local["PROV_KEY"] = df_of_local["PROV_DISPLAY"].map(norm_search)
        df_of_local["CAMPO_KEY"] = df_of_local["CAMPO_DETALLADO"].map(norm_search)

        df_of_raw = df_of_raw_local
        df_of = df_of_local

        logging.info("✅ Oferta vigente cargada: %s filas | archivo: %s", len(df_of), OFERTA_VIGENTE_PATH)
    except Exception as e:
        logging.error("❌ No se pudo cargar OFERTA VIGENTE: %s", str(e))
        df_of_raw = pd.DataFrame()
        df_of = pd.DataFrame(columns=["PROV_DISPLAY", "CAMPO_DETALLADO", "PROV_KEY", "CAMPO_KEY"])

    # ── F1 (MATRICULADOS + TITULADOS) ──────────────────────────────
    try:
        if not os.path.exists(F1_PATH):
            raise FileNotFoundError(f"No existe F1 en: {F1_PATH}")

        df_mat_raw_local = pd.read_excel(F1_PATH)

        # detecta columnas matriculados
        COL_MAT_ANIO = find_column(df_mat_raw_local.columns, candidates_map["anio_mat"])
        COL_MAT_NIVEL = find_column(df_mat_raw_local.columns, candidates_map["nivel_mat"])
        COL_MAT_CAMPO_P = find_column(df_mat_raw_local.columns, candidates_map["campo_p"])
        COL_MAT_PROV = find_column(df_mat_raw_local.columns, candidates_map["prov_mat"])
        COL_MAT_MAT = find_column(df_mat_raw_local.columns, candidates_map["matriculados"])

        df_mat_local = df_mat_raw_local.copy()

        df_mat_local["ANIO_MATRICULACION"] = (
            df_mat_local[COL_MAT_ANIO].map(parse_year) if COL_MAT_ANIO else None
        )
        df_mat_local["NIVEL_FORMACION"] = (
            df_mat_local[COL_MAT_NIVEL].fillna("").map(clean_str) if COL_MAT_NIVEL else ""
        )

        # CAMPO_DETALLADO_P:
        #  - si ya viene con "_" (campo_provincia), NO inventamos nada
        #  - si NO viene con "_", entonces recién armamos: campo + "_" + provincia
        campo_src = df_mat_local[COL_MAT_CAMPO_P].fillna("").map(clean_str) if COL_MAT_CAMPO_P else pd.Series([""] * len(df_mat_local))
        campo_src = campo_src.map(normalize_campo_p)

        has_underscore = campo_src.astype(str).str.contains("_", regex=False)

        if has_underscore.any():
            # usa tal cual (porque tú dijiste: provincia viene desde CAMPO_DETALLADO_P)
            campo_p_final = campo_src
        else:
            # fallback: arma con provincia si existiera
            prov_src = df_mat_local[COL_MAT_PROV].fillna("").map(clean_str) if (COL_MAT_PROV and COL_MAT_PROV in df_mat_local.columns) else pd.Series([""] * len(df_mat_local))
            prov_src = prov_src.map(lambda p: PROV_MAP.get(norm_search(p), p))
            campo_p_final = (campo_src + "_" + prov_src).map(normalize_campo_p)

        df_mat_local["CAMPO_DETALLADO_P"] = campo_p_final

        # Derivar CAMPO_BASE_P y PROV_DESDE_CAMPO_P desde CAMPO_DETALLADO_P
        bases, provs = [], []
        for v in df_mat_local["CAMPO_DETALLADO_P"].astype(str):
            b, p = split_campo_p(v)
            bases.append(b)
            provs.append(p)

        df_mat_local["CAMPO_BASE_P"] = bases
        df_mat_local["PROV_DESDE_CAMPO_P"] = provs

        # Keys comparación (sin tildes)
        df_mat_local["PROV_KEY"] = df_mat_local["PROV_DESDE_CAMPO_P"].map(norm_search)
        df_mat_local["CAMPO_KEY"] = df_mat_local["CAMPO_BASE_P"].map(norm_search)

        # Matriculados num
        if COL_MAT_MAT and COL_MAT_MAT in df_mat_local.columns:
            df_mat_local[COL_MAT_MAT] = df_mat_local[COL_MAT_MAT].map(to_int_safe)
        else:
            COL_MAT_MAT = "TOTAL_MATRICULADOS"
            df_mat_local[COL_MAT_MAT] = 0

        df_mat_raw = df_mat_raw_local
        df_mat = df_mat_local

        logging.info("✅ Matriculados cargados: %s filas | archivo: %s", len(df_mat), F1_PATH)
    except Exception as e:
        logging.error("❌ No se pudo cargar F1 MATRICULADOS: %s", str(e))
        df_mat_raw = pd.DataFrame()
        df_mat = pd.DataFrame(columns=[
            "ANIO_MATRICULACION", "NIVEL_FORMACION",
            "CAMPO_DETALLADO_P", "CAMPO_BASE_P", "PROV_DESDE_CAMPO_P",
            "PROV_KEY", "CAMPO_KEY", "TOTAL_MATRICULADOS"
        ])
        COL_MAT_MAT = "TOTAL_MATRICULADOS"

    # ── TITULADOS (desde el MISMO F1) ──────────────────────────────
    try:
        if df_mat_raw is None or df_mat_raw.empty:
            raise ValueError("F1 no cargado; titulados no disponible.")

        COL_TIT_P = find_column(df_mat_raw.columns, candidates_map["titulados_p"])
        COL_TIT_ANIO = find_column(df_mat_raw.columns, candidates_map["anio_titulados"])
        COL_TIT_TOTAL = find_column(df_mat_raw.columns, candidates_map["titulados_totales"])

        if COL_TIT_P and COL_TIT_ANIO and COL_TIT_TOTAL:
            df_tit_local = df_mat_raw[[COL_TIT_P, COL_TIT_ANIO, COL_TIT_TOTAL]].copy()

            df_tit_local["TITULADOS_P"] = df_tit_local[COL_TIT_P].fillna("").map(clean_str).map(normalize_campo_p)
            df_tit_local["ANIO_TITULADOS"] = df_tit_local[COL_TIT_ANIO].map(parse_year)
            df_tit_local["TITULADOS_TOTALES"] = df_tit_local[COL_TIT_TOTAL].map(to_int_safe)

            bases_t, provs_t = [], []
            for v in df_tit_local["TITULADOS_P"].astype(str):
                b, p = split_campo_p(v)
                bases_t.append(b)
                provs_t.append(p)

            df_tit_local["CAMPO_BASE_T"] = bases_t
            df_tit_local["PROV_T"] = provs_t
            df_tit_local["PROV_KEY"] = df_tit_local["PROV_T"].map(norm_search)
            df_tit_local["CAMPO_KEY"] = df_tit_local["CAMPO_BASE_T"].map(norm_search)

            df_tit_local = df_tit_local[
                df_tit_local["CAMPO_KEY"].astype(str).str.len() > 0
            ].copy()

            df_tit = df_tit_local
            logging.info("✅ Titulados cargados: %s filas", len(df_tit))
        else:
            df_tit = pd.DataFrame(columns=[
                "TITULADOS_P", "ANIO_TITULADOS", "TITULADOS_TOTALES",
                "PROV_KEY", "CAMPO_KEY", "CAMPO_BASE_T"
            ])
            logging.warning("⚠️ No se detectaron columnas completas de TITULADOS (TITULADOS_P / AÑO_DE_TITULADOS / TITULADOS_TOTALES).")
    except Exception as e:
        logging.warning("⚠️ Titulados no disponible: %s", str(e))
        df_tit = pd.DataFrame(columns=[
            "TITULADOS_P", "ANIO_TITULADOS", "TITULADOS_TOTALES",
            "PROV_KEY", "CAMPO_KEY", "CAMPO_BASE_T"
        ])

# carga inicial (sin reventar)
load_base()

# ──────────────────────── LISTAS FILTROS ────────────────────────

def provincias_list():
    # Provincias desde matriculados (mapa histórico)
    if df_mat is None or df_mat.empty:
        return []
    provs = [p for p in df_mat["PROV_DESDE_CAMPO_P"].dropna().unique().tolist() if p]
    return sorted(provs)

def years_list():
    if df_mat is None or df_mat.empty:
        return []
    years = pd.Series(df_mat["ANIO_MATRICULACION"]).dropna()
    try:
        years = years.astype(int)
    except Exception:
        return []
    return sorted(years.unique().tolist(), reverse=True)

def levels_list():
    if df_mat is None or df_mat.empty:
        return []
    return sorted([l for l in df_mat["NIVEL_FORMACION"].dropna().unique().tolist() if l])

# ──────────────────────── OFERTA (VIGENTE) ────────────────────────

def oferta_tipo_programa_table():
    if df_of is None or df_of.empty:
        return pd.DataFrame(columns=["PROVINCIA", "INSTITUCIÓN DE EDUCACIÓN SUPERIOR", "TIPO DE PROGRAMA", "NUM_PROGRAMAS"])

    if not (COL_IES_OF and COL_TIPO_PROG_OF):
        return pd.DataFrame(columns=["PROVINCIA", "INSTITUCIÓN DE EDUCACIÓN SUPERIOR", "TIPO DE PROGRAMA", "NUM_PROGRAMAS"])

    tmp = df_of.copy()
    tmp["PROV"] = tmp.get("PROV_DISPLAY", "").astype(str).map(clean_str)
    tmp["IES"] = tmp[COL_IES_OF].fillna("").map(clean_str) if COL_IES_OF in tmp.columns else ""
    tmp["TIPO"] = tmp[COL_TIPO_PROG_OF].fillna("").map(clean_str) if COL_TIPO_PROG_OF in tmp.columns else ""

    g = (
        tmp.groupby(["PROV", "IES", "TIPO"])
        .size()
        .reset_index(name="NUM_PROGRAMAS")
        .rename(columns={
            "PROV": "PROVINCIA",
            "IES": "INSTITUCIÓN DE EDUCACIÓN SUPERIOR",
            "TIPO": "TIPO DE PROGRAMA"
        })
        .sort_values(["PROVINCIA", "INSTITUCIÓN DE EDUCACIÓN SUPERIOR", "TIPO DE PROGRAMA", "NUM_PROGRAMAS"],
                     ascending=[True, True, True, False])
    )
    return g

def oferta_por_campo(provincia=None):
    """
    Cuenta oferta vigente por CAMPO_DETALLADO (display), filtrando por provincia (si aplica).
    Devuelve: CAMPO_DETALLADO, NUM_PROGRAMAS
    """
    if df_of is None or df_of.empty:
        return pd.DataFrame(columns=["CAMPO_DETALLADO", "NUM_PROGRAMAS"])

    tmp = df_of
    if provincia:
        prov_key = norm_search(provincia)
        tmp = tmp[tmp["PROV_KEY"] == prov_key]

    if tmp.empty:
        return pd.DataFrame(columns=["CAMPO_DETALLADO", "NUM_PROGRAMAS"])

    g = (
        tmp.groupby("CAMPO_DETALLADO")
        .size()
        .reset_index(name="NUM_PROGRAMAS")
        .sort_values("NUM_PROGRAMAS", ascending=False)
    )
    return g

# ─────────────────────── MATRICULADOS (F1) ───────────────────────

def _filtrar_mat(provincia=None, anio=None, nivel=None):
    tmp = df_mat
    if tmp is None or tmp.empty:
        return pd.DataFrame(columns=df_mat.columns if df_mat is not None else [])

    if provincia:
        prov_norm = norm_search(provincia)
        tmp = tmp[tmp["PROV_KEY"] == prov_norm]

    if anio and str(anio).upper() != "ALL":
        try:
            anio_int = int(anio)
            tmp = tmp[tmp["ANIO_MATRICULACION"] == anio_int]
        except Exception:
            pass

    if nivel:
        tmp = tmp[tmp["NIVEL_FORMACION"] == clean_str(nivel)]

    return tmp

def matriculas_base_nacional(anio=None, nivel=None):
    tmp = _filtrar_mat(None, anio, nivel).copy()
    if tmp.empty:
        return pd.DataFrame(columns=["CAMPO_BASE", "TOTAL_MATRICULADOS"])

    g = (
        tmp.groupby("CAMPO_BASE_P")[COL_MAT_MAT]
        .sum()
        .reset_index()
        .rename(columns={"CAMPO_BASE_P": "CAMPO_BASE", COL_MAT_MAT: "TOTAL_MATRICULADOS"})
        .sort_values("TOTAL_MATRICULADOS", ascending=False)
    )
    return g

def matriculas_base_provincia(provincia, anio=None, nivel=None):
    if not provincia:
        return pd.DataFrame(columns=["CAMPO_BASE", "TOTAL_MATRICULADOS"])

    tmp = _filtrar_mat(provincia, anio, nivel).copy()
    if tmp.empty:
        return pd.DataFrame(columns=["CAMPO_BASE", "TOTAL_MATRICULADOS"])

    g = (
        tmp.groupby("CAMPO_BASE_P")[COL_MAT_MAT]
        .sum()
        .reset_index()
        .rename(columns={"CAMPO_BASE_P": "CAMPO_BASE", COL_MAT_MAT: "TOTAL_MATRICULADOS"})
        .sort_values("TOTAL_MATRICULADOS", ascending=False)
    )
    return g

def matriculas_full_provincia(provincia, anio=None, nivel=None):
    if not provincia:
        return pd.DataFrame(columns=["CAMPO_DETALLADO_P", "TOTAL_MATRICULADOS"])

    tmp = _filtrar_mat(provincia, anio, nivel).copy()
    if tmp.empty:
        return pd.DataFrame(columns=["CAMPO_DETALLADO_P", "TOTAL_MATRICULADOS"])

    g = (
        tmp.groupby("CAMPO_DETALLADO_P")[COL_MAT_MAT]
        .sum()
        .reset_index()
        .rename(columns={COL_MAT_MAT: "TOTAL_MATRICULADOS"})
        .sort_values("TOTAL_MATRICULADOS", ascending=False)
    )
    return g

# ─────────────────────── TITULADOS (F1) ───────────────────────

def _filtrar_tit(provincia=None, anio_titulacion=None):
    tmp = df_tit
    if tmp is None or tmp.empty:
        return pd.DataFrame(columns=df_tit.columns if df_tit is not None else [])

    if provincia:
        prov_norm = norm_search(provincia)
        tmp = tmp[tmp["PROV_KEY"] == prov_norm]

    if anio_titulacion:
        try:
            a = int(anio_titulacion)
            tmp = tmp[tmp["ANIO_TITULADOS"] == a]
        except Exception:
            pass

    return tmp

def titulados_por_cohorte(provincia=None, anio_cohorte=None):
    """
    cohorte -> año titulación = cohorte + 4
    Ej: 2020 -> 2024, 2021 -> 2025
    Devuelve df: CAMPO_KEY, TOTAL_TITULADOS
    """
    if not anio_cohorte or str(anio_cohorte).upper() == "ALL":
        return pd.DataFrame(columns=["CAMPO_KEY", "TOTAL_TITULADOS"])

    try:
        coh = int(anio_cohorte)
    except Exception:
        return pd.DataFrame(columns=["CAMPO_KEY", "TOTAL_TITULADOS"])

    anio_tit = coh + 4
    tmp = _filtrar_tit(provincia, anio_tit)
    if tmp.empty:
        return pd.DataFrame(columns=["CAMPO_KEY", "TOTAL_TITULADOS"])

    g = (
        tmp.groupby("CAMPO_KEY")["TITULADOS_TOTALES"]
        .sum()
        .reset_index(name="TOTAL_TITULADOS")
    )
    return g

# ─────────────────────── COMPARACIÓN ───────────────────────

def compare_oferta_vs_matriculas(provincia=None, anio=None, nivel=None):
    """
    Devuelve lista merged:
      campo: display bonito del campo (preferimos oferta vigente)
      oferta: #programas (vigente)
      matriculados: total matriculados (si anio/nivel)
      titulados: total titulados (si anio específico -> cohorte+4)
      anio_titulacion: (si aplica)
    """

    # 1) Oferta (vigente) — SIEMPRE
    oferta_df = oferta_por_campo(provincia)
    if oferta_df.empty:
        oferta_df = pd.DataFrame(columns=["CAMPO_DETALLADO", "NUM_PROGRAMAS"])

    oferta_df["CAMPO_DISPLAY"] = oferta_df["CAMPO_DETALLADO"].fillna("")
    oferta_df["CAMPO_KEY"] = oferta_df["CAMPO_DISPLAY"].map(norm_search)
    of_map = oferta_df.set_index("CAMPO_KEY")["NUM_PROGRAMAS"].to_dict() if not oferta_df.empty else {}
    of_disp = oferta_df.set_index("CAMPO_KEY")["CAMPO_DISPLAY"].to_dict() if not oferta_df.empty else {}

    # 2) Matriculados
    if provincia:
        mats_df = matriculas_base_provincia(provincia, anio, nivel)
    else:
        mats_df = matriculas_base_nacional(anio, nivel)

    if mats_df.empty:
        mats_df = pd.DataFrame(columns=["CAMPO_BASE", "TOTAL_MATRICULADOS"])

    mats_df["CAMPO_DISPLAY"] = mats_df["CAMPO_BASE"].fillna("")
    mats_df["CAMPO_KEY"] = mats_df["CAMPO_DISPLAY"].map(norm_search)
    ma_map = mats_df.set_index("CAMPO_KEY")["TOTAL_MATRICULADOS"].to_dict() if not mats_df.empty else {}
    ma_disp = mats_df.set_index("CAMPO_KEY")["CAMPO_DISPLAY"].to_dict() if not mats_df.empty else {}

    # 3) Titulados (solo si hay año cohorte específico)
    ti_map = {}
    anio_titulacion = None
    if anio and str(anio).upper() != "ALL":
        try:
            anio_int = int(anio)
            anio_titulacion = anio_int + 4
            tit_df = titulados_por_cohorte(provincia, anio_int)
            if not tit_df.empty:
                ti_map = tit_df.set_index("CAMPO_KEY")["TOTAL_TITULADOS"].to_dict()
        except Exception:
            ti_map = {}
            anio_titulacion = None

    # 4) Union keys: Oferta ∪ Matriculados ∪ Titulados
    keys = sorted(set(of_map.keys()).union(set(ma_map.keys())).union(set(ti_map.keys())))

    merged = []
    for k in keys:
        oferta_val = int(of_map.get(k, 0) or 0)
        mat_val = int(ma_map.get(k, 0) or 0)
        tit_val = int(ti_map.get(k, 0) or 0)

        campo_label = of_disp.get(k) or ma_disp.get(k) or k

        row = {"campo": campo_label, "oferta": oferta_val, "matriculados": mat_val}
        if anio_titulacion is not None:
            row["titulados"] = tit_val
            row["anio_titulacion"] = anio_titulacion

        merged.append(row)

    # 5) Orden:
    #   - Si hay año específico: queremos ver oferta completa => ordenamos por oferta
    #   - Si es histórico (ALL): orden útil por matriculados
    if anio and str(anio).upper() != "ALL":
        return sorted(
            merged,
            key=lambda x: (x["oferta"], x["matriculados"], x.get("titulados", 0)),
            reverse=True
        )

    return sorted(
        merged,
        key=lambda x: (x["matriculados"], x["oferta"]),
        reverse=True
    )

# ───────────────────────── RUTAS UI ─────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/matriculas")
def view_matriculas():
    return render_template("matriculas.html")

# ───────────────────────── API BASE ─────────────────────────

@app.route("/api/provincias_list")
def api_provincias():
    return jsonify(provincias_list())

@app.route("/api/matriculas_years")
def api_years():
    return jsonify(years_list())

@app.route("/api/matriculas_levels")
def api_levels():
    return jsonify(levels_list())

@app.route("/api/oferta_tipo_programa")
def api_oferta_tipo():
    data = oferta_tipo_programa_table()
    return jsonify(data.to_dict(orient="records"))

@app.route("/api/oferta_campo")
def api_oferta_campo():
    prov = request.args.get("provincia")
    data = oferta_por_campo(prov)
    return jsonify(data.to_dict(orient="records"))

@app.route("/api/matriculas_campo_base_nacional")
def api_mat_base_nac():
    anio = request.args.get("anio")
    nivel = request.args.get("nivel")
    data = matriculas_base_nacional(anio, nivel)
    return jsonify(data.to_dict(orient="records"))

@app.route("/api/matriculas_campo_base_provincia")
def api_mat_base_prov():
    prov = request.args.get("provincia")
    if not prov:
        return jsonify([])
    anio = request.args.get("anio")
    nivel = request.args.get("nivel")
    data = matriculas_base_provincia(prov, anio, nivel)
    return jsonify(data.to_dict(orient="records"))

@app.route("/api/matriculas_campo_full_provincia")
def api_mat_full_prov():
    prov = request.args.get("provincia")
    if not prov:
        return jsonify([])
    anio = request.args.get("anio")
    nivel = request.args.get("nivel")
    data = matriculas_full_provincia(prov, anio, nivel)
    return jsonify(data.to_dict(orient="records"))

@app.route("/api/compare")
def api_compare():
    prov = request.args.get("provincia")
    anio = request.args.get("anio")
    nivel = request.args.get("nivel")
    merged = compare_oferta_vs_matriculas(prov, anio, nivel)
    return jsonify({"merged": merged})

@app.route("/api/export_compare_csv")
def api_export_compare_csv():
    prov = request.args.get("provincia")
    anio = request.args.get("anio")
    nivel = request.args.get("nivel")

    merged = compare_oferta_vs_matriculas(prov, anio, nivel)

    si = io.StringIO()
    w = csv.writer(si)

    has_tit = any(("titulados" in r) for r in merged)
    if has_tit:
        w.writerow(["CAMPO_BASE", "OFERTA_NUM_PROGRAMAS", "TOTAL_MATRICULADOS", "TOTAL_TITULADOS", "ANIO_TITULACION"])
        for r in merged:
            w.writerow([r["campo"], r["oferta"], r["matriculados"], r.get("titulados", 0), r.get("anio_titulacion", "")])
    else:
        w.writerow(["CAMPO_BASE", "OFERTA_NUM_PROGRAMAS", "TOTAL_MATRICULADOS"])
        for r in merged:
            w.writerow([r["campo"], r["oferta"], r["matriculados"]])

    mem = io.BytesIO()
    mem.write(si.getvalue().encode("utf-8"))
    mem.seek(0)

    fname = f"comparacion_{'NACIONAL' if not prov else prov}_{datetime.now().strftime('%Y%m%d')}.csv"
    return send_file(mem, as_attachment=True, download_name=fname, mimetype="text/csv")

# ───────────────────────── TOTALES PARA BADGES ─────────────────────────

@app.route("/api/total_oferta_provincia")
def api_total_oferta_provincia():
    """
    Total de campos ofertados (únicos) en oferta vigente.
    """
    provincia = request.args.get("provincia", None)
    tmp = df_of
    if tmp is None or tmp.empty:
        return jsonify({"total_oferta": 0})

    if provincia:
        prov_key = norm_search(provincia)
        tmp = tmp[tmp["PROV_KEY"] == prov_key]

    total = int(tmp["CAMPO_DETALLADO"].nunique()) if "CAMPO_DETALLADO" in tmp.columns else 0
    return jsonify({"total_oferta": total})

@app.route("/api/total_matriculados_provincia")
def api_total_matriculados_provincia():
    provincia = request.args.get("provincia", None)
    anio = request.args.get("anio", None)
    nivel = request.args.get("nivel", None)

    tmp = _filtrar_mat(provincia, anio, nivel)
    if tmp is None or tmp.empty:
        return jsonify({"total_matriculados": 0})

    total = int(tmp[COL_MAT_MAT].sum()) if COL_MAT_MAT in tmp.columns else 0
    return jsonify({"total_matriculados": total})

@app.route("/api/total_titulados_provincia")
def api_total_titulados_provincia():
    """
    cohorte -> año titulación = cohorte + 4
    Ej: cohorte 2020 => titulados 2024
    """
    provincia = request.args.get("provincia", None)
    anio = request.args.get("anio", None)

    if not anio or str(anio).upper() == "ALL":
        return jsonify({"total_titulados": 0, "anio_titulacion": None})

    try:
        coh = int(anio)
    except Exception:
        return jsonify({"total_titulados": 0, "anio_titulacion": None})

    anio_tit = coh + 4
    tmp = _filtrar_tit(provincia, anio_tit)
    total = int(tmp["TITULADOS_TOTALES"].sum()) if (tmp is not None and not tmp.empty and "TITULADOS_TOTALES" in tmp.columns) else 0
    return jsonify({"total_titulados": total, "anio_titulacion": anio_tit})

# ─────────────────────── CARRERAS OFERTADAS ───────────────────────

def total_carreras(provincia=None):
    # total de registros (programas) ofertados (no únicos)
    tmp = df_of
    if tmp is None or tmp.empty:
        return 0
    if provincia:
        prov_key = norm_search(provincia)
        tmp = tmp[tmp["PROV_KEY"] == prov_key]
    return int(len(tmp.index))

@app.route("/api/total_carreras_provincia")
def api_total_carreras_provincia():
    provincia = request.args.get("provincia", None)
    return jsonify({"total_carreras": total_carreras(provincia)})

# ───────────────────────── PIPELINE ACTUALIZAR OFERTA ─────────────────────────

@app.route("/api/actualizar_oferta", methods=["GET"])
def api_actualizar_oferta():
    """
    Ejecuta tu pipeline local (si lo tienes habilitado en tu máquina).
    Nota: en Render no es ideal correr Selenium aquí; esto es solo para local/testing.
    """
    try:
        current_app.logger.info("Ejecutando pipeline: %s", PIPELINE_SCRIPT)

        if not os.path.exists(PIPELINE_SCRIPT):
            return jsonify({"ok": False, "error": f"No existe el pipeline en: {PIPELINE_SCRIPT}"}), 400

        res = subprocess.run(["python", PIPELINE_SCRIPT], capture_output=True, text=True)
        if res.returncode != 0:
            return jsonify({"ok": False, "stderr": res.stderr, "stdout": res.stdout}), 500

        # recargar bases luego del update
        load_base()
        return jsonify({"ok": True, "stdout": res.stdout})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ───────────────────────── Main ─────────────────────────

if __name__ == "__main__":
    # debug True solo en local
    app.run(host="0.0.0.0", port=5000, debug=True)
