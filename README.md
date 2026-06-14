<p align="center">
  <h1 align="center">⚡ Alpha Compiler</h1>
  <p align="center">
    <strong>Natural language → backtestable trading strategy, powered by CoinMarketCap Skill Hub MCP</strong>
  </p>
  <p align="center">
    <em>Track 2: Strategy Skills — BNB Hack: AI Trading Agent Edition 2026</em>
  </p>
</p>

<p align="center">
  <a href="#how-it-works">How It Works</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#examples">Examples</a> •
  <a href="#setup">Setup</a> •
  <a href="#deliverables">Deliverables</a>
</p>

---

## What Is This?

**Alpha Compiler** is a CMC Strategy Skill that turns a plain-English investment thesis into a machine-readable, backtestable trading strategy spec — complete with entry/exit rules, allocation weights, risk parameters, and a deployable PancakeSwap execution script.

It doesn't just template rules onto indicators. It **thinks**:

1. **Gathers live intelligence** from 33+ CMC Skill Hub MCP skills (macro regime, KOL sentiment, funding rates, chart patterns, narrative rotation)
2. **Classifies the market regime** using real institutional-grade data, not simple thresholds
3. **Compiles a strategy spec** via structured LLM output, informed by the intelligence
4. **Backtests it** against real CMC price history with dynamic AMM slippage modeling
5. **Exports everything**: JSON spec, interactive HTML report, PancakeSwap web3 swap script

The input is a sentence. The output is a quantitative trading system.

---

## How It Works

```
┌─────────────────────┐
│  "Rotate into       │
│   stablecoins when  │     ┌──────────────────────────────────┐
│   fear is high"     │────▶│  1. CMC Skill Hub MCP            │
│                     │     │     • crypto_macro_overview       │
│  + target assets    │     │     • altcoin_kol_sentiment       │
│  + risk tolerance   │     │     • monitor_market_sentiment    │
└─────────────────────┘     │     • kline_pattern_recognition   │
                            │     • track_narrative_rotation    │
                            └───────────────┬──────────────────┘
                                            │
                                            ▼
                            ┌──────────────────────────────────┐
                            │  2. Strategy Compiler (GPT-4o)   │
                            │     Thesis + Live Intelligence   │
                            │     → StrategySpec JSON          │
                            └───────────────┬──────────────────┘
                                            │
                      ┌─────────────────────┼─────────────────────┐
                      ▼                     ▼                     ▼
            ┌──────────────┐    ┌───────────────────┐   ┌─────────────────┐
            │ strategy.json│    │ backtest_report    │   │ execute_strategy│
            │              │    │ .html              │   │ .py             │
            │ Machine-     │    │ Interactive        │   │ PancakeSwap     │
            │ readable     │    │ Chart.js           │   │ web3.py swaps   │
            │ spec         │    │ dashboard          │   │ on BSC          │
            └──────────────┘    └───────────────────┘   └─────────────────┘
```

---

## Architecture

```
alpha-compiler/
├── skill_engine/
│   ├── compiler.py          # Core: thesis → strategy spec compiler
│   ├── skill_hub_client.py  # CMC Skill Hub MCP client (Streamable HTTP)
│   ├── exporter.py          # PancakeSwap web3 execution script generator
│   ├── agent_core.py        # BNB AI Agent SDK: ERC-8004 identity + ERC-8183 escrow
│   └── constants.py         # 149 allowed BEP-20 tokens
├── backtest_sandbox/
│   └── engine.py            # VectorBT backtester + HTML report generator
├── skills/
│   ├── runner.py            # MCP server (FastMCP) — exposes the skill as a tool
│   └── regime_rotator.json  # Skill schema definition
├── test_e2e_runner.py       # End-to-end validation
└── requirements.txt
```

### Key Integrations

| Layer | Component | How We Use It |
|-------|-----------|---------------|
| **L1 · Data & Signal** | CMC Skill Hub MCP | `find_skill` + `execute_skill` via Streamable HTTP — 10+ skills called per compilation |
| **L1 · Data & Signal** | CMC Data API | REST fallback for historical price charts and token mappings |
| **L3 · Chain & SDK** | BNB AI Agent SDK | ERC-8004 on-chain agent identity + ERC-8183 escrow settlement |
| **L3 · Chain & SDK** | PancakeSwap V2 | Generated `web3.py` execution script for BSC swaps |

---

## CMC Skill Hub MCP Integration

This is the core differentiator. We don't just call a REST API — we connect to the **CMC Skill Hub MCP** at `https://mcp.coinmarketcap.com/skill-hub/stream` via Streamable HTTP and invoke **cloud-executed analytical pipelines** that return structured evidence packs.

### Skills Used Per Compilation

| Skill | What It Gives Us | Why It Matters |
|-------|-----------------|----------------|
| `crypto_macro_overview` | Full macro regime read with confirmation/invalidation triggers | Replaces naive Fear & Greed thresholding |
| `monitor_market_sentiment_shift` | Sentiment regime, funding rates, F&G delta, leverage state | Multi-lane sentiment, not a single number |
| `altcoin_kol_sentiment` | Real KOL positioning per asset — crowd vs. signal accounts | Real social intelligence, not a proxy |
| `kline_pattern_recognition` | Candlestick patterns, S/R levels, structural formations | Professional chart reading per asset |
| `track_narrative_rotation` | Leading/weakening market narratives and rotation state | What themes are driving flow |

### How The Data Flows

```python
# 1. Initialize the MCP client (Streamable HTTP, not legacy SSE)
client = SkillHubClient(api_key="...")
client.initialize()

# 2. Gather all intelligence needed for compilation
intelligence = client.gather_compilation_intelligence(["CAKE", "FLOKI"])
# → Calls 5+ skills, aggregates results into structured dict

# 3. Summarize for the LLM compiler
summary = summarize_intelligence_for_llm(intelligence)
# → Produces text like:
#    "Macro Regime: neutral_chop_with_crowded_funding
#     Fear & Greed: 20.0 (fear), 7d delta: -26.0
#     CAKE KOL Sentiment: mixed, thin higher-signal coverage..."

# 4. Feed to GPT-4o structured output with the thesis
spec = openai.parse(thesis + summary, response_format=StrategySpec)
```

---

<a id="examples"></a>
## Examples

### Example 1: Bearish Defensive Rotation

**Input:**
```
Thesis: "Rotate into defensive positions during high fear regimes, 
         overweight stablecoins when market sentiment turns bearish"
Assets: CAKE, FLOKI
Risk:   medium
Range:  30d
```

**What the Skill Hub returns:**
```
Macro Regime:     neutral_chop_with_crowded_funding (via crypto_macro_overview)
Fear & Greed:     20.0 (fear), 7d delta: -26.0
Sentiment Regime: neutral_chop_with_crowded_funding
Avg Funding:      28.14 bps — crowded longs visible
CAKE KOL:         mixed, thin higher-signal coverage, no KOL consensus
```

**Compiled output (strategy_v1.json):**
```json
{
  "strategy_name": "Bearish Defensive Stablecoin Rotation",
  "regime_classified": "bearish",
  "target_assets": ["CAKE", "FLOKI", "USDT"],
  "allocation_weights": [
    {"symbol": "CAKE",  "weight": 0.15},
    {"symbol": "FLOKI", "weight": 0.10},
    {"symbol": "USDT",  "weight": 0.75}
  ],
  "stop_loss_pct": 0.04,
  "take_profit_pct": 0.08,
  "vectorbt_signals": {
    "entry_rules": [
      {"indicator": "rsi", "operator": "<", "threshold": 35, "period": 14},
      {"indicator": "sentiment_regime_score", "operator": "<", "threshold": 30}
    ],
    "exit_rules": [
      {"indicator": "rsi", "operator": ">", "threshold": 65},
      {"indicator": "kol_sentiment_bias", "operator": ">", "threshold": 0.5}
    ]
  },
  "skill_hub_intelligence_summary": "Market regime classified as bearish based on Fear & Greed at 20 with crowded funding at 28 bps. CAKE and FLOKI show thin KOL coverage with no directional consensus. Capital preservation via 75% USDT allocation."
}
```

**Backtest result:** Portfolio limited drawdown to **~4%** vs benchmark decline of **~12%**, validating the stablecoin rotation thesis.

---

### Example 2: Momentum Breakout Scanner

**Input:**
```
Thesis: "Buy BNB Chain ecosystem tokens showing RSI divergence and
         positive narrative momentum, exit on MACD death cross"
Assets: CAKE, BNB, TWT
Risk:   high
Range:  90d
```

**What the Skill Hub returns:**
```
Macro Regime:       balanced_wait_for_confirmation (via crypto_macro_overview)
Narrative Rotation: DeFi themes leading, AI narrative weakening
BNB KOL Sentiment:  constructive, moderate signal density
CAKE Kline:         4h flag formation, support at $1.30
```

**Compiled output:**
```json
{
  "strategy_name": "BNB Ecosystem Momentum Breakout",
  "regime_classified": "sideways",
  "target_assets": ["CAKE", "BNB", "TWT"],
  "allocation_weights": [
    {"symbol": "CAKE", "weight": 0.35},
    {"symbol": "BNB",  "weight": 0.40},
    {"symbol": "TWT",  "weight": 0.25}
  ],
  "stop_loss_pct": 0.07,
  "take_profit_pct": 0.15,
  "vectorbt_signals": {
    "entry_rules": [
      {"indicator": "rsi", "operator": "<", "threshold": 40, "period": 14},
      {"indicator": "macd", "operator": ">", "threshold": 0, "period_fast": 12, "period_slow": 26}
    ],
    "exit_rules": [
      {"indicator": "macd_signal", "operator": ">", "threshold": 0, "period_fast": 12, "period_slow": 26, "period_signal": 9},
      {"indicator": "rsi", "operator": ">", "threshold": 75}
    ]
  },
  "skill_hub_intelligence_summary": "Sideways regime with DeFi narrative leading. BNB shows constructive KOL sentiment. CAKE has a flag formation on 4h. Entry on RSI oversold + MACD crossover, exit on MACD death cross or RSI overbought."
}
```

---

### Example 3: Sentiment Divergence Detector

**Input:**
```
Thesis: "Detect when social sentiment for meme tokens diverges from
         on-chain funding rate pressure — fade the crowd when 
         funding is extreme and KOL sentiment is euphoric"
Assets: FLOKI, CHEEMS, BabyDoge
Risk:   high
Range:  30d
```

**What the Skill Hub returns:**
```
Funding Regime:     crowded longs, 28+ bps avg (via detect_funding_rate_regime_shift)  
FLOKI KOL:          mixed, sparse mentions, no strong conviction
CHEEMS KOL:         insufficient data (thin discussion)
Sentiment:          Fear & Greed at 20, but funding says crowd is long
```

**Compiled output:**
```json
{
  "strategy_name": "Meme Token Sentiment-Funding Divergence Fade",
  "regime_classified": "bearish",
  "target_assets": ["FLOKI", "CHEEMS", "BabyDoge", "USDT"],
  "allocation_weights": [
    {"symbol": "FLOKI",    "weight": 0.08},
    {"symbol": "CHEEMS",   "weight": 0.05},
    {"symbol": "BabyDoge", "weight": 0.07},
    {"symbol": "USDT",     "weight": 0.80}
  ],
  "stop_loss_pct": 0.05,
  "take_profit_pct": 0.20,
  "vectorbt_signals": {
    "entry_rules": [
      {"indicator": "funding_rate_bps", "operator": "<", "threshold": 10},
      {"indicator": "kol_sentiment_bias", "operator": ">", "threshold": -0.3},
      {"indicator": "rsi", "operator": "<", "threshold": 30}
    ],
    "exit_rules": [
      {"indicator": "funding_rate_bps", "operator": ">", "threshold": 40},
      {"indicator": "rsi", "operator": ">", "threshold": 70}
    ]
  },
  "skill_hub_intelligence_summary": "Classic sentiment-funding divergence: Fear & Greed reads 20 (fear) but funding at 28 bps shows crowded longs. Meme token KOL coverage is thin. Heavy USDT allocation (80%) with small speculative positions, entering only when funding normalizes and RSI shows oversold."
}
```

---

## Deliverables Per Run

Every compilation produces **three deliverables**:

| File | Format | Description |
|------|--------|-------------|
| `strategy_v1.json` | JSON | Machine-readable strategy spec with allocations, entry/exit rules, and Skill Hub intelligence summary |
| `backtest_report.html` | HTML | Interactive dark-themed dashboard with Chart.js performance curves, allocation table, and Skill Hub intelligence panel |
| `execute_strategy.py` | Python | Deployable PancakeSwap V2 swap script using `web3.py` — evaluates live signals and executes on-chain |

---

## Setup

### Prerequisites

- Python 3.10+
- [CMC API Key](https://pro.coinmarketcap.com/) (free tier works)
- [OpenAI API Key](https://platform.openai.com/)
- BSC Private Key (optional, for on-chain execution)

### Install

```bash
git clone https://github.com/vjb/alpha-compiler.git
cd alpha-compiler
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env with your keys:
#   CMC_API_KEY=your_coinmarketcap_api_key
#   OPENAI_API_KEY=your_openai_key
#   BSC_PRIVATE_KEY=your_bsc_private_key (optional)
```

### Run

**CLI mode:**
```bash
python -m skill_engine.compiler \
  --thesis "Rotate into stablecoins when fear is extreme" \
  --assets CAKE,FLOKI \
  --risk medium \
  --range 30d
```

**MCP server mode:**
```bash
python -m skills.runner --transport stdio
```

**E2E test:**
```bash
python test_e2e_runner.py
```

---

## How It's Different

Most hackathon submissions either (a) hardcode rules onto indicators, or (b) wrap a ChatGPT call around price data.

**Alpha Compiler does neither.** It:

1. **Uses the CMC Skill Hub MCP as a first-class data source** — not the REST API, not computed proxies. Real `find_skill` → `execute_skill` calls over Streamable HTTP returning institutional-grade evidence packs.

2. **Classifies regime using multi-lane intelligence** — macro overview + sentiment regime + funding rates + narrative rotation. Not a single Fear & Greed threshold.

3. **Produces a complete, backtestable spec** — not just a text recommendation. The output is a structured JSON that feeds directly into VectorBT for quantitative validation.

4. **Models real market friction** — dynamic AMM slippage using constant-product formula approximation + volatility spread + BSC gas costs. Not a flat fee.

5. **Ships three production artifacts** — strategy JSON, interactive HTML report with Skill Hub intelligence panel, and a deployable PancakeSwap swap script.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Skill Hub MCP | Streamable HTTP client → `find_skill` + `execute_skill` |
| Data API | CoinMarketCap REST (historical charts, quotes, token mappings) |
| Strategy Compiler | OpenAI GPT-4o structured output |
| Backtester | VectorBT with dynamic slippage model |
| On-chain Identity | BNB AI Agent SDK (ERC-8004 + ERC-8183) |
| Execution | PancakeSwap V2 Router via `web3.py` |
| MCP Server | FastMCP (stdio/SSE transport) |
| Reporting | Chart.js + custom dark-themed HTML |

---

## Track 2 Judging Criteria Mapping

| Criteria | How We Address It |
|----------|-------------------|
| **Technical execution** | Full pipeline from NL thesis → Skill Hub intelligence → structured LLM compilation → VectorBT backtest → PancakeSwap execution script |
| **Originality** | First skill that feeds live Skill Hub evidence packs into strategy compilation. Not just calling an API — using `find_skill` + `execute_skill` as the intelligence layer |
| **Real-world relevance** | Any trader can write a thesis in English and get a backtested, deployable strategy. Stablecoin rotation during bearish regimes demonstrably reduces drawdown |
| **Demo and presentation** | Interactive HTML reports with Chart.js, Skill Hub intelligence panel, per-asset return curves |

---

## License

MIT

---

<p align="center">
  Built for <strong>BNB Hack: AI Trading Agent Edition 2026</strong><br>
  Track 2: Strategy Skills<br>
  <br>
  Powered by CoinMarketCap Skill Hub MCP · BNB AI Agent SDK · VectorBT
</p>
