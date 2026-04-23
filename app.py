"""Streamlit dashboard：政府標案觀測（軟體開發類）。"""
import re

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="政府標案觀測", layout="wide")

DATA_PATH = "data/bids.csv"

# 需求主題關鍵字（用於分析機關/廠商的需求類型）
DEMAND_THEMES = {
    "系統建置": ["系統建置", "建置案", "開發案", "新建", "導入"],
    "系統維運": ["維運", "維護", "保養", "年度維護", "委外維護"],
    "網站平台": ["網站", "平台", "平臺", "入口網"],
    "App 應用": ["App", "APP", "應用程式", "行動", "Mobile"],
    "資訊服務": ["資訊服務", "資料處理", "委託服務"],
    "資安": ["資安", "資訊安全", "防火牆", "資通安全"],
    "雲端": ["雲端", "Cloud", "虛擬化", "容器"],
    "AI/數據": ["AI", "人工智慧", "大數據", "數據分析", "機器學習"],
    "資料庫": ["資料庫", "Database", "DB"],
    "GIS/地圖": ["GIS", "地理資訊", "地圖", "圖資"],
    "資訊設備": ["資訊設備", "電腦", "伺服器", "筆電", "平板"],
    "網路": ["網路", "交換器", "路由器", "WIFI", "Wi-Fi"],
    "教育訓練": ["訓練", "課程", "教育", "研習"],
    "監控/監視": ["監視", "監控", "攝影機", "CCTV"],
    "身分識別": ["身分", "認證", "簽章", "FIDO"],
}


def count_themes(titles):
    result = {}
    for theme, kws in DEMAND_THEMES.items():
        n = sum(any(k in str(t) for k in kws) for t in titles)
        if n:
            result[theme] = n
    return result

# 凌網系列：任一匹配即標示為自家
OWN_COMPANIES = ["凌網資訊", "凌網全球", "HYWEB", "網擎"]
HIGHLIGHT_COLOR = "#E74C3C"

# 機關類型分類（6 類）
UNIT_TYPE_RULES = [
    ("國營事業", re.compile(r"台灣電力|中油|台灣自來水|中華郵政|台灣鐵路|台灣糖業|台灣肥料|桃園國際機場|漢翔|中華電信|台灣港務|中央印製|台灣菸酒|台船|臺灣銀行|土地銀行|合作金庫|第一銀行|華南銀行|彰化銀行|兆豐|陽信|臺北自來水")),
    ("醫療", re.compile(r"醫院|醫療|衛生所|健保|疾病管制")),
    ("學校", re.compile(r"大學|學院|高中|高商|國中|國小|幼兒園|學校|國民中學|國民小學|職校|技術學院|科技大學")),
    ("地方政府", re.compile(r"縣政府|市政府|鄉公所|鎮公所|區公所|縣|市立|鄉立|鎮立|村里")),
    ("中央部會", re.compile(r"行政院|立法院|司法院|考試院|監察院|總統府|部$|署$|委員會|國家|中央|銓敘|審計|法務部|教育部|國防部|外交部|財政部|經濟部|交通部|農業部|衛生福利|文化部|內政部|勞動部|數位發展|環境|國科會|通傳")),
]


def classify_unit(name):
    if not name or pd.isna(name):
        return "其他"
    for label, rx in UNIT_TYPE_RULES:
        if rx.search(str(name)):
            return label
    return "其他"


def is_own(company):
    if not company or pd.isna(company):
        return False
    return any(k in str(company) for k in OWN_COMPANIES)


@st.cache_data(ttl=3600)
def load():
    df = pd.read_csv(DATA_PATH, dtype=str)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    for col in ("budget", "award_amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["unit_type"] = df["unit_name"].apply(classify_unit)
    return df


try:
    df = load()
except FileNotFoundError:
    st.error(f"找不到資料檔 {DATA_PATH}。等 GitHub Actions 第一次跑完或 push 初始資料後重整。")
    st.stop()

st.title("政府標案觀測（軟體開發類）")
date_max = df["date"].max()
date_min = df["date"].min()
date_span_days = (date_max - date_min).days if pd.notna(date_max) and pd.notna(date_min) else 0
st.caption(
    f"資料 {date_min.strftime('%Y-%m-%d') if pd.notna(date_min) else 'N/A'} ~ "
    f"{date_max.strftime('%Y-%m-%d') if pd.notna(date_max) else 'N/A'} · "
    f"共 {len(df):,} 筆 · 跨度 {date_span_days} 天"
)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["市場", "趨勢", "競爭", "機關", "清單"])

# ---------- 市場 ----------
with tab1:
    st.subheader("市場大小")
    award = df[df["type"].str.contains("決標", na=False) & df["award_amount"].notna()]

    c1, c2, c3, c4 = st.columns(4)
    total_amount = award["award_amount"].sum()
    c1.metric("決標總金額（億）", f"{total_amount / 1e8:,.1f}")
    c2.metric("決標筆數", f"{len(award):,}")
    c3.metric("平均單案（萬）", f"{(award['award_amount'].mean() / 1e4):,.0f}" if len(award) else "—")
    c4.metric("機關數", f"{df['unit_name'].nunique():,}")

    st.divider()
    st.subheader("月度金額趨勢")
    if len(award):
        monthly = award.groupby("month")["award_amount"].sum().reset_index()
        monthly["金額(億)"] = monthly["award_amount"] / 1e8
        fig = px.line(monthly, x="month", y="金額(億)", markers=True, title="月度決標金額（億）")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("尚無決標金額資料（v3 跑完後會有）")

    st.divider()
    st.subheader("案件金額級距分布")
    if len(award):
        bins = [0, 1e6, 5e6, 1e7, 5e7, 1e8, 1e10]
        labels = ["<100萬", "100-500萬", "500-1000萬", "1000-5000萬", "5000萬-1億", ">1億"]
        award_bucket = pd.cut(award["award_amount"], bins=bins, labels=labels)
        dist = award_bucket.value_counts().reindex(labels).reset_index()
        dist.columns = ["級距", "案數"]
        fig = px.bar(dist, x="級距", y="案數", title="案件金額級距")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("尚無金額資料")

    st.divider()
    st.subheader("YoY（同月對比）")
    if len(award):
        tmp = award.copy()
        tmp["年"] = tmp["date"].dt.year
        tmp["月"] = tmp["date"].dt.month
        yoy = tmp.groupby(["年", "月"])["award_amount"].sum().unstack(fill_value=0)
        if len(yoy) >= 2:
            st.dataframe((yoy / 1e8).round(2), use_container_width=True)
            st.caption("單位：億元")
        else:
            st.info("資料跨度不足 2 年，無法算 YoY（待 24 個月 backfill 完成）")
    else:
        st.info("尚無金額資料")

# ---------- 趨勢 ----------
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
        st.info("尚無分類資料（需 v3 跑完）")

    st.divider()
    st.subheader("分類月度趨勢")
    if "category" in df.columns and df["category"].notna().any():
        top_cats = df["category"].value_counts().head(10).index.tolist()
        pick = st.multiselect("選分類（最多 5 個）", top_cats, default=top_cats[:3])
        if pick:
            sub = df[df["category"].isin(pick)]
            trend = sub.groupby(["month", "category"]).size().reset_index(name="count")
            fig = px.line(trend, x="month", y="count", color="category", markers=True)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("尚無分類資料")

    st.divider()
    st.subheader("月度標案數（依年分色）")
    tmp = df.dropna(subset=["date"]).copy()
    tmp["年"] = tmp["date"].dt.year.astype(str)
    tmp["月"] = tmp["date"].dt.month
    monthly_count = tmp.groupby(["年", "月"]).size().reset_index(name="案件數")
    fig = px.bar(monthly_count, x="月", y="案件數", color="年", barmode="group")
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=[f"{m}月" for m in range(1, 13)])
    st.plotly_chart(fig, use_container_width=True)

# ---------- 競爭 ----------
with tab3:
    award_all = df[df["type"].str.contains("決標", na=False) & df["companies"].notna()].copy()
    if len(award_all):
        award_all["company"] = award_all["companies"].str.split("|")
        exploded = award_all.explode("company")
        exploded["company"] = exploded["company"].str.strip()
        exploded["自家"] = exploded["company"].apply(is_own)

        agg = exploded.groupby("company").agg(
            次數=("job_number", "count"),
            總金額=("award_amount", "sum"),
        ).sort_values("次數", ascending=False)
        agg["自家"] = agg.index.to_series().apply(is_own)

        own_rows = agg[agg["自家"]]
        st.subheader("凌網（自家）表現")
        if len(own_rows):
            c1, c2, c3 = st.columns(3)
            c1.metric("自家承接案數", f"{int(own_rows['次數'].sum())}")
            c2.metric("自家總金額（億）", f"{own_rows['總金額'].sum() / 1e8:.2f}")
            market_share = own_rows["次數"].sum() / agg["次數"].sum() * 100 if agg["次數"].sum() else 0
            c3.metric("次數市佔", f"{market_share:.1f}%")
            st.dataframe(own_rows, use_container_width=True)
        else:
            st.info("目前期間無凌網中標紀錄")

        st.divider()
        st.subheader("集中度")
        top10_share = agg.head(10)["次數"].sum() / agg["次數"].sum() * 100
        top20_share = agg.head(20)["次數"].sum() / agg["次數"].sum() * 100
        c1, c2, c3 = st.columns(3)
        c1.metric("Top 10 次數市佔", f"{top10_share:.1f}%")
        c2.metric("Top 20 次數市佔", f"{top20_share:.1f}%")
        c3.metric("總廠商數", f"{len(agg):,}")

        st.divider()
        st.subheader("廠商 Top 20（紅色=凌網）")
        top20 = agg.head(20).reset_index()
        colors = [HIGHLIGHT_COLOR if row["自家"] else "#4A90E2" for _, row in top20.iterrows()]
        import plotly.graph_objects as go
        fig = go.Figure(go.Bar(
            x=top20["次數"], y=top20["company"], orientation="h",
            marker_color=colors,
            text=top20["次數"], textposition="outside",
        ))
        # y 軸字色：凌網紅、其他預設
        tick_colors = [HIGHLIGHT_COLOR if own else "#CCCCCC" for own in top20["自家"]]
        fig.update_yaxes(
            categoryorder="array",
            categoryarray=top20["company"].tolist()[::-1],  # 反轉使最大在上
        )
        fig.update_layout(
            yaxis=dict(
                tickmode="array",
                tickvals=top20["company"].tolist(),
                ticktext=[f'<span style="color:{HIGHLIGHT_COLOR}"><b>{c}</b></span>' if own else c
                         for c, own in zip(top20["company"], top20["自家"])],
            ),
            xaxis_title="次數", height=600,
        )
        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("廠商承接案件（Top 20）")
        top20_names = agg.head(20).index.tolist()
        company = st.selectbox("選廠商", [""] + top20_names)
        if company:
            sub = exploded[exploded["company"] == company].sort_values("date", ascending=False)

            # Summary
            total_amt = sub["award_amount"].sum()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("承接案數", f"{len(sub):,}")
            c2.metric("總金額（億）", f"{total_amt / 1e8:.2f}" if total_amt else "—")
            c3.metric("平均單案（萬）", f"{(sub['award_amount'].mean() / 1e4):,.0f}" if sub["award_amount"].notna().any() else "—")
            c4.metric("合作機關數", f"{sub['unit_name'].nunique():,}")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Top 5 合作機關**")
                top_units = sub.groupby("unit_name").agg(
                    案數=("job_number", "count"),
                    金額=("award_amount", "sum"),
                ).sort_values("案數", ascending=False).head(5)
                top_units["金額"] = (top_units["金額"] / 1e4).round(0).astype(int).astype(str) + " 萬"
                st.dataframe(top_units, use_container_width=True)
            with col2:
                st.markdown("**機關類型分布**")
                type_dist = sub.groupby("unit_type").agg(案數=("job_number", "count")).sort_values("案數", ascending=False)
                st.dataframe(type_dist, use_container_width=True)

            if "category" in sub.columns and sub["category"].notna().any():
                st.markdown("**Top 5 標的分類**")
                cat_dist = sub["category"].value_counts().head(5)
                st.dataframe(cat_dist.rename("案數"), use_container_width=True)

            st.markdown("**承接需求主題分布**")
            themes = count_themes(sub["title"].dropna().tolist())
            if themes:
                theme_df = pd.DataFrame(
                    sorted(themes.items(), key=lambda x: -x[1]),
                    columns=["主題", "案數"],
                )
                fig = px.bar(theme_df, x="案數", y="主題", orientation="h",
                             title=f"「{company}」承接的軟體開發主題")
                fig.update_yaxes(categoryorder="total ascending")
                st.plotly_chart(fig, use_container_width=True)

            st.divider()
            st.caption(f"案件清單：{len(sub):,} 筆（決標）")
            st.dataframe(
                sub[["date", "unit_name", "title", "award_amount", "budget", "url"]],
                use_container_width=True,
                column_config={"url": st.column_config.LinkColumn("連結")},
            )

        st.divider()
        st.subheader("廠商 Top 50 完整表")
        st.dataframe(agg.head(50), use_container_width=True)
    else:
        st.info("尚無決標資料")

# ---------- 機關 ----------
with tab4:
    st.subheader("機關類型分布")
    type_agg = df.groupby("unit_type").agg(
        案件數=("job_number", "count"),
        總預算=("budget", "sum"),
    ).sort_values("案件數", ascending=False)
    c1, c2 = st.columns(2)
    with c1:
        fig = px.pie(type_agg.reset_index(), names="unit_type", values="案件數", title="案件數佔比")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        if type_agg["總預算"].sum() > 0:
            fig = px.pie(type_agg.reset_index(), names="unit_type", values="總預算", title="預算佔比")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("尚無預算資料")

    st.divider()
    st.subheader("機關所有案件")
    unit_type_filter = st.selectbox("機關類型篩選", ["全部"] + type_agg.index.tolist())
    pool = df if unit_type_filter == "全部" else df[df["unit_type"] == unit_type_filter]
    unit = st.selectbox("選機關", [""] + sorted(pool["unit_name"].dropna().unique().tolist()))
    if unit:
        sub = df[df["unit_name"] == unit].sort_values("date", ascending=False)
        sub_award = sub[sub["type"].str.contains("決標", na=False)]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("總案數", f"{len(sub):,}")
        c2.metric("決標案數", f"{len(sub_award):,}")
        c3.metric("決標總金額（億）", f"{sub_award['award_amount'].sum() / 1e8:.2f}" if sub_award["award_amount"].notna().any() else "—")
        c4.metric("平均單案（萬）", f"{(sub_award['award_amount'].mean() / 1e4):,.0f}" if sub_award["award_amount"].notna().any() else "—")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Top 5 承接廠商**")
            aw_c = sub_award[sub_award["companies"].notna()].copy()
            if len(aw_c):
                aw_c["company"] = aw_c["companies"].str.split("|")
                exp = aw_c.explode("company")
                exp["company"] = exp["company"].str.strip()
                top_vendors = exp.groupby("company").agg(
                    案數=("job_number", "count"),
                    金額=("award_amount", "sum"),
                ).sort_values("案數", ascending=False).head(5)
                top_vendors["金額"] = (top_vendors["金額"] / 1e4).round(0).astype(int).astype(str) + " 萬"
                st.dataframe(top_vendors, use_container_width=True)
            else:
                st.caption("尚無決標廠商資料")
        with col2:
            st.markdown("**案件類型分布**")
            type_dist = sub.groupby("type").size().sort_values(ascending=False)
            st.dataframe(type_dist.rename("案數"), use_container_width=True)

        if "category" in sub.columns and sub["category"].notna().any():
            st.markdown("**Top 5 標的分類**")
            cat_dist = sub["category"].value_counts().head(5)
            st.dataframe(cat_dist.rename("案數"), use_container_width=True)

        st.markdown("**需求主題分布**（依標題關鍵字命中）")
        themes = count_themes(sub["title"].dropna().tolist())
        if themes:
            theme_df = pd.DataFrame(
                sorted(themes.items(), key=lambda x: -x[1]),
                columns=["主題", "案數"],
            )
            fig = px.bar(theme_df, x="案數", y="主題", orientation="h",
                         title=f"「{unit}」軟體開發需求主題")
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("無命中主題")

        # 凌網在此機關的表現
        own_here = sub[sub["companies"].fillna("").apply(lambda s: any(k in s for k in OWN_COMPANIES))]
        if len(own_here):
            st.success(f"🎯 凌網在此機關承接 {len(own_here)} 案，總金額 {own_here['award_amount'].sum() / 1e4:,.0f} 萬")

        st.divider()
        st.caption(f"案件清單：{len(sub):,} 筆")
        st.dataframe(
            sub[["date", "type", "title", "budget", "award_amount", "companies", "url"]],
            use_container_width=True,
            column_config={"url": st.column_config.LinkColumn("連結")},
        )

    st.divider()
    st.subheader("機關 Top 50（案件數 / 預算）")
    unit_agg = df.groupby(["unit_name", "unit_type"]).agg(
        案件數=("job_number", "count"),
        決標數=("type", lambda s: s.str.contains("決標", na=False).sum()),
        總預算=("budget", "sum"),
    ).sort_values("案件數", ascending=False).head(50)
    st.dataframe(unit_agg, use_container_width=True)

# ---------- 清單 ----------
with tab5:
    col1, col2, col3 = st.columns(3)
    types = col1.multiselect("類型", df["type"].dropna().unique())
    kw = col2.text_input("標題關鍵字")
    date_range = col3.date_input("日期區間", value=(df["date"].min(), df["date"].max()))

    col4, col5 = st.columns(2)
    unit_types = col4.multiselect("機關類型", df["unit_type"].unique().tolist())
    only_own = col5.checkbox("只看凌網中標", value=False)

    view = df.copy()
    if types:
        view = view[view["type"].isin(types)]
    if unit_types:
        view = view[view["unit_type"].isin(unit_types)]
    if kw:
        view = view[view["title"].str.contains(kw, case=False, na=False)]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        view = view[(view["date"] >= pd.Timestamp(date_range[0])) & (view["date"] <= pd.Timestamp(date_range[1]))]
    if only_own:
        view = view[view["companies"].fillna("").apply(lambda s: any(k in s for k in OWN_COMPANIES))]

    st.caption(f"{len(view):,} 筆")
    st.dataframe(
        view[["date", "unit_name", "unit_type", "type", "title", "budget", "award_amount", "companies", "url"]],
        use_container_width=True,
        column_config={"url": st.column_config.LinkColumn("連結")},
    )
