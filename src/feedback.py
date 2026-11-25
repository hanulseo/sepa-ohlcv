"""Five-session missed-leader analysis from actual OHLCV, no inferred trades."""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.score import normalize

def detect_moves(symbol,company,market,exchange,raw,benchmark=None):
    p=normalize(raw)
    if len(p)<30:
        return []
    records=[]
    # Market clock is defined by index candles. Dates not present are never filled.
    for i in range(max(21,len(p)-5),len(p)):
        prev=p.iloc[i-1]
        row=p.iloc[i]
        prior=p.iloc[i-20:i]
        if float(prev.Close)<=0:continue
        change=(float(row.Close)/float(prev.Close)-1)*100
        vol_ratio=float(row.Volume/max(1,float(prior.Volume.mean())))
        prev_20_high=float(prior.High.max())
        lookback=p.iloc[max(0,i-252):i]
        prev_52_high=float(lookback.High.max()) if len(lookback)>=200 else None
        new20=bool(row.High>prev_20_high)
        new52=bool(prev_52_high is not None and row.High>prev_52_high)
        high_volume=vol_ratio>=1.5
        spike=change>=10
        if not (new52 or new20 and high_volume or spike and high_volume):
            continue
        bench_move=None
        if benchmark is not None:
            b=normalize(benchmark)
            stamp=p.index[i]
            if stamp in b.index and p.index[i-1] in b.index:
                bench_move=(float(b.Close.loc[stamp])/float(b.Close.loc[p.index[i-1]])-1)*100
        records.append({"market":market,"exchange":exchange,"ticker":symbol,"company_name":company,
                        "date":str(p.index[i].date()),"close":round(float(row.Close),5),
                        "one_day_return_pct":round(change,2),
                        "previous_20_day_high":round(prev_20_high,5),
                        "new_20day_high":new20,"new_52week_high":new52,
                        "volume_ratio_20d":round(vol_ratio,2),
                        "index_one_day_return_pct":None if bench_move is None else round(bench_move,2),
                        "trigger":",".join(t for t,yes in
                            (("52week_high",new52),("20day_high_volume",new20 and high_volume),
                             ("spike_10pct_volume",spike and high_volume)) if yes)})
    return records

def load_verified_log(path):
    log=pd.read_csv(path,dtype={"ticker":str})
    needed=["market","ticker","recommended_date","recommended_price","recommendation_type","reason","source"]
    if not set(needed).issubset(log.columns):raise ValueError("Invalid recommendation log columns")
    return log

def evaluate_log(log,price_lookup):
    """No recommendation date/price -> not backtestable. No synthetic entry."""
    items=[]
    for _,r in log.iterrows():
        market,ticker=r["market"],r["ticker"]
        record={"market":market,"ticker":ticker,"recommended_date":r["recommended_date"],
                "recommended_price":r["recommended_price"],
                "recommendation_type":r["recommendation_type"],"source":r["source"],
                "reason":r["reason"],"status":"UNVERIFIED_RECOMMENDATION_LOG",
                "since_recommendation_pct":None,"evaluation_close":None}
        if pd.notna(r["recommended_date"]) and pd.notna(r["recommended_price"]):
            key=(market,ticker)
            if key in price_lookup:
                p=normalize(price_lookup[key])
                date=pd.Timestamp(r["recommended_date"])
                aft=p[p.index>=date]
                if len(aft) and float(r["recommended_price"])>0:
                    record["status"]="COMPUTED_FROM_VERIFIED_LOG"
                    record["evaluation_close"]=float(aft.Close.iloc[-1])
                    record["since_recommendation_pct"]=round(
                        (float(aft.Close.iloc[-1])/float(r["recommended_price"])-1)*100,2)
        items.append(record)
    return pd.DataFrame(items)
