tv-backtest-api
================

Python 戦略コードと CSV データを用いてローカルでバックテスト / 最適化を行うための FastAPI ベースのシンプルなバックエンドです。

## セットアップ

```bash
cd tv-backtest-api
python -m venv .venv
source .venv/bin/activate  # Windows の場合: .venv\Scripts\activate
pip install -r requirements.txt
```

## 開発サーバ起動

```bash
uvicorn app.main:app --reload
```

テスト実行:

```bash
pytest
```

> **既存 DB からのスキーマ更新について**
>
> 開発中は SQLite ファイルに対して手動でスキーマを変更しています（Alembic などのマイグレーションツールは未導入）。
> 新しいカラム（例: `optimization_runs.objective_metric`）を追加した場合、既存の `tv-backtest-api.db` には自動反映されません。
> 不整合を避けるため、**既存 DB を削除してから `uvicorn app.main:app --reload` で再起動し、テーブルを再作成**してください。

> **既存の Optimization 結果と profit_factor について**
>
> Optimization の result JSON（`storage/results/optimizations/*.json`）には、実行時点の metrics がそのまま保存されています。
> 今回の修正で `profit_factor` や `gross_profit` / `gross_loss` を追加しても、**過去に生成済みの JSON には自動では反映されません**。
> PF 列や PF 順のランキングを確認したい場合は、**修正後に Optimization を再実行して新しい result JSON を生成**してください。
> PF は各トレードの realized PnL（割合ベース）の合計から
> `profit_factor = gross_profit / gross_loss`（gross_loss > 0 のとき）で計算し、損失が 0 の場合は `None` として扱います。

## 目的

- ChatGPT が生成した Python 戦略コードを登録
- CSV データに対してバックテスト / 最適化を実行
- 結果を保存・閲覧できる MVP を提供

## サンプル戦略

`examples/sample_strategy_ma_cross.py` に、`close` 列を用いたシンプルな移動平均クロス戦略のサンプルを用意しています。

```bash
ls examples/
sample_strategy_ma_cross.py
```

このファイルをそのまま戦略登録 API に渡すことで動作確認ができます。

## API 実行例（curl）

以下では、サーバが `http://localhost:8000` で起動している前提とします。

### 1. CSV データセット登録

`data/sample_ohlcv.csv` などの CSV ファイル（`close` 列を含む）を用意して、次のように登録します。

```bash
curl -X POST "http://localhost:8000/datasets" \
  -F "name=sample-dataset" \
  -F "symbol=BTCUSD" \
  -F "timeframe=1h" \
  -F "file=@data/sample_ohlcv.csv"
```

レスポンス例（抜粋）:

```json
{
  "id": 1,
  "name": "sample-dataset",
  "symbol": "BTCUSD",
  "timeframe": "1h",
  "file_path": "...",
  "rows_count": 1234,
  "created_at": "2026-03-16T00:00:00"
}
```

### 2. Python 戦略登録

サンプル戦略 `examples/sample_strategy_ma_cross.py` をアップロードします。

```bash
curl -X POST "http://localhost:8000/strategies" \
  -F "name=ma-cross" \
  -F "description=Simple moving average crossover strategy" \
  -F "default_params_json={\"fast_window\": 5, \"slow_window\": 20}" \
  -F "file=@examples/sample_strategy_ma_cross.py"
```

レスポンス例（抜粋）:

```json
{
  "id": 1,
  "name": "ma-cross",
  "description": "Simple moving average crossover strategy",
  "file_path": "...",
  "default_params_json": "{\"fast_window\": 5, \"slow_window\": 20}",
  "created_at": "2026-03-16T00:00:00",
  "updated_at": "2026-03-16T00:00:00"
}
```

### 3. Backtest 実行

登録済み `dataset_id` と `strategy_id` を使ってバックテストを 1 回実行します。

```bash
curl -X POST "http://localhost:8000/backtests" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": 1,
    "strategy_id": 1,
    "params": {
      "fast_window": 5,
      "slow_window": 20
    },
    "settings": {
      "initial_capital": 1000000
    }
  }'
```

レスポンス例（抜粋）:

```json
{
  "id": 1,
  "dataset_id": 1,
  "strategy_id": 1,
  "status": "success",
  "metrics_json": "{\"net_profit\": 12345.6, \"final_equity\": 1012345.6, \"max_drawdown\": 1234.5, \"total_trades\": 10}",
  "result_path": "storage/results/backtests/1.json",
  "created_at": "2026-03-16T00:00:00",
  "finished_at": "2026-03-16T00:00:05"
}
```

### 4. Backtest 結果取得

バックテスト結果 JSON（`metrics`, `trades`, `equity_series`）を取得します。

```bash
curl "http://localhost:8000/backtests/1/result"
```

レスポンス例（抜粋）:

```json
{
  "metrics": {
    "net_profit": 12345.6,
    "final_equity": 1012345.6,
    "max_drawdown": 1234.5,
    "total_trades": 10
  },
  "trades": [
    {
      "index": 10,
      "position": 1,
      "price": 20000.0
    }
  ],
  "equity_series": [
    {
      "index": 0,
      "equity": 1000000.0
    }
  ]
}
```

### 5. Optimization 実行（Grid Search）

`search_space` に複数のパラメータ候補を指定して、単純な grid search による最適化を行います。

```bash
curl -X POST "http://localhost:8000/optimizations" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": 1,
    "strategy_id": 1,
    "search_space": {
      "fast_window": [5, 10, 15],
      "slow_window": [20, 30, 40]
    },
    "settings": {
      "initial_capital": 1000000
    },
    "objective_metric": "net_profit"
  }'
```

レスポンス例（抜粋）:

```json
{
  "id": 1,
  "dataset_id": 1,
  "strategy_id": 1,
  "status": "success",
  "best_params_json": "{\"fast_window\": 10, \"slow_window\": 30}",
  "best_score": 23456.7,
  "result_path": "storage/results/optimizations/1.json",
  "created_at": "2026-03-16T00:10:00",
  "finished_at": "2026-03-16T00:10:10"
}
```

### 6. Optimization 結果取得

Grid search の全トライアルと最良結果を取得します。

```bash
curl "http://localhost:8000/optimizations/1/result"
```

レスポンス例（抜粋）:

```json
{
  "trials": [
    {
      "params": {
        "fast_window": 5,
        "slow_window": 20
      },
      "metrics": {
        "net_profit": 10000.0
      },
      "score": 10000.0
    }
  ],
  "best_params": {
    "fast_window": 10,
    "slow_window": 30
  },
  "best_score": 23456.7,
  "objective_metric": "net_profit"
}
```

## 開発環境セットアップ

開発環境の詳細なセットアップ手順は、[docs/setup_and_run.md](docs/setup_and_run.md) を参照してください。

