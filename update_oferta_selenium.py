# update_oferta_selenium.py
# Descarga la oferta vigente del CES usando Selenium
# y genera data/OFERTA_ACAD_CES_RAW.xlsx
#
# AHORA:
# - Detecta las columnas usando el THEAD de la tabla.
# - Incluye PROVINCIA (si existe en la tabla) en el Excel resultante.

import os
import sys
import time
import traceback

import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

DATA_DIR = "data"
CES_RAW_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CES_RAW.xlsx")

CES_URL = "https://appcmi.ces.gob.ec/oferta_vigente/inicio.php"


def _build_driver(headless: bool = True, timeout: int = 60):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(timeout)
    return driver


def _seleccionar_tercer_nivel_y_consultar(driver, wait, add_log):
    """
    1) Busca el combo 'Tipo de programa / carrera'
    2) Elige la opción que contenga 'TERCER' y 'NIVEL'
    3) Pulsa el botón CONSULTAR
    """
    try:
        select_elem = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//label[contains(translate(., 'TIPO', 'tipo'), 'tipo de programa')]/following::select[1]"
                )
            )
        )
        sel = Select(select_elem)

        opcion_tercer = None
        for opt in sel.options:
            txt = (opt.text or "").upper()
            if "TERCER" in txt and "NIVEL" in txt:
                opcion_tercer = opt.text
                break

        if opcion_tercer:
            sel.select_by_visible_text(opcion_tercer)
            add_log(f"Filtro 'Tipo de programa / carrera' = '{opcion_tercer}'.")
        else:
            add_log(
                "No se encontró opción que contenga 'TERCER' y 'NIVEL' en el filtro. "
                "Se deja el valor por defecto."
            )
    except TimeoutException:
        add_log("No se encontró el filtro 'Tipo de programa / carrera'. Se continúa sin aplicarlo.")
    except Exception as e:
        add_log(f"Error al seleccionar 'Tercer nivel': {e}")

    # Pulsar CONSULTAR si existe
    try:
        btn_consultar = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(., 'CONSULTAR') or contains(., 'Consultar')]")
            )
        )
        btn_consultar.click()
        add_log("Botón CONSULTAR presionado.")
    except TimeoutException:
        add_log("No se encontró botón CONSULTAR.")
    except Exception as e:
        add_log(f"Error al pulsar CONSULTAR: {e}")


def _cambiar_page_size_100(driver, wait, add_log):
    """
    Cambia el tamaño de página a 100 registros usando el <select> de la tabla.
    Intenta primero localizar el select asociado a 'registros' / 'Mostrar',
    y si no, busca cualquier select con opciones 10 y 100.
    """
    try:
        select_elem = None

        # 1) Select asociado a texto "registros" / "Mostrar"
        try:
            select_elem = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//label[contains(., 'egistros') or contains(., 'ostrar')]/following::select[1]"
                    )
                )
            )
            add_log("Selector de tamaño de página encontrado por etiqueta.")
        except TimeoutException:
            add_log("No se encontró selector de tamaño de página por etiqueta; se busca genérico.")

        # 2) Fallback genérico: cualquier select con opciones 10 y 100
        if select_elem is None:
            select_elem = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//select[option[contains(normalize-space(.), '10')] "
                        "and option[contains(normalize-space(.), '100')]]"
                    )
                )
            )
            add_log("Selector de tamaño de página encontrado por búsqueda genérica.")

        sel = Select(select_elem)

        opcion_100 = None
        for opt in sel.options:
            txt = (opt.text or "").strip()
            if "100" in txt:
                opcion_100 = opt.text
                break

        if opcion_100:
            sel.select_by_visible_text(opcion_100)
            add_log(f"Tamaño de página cambiado a: '{opcion_100}'.")
            time.sleep(1.5)  # tiempo para que la tabla se recargue
        else:
            add_log("El selector de tamaño de página no tiene opción con '100'.")
    except TimeoutException:
        add_log("No se encontró selector de tamaño de página; se usa el valor por defecto.")
    except Exception as e:
        add_log(f"Error al ajustar tamaño de página a 100: {e}")


def _normalizar_header(txt: str) -> str:
    """
    Normaliza un texto de encabezado para poder buscar por palabras clave.
    """
    import unicodedata
    if txt is None:
        return ""
    s = txt.strip().upper()
    s = "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )
    while "  " in s:
        s = s.replace("  ", " ")
    return s


def _detectar_indices_columnas(driver, add_log):
    """
    Lee el THEAD de la tabla y devuelve un dict con los índices de columna:
      {
        "codigo_ies": idx,
        "universidad": idx,
        "financiamiento": idx,
        "tipo_ies": idx,
        "programa": idx,
        "titulo": idx,
        "provincia": idx or None
      }
    Si algo no se encuentra, deja None y luego se usa un fallback.
    """
    headers = driver.find_elements(By.XPATH, "//table//thead//tr[1]/th")
    if not headers:
        add_log("No se pudo leer el THEAD de la tabla; se usarán índices fijos 0-5.")
        return {
            "codigo_ies": 0,
            "universidad": 1,
            "financiamiento": 2,
            "tipo_ies": 3,
            "programa": 4,
            "titulo": 5,
            "provincia": None,
        }

    textos = [_normalizar_header(h.text) for h in headers]
    add_log("Encabezados detectados en tabla CES:")
    for i, t in enumerate(textos):
        add_log(f"  Col {i}: {t}")

    def buscar_idx(cond):
        for i, t in enumerate(textos):
            if cond(t):
                return i
        return None

    idx_codigo = buscar_idx(lambda t: "CODIGO" in t and "IES" in t)
    idx_universidad = buscar_idx(lambda t: "UNIVERSIDAD" in t or "INSTITUCION" in t)
    idx_financ = buscar_idx(lambda t: "FINANC" in t)
    idx_tipo_ies = buscar_idx(lambda t: "TIPO" in t and ("IES" in t or "INSTITUCION" in t))
    idx_programa = buscar_idx(lambda t: "PROGRAMA" in t or "CARRERA" in t)
    idx_titulo = buscar_idx(lambda t: "TITULO" in t or "TÍTULO" in t)
    idx_provincia = buscar_idx(lambda t: "PROVINCIA" in t)

    # Fallbacks si algo quedó en None (usamos el orden clásico 0-5)
    if idx_codigo is None:
        idx_codigo = 0
    if idx_universidad is None and len(textos) > 1:
        idx_universidad = 1
    if idx_financ is None and len(textos) > 2:
        idx_financ = 2
    if idx_tipo_ies is None and len(textos) > 3:
        idx_tipo_ies = 3
    if idx_programa is None and len(textos) > 4:
        idx_programa = 4
    if idx_titulo is None and len(textos) > 5:
        idx_titulo = 5

    add_log("Mapeo de columnas usado para scraping:")
    add_log(f"  Código IES   -> col {idx_codigo}")
    add_log(f"  Universidad  -> col {idx_universidad}")
    add_log(f"  Financiamiento -> col {idx_financ}")
    add_log(f"  Tipo IES     -> col {idx_tipo_ies}")
    add_log(f"  Programa     -> col {idx_programa}")
    add_log(f"  Título       -> col {idx_titulo}")
    if idx_provincia is not None:
        add_log(f"  PROVINCIA    -> col {idx_provincia}")
    else:
        add_log("  PROVINCIA    -> NO encontrada en encabezados; se dejará en blanco.")

    return {
        "codigo_ies": idx_codigo,
        "universidad": idx_universidad,
        "financiamiento": idx_financ,
        "tipo_ies": idx_tipo_ies,
        "programa": idx_programa,
        "titulo": idx_titulo,
        "provincia": idx_provincia,
    }


def _scrapear_tabla_oferta(headless: bool, timeout: int):
    """
    Navega a la tabla del CES, aplica filtro 'Tercer nivel', ajusta tamaño de
    página a 100 registros y devuelve:
      - df (DataFrame con la información)
      - log (lista de mensajes)
    """
    log = []

    def add_log(msg: str):
        log.append(msg)

    driver = _build_driver(headless=headless, timeout=timeout)
    wait = WebDriverWait(driver, timeout)

    try:
        add_log(f"Abrir URL CES: {CES_URL}")
        driver.get(CES_URL)
        time.sleep(3)

        _seleccionar_tercer_nivel_y_consultar(driver, wait, add_log)

        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//table//tbody/tr")))
            add_log("Tabla de resultados encontrada.")
        except TimeoutException:
            add_log("No se encontraron filas de tabla tras aplicar filtros.")
            return pd.DataFrame(), log

        # Cambiar tamaño de página a 100 registros si es posible
        _cambiar_page_size_100(driver, wait, add_log)

        # Detectar índices de columnas (incluyendo PROVINCIA)
        col_idx = _detectar_indices_columnas(driver, add_log)

        registros = []
        pagina = 1
        total_reg_prev = 0
        max_paginas_seguras = 2000

        while pagina <= max_paginas_seguras:
            filas = wait.until(
                EC.presence_of_all_elements_located((By.XPATH, "//table//tbody/tr"))
            )

            for fila in filas:
                celdas = fila.find_elements(By.TAG_NAME, "td")
                if not celdas:
                    continue

                def get_cell(idx):
                    if idx is None:
                        return ""
                    if idx < 0 or idx >= len(celdas):
                        return ""
                    return celdas[idx].text.strip()

                codigo_ies = get_cell(col_idx["codigo_ies"])
                universidad = get_cell(col_idx["universidad"])
                financiamiento = get_cell(col_idx["financiamiento"])
                tipo_ies = get_cell(col_idx["tipo_ies"])
                programa = get_cell(col_idx["programa"])
                titulo = get_cell(col_idx["titulo"])
                provincia = get_cell(col_idx["provincia"])

                registros.append(
                    {
                        "Código IES": codigo_ies,
                        "Universidad": universidad,
                        "Financiamiento": financiamiento,
                        "Tipo IES": tipo_ies,
                        "PROGRAMA / CARRERA": programa,
                        "Título que otorga": titulo,
                        "PROVINCIA": provincia,  # <-- NUEVA COLUMNA
                    }
                )

            add_log(f"Página {pagina}: filas acumuladas {len(registros)}.")

            # Intentar ir a la siguiente página
            try:
                next_li = driver.find_element(
                    By.XPATH,
                    "//li[contains(@class,'next') or .//a[contains(., 'Siguiente') or contains(., 'Next')]]",
                )
            except WebDriverException:
                add_log("No se encontró botón Siguiente. Fin de paginación.")
                break

            classes = (next_li.get_attribute("class") or "").lower()
            if "disabled" in classes or "ui-state-disabled" in classes:
                add_log("Botón Siguiente deshabilitado. Última página.")
                break

            try:
                clickable = next_li.find_element(By.TAG_NAME, "a")
            except WebDriverException:
                clickable = next_li

            clickable.click()
            pagina += 1
            time.sleep(1.0)

            if len(registros) == total_reg_prev:
                add_log(
                    "No se encontraron registros nuevos al avanzar de página. "
                    "Se detiene la paginación."
                )
                break
            total_reg_prev = len(registros)

        df = pd.DataFrame(registros)
        add_log(f"Total registros capturados: {len(df)}")
        return df, log

    finally:
        driver.quit()


def actualizar_oferta_ces(headless: bool = True, timeout: int = 60):
    """
    Función principal que se importa desde app.py o se ejecuta en consola.

    Devuelve:
      ok (bool), stdout (str), stderr (str)
    """
    stdout_lines = []
    stderr_lines = []

    def log(msg: str):
        stdout_lines.append(msg)

    try:
        log("Iniciando actualizacion de oferta CES.")
        df, log_scrap = _scrapear_tabla_oferta(headless=headless, timeout=timeout)
        stdout_lines.extend(log_scrap)

        if df.empty:
            msg = "La tabla del CES se descargó vacía. No se genera archivo."
            stderr_lines.append(msg)
            return False, "\n".join(stdout_lines), "\n".join(stderr_lines)

        os.makedirs(DATA_DIR, exist_ok=True)
        df.to_excel(CES_RAW_PATH, index=False)
        log(f"Archivo guardado en: {CES_RAW_PATH}")
        log("Actualizacion de oferta CES completada correctamente.")

        return True, "\n".join(stdout_lines), "\n".join(stderr_lines)

    except Exception as e:
        stderr_lines.append(str(e))
        stderr_lines.append(traceback.format_exc())
        return False, "\n".join(stdout_lines), "\n".join(stderr_lines)


if __name__ == "__main__":
    ok, out, err = actualizar_oferta_ces(headless=False)

    if out:
        print(out)

    if not ok and err:
        print(err, file=sys.stderr)

    sys.exit(0 if ok else 1)
