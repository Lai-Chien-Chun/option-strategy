# option 說明

## 1. 專案目的

option.py 用於統計台指選擇權 (TAIEX Options) 在 2000 年至 2026 年期間，不同履約價距離與到期天數條件下的理論價格與策略勝率。此程式主要用於研究不同選擇權策略在長期歷史資料下的統計表現，包含勝率與平均獲利。

---

## 2. 模型設定

### 2.1 選擇權定價模型

本程式使用 Black-Scholes Model 計算選擇權理論價格。

模型假設：

- 選擇權為歐式選擇權 (European Option)
- 無交易成本
- 無滑價 (slippage)
- EWMA 計算波動率

Black-Scholes 用於計算：

- Call option price
- Put option price

---

### 2.2 回測資料範圍

統計資料範圍：

2000 年 ～ 2026 年

使用台灣指數歷史價格資料模擬不同履約價與到期日條件下的選擇權策略。

---

### 2.3 保證金假設

回測過程中假設：

保證金永遠足夠，不會發生斷頭。

原因為本研究主要目的是策略統計分析，因此不考慮資金限制。

---

### 2.4 實際交易風控假設

在實際操作時，會透過停損機制控制風險，使保證金維持在安全水位。

實際交易假設：

維持保證金比例 > 75%

若保證金比例低於門檻，則會進行停損平倉。

此部分目前尚未納入回測模型。

---

## 3. Summary 欄位說明

summary 表格為回測結果的統計資料。

每一列代表：

特定 duration 與 ratio 條件下的策略統計結果。

內容包含：

- 勝率
- 平均獲利

---

## 4. 基本欄位

### duration

duration 表示選擇權距離到期日的交易天數。

例如：

5
10
20

代表不同的到期時間。

---

### ratio

ratio 表示履約價與現價之間的價差百分比。

計算方式：

ratio = (strike - spot) / spot

例如：

| ratio | 意義               |
| ----- | ------------------ |
| -0.05 | 履約價低於現價 5%  |
| 0     | ATM (at-the-money) |
| 0.05  | 履約價高於現價 5%  |

---

## 5. 策略統計欄位

### Buy Call

bc_win%

表示在指定 ratio 履約價條件下，Buy Call 持有至到期的勝率。

計算方式：

win_rate = 獲利交易數 / 總交易數

bc_earn

表示 Buy Call 持有至到期的平均獲利。

profit = settlement_price - strike - premium

---

### Sell Call

sc_win%

表示 Sell Call 持有至到期的勝率。

當以下條件成立時視為獲利：

premium > max(settlement_price - strike, 0)

sc_earn

Sell Call 持有至到期的平均獲利：

profit = premium - max(settlement_price - strike, 0)

---

### Buy Put

bp_win%

Buy Put 持有至到期的勝率。

win_rate = 獲利交易數 / 總交易數

bp_earn

Buy Put 持有至到期的平均獲利：

profit = strike - settlement_price - premium

---

### Sell Put（含停損）

sp_SL_win%

SL = Stop Loss

策略規則：

若合約存續期間任一天指數價格跌破履約價 (index_price < strike)，則立即停損平倉。

sp_SL_win% 表示在此停損機制下 Sell Put 的勝率。

sp_SL_earn

Sell Put 在停損策略下的平均獲利。

---

### Sell Put（持有至結算）

sp_final_win%

Sell Put 不設定停損，持有至到期結算。

當以下條件成立時視為獲利：

settlement_price >= strike

sp_final_earn

Sell Put 持有至到期的平均獲利：

profit = premium - max(strike - settlement_price, 0)

---

## 6. 回測流程

回測邏輯如下：

對每一交易日：

1. 取得當日指數價格  
2. 遍歷不同 duration  
3. 計算對應到期日  
4. 遍歷不同 ratio  
5. 計算履約價 strike  
6. 使用 Black-Scholes 計算選擇權理論價格  
7. 模擬不同策略：

- Buy Call
- Sell Call
- Buy Put
- Sell Put

最後統計：

- 勝率
- 平均獲利
- 策略表現

---

## 7. TODO

未來需要加入更接近實際市場的條件。

### 7.1 使用實際波動率

目前：

使用固定 volatility

未來：

抓取每日 VIxTWN

並使用 implied volatility 進行定價。

---

### 7.2 使用實際選擇權市場價格

目前：

使用 Black-Scholes 理論價格

未來：

改為使用市場實際成交價格。

資料來源：

- 台灣期貨交易所
- 選擇權歷史資料

---

### 7.3 保證金與維持率模擬

目前：

假設保證金永遠足夠。

未來應加入：

Initial Margin  
Maintenance Margin

並模擬：

若維持率低於門檻  
則強制平倉。