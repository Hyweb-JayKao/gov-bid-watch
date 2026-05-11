"""政府採購法合規查核 PoC（Story 006 Phase 3）。

輸入：bids.csv 解析後的 DataFrame
輸出：違規候選清單，每筆含 rule_id / article_no / severity / evidence

目前規則僅 PoC，著重在公開資料即可推論的訊號；非法律結論。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class Finding:
    job_number: str
    unit_name: str
    title: str
    date: str
    rule_id: str
    article_no: str
    article_title: str
    severity: str  # low / mid / high
    evidence: str


Rule = Callable[[pd.DataFrame], list[Finding]]
RULES: dict[str, Rule] = {}


def rule(rule_id: str) -> Callable[[Rule], Rule]:
    def deco(fn: Rule) -> Rule:
        RULES[rule_id] = fn
        return fn

    return deco


def _row_meta(r) -> dict:
    return {
        "job_number": str(r.get("job_number", "")),
        "unit_name": str(r.get("unit_name", "") or ""),
        "title": str(r.get("title", "") or ""),
        "date": r["date"].strftime("%Y-%m-%d") if pd.notna(r.get("date")) else "",
    }


@rule("R-058-低價偏離")
def r58(df: pd.DataFrame) -> list[Finding]:
    """§58：總標價偏低之處理。

    分級：
    - ratio < 0.6 → high（大幅偏低）
    - 0.6 ≤ ratio < 0.8 → low（觀察區，採購法施行細則 §79 常用 80% 門檻）
    """
    out: list[Finding] = []
    award = df[df["type"].str.contains("決標", na=False)].copy()
    award = award[award["award_amount"].notna() & award["budget"].notna()]
    award = award[award["budget"] > 0]
    award["ratio"] = award["award_amount"] / award["budget"]
    hits = award[award["ratio"] < 0.8]
    for _, r in hits.iterrows():
        meta = _row_meta(r)
        sev = "high" if r["ratio"] < 0.6 else "low"
        out.append(
            Finding(
                **meta,
                rule_id="R-058-低價偏離",
                article_no="58",
                article_title="總標價偏低之處理",
                severity=sev,
                evidence=f"決標金額 {int(r['award_amount']):,} / 預算 {int(r['budget']):,} = {r['ratio']:.0%}",
            )
        )
    return out


@rule("R-087-集中度")
def r87(df: pd.DataFrame) -> list[Finding]:
    """§87/88：同機關短期內高度集中於少數廠商，圍標 / 不當聯合行為的訊號。

    PoC 條件：近 12 個月內，某機關決標案中，單一廠商佔 ≥ 70% 且案數 ≥ 5。
    回報該廠商於該機關的最近一筆決標案做為代表。
    """
    out: list[Finding] = []
    if "date" not in df.columns:
        return out
    cutoff = df["date"].max() - pd.Timedelta(days=365)
    recent = df[df["date"] >= cutoff].copy()
    award = recent[recent["type"].str.contains("決標", na=False)].copy()
    award = award[award["companies"].fillna("").astype(str).str.len() > 0]
    award = award[award["unit_name"].fillna("").astype(str).str.len() > 0]

    for unit, grp in award.groupby("unit_name"):
        total = len(grp)
        if total < 5:
            continue
        top = grp["companies"].value_counts()
        if top.empty:
            continue
        winner = top.index[0]
        share = top.iloc[0] / total
        if share >= 0.7 and top.iloc[0] >= 5:
            rep = grp[grp["companies"] == winner].sort_values("date").iloc[-1]
            meta = _row_meta(rep)
            out.append(
                Finding(
                    **meta,
                    rule_id="R-087-集中度",
                    article_no="87",
                    article_title="圍標、強迫投標等罰則",
                    severity="high",
                    evidence=(
                        f"近 12 個月內「{unit}」決標 {total} 件，"
                        f"「{winner}」佔 {top.iloc[0]} 件（{share:.0%}）"
                    ),
                )
            )
    return out


PUBLIC_NOTICE_AMOUNT = 1_500_000  # 公告金額（目前為 NT$150 萬）


@rule("R-049-小額未公開")
def r49(df: pd.DataFrame) -> list[Finding]:
    """§49：未達公告金額但 ≥ 公告金額十分之一者，應公開取得書面報價或企劃書。

    PoC：預算落在 [15萬, 150萬) 且 type 為純「限制性招標」（無「公開徵求/公開評選」字眼）
    → 標示應檢視是否符合 §49 程序。
    """
    out: list[Finding] = []
    if "budget" not in df.columns:
        return out
    lo = PUBLIC_NOTICE_AMOUNT // 10
    hi = PUBLIC_NOTICE_AMOUNT
    sub = df[(df["budget"] >= lo) & (df["budget"] < hi)].copy()
    sub = sub[sub["type"].fillna("").str.contains("限制性招標", na=False)]
    sub = sub[~sub["type"].fillna("").str.contains("公開評選|公開徵求", na=False)]
    for _, r in sub.iterrows():
        meta = _row_meta(r)
        out.append(
            Finding(
                **meta,
                rule_id="R-049-小額未公開",
                article_no="49",
                article_title="未達公告金額之公開取得程序",
                severity="mid",
                evidence=(
                    f"預算 {int(r['budget']):,}（公告金額 1/10~公告金額區間），"
                    f"招標方式：{r.get('type', '')}（請確認是否走公開取得書面報價）"
                ),
            )
        )
    return out


@rule("R-033-單一投標")
def r33(df: pd.DataFrame) -> list[Finding]:
    """§33 / §48：投標家數過少之高金額決標，疑似條件過嚴或限制競爭訊號。

    PoC（無投標家數欄位 → 用 proxy）：
    同 job_number 先有「無法決標」後仍以高金額決標 → 可能為流標重招、條件過嚴。
    """
    out: list[Finding] = []
    if not {"job_number", "type", "award_amount"}.issubset(df.columns):
        return out
    fail = df[df["type"].fillna("").str.contains("無法決標", na=False)]
    fail_jobs = set(fail["job_number"].dropna().astype(str))
    if not fail_jobs:
        return out
    award = df[df["type"].fillna("").str.contains("決標", na=False) & ~df["type"].fillna("").str.contains("無法決標", na=False)].copy()
    award = award[award["job_number"].astype(str).isin(fail_jobs)]
    award = award[award["award_amount"].fillna(0) >= PUBLIC_NOTICE_AMOUNT]
    for _, r in award.iterrows():
        meta = _row_meta(r)
        out.append(
            Finding(
                **meta,
                rule_id="R-033-單一投標",
                article_no="33",
                article_title="投標廠商家數及開標",
                severity="low",
                evidence=(
                    f"同案號曾「無法決標」後再以 {int(r['award_amount']):,} 元決標，"
                    "可能為流標重招／條件過嚴，建議檢視招標條件。"
                ),
            )
        )
    return out


@rule("R-022-限制性")
def r22(df: pd.DataFrame) -> list[Finding]:
    """§22：限制性招標僅得於符合特定款項時辦理。

    PoC：標示出「未經公開評選 / 公開徵求」之限制性招標公告，提醒查驗依據款項。
    僅作旗標，非斷定違規。
    """
    out: list[Finding] = []
    if "type" not in df.columns:
        return out
    sub = df[df["type"].fillna("").str.contains("限制性招標", na=False)]
    sub = sub[~sub["type"].fillna("").str.contains("公開評選|公開徵求", na=False)]
    for _, r in sub.iterrows():
        meta = _row_meta(r)
        out.append(
            Finding(
                **meta,
                rule_id="R-022-限制性",
                article_no="22",
                article_title="限制性招標適用條件",
                severity="low",
                evidence=f"招標方式：{r.get('type', '')}（請查驗 §22 各款依據）",
            )
        )
    return out


def run_all(df: pd.DataFrame, rule_ids: list[str] | None = None) -> list[Finding]:
    targets = rule_ids or list(RULES)
    findings: list[Finding] = []
    for rid in targets:
        findings.extend(RULES[rid](df))
    return findings


def findings_to_df(findings: list[Finding]) -> pd.DataFrame:
    if not findings:
        return pd.DataFrame(
            columns=[
                "date",
                "unit_name",
                "title",
                "job_number",
                "rule_id",
                "article_no",
                "severity",
                "evidence",
            ]
        )
    return pd.DataFrame([f.__dict__ for f in findings])[
        [
            "date",
            "unit_name",
            "title",
            "job_number",
            "rule_id",
            "article_no",
            "article_title",
            "severity",
            "evidence",
        ]
    ]
