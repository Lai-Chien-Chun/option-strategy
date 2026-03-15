import requests as r
import pandas as pd
from datetime import date

def get_stock_data(start_year, start_month, end_year, end_month):
    # Build monthly date list
    start_date = str(date(start_year, start_month, 1))
    end_date = str(date(end_year, end_month, 1))
    month_list = pd.date_range(start_date, end_date, freq='MS').strftime("%Y%m%d").tolist()
    
    all_data = []
    
    for month in month_list:
        url = f"https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=json&date={month}"
        res = r.get(url)
        stock_json = res.json()
        
        # Skip if no data
        if "data" not in stock_json or stock_json["data"] is None:
            continue
        
        stock_df = pd.DataFrame(stock_json["data"])
        all_data.append(stock_df)
    
    if not all_data:
        return pd.DataFrame()  # return empty df if nothing fetched
        
    df = pd.concat(all_data, ignore_index=True)
    df.columns = ["Date", "Open", "High", "Low", "Close"]
    
    return df


# Example: fetch data from 2010 to 2025
stock = get_stock_data(2000, 1, 2026, 2)

# Show first 5 rows
print(stock.head())

# Save to CSV
stock.to_csv("twse_index.csv", index=False, encoding="utf-8-sig")
