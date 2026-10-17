from __future__ import annotations

from datetime import date
from math import isfinite
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from operations_store import MOVEMENT_KINDS


def read_movement_file(file: BinaryIO, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file, dtype=str, encoding="utf-8-sig")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(file)
    raise ValueError("Formato no permitido. Use un archivo CSV o Excel.")


def prepare_movement_batches(
    frame: pd.DataFrame,
    kind: str,
    valid_skus: set[str],
    default_week: str,
) -> list[tuple[str, dict[str, float]]]:
    if kind not in MOVEMENT_KINDS:
        raise ValueError(f"Tipo de movimiento no permitido: {kind}")
    _validate_week(default_week)
    if frame.empty:
        raise ValueError("El archivo no contiene filas para importar.")

    normalized_columns = [
        str(column).strip().casefold().lstrip("\ufeff") for column in frame.columns
    ]
    if len(set(normalized_columns)) != len(normalized_columns):
        raise ValueError("El archivo contiene encabezados duplicados.")
    data = frame.copy()
    data.columns = normalized_columns
    quantity_column = "consumo" if kind == "consumo" else "recibido"
    required = {"sku", quantity_column}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(
            "Faltan columnas requeridas: " + ", ".join(sorted(missing))
        )

    data["sku"] = data["sku"].fillna("").astype(str).str.strip()
    if "semana" in data.columns:
        data["semana"] = data["semana"].fillna("").astype(str).str.strip()
        data["semana"] = data["semana"].replace("", default_week)
    else:
        data["semana"] = default_week
    if data["sku"].eq("").any():
        raise ValueError("Todas las filas deben incluir un SKU.")
    invalid_skus = sorted(set(data["sku"]) - valid_skus)
    if invalid_skus:
        sample = ", ".join(invalid_skus[:10])
        raise ValueError(
            f"El archivo contiene {len(invalid_skus)} SKU fuera del plan: {sample}."
        )

    for week in data["semana"].unique():
        _validate_week(str(week))
    quantities = pd.to_numeric(data[quantity_column], errors="coerce")
    if quantities.isna().any() or not quantities.map(
        lambda value: isfinite(float(value)) and value >= 0
    ).all():
        raise ValueError("Las cantidades deben ser números finitos no negativos.")
    data[quantity_column] = quantities

    grouped = (
        data.groupby(["semana", "sku"], as_index=False, sort=True)[quantity_column]
        .sum()
    )
    batches: list[tuple[str, dict[str, float]]] = []
    for week, weekly in grouped.groupby("semana", sort=True):
        batches.append(
            (
                str(week),
                {
                    str(row["sku"]): float(row[quantity_column])
                    for row in weekly.to_dict(orient="records")
                },
            )
        )
    return batches


def _validate_week(week: str) -> None:
    if len(week) != 8 or week[4:6] != "-W" or not week[:4].isdigit() or not week[6:].isdigit():
        raise ValueError(f"Semana no válida: {week}. Use AAAA-W##.")
    try:
        date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
    except ValueError as exc:
        raise ValueError(f"Semana no válida: {week}. Use AAAA-W##.") from exc
