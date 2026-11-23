"""SEPA quantitative scores from observed daily OHLCV only."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

def normalize(df):
    if df is None or df.empty:
        return pd.DataFrame()
    d=df.copy()
    if isinstance(d.columns,pd.MultiIndex):
        d.columns=d.columns.get_level_values(0)
    d.columns=[str(c).title() for c in d.columns]
    need=["Open","High","Low","Close","Volume"]
    if not all(c in d for c in need):
        return pd.DataFrame()
    d=d[need].apply(pd.to_numeric,errors="coerce")
    d.index=pd.to_datetime(d.index,utc=True).tz_convert(None).normalize()
    d=d[~d.index.duplicated(keep="last")].sort_index().dropna()
    return d[(d[["Open","High","Low","Close"]]>0).all(axis=1) & (d.Volume>=0)]

def score_one(symbol,market,raw,benchmark,percentile=None):
    p,b=normalize(raw),normalize(benchmark)
    if len(p)<20 or b.empty:
        return None
    aligned=p[["Close"]].rename(columns={"Close":"stock"}).join(
        b[["Close"]].rename(columns={"Close":"index"}),how="inner").dropna()
    if len(aligned)<20 or aligned.index[-1] != p.index[-1]:
        return None
    n=len(p)
    c,v=p.Close,p.Volume
    last=float(c.iloc[-1])
    m20=float(c.tail(20).mean())
    m50=float(c.tail(50).mean()) if n>=50 else None
    m150=float(c.tail(150).mean()) if n>=150 else None
    m200=float(c.tail(200).mean()) if n>=200 else None
    old200=float(c.iloc[-220:-20].mean()) if n>=220 else None
    if n>=200:
        trend=sum((7 if last>m50 else 0,5 if last>m150 else 0,
                   5 if last>m200 else 0,6 if m50>m150>m200 else 0,
                   7 if old200 is not None and m200>old200 else 0))
    else:
        change20=last/float(c.iloc[-20])-1
        trend=sum((10 if last>m20 else 0,8 if m50 and last>m50 else 0,
                   7 if m50 and m20>m50 else 0,5 if change20>0 else 0))
    stock_ret=float(aligned.stock.iloc[-1]/aligned.stock.iloc[0]-1)
    index_ret=float(aligned["index"].iloc[-1]/aligned["index"].iloc[0]-1)
    excess=stock_ret-index_ret
    rs=min(16,max(0,round(excess/.30*16))) + (min(4,max(0,round(percentile/100*4))) if percentile is not None else 0)
    widths=[]
    if n>=40:
        for sub in (p.iloc[-40:-30],p.iloc[-30:-20],p.iloc[-20:-10],p.iloc[-10:]):
            widths.append(float(sub.High.max()/sub.Low.min()-1))
        contractions=sum(widths[i+1]<widths[i] for i in range(3))
        dry=float(v.tail(10).mean()/max(1,v.iloc[-40:-10].mean()))
        vcp=min(12,contractions*4)+(8 if dry<=.55 else 5 if dry<=.70 else 2 if dry<=.85 else 0)
        vcp_ok=contractions>=2 and dry<=.70 and widths[-1]<=.18
    else:
        dry=float(v.tail(5).mean()/max(1,v.iloc[:-5].mean()))
        vcp=8 if dry<=.55 else 5 if dry<=.70 else 2 if dry<=.85 else 0
        vcp_ok=False
    historical=v.iloc[-65:-15] if n>=65 else v.iloc[:-10] if n>=30 else v.iloc[:-5]
    lead=float(historical.max()/max(1,historical.mean()))
    leading=20 if lead>=2 else 15 if lead>=1.5 else 8 if lead>=1.2 else 0
    pivot=float(p.High.iloc[-21:-1].max()) if n>=21 else None
    breakout=pivot is not None and pivot<=last<=pivot*1.05
    vr=float(v.iloc[-1]/max(1,v.iloc[-51:-1].mean() if n>=51 else v.iloc[:-1].mean()))
    pivot_score=10 if breakout and vr>=1.5 else 6 if breakout else 0
    # A fully observed 52-week window needs 252 sessions, not just 200.
    low_date=p.Low.tail(252).idxmin() if n>=252 else None
    low=float(p.Low.loc[low_date]) if low_date is not None else None
    since_low=last/low-1 if low is not None else None
    relative_low=None
    if low_date is not None and low_date in b.index and p.index[-1] in b.index:
        relative_low=last/float(p.Close.loc[low_date])-1 - (
            float(b.Close.loc[p.index[-1]])/float(b.Close.loc[low_date])-1)
    filters={"52w_low_plus_100":None if since_low is None else bool(since_low>=1),
             "benchmark_outperformance":None if relative_low is None else bool(relative_low>0),
             "leading_volume":bool(lead>=1.5),"vcp":bool(vcp_ok),"pivot":bool(breakout),
             "breakout_volume":bool(vr>=1.5)}
    total=int(trend+rs+vcp+leading+pivot_score)
    pre=all(filters[k] is True for k in ("52w_low_plus_100","benchmark_outperformance","leading_volume","vcp"))
    status="BUY NOW" if pre and breakout and vr>=1.5 and total>=80 else (
           "BUY WAIT" if pre and not breakout and total>=70 else "WATCH")
    entry=pivot if status=="BUY NOW" else None
    return {"ticker":symbol,"market":market,"date":str(p.index[-1].date()),"bars":n,
            "score_type":"REGULAR" if n>=220 else "SHORT_HISTORY_PROXY",
            "trend30":int(trend),"rs20":int(rs),"vcp20":int(vcp),
            "leading20":int(leading),"pivot10":int(pivot_score),"total100":total,
            "rs_sample_percentile":None if percentile is None else round(float(percentile),1),
            "excess_return_pct":round(excess*100,2),"vcp_widths":widths,
            "volume_dryup_ratio":round(dry,3),"leading_volume_ratio":round(lead,3),
            "breakout_volume_ratio":round(vr,3),"low52":low,
            "rise_since_low_pct":None if since_low is None else round(since_low*100,2),
            "excess_since_low_pct":None if relative_low is None else round(relative_low*100,2),
            "pivot":pivot,"last_close":last,"status":status,"filters":filters,
            "entry":entry,"stop_minus_10pct":None if entry is None else round(entry*.9,4),
            "target_plus_20pct":None if entry is None else round(entry*1.2,4),
            "chart_failure_line":float(p.Low.tail(10).min())}
