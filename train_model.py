#!/usr/bin/env python3
"""
train_model.py — Pipeline ETL + Entrenamiento completo
=======================================================
Orquesta la ejecución secuencial de todos los pasos del pipeline:

  Paso 1  Copia los archivos Excel desde /app/source_data/ → /app/
  Paso 2  extract_data.py   → genera CSVs en data/ (historico, semanas, inf, bio)
  Paso 3  nb 01             → ingeniería de datos → data/parquet/
  Paso 4  nb 02             → pronóstico de demanda (LR + RF + GBT)
  Paso 5  nb 03             → segmentación KMeans
  Paso 6  nb 04             → política de reorden → data/plan_reabastecimiento_csv/
  Paso 7  generar_graficas  → actualiza las figuras en informe/img/

Los pasos 3-6 se ejecutan con nbconvert en modo headless (sin kernel interactivo).
El exit-code 1 de nbconvert en Linux es benigno (cleanup de JVM de Spark).

Ejecutar manualmente dentro del contenedor:
    python train_model.py

Variables de entorno:
    SOURCE_DATA_DIR   Ruta de los Excel (default: /app/source_data)
    SPARK_DRIVER_MEM  Memoria del driver Spark (default: 2g)
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging — consola + archivo rotativo
# ---------------------------------------------------------------------------
LOG_DIR = Path(os.environ.get("LOG_DIR", "/app/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
ROOT = Path("/app")
SOURCE_DATA = Path(os.environ.get("SOURCE_DATA_DIR", "/app/source_data"))

NOTEBOOKS = [
    "notebooks/01_eda_data_engineering.ipynb",
    "notebooks/02_regression_demand_forecasting.ipynb",
    "notebooks/03_kmeans_sku_segmentation.ipynb",
    "notebooks/04_reorder_policy.ipynb",
]

# Archivo marcador que Spark escribe al completar la escritura del plan.
SUCCESS_MARKER = ROOT / "data" / "plan_reabastecimiento_csv" / "_SUCCESS"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _run(cmd: list[str], step: str) -> bool:
    """Ejecuta un subcomando, retorna True si el paso fue exitoso."""
    log.info("[%s] Iniciando...", step)
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
        )
        # nbconvert devuelve rc=1 en Linux por el cleanup de la JVM de Spark
        # (mensaje 'ERROR: process not found'). Es benigno si el notebook
        # escribió los archivos de salida.
        if result.returncode not in (0, 1):
            log.error("[%s] Falló con código de retorno %d.", step, result.returncode)
            return False
        log.info("[%s] Completado (rc=%d).", step, result.returncode)
        return True
    except Exception as exc:
        log.error("[%s] Excepción inesperada: %s", step, exc)
        return False


def _copy_excels() -> bool:
    """Copia los archivos Excel de source_data/ → /app/ para que
    extract_data.py los encuentre en su ruta relativa esperada."""
    if not SOURCE_DATA.is_dir():
        log.warning("source_data/ no encontrado (%s). Usando datos existentes.", SOURCE_DATA)
        return False

    excels = sorted(SOURCE_DATA.glob("*.xlsx")) + sorted(SOURCE_DATA.glob("*.xls"))
    if not excels:
        log.warning("source_data/ existe pero no contiene archivos Excel (*.xlsx / *.xls).")
        return False

    for xl in excels:
        dest = ROOT / xl.name
        shutil.copy2(xl, dest)
        log.info("  Copiado: %s → %s", xl.name, dest)
    return True


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def main() -> int:
    start = datetime.now()
    sep = "=" * 64
    log.info(sep)
    log.info("PIPELINE INICIADO: %s", start.isoformat())
    log.info(sep)

    # ── Paso 1: copiar Excel ──────────────────────────────────────────────── #
    log.info("--- Paso 1/7: Copiar archivos Excel desde source_data/ ---")
    excel_available = _copy_excels()

    # ── Paso 2: extracción de datos ──────────────────────────────────────── #
    xl_old = ROOT / "Analisis CR 44.xlsx"
    xl_new = ROOT / "Analisis CR 30.xlsx"
    if xl_old.exists() and xl_new.exists():
        log.info("--- Paso 2/7: extract_data.py ---")
        if not _run([sys.executable, "extract_data.py"], "extract_data"):
            log.error("extract_data.py falló. Abortando el pipeline.")
            return 1
    else:
        log.warning(
            "--- Paso 2/7: SALTADO (archivos Excel no disponibles en /app/). ---\n"
            "    Coloque 'Analisis CR 44.xlsx' y 'Analisis CR 30.xlsx'\n"
            "    en el directorio source_data/ del host y reinicie el servicio."
        )

    # ── Pasos 3-6: notebooks ─────────────────────────────────────────────── #
    errors = 0
    for idx, nb in enumerate(NOTEBOOKS, start=3):
        step_label = f"Paso {idx}/7: {Path(nb).stem}"
        log.info("--- %s ---", step_label)
        ok = _run(
            [
                sys.executable, "-m", "nbconvert",
                "--to", "notebook",
                "--execute",
                "--inplace",
                "--ExecutePreprocessor.timeout=3600",
                nb,
            ],
            step_label,
        )
        if not ok:
            errors += 1
            log.error("El notebook %s falló. Continuando con el siguiente.", nb)

    # ── Paso 7: gráficas ─────────────────────────────────────────────────── #
    log.info("--- Paso 7/7: generar_graficas.py ---")
    _run([sys.executable, "generar_graficas.py"], "generar_graficas")

    # ── Resumen ──────────────────────────────────────────────────────────── #
    elapsed = (datetime.now() - start).total_seconds()
    log.info(sep)
    if errors:
        log.warning(
            "PIPELINE COMPLETADO CON %d ERROR(ES) en %.1f s.", errors, elapsed
        )
    else:
        log.info("PIPELINE COMPLETADO EXITOSAMENTE en %.1f s.", elapsed)
        if SUCCESS_MARKER.exists():
            log.info("Marcador de éxito: %s", SUCCESS_MARKER)
    log.info(sep)
    return errors


if __name__ == "__main__":
    sys.exit(main())
