import numpy as np
import pandas as pd
from src.score import normalize,score_one

def bars(n):
    idx=pd.bdate_range("2025-01-01",periods=n)
    p=np.linspace(20,60,n)
    v=np.full(n,100000,dtype=float)
    v[min(n-1,45)]=350000
    return pd.DataFrame({"Open":p*.999,"High":p*1.02,
                         "Low":p*.98,"Close":p,"Volume":v},index=idx)

def test_score_bounds_and_sum():
    record=score_one("TEST","US",bars(260),bars(260),65)
    assert record is not None
    assert record["score_type"]=="REGULAR"
    weights={"trend30":30,"rs20":20,"vcp20":20,"leading20":20,"pivot10":10}
    assert all(0<=record[k]<=w for k,w in weights.items())
    assert record["total100"]==sum(record[k] for k in weights)

def test_short_history_cannot_buy():
    x=score_one("ABC","KR",bars(45),bars(45))
    assert x["score_type"]=="SHORT_HISTORY_PROXY"
    assert x["filters"]["52w_low_plus_100"] is None
    assert x["status"]=="WATCH"

def test_200_bars_does_not_verify_52_week_low():
    x=score_one("A","US",bars(210),bars(210))
    assert x["filters"]["52w_low_plus_100"] is None

def test_missing_or_unaligned_data():
    assert score_one("A","US",bars(19),bars(19)) is None
    b=bars(50);b.index+=pd.Timedelta(days=600)
    assert score_one("A","US",bars(50),b) is None
