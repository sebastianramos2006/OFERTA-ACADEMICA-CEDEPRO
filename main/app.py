# app.py — CEDEPRO Matriculados + Titulados (compatible con tu matriculas.js)
# ✅ Oferta SIEMPRE sale de OFERTA VIGENTE
# ✅ Matriculados + Titulados salen de F1
# ✅ En Render: si no existe /data/*.xlsx => descarga desde Google Drive (URL) a /tmp
# ✅ Arregla rutas de templates/static cuando app.py está dentro de /main
# ✅ FIX: normalización de provincias + mapping códigos (SE/SD/etc) + variantes tipo ELORO/_GUAYAS

import os
import re
import io
import csv
import unicodedata
import logging
import subprocess
from datetime import datetime
from urllib.request import urlopen, Request

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))              # .../main
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))           # repo root

TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")
STATIC_DIR = os.path.join(ROOT_DIR, "static")

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)

# Data local dentro del repo (solo existe si lo subes al repo)
DATA_DIR = os.path.join(ROOT_DIR, "data")

# Archivos esperados
DEFAULT_OFERTA_FILENAME = "OFERTA_ACAD_CEDEPRO_F_1_VIGENTE.xlsx"
DEFAULT_F1_FILENAME = "OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS.xlsx"

# ENV paths (local/Render). Si no, usa /data/...
ENV_OFERTA_PATH = os.environ.get("CEDEPRO_OFERTA_VIGENTE_PATH")
ENV_F1_PATH = os.environ.get("CEDEPRO_F1_PATH")

OFERTA_VIGENTE_PATH = ENV_OFERTA_PATH or os.path.join(DATA_DIR, DEFAULT_OFERTA_FILENAME)
F1_PATH = ENV_F1_PATH or os.path.join(DATA_DIR, DEFAULT_F1_FILENAME)

# ENV URLs (Google Drive direct download)
ENV_OFERTA_URL = (
    os.environ.get("CEDEPRO_OFERTA_VIGENTE_URL")
    or os.environ.get("OFERTA_REMOTE_URL")
    or os.environ.get("OFERTA_URL")
)
ENV_F1_URL = (
    os.environ.get("CEDEPRO_F1_URL")
    or os.environ.get("F1_REMOTE_URL")
    or os.environ.get("F1_URL")
)

# Donde guardamos descargas en Render (disco temporal)
TMP_DIR = os.environ.get("TMPDIR", "/tmp")
OFERTA_TMP_PATH = os.path.join(TMP_DIR, DEFAULT_OFERTA_FILENAME)
F1_TMP_PATH = os.path.join(TMP_DIR, DEFAULT_F1_FILENAME)

# Pipeline (solo local; en Render normalmente NO conviene correr Selenium aquí)
PIPELINE_SCRIPT = os.path.join(BASE_DIR, "pipeline_update.py")

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
    for c in candidates:
        if c in cols:
            return c
    norm_map = {norm_search(c): c for c in cols}
    for cand in candidates:
        k = norm_search(cand)
        if k in norm_map:
            return norm_map[k]
    return None

# =========================
# FIX PROVINCIAS (códigos + variantes)
# =========================

PROV_CODE_MAP = {
    "SE": "SANTA ELENA",
    "SD": "SANTO DOMINGO DE LOS TSÁCHILAS",
    "ST": "SANTO DOMINGO DE LOS TSÁCHILAS",
    "GPS": "GALÁPAGOS",
    "GA": "GALÁPAGOS",
}

# OJO: estas llaves deben estar YA normalizadas (norm_search)
PROV_TEXT_MAP = {
    "GALAPAGOS": "GALÁPAGOS",
    "SANTO DOMINGO": "SANTO DOMINGO DE LOS TSÁCHILAS",
    "SANTO DOMINGO DE LOS TSACHILAS": "SANTO DOMINGO DE LOS TSÁCHILAS",

    # Variantes típicas de data sucia:
    "ELORO": "EL ORO",
    "EL ORO": "EL ORO",
    "GUAYAS": "GUAYAS",
}

def normalize_prov_token(v: str) -> str:
    s = clean_str(v)
    # soportar "_GUAYAS", "  guayas  ", etc
    s = s.replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""

    s_norm = norm_search(s)

    # 1) códigos (SE/SD/GA/etc)
    if s_norm in PROV_CODE_MAP:
        return PROV_CODE_MAP[s_norm]

    # 2) texto sucio (ELORO -> EL ORO)
    if s_norm in PROV_TEXT_MAP:
        return PROV_TEXT_MAP[s_norm]

    # 3) default: devolvemos normalizado (sin tildes, uppercase)
    return s_norm

def normalize_campo_p(v: str) -> str:
    v = clean_str(v)
    v = v.replace(" - ", " ")
    v = re.sub(r"\s+", " ", v).strip()
    return v

def split_campo_p(v: str):
    s = normalize_campo_p(v)
    if "_" in s:
        parts = [p.strip() for p in s.split("_", 1)]
        if len(parts) == 2:
            base = parts[0]
            prov = normalize_prov_token(parts[1])
            return base, prov
    return s, ""

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def download_file(url: str, dest_path: str) -> bool:
    if not url:
        return False
    try:
        ensure_dir(os.path.dirname(dest_path))
        logging.info("⬇️ Descargando: %s -> %s", url, dest_path)
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=60) as r:
            content = r.read()
        with open(dest_path, "wb") as f:
            f.write(content)

        ok = os.path.exists(dest_path) and os.path.getsize(dest_path) > 0
        logging.info("✅ Descarga OK (%s bytes)", os.path.getsize(dest_path) if ok else 0)
        return ok
    except Exception as e:
        logging.error("❌ Error descargando %s: %s", url, str(e))
        return False

def resolve_data_path(local_path: str, url_env: str, tmp_path: str) -> str:
    if os.path.exists(local_path):
        return local_path
    if url_env:
        if download_file(url_env, tmp_path):
            return tmp_path
    return local_path

def try_autofind_in_data_dir(preferred_path: str, fallback_keywords: list[str]) -> str:
    if os.path.exists(preferred_path):
        return preferred_path

    if not os.path.isdir(DATA_DIR):
        return preferred_path

    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith((".xlsx", ".xls"))]
    if not files:
        return preferred_path

    pref_name = os.path.basename(preferred_path).lower()
    for f in files:
        if f.lower() == pref_name:
            return os.path.join(DATA_DIR, f)

    best = None
    best_score = -1
    for f in files:
        name = f.lower()
        score = sum(1 for kw in fallback_keywords if kw.lower() in name)
        if score > best_score:
            best_score = score
            best = f

    if best and best_score > 0:
        return os.path.join(DATA_DIR, best)

    return preferred_path

# ───────────────────────────── Globals ─────────────────────────────

df_of_raw = None
df_of = None
df_mat_raw = None
df_mat = None
df_tit = None

COL_PROV_OF = None
COL_CAMPO_OF = None
COL_IES_OF = None
COL_TIPO_PROG_OF = None

COL_MAT_ANIO = None
COL_MAT_NIVEL = None
COL_MAT_CAMPO_P = None
COL_MAT_PROV = None
COL_MAT_MAT = None

COL_TIT_P = None
COL_TIT_ANIO = None
COL_TIT_TOTAL = None

candidates_map = {
    "provincia_of": ["PROVINCIA", "Provincia"],
    "campo_of": ["CAMPO DETALLADO", "CAMPO_DETALLADO", "CAMPO_DETALLADO_P", "CAMPO DETALLADO P"],
    "ies_of": ["Universidad", "INSTITUCIÓN DE EDUCACIÓN SUPERIOR", "INSTITUCION DE EDUCACION SUPERIOR", "IES"],
    "tipo_prog_of": ["TIPO DE PROGRAMA", "TIPO_PROGRAMA", "TIPO PROGRAMA", "NIVEL"],

    "anio_mat": ["AÑO DE MATRICULACIÓN", "AÑO_MATRICULACIÓN", "AÑO", "ANIO", "AÑO DE MATRICULACION", "ANIO DE MATRICULACION"],
    "nivel_mat": ["TIPO DE PROGRAMA", "NIVEL_FORMACION", "NIVEL FORMACION", "NIVEL DE FORMACIÓN", "NIVEL DE FORMACION"],
    "campo_p": ["CAMPO_DETALLADO_P", "CAMPO DETALLADO P", "CAMPO DETALLADO", "CAMPO_DETALLADO"],
    "prov_mat": ["PROVINCIA", "Provincia"],
    "matriculados": ["TOTAL_MATRICULADOS", "MATRICULADOS", "TOTAL DE MATRICULADOS", "TOTAL MATRICULADOS"],

    "titulados_p": ["TITULADOS_P", "TITULADOS P"],
    "anio_titulados": ["AÑO_DE_TITULADOS", "ANIO_DE_TITULADOS", "AÑO TITULADOS", "ANIO TITULADOS"],
    "titulados_totales": ["TITULADOS_TOTALES", "TOTAL_TITULADOS", "TOTAL DE TITULADOS", "TITULADOS TOTALES"],
}

# ───────────────────────────── Loaders ─────────────────────────────

def load_base():
    global df_of_raw, df_of, df_mat_raw, df_mat, df_tit
    global COL_PROV_OF, COL_CAMPO_OF, COL_IES_OF, COL_TIPO_PROG_OF
    global COL_MAT_ANIO, COL_MAT_NIVEL, COL_MAT_CAMPO_P, COL_MAT_PROV, COL_MAT_MAT
    global COL_TIT_P, COL_TIT_ANIO, COL_TIT_TOTAL
    global OFERTA_VIGENTE_PATH, F1_PATH

    ensure_dir(DATA_DIR)

    oferta_path_resolved = resolve_data_path(OFERTA_VIGENTE_PATH, ENV_OFERTA_URL, OFERTA_TMP_PATH)
    f1_path_resolved = resolve_data_path(F1_PATH, ENV_F1_URL, F1_TMP_PATH)

    oferta_path_resolved = try_autofind_in_data_dir(
        oferta_path_resolved,
        fallback_keywords=["vigente", "f_1_vigente", "f1_vigente", "oferta"]
    )
    f1_path_resolved = try_autofind_in_data_dir(
        f1_path_resolved,
        fallback_keywords=["matriculados", "f_1_matriculados", "f1_matriculados", "f1"]
    )

    OFERTA_VIGENTE_PATH = oferta_path_resolved
    F1_PATH = f1_path_resolved

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

        if COL_PROV_OF and COL_PROV_OF in df_of_local.columns:
            df_of_local["PROV_DISPLAY"] = df_of_local[COL_PROV_OF].fillna("").map(clean_str).map(normalize_prov_token)
        else:
            df_of_local["PROV_DISPLAY"] = ""

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

        campo_src = df_mat_local[COL_MAT_CAMPO_P].fillna("").map(clean_str) if COL_MAT_CAMPO_P else pd.Series([""] * len(df_mat_local))
        campo_src = campo_src.map(normalize_campo_p)
        has_underscore = campo_src.astype(str).str.contains("_", regex=False)

        if has_underscore.any():
            campo_p_final = campo_src
        else:
            prov_src = df_mat_local[COL_MAT_PROV].fillna("").map(clean_str) if (COL_MAT_PROV and COL_MAT_PROV in df_mat_local.columns) else pd.Series([""] * len(df_mat_local))
            prov_src = prov_src.map(normalize_prov_token)
            campo_p_final = (campo_src + "_" + prov_src).map(normalize_campo_p)

        df_mat_local["CAMPO_DETALLADO_P"] = campo_p_final

        bases, provs = [], []
        for v in df_mat_local["CAMPO_DETALLADO_P"].astype(str):
            b, p = split_campo_p(v)
            bases.append(b)
            provs.append(p)

        df_mat_local["CAMPO_BASE_P"] = bases
        df_mat_local["PROV_DESDE_CAMPO_P"] = provs

        df_mat_local["PROV_KEY"] = df_mat_local["PROV_DESDE_CAMPO_P"].map(norm_search)
        df_mat_local["CAMPO_KEY"] = df_mat_local["CAMPO_BASE_P"].map(norm_search)

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

            df_tit_local = df_tit_local[df_tit_local["CAMPO_KEY"].astype(str).str.len() > 0].copy()

            df_tit = df_tit_local
            logging.info("✅ Titulados cargados: %s filas", len(df_tit))
        else:
            df_tit = pd.DataFrame(columns=[
                "TITULADOS_P", "ANIO_TITULADOS", "TITULADOS_TOTALES",
                "PROV_KEY", "CAMPO_KEY", "CAMPO_BASE_T"
            ])
            logging.warning("⚠️ No se detectaron columnas completas de TITULADOS.")
    except Exception as e:
        logging.warning("⚠️ Titulados no disponible: %s", str(e))
        df_tit = pd.DataFrame(columns=[
            "TITULADOS_P", "ANIO_TITULADOS", "TITULADOS_TOTALES",
            "PROV_KEY", "CAMPO_KEY", "CAMPO_BASE_T"
        ])

# Carga inicial
load_base()

# ──────────────────────── LISTAS FILTROS ────────────────────────

def provincias_list():
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
    if df_of is None or df_of.empty:
        return pd.DataFrame(columns=["CAMPO_DETALLADO", "NUM_PROGRAMAS"])

    tmp = df_of
    if provincia:
        prov_key = norm_search(normalize_prov_token(provincia))
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
        prov_norm = norm_search(normalize_prov_token(provincia))
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
        prov_norm = norm_search(normalize_prov_token(provincia))
        tmp = tmp[tmp["PROV_KEY"] == prov_norm]

    if anio_titulacion:
        try:
            a = int(anio_titulacion)
            tmp = tmp[tmp["ANIO_TITULADOS"] == a]
        except Exception:
            pass

    return tmp

def titulados_por_cohorte(provincia=None, anio_cohorte=None):
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
    oferta_df = oferta_por_campo(provincia)
    if oferta_df.empty:
        oferta_df = pd.DataFrame(columns=["CAMPO_DETALLADO", "NUM_PROGRAMAS"])

    oferta_df["CAMPO_DISPLAY"] = oferta_df["CAMPO_DETALLADO"].fillna("")
    oferta_df["CAMPO_KEY"] = oferta_df["CAMPO_DISPLAY"].map(norm_search)
    of_map = oferta_df.set_index("CAMPO_KEY")["NUM_PROGRAMAS"].to_dict() if not oferta_df.empty else {}
    of_disp = oferta_df.set_index("CAMPO_KEY")["CAMPO_DISPLAY"].to_dict() if not oferta_df.empty else {}

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
    provincia = request.args.get("provincia", None)
    tmp = df_of
    if tmp is None or tmp.empty:
        return jsonify({"total_oferta": 0})

    if provincia:
        prov_key = norm_search(normalize_prov_token(provincia))
        tmp = tmp[tmp["PROV_KEY"] == prov_key]

    # Total oferta = total de programas (filas) en oferta vigente (filtradas por provincia)
    total = int(len(tmp))
    return jsonify({"total_oferta": total})

@app.route("/api/total_carreras_provincia")
def api_total_carreras_provincia():
    provincia = request.args.get("provincia", None)
    tmp = df_of
    if tmp is None or tmp.empty:
        return jsonify({"total_carreras": 0})

    if provincia:
        prov_key = norm_search(normalize_prov_token(provincia))
        if "PROV_KEY" in tmp.columns:
            tmp = tmp[tmp["PROV_KEY"] == prov_key]

    col_programa = None
    for c in ["PROGRAMA / CARRERA", "PROGRAMA", "CARRERA", "NOMBRE_PROGRAMA", "NOMBRE_CARRERA"]:
        if c in tmp.columns:
            col_programa = c
            break

    if col_programa:
        total = int(tmp[col_programa].nunique())
    else:
        total = int(len(tmp))

    return jsonify({"total_carreras": total})

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

# ───────────────────────── PIPELINE ─────────────────────────

@app.route("/api/actualizar_oferta", methods=["GET"])
def api_actualizar_oferta():
    """
    En Render NO conviene (Selenium). Úsalo local.
    """
    try:
        current_app.logger.info("Ejecutando pipeline: %s", PIPELINE_SCRIPT)

        if not os.path.exists(PIPELINE_SCRIPT):
            return jsonify({"ok": False, "error": f"No existe el pipeline en: {PIPELINE_SCRIPT}"}), 400

        res = subprocess.run(["python", PIPELINE_SCRIPT], capture_output=True, text=True)
        if res.returncode != 0:
            return jsonify({"ok": False, "stderr": res.stderr, "stdout": res.stdout}), 500

        load_base()
        return jsonify({"ok": True, "stdout": res.stdout})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ───────────────────────── Main ─────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
