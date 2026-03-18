# tv-backtest-api セットアップ & 起動手順（Ubuntu / WSL 想定）

このドキュメントでは、Ubuntu / WSL 環境で `tv-backtest-api` をセットアップし、
FastAPI バックエンドと Streamlit フロントエンドを起動する手順を説明します。

---

## 前提条件

以下がインストールされていることを前提とします。

- Python 3.10+
- python3-venv
- python3-pip

Ubuntu / WSL の場合:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

## 1. Python 仮想環境の作成

リポジトリのルートディレクトリ（`tv-backtest-api` フォルダ）に移動し、Python 仮想環境を作成します。

```bash
# プロジェクトルートに移動
cd tv-backtest-api

# 仮想環境作成
python3 -m venv .venv
```

---

## 2. 仮想環境の有効化

作成した仮想環境を有効化します。

```bash
source .venv/bin/activate
```

プロンプトの先頭に `(.venv)` が付いていれば有効化されています。

---

## 3. 依存ライブラリのインストール

`requirements.txt` に定義された依存ライブラリをインストールします。

```bash
pip install -r requirements.txt
```

---

## 4. FastAPI API サーバーの起動

FastAPI ベースのバックエンド API サーバーを uvicorn で起動します。

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API ベース URL の例: `http://localhost:8000`
- ヘルスチェック: `http://localhost:8000/health`

このコマンドはターミナルを占有するため、**別のタブ / ウィンドウ** で次のステップを実行してください。

---

## 5. Streamlit フロントエンドの起動

別ターミナルで同じ仮想環境を有効化し、Streamlit アプリを起動します。

```bash
cd tv-backtest-api
source .venv/bin/activate
streamlit run frontend/streamlit_app.py --server.port 8501
```

---

## 6. ブラウザで開く URL

ブラウザで以下の URL を開き、MVP フロントエンドにアクセスします。

- Streamlit フロントエンド: `http://localhost:8501`

フロントエンドから呼び出す API ベース URL は、デフォルトで `http://localhost:8000` に設定されています（サイドバーから変更可能です）。

---

## 7. 次回起動時の簡易手順

次回以降、仮想環境と依存ライブラリがすでに準備済みであれば、以下の手順だけで再起動できます。

```bash
# ターミナル1: API サーバー
cd tv-backtest-api
source .venv/bin/activate
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
# ターミナル2: Streamlit フロントエンド
cd tv-backtest-api
source .venv/bin/activate
streamlit run frontend/streamlit_app.py --server.port 8501
```

ブラウザで `http://localhost:8501` を開けば利用開始できます。

---

## 8. 検証チェックリスト

自動売買 bot のパラメータ研究用途として本ツールをどこまで信頼できるかを確認するための検証項目は、`docs/validation_checklist.md` にまとめています。  
運用前 / 大きな改修後は、同ドキュメントのチェックリストに沿って検証を実施してください。

TradingView のバックテスト結果をベンチマークとして保存する場合は、`validation/tradingview_results/` 配下に JSON 形式で保存し、  
`scripts/compare_with_tradingview.py` を用いてエンジン出力とのメトリクス差分を確認してください。

---

## 9. 組み込みストラテジー（builtin）の復元

`strategies/` 配下には、Pine Script から Python 化した実践用ストラテジーなどを配置できます。

- 定義ファイル: `strategies/manifest.json`
- 本体コード: `strategies/builtins/*.py`

DB を新規作成したあと、組み込みストラテジーを登録するには以下を実行します。

```bash
cd tv-backtest-api
source .venv/bin/activate

python -m app.scripts.seed_builtin_strategies
```

このコマンドは以下を行います。

- `Base.metadata.create_all(bind=engine)` を実行し、DB やテーブルが存在しない場合でも作成する
- `strategies/manifest.json` を読み込み、各エントリの:
  - `file` パスの実在チェック（存在しない場合はエラー終了）
  - `strategy_key` ごとの upsert
    - 同じ `strategy_key` の戦略があれば更新
    - 無ければ新規作成（`is_builtin=True`, `source_type="builtin"`）

ユーザーがアップロードしたストラテジー（`/strategies` API で作成, `source_type="uploaded"`）には影響しません。

---

## 10. 組み込みデータセット（builtin）の復元

`datasets/` 配下には、TradingView 比較用や固定検証用の CSV を「組み込みデータセット」として配置できます。

- 定義ファイル: `datasets/manifest.json`
- 本体 CSV: `datasets/builtins/*.csv`

例（`datasets/manifest.json`）:

```json
[
  {
    "key": "btc_usdt_1h_sample_v1",
    "name": "BTCUSDT 1h Sample (Builtin)",
    "symbol": "BTCUSDT",
    "timeframe": "1h",
    "file": "builtins/btcusdt_1h_sample.csv"
  }
]
```

DB を新規作成したあと、組み込みデータセットを登録するには以下を実行します。

```bash
cd tv-backtest-api
source .venv/bin/activate

python -m app.scripts.seed_builtin_datasets
```

このコマンドは以下を行います。

- `Base.metadata.create_all(bind=engine)` を実行し、DB やテーブルが存在しない場合でも作成する
- `datasets/manifest.json` を読み込み、各エントリの:
  - `file` パスの実在チェック（存在しない場合はエラー終了）
  - `dataset_key` ごとの upsert
    - 同じ `dataset_key` のデータセットがあれば `name` / `symbol` / `timeframe` / `file_path` / `rows_count` を更新し、`is_builtin=True`, `source_type="builtin"` を設定
    - 無ければ新規作成
  - `rows_count` は CSV を読み込んで再計算

ユーザーがアップロードしたデータセット（`/datasets` API で作成, `source_type="uploaded"`）には影響しません。
