## TradingView 比較検証サンプル: MA クロス戦略

このドキュメントは、シンプルな移動平均クロス戦略（`examples/sample_strategy_ma_cross.py`）を用いて、  
TradingView と `tv-backtest-api` のバックテスト結果を比較するための **一連の手順サンプル**です。

---

### 前提

- TradingView 上で MA クロス戦略（短期 / 長期移動平均）を実装済みであること。
- `tv-backtest-api` がローカルで起動済みであること（`docs/setup_and_run.md` を参照）。
- `examples/sample_strategy_ma_cross.py` を戦略として登録済みであること。

---

### 1. TradingView で条件を固定する

1. 対象シンボル例: `BTCUSDT`
2. 時間足例: `1h`
3. バックテスト期間例: `2023-01-01` 〜 `2023-12-31`
4. 戦略パラメータ例:
   - `fast`: 9
   - `slow`: 21
5. 手数料・スリッページ・初期残高・ポジションサイズなど、  
   **エンジン側でも再現可能なパラメータを明確にメモ**しておく。

TradingView の Strategy Tester 画面で、上記条件を設定した状態の結果（損益、勝率、PF、トレード数、最大 DD など）を確認します。

---

### 2. TradingView 結果を JSON として保存する

1. TradingView の Strategy Tester 画面から、必要なメトリクスを読み取る。
2. 次のような JSON を作成し、`validation/tradingview_results/ma_cross_BTCUSDT_1h_2023.json` として保存する。

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

3. `metrics` の値は TradingView 側に表示されている数値を利用し、  
   単位（通貨 or 率）、桁数、丸め方をわかる範囲でメモに残す。

詳細な保存ルールは `validation/tradingview_results/README.md` を参照してください。

---

### 3. tv-backtest-api で同条件の Backtest を実行する

1. 対応する CSV データセット（例: `BTCUSDT` の 1h 足、2023 年分）を `datasets` として登録する。
2. `examples/sample_strategy_ma_cross.py` を `strategies` として登録する（すでに登録済みなら流用）。
3. TradingView 側の条件に合わせて、次のように `POST /backtests` を実行する。

   ```bash
   curl -X POST "http://localhost:8000/backtests" \
     -H "Content-Type: application/json" \
     -d '{
       "dataset_id": 1,
       "strategy_id": 1,
       "params": {
         "fast_window": 9,
         "slow_window": 21
       },
       "settings": {
         "initial_capital": 100000
       }
     }'
   ```

4. 実行結果（`/backtests/{id}/result` の JSON）をファイルに保存する。

   例:

   ```bash
   curl "http://localhost:8000/backtests/1/result" > validation/engine_results/ma_cross_BTCUSDT_1h_2023_engine.json
   ```

   ※ `validation/engine_results/` ディレクトリは任意ですが、TradingView 側 JSON と対応が分かる場所に保存してください。

---

### 4. `scripts/compare_with_tradingview.py` を実行する

TradingView の JSON とエンジン結果の JSON を比較します。

```bash
python scripts/compare_with_tradingview.py \
  --tv validation/tradingview_results/ma_cross_BTCUSDT_1h_2023.json \
  --engine validation/engine_results/ma_cross_BTCUSDT_1h_2023_engine.json
```

実行すると、`net_profit` / `profit_factor` / `win_rate` / `trades` / `max_drawdown` の  
TradingView vs Engine 差分がパーセント付きで表示されます。

---

### 5. 差分を確認し、原因を検討する

- 各メトリクスの差分がどの程度かを確認し、許容範囲かどうかを判断します。
- 大きな差分がある場合は、以下を重点的に見直します。
  - 価格データ（OHLCV）の一致
  - 手数料・スリッページ・初期残高・ポジションサイズ
  - エントリー / エグジット条件（バーのどの価格を使うか、signal のタイミングなど）
  - ポジションの持ち方（常時フルポジション / フラット期間の扱い）
- 検証結果や差分理由は `docs/validation_checklist.md` の該当行（1-1〜1-6 など）に  
  実施日・結果・メモとして記録してください。

