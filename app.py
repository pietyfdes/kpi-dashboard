"""KPI Dashboard - interactive business analytics built with Streamlit, pandas and Plotly."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

SAMPLE_PATH = Path(__file__).parent / "sample_data.csv"
NOT_MAPPED = "— not mapped —"

# field -> (required?, aliases used for auto-detection)
FIELDS: dict[str, tuple[bool, list[str]]] = {
    "Date": (True, ["date", "orderdate", "day", "datetime", "transactiondate"]),
    "Region": (True, ["region", "area", "territory", "market"]),
    "Product": (True, ["product", "productname", "item", "sku"]),
    "Category": (True, ["category", "productcategory", "productline", "type"]),
    "Units Sold": (True, ["unitssold", "units", "quantity", "qty"]),
    "Revenue": (True, ["revenue", "sales", "amount", "totalsales", "turnover"]),
    "Cost": (True, ["cost", "cogs", "costofgoods", "totalcost"]),
    "Salesperson": (False, ["salesperson", "rep", "salesrep", "seller", "employee"]),
    "Customer Segment": (False, ["customersegment", "segment", "customertype"]),
}
REQUIRED = [f for f, (req, _) in FIELDS.items() if req]
NUMERIC = ["Units Sold", "Revenue", "Cost"]
GREEN, RED = "#21c55d", "#ff4b4b"
PLOT_COLORS = ["#ff4b4b", "#4c9be8", "#f5b942", "#21c55d", "#a77bf3", "#2bc4c4"]


# ----------------------------------------------------------------------------
# Data loading & preparation
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_data(file_bytes: bytes | None, filename: str | None) -> pd.DataFrame:
    """Read an uploaded CSV/Excel file (or the bundled sample when nothing is uploaded)."""
    if file_bytes is None:
        return pd.read_csv(SAMPLE_PATH)
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(io.BytesIO(file_bytes))
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(io.BytesIO(file_bytes))
    raise ValueError(f"Unsupported file format '{suffix or 'unknown'}'. Upload a .csv, .xlsx or .xls file.")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def auto_detect_mapping(columns: list[str]) -> dict[str, str | None]:
    """Guess which uploaded column matches each dashboard field."""
    by_norm = {_norm(c): c for c in columns}
    mapping: dict[str, str | None] = {}
    for field, (_, aliases) in FIELDS.items():
        found = by_norm.get(_norm(field))
        if found is None:
            found = next((by_norm[a] for a in aliases if a in by_norm), None)
        mapping[field] = found
    return mapping


def mapping_problems(mapping: dict[str, str | None]) -> tuple[list[str], list[str]]:
    """Return (missing required fields, columns mapped to more than one field)."""
    missing = [f for f in REQUIRED if not mapping.get(f)]
    used = [c for c in mapping.values() if c]
    duplicated = sorted({c for c in used if used.count(c) > 1})
    return missing, duplicated


def prepare_data(raw: pd.DataFrame, mapping: dict[str, str | None]) -> tuple[pd.DataFrame, int]:
    """Rename mapped columns, coerce types and drop unusable rows. Returns (clean df, rows dropped)."""
    renames = {src: field for field, src in mapping.items() if src}
    df = raw[list(renames)].rename(columns=renames).copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in df.columns.difference(["Date", *NUMERIC]):
        df[col] = df[col].astype("string").str.strip()
    before = len(df)
    df = df.dropna(subset=["Date", *NUMERIC, "Region", "Product", "Category"]).reset_index(drop=True)
    df["Profit"] = df["Revenue"] - df["Cost"]
    return df, before - len(df)


def apply_filters(df: pd.DataFrame, date_range, regions, categories, products) -> pd.DataFrame:
    start, end = (pd.Timestamp(d) for d in date_range)
    mask = (
        df["Date"].between(start, end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
        & df["Region"].isin(regions)
        & df["Category"].isin(categories)
        & df["Product"].isin(products)
    )
    return df[mask]


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    m = df.groupby(df["Date"].dt.to_period("M")).agg(
        Revenue=("Revenue", "sum"), Profit=("Profit", "sum"), Units=("Units Sold", "sum"), Orders=("Revenue", "size")
    )
    m["Margin"] = m["Profit"] / m["Revenue"] * 100
    m["AOV"] = m["Revenue"] / m["Orders"]
    m["MoM"] = m["Revenue"].pct_change() * 100
    return m


def _pct_change(new: float, old: float) -> float | None:
    return None if old in (0, None) or pd.isna(old) else (new - old) / abs(old) * 100


def compute_kpis(df: pd.DataFrame) -> list[dict]:
    """Return KPI card definitions. Deltas compare the latest month with the month before it."""
    revenue, profit, units = df["Revenue"].sum(), df["Profit"].sum(), df["Units Sold"].sum()
    margin = profit / revenue * 100 if revenue else 0.0
    aov = revenue / len(df) if len(df) else 0.0

    m = monthly_summary(df)
    last, prev = (m.iloc[-1], m.iloc[-2]) if len(m) >= 2 else (None, None)
    d_rev = _pct_change(last["Revenue"], prev["Revenue"]) if last is not None else None
    d_profit = _pct_change(last["Profit"], prev["Profit"]) if last is not None else None
    d_units = _pct_change(last["Units"], prev["Units"]) if last is not None else None
    d_aov = _pct_change(last["AOV"], prev["AOV"]) if last is not None else None
    d_margin = last["Margin"] - prev["Margin"] if last is not None else None
    mom = last["MoM"] if last is not None else None
    d_mom = mom - prev["MoM"] if last is not None and len(m) >= 3 and pd.notna(prev["MoM"]) else None

    return [
        {"label": "Total Revenue", "value": f"${revenue:,.0f}", "delta": d_rev, "unit": "%"},
        {"label": "Total Profit", "value": f"${profit:,.0f}", "delta": d_profit, "unit": "%"},
        {"label": "Profit Margin", "value": f"{margin:.1f}%", "delta": d_margin, "unit": " pp"},
        {"label": "Units Sold", "value": f"{units:,.0f}", "delta": d_units, "unit": "%"},
        {"label": "Avg Order Value", "value": f"${aov:,.2f}", "delta": d_aov, "unit": "%"},
        {"label": "MoM Growth", "value": "n/a" if mom is None or pd.isna(mom) else f"{mom:+.1f}%", "delta": d_mom, "unit": " pp"},
    ]


# ----------------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------------
def _style(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=10, r=10, t=50, b=10),
        colorway=PLOT_COLORS,
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


def build_charts(df: pd.DataFrame, granularity: str = "Monthly") -> dict[str, go.Figure]:
    """Build all dashboard figures from the filtered data."""
    freq = "W-MON" if granularity == "Weekly" else "MS"
    trend = (
        df.set_index("Date")[["Revenue", "Profit"]].resample(freq, label="left", closed="left").sum().reset_index()
    )
    fig_trend = px.line(trend, x="Date", y=["Revenue", "Profit"], markers=True, title=f"Revenue & Profit ({granularity.lower()})")
    fig_trend.update_layout(yaxis_title="Amount ($)", xaxis_title=None, legend_title=None)

    region = df.groupby("Region", as_index=False)["Revenue"].sum().sort_values("Revenue", ascending=False)
    fig_region = px.bar(region, x="Region", y="Revenue", title="Revenue by Region", text_auto=".3s")
    fig_region.update_traces(marker_color=RED)

    cat = df.groupby("Category", as_index=False)["Revenue"].sum()
    fig_cat = px.pie(cat, names="Category", values="Revenue", hole=0.55, title="Revenue Share by Category")
    fig_cat.update_traces(textinfo="percent+label")

    top = df.groupby("Product", as_index=False)["Revenue"].sum().nlargest(10, "Revenue").sort_values("Revenue")
    fig_top = px.bar(top, x="Revenue", y="Product", orientation="h", title="Top 10 Products by Revenue", text_auto=".3s")
    fig_top.update_traces(marker_color=RED)

    pivot = df.pivot_table(index="Region", columns="Category", values="Revenue", aggfunc="sum", fill_value=0)
    fig_heat = px.imshow(pivot, text_auto=".3s", aspect="auto", color_continuous_scale="Reds", title="Revenue: Region × Category")

    m = monthly_summary(df).reset_index()
    m["Month"] = m["Date"].dt.to_timestamp()
    mom = m.dropna(subset=["MoM"])
    fig_mom = px.bar(
        mom, x="Month", y="MoM", title="Month-over-Month Revenue Growth (%)",
        color=(mom["MoM"] >= 0).map({True: "Growth", False: "Decline"}),
        color_discrete_map={"Growth": GREEN, "Decline": RED},
    )
    fig_mom.update_layout(legend_title=None, yaxis_title="%", xaxis_title=None)

    return {
        "trend": _style(fig_trend),
        "region": _style(fig_region),
        "category": _style(fig_cat),
        "top_products": _style(fig_top, 420),
        "heatmap": _style(fig_heat, 420),
        "mom": _style(fig_mom),
    }


# ----------------------------------------------------------------------------
# Insights
# ----------------------------------------------------------------------------
def generate_insights(df: pd.DataFrame, margin_threshold: float = 30.0) -> list[tuple[str, str]]:
    """Rule-based observations. Returns (level, message) with level in {'info', 'success', 'warning'}."""
    out: list[tuple[str, str]] = []

    def grouped(col: str) -> pd.DataFrame:
        g = df.groupby(col).agg(Revenue=("Revenue", "sum"), Profit=("Profit", "sum"))
        g["Margin"] = g["Profit"] / g["Revenue"] * 100
        return g

    total_rev = df["Revenue"].sum()
    reg = grouped("Region")
    if len(reg):
        best = reg["Revenue"].idxmax()
        out.append(("success", f"**{best}** is the best region with ${reg.loc[best, 'Revenue']:,.0f} revenue "
                              f"({reg.loc[best, 'Revenue'] / total_rev:.0%} of total)."))
        if len(reg) > 1:
            worst = reg["Revenue"].idxmin()
            out.append(("info", f"**{worst}** is the weakest region at ${reg.loc[worst, 'Revenue']:,.0f} revenue."))

    prod = grouped("Product")
    if len(prod):
        hi, lo = prod["Margin"].idxmax(), prod["Margin"].idxmin()
        out.append(("success", f"**{hi}** has the highest margin at {prod.loc[hi, 'Margin']:.1f}%."))
        if len(prod) > 1:
            out.append(("info", f"**{lo}** has the lowest margin at {prod.loc[lo, 'Margin']:.1f}%."))
        out.append(("info", f"**{prod['Revenue'].idxmax()}** is the top product by revenue "
                            f"(${prod['Revenue'].max():,.0f})."))

    for col in ("Salesperson", "Customer Segment"):
        if col in df.columns and df[col].notna().any():
            g = grouped(col)
            out.append(("info", f"Top {col.lower()} by revenue: **{g['Revenue'].idxmax()}** (${g['Revenue'].max():,.0f})."))

    m = monthly_summary(df)
    if len(m) >= 2:
        worst_m = m["MoM"].idxmin()
        if m.loc[worst_m, "MoM"] < 0:
            out.append(("warning", f"The biggest monthly drop was in **{worst_m.strftime('%B %Y')}**: revenue fell "
                                   f"{abs(m.loc[worst_m, 'MoM']):.1f}% versus the previous month."))
        else:
            out.append(("success", "Revenue did not decline in any month of the selected period."))
        best_m = m["Revenue"].idxmax()
        out.append(("info", f"**{best_m.strftime('%B %Y')}** was the strongest month (${m.loc[best_m, 'Revenue']:,.0f})."))
    else:
        out.append(("info", "Select a range covering at least two months to see month-over-month insights."))

    overall = df["Profit"].sum() / total_rev * 100 if total_rev else 0.0
    if overall < margin_threshold:
        out.append(("warning", f"Overall margin is {overall:.1f}%, below the {margin_threshold:.0f}% threshold."))
    for col in ("Region", "Category", "Product"):
        low = grouped(col)
        low = low[low["Margin"] < margin_threshold].sort_values("Margin")
        if len(low):
            names = ", ".join(f"{i} ({v:.1f}%)" for i, v in low["Margin"].head(5).items())
            out.append(("warning", f"{col}s below the {margin_threshold:.0f}% margin threshold: {names}."))
    return out


def data_quality(raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Per-column missing values and dtypes, plus the duplicate row count."""
    report = pd.DataFrame({
        "Type": raw.dtypes.astype(str),
        "Missing": raw.isna().sum(),
        "Missing %": (raw.isna().mean() * 100).round(2),
        "Unique": raw.nunique(),
    })
    return report, int(raw.duplicated().sum())


# ----------------------------------------------------------------------------
# UI helpers
# ----------------------------------------------------------------------------
CSS = f"""
<style>
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{background-color:#0e1117;color:#fafafa;}}
[data-testid="stSidebar"], [data-testid="stSidebar"] > div {{background-color:#1a1d27;}}
.stApp p, .stApp label, .stApp span, .stApp h1, .stApp h2, .stApp h3, .stApp li {{color:#fafafa;}}
.kpi-card {{background:#1a1d27;border:1px solid #2c3040;border-radius:12px;padding:14px 16px;}}
.kpi-label {{color:#9aa0b4;font-size:0.8rem;text-transform:uppercase;letter-spacing:.04em;}}
.kpi-value {{font-size:1.6rem;font-weight:700;margin:2px 0;}}
.kpi-delta {{font-size:0.85rem;font-weight:600;}}
.kpi-up {{color:{GREEN};}} .kpi-down {{color:{RED};}} .kpi-flat {{color:#9aa0b4;}}
h2, h3 {{border-left:4px solid {RED};padding-left:10px;}}
</style>
"""


def render_kpi_cards(kpis: list[dict]) -> None:
    for col, k in zip(st.columns(len(kpis)), kpis):
        d = k["delta"]
        if d is None or pd.isna(d):
            delta_html = '<span class="kpi-flat">– no prior month</span>'
        else:
            cls, arrow = ("kpi-up", "▲") if d >= 0 else ("kpi-down", "▼")
            delta_html = f'<span class="{cls}">{arrow} {d:+.1f}{k["unit"]}</span> <span class="kpi-flat">vs prev month</span>'
        col.markdown(
            f'<div class="kpi-card"><div class="kpi-label">{k["label"]}</div>'
            f'<div class="kpi-value">{k["value"]}</div><div class="kpi-delta">{delta_html}</div></div>',
            unsafe_allow_html=True,
        )


def sidebar_upload_and_mapping() -> tuple[pd.DataFrame, dict[str, str | None], str]:
    """Handle upload + column mapping. Stops the script with a clear message on any problem."""
    uploaded = st.sidebar.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"])
    if uploaded is None:
        raw = load_data(None, None)
        return raw, {f: (f if f in raw.columns else None) for f in FIELDS}, "sample_data.csv (built-in)"

    try:
        raw = load_data(uploaded.getvalue(), uploaded.name)
    except Exception as exc:  # wrong format, corrupt file, empty file...
        st.error(f"Could not read **{uploaded.name}**: {exc}")
        st.stop()
    if raw.empty:
        st.error(f"**{uploaded.name}** contains no rows.")
        st.stop()

    cols = [str(c) for c in raw.columns]
    raw.columns = cols
    guess = auto_detect_mapping(cols)
    mapping: dict[str, str | None] = {}
    with st.sidebar.expander("🔗 Column mapping", expanded=any(guess[f] is None for f in REQUIRED)):
        st.caption("Match your columns to the fields the dashboard needs.")
        for field, (required, _) in FIELDS.items():
            options = [NOT_MAPPED, *cols]
            default = options.index(guess[field]) if guess[field] in cols else 0
            choice = st.selectbox(f"{field}{' *' if required else ''}", options, index=default, key=f"map_{uploaded.name}_{field}")
            mapping[field] = None if choice == NOT_MAPPED else choice

    missing, duplicated = mapping_problems(mapping)
    if missing:
        st.error(f"Missing required column(s): **{', '.join(missing)}**. Map them in the sidebar (Column mapping).")
        st.info(f"Columns found in your file: {', '.join(cols)}")
        st.stop()
    if duplicated:
        st.error(f"The same column is mapped to more than one field: {', '.join(duplicated)}.")
        st.stop()
    return raw, mapping, uploaded.name


def init_filter_state(df: pd.DataFrame, source: str) -> dict[str, list]:
    """Create default filter values and (re)initialise session state when the dataset changes."""
    defaults = {
        "f_date": (df["Date"].min().date(), df["Date"].max().date()),
        "f_region": sorted(df["Region"].unique()),
        "f_category": sorted(df["Category"].unique()),
        "f_product": sorted(df["Product"].unique()),
    }
    signature = (source, len(df), str(df["Date"].min()), str(df["Date"].max()))
    if st.session_state.get("_signature") != signature:
        st.session_state.update(defaults)
        st.session_state["_signature"] = signature
    return defaults


def sidebar_filters(df: pd.DataFrame, defaults: dict) -> tuple:
    st.sidebar.header("🔎 Filters")
    lo, hi = defaults["f_date"]
    date_range = st.sidebar.date_input("Date range", min_value=lo, max_value=hi, key="f_date")
    regions = st.sidebar.multiselect("Region", defaults["f_region"], key="f_region")
    categories = st.sidebar.multiselect("Category", defaults["f_category"], key="f_category")
    products = st.sidebar.multiselect("Product", defaults["f_product"], key="f_product")

    def reset() -> None:
        st.session_state.update(defaults)

    st.sidebar.button("↺ Reset filters", on_click=reset, width="stretch")
    return date_range, regions, categories, products


def sidebar_about() -> None:
    with st.sidebar.expander("ℹ️ About", expanded=False):
        st.write(
            "Interactive KPI dashboard built with Streamlit, pandas and Plotly. "
            "Upload your own sales data (CSV/Excel) or explore the built-in sample. "
            "Each row is treated as one order; profit = revenue − cost."
        )


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="KPI Dashboard", page_icon="📊", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("📊 KPI Dashboard")

    st.sidebar.title("⚙️ Controls")
    sidebar_about()
    st.sidebar.header("📁 Data")
    raw, mapping, source = sidebar_upload_and_mapping()

    try:
        data, dropped = prepare_data(raw, mapping)
    except Exception as exc:
        st.error(f"Could not process the data with the selected mapping: {exc}")
        st.stop()
    if data.empty:
        st.error("No valid rows after parsing. Check that Date is a date and Units Sold/Revenue/Cost are numeric.")
        st.stop()
    st.sidebar.caption(f"Source: {source} · {len(data):,} rows" + (f" · {dropped} unusable rows skipped" if dropped else ""))

    defaults = init_filter_state(data, source)
    date_range, regions, categories, products = sidebar_filters(data, defaults)
    threshold = st.sidebar.slider("Margin warning threshold (%)", 0, 60, 30)

    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.info("Select both a start and an end date to continue.")
        st.stop()
    filtered = apply_filters(data, date_range, regions, categories, products)
    if filtered.empty:
        st.warning("No data matches the current filters. Widen the selection or click **Reset filters**.")
        st.stop()

    st.subheader("Key Metrics")
    render_kpi_cards(compute_kpis(filtered))
    st.caption("Deltas compare the latest month in the selection with the month before it.")

    tabs = st.tabs(["Overview", "Trends", "Breakdown", "Data", "Insights"])

    charts = build_charts(filtered, "Monthly")

    with tabs[0]:
        st.subheader("Performance Overview")
        st.plotly_chart(charts["trend"], width="stretch", key="chart_1")
        c1, c2 = st.columns(2)
        c1.plotly_chart(charts["region"], width="stretch", key="chart_4")
        c2.plotly_chart(charts["category"], width="stretch", key="chart_5")

    with tabs[1]:
        st.subheader("Trends over Time")
        granularity = st.radio("Granularity", ["Monthly", "Weekly"], horizontal=True)
        trend_charts = build_charts(filtered, granularity)
        st.plotly_chart(trend_charts["trend"], width="stretch", key="chart_2")
        if len(monthly_summary(filtered)) >= 2:
            st.plotly_chart(trend_charts["mom"], width="stretch", key="chart_3")
        else:
            st.info("Month-over-month growth needs at least two months of data.")

    with tabs[2]:
        st.subheader("Breakdown")
        c1, c2 = st.columns(2)
        c1.plotly_chart(charts["top_products"], width="stretch", key="chart_6")
        c2.plotly_chart(charts["heatmap"], width="stretch", key="chart_7")

    with tabs[3]:
        st.subheader("Filtered Data")
        query = st.text_input("Search", placeholder="Type to search any column…")
        shown = filtered.assign(Date=filtered["Date"].dt.date)
        if query:
            hit = shown.astype(str).apply(lambda col: col.str.contains(query, case=False, regex=False)).any(axis=1)
            shown = shown[hit]
        st.caption(f"{len(shown):,} of {len(data):,} rows")
        if shown.empty:
            st.warning("No rows match your search.")
        else:
            st.dataframe(shown, width="stretch", hide_index=True)
        st.download_button("⬇️ Download filtered CSV", shown.to_csv(index=False).encode("utf-8"),
                           "filtered_data.csv", "text/csv", disabled=shown.empty)

        st.subheader("Data Quality")
        report, dups = data_quality(raw)
        q1, q2, q3 = st.columns(3)
        q1.metric("Rows", f"{len(raw):,}")
        q2.metric("Missing values", f"{int(report['Missing'].sum()):,}")
        q3.metric("Duplicate rows", f"{dups:,}")
        st.dataframe(report, width="stretch")

    with tabs[4]:
        st.subheader("Insights")
        for level, message in generate_insights(filtered, threshold):
            {"success": st.success, "warning": st.warning}.get(level, st.info)(message)


if __name__ == "__main__":
    main()
