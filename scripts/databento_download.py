"""Download CME Globex 1-minute bars (continuous, volume roll) from Databento, one file per year.

Usage: DATABENTO_API_KEY=... python scripts/databento_download.py OUT_DIR SYMBOL [SYMBOL ...]
       (symbols like ES.v.0, NQ.v.0; years 2010-2026)

Writes OUT_DIR/<ROOT>_ohlcv1m_<YEAR>.csv.gz with columns
ts_event (UTC ISO), open, high, low, close, volume, instrument_id (changes at each roll).
The API key is only read from the environment and never written anywhere.
"""

import sys
import time
from pathlib import Path

import databento as db

out = Path(sys.argv[1])
client = db.Historical()
for sym in sys.argv[2:]:
    root = sym.split(".")[0]
    for year in range(2010, 2027):
        path = out / f"{root}_ohlcv1m_{year}.csv.gz"
        if path.exists():
            continue
        start = "2010-06-06" if year == 2010 else f"{year}-01-01"
        end = "2026-09-26" if year == 2026 else f"{year + 1}-01-01"
        for attempt in range(4):
            try:
                data = client.timeseries.get_range(
                    dataset="GLBX.MDP3", symbols=[sym], stype_in="continuous",
                    schema="ohlcv-1m", start=start, end=end,
                )
                df = data.to_df(price_type="float", pretty_ts=True)
                df = df[["open", "high", "low", "close", "volume", "instrument_id"]]
                df.index.name = "ts_event"
                df.to_csv(path, compression="gzip")
                print(f"{path.name}: {len(df)} rows", flush=True)
                break
            except Exception as e:  # noqa: BLE001
                print(f"{sym} {year} attempt {attempt + 1}: {str(e)[:120]}", flush=True)
                time.sleep(10 * (attempt + 1))
