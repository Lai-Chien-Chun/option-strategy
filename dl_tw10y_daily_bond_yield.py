#!/usr/bin/env python3
"""
Investing.com 台灣 10 年期政府公債日度殖利率爬蟲
使用 POST 請求 HistoricalDataAjax，分段請求後合併存成 CSV。
需用 curl_cffi 模擬瀏覽器以通過 Cloudflare（requests 易 403）。
"""

import re
import time
import pandas as pd
from datetime import datetime

try:
    from curl_cffi import requests as req_lib
    USE_CURL_CFFI = True
except ImportError:
    import requests as req_lib
    USE_CURL_CFFI = False

# 目標頁面（用於 Referer 與取得 curr_id/smlID）
HISTORY_PAGE_URL = "https://www.investing.com/rates-bonds/taiwan-10-year-bond-yield-historical-data"
AJAX_URL = "https://www.investing.com/instruments/HistoricalDataAjax"

# 每段請求約 20~24 筆，需分段；每段天數愈大請求次數愈少（全區間約 26 年）
CHUNK_DAYS = 90

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "text/plain, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.investing.com",
    "Referer": HISTORY_PAGE_URL,
    "Accept-Language": "en-US,en;q=0.9",
}


def get_session():
    """建立 session 並取得 cookie（必要時可先載入頁面）。"""
    s = req_lib.Session()
    s.headers.update(HEADERS)
    kw = {"timeout": 15}
    if USE_CURL_CFFI:
        kw["impersonate"] = "chrome120"
    s.get(HISTORY_PAGE_URL, **kw)
    return s


def extract_ids_from_page(session):
    """
    從歷史資料頁 HTML 擷取 curr_id 與 smlID。
    優先從 identifiers / bond 區塊找 instrument_id 與 sml（台灣 10Y: 29351, 206322）。
    """
    try:
        kw = {"timeout": 15}
        if USE_CURL_CFFI:
            kw["impersonate"] = "chrome120"
        r = session.get(HISTORY_PAGE_URL, **kw)
        r.raise_for_status()
        html = r.text
        # 頁面 JSON 中 "identifiers":{"instrument_id":"29351","sml":206322,...}
        m = re.search(r'"identifiers"\s*:\s*\{\s*"instrument_id"\s*:\s*"(\d+)"\s*,\s*"sml"\s*:\s*(\d+)', html)
        if m:
            return m.group(1), m.group(2)
        # 備援: instrument_id 與 smlID
        m = re.search(r'"instrument_id"\s*:\s*"(\d+)"', html)
        curr_id = m.group(1) if m else None
        m = re.search(r'"sml"\s*:\s*(\d+)', html)
        smlID = m.group(1) if m else curr_id
        if curr_id and smlID:
            return curr_id, smlID
    except Exception as e:
        print(f"Warning: could not extract IDs from page: {e}")
    # 台灣 10 年期公債已知 ID（instrument_id=29351, sml=206322）
    return "29351", "206322"


def date_to_mdy(d):
    """datetime/date -> MM/DD/YYYY"""
    if hasattr(d, "strftime"):
        return d.strftime("%m/%d/%Y")
    return d


def fetch_one_chunk(session, curr_id, smlID, st_date, end_date):
    """
    對 HistoricalDataAjax 送一次 POST，回傳該區間的 HTML 表格片段。
    """
    payload = {
        "curr_id": curr_id,
        "smlID": smlID,
        "header": "Taiwan 10-Year Bond Yield Historical Data",
        "st_date": date_to_mdy(st_date),
        "end_date": date_to_mdy(end_date),
        "interval_sec": "Daily",
        "sort_col": "date",
        "sort_ord": "DESC",
        "action": "historical_data",
    }
    kw = {"timeout": 15}
    if USE_CURL_CFFI:
        kw["impersonate"] = "chrome120"
    r = session.post(AJAX_URL, data=payload, **kw)
    r.raise_for_status()
    return r.text


def parse_html_table(html):
    """
    解析 Ajax 回傳的 HTML 表格，回傳 DataFrame 欄位: date, yield。
    表格欄位通常為 Date, Price (即殖利率), Open, High, Low, Vol., Change %
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return pd.DataFrame()

    rows = []
    thead = table.find("thead")
    if thead:
        headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    else:
        headers = []

    tbody = table.find("tbody")
    if not tbody:
        return pd.DataFrame()

    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        row = [c.get_text(strip=True) for c in cells]
        if len(row) >= 2:
            # 第一欄日期，第二欄通常為 Price（殖利率）
            date_str = row[0]  # e.g. "Feb 28, 2026"
            try:
                dt = pd.to_datetime(date_str)
                date_out = dt.strftime("%Y-%m-%d")
            except Exception:
                date_out = row[0]
            # 殖利率：移除逗號後轉數字
            yield_str = row[1].replace(",", "")
            try:
                y = float(yield_str)
            except ValueError:
                continue
            rows.append({"date": date_out, "yield": y})

    return pd.DataFrame(rows)


def generate_date_chunks(start_date, end_date, chunk_days=CHUNK_DAYS):
    """產生 (st, end) 日期區間，供分段 POST。"""
    from datetime import timedelta

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    chunks = []
    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=chunk_days), end)
        chunks.append((current, chunk_end))
        current = chunk_end
    return chunks


def fetch_full_range(session, curr_id, smlID, start_date, end_date, chunk_days=CHUNK_DAYS):
    """
    分段 POST 請求並合併結果，依日期排序、去重。
    """
    chunks = generate_date_chunks(start_date, end_date, chunk_days)
    all_dfs = []
    for i, (st, ed) in enumerate(chunks):
        try:
            html = fetch_one_chunk(session, curr_id, smlID, st, ed)
            df = parse_html_table(html)
            if not df.empty:
                all_dfs.append(df)
                print(f"  Chunk {i+1}/{len(chunks)}: {date_to_mdy(st)} ~ {date_to_mdy(ed)} -> {len(df)} rows")
        except Exception as e:
            print(f"  Chunk {i+1} failed: {e}")
        time.sleep(0.5)
    if not all_dfs:
        return pd.DataFrame()
    merged = pd.concat(all_dfs, ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    merged = merged.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    return merged


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Investing.com 台灣 10 年公債殖利率爬蟲 (POST)")
    parser.add_argument("--start", default="2000-01-01", help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="2026-03-01", help="結束日期 YYYY-MM-DD")
    parser.add_argument("--csv", default="taiwan_10y_bond_yield_daily.csv", help="輸出 CSV 路徑")
    parser.add_argument("--test-feb2026", action="store_true", help="僅先抓 2026/2 月資料測試")
    args = parser.parse_args()

    session = get_session()
    curr_id, smlID = extract_ids_from_page(session)
    print(f"Using curr_id={curr_id}, smlID={smlID}")

    if args.test_feb2026:
        print("Test: fetching February 2026 only...")
        start_date = "2026-02-01"
        end_date = "2026-03-01"
    else:
        start_date = args.start
        end_date = args.end
        print(f"Fetching full range: {start_date} to {end_date} (chunked every {CHUNK_DAYS} days)")

    df = fetch_full_range(session, curr_id, smlID, start_date, end_date)
    if df.empty:
        print("No data retrieved. Check IDs and date range.")
        return

    df.to_csv(args.csv, index=False)
    print(f"Saved {len(df)} rows to {args.csv}")
    print(df.head(10).to_string())
    print("...")
    print(df.tail(5).to_string())


if __name__ == "__main__":
    main()
