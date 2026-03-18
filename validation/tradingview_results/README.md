## TradingView ベンチマーク結果の保存ルール

`validation/tradingview_results/` ディレクトリには、TradingView のバックテスト結果を **ベンチマーク JSON** として保存します。  
`scripts/compare_with_tradingview.py` でエンジン結果と比較する際の前提となるフォーマットです。

---

### ファイル名ルール

基本形式:

```text
<strategy>_<symbol>_<timeframe>_<year or period>.json
```

例:

- `ma_cross_BTCUSDT_1h_2023.json`
- `ma_cross_ETHUSDT_4h_2021-2023.json`

**推奨ルール**

- `strategy`: TradingView 側の戦略名 or 論理名（例: `ma_cross`、`rsi_mean_revert` など）
- `symbol`: TradingView で使用したシンボル（例: `BTCUSDT`、`BTCUSD.P`）
- `timeframe`: TradingView のチャート時間足（例: `1h`, `4h`, `1D`）
- 末尾: 主な検証期間（西暦年 or `YYYY-YYYY` など）。必要に応じて `2023_Q1` のような表記も可。

---

### JSON の必須項目

`scripts/compare_with_tradingview.py` は以下の構造を前提とします。

```json
{
  "source": "TradingView",
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "strategy": "ma_cross",
  "params": {
    "fast": 9,
    "slow": 21
  },
  "period": {
    "start": "2023-01-01",
    "end": "2023-12-31"
  },
  "metrics": {
    "net_profit": 1023.5,
    "profit_factor": 1.45,
    "win_rate": 0.52,
    "trades": 84,
    "max_drawdown": -0.12
  }
}
```

**必須キー**

- `source`: `"TradingView"` 固定推奨（どこから取得した結果か明示）
- `symbol`: シンボル名
- `timeframe`: チャート時間足
- `strategy`: 戦略名 or ロジック名
- `params`: 戦略パラメータ（キー名は TradingView 側の意味が分かるように）
- `period.start` / `period.end`: バックテスト期間（`YYYY-MM-DD` 形式推奨）
- `metrics`: 少なくとも以下 5 つを含むメトリクスオブジェクト

---

### metrics の説明

`metrics` には、TradingView 側で確認した代表的な指標をまとめます。

必須:

- `net_profit`: 期間トータル損益（通貨建て or 口座通貨建て）。  
  - TradingView 側とエンジン側で単位・基準（初期残高など）が一致するように注意してください。
- `profit_factor`: プロフィットファクター（総利益 / 総損失）。
- `win_rate`: 勝率。  
  - 0〜1 の実数（例: 0.52）を推奨。パーセント表記（52）にする場合はエンジン側も合わせること。
- `trades`: 期間中のトレード回数（エントリー数 or クローズ数、どちらに合わせるかはプロジェクト内で統一）。
- `max_drawdown`: 最大ドローダウン。  
  - 損失額（負の値） or 割合（-0.12 = -12%）など、解釈を README やコメントで明示してください。

任意（あれば追加で記録推奨）:

- `sharpe_ratio`, `sortino_ratio`, `max_consecutive_losses`, `expectancy` など、比較に使いたい指標。

---

### 注意点

- TradingView 側の UI から読み取った値を手入力する場合、**小数点以下の桁数や丸め方**に注意してください。
- エンジン側のメトリクス定義と意味がズレないよう、必要に応じて `README.md` や `docs/validation_checklist.md` に差分理由をメモしてください。
- 本ディレクトリの JSON はあくまで **検証用ベンチマーク** のため、本番運用ロジックとは別管理でも構いません。

