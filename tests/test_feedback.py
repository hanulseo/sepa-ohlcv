import numpy as np
import pandas as pd
from src.feedback import detect_moves,load_verified_log,evaluate_log

def make_data(days=60):
    idx=pd.bdate_range("2026-07-01",periods=days)
    close=np.full(days,20.,dtype=float)
    volume=np.full(days,1000.,dtype=float)
    close[-3]=24.
    volume[-3]=2500.
    return pd.DataFrame({"Open":close,"High":close*1.02,"Low":close*.98,
                         "Close":close,"Volume":volume},index=idx)

def test_five_day_event_is_observed():
    data=make_data()
    rows=detect_moves("ABC","Example","US","NASDAQ",data,data)
    assert any(r["date"]==str(data.index[-3].date()) and
               r["ticker"]=="ABC" and r["volume_ratio_20d"]>=1.5 for r in rows)

def test_no_fake_historical_recommendation(tmp_path):
    p=tmp_path/"history.csv"
    p.write_text("market,ticker,recommended_date,recommended_price,recommendation_type,reason,source\nUS,FCX,,,,,\n")
    log=load_verified_log(p)
    result=evaluate_log(log,{("US","FCX"):make_data()})
    assert result.iloc[0]["status"]=="UNVERIFIED_RECOMMENDATION_LOG"
    assert pd.isna(result.iloc[0]["since_recommendation_pct"])

def test_verified_price_audit(tmp_path):
    d=make_data()
    p=tmp_path/"history.csv"
    p.write_text("market,ticker,recommended_date,recommended_price,recommendation_type,reason,source\nUS,FCX,2026-07-01,10.0,WATCH,trend,archive\n")
    log=load_verified_log(p)
    r=evaluate_log(log,{("US","FCX"):d})
    assert r.iloc[0]["status"]=="COMPUTED_FROM_VERIFIED_LOG"
    assert r.iloc[0]["since_recommendation_pct"]==100.0
