"""Streamlit dashboard：政府標案觀測（軟體開發類）。"""
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="政府標案觀測", layout="wide")

DATA_PATH = "data/bids.csv"


@st.cache_data(ttl=3600)
def load():
    df = pd.read_csv(DATA_PATH, dtype=str)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    for col in ("budget", "award_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["month"] = df["date"].dt.to_period("M").astype(str)
    return df


try:
    df = load()
except FileNotFoundError:
    st.error(f"找不到資料檔 {DATA_PATH}。等 GitHub Actions 第一次跑完或 push 初始資料後重整。")
    st.stop()

st.title("政府標案觀測（軟體開發類）")
st.caption(f"資料截至 {df['date'].max().strftime('%Y-%m-%d') if df['date'].notna().any() else 'N/A'} · 共 {len(df):,} 筆")

tab1, tab2, tab3, tab4 = st.tabs(["總覽", "熱度", "廠商", "清單"])

# ---- 總覽 ----
with tab1:
    c1, c2, c3, c4 = st.columns(4)
    last_week = df[df["date"] >= df["date"].max() - pd.Timedelta(days=7)]
    c1.metric("近 7 天新增", f"{len(last_week):,}")
    if "budget" in df.columns:
        c2.metric("總預算（近 12 月，億）", f"{df[df['date'] >= df['date'].max() - pd.Timedelta(days=365)]['budget'].sum() / 1e8:,.1f}")
    award = df[df["type"].str.contains("決標", na=False)]
    c3.metric("決標筆數", f"{len(award):,}")
    c4.metric("機關數", f"{df['unit_name'].nunique():,}")

    monthly = df.groupby("month").size().reset_index(name="count")
    fig = px.bar(monthly, x="month", y="count", title="月度標案數")
    st.plotly_chart(fig, use_container_width=True)

# ---- 熱度 ----
with tab2:
    st.subheader("分類月度環比成長（Top 10）")
    if "category" in df.columns and df["category"].notna().any():
        cat_month = df.groupby(["category", "month"]).size().unstack(fill_value=0)
        if cat_month.shape[1] >= 2:
            last, prev = cat_month.columns[-1], cat_month.columns[-2]
            growth = pd.DataFrame({
                "category": cat_month.index,
                "last": cat_month[last],
                "prev": cat_month[prev],
            })
            growth = growth[growth["last"] >= 5]
            growth["growth_%"] = ((growth["last"] / growth["prev"].replace(0, 1)) - 1) * 100
            st.dataframe(growth.sort_values("growth_%", ascending=False).head(10), use_container_width=True)
        else:
            st.info("資料跨度不足 2 個月，無法計算環比")
    else:
        st.info("尚無分類資料（需 fetch_bids.py detail 模式）")

# ---- 廠商 ----
with tab3:
    award = df[df["type"].str.contains("決標", na=False) & df["companies"].notna()].copy()
    if len(award):
        award["company"] = award["companies"].str.split("|")
        exploded = award.explode("company")
        exploded["company"] = exploded["company"].str.strip()
        agg = exploded.groupby("company").agg(
            次數=("job_number", "count"),
            總金額=("award_amount", "sum"),
        ).sort_values("次數", ascending=False).head(50)
        st.dataframe(agg, use_container_width=True)
    else:
        st.info("尚無決標資料")

# ---- 清單 ----
with tab4:
    col1, col2, col3 = st.columns(3)
    types = col1.multiselect("類型", df["type"].dropna().unique())
    kw = col2.text_input("標題關鍵字")
    date_range = col3.date_input("日期區間", value=(df["date"].min(), df["date"].max()))

    view = df.copy()
    if types:
        view = view[view["type"].isin(types)]
    if kw:
        view = view[view["title"].str.contains(kw, case=False, na=False)]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        view = view[(view["date"] >= pd.Timestamp(date_range[0])) & (view["date"] <= pd.Timestamp(date_range[1]))]

    st.caption(f"{len(view):,} 筆")
    st.dataframe(
        view[["date", "unit_name", "type", "title", "budget", "award_amount", "companies", "url"]],
        use_container_width=True,
        column_config={"url": st.column_config.LinkColumn("連結")},
    )
