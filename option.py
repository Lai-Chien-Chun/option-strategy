from ast import main
import pandas as pd
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from collections import Counter
import numpy as np
from scipy.stats import norm
from tomlkit import date
import os

class EWMAVolatility:
    def __init__(self, lambda_=0.94, init_window=60):
        self.lambda_ = lambda_
        self.init_window = init_window
        self.sigma2 = None

    def fit(self, df):
        """
        計算 EWMA 每日波動率，回傳 Series 對齊 df.index
        df 必須包含 "log_return"
        """
        returns = df["log_return"].values

        # 初始 variance
        self.sigma2 = np.var(returns[:self.init_window], ddof=1)

        # 前 init_window 天填 NaN
        sigma_daily = [np.nan] * self.init_window

        # EWMA 遞迴
        for r in returns[self.init_window:]:
            self.sigma2 = self.lambda_ * self.sigma2 + (1 - self.lambda_) * r**2
            sigma_daily.append(np.sqrt(self.sigma2))

        return pd.Series(sigma_daily, index=df.index)

    @staticmethod
    def annualize(sigma_daily):
        return sigma_daily * np.sqrt(252)

    @staticmethod
    def to_vix_like(sigma_daily, days_forward=30, calib_factor=4.2):
        """
        將每日 EWMA 波動率轉成近似 VIXTWN (%)
        """
        # 轉成 30天 forward 波動率
        sigma_30d = sigma_daily * np.sqrt(days_forward)
        # 轉百分比並乘校準係數
        return sigma_30d * calib_factor

class BlackScholes:
    @staticmethod
    def price(S, K, r, q, T, sigma_annual, option_type="call"):
        """
        Black-Scholes price with continuous dividend yield
        
        Parameters
        ----------
        S : float
            Spot price 標的價格
        K : float
            Strike price 履約價格
        r : float
            Risk-free rate (annual, continuous compounding) 無風險利率
        q : float
            Dividend yield (annual, continuous compounding) 現金股利殖利率
        T : float
            Time to maturity (in years)
        sigma_annual : float
            Annual volatility 波動率
        option_type : str
            "call" or "put"
        """
        
        if T <= 0:
            # Expired option
            if option_type == "call":
                return max(S - K, 0)
            else:
                return max(K - S, 0)

        sigma = sigma_annual
        
        d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option_type.lower() == "call":
            return (S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
        
        elif option_type.lower() == "put":
            return (K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1))
        
        else:
            raise ValueError("option_type must be 'call' or 'put'")
        
# Convert ROC date (e.g. 89/01/04 -> 2000/01/04)
def roc_to_gregorian(roc_date):
    y, m, d = roc_date.split('/')
    year = int(y) + 1911
    return f"{year}-{m}-{d}"

def init_data(tw_index_file, cash_yield_file, bond_yield_file):
    # read stock index data
    df = pd.read_csv(tw_index_file)
    df['Date'] = df['Date'].astype(str).str.strip().apply(roc_to_gregorian)
    df['Date'] = pd.to_datetime(df['Date'])

    # clean number columns
    for col in ['Open', 'High', 'Low', 'Close']:
        df[col] = df[col].astype(str).str.replace(",", "").astype(float)

    # read cash yield data
    cash_df = pd.read_csv(cash_yield_file)
    cash_df['date'] = pd.to_datetime(cash_df['date'])
    cash_df = cash_df.rename(columns={'date': 'Date', 'yield': 'cash_yield'})

    # 如果 yield 可能有空白字串
    cash_df['cash_yield'] = cash_df['cash_yield'].astype(float)

    # read 10y bond yield data
    bond_df = pd.read_csv(bond_yield_file)
    bond_df['date'] = pd.to_datetime(bond_df['date'])
    bond_df = bond_df.rename(columns={'date': 'Date', 'yield': 'bond_yield'})

    bond_df['bond_yield'] = bond_df['bond_yield'].astype(float)

    # merge cash_df and bond_df to df
    df = df.merge(cash_df[['Date', 'cash_yield']], on='Date', how='left')
    df = df.merge(bond_df[['Date', 'bond_yield']], on='Date', how='left')

    #check if exist NaN, fill with avg of previous row and next row value
    for col in ['cash_yield', 'bond_yield']:
        df[col] = df[col].interpolate(method='linear').bfill().ffill()

    df["log_return"] = np.log(df["Close"] / df["Close"].shift(1))
    df_vol = df.dropna(subset=["log_return"]).reset_index(drop=True)

    return df_vol


def cal_option_result(df, duration, sp_ratio, bc_ratio):
    
    T = duration / 252   # time to maturity in years
    
    sp_win_count_SL = 0
    sp_win_count_final = 0
    bp_win_count = 0
    bc_win_count = 0
    sc_win_count = 0

    results = []

    for i in range(len(df)):
        S = df.iloc[i]["Close"]
        sigma = df.iloc[i]["hv"]
        risk_free_rate = df.iloc[i]["bond_yield"] / 100  # Convert percentage to decimal
        cash_yield = df.iloc[i]["cash_yield"] / 100  # Convert percentage to decimal

        #skip if sigma is NaN (e.g. first 60 days)
        if np.isnan(sigma):
            continue

        put_K = sp_ratio * S  # ATM
        put_price = BlackScholes.price(S, put_K, risk_free_rate, cash_yield, T, sigma, "put")
        
        call_K = bc_ratio * S  # OTM
        call_price  = BlackScholes.price(S, call_K, risk_free_rate, cash_yield, T, sigma, "call")

        # realized payoff after duration days
        if i + duration < len(df):
            count_days = duration
            days_to_expire = 0

            for j in range(1, duration + 1):
                days_to_expire = (df.iloc[i + j]["Date"].date() - df.iloc[i]["Date"].date()).days
                if days_to_expire >= duration + 2*duration/5: # add weekend
                    count_days = j
                    break

            # Skip observations where the actual holding period is much longer than intended (e.g. due to holidays)
            if days_to_expire >= duration + 2*duration/5 + 2:
                continue

            S_T = df.iloc[i + count_days]["Close"]
            S_lowest = df.iloc[i + 1 : i + count_days + 1]["Close"].min()           # minimum of the following n days
            S_hightest = df.iloc[i + 1 : i + count_days + 1]["Close"].max()

            sp_earn = round(put_price, 2)
            bp_earn = 0 - sp_earn
            sc_earn = round(call_price, 2)
            bc_earn  = 0 - sc_earn
            sp_earn_final = sp_earn
            sp_earn_SL = sp_earn

            # sell put (stop loss)
            if S_lowest > put_K:
                sp_win_count_SL += 1
            else:
                sp_earn_SL = sp_earn - 300
            # sell put final
            if S_T >= put_K:
                sp_win_count_final += 1
            else:
                sp_earn_final = (S_T - put_K) + sp_earn

            if S_T < put_K:
                bp_win_count += 1
                bp_earn += (put_K - S_T)

            # sell call final
            if S_T <= call_K:
                sc_win_count += 1
            else:
                sc_earn = (call_K - S_T) + sc_earn

            if S_T > call_K:
                bc_win_count += 1
                bc_earn += (S_T - call_K)
            
        else:
            S_T = S
            continue

        results.append({
            "date": df.iloc[i]['Date'].date(),
            "open": df.iloc[i]["Open"],
            "close": df.iloc[i]["Close"],
            "high": df.iloc[i]["High"],
            "low": df.iloc[i]["Low"],
            "final": S_T,
            "sigma": round(sigma, 4), # sigma,
            "bond_yield%": round(df.iloc[i]["bond_yield"], 2), #risk_free_rate,
            "cash_yield%": round(df.iloc[i]["cash_yield"], 2), #cash_yield,
            "duration": days_to_expire,
            "trading_days": count_days,
            "call_strike": round(call_K, 2), #call_K,
            "call_price": round(call_price, 2), #call_price,
            "bc_earn": round(bc_earn, 2),
            "bc_win%": round(bc_win_count / (len(results) + 1), 4), #bc_win_count / (len(results) + 1),
            "sc_earn": round(sc_earn, 2),
            "sc_win%": round(sc_win_count / (len(results) + 1), 4),
            "put_strike": round(put_K, 2),
            "put_price": round(put_price, 2),
            "sp_SL_win%": round(sp_win_count_SL / (len(results) + 1), 4),
            "sp_earn_SL": round(sp_earn_SL, 2),
            "sp_final_win%": round(sp_win_count_final / (len(results) + 1), 4),
            "sp_earn_final": round(sp_earn_final, 2),
            "bp_earn": round(bp_earn, 2),
            "bp_win%": round(bp_win_count / (len(results) + 1), 4)
        })
    bt = pd.DataFrame(results)
    return bt

def main():
            
    df = init_data("twse_index.csv", "taiwan_cash_yield_daily.csv", "taiwan_10y_bond_yield_daily.csv")
    
    # 初始化 EWMA
    window = 60
    ewma = EWMAVolatility(lambda_=0.94, init_window=window)

    # 計算 EWMA 日波動率
    sigma_daily = ewma.fit(df)

    # 轉成近似 VIXTWN
    df["hv"] = EWMAVolatility.to_vix_like(
        sigma_daily,
        days_forward=30,
        calib_factor=4.2   # 根據歷史比對調整
    )

    summary = []
    if not os.path.exists("option_strategy_result"):
        os.makedirs("option_strategy_result")

    # take 0.005 as interleave from 1 to 1.1
    for duration in [5, 10, 15, 20]:
        for ratio in np.arange(0.00, 0.105, 0.005):
            sp_ratio = 1 - ratio
            bc_ratio = 1 + ratio
            bt = cal_option_result(df, duration, sp_ratio, bc_ratio)
            summary.append({
                "duration": duration,
                "ratio": ratio,
                "bc_win%": round(bt["bc_win%"].iloc[-1] * 100, 2),
                "bc_earn": round(bt["bc_earn"].mean(), 2),
                "sc_win%": round(bt["sc_win%"].iloc[-1] * 100, 2),
                "sc_earn": round(bt["sc_earn"].mean(), 2),
                "bp_win%": round(bt["bp_win%"].iloc[-1] * 100, 2),
                "bp_earn": round(bt["bc_earn"].mean(), 2),
                "sp_SL_win%": round(bt["sp_SL_win%"].iloc[-1] * 100, 2),
                "sp_SL_earn": round(bt["sp_earn_SL"].mean(), 2),
                "sp_final_win%": round(bt["sp_final_win%"].iloc[-1] * 100, 2),
                "sp_final_earn": round(bt["sp_earn_final"].mean(), 2)
            })

            bt.to_csv(f"option_strategy_result/duration_{duration}_ratio_{ratio}_result.csv", index=False)
            print(f"Completed duration={duration}, ratio={ratio:.3f} | "
                  f"BC Win%: {bt['bc_win%'].iloc[-1]:.2%} BC Earn: {bt['bc_earn'].mean():.2f} | "
                  f"SC Win%: {bt['sc_win%'].iloc[-1]:.2%} SC Earn: {bt['sc_earn'].mean():.2f} | "
                  f"BP Win%: {bt['bp_win%'].iloc[-1]:.2%} BP Earn: {bt['bp_earn'].mean():.2f} | "
                  f"SP Win%: {bt['sp_final_win%'].iloc[-1]:.2%} SP Earn: {bt['sp_earn_final'].mean():.2f} | "
                  f"SP Win(SL)%: {bt['sp_SL_win%'].iloc[-1]:.2%} SP Earn(SL): {bt['sp_earn_SL'].mean():.2f}")

    summary = pd.DataFrame(summary)
    summary.to_csv("option_strategy_result/summary.csv", index=False)

if __name__ == "__main__":
    main()