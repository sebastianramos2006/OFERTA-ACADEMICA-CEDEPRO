# pipeline_update.py
# Orquesta la actualización de la oferta CES para CEDEPRO

import os
import subprocess
import shutil
from datetime import datetime
import sys

import pandas as pd  # solo para leer totales de F1 original (monitoreo)

DATA_DIR = "data"
F1_PATH = os.path.join(DATA_DIR, "OFERTA_ACAD_CEDEPRO_F_1_MATRICULADOS.xlsx")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")


def backup_f1() -> None:
    """Crea un backup timestamp de la F1 original si existe."""
    if not os.path.exists(F1_PATH):
        print("No existe F1 original, no se crea backup.")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"F1_backup_{ts}.xlsx"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    shutil.copy2(F1_PATH, backup_path)
    print(f"Backup de F1 creado en: {backup_path}")


def run_script(path: str) -> int:
    """Ejecuta un script Python y devuelve su código de salida."""
    print(f"\nEjecutando: {path}")
    result = subprocess.run([sys.executable, path], text=True)
    if result.returncode != 0:
        print(f"{path} terminó con código {result.returncode}")
    else:
        print(f"{path} finalizó correctamente")
    return result.returncode


def leer_total_matriculados(path: str, label: str):
    """
    Lee un Excel y devuelve el total de matriculados si encuentra la columna adecuada.
    Solo para monitoreo (no rompe el pipeline si no coincide).
    """
    if not os.path.exists(path):
        print(f"{label}: archivo no encontrado en {path}")
        return None

    df = pd.read_excel(path)

    posibles = [
        "MATRICULADOS",
        "TOTAL_MATRICULADOS",
        "TOTAL DE MATRICULADOS",
        "TOTAL MATRICULADOS",
    ]

    col_encontrada = None
    for c in posibles:
        if c in df.columns:
            col_encontrada = c
            break

    if col_encontrada is None:
        print(f"{label}: no se encontró columna de matriculados en {path}")
        return None

    total = df[col_encontrada].sum()
    print(f"{label}: total de matriculados = {int(total):,} (columna: {col_encontrada})")
    return total


def pipeline() -> int:
    print("\n==========================")
    print("PIPELINE CEDEPRO – INICIO")
    print("==========================")

    # 0) Backup de F1 (por seguridad, aunque ya no la modificamos automáticamente)
    backup_f1()

    # (Opcional) total original solo para monitoreo
    leer_total_matriculados(F1_PATH, "F1 ORIGINAL")

    # 1) Descargar oferta CES (genera data/OFERTA_ACAD_CES_RAW.xlsx)
    rc = run_script("update_oferta_selenium.py")
    if rc != 0:
        print("Error en update_oferta_selenium.py. Se detiene el pipeline.")
        return 1

    # 2) Clasificar CES_RAW con CAMPO DETALLADO
    #    (genera data/OFERTA_ACAD_CES_CLASIFICADA.xlsx)
    if os.path.exists("clasificar_oferta_nueva.py"):
        rc = run_script("clasificar_oferta_nueva.py")
        if rc != 0:
            print("Error en clasificar_oferta_nueva.py. Se detiene el pipeline.")
            return 1
    else:
        print("No se encontró clasificar_oferta_nueva.py, se omite este paso.")

    # 3) Construir F1_VIGENTE usando solo oferta oficial CES
    #    y columnas estáticas de F1_ACT (si existe el script)
    if os.path.exists("construir_f1_vigente.py"):
        rc = run_script("construir_f1_vigente.py")
        if rc != 0:
            print("Error en construir_f1_vigente.py. Se detiene el pipeline.")
            return 1
    else:
        print("No se encontró construir_f1_vigente.py, se omite este paso.")

    # 4) Comparar bases F1_ACT vs CES_RAW (opcional, solo diagnóstico)
    if os.path.exists("comparar_bases.py"):
        rc = run_script("comparar_bases.py")
        if rc != 0:
            print("Error en comparar_bases.py. Se detiene el pipeline.")
            return 1
    else:
        print("No se encontró comparar_bases.py, se omite este paso.")

    print("\n==========================")
    print("PIPELINE COMPLETADO")
    print("==========================")
    return 0


if __name__ == "__main__":
    sys.exit(pipeline())
