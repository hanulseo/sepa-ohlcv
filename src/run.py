"""Public no-key US/KR OHLCV scan. Output is research, not trading advice."""
from __future__ import annotations
import json,logging,os,time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf
from src.score import normalize,score_one

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
LOG=logging.getLogger("sepa")
OUT=Path("output")
US="""AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO AMD MU LRCX AMAT KLAC ASML ARM PLTR CRWD PANW NET ZS OKTA FTNT DDOG SNOW MDB ORCL CRM SHOP APP RBLX UBER COIN HOOD IBKR SOFI AFRM V MA JPM GS MS BAC C WFC PGR CB ALL TRV WRB RLI PLMR SKWD AJG HIG AIG KNSL UNH HUM CI ELV HCA LLY NVO ABBV MRK VRTX REGN BIIB INSM GILD ISRG TMO DHR COST WMT TGT DG DLTR KO PEP PG MCD HD LOW DE CAT GE ETN PWR VRT CEG VST NRG GEV NEE XOM CVX COP OXY FCX SCCO GOLD NEM KGC IAG ERO AA ALB MP FSLR ENPH BA LMT RTX NOC GD NFLX SPOT DIS TTD ROKU TTWO EA JBL SANM CLS FN ONTO COHR LITE ANET DELL SMCI TWST FIVE GNRC FEIM""".split()
KR="""005930 000660 042700 058470 009150 005380 000270 012330 105560 055550 086790 316140 138040 024110 035420 035720 259960 036570 352820 068270 207940 196170 028300 000100 128940 000250 095340 247540 086520 091990 214450 263750 039030 336260 108490 145020 099190 041510 035900 122870 253450 078340 060250 348370 272210 267260 047810 012450 064350 010120 028050 005490 015760 034020 373220 006400 051910 003670 011070 017670 030200 032830 000810 139480 161390 004170 010950 150900 067010 197140""".split()

def universe(region,limit):
    fallback=US if region=="US" else KR
    listings=[]
    try:
        import FinanceDataReader as fdr
        markets=("NASDAQ","NYSE","AMEX") if region=="US" else ("KRX",)
        for market in markets:
            d=fdr.StockListing(market)
            key="Symbol" if region=="US" else "Code" if "Code" in d else "Symbol"
            if "Marcap" in d: d=d.sort_values("Marcap",ascending=False)
            listings.extend(str(x).strip() for x in d[key].dropna())
    except Exception as e:
        LOG.warning("%s symbol listing failed: %s",region,str(e)[:200])
    if region=="KR": listings=[s.zfill(6) for s in listings if s.isdigit() and len(s)<=6]
    else: listings=[s for s in listings if s.isascii() and s.replace(".","").replace("-","").isalnum()]
    # Rotate across exchange symbols by calendar day to broaden market coverage over time.
    day=datetime.now(ZoneInfo("Asia/Seoul")).toordinal()
    listings=list(dict.fromkeys(listings))
    rotated=listings[day%len(listings):]+listings[:day%len(listings)] if listings else []
    return list(dict.fromkeys(fallback[:60]+rotated+fallback[60:]))[:limit],bool(listings)

def yahoo_batch(codes,region):
    found={};sources={}
    for offset in range(0,len(codes),15):
        batch=codes[offset:offset+15]
        # KR listing exchange may be KOSDAQ; try .KS first and .KQ later.
        symbols=[s if region=="US" else s+".KS" for s in batch]
        try:
            raw=yf.download(symbols,period="20mo",interval="1d",group_by="ticker",
                            auto_adjust=True,threads=False,progress=False,timeout=20)
            for s,t in zip(batch,symbols):
                try:
                    sub=raw[t] if isinstance(raw.columns,pd.MultiIndex) else raw
                    f=normalize(sub)
                    if len(f)>=20:
                        found[s]=f
                        sources[s]={"provider":"yfinance","symbol":t,"adjusted":True}
                except Exception: pass
        except Exception as e:
            LOG.warning("%s Yahoo batch %d failed: %s",region,offset,str(e)[:150])
    return found,sources

def kr_fallback(codes,found,sources,max_calls=60):
    # Attempt KOSDAQ Yahoo suffix, then FinanceDataReader only when still missing.
    missing=[s for s in codes if s not in found][:max_calls]
    for offset in range(0,len(missing),15):
        batch=missing[offset:offset+15]
        tickers=[s+".KQ" for s in batch]
        try:
            raw=yf.download(tickers,period="20mo",interval="1d",group_by="ticker",
                            auto_adjust=True,threads=False,progress=False,timeout=20)
            for s,t in zip(batch,tickers):
                try:
                    sub=raw[t] if isinstance(raw.columns,pd.MultiIndex) else raw
                    f=normalize(sub)
                    if len(f)>=20:
                        found[s]=f
                        sources[s]={"provider":"yfinance","symbol":t,"adjusted":True}
                except Exception: pass
        except Exception as e: LOG.warning("KOSDAQ retry: %s",str(e)[:120])
    try:
        import FinanceDataReader as fdr
        for s in [s for s in codes if s not in found][:max_calls]:
            try:
                f=normalize(fdr.DataReader(s,(pd.Timestamp.now()-pd.Timedelta(days=640)).strftime("%Y-%m-%d")))
                if len(f)>=20:
                    found[s]=f
                    sources[s]={"provider":"FinanceDataReader","symbol":s,"adjusted":"unverified"}
            except Exception: pass
    except Exception as e: LOG.warning("FDR fallback unavailable: %s",str(e)[:120])

def get_benchmarks():
    out={}
    for region,ticker in (("US","^GSPC"),("KOSPI","^KS11"),("KOSDAQ","^KQ11")):
        try:
            f=normalize(yf.download(ticker,period="20mo",auto_adjust=True,progress=False,timeout=20))
            if len(f)>=20: out[region]=(f,"yfinance:"+ticker)
        except Exception as e: LOG.warning("Benchmark %s unavailable: %s",ticker,str(e)[:120])
    if "KOSPI" not in out or "KOSDAQ" not in out:
        try:
            import FinanceDataReader as fdr
            for reg,code in (("KOSPI","KS11"),("KOSDAQ","KQ11")):
                if reg not in out:
                    try:
                        f=normalize(fdr.DataReader(code,(pd.Timestamp.now()-pd.Timedelta(days=640)).strftime("%Y-%m-%d")))
                        if len(f)>=20: out[reg]=(f,"FDR:"+code)
                    except Exception: pass
        except Exception: pass
    return out

def score_group(region,prices,sources,benchmarks):
    first=[]; invalid=[]
    for ticker,frame in prices.items():
        bkey="US" if region=="US" else "KOSDAQ" if sources[ticker]["symbol"].endswith(".KQ") else "KOSPI"
        if bkey not in benchmarks:
            invalid.append(ticker);continue
        benchmark,bname=benchmarks[bkey]
        try:
            rec=score_one(ticker,region,frame,benchmark)
            if rec:
                rec.update(source=sources[ticker],benchmark=bname)
                first.append(rec)
        except Exception as e: LOG.warning("Scoring %s failed: %s",ticker,str(e)[:120])
    relative=np.sort([x["excess_return_pct"] for x in first])
    for x in first:
        pct=(np.searchsorted(relative,x["excess_return_pct"],side="right")-.5)/len(relative)*100
        bkey="US" if region=="US" else "KOSDAQ" if x["source"]["symbol"].endswith(".KQ") else "KOSPI"
        revised=score_one(x["ticker"],region,prices[x["ticker"]],benchmarks[bkey][0],pct)
        x.update(revised)
        x["rs_universe_sample"]=len(first)
    return sorted(first,key=lambda x:x["total100"],reverse=True),invalid

def main():
    OUT.mkdir(exist_ok=True)
    now=datetime.now(ZoneInfo("Asia/Seoul"))
    b=get_benchmarks()
    result=[];history={};scan={};errors=[]
    for region in ("US","KR"):
        limit=int(os.getenv("MAX_"+region+"_SCAN","120" if region=="US" else "100"))
        codes,listed=universe(region,limit)
        LOG.info("%s symbols attempted=%d exchange_listing=%s",region,len(codes),listed)
        frames,sources=yahoo_batch(codes,region)
        if region=="KR": kr_fallback(codes,frames,sources)
        ranked,invalid=score_group(region,frames,sources,b)
        scan[region]={"attempted":len(codes),"ohlcv_obtained":len(frames),
                      "scored":len(ranked),"listing_success":listed,
                      "benchmark_missing":len(invalid),"full_market_coverage":False}
        result.extend(ranked)
        history.update({(region,s):f for s,f in frames.items()})
    # Report every genuinely eligible BUY signal from the scanned universe.
    result.sort(key=lambda x:x["total100"],reverse=True)
    approved=[r for r in result if r["status"]!="WATCH"]
    # Ten scored observations, independent of any private holdings.
    ten=sorted([r for r in result if r["market"]=="US"][:6]+
               [r for r in result if r["market"]=="KR"][:4],key=lambda x:x["total100"],reverse=True)
    for r in ten:
        history[(r["market"],r["ticker"])].to_csv(OUT/(r["market"]+"_"+r["ticker"]+"_ohlcv.csv"),index_label="date")
    report={"generated_kst":now.isoformat(),"data_scope":"limited retrieved universe, not exhaustive",
            "scan":scan,"ten_scored":ten,"verified_buy_signals":approved,
            "scores_completed":len(result),"warnings":errors,
            "notes":["252 daily sessions required to validate a 52-week low",
                     "RS percentile calculated among successfully scored symbols only",
                     "Yahoo adjusted prices; corporate actions must be verified independently",
                     "Technical VCP proxy is algorithmic, not discretionary chart confirmation",
                     "SEC/DART fundamentals, historical recommendations and personal holdings excluded"]}
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    pd.DataFrame([{**{k:v for k,v in r.items() if k not in ("filters","source","vcp_widths")},
                  "source":r["source"]["provider"]+":"+r["source"]["symbol"]}
                  for r in result]).to_csv(OUT/"scores.csv",index=False,encoding="utf-8-sig")
    lines=[f"# SEPA scan — {now:%Y-%m-%d %H:%M} KST","",
           "**Actual OHLCV only. Scores are quantitative proxies, not independently confirmed trade recommendations.**",""]
    for k,v in scan.items():
        lines.append(f"- {k}: attempted {v['attempted']}, OHLCV {v['ohlcv_obtained']}, scored {v['scored']}; exchange listing available={v['listing_success']}")
    lines += ["","|market|ticker|score|trend30|RS20|VCP20|leading20|pivot10|bars|date|status|",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for r in ten:
        lines.append("|"+ "|".join(map(str,[r["market"],r["ticker"],r["total100"],r["trend30"],r["rs20"],r["vcp20"],r["leading20"],r["pivot10"],r["bars"],r["date"],r["status"]]))+"|")
    lines+=["",f"Verified BUY candidates in scanned subset: {len(approved)}.",
            "Unretrieved symbols must not be counted as having failed SEPA screens.",
            "No private positions/cost basis are stored in this public repository."]
    (OUT/"report.md").write_text("\n".join(lines),encoding="utf-8")
    LOG.info("Completed %d scored; top list %d; approved %d",len(result),len(ten),len(approved))
    if not result: raise RuntimeError("No observed prices with aligned benchmarks; check upstream providers and logs")

if __name__=="__main__":
    main()
