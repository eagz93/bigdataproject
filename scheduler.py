#!/usr/bin/env python3
"""
scheduler.py — Programador automático del pipeline ETL
=======================================================
Comportamiento al iniciar el contenedor:
  - Modo 'auto' (default): ejecuta el pipeline solo si el plan de compras
    no existe todavía (primera vez o datos borrados). Ideal para reinicios.
  - Modo 'true' : fuerza una ejecución al arrancar siempre.
  - Modo 'false': no ejecuta al arrancar; solo por el schedule programado.

Después del arranque, el pipeline se reprograma automáticamente:
  Todos los MARTES a las 21:00 (cron equivalente: 0 21 * * 2)

Variables de entorno:
  PIPELINE_RUN_ON_STARTUP  auto | true | false  (default: auto)
  TZ                       Zona horaria del contenedor (default: UTC)
                           Ejemplo: TZ=America/Costa_Rica

Ejecución manual del pipeline:
  docker exec starbucks-spark-etl python train_model.py
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(os.environ.get("LOG_DIR", "/app/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "scheduler.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Archivo marcador: si existe, el plan ya fue generado al menos una vez.
_SUCCESS_MARKER = Path("/app/data/plan_reabastecimiento_csv/_SUCCESS")


# ---------------------------------------------------------------------------
# Ejecución del pipeline
# ---------------------------------------------------------------------------
def run_pipeline() -> None:
    """Lanza train_model.py como subproceso independiente."""
    ts = datetime.now().isoformat()
    log.info("=" * 60)
    log.info("PIPELINE DISPARADO: %s", ts)
    log.info("=" * 60)
    try:
        result = subprocess.run(
            [sys.executable, "/app/train_model.py"],
            cwd="/app",
            text=True,
        )
        if result.returncode == 0:
            log.info("Pipeline finalizado exitosamente.")
        else:
            log.warning("Pipeline finalizado con código %d.", result.returncode)
    except Exception as exc:
        log.error("Error al ejecutar el pipeline: %s", exc)


# ---------------------------------------------------------------------------
# Decisión de ejecución en startup
# ---------------------------------------------------------------------------
def _should_run_on_startup() -> bool:
    """
    auto  → ejecutar solo si no existe el marcador _SUCCESS
    true  → ejecutar siempre al arrancar
    false → no ejecutar al arrancar
    """
    mode = os.environ.get("PIPELINE_RUN_ON_STARTUP", "auto").strip().lower()
    if mode in ("1", "true", "yes"):
        log.info("PIPELINE_RUN_ON_STARTUP=true → ejecución forzada al iniciar.")
        return True
    if mode in ("0", "false", "no"):
        log.info("PIPELINE_RUN_ON_STARTUP=false → sin ejecución al iniciar.")
        return False
    # Modo 'auto': ejecutar solo si el plan no existe todavía.
    exists = _SUCCESS_MARKER.exists()
    log.info(
        "PIPELINE_RUN_ON_STARTUP=auto → datos %s → %s.",
        "ENCONTRADOS" if exists else "NO ENCONTRADOS",
        "saltando ejecución inicial" if exists else "ejecutando pipeline inicial",
    )
    return not exists


# ---------------------------------------------------------------------------
# Scheduler principal
# ---------------------------------------------------------------------------
def main() -> None:
    tz = os.environ.get("TZ", "UTC")
    log.info("Scheduler iniciado.")
    log.info("Zona horaria del contenedor: %s", tz)
    log.info("Pipeline programado para: MARTES 21:00 (cron: 0 21 * * 2)")

    # ── Ejecución inicial (según modo configurado) ────────────────────────── #
    if _should_run_on_startup():
        run_pipeline()

    # ── Programación semanal: martes 21:00 ───────────────────────────────── #
    schedule.every().tuesday.at("21:00").do(run_pipeline)
    log.info("Próxima ejecución programada: %s", schedule.next_run())

    # ── Bucle principal: comprueba tareas pendientes cada 60 segundos ─────── #
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
