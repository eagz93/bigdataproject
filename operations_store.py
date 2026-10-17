from __future__ import annotations

import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Iterator, Mapping

import pandas as pd

WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
MOVEMENT_KINDS = {"consumo", "recepcion"}
BREAKER_LIMIT = 0.15


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    return db


@contextmanager
def _connection(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    db = connect(db_path)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(db_path: str | Path, plan: pd.DataFrame) -> None:
    with _connection(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                sku TEXT PRIMARY KEY,
                existencias REAL NOT NULL CHECK (existencias >= 0),
                en_transito REAL NOT NULL CHECK (en_transito >= 0),
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS movements (
                sku TEXT NOT NULL,
                week TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('consumo', 'recepcion')),
                quantity REAL NOT NULL CHECK (quantity >= 0),
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (sku, week, kind)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY,
                happened_at TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                action TEXT NOT NULL,
                sku TEXT NOT NULL,
                week TEXT NOT NULL,
                suggested_cases REAL,
                actual_cases REAL,
                reason TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS approvals (
                sku TEXT NOT NULL,
                week TEXT NOT NULL,
                suggested_cases INTEGER NOT NULL,
                approved_cases INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                approved_by TEXT NOT NULL,
                approved_at TEXT NOT NULL,
                PRIMARY KEY (sku, week)
            );
            CREATE TABLE IF NOT EXISTS pilot_metrics (
                week TEXT PRIMARY KEY,
                pilot_events INTEGER NOT NULL,
                pilot_exposure INTEGER NOT NULL,
                control_events INTEGER NOT NULL,
                control_exposure INTEGER NOT NULL,
                pilot_rate REAL NOT NULL,
                control_rate REAL NOT NULL,
                above_limit INTEGER NOT NULL,
                entered_by TEXT NOT NULL,
                entered_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings (key, value) VALUES ('recommendations_paused', 'false');
            """
        )
        now = _now()
        for row in plan[["SKU", "EXIST_W11", "TRANSITO"]].itertuples(index=False):
            sku = str(row.SKU).strip()
            if not sku:
                continue
            db.execute(
                """
                INSERT OR IGNORE INTO inventory (sku, existencias, en_transito, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (sku, _number(row.EXIST_W11), _number(row.TRANSITO), now),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _number(value: object) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Los valores deben ser números finitos.")
    return result


def _validate_week(week: str) -> None:
    if not WEEK_RE.fullmatch(week):
        raise ValueError("La semana debe usar el formato AAAA-W##.")
    year, number = week.split("-W")
    date.fromisocalendar(int(year), int(number), 1)


def get_inventory(db_path: str | Path) -> dict[str, tuple[float, float]]:
    with _connection(db_path) as db:
        rows = db.execute("SELECT sku, existencias, en_transito FROM inventory").fetchall()
    return {row["sku"]: (row["existencias"], row["en_transito"]) for row in rows}


def movement_history(
    db_path: str | Path, kind: str, limit: int = 500
) -> pd.DataFrame:
    if kind not in MOVEMENT_KINDS:
        raise ValueError(f"Tipo de movimiento no permitido: {kind}")
    with _connection(db_path) as db:
        return pd.read_sql_query(
            "SELECT sku, week, quantity, updated_by, updated_at FROM movements "
            "WHERE kind = ? ORDER BY week DESC, sku LIMIT ?",
            db,
            params=(kind, limit),
        )


def pilot_history(db_path: str | Path, limit: int = 104) -> pd.DataFrame:
    with _connection(db_path) as db:
        return pd.read_sql_query(
            "SELECT * FROM pilot_metrics ORDER BY week DESC LIMIT ?",
            db,
            params=(limit,),
        )


def apply_movements(
    db_path: str | Path,
    week: str,
    kind: str,
    values: Mapping[str, float],
    username: str,
    role: str,
) -> None:
    _validate_week(week)
    if kind not in MOVEMENT_KINDS:
        raise ValueError(f"Tipo de movimiento no permitido: {kind}")
    now = _now()
    with _connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        _apply_movements_in_transaction(db, week, kind, values, username, role, now)


def replace_movements_batch(
    db_path: str | Path,
    kind: str,
    batches: Iterable[tuple[str, Mapping[str, float]]],
    username: str,
    role: str,
) -> None:
    """Replace complete weekly movement snapshots in one transaction."""
    if kind not in MOVEMENT_KINDS:
        raise ValueError(f"Tipo de movimiento no permitido: {kind}")
    prepared = list(batches)
    if not prepared:
        raise ValueError("El archivo no contiene movimientos para importar.")
    for week, values in prepared:
        _validate_week(week)
        if not values:
            raise ValueError(f"No hay movimientos para reemplazar en {week}.")
    prepared.sort(key=lambda batch: date.fromisocalendar(
        int(batch[0][:4]), int(batch[0][-2:]), 1
    ))
    now = _now()
    with _connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        for week, values in prepared:
            existing = db.execute(
                "SELECT sku FROM movements WHERE week = ? AND kind = ?", (week, kind)
            ).fetchall()
            replacement = dict(values)
            for row in existing:
                replacement.setdefault(row["sku"], 0.0)
            _apply_movements_in_transaction(
                db, week, kind, replacement, username, role, now
            )


def _apply_movements_in_transaction(
    db: sqlite3.Connection,
    week: str,
    kind: str,
    values: Mapping[str, float],
    username: str,
    role: str,
    now: str,
) -> None:
    for raw_sku, raw_quantity in values.items():
        sku = str(raw_sku).strip()
        quantity = _number(raw_quantity)
        if not sku or quantity < 0:
            raise ValueError("SKU y cantidad deben ser válidos y la cantidad no negativa.")
        current = db.execute(
            "SELECT existencias, en_transito FROM inventory WHERE sku = ?", (sku,)
        ).fetchone()
        if current is None:
            raise ValueError(f"El SKU {sku} no existe en el inventario.")
        prior = db.execute(
            "SELECT quantity FROM movements WHERE sku = ? AND week = ? AND kind = ?",
            (sku, week, kind),
        ).fetchone()
        old_quantity = prior["quantity"] if prior else 0.0
        delta = quantity - old_quantity
        if kind == "consumo":
            existencias = current["existencias"] - delta
            en_transito = current["en_transito"]
        else:
            existencias = current["existencias"] + delta
            en_transito = current["en_transito"] - delta
        if existencias < -1e-9 or en_transito < -1e-9:
            raise ValueError(
                f"El movimiento de {sku} supera las existencias o el tránsito disponible."
            )
        db.execute(
            """
            INSERT INTO movements (sku, week, kind, quantity, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku, week, kind) DO UPDATE SET
                quantity = excluded.quantity,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (sku, week, kind, quantity, username, now),
        )
        db.execute(
            """
            UPDATE inventory SET existencias = ?, en_transito = ?, updated_at = ?
            WHERE sku = ?
            """,
            (max(0.0, existencias), max(0.0, en_transito), now, sku),
        )
        if delta:
            db.execute(
                """
                INSERT INTO audit_log
                    (happened_at, username, role, action, sku, week, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (now, username, role, kind, sku, week, f"Delta corregido: {delta:g}"),
            )


def approve_orders(
    db_path: str | Path,
    week: str,
    orders: Iterable[Mapping[str, object]],
    username: str,
    role: str,
) -> None:
    _validate_week(week)
    if role not in {"planner", "admin"}:
        raise PermissionError("Solo Compras o administración pueden aprobar órdenes.")
    now = _now()
    with _connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        paused = db.execute(
            "SELECT value FROM settings WHERE key = 'recommendations_paused'"
        ).fetchone()["value"] == "true"
        if paused:
            raise RuntimeError("El circuito de contingencia está activo; las aprobaciones están pausadas.")
        for order in orders:
            sku = str(order["sku"]).strip()
            suggested = int(order["suggested_cases"])
            actual = int(order["approved_cases"])
            reason = str(order.get("reason", "")).strip()
            if not sku or suggested < 0 or actual < 0:
                raise ValueError("SKU y cantidades deben ser enteros no negativos.")
            change = abs(actual - suggested) / suggested if suggested else (0.0 if actual == 0 else math.inf)
            if change > 0.10 and not reason:
                raise ValueError(f"SKU {sku}: justifique cambios mayores al 10%.")
            db.execute(
                """
                INSERT INTO approvals
                    (sku, week, suggested_cases, approved_cases, reason, approved_by, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sku, week) DO UPDATE SET
                    suggested_cases = excluded.suggested_cases,
                    approved_cases = excluded.approved_cases,
                    reason = excluded.reason,
                    approved_by = excluded.approved_by,
                    approved_at = excluded.approved_at
                """,
                (sku, week, suggested, actual, reason, username, now),
            )
            db.execute(
                """
                INSERT INTO audit_log
                    (happened_at, username, role, action, sku, week,
                     suggested_cases, actual_cases, reason)
                VALUES (?, ?, ?, 'aprobacion', ?, ?, ?, ?, ?)
                """,
                (now, username, role, sku, week, suggested, actual, reason),
            )


def get_approvals(db_path: str | Path, week: str) -> dict[str, dict[str, object]]:
    _validate_week(week)
    with _connection(db_path) as db:
        rows = db.execute("SELECT * FROM approvals WHERE week = ?", (week,)).fetchall()
    return {row["sku"]: dict(row) for row in rows}


def record_pilot_metrics(
    db_path: str | Path,
    week: str,
    pilot_events: int,
    pilot_exposure: int,
    control_events: int,
    control_exposure: int,
    username: str,
) -> bool:
    _validate_week(week)
    counts = (pilot_events, pilot_exposure, control_events, control_exposure)
    if any(not isinstance(value, int) or value < 0 for value in counts):
        raise ValueError("Los eventos y exposiciones deben ser enteros no negativos.")
    if pilot_exposure == 0 or control_exposure == 0:
        raise ValueError("Cada grupo debe tener al menos una observación de exposición.")
    if pilot_events > pilot_exposure or control_events > control_exposure:
        raise ValueError("Los eventos de quiebre no pueden superar las observaciones.")
    pilot_rate = pilot_events / pilot_exposure
    control_rate = control_events / control_exposure
    threshold = 1 + Fraction(str(BREAKER_LIMIT))
    above = int(
        threshold.denominator * pilot_events * control_exposure
        > threshold.numerator * control_events * pilot_exposure
    )
    with _connection(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """
            INSERT INTO pilot_metrics
                (week, pilot_events, pilot_exposure, control_events, control_exposure,
                 pilot_rate, control_rate, above_limit, entered_by, entered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week) DO UPDATE SET
                pilot_events = excluded.pilot_events,
                pilot_exposure = excluded.pilot_exposure,
                control_events = excluded.control_events,
                control_exposure = excluded.control_exposure,
                pilot_rate = excluded.pilot_rate,
                control_rate = excluded.control_rate,
                above_limit = excluded.above_limit,
                entered_by = excluded.entered_by,
                entered_at = excluded.entered_at
            """,
            (week, *counts, pilot_rate, control_rate, above, username, _now()),
        )
        year, number = map(int, week.split("-W"))
        previous_week = date.fromisocalendar(year, number, 1).toordinal() - 7
        previous = date.fromordinal(previous_week).isocalendar()
        prior_key = f"{previous.year}-W{previous.week:02d}"
        prior = db.execute(
            "SELECT above_limit FROM pilot_metrics WHERE week = ?", (prior_key,)
        ).fetchone()
        triggered = bool(above and prior and prior["above_limit"])
        if triggered:
            db.execute(
                "UPDATE settings SET value = 'true' WHERE key = 'recommendations_paused'"
            )
        return triggered


def breaker_paused(db_path: str | Path) -> bool:
    with _connection(db_path) as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key = 'recommendations_paused'"
        ).fetchone()
    return bool(row and row["value"] == "true")


def resume_recommendations(db_path: str | Path, username: str, role: str) -> None:
    if role != "admin":
        raise PermissionError("Solo administración puede reanudar las recomendaciones.")
    with _connection(db_path) as db:
        db.execute(
            "UPDATE settings SET value = 'false' WHERE key = 'recommendations_paused'"
        )
        db.execute(
            """
            INSERT INTO audit_log
                (happened_at, username, role, action, sku, week, reason)
            VALUES (?, ?, ?, 'reanudar_circuito', '*', ?, 'Reanudación autorizada')
            """,
            (_now(), username, role, date.today().strftime("%G-W%V")),
        )


def audit_history(db_path: str | Path, limit: int = 500) -> pd.DataFrame:
    with _connection(db_path) as db:
        return pd.read_sql_query(
            "SELECT * FROM audit_log ORDER BY happened_at DESC LIMIT ?",
            db,
            params=(limit,),
        )
