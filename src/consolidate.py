"""Combine GitHub matrix shards, rank globally, and audit listing coverage."""
from __future__ import annotations
import json,logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

LOG=logging.getLogger("consolidate")
logging.basicConfig(level=logging.INFO)

def read_all(root,filename):
    files=sorted(root.glob("shard_*/"+filename))
    parts=[]
    for f in files:
        try:
            p=pd.read_csv(f,dtype={"symbol":str})
            if len(p): parts.append(p)
        except pd.errors.EmptyDataError: continue
    return (pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()),files

def main():
    root=Path("all_shards");out=Path("output");out.mkdir(exist_ok=True)
    universe,ufiles=read_all(root,"universe.csv")
    coverage,cfiles=read_all(root,"coverage.csv")
    scores,sfiles=read_all(root,"scores.csv")
    events,efiles=read_all(root,"recent_events.csv")
    metas=[]
    for path in root.glob("shard_*/meta.json"):
        try: metas.append(json.loads(path.read_text()))
        except Exception as e: LOG.error("Unreadable %s: %s",path,e)
    expected=int(metas[0]["shards"]) if metas else 16
    complete_shards=len(metas)==expected and set(m["shard"] for m in metas)==set(range(expected))
    listing_errors={str(m["shard"]):m.get("listing_errors") for m in metas if m.get("listing_errors")}
    if not universe.empty: universe=universe.drop_duplicates(["region","symbol"])
    if not coverage.empty: coverage=coverage.drop_duplicates(["region","symbol"])
    if not scores.empty:
        scores["ticker"]=scores["ticker"].astype(str).str.replace(r"\.0$","",regex=True)
        scores.loc[scores.market=="KR","ticker"]=scores.loc[scores.market=="KR","ticker"].str.zfill(6)
        scores=scores.drop_duplicates(["market","ticker"])
        for market in ("US","KR"):
            ix=scores.market==market
            n=int(ix.sum())
            if n:
                pct=scores.loc[ix,"excess_return_pct"].rank(method="average",pct=True)*100
                rs=np.clip(np.round(scores.loc[ix,"excess_return_pct"].fillna(-999)/30*16),0,16)
                rs=rs+np.clip(np.round(pct/100*4),0,4)
                scores.loc[ix,"rs20"]=rs.astype(int)
                scores.loc[ix,"rs_universe_sample"]=n
                scores.loc[ix,"total100"]=(scores.loc[ix,["trend30","rs20","vcp20","leading20","pivot10"]]
                                             .sum(axis=1)).astype(int)
        def classify(r):
            try: filters=json.loads(r["filters"])
            except Exception: return "WATCH"
            pre=all(filters.get(k) is True for k in
                ("52w_low_plus_100","benchmark_outperformance","leading_volume","vcp"))
            if not pre:return "WATCH"
            if filters.get("pivot") is True and filters.get("breakout_volume") is True and r["total100"]>=80:
                return "BUY NOW"
            if filters.get("pivot") is False and r["total100"]>=70:return "BUY WAIT"
            return "WATCH"
        scores["status"]=scores.apply(classify,axis=1)
        scores=scores.sort_values(["total100","market","company_name"],ascending=[False,True,True])
    universe.to_csv(out/"full_universe.csv",index=False,encoding="utf-8-sig")
    coverage.to_csv(out/"coverage.csv",index=False,encoding="utf-8-sig")
    scores.to_csv(out/"all_scores.csv",index=False,encoding="utf-8-sig")
    top=pd.concat([scores[scores.market=="US"].head(6),
                   scores[scores.market=="KR"].head(4)],ignore_index=True) if not scores.empty else pd.DataFrame()
    if not top.empty: top=top.sort_values("total100",ascending=False)
    top.to_csv(out/"top10.csv",index=False,encoding="utf-8-sig")
    approved=scores[scores.status.isin(["BUY NOW","BUY WAIT"])] if not scores.empty else pd.DataFrame()
    approved.to_csv(out/"all_approved.csv",index=False,encoding="utf-8-sig")
    # Retrospective: flag recent events absent from the top-10 table, not
    # alleged missed BUY recommendations. Event OHLCV is the underlying evidence.
    if not events.empty:
        events["ticker"]=events.ticker.astype(str).str.replace(r"\\.0$","",regex=True)
        events.loc[events.market=="KR","ticker"]=events.loc[events.market=="KR","ticker"].str.zfill(6)
        events=events.drop_duplicates(["market","ticker","date"])
        top_set=set(zip(top.market,top.ticker)) if not top.empty else set()
        events["included_in_top10"]=events.apply(
            lambda r:(r.market,r.ticker) in top_set,axis=1)
        events["potentially_missed_from_top10"]=~events["included_in_top10"]
        events=events.sort_values(["date","new_52week_high","one_day_return_pct"],
                                  ascending=[False,False,False])
    events.to_csv(out/"recent_5session_events.csv",index=False,encoding="utf-8-sig")
    misses=events[events.potentially_missed_from_top10] if not events.empty else pd.DataFrame()
    misses.head(50).to_csv(out/"recent_5session_missed_top50.csv",index=False,encoding="utf-8-sig")
    counts=coverage.status.value_counts().to_dict() if not coverage.empty else {}
    report={"generated_kst":datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "exchange_scope":["NASDAQ","NYSE","AMEX","KOSPI","KOSDAQ"],
            "shards_found":len(metas),"shards_expected":expected,"shards_complete":complete_shards,
            "exchange_listing_errors":listing_errors,
            "unique_listed":int(len(universe)),"recorded_coverage":int(len(coverage)),
            "scored":int(len(scores)),"US_scored":int((scores.market=="US").sum()) if not scores.empty else 0,
            "KR_scored":int((scores.market=="KR").sum()) if not scores.empty else 0,
            "coverage_status_counts":{str(k):int(v) for k,v in counts.items()},
            "fully_processed_listing":complete_shards and not listing_errors and len(universe)==len(coverage),
            "eligible_buy_signals":int(len(approved)),
            "recent_events":int(len(events)),"recent_events_not_in_top10":int(len(misses)),
            "qualification":"Every available listing ticker attempted, not all successfully priced. ETF/security-class filtering heuristic; fundamentals not covered.",
            "top10":top[["market","company_name","ticker","exchange","total100","trend30","rs20","vcp20","leading20","pivot10","bars","date","status"]].to_dict("records") if not top.empty else []}
    (out/"coverage_summary.json").write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    t=["# Full-market SEPA scanner","",
       "Data date and universe coverage are authoritative in coverage_summary.json.","",
       f"- Listed in discovered exchanges: {len(universe):,}",
       f"- Tickers attempted / coverage recorded: {len(coverage):,}",
       f"- Actually scored from OHLCV: {len(scores):,} (US {report['US_scored']:,}, KR {report['KR_scored']:,})",
       f"- All {expected} matrix shards present: {complete_shards}",
       f"- Fully processed listing: {report['fully_processed_listing']}",
       f"- BUY NOW/WAIT qualified: {len(approved)}","",
       "|회사명 (티커)|시장|추세30|RS20|VCP20|거래량20|피벗10|총점|기준일|판정|",
       "|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for _,r in top.iterrows():
        t.append(f"|{r.company_name} ({r.ticker})|{r.exchange}|{r.trend30}|{r.rs20}|{r.vcp20}|{r.leading20}|{r.pivot10}|**{r.total100}**|{r.date}|{r.status}|")
    t+=["","## Coverage outcomes",""]
    for key,val in counts.items(): t.append(f"- {key}: {val:,}")
    t+=["","Important: 52w_low_plus_100 requires 252 sessions; insufficient history blocks BUY. Scored does not mean SEPA gates are passed."]
    t+=["","## 사후피드백 — 최근 5거래일 급등·신고가 누락 추적","",
        f"- OHLCV 검출 신호 {len(events):,}건 / 상위 10종목에 포함되지 않은 신호 {len(misses):,}건.",
        "- 누락은 상위 10종목 표 미포함을 뜻하며 당시 실제 매수 가능했다는 의미가 아님.",
        "- 각 종목은 발생일 종가·일간 수익률·20거래일 평균 대비 거래량·52주 신고가 여부로 정렬함.","",
        "|기업명 (티커)|발생일|당일 수익률|거래량/20일|52주 신고가|",
        "|---|---|---:|---:|---|"]
    for _,e in misses.head(12).iterrows():
        t.append(f"|{e.company_name} ({e.ticker})|{e.date}|{float(e.one_day_return_pct):+.2f}%|{float(e.volume_ratio_20d):.2f}배|{'예' if e.new_52week_high else '아니오'}|")
    t+=["","## 과거 추천 로그 검증","",
        "- FCX·FIVE·ERO·SHOP·FEIM·FTNT·GNRC·TWST·CRWD: 당시 추천 날짜·가격·추천 사유의 검증된 원본 로그가 현재 저장소에 없어 수익률 산정 불가.",
        "- 추천 시점이 확인되지 않은 종목에 임의 진입가격·수익률을 부여하지 않음.",
        "- 앞으로 추천시점과 기준가격을 기록하고 이후 실제 일봉과 대조하도록 추천 로그 구조를 유지함."]
    (out/"report.md").write_text("\n".join(t),encoding="utf-8")
    LOG.info("Coverage summary: %s",json.dumps({k:v for k,v in report.items() if k!="top10"},ensure_ascii=False))
    if not report["fully_processed_listing"] or scores.empty:
        raise RuntimeError("Coverage incomplete or zero scores: inspect output/coverage_summary.json")

if __name__=="__main__":main()
