"""Immediate source-verified postmortem for nine historical watchlist names.

A watchlist mention is NOT an executed recommendation; absent recorded date,
price and reason, log returns are withheld rather than invented.
"""
from __future__ import annotations
import json,logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf
from src.score import normalize
from src.feedback import detect_moves,load_verified_log,evaluate_log

logging.basicConfig(level=logging.INFO)
LOG=logging.getLogger("feedback_check")
TICKERS=["FCX","FIVE","ERO","SHOP","FEIM","FTNT","GNRC","TWST","CRWD"]
def main():
    out=Path("feedback_output")
    out.mkdir(exist_ok=True)
    log=load_verified_log("data/historical_recommendations.csv")
    prices={};recent=[];events=[];errors=[]
    try:
        b=normalize(yf.download("^GSPC",period="5mo",interval="1d",auto_adjust=True,progress=False,timeout=25))
    except Exception as e:
        b=None
        errors.append("benchmark:"+str(e)[:160])
    for ticker in TICKERS:
        try:
            p=normalize(yf.download(ticker,period="14mo",interval="1d",
                        auto_adjust=True,progress=False,timeout=25))
            if len(p)<30:
                raise ValueError("fewer than 30 valid trading sessions")
            prices[("US",ticker)]=p
            last5=p.tail(6)
            first,last=last5.iloc[0],last5.iloc[-1]
            day_count=len(last5)-1
            five_return=(float(last.Close)/float(first.Close)-1)*100 if day_count==5 else None
            recent.append({"ticker":ticker,"company_name":ticker,"date":str(p.index[-1].date()),
                     "close":round(float(last.Close),5),
                     "trading_days":day_count,
                     "last_5sessions_return_pct":round(five_return,2) if five_return is not None else None,
                     "last_5sessions_high":round(float(p.High.tail(5).max()),5),
                     "last_5sessions_low":round(float(p.Low.tail(5).min()),5),
                     "bars":len(p),"source":"Yahoo Finance / yfinance adjusted OHLCV"})
            events.extend(detect_moves(ticker,ticker,"US","US",p,b))
            LOG.info("Historical watchlist %s OHLCV=%d latest=%s",ticker,len(p),p.index[-1].date())
        except Exception as e:
            errors.append(ticker+":"+str(e)[:180])
    daily=pd.DataFrame(recent)
    daily.to_csv(out/"old_watchlist_actual_5day_returns.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(events).to_csv(out/"old_watchlist_recent_events.csv",index=False,encoding="utf-8-sig")
    historical=evaluate_log(log,prices)
    historical.to_csv(out/"recommendation_history_audit.csv",index=False,encoding="utf-8-sig")
    notes=["# 추천·누락 사후검증 (실제 OHLCV)","",
           "수집: "+datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
           "","과거 후보로 언급되었다는 사실과 실제 매수 추천은 구분함.",
           "추천 당시의 검증 가능한 날짜·가격·사유가 없다면 추천 이후 수익률을 산정하지 않음.",
           "","|기업명/티커|기준일|최근 5거래일 등락|최근 5일 고가|최근 종가|",
           "|---|---|---:|---:|---:|"]
    for r in recent:
        ret="미산출" if r["last_5sessions_return_pct"] is None else "{:+.2f}%".format(r["last_5sessions_return_pct"])
        notes.append(f"|{r['ticker']}|{r['date']}|{ret}|{r['last_5sessions_high']}|{r['close']}|")
    notes+=["","## 추천일 기준 성과평가","",
            "- FCX/FIVE/ERO/SHOP/FEIM/FTNT/GNRC/TWST/CRWD의 당시 추천 날짜·가격·사유는 미확인.",
            "- 그 시점을 검증한 뒤에만 추천가 대비 현재 수익률을 계산함.",
            "- 위 5거래일 등락률은 과거 추천 이후 수익률이 아님.","",
            "## 데이터 수집 실패 항목",""]
    notes.extend("- "+e for e in errors)
    (out/"feedback.md").write_text("\n".join(notes),encoding="utf-8")
    (out/"summary.json").write_text(json.dumps({"generated_kst":datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
                  "expected_tickers":len(TICKERS),"retrieved":len(recent),
                  "actually_verified_recommendation_logs":int((historical.status=="COMPUTED_FROM_VERIFIED_LOG").sum()),
                  "recent_breakouts_or_spikes":len(events),"errors":errors},ensure_ascii=False,indent=2),encoding="utf-8")
    if not recent:raise RuntimeError("No actual OHLCV retrieved")

if __name__=="__main__":main()
