"""
Interfaz operativa del Plan de Compras — Starbucks Costa Rica
============================================================
Dashboard interactivo (Streamlit) que:
  1. Muestra el plan de reabastecimiento generado por el notebook 04
     (pronóstico de demanda ensamblado + modelo de inventario con punto de
     reorden y tránsito de 13 semanas).
  2. Permite registrar el CONSUMO de la semana por SKU para recalcular el
     pedido sin volver a correr Spark (ciclo de pedidos semanal).
  3. Permite CONFIRMAR la recepción de lo que llegó en la semana, moviendo
     unidades de tránsito a existencias.

Ejecutar con:
    python -m streamlit run app.py
"""
from __future__ import annotations

import glob
import math
import os
from datetime import date

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Configuración general
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.abspath(__file__))
PLAN_DIR = os.path.join(ROOT, "data", "plan_reabastecimiento_csv")
SEG_DIR = os.path.join(ROOT, "data", "segmentos_sku_csv")
MOV_DIR = os.path.join(ROOT, "data", "movimientos")
CONSUMO_CSV = os.path.join(MOV_DIR, "consumo_semanal.csv")
RECEPCION_CSV = os.path.join(MOV_DIR, "recepciones.csv")

# Parámetros de la política de inventario (deben coincidir con el notebook 04).
L = 13   # lead time / tránsito en semanas
R = 4    # periodo de revisión en semanas

VERDE = "#00704A"  # verde Starbucks

# --------------------------------------------------------------------------- #
# Iconos SVG vectoriales (estilo Lucide — 24×24 viewport, stroke-based)        #
# --------------------------------------------------------------------------- #
def _ico(paths: str, size: int = 20, color: str = "currentColor") -> str:
    """Devuelve un SVG inline con los paths indicados (estilo Lucide)."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'style="vertical-align:middle;flex-shrink:0;">{paths}</svg>'
    )


ICO_CHART    = _ico('<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>')
ICO_EDIT     = _ico('<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4Z"/>')
ICO_BOX      = _ico('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>')
ICO_DOWNLOAD = _ico('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>')
ICO_SAVE     = _ico('<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>')
ICO_TRASH    = _ico('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>')
ICO_CHECK    = _ico('<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>')
ICO_REFRESH  = _ico('<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>')
ICO_HISTORY  = _ico('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>')
ICO_UPLOAD   = _ico('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>')
ICO_ORDERS   = _ico('<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>')


def _hdr(icon: str, text: str, tag: str = "h3") -> None:
    """Renderiza un encabezado con icono SVG Lucide inline."""
    st.markdown(
        f'<{tag} style="display:flex;align-items:center;gap:10px;margin:0.6em 0 0.4em;">'
        f'{icon}&nbsp;{text}</{tag}>',
        unsafe_allow_html=True,
    )


st.set_page_config(
    page_title="Plan de Compras · Starbucks CR",
    page_icon=None,
    layout="wide",
)


# --------------------------------------------------------------------------- #
# Carga de datos (con caché)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _leer_csv_spark(carpeta: str) -> pd.DataFrame:
    """Lee el único part-file CSV que Spark escribe dentro de una carpeta."""
    archivos = glob.glob(os.path.join(carpeta, "part-*.csv"))
    if not archivos:
        return pd.DataFrame()
    return pd.read_csv(archivos[0])


@st.cache_data(show_spinner=False)
def cargar_plan() -> pd.DataFrame:
    df = _leer_csv_spark(PLAN_DIR)
    if df.empty:
        return df
    num = ["mu", "sigma", "z_aplicado", "EXIST_W11", "TRANSITO", "IP", "DDLT",
           "SS", "ROP", "nivel_objetivo_S", "cantidad_unid", "cantidad_cajas",
           "valor_pedido_usd", "cobertura_sem", "semanas_hasta_pedido",
           "FACTOR", "COSTO_UNITARIO"]
    for c in num:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["pedir_ahora"] = pd.to_numeric(df.get("pedir_ahora", 0), errors="coerce").fillna(0).astype(int)
    df["SKU"] = df["SKU"].astype(str)
    # Defensivos por si el plan se generó sin estas columnas.
    if "FACTOR" not in df.columns:
        df["FACTOR"] = 1.0
    if "COSTO_UNITARIO" not in df.columns:
        df["COSTO_UNITARIO"] = 0.0
    df["FACTOR"] = df["FACTOR"].fillna(1.0).replace(0, 1.0)
    df["COSTO_UNITARIO"] = df["COSTO_UNITARIO"].fillna(0.0)
    return df


def _cargar_movimientos(path: str, columnas: list[str]) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            d = pd.read_csv(path)
            d["SKU"] = d["SKU"].astype(str)
            return d
        except Exception:
            pass
    return pd.DataFrame(columns=columnas)


def _guardar_movimientos(path: str, df: pd.DataFrame) -> None:
    os.makedirs(MOV_DIR, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def recalcular_plan(plan: pd.DataFrame,
                    consumo: dict[str, float],
                    recepcion: dict[str, float]) -> pd.DataFrame:
    """Recalcula el plan de reabastecimiento en pandas a partir del consumo de
    la semana y las recepciones confirmadas, sin invocar Spark.

    - Recepciones: mueven unidades de tránsito a existencias.
    - Consumo: reduce existencias.
    - Se recalcula IP, ROP, nivel objetivo S, pedir_ahora y la cantidad en
      cajas completas (igual que el notebook 04).
    """
    d = plan.copy()
    cons = d["SKU"].map(lambda s: float(consumo.get(s, 0.0))).fillna(0.0)
    recep = d["SKU"].map(lambda s: float(recepcion.get(s, 0.0))).fillna(0.0)

    # No se puede recibir más de lo que está en tránsito.
    recep_efectiva = recep.clip(upper=d["TRANSITO"].clip(lower=0))
    exist_new = (d["EXIST_W11"] + recep_efectiva - cons).clip(lower=0)
    transito_new = (d["TRANSITO"] - recep_efectiva).clip(lower=0)
    ip_new = exist_new + transito_new

    factor = d["FACTOR"].replace(0, 1.0)
    ddlt = d["mu"] * L
    ss = d["z_aplicado"] * d["sigma"] * math.sqrt(L)
    rop = ddlt + ss
    nivel_s = d["mu"] * (L + R) + ss
    faltante = (nivel_s - ip_new).clip(lower=0)
    cajas = (faltante / factor).apply(math.ceil)
    unid = cajas * factor
    valor = (unid * d["COSTO_UNITARIO"]).round(2)

    r = d[["SKU", "DESCRIPCION", "PROVEEDOR", "segmento", "tipologia",
           "mu", "sigma", "z_aplicado"]].copy()
    r["consumo_semana"] = cons.round(0)
    r["recibido_semana"] = recep_efectiva.round(0)
    r["EXIST_actual"] = exist_new.round(0)
    r["TRANSITO_actual"] = transito_new.round(0)
    r["IP"] = ip_new.round(0)
    r["ROP"] = rop.round(0)
    r["nivel_objetivo_S"] = nivel_s.round(0)
    r["pedir_ahora"] = (ip_new <= rop).astype(int)
    r["cantidad_cajas"] = cajas.astype(int)
    r["cantidad_unid"] = unid.round(0)
    r["valor_pedido_usd"] = valor
    r["cobertura_sem"] = (ip_new / d["mu"].replace(0, pd.NA)).round(1)
    r["semanas_hasta_pedido"] = ((ip_new - rop) / d["mu"].replace(0, pd.NA)).clip(lower=0).round(1)
    return r


plan = cargar_plan()

# --------------------------------------------------------------------------- #
# Encabezado
# --------------------------------------------------------------------------- #
st.title("Plan de Compras — Starbucks Costa Rica")
st.caption(
    "Pronóstico de demanda (ensamble LR + RF + GBT) + modelo de inventario "
    "(punto de reorden) con tránsito de **13 semanas** y pedidos **semanales**."
)

if plan.empty:
    st.error(
        "No se encontró el plan de reabastecimiento. Ejecute primero el "
        "notebook `04_reorder_policy.ipynb` para generar "
        "`data/plan_reabastecimiento_csv/`."
    )
    st.stop()

tab_plan, tab_consumo, tab_recepcion = st.tabs(
    ["Plan de Compras", "Consumo Semanal", "Recepcion de Pedidos"]
)

# =========================================================================== #
# PESTAÑA 1 — PLAN DE COMPRAS (vista del modelo)
# =========================================================================== #
with tab_plan:
    st.sidebar.header("Filtros del plan")

    segmentos = sorted(plan["segmento"].dropna().unique()) if "segmento" in plan else []
    tipologias = sorted(plan["tipologia"].dropna().unique()) if "tipologia" in plan else []
    proveedores = sorted(plan["PROVEEDOR"].dropna().unique()) if "PROVEEDOR" in plan else []

    sel_seg = st.sidebar.multiselect("Segmento", segmentos, default=segmentos)
    sel_tip = st.sidebar.multiselect("Tipología de demanda", tipologias, default=tipologias)
    sel_prov = st.sidebar.multiselect("Proveedor", proveedores, default=[])
    solo_pedir = st.sidebar.checkbox("Mostrar solo SKUs a pedir ahora", value=True)
    busca = st.sidebar.text_input("Buscar por SKU o descripción").strip().lower()

    f = plan.copy()
    if sel_seg:
        f = f[f["segmento"].isin(sel_seg)]
    if sel_tip:
        f = f[f["tipologia"].isin(sel_tip)]
    if sel_prov:
        f = f[f["PROVEEDOR"].isin(sel_prov)]
    if solo_pedir:
        f = f[f["pedir_ahora"] == 1]
    if busca:
        f = f[
            f["SKU"].str.lower().str.contains(busca)
            | f["DESCRIPCION"].astype(str).str.lower().str.contains(busca)
        ]

    # KPIs ------------------------------------------------------------------- #
    total_skus = int(plan.shape[0])
    pedir_global = plan[plan["pedir_ahora"] == 1]
    n_pedir = int(pedir_global.shape[0])
    valor_global = float(pedir_global["valor_pedido_usd"].sum())
    valor_filtrado = float(f["valor_pedido_usd"].sum())
    unid_filtrado = float(f["cantidad_unid"].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SKUs en catálogo", f"{total_skus:,}")
    c2.metric("SKUs a pedir ahora", f"{n_pedir:,}", f"{100*n_pedir/total_skus:.0f}% del catálogo")
    c3.metric("Valor total a pedir", f"${valor_global:,.0f}")
    c4.metric("Valor de la selección", f"${valor_filtrado:,.0f}", f"{unid_filtrado:,.0f} unid.")

    st.divider()

    # Gráficas --------------------------------------------------------------- #
    g1, g2 = st.columns(2)
    with g1:
        _hdr(ICO_CHART, "Valor del pedido por segmento")
        if not pedir_global.empty:
            por_seg = pedir_global.groupby("segmento")["valor_pedido_usd"].sum().sort_values()
            st.bar_chart(por_seg, color=VERDE, horizontal=True)
        else:
            st.info("No hay pedidos pendientes.")
    with g2:
        _hdr(ICO_CHART, "SKUs a pedir por tipología de demanda")
        if not pedir_global.empty:
            por_tip = pedir_global.groupby("tipologia")["SKU"].count().sort_values()
            st.bar_chart(por_tip, color="#1f77b4", horizontal=True)
        else:
            st.info("No hay pedidos pendientes.")

    _hdr(ICO_CHART, "Top 15 SKUs por valor de pedido (selección actual)")
    top = f.sort_values("valor_pedido_usd", ascending=False).head(15)
    if not top.empty:
        st.bar_chart(top.set_index("DESCRIPCION")["valor_pedido_usd"], color=VERDE, horizontal=True)
    else:
        st.info("Sin resultados con los filtros actuales.")

    st.divider()

    # Tabla y descarga ------------------------------------------------------- #
    _hdr(ICO_ORDERS, f"Orden de compra sugerida ({f.shape[0]:,} SKUs)")
    cols_orden = [
        "SKU", "DESCRIPCION", "segmento", "tipologia", "PROVEEDOR",
        "mu", "IP", "ROP", "cantidad_unid", "cantidad_cajas",
        "valor_pedido_usd", "semanas_hasta_pedido", "z_aplicado",
    ]
    cols_orden = [c for c in cols_orden if c in f.columns]
    tabla = f[cols_orden].sort_values(
        ["semanas_hasta_pedido", "valor_pedido_usd"], ascending=[True, False]
    )
    st.dataframe(
        tabla,
        use_container_width=True,
        hide_index=True,
        column_config={
            "mu": st.column_config.NumberColumn("Demanda/sem", format="%.2f"),
            "IP": st.column_config.NumberColumn("Inventario (IP)", format="%.0f"),
            "ROP": st.column_config.NumberColumn("Punto reorden", format="%.0f"),
            "cantidad_unid": st.column_config.NumberColumn("Pedir (unid)", format="%.0f"),
            "cantidad_cajas": st.column_config.NumberColumn("Pedir (cajas)", format="%.0f"),
            "valor_pedido_usd": st.column_config.NumberColumn("Valor USD", format="$%.2f"),
            "semanas_hasta_pedido": st.column_config.NumberColumn("Sem. hasta ROP", format="%.1f"),
            "z_aplicado": st.column_config.NumberColumn("z", format="%.2f"),
        },
    )
    st.download_button(
        "Descargar orden de compra (CSV)",
        data=tabla.to_csv(index=False).encode("utf-8-sig"),
        file_name="orden_de_compra.csv",
        mime="text/csv",
    )
    st.caption(
        "Lógica: ROP = μ·L + z·σ·√L · | IP = existencias + tránsito · "
        "Pedir si IP ≤ ROP · Cantidad = máx(0, S − IP) con S = μ·(L+R) + SS, "
        "redondeada a cajas completas. Nivel de servicio z diferenciado por segmento."
    )

# =========================================================================== #
# PESTAÑA 2 — CONSUMO SEMANAL                                                 #
# =========================================================================== #
with tab_consumo:
    _hdr(ICO_EDIT, "Registrar el consumo de la semana")
    st.caption(
        "Ingrese las unidades consumidas (vendidas/usadas) por SKU durante la "
        "última semana. El sistema descuenta ese consumo de las existencias y "
        "recalcula el pedido de la semana siguiente."
    )

    iso = date.today().isocalendar()
    etiqueta_sem = st.text_input(
        "Etiqueta de la semana", value=f"{iso.year}-W{iso.week:02d}"
    )

    # ── Importar desde Excel / CSV ─────────────────────────────────────────── #
    with st.expander("Importar desde Excel o CSV"):
        st.markdown(
            f'{ICO_UPLOAD}&nbsp;<b>Formato requerido:</b> columnas '
            f'<code>SKU</code> y <code>consumo</code>. Las demás columnas se ignoran.',
            unsafe_allow_html=True,
        )
        tpl_cons = pd.DataFrame({"SKU": ["1234", "5678"], "consumo": [10, 25]})
        st.download_button(
            "Descargar plantilla CSV",
            data=tpl_cons.to_csv(index=False).encode("utf-8-sig"),
            file_name="plantilla_consumo.csv",
            mime="text/csv",
            key="tpl_consumo",
        )
        uploaded_cons = st.file_uploader(
            "Seleccionar archivo (xlsx / xls / csv)",
            type=["xlsx", "xls", "csv"],
            key="upload_consumo",
        )
        if uploaded_cons is not None:
            try:
                if uploaded_cons.name.lower().endswith(".csv"):
                    df_up_c = pd.read_csv(uploaded_cons)
                else:
                    df_up_c = pd.read_excel(uploaded_cons)
                df_up_c.columns = df_up_c.columns.str.strip().str.lower()
                if "sku" not in df_up_c.columns or "consumo" not in df_up_c.columns:
                    st.error(
                        "El archivo debe contener las columnas 'SKU' y 'consumo'. "
                        f"Columnas encontradas: {list(df_up_c.columns)}"
                    )
                else:
                    df_up_c["sku"] = df_up_c["sku"].astype(str).str.strip()
                    df_up_c["consumo"] = pd.to_numeric(df_up_c["consumo"], errors="coerce").fillna(0)
                    df_up_c = df_up_c[df_up_c["consumo"] > 0][["sku", "consumo"]].copy()
                    validos_c = set(plan["SKU"])
                    no_enc_c = df_up_c[~df_up_c["sku"].isin(validos_c)]
                    df_up_c = df_up_c[df_up_c["sku"].isin(validos_c)]
                    aviso_c = f"**{len(df_up_c)}** SKUs validos para importar"
                    if not no_enc_c.empty:
                        aviso_c += f" · {len(no_enc_c)} SKUs no encontrados en el plan (ignorados)."
                    st.markdown(aviso_c)
                    st.dataframe(
                        df_up_c.rename(columns={"sku": "SKU", "consumo": "Consumo"}),
                        use_container_width=True,
                        hide_index=True,
                    )
                    if st.button("Aplicar importacion", key="aplicar_consumo_xls", type="primary"):
                        nuevos_xls = df_up_c.rename(columns={"sku": "SKU"}).copy()
                        nuevos_xls["semana"] = etiqueta_sem
                        nuevos_xls["fecha"] = date.today().isoformat()
                        nuevos_xls = nuevos_xls[["SKU", "semana", "consumo", "fecha"]]
                        hist_xls = _cargar_movimientos(CONSUMO_CSV, ["SKU", "semana", "consumo", "fecha"])
                        hist_xls = hist_xls[hist_xls["semana"] != etiqueta_sem]
                        hist_xls = pd.concat([hist_xls, nuevos_xls], ignore_index=True)
                        _guardar_movimientos(CONSUMO_CSV, hist_xls)
                        st.success(f"Importados {len(nuevos_xls)} SKUs para {etiqueta_sem}.")
            except Exception as exc_c:
                st.error(f"Error al leer el archivo: {exc_c}")

    st.divider()

    # ── Ingreso manual ─────────────────────────────────────────────────────── #
    base_cons = plan[["SKU", "DESCRIPCION", "segmento", "EXIST_W11", "TRANSITO", "mu"]].copy()
    base_cons = base_cons.rename(columns={"EXIST_W11": "existencias", "mu": "demanda_prom"})
    base_cons["consumo"] = 0.0

    filtro_c = st.text_input("Filtrar SKU o descripcion", key="busca_consumo").strip().lower()
    vista = base_cons
    if filtro_c:
        vista = base_cons[
            base_cons["SKU"].str.lower().str.contains(filtro_c)
            | base_cons["DESCRIPCION"].astype(str).str.lower().str.contains(filtro_c)
        ]

    edit_cons = st.data_editor(
        vista,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["SKU", "DESCRIPCION", "segmento", "existencias", "TRANSITO", "demanda_prom"],
        column_config={
            "existencias": st.column_config.NumberColumn("Existencias", format="%.0f"),
            "TRANSITO": st.column_config.NumberColumn("En transito", format="%.0f"),
            "demanda_prom": st.column_config.NumberColumn("Demanda/sem", format="%.2f"),
            "consumo": st.column_config.NumberColumn(
                "Consumo semana", min_value=0.0, step=1.0, format="%.0f",
                help="Unidades consumidas esta semana",
            ),
        },
        key="editor_consumo",
    )

    cga, cgb = st.columns([1, 1])
    with cga:
        guardar_c = st.button("Guardar consumo y recalcular pedido", type="primary")
    with cgb:
        limpiar_c = st.button("Borrar consumos guardados de esta semana")

    if limpiar_c and os.path.exists(CONSUMO_CSV):
        hist = _cargar_movimientos(CONSUMO_CSV, ["SKU", "semana", "consumo", "fecha"])
        hist = hist[hist["semana"] != etiqueta_sem]
        _guardar_movimientos(CONSUMO_CSV, hist)
        st.success(f"Consumos de la semana {etiqueta_sem} eliminados.")

    if guardar_c:
        nuevos = edit_cons[edit_cons["consumo"] > 0][["SKU", "consumo"]].copy()
        nuevos["semana"] = etiqueta_sem
        nuevos["fecha"] = date.today().isoformat()
        nuevos = nuevos[["SKU", "semana", "consumo", "fecha"]]
        hist = _cargar_movimientos(CONSUMO_CSV, ["SKU", "semana", "consumo", "fecha"])
        hist = hist[hist["semana"] != etiqueta_sem]  # reemplaza la semana
        hist = pd.concat([hist, nuevos], ignore_index=True)
        _guardar_movimientos(CONSUMO_CSV, hist)
        st.success(f"Se guardó el consumo de {len(nuevos)} SKUs para {etiqueta_sem}.")

    # Construye el consumo de la semana actual (lo guardado).
    consumo_dict: dict[str, float] = {}
    hist_c = _cargar_movimientos(CONSUMO_CSV, ["SKU", "semana", "consumo", "fecha"])
    if not hist_c.empty:
        sem_actual = hist_c[hist_c["semana"] == etiqueta_sem]
        consumo_dict = dict(zip(sem_actual["SKU"].astype(str),
                                pd.to_numeric(sem_actual["consumo"], errors="coerce").fillna(0)))

    # Recepciones confirmadas (para que el IP refleje lo recibido).
    recep_dict: dict[str, float] = {}
    hist_r = _cargar_movimientos(RECEPCION_CSV, ["SKU", "semana", "recibido", "fecha"])
    if not hist_r.empty:
        agg_r = hist_r.groupby("SKU")["recibido"].apply(
            lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()
        )
        recep_dict = dict(zip(agg_r.index.astype(str), agg_r.values))

    st.divider()
    _hdr(ICO_REFRESH, "Pedido recalculado")
    if consumo_dict or recep_dict:
        nuevo = recalcular_plan(plan, consumo_dict, recep_dict)
        nuevo_pedir = nuevo[nuevo["pedir_ahora"] == 1]
        k1, k2, k3 = st.columns(3)
        k1.metric("SKUs a pedir ahora", f"{nuevo_pedir.shape[0]:,}")
        k2.metric("Valor total a pedir", f"${nuevo_pedir['valor_pedido_usd'].sum():,.0f}")
        k3.metric("Unidades a pedir", f"{nuevo_pedir['cantidad_unid'].sum():,.0f}")

        cols_n = ["SKU", "DESCRIPCION", "segmento", "consumo_semana", "recibido_semana",
                  "EXIST_actual", "TRANSITO_actual", "IP", "ROP", "cantidad_unid",
                  "cantidad_cajas", "valor_pedido_usd", "semanas_hasta_pedido"]
        mostrar = nuevo_pedir[cols_n].sort_values(
            ["semanas_hasta_pedido", "valor_pedido_usd"], ascending=[True, False]
        )
        st.dataframe(
            mostrar,
            use_container_width=True,
            hide_index=True,
            column_config={
                "consumo_semana": st.column_config.NumberColumn("Consumo", format="%.0f"),
                "recibido_semana": st.column_config.NumberColumn("Recibido", format="%.0f"),
                "EXIST_actual": st.column_config.NumberColumn("Existencias", format="%.0f"),
                "TRANSITO_actual": st.column_config.NumberColumn("Transito", format="%.0f"),
                "IP": st.column_config.NumberColumn("Inventario (IP)", format="%.0f"),
                "ROP": st.column_config.NumberColumn("Punto reorden", format="%.0f"),
                "cantidad_unid": st.column_config.NumberColumn("Pedir (unid)", format="%.0f"),
                "cantidad_cajas": st.column_config.NumberColumn("Pedir (cajas)", format="%.0f"),
                "valor_pedido_usd": st.column_config.NumberColumn("Valor USD", format="$%.2f"),
                "semanas_hasta_pedido": st.column_config.NumberColumn("Sem. hasta ROP", format="%.1f"),
            },
        )
        st.download_button(
            "Descargar pedido recalculado (CSV)",
            data=mostrar.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"pedido_{etiqueta_sem}.csv",
            mime="text/csv",
        )
    else:
        st.info(
            "Aún no hay consumo ni recepciones registradas. Ingrese el consumo "
            "arriba y presione **Guardar consumo y recalcular pedido**."
        )

# =========================================================================== #
# PESTAÑA 3 — RECEPCION DE PEDIDOS                                            #
# =========================================================================== #
with tab_recepcion:
    _hdr(ICO_BOX, "Confirmar lo que llegó esta semana")
    st.caption(
        "Registre las unidades recibidas por SKU. Lo recibido se descuenta del "
        "tránsito y se suma a las existencias, actualizando el inventario que "
        "alimenta el recálculo del pedido."
    )

    iso_r = date.today().isocalendar()
    etiqueta_rec = st.text_input(
        "Etiqueta de la semana de recepción",
        value=f"{iso_r.year}-W{iso_r.week:02d}",
        key="etiqueta_recepcion",
    )

    # ── Importar desde Excel / CSV ─────────────────────────────────────────── #
    with st.expander("Importar desde Excel o CSV"):
        st.markdown(
            f'{ICO_UPLOAD}&nbsp;<b>Formato requerido:</b> columnas '
            f'<code>SKU</code> y <code>recibido</code>. Las demás columnas se ignoran.',
            unsafe_allow_html=True,
        )
        tpl_rec = pd.DataFrame({"SKU": ["1234", "5678"], "recibido": [48, 120]})
        st.download_button(
            "Descargar plantilla CSV",
            data=tpl_rec.to_csv(index=False).encode("utf-8-sig"),
            file_name="plantilla_recepcion.csv",
            mime="text/csv",
            key="tpl_recepcion",
        )
        uploaded_rec = st.file_uploader(
            "Seleccionar archivo (xlsx / xls / csv)",
            type=["xlsx", "xls", "csv"],
            key="upload_recepcion",
        )
        if uploaded_rec is not None:
            try:
                if uploaded_rec.name.lower().endswith(".csv"):
                    df_up_r = pd.read_csv(uploaded_rec)
                else:
                    df_up_r = pd.read_excel(uploaded_rec)
                df_up_r.columns = df_up_r.columns.str.strip().str.lower()
                if "sku" not in df_up_r.columns or "recibido" not in df_up_r.columns:
                    st.error(
                        "El archivo debe contener las columnas 'SKU' y 'recibido'. "
                        f"Columnas encontradas: {list(df_up_r.columns)}"
                    )
                else:
                    df_up_r["sku"] = df_up_r["sku"].astype(str).str.strip()
                    df_up_r["recibido"] = pd.to_numeric(df_up_r["recibido"], errors="coerce").fillna(0)
                    df_up_r = df_up_r[df_up_r["recibido"] > 0][["sku", "recibido"]].copy()
                    validos_r = set(plan["SKU"])
                    no_enc_r = df_up_r[~df_up_r["sku"].isin(validos_r)]
                    df_up_r = df_up_r[df_up_r["sku"].isin(validos_r)]
                    aviso_r = f"**{len(df_up_r)}** SKUs validos para importar"
                    if not no_enc_r.empty:
                        aviso_r += f" · {len(no_enc_r)} SKUs no encontrados en el plan (ignorados)."
                    st.markdown(aviso_r)
                    st.dataframe(
                        df_up_r.rename(columns={"sku": "SKU", "recibido": "Recibido"}),
                        use_container_width=True,
                        hide_index=True,
                    )
                    if st.button("Aplicar importacion", key="aplicar_recepcion_xls", type="primary"):
                        nuevos_xls_r = df_up_r.rename(columns={"sku": "SKU"}).copy()
                        nuevos_xls_r["semana"] = etiqueta_rec
                        nuevos_xls_r["fecha"] = date.today().isoformat()
                        nuevos_xls_r = nuevos_xls_r[["SKU", "semana", "recibido", "fecha"]]
                        hist_xls_r = _cargar_movimientos(RECEPCION_CSV, ["SKU", "semana", "recibido", "fecha"])
                        hist_xls_r = pd.concat([hist_xls_r, nuevos_xls_r], ignore_index=True)
                        _guardar_movimientos(RECEPCION_CSV, hist_xls_r)
                        st.success(f"Importadas recepciones de {len(nuevos_xls_r)} SKUs para {etiqueta_rec}.")
            except Exception as exc_r:
                st.error(f"Error al leer el archivo: {exc_r}")

    st.divider()

    # ── Ingreso manual ─────────────────────────────────────────────────────── #
    base_rec = plan[["SKU", "DESCRIPCION", "PROVEEDOR", "EXIST_W11", "TRANSITO"]].copy()
    base_rec = base_rec.rename(columns={"EXIST_W11": "existencias", "TRANSITO": "en_transito"})
    base_rec["recibido"] = 0.0

    # Mostrar por defecto solo SKUs con tránsito (lo que puede llegar).
    solo_transito = st.checkbox("Mostrar solo SKUs con transito pendiente", value=True)
    vista_r = base_rec[base_rec["en_transito"] > 0] if solo_transito else base_rec

    filtro_r = st.text_input("Filtrar SKU o descripcion", key="busca_recepcion").strip().lower()
    if filtro_r:
        vista_r = vista_r[
            vista_r["SKU"].str.lower().str.contains(filtro_r)
            | vista_r["DESCRIPCION"].astype(str).str.lower().str.contains(filtro_r)
        ]

    edit_rec = st.data_editor(
        vista_r,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["SKU", "DESCRIPCION", "PROVEEDOR", "existencias", "en_transito"],
        column_config={
            "existencias": st.column_config.NumberColumn("Existencias", format="%.0f"),
            "en_transito": st.column_config.NumberColumn("En transito", format="%.0f"),
            "recibido": st.column_config.NumberColumn(
                "Recibido", min_value=0.0, step=1.0, format="%.0f",
                help="Unidades que llegaron esta semana",
            ),
        },
        key="editor_recepcion",
    )

    cra, crb = st.columns([1, 1])
    with cra:
        confirmar_r = st.button("Confirmar recepcion", type="primary")
    with crb:
        recibir_todo = st.button("Recibir todo el transito mostrado")

    hist_r = _cargar_movimientos(RECEPCION_CSV, ["SKU", "semana", "recibido", "fecha"])

    if recibir_todo:
        completos = vista_r[vista_r["en_transito"] > 0][["SKU", "en_transito"]].copy()
        completos = completos.rename(columns={"en_transito": "recibido"})
        completos["semana"] = etiqueta_rec
        completos["fecha"] = date.today().isoformat()
        completos = completos[["SKU", "semana", "recibido", "fecha"]]
        hist_r = pd.concat([hist_r, completos], ignore_index=True)
        _guardar_movimientos(RECEPCION_CSV, hist_r)
        st.success(f"Se confirmó la recepción completa de {len(completos)} SKUs.")

    if confirmar_r:
        nuevos_r = edit_rec[edit_rec["recibido"] > 0][["SKU", "recibido"]].copy()
        nuevos_r["semana"] = etiqueta_rec
        nuevos_r["fecha"] = date.today().isoformat()
        nuevos_r = nuevos_r[["SKU", "semana", "recibido", "fecha"]]
        hist_r = pd.concat([hist_r, nuevos_r], ignore_index=True)
        _guardar_movimientos(RECEPCION_CSV, hist_r)
        st.success(f"Se confirmó la recepción de {len(nuevos_r)} SKUs para {etiqueta_rec}.")

    st.divider()
    _hdr(ICO_HISTORY, "Historial de recepciones")
    hist_r = _cargar_movimientos(RECEPCION_CSV, ["SKU", "semana", "recibido", "fecha"])
    if hist_r.empty:
        st.info("Aún no se han confirmado recepciones.")
    else:
        resumen = hist_r.merge(
            plan[["SKU", "DESCRIPCION"]], on="SKU", how="left"
        ).sort_values("fecha", ascending=False)
        total_recibido = pd.to_numeric(hist_r["recibido"], errors="coerce").fillna(0).sum()
        st.metric("Unidades recibidas acumuladas", f"{total_recibido:,.0f}")
        st.dataframe(
            resumen[["fecha", "semana", "SKU", "DESCRIPCION", "recibido"]],
            use_container_width=True,
            hide_index=True,
        )
        cda, cdb = st.columns([1, 1])
        with cda:
            st.download_button(
                "Descargar historial (CSV)",
                data=hist_r.to_csv(index=False).encode("utf-8-sig"),
                file_name="recepciones.csv",
                mime="text/csv",
            )
        with cdb:
            if st.button("Borrar todo el historial de recepciones"):
                if os.path.exists(RECEPCION_CSV):
                    os.remove(RECEPCION_CSV)
                st.warning("Historial de recepciones eliminado.")
