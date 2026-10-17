from __future__ import annotations

import glob
import math
import os
import tomllib
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from auth_utils import verify_password
from movement_import import prepare_movement_batches, read_movement_file
from operations_store import (
    apply_movements,
    approve_orders,
    audit_history,
    breaker_paused,
    get_approvals,
    get_inventory,
    initialize,
    movement_history,
    pilot_history,
    record_pilot_metrics,
    replace_movements_batch,
    resume_recommendations,
)

ROOT = Path(__file__).resolve().parent
LOCAL_USERS_FILE = ROOT / ".streamlit" / "users.local.toml"
PLAN_DIR = ROOT / "data" / "plan_reabastecimiento_csv"
MOV_DIR = Path(os.environ.get("MOVEMENTS_DIR", ROOT / "data" / "movimientos"))
DB_PATH = MOV_DIR / "operations.sqlite3"
L = 13
R = 4
ROLE_LABELS = {
    "admin": "Administración",
    "planner": "Compras",
    "warehouse": "CEDI",
    "viewer": "Consulta",
}


def _read_plan() -> pd.DataFrame:
    files = sorted(glob.glob(str(PLAN_DIR / "part-*.csv")))
    if not files:
        return pd.DataFrame()
    frames = [pd.read_csv(path, dtype={"SKU": str}) for path in files]
    df = pd.concat(frames, ignore_index=True)
    numeric = [
        "mu", "sigma", "z_aplicado", "EXIST_W11", "TRANSITO", "IP", "DDLT",
        "SS", "ROP", "nivel_objetivo_S", "cantidad_unid", "cantidad_cajas",
        "valor_pedido_usd", "cobertura_sem", "semanas_hasta_pedido",
        "FACTOR", "COSTO_UNITARIO",
    ]
    for column in numeric:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df["SKU"] = df["SKU"].astype(str).str.strip()
    df["FACTOR"] = df.get("FACTOR", 1.0)
    df["COSTO_UNITARIO"] = df.get("COSTO_UNITARIO", 0.0)
    df["FACTOR"] = pd.to_numeric(df["FACTOR"], errors="coerce").fillna(1.0).replace(0, 1.0)
    df["COSTO_UNITARIO"] = pd.to_numeric(
        df["COSTO_UNITARIO"], errors="coerce"
    ).fillna(0.0)
    return df


def _configured_users() -> dict[str, dict[str, str]]:
    users = st.secrets.get("users", {})
    if users:
        return users
    if LOCAL_USERS_FILE.is_file():
        return tomllib.loads(LOCAL_USERS_FILE.read_text(encoding="utf-8")).get(
            "users", {}
        )
    return {}


def _authenticate() -> dict[str, str] | None:
    users = _configured_users()
    if not users:
        st.error(
            "La aplicación está bloqueada: configure usuarios y hashes PBKDF2 "
            "en .streamlit/secrets.toml según README.md."
        )
        st.stop()
    if "authenticated_user" in st.session_state:
        return {
            "username": st.session_state["authenticated_user"],
            "role": st.session_state["authenticated_role"],
        }
    st.title("Acceso al plan de compras")
    with st.form("login"):
        username = st.text_input("Usuario").strip()
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Ingresar", type="primary")
    if submitted:
        record = users.get(username)
        if (
            record
            and record.get("role") in ROLE_LABELS
            and verify_password(password, record.get("password_hash", ""))
        ):
            st.session_state["authenticated_user"] = username
            st.session_state["authenticated_role"] = record["role"]
            st.rerun()
        st.error("Usuario o contraseña incorrectos.")
    return None


def _week_label(today: date | None = None) -> str:
    iso = (today or date.today()).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _attach_inventory(plan: pd.DataFrame, inventory: dict[str, tuple[float, float]]) -> pd.DataFrame:
    result = plan.copy()
    current = result["SKU"].map(inventory)
    result["EXIST_W11"] = current.map(lambda pair: pair[0] if pair else 0.0)
    result["TRANSITO"] = current.map(lambda pair: pair[1] if pair else 0.0)
    return result


def recalcular_plan(plan: pd.DataFrame) -> pd.DataFrame:
    """Recalcula ROP y cantidad sugerida con el saldo persistido en SQLite."""
    d = plan.copy()
    factor = pd.to_numeric(d["FACTOR"], errors="coerce").fillna(1.0).replace(0, 1.0)
    mu = pd.to_numeric(d["mu"], errors="coerce").fillna(0.0).clip(lower=0)
    sigma = pd.to_numeric(d["sigma"], errors="coerce").fillna(0.0).clip(lower=0)
    z = pd.to_numeric(d["z_aplicado"], errors="coerce").fillna(0.0).clip(lower=0)
    stock = pd.to_numeric(d["EXIST_W11"], errors="coerce").fillna(0.0).clip(lower=0)
    transit = pd.to_numeric(d["TRANSITO"], errors="coerce").fillna(0.0).clip(lower=0)
    ip = stock + transit
    safety = z * sigma * math.sqrt(L)
    rop = mu * L + safety
    target = mu * (L + R) + safety
    boxes = ((target - ip).clip(lower=0) / factor).apply(math.ceil)
    result = d.copy()
    result["IP"] = ip
    result["ROP"] = rop
    result["nivel_objetivo_S"] = target
    result["pedir_ahora"] = (ip <= rop).astype(int)
    result["cantidad_cajas"] = boxes.astype(int)
    result["cantidad_unid"] = boxes * factor
    result["valor_pedido_usd"] = (
        result["cantidad_unid"] * pd.to_numeric(d["COSTO_UNITARIO"], errors="coerce").fillna(0)
    ).round(2)
    result["cobertura_sem"] = (ip / mu.replace(0, pd.NA)).round(1)
    result["semanas_hasta_pedido"] = ((ip - rop) / mu.replace(0, pd.NA)).clip(lower=0).round(1)
    return result


def _require_role(role: str, permitted: set[str]) -> bool:
    return role == "admin" or role in permitted


def _render_movement_import(
    kind: str,
    week: str,
    plan: pd.DataFrame,
    username: str,
    role: str,
) -> None:
    quantity_column = "consumo" if kind == "consumo" else "recibido"
    label = "consumos" if kind == "consumo" else "recepciones"
    with st.expander(f"Importar {label} desde CSV o Excel"):
        if not _require_role(role, {"warehouse"}):
            st.info("La importación de movimientos requiere rol CEDI o Administración.")
            return
        template = pd.DataFrame(
            {"SKU": [plan["SKU"].iloc[0]], "semana": [week], quantity_column: [0]}
        )
        st.download_button(
            f"Descargar plantilla de {label}",
            template.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"plantilla_{label}.csv",
            mime="text/csv",
            key=f"template_{kind}",
        )
        st.caption(
            "El archivo requiere SKU y "
            f"{quantity_column}; la columna semana es opcional. "
            "La carga reemplaza los movimientos del mismo tipo para cada semana incluida."
        )
        uploaded = st.file_uploader(
            "Seleccionar archivo CSV o Excel",
            type=["csv", "xlsx", "xls"],
            key=f"upload_{kind}",
        )
        if uploaded is not None and st.button(
            f"Validar e importar {label}", key=f"import_{kind}"
        ):
            try:
                frame = read_movement_file(uploaded, uploaded.name)
                batches = prepare_movement_batches(
                    frame, kind, set(plan["SKU"].astype(str)), week
                )
                replace_movements_batch(DB_PATH, kind, batches, username, role)
            except (
                ValueError,
                OSError,
                UnicodeDecodeError,
                zipfile.BadZipFile,
                pd.errors.ParserError,
            ) as exc:
                st.error(f"No se importaron los movimientos: {exc}")
            else:
                rows = sum(len(values) for _, values in batches)
                st.success(
                    f"Se importaron {rows} movimientos en {len(batches)} semana(s)."
                )
                st.rerun()


def main() -> None:
    st.set_page_config(page_title="Plan de Compras · Starbucks CR", layout="wide")
    user = _authenticate()
    if user is None:
        return
    username, role = user["username"], user["role"]
    with st.sidebar:
        st.caption(f"Sesión: **{username}** · {ROLE_LABELS[role]}")
        if st.button("Cerrar sesión"):
            st.session_state.pop("authenticated_user", None)
            st.session_state.pop("authenticated_role", None)
            st.rerun()

    plan = _read_plan()
    st.title("Plan de Compras — Starbucks Costa Rica")
    st.caption(
        "Recomendación semanal para revisión humana. El modelo no emite órdenes "
        "automáticas ni demuestra por sí mismo reducción de quiebres."
    )
    if plan.empty:
        st.error(f"No se encontró un archivo part-*.csv en {PLAN_DIR}.")
        st.stop()

    initialize(DB_PATH, plan)
    plan = _attach_inventory(plan, get_inventory(DB_PATH))
    plan = recalcular_plan(plan)
    week = _week_label()
    saved_approvals = get_approvals(DB_PATH, week)
    plan["cantidad_cajas_sugeridas"] = plan["cantidad_cajas"]
    plan["cantidad_cajas_aprobadas"] = plan.apply(
        lambda row: saved_approvals.get(str(row["SKU"]), {}).get(
            "approved_cases", int(row["cantidad_cajas_sugeridas"])
        ),
        axis=1,
    )

    tab_plan, tab_consumption, tab_receipts, tab_pilot, tab_audit = st.tabs(
        ["Plan y aprobación", "Consumo", "Recepciones", "Control piloto", "Auditoría"]
    )

    with tab_plan:
        st.subheader(f"Recomendación de compra · {week}")
        col1, col2, col3 = st.columns(3)
        to_order = plan[plan["pedir_ahora"] == 1]
        col1.metric("SKUs en catálogo", f"{len(plan):,}")
        col2.metric("SKUs bajo ROP", f"{len(to_order):,}")
        col3.metric("Valor sugerido", f"${to_order['valor_pedido_usd'].sum():,.2f}")
        paused = breaker_paused(DB_PATH)
        if paused:
            st.error("Circuit breaker activo: aprobaciones pausadas hasta revisión administrativa.")

        f1, f2, f3 = st.columns(3)
        segments = sorted(plan["segmento"].dropna().unique()) if "segmento" in plan else []
        providers = sorted(plan["PROVEEDOR"].dropna().unique()) if "PROVEEDOR" in plan else []
        selected_segments = f1.multiselect("Nivel de rotación", segments, default=segments)
        selected_providers = f2.multiselect("Proveedor", providers)
        search = f3.text_input("Buscar SKU o descripción").strip().lower()
        filtered = to_order[to_order["segmento"].isin(selected_segments)] if "segmento" in plan else to_order
        if selected_providers:
            filtered = filtered[filtered["PROVEEDOR"].isin(selected_providers)]
        if search:
            filtered = filtered[
                filtered["SKU"].str.lower().str.contains(search)
                | filtered["DESCRIPCION"].astype(str).str.lower().str.contains(search)
            ]

        visible = filtered[
            [
                "SKU", "DESCRIPCION", "segmento", "PROVEEDOR", "mu", "IP", "ROP",
                "cantidad_cajas_sugeridas", "cantidad_cajas_aprobadas", "FACTOR",
                "COSTO_UNITARIO",
            ]
        ].copy()
        visible["justificacion"] = visible["SKU"].map(
            lambda sku: saved_approvals.get(str(sku), {}).get("reason", "")
        )
        can_approve = _require_role(role, {"planner"})
        if can_approve:
            edited = st.data_editor(
                visible,
                width="stretch",
                hide_index=True,
                disabled=[
                    "SKU", "DESCRIPCION", "segmento", "PROVEEDOR", "mu", "IP", "ROP",
                    "cantidad_cajas_sugeridas", "FACTOR", "COSTO_UNITARIO",
                ],
                column_config={
                    "cantidad_cajas_aprobadas": st.column_config.NumberColumn(
                        "Cajas aprobadas", min_value=0, step=1, format="%d"
                    ),
                    "justificacion": st.column_config.TextColumn(
                        "Justificación (obligatoria si varía >10%)"
                    ),
                },
                key="order_editor",
            )
            if st.button("Aprobar selección", type="primary", disabled=paused):
                orders = []
                for row in edited.to_dict(orient="records"):
                    raw_cases = float(row["cantidad_cajas_aprobadas"])
                    if not math.isfinite(raw_cases) or raw_cases < 0 or not raw_cases.is_integer():
                        raise ValueError(f"SKU {row['SKU']}: las cajas deben ser enteros no negativos.")
                    orders.append(
                        {
                            "sku": row["SKU"],
                            "suggested_cases": int(row["cantidad_cajas_sugeridas"]),
                            "approved_cases": int(raw_cases),
                            "reason": row["justificacion"],
                        }
                    )
                try:
                    approve_orders(DB_PATH, week, orders, username, role)
                except (ValueError, RuntimeError, PermissionError) as exc:
                    st.error(f"No se aprobaron las órdenes: {exc}")
                else:
                    st.success(f"Se registraron {len(orders)} aprobaciones auditables.")
                    st.rerun()
        else:
            st.dataframe(visible, width="stretch", hide_index=True)

        approved = get_approvals(DB_PATH, week)
        export = filtered.copy()
        export["cantidad_cajas_aprobadas"] = export.apply(
            lambda row: approved.get(str(row["SKU"]), {}).get(
                "approved_cases", int(row["cantidad_cajas_sugeridas"])
            ),
            axis=1,
        )
        export["valor_aprobado_usd"] = (
            export["cantidad_cajas_aprobadas"] * export["FACTOR"] * export["COSTO_UNITARIO"]
        ).round(2)
        st.download_button(
            "Descargar sugerencias/aprobaciones CSV",
            export.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"orden_{week}.csv",
            mime="text/csv",
        )
        st.caption(
            "Cambios de hasta ±10% no requieren nota; cualquier desviación mayor, "
            "incluido pedir sobre una sugerencia cero, exige justificación. "
            "La aprobación queda asociada al usuario y a la semana."
        )

    with tab_consumption:
        st.subheader("Registrar consumo de inventario")
        if _require_role(role, {"warehouse"}):
            view = plan[["SKU", "DESCRIPCION", "EXIST_W11"]].copy()
            view["consumo"] = 0
            edited = st.data_editor(
                view,
                width="stretch",
                hide_index=True,
                disabled=["SKU", "DESCRIPCION", "EXIST_W11"],
                column_config={"consumo": st.column_config.NumberColumn("Consumo", min_value=0, step=1)},
                key="consumption_editor",
            )
            entry_week = st.text_input("Semana del consumo (AAAA-W##)", value=week, key="consumption_week")
            if st.button("Guardar consumo", type="primary"):
                values = {}
                for row in edited.to_dict(orient="records"):
                    amount = float(row["consumo"])
                    if not math.isfinite(amount) or amount < 0:
                        raise ValueError(f"Consumo no válido para SKU {row['SKU']}.")
                    values[row["SKU"]] = amount
                try:
                    apply_movements(DB_PATH, entry_week, "consumo", values, username, role)
                except ValueError as exc:
                    st.error(f"No se guardó el consumo: {exc}")
                else:
                    st.success("Consumo guardado. El saldo persistido se actualizó de forma idempotente.")
                    st.rerun()
        else:
            st.info("El registro de consumo requiere rol CEDI o Administración.")
        _render_movement_import("consumo", week, plan, username, role)
        st.subheader("Consumos guardados")
        st.caption("Últimos 500 registros por semana y SKU; cantidades semanales, no movimientos adicionales.")
        st.dataframe(movement_history(DB_PATH, "consumo"), width="stretch", hide_index=True)

    with tab_receipts:
        st.subheader("Confirmar recepciones")
        if _require_role(role, {"warehouse"}):
            view = plan[["SKU", "DESCRIPCION", "TRANSITO"]].copy()
            view["recibido"] = 0
            view = view[view["TRANSITO"] > 0]
            edited = st.data_editor(
                view,
                width="stretch",
                hide_index=True,
                disabled=["SKU", "DESCRIPCION", "TRANSITO"],
                column_config={"recibido": st.column_config.NumberColumn("Recibido", min_value=0, step=1)},
                key="receipt_editor",
            )
            entry_week = st.text_input("Semana de recepción (AAAA-W##)", value=week, key="receipt_week")
            if st.button("Confirmar recepción", type="primary"):
                values = {}
                for row in edited.to_dict(orient="records"):
                    amount = float(row["recibido"])
                    if not math.isfinite(amount) or amount < 0:
                        raise ValueError(f"Recepción no válida para SKU {row['SKU']}.")
                    values[row["SKU"]] = amount
                try:
                    apply_movements(DB_PATH, entry_week, "recepcion", values, username, role)
                except ValueError as exc:
                    st.error(f"No se guardó la recepción: {exc}")
                else:
                    st.success("Recepción guardada; unidades movidas de tránsito a existencias.")
                    st.rerun()
        else:
            st.info("La recepción requiere rol CEDI o Administración.")
        _render_movement_import("recepcion", week, plan, username, role)
        st.subheader("Recepciones guardadas")
        st.caption("Últimos 500 registros por semana y SKU; recibir descuenta el tránsito existente.")
        st.dataframe(movement_history(DB_PATH, "recepcion"), width="stretch", hide_index=True)

    with tab_pilot:
        st.subheader("Métricas semanales del piloto")
        st.caption(
            "Compare tasas de quiebre por exposición observada. El circuito se "
            "activa cuando la tasa piloto supera a control en más de 15% por "
            "dos semanas ISO consecutivas."
        )
        if _require_role(role, {"warehouse"}):
            with st.form("pilot_metrics"):
                metric_week = st.text_input("Semana (AAAA-W##)", value=week)
                c1, c2 = st.columns(2)
                pilot_exposure = c1.number_input("Exposición piloto", min_value=1, step=1)
                pilot_events = c1.number_input("Quiebres piloto", min_value=0, step=1)
                control_exposure = c2.number_input("Exposición control", min_value=1, step=1)
                control_events = c2.number_input("Quiebres control", min_value=0, step=1)
                submit_metrics = st.form_submit_button("Guardar métricas", type="primary")
            if submit_metrics:
                try:
                    triggered = record_pilot_metrics(
                        DB_PATH, metric_week, int(pilot_events), int(pilot_exposure),
                        int(control_events), int(control_exposure), username,
                    )
                except ValueError as exc:
                    st.error(f"No se guardaron las métricas: {exc}")
                else:
                    if triggered:
                        st.error("Circuit breaker activado. Las aprobaciones quedan pausadas.")
                    else:
                        st.success("Métricas guardadas.")
                    st.rerun()
        if breaker_paused(DB_PATH):
            st.error("Recomendaciones en pausa.")
            if role == "admin" and st.button("Reanudar tras revisión"):
                resume_recommendations(DB_PATH, username, role)
                st.success("Recomendaciones reanudadas y acción auditada.")
                st.rerun()
        else:
            st.success("Recomendaciones habilitadas.")
        st.subheader("Métricas guardadas")
        st.caption("Últimas 104 semanas ISO registradas. Las tasas se expresan como fracciones entre 0 y 1.")
        st.dataframe(pilot_history(DB_PATH), width="stretch", hide_index=True)

    with tab_audit:
        if role in {"planner", "admin"}:
            history = audit_history(DB_PATH)
            st.dataframe(history, width="stretch", hide_index=True)
            st.download_button(
                "Descargar auditoría CSV",
                history.to_csv(index=False).encode("utf-8-sig"),
                file_name="auditoria_operativa.csv",
                mime="text/csv",
            )
        else:
            st.info("La auditoría requiere rol Compras o Administración.")


if __name__ == "__main__":
    main()
