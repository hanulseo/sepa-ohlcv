"""Enumerate the whole exchange listing; scan one stable shard of names.

All candidates from each universe are attempted. Errors remain visible in coverage.csv.
This does not claim that every listed security has price history.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, os, re, time
from pathlib import Path
import pandas as pd
import yfinance as yf
from src.score import normalize, score_one

LOG=logging.getLogger("full_market")
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
EXCHANGES=("NASDAQ","NYSE","AMEX","KOSPI","KOSDAQ")

def collect_universe():
    import FinanceDataReader as fdr
    rows=[]
    unavailable={}
    for exchange in EXCHANGES:
        try:
            listing=fdr.StockListing(exchange)
            if listing is None or listing.empty:
                raise ValueError("empty listing")
            sym_col=next((x for x in ("Symbol","Code") if x in listing.columns),None)
            if not sym_col:
                raise ValueError("missing Symbol/Code field: "+str(listing.columns.tolist()))
            name_col=next((x for x in ("Name","CompanyName","Company Name") if x in listing.columns),None)
            if not name_col:
                raise ValueError("missing company name: "+str(listing.columns.tolist()))
            for _,r in listing.iterrows():
                sym=str(r[sym_col]).strip().upper()
                if exchange in ("KOSPI","KOSDAQ"):
                    if not sym.isdigit() or len(sym)>6:
                        continue
                    sym=sym.zfill(6)
                else:
                    if not re.fullmatch(r"[A-Z0-9.\-]{1,20}",sym):
                        continue
                name=str(r[name_col]).strip()
                if not name or name.lower() in ("nan","none"):
                    continue
                raw_type=str(r.get("Type",r.get("Category",""))).upper()
                combined=(name+" "+raw_type).upper()
                is_fund=any(t in combined for t in
                    (" ETF"," ETF ","ETN","EXCHANGE TRADED FUND"," EXCHANGE-TRADED FUND",
                     "ISHARES","SPDR ","INVESCO QQQ","PROSHARES","DIREXION","VANGUARD INDEX"))
                is_special=any(t in combined for t in
                    (" WARRANT"," RIGHTS"," UNIT"," DEPOSITARY SHARES"," PREFERRED"," PREFERENCE"))
                # US ticker ending 'W' etc cannot reliably establish instrument class:
                # use metadata/type, report remaining classification uncertainty.
                yahoo=sym if exchange in ("NASDAQ","NYSE","AMEX") else sym+(".KS" if exchange=="KOSPI" else ".KQ")
                rows.append({"region":"US" if exchange in ("NASDAQ","NYSE","AMEX") else "KR",
                    "exchange":exchange,"symbol":sym,"name":name,"yahoo":yahoo,
                    "screen_eligible":not(is_fund or is_special),
                    "class_note":"excluded_fund" if is_fund else "excluded_special" if is_special else "presumed_equity"})
            LOG.info("Listing %-6s %d rows",exchange,len(listing))
        except Exception as e:
            unavailable[exchange]=str(e)[:250]
            LOG.exception("Exchange listing failed: %s",exchange)
    universe=pd.DataFrame(rows)
    if universe.empty:
        raise RuntimeError("No exchange listings obtained")
    universe=universe.drop_duplicates(subset=["region","symbol"],keep="first")
    return universe,unavailable

def shard_of(region,symbol,total):
    digest=hashlib.sha256((region+":"+symbol).encode()).digest()
    return int.from_bytes(digest[:8],"big")%total

def download_batch(records):
    """Try batched Yahoo; use explicit one-at-a-time retry for missed symbols."""
    if not records: return {},{}
    names=[r["yahoo"] for r in records]
    found={};problems={}
    def extract(raw,records):
        for r in records:
            try:
                f=normalize(raw[r["yahoo"]] if isinstance(raw.columns,pd.MultiIndex) else raw)
                if len(f)>=20:
                    found[r["yahoo"]]=f
                else:
                    problems[r["yahoo"]]="no_20_day_ohlcv"
            except Exception as ex: problems[r["yahoo"]]="parse:"+str(ex)[:120]
    try:
        raw=yf.download(names,period="20mo",interval="1d",auto_adjust=True,
                        group_by="ticker",threads=True,progress=False,timeout=25)
        extract(raw,records)
    except Exception as ex:
        for r in records: problems[r["yahoo"]]="batch:"+str(ex)[:120]
    return found,problems

def benchmarks():
    b={}
    for market,sym in (("US","^GSPC"),("KOSPI","^KS11"),("KOSDAQ","^KQ11")):
        try:
            f=normalize(yf.download(sym,period="20mo",auto_adjust=True,progress=False,timeout=25))
            if len(f)>=20: b[market]=f
        except Exception as e:
            LOG.warning("Index %s Yahoo error: %s",sym,str(e)[:120])
    for m,s in (("KOSPI","KS11"),("KOSDAQ","KQ11")):
        if m in b: continue
        try:
            import FinanceDataReader as fdr
            f=normalize(fdr.DataReader(s,(pd.Timestamp.now()-pd.Timedelta(days=650)).strftime("%Y-%m-%d")))
            if len(f)>=20: b[m]=f
        except Exception as e: LOG.warning("FDR index %s error: %s",s,str(e)[:120])
    return b

def fallback_kr(record):
    try:
        import FinanceDataReader as fdr
        f=normalize(fdr.DataReader(record["symbol"],(pd.Timestamp.now()-pd.Timedelta(days=650)).strftime("%Y-%m-%d")))
        return f if len(f)>=20 else None
    except Exception: return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--shard",type=int,required=True)
    ap.add_argument("--shards",type=int,default=16)
    args=ap.parse_args()
    if not (0<=args.shard<args.shards): raise ValueError("invalid shard")
    out=Path("output")/f"shard_{args.shard:02d}"
    out.mkdir(parents=True,exist_ok=True)
    listing,failed=collect_universe()
    chosen=listing[[shard_of(r.region,r.symbol,args.shards)==args.shard for r in listing.itertuples()]].copy()
    chosen.to_csv(out/"universe.csv",index=False,encoding="utf-8-sig")
    b=benchmarks()
    scores=[];coverage=[]
    elig=chosen[chosen.screen_eligible].to_dict("records")
    for _,r in chosen[~chosen.screen_eligible].iterrows():
        coverage.append({**r.to_dict(),"status":"excluded_security_class","bars":0,"source":""})
    for off in range(0,len(elig),40):
        part=elig[off:off+40]
        fetched,problems=download_batch(part)
        for r in part:
            sym=r["yahoo"];f=fetched.get(sym)
            source="yfinance" if f is not None else ""
            if f is None and r["region"]=="KR":
                f=fallback_kr(r)
                if f is not None: source="FinanceDataReader"
            if f is None:
                coverage.append({**r,"status":problems.get(sym,"missing_prices"),"bars":0,"source":source})
                continue
            key="US" if r["region"]=="US" else r["exchange"]
            if key not in b:
                coverage.append({**r,"status":"missing_benchmark","bars":len(f),"source":source})
                continue
            try:
                rec=score_one(r["symbol"],r["region"],f,b[key],percentile=None)
                if rec is None:
                    coverage.append({**r,"status":"insufficient_aligned_history","bars":len(f),"source":source})
                    continue
                rec.update(company_name=r["name"],exchange=r["exchange"],
                           source=source,download_symbol=sym)
                scores.append({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
                               for k,v in rec.items()})
                coverage.append({**r,"status":"scored","bars":len(f),"source":source})
            except Exception as e:
                LOG.warning("Scoring %s failed: %s",sym,str(e)[:150])
                coverage.append({**r,"status":"score_error:"+str(e)[:160],"bars":len(f),"source":source})
        LOG.info("shard=%d progress=%d/%d scored=%d",args.shard,min(off+40,len(elig)),len(elig),len(scores))
    pd.DataFrame(coverage).to_csv(out/"coverage.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(scores).to_csv(out/"scores.csv",index=False,encoding="utf-8-sig")
    meta={"shard":args.shard,"shards":args.shards,"listed":len(chosen),
          "eligible":len(elig),"scored":len(scores),"listing_errors":failed,
          "benchmarks":sorted(b),"complete_listing":not bool(failed)}
    (out/"meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    LOG.info("Shard %d finished: %s",args.shard,meta)
    if failed:
        raise RuntimeError("Incomplete exchange listings: "+str(failed))
    if len(scores)==0:
        raise RuntimeError("No scored symbols in shard: inspect coverage.csv")

if __name__=="__main__": main()
