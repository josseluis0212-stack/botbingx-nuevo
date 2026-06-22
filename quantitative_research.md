# Quantitative Research Report
## Statistical Arbitrage & Market Microstructure: An Institutional Framework for High-Frequency Crypto Scalping

---

### Abstract
This research report presents the quantitative and mathematical foundation of the high-frequency perpetual futures scalping bot implemented for the BingX VST environment. Drawing from foundational concepts in market microstructure, statistical arbitrage, and stochastic control, we outline a mathematically cohesive strategy. We detail the mechanics of Order Book Imbalance (OBI), mathematically derive the algebraic optimization for real-time Volume Weighted Average Price (VWAP) variance, analyze volatility-based exits via Average True Range (ATR), and establish an ergodic growth framework utilizing the Fractional Kelly Criterion.

---

## 1. Market Microstructure & Order Book Dynamics

Institutional high-frequency trading (HFT) operates at the level of the **Limit Order Book (LOB)**. Asset pricing at ultra-short horizons is not a random walk; rather, it is driven by order flow dynamics and liquidity asymmetries.

### 1.1 Order Flow & Order Book Imbalance (OBI)
Following the seminal work of *Cont, Kukanov, and Stoikov (2014)* on the price impact of order book events, short-term price adjustments are heavily influenced by the immediate imbalance between buy and sell pressure. We define **Order Book Imbalance (OBI)** at level $L$ of the LOB as:

$$OBI_t = \frac{V_t^{bid} - V_t^{ask}}{V_t^{bid} + V_t^{ask}}$$

where:
- $V_t^{bid}$ is the cumulative volume of active bids at level $L$ (typically Level 1 to Level 5).
- $V_t^{ask}$ is the cumulative volume of active asks at level $L$.

In crypto futures markets, OBI displays a powerful linear relationship with short-term mid-price changes, represented by:

$$\Delta P_{t+\tau} = \beta \cdot OBI_t + \epsilon_t$$

When OBI approaches $+1$, buy liquidity heavily dominates, signaling an immediate upward price impact due to aggressive market buyers sweeping the ask book. Conversely, $OBI \to -1$ signals aggressive selling pressure.

### 1.2 Order Flow Toxicity & VPIN
To protect market-making or scalping inventory from adverse selection (trading against informed institutional flow), we monitor **Volume-Synchronized Probability of Informed Trading (VPIN)**, developed by *Easley, Lopez de Prado, and O'Hara (2012)*. VPIN measures the toxicity of order flow by dividing volume into constant volume buckets $V$ and tracking trade imbalances:

$$VPIN = \frac{\sum_{\tau=1}^N |V_\tau^{Buy} - V_\tau^{Sell}|}{N \cdot V}$$

When VPIN exceeds specific historical percentiles (e.g., 90th percentile), order flow is deemed highly toxic, signaling impending liquidity drain or rapid breakout. In our scalping strategy, we mitigate toxicity risk by aligning all entries with the **200-period Exponential Moving Average (EMA)** trend filter, strictly forbidding counter-trend trades during high-volatility regimes.

---

## 2. Mathematically Optimized VWAP Mean Reversion

Volume Weighted Average Price (VWAP) is the primary benchmark used by institutional execution algorithms (e.g., JPMorgan, Goldman Sachs) to determine the fair price of an asset over a given trading day.

### 2.1 The Standard VWAP Formula
For a set of intraday trades, the VWAP is defined as:

$$VWAP = \frac{\sum_{i} P_i \cdot V_i}{\sum_{i} V_i}$$

where $P_i$ and $V_i$ represent the typical price and volume of candle $i$, respectively.

### 2.2 Algebraic Derivation of Weighted Variance
Calculating standard deviation bands around the VWAP in real-time is computationally expensive when done via traditional rolling window calculations, as it requires storing historical price points and re-evaluating the sum of squared differences:

$$\sigma_{VWAP} = \sqrt{\frac{\sum_{i} V_i \cdot (P_i - VWAP)^2}{\sum_{i} V_i}}$$

To achieve sub-millisecond execution speeds necessary for high-frequency scalping, we optimize this formula using the algebraic identity of weighted variance. 

**Derivation:**
1. Expand the squared term:
   $$(P_i - VWAP)^2 = P_i^2 - 2 \cdot P_i \cdot VWAP + VWAP^2$$

2. Substitute back into the numerator:
   $$\sum_{i} V_i \cdot (P_i - VWAP)^2 = \sum_{i} V_i \cdot \left( P_i^2 - 2 \cdot P_i \cdot VWAP + VWAP^2 \right)$$

3. Distribute the summation:
   $$= \sum_{i} V_i \cdot P_i^2 - 2 \cdot VWAP \cdot \sum_{i} V_i \cdot P_i + VWAP^2 \cdot \sum_{i} V_i$$

4. Divide by cumulative volume $V_{cum} = \sum_{i} V_i$:
   $$\sigma_{VWAP}^2 = \frac{\sum_{i} V_i \cdot P_i^2}{V_{cum}} - 2 \cdot VWAP \cdot \left( \frac{\sum_{i} V_i \cdot P_i}{V_{cum}} \right) + VWAP^2 \cdot \left( \frac{\sum_{i} V_i}{V_{cum}} \right)$$

5. Recognize that $\frac{\sum_{i} V_i \cdot P_i}{V_{cum}} = VWAP$ and $\frac{\sum_{i} V_i}{V_{cum}} = 1$:
   $$\sigma_{VWAP}^2 = \frac{\sum_{i} V_i \cdot P_i^2}{V_{cum}} - 2 \cdot VWAP^2 + VWAP^2$$
   $$\sigma_{VWAP}^2 = \frac{\sum_{i} V_i \cdot P_i^2}{\sum_{i} V_i} - VWAP^2$$

6. Take the square root:
   $$\sigma_{VWAP} = \sqrt{\frac{\sum_{i} V_i \cdot P_i^2}{\sum_{i} V_i} - VWAP^2}$$

**Execution Advantage:**
By maintaining only two cumulative sums—$\sum (Volume \cdot Price^2)$ and $\sum (Volume \cdot Price)$—we calculate the exact VWAP and standard deviation bands in $O(1)$ constant time complexity per new tick, completely eliminating rolling array memory allocation and CPU overhead!

---

## 3. Institutional 5-Minute Microstructure Momentum Pullback

### 3.1 Critical Design Decision
The strategy is not implemented as pure high-frequency market making. That would be structurally dishonest for the current infrastructure because the bot does not maintain colocated order-book queues, millisecond cancel/replace logic, or tick-by-tick signed trade reconstruction.

Instead, the institutional idea is adapted correctly:

1. Use 5-minute OHLCV to define a tradable regime.
2. Use VWAP reclaim/rejection to avoid chasing extended candles.
3. Use volume participation and candle efficiency to reject dead/noisy bars.
4. Use live order-book state as an execution and adverse-selection filter.
5. Execute entries with aggressive IOC limit orders, not floating passive limits.

### 3.2 Signal Model
For each 5-minute candle, the bot now computes:

- EMA 9/21/200 trend alignment.
- EMA 200 slope as regime direction.
- ATR percentage and rolling volatility percentile.
- Relative volume versus recent median volume.
- Candle body efficiency: `abs(close - open) / (high - low)`.
- Signed volume pressure using candle direction as a conservative proxy.
- VWAP z-score location.

Long setup:

$$Close > EMA_{200},\ EMA_9 > EMA_{21},\ Low \le VWAP,\ Close > VWAP,\ SignedVolumePressure > 0$$

Short setup:

$$Close < EMA_{200},\ EMA_9 < EMA_{21},\ High \ge VWAP,\ Close < VWAP,\ SignedVolumePressure < 0$$

The setup is rejected if volatility is too compressed, volatility is in the upper stress tail, relative volume is too weak, candle efficiency is poor, or price is too extended from VWAP.

### 3.3 Live Microstructure Gate
Before execution, the bot validates:

$$OBI = \frac{\sum BidVolume_{1..5} - \sum AskVolume_{1..5}}{\sum BidVolume_{1..5} + \sum AskVolume_{1..5}}$$

It also computes top-of-book spread and microprice:

$$Microprice = \frac{Ask \cdot BidSize + Bid \cdot AskSize}{BidSize + AskSize}$$

Rules:

- Reject entries when spread is too wide.
- Reject entries when top-of-book liquidity is too thin.
- Long requires positive OBI and positive microprice edge.
- Short requires negative OBI and negative microprice edge.

This converts order-book imbalance from a fragile standalone signal into an adverse-selection filter.

### 3.4 Execution Model
Entries use aggressive IOC limit orders:

- Long limit price: slightly above best ask.
- Short limit price: slightly below best bid.
- If BingX does not confirm an actual position after the IOC order, the bot refuses to register a local position.

This protects the system from phantom positions and stale floating orders.

### 3.5 Risk Model
The current deployed risk model remains:

- Margin per trade: 20 USDT.
- Leverage: 10x.
- Gross exposure: 200 USDT.
- Maximum simultaneous positions: 10.
- One position per pair.
- Stop loss: 4 ATR.
- Initial take profit: 2R.
- Breakeven/protected stop activates after 40% progress to target and locks 25% of target distance.
- Trailing activates after 75% progress and disables the fixed take profit.

This risk model is operationally coherent, but it is not yet statistically validated. It must pass walk-forward testing with costs before scaling.

---

## 4. Stochastic Control & Asymmetric Expectancy

A mathematically profitable trading bot requires a positive **Expectancy ($E$)** per trade. We enforce this through asymmetric volatility-based exits.

### 4.1 Volatility Scaling via Average True Range (ATR)
Instead of arbitrary percentage-based targets, we scale exits based on current market volatility using the **Average True Range (ATR)**.
- **Stop Loss (SL)**: Set at $\text{Entry Price} \pm 4.0 \times ATR$. This is deliberately wider than a naive scalping stop and must be paired with fixed exposure.
- **Take Profit (TP)**: Set at $\text{Entry Price} \pm 2R$, where $R$ is the initial stop distance.

This establishes an **asymmetric Risk-to-Reward Ratio ($R$)**:

$$R = \frac{8.0 \cdot ATR}{4.0 \cdot ATR} = 2.0$$

### 4.2 Expectancy Formula
Mathematical expectancy is given by:

$$E = (p \cdot \text{Average Win}) - ((1 - p) \cdot \text{Average Loss})$$

where $p$ is the probability of a winning trade. With $R = 2.0$, the break-even win rate is:

$$p_{breakeven} = \frac{1}{1 + R} = \frac{1}{3.0} \approx 33.3\%$$

Any win rate above $33.3\%$ can generate positive expectancy before costs. This does not guarantee profitability because fees, slippage, latency, spread, partial fills, funding, and adverse selection must be included.

---

## 5. Optimal Position Sizing & Ergodic Growth

Using the correct position size is as critical as the strategy itself. In crypto markets, excess leverage leads to immediate risk of ruin. We implement stochastic capital allocation via the **Kelly Criterion**.

### 5.1 Classical Kelly Criterion Derivation
The Kelly Criterion determines the optimal fraction of capital ($K^*$) to allocate to maximize the exponential growth rate of capital, assuming log-utility:

$$K^* = \frac{p \cdot R - (1 - p)}{R}$$

where:
- $p$ is the historical win rate of the bot.
- $R$ is the win/loss ratio (Average Win / Average Loss).

### 5.2 The Fat-Tail Problem in Crypto & Fractional Kelly
The classical Kelly formula assumes a normal distribution of returns and frictionless execution. However, cryptocurrency markets are highly **leptokurtic** (fat-tailed), displaying extreme outliers and slippage during volatile liquidations.

Applying full Kelly ($K^*$) under fat-tailed distributions results in extreme drawdowns and a high probability of capital depletion (ruin). To enforce capital preservation, we apply **Fractional Kelly**:

$$K^*_{fractional} = f \cdot K^*$$

where $f = 0.10$ (10% fractional factor).
This fractional factor acts as a risk ceiling, damping variance by $90\%$ while retaining the geometric growth characteristics of the Kelly path. Furthermore, we programmatically cap the final allocation between a strict **1% and 5% of total equity**, ensuring absolute immunity to tail-risk events.

---

## 6. Research Sources Used

This trading model is synthesized from the following academic literature and institutional research papers:

1. **Cont, R., Kukanov, A., & Stoikov, S. (2014).** *The Price Impact of Order Book Events.* **Journal of Financial Econometrics**, 12(1), 47-88. https://arxiv.org/abs/1011.6402
   - *Key takeaway:* Establishes OBI as the primary driver of high-frequency price impact in limit order books.
2. **Cartea, Á., Donnelly, R., & Jaimungal, S. (2015).** *Enhancing Trading Strategies with Order Book Signals.* SSRN / Applied Mathematical Finance. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2668277
   - *Key takeaway:* Limit-order-book imbalance can reduce adverse selection and improve execution quality when used as a state variable.
3. **Easley, D., Lopez de Prado, M. M., & O’Hara, M. (2012).** *Flow Toxicity and Liquidity in a High-Frequency World.* **The Review of Financial Studies**, 25(5), 1457-1493. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1695596
   - *Key takeaway:* Introduces VPIN to measure informed trade flow toxicity and anticipate micro-flash crashes.
4. **Andersen, T. G., & Bondarenko, O. (2014).** *Assessing Measures of Order Flow Toxicity and Early Warning Signals for Market Turbulence.* SSRN / Review of Finance. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2292602
   - *Key takeaway:* VPIN must be treated cautiously; toxicity filters can fail if they only proxy volatility or volume.
5. **Gould, M. D., & Bonart, J. (2016).** *Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book.* https://arxiv.org/abs/1512.03492
   - *Key takeaway:* Queue imbalance can predict very short-horizon price changes, but the horizon is often much shorter than 5 minutes.
6. **Bailey, D. H., & Lopez de Prado, M. M. (2014).** *The Deflated Sharpe Ratio.* https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
   - *Key takeaway:* Sharpe must be corrected for non-normality, short samples, and strategy selection bias.
7. **Bailey, D. H., Borwein, J., Lopez de Prado, M. M., & Zhu, Q. J. (2015).** *The Probability of Backtest Overfitting.* https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
   - *Key takeaway:* A strategy can look excellent due to repeated testing; estimate PBO before approving production.
8. **López de Prado, M. M.** *Advances in Financial Machine Learning.*
   - *Key takeaway:* Purged cross-validation, embargo, triple-barrier labeling, and proper financial ML validation are mandatory for non-leaky research.
9. **Cartea, Á., Jaimungal, S., & Penalva, J. (2015).** *Algorithmic and High-Frequency Trading.* **Cambridge University Press**.
   - *Key takeaway:* Foundational derivations of stochastic control and inventory risk management for market makers.
