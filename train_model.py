"""
train_model.py — Pipeline ETL + Entrenamiento completo
=======================================================
Orquesta la ejecución secuencial de todos los pasos del pipeline:

  Paso 1  Copia los archivos Excel desde SOURCE_DATA_DIR → el directorio del proyecto
  Paso 2  extract_data.py   → genera CSVs en data/ (historico, semanas, inf, bio)
  Paso 3  nb 01             → ingeniería de datos → data/parquet/
  Paso 4  nb 02             → pronóstico de demanda (LR + RF + GBT)
  Paso 5  nb 03             → segmentación KMeans
  Paso 6  nb 04             → política de reorden → data/plan_reabastecimiento_csv/
  Paso 7  generar_graficas  → actualiza las figuras en informe/img/

Los pasos 3-6 se ejecutan con nbconvert en modo headless (sin kernel interactivo).

Ejecutar manualmente dentro del contenedor:
    python train_model.py

Variables de entorno:
    SOURCE_DATA_DIR   Ruta de los Excel (default: /app/source_data)
    SPARK_DRIVER_MEM  Memoria del driver Spark (default: 2g)
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

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

ROOT = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parent)).resolve()
SOURCE_DATA = Path(os.environ.get("SOURCE_DATA_DIR", ROOT / "source_data")).resolve()

NOTEBOOKS = [
    "notebooks/01_eda_data_engineering.ipynb",
    "notebooks/02_regression_demand_forecasting.ipynb",
    "notebooks/03_kmeans_sku_segmentation.ipynb",
    "notebooks/04_reorder_policy.ipynb",
]

SUCCESS_MARKER = ROOT / "data" / "plan_reabastecimiento_csv" / "_SUCCESS"


def _run(cmd: list[str], step: str, env: dict[str, str] | None = None) -> bool:
    """Ejecuta un subcomando, retorna True si el paso fue exitoso."""
    log.info("[%s] Iniciando...", step)
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            log.error("[%s] Falló con código de retorno %d.", step, result.returncode)
            return False
        log.info("[%s] Completado (rc=%d).", step, result.returncode)
        return True
    except Exception as exc:
        log.error("[%s] Excepción inesperada: %s", step, exc)
        return False


def _source_excels() -> tuple[Path, Path] | None:
    """Valida y devuelve los libros fuente sin copiarlos al directorio del proyecto."""
    if not SOURCE_DATA.is_dir():
        log.error("No existe el directorio requerido de datos fuente: %s", SOURCE_DATA)
        return None
    old, new = SOURCE_DATA / "Analisis CR 44.xlsx", SOURCE_DATA / "Analisis CR 30.xlsx"
    missing = [path.name for path in (old, new) if not path.is_file()]
    if missing:
        log.error("Faltan libros Excel requeridos en %s: %s", SOURCE_DATA, ", ".join(missing))
        return None
    return old, new


def main() -> int:
    start = datetime.now()
    sep = "=" * 64
    log.info(sep)
    log.info("PIPELINE INICIADO: %s", start.isoformat())
    log.info(sep)

    log.info("--- Paso 1/7: Validar libros Excel en source_data/ ---")
    excel_paths = _source_excels()
    if excel_paths is None:
        log.error("No se puede iniciar sin los archivos Excel fuente.")
        return 1

    log.info("--- Paso 2/7: extract_data.py ---")
    extraction_env = os.environ.copy()
    extraction_env["XL_OLD_PATH"] = str(excel_paths[0])
    extraction_env["XL_NEW_PATH"] = str(excel_paths[1])
    if not _run(
        [sys.executable, "extract_data.py"], "extract_data", env=extraction_env
    ):
        log.error("extract_data.py falló. Abortando el pipeline.")
        return 1

    if SUCCESS_MARKER.exists():
        SUCCESS_MARKER.unlink()

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
            log.error("El notebook %s falló. Abortando para evitar salidas parciales.", nb)
            return 1

    log.info("--- Paso 7/7: generar_graficas.py ---")
    if not _run([sys.executable, "generar_graficas.py"], "generar_graficas"):
        return 1

    elapsed = (datetime.now() - start).total_seconds()
    log.info(sep)
    if not SUCCESS_MARKER.is_file():
        log.error("Falta el marcador de salida del plan; la corrida no se considera exitosa.")
        return 1
    log.info("PIPELINE COMPLETADO EXITOSAMENTE en %.1f s.", elapsed)
    log.info("Marcador de éxito de esta corrida: %s", SUCCESS_MARKER)
    log.info(sep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
