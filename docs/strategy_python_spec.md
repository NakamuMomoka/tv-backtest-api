## Python ストラテジー実装仕様（tv-backtest-api）

このドキュメントは、`tv-backtest-api` で実行する **Python 戦略ファイル（ストラテジー）** の実装仕様をまとめたものです。  
TradingView との比較検証や将来拡張を見据えた、共通インターフェースと推奨ルールを定義します。

---

### 1. 必須インターフェース

戦略ファイルは、**グローバルスコープに 1 つの `backtest` 関数**を必ず定義してください。

```python
def backtest(bars, params, settings):
    ...
```

- `bars`: `pandas.DataFrame`（バックテスト対象のチャートデータ）
- `params`: `dict` または `None`（ストラテジーパラメータ）
- `settings`: `dict` または `None`（バックテスト実行時の設定情報）

関数は必ず **`dict` を返し**、少なくとも以下 3 つのキーを含める必要があります。

```python
return {
    "metrics": {...},        # dict
    "trades": [...],         # list
    "equity_series": [...],  # list
}
```

---

### 2. 引数の仕様

#### 2.1 `bars`（チャートデータ）

- 型: `pandas.DataFrame`
- 含まれる列（最低限）:
  - `open`: 始値（float）
  - `high`: 高値（任意だが推奨）
  - `low` : 安値（任意だが推奨）
  - `close`: 終値（float, 必須）
  - `volume`: 出来高（任意）
- 日時列（後述）:
  - いずれか 1 つ以上: `timestamp`, `time`, `datetime`, `date`

アドバイス:

- `bars` は **呼び出し側で reuse される可能性**があるため、内部で加工したい場合は `bars.copy()` してから利用してください。

#### 2.2 `params`（ストラテジーパラメータ）

- 型: `dict[str, Any]` または `None`
- 例:
  - `{"fast_window": 9, "slow_window": 21}`
- 戦略側では、`params = params or {}` で `None` を吸収してから利用することを推奨します。

```python
params = params or {}
fast_window = int(params.get("fast_window", 9))
slow_window = int(params.get("slow_window", 21))
```

#### 2.3 `settings`（バックテスト実行設定）

- 型: `dict[str, Any]` または `None`
- 例:
  - `{"initial_capital": 1000000, "slippage": 0.0}`
- 戦略側では、`settings = settings or {}` で `None` を吸収してから利用することを推奨します。

```python
settings = settings or {}
initial_capital = float(settings.get("initial_capital", 1_000_000))
```

---

### 3. 戻り値の仕様

#### 3.1 `metrics`（集計指標）

- 型: `dict[str, Any]`
- 必須ではないものの、**以下のキーを強く推奨**します。

推奨項目:

- `net_profit`: 最終損益（初期残高との差分, float）
- `final_equity`: 最終残高（float）
- `max_drawdown`: 最大ドローダウン（金額ベース, float）
- `total_trades`: 実現トレード数（int）
- `win_rate`: 勝率（0〜1, float）
- `profit_factor`: プロフィットファクター（総利益 / 総損失, float or None）
- `open_position_at_end`: 最終バー時点でポジションが残っているかどうか（bool）

例:

```python
metrics = {
    "net_profit": 27497.62,
    "final_equity": 127497.62,
    "max_drawdown": 8000.0,
    "total_trades": 84,
    "win_rate": 0.52,
    "profit_factor": 1.45,
    "open_position_at_end": False,
}
```

#### 3.2 `trades`（トレード一覧）

- 型: `list[dict[str, Any]]`
- **1 要素 = 1 トレード（エントリー〜エグジット）**を表現します。

推奨項目:

- `entry_index`: エントリー約定バーのインデックス（0 始まり, int）
- `exit_index`: エグジット約定バーのインデックス（int または `None`）
- `entry_time`: エントリー約定バーの日時（str または `None`）
- `exit_time`: エグジット約定バーの日時（str または `None`）
- `entry_price`: エントリー約定価格（float）
- `exit_price`: エグジット約定価格（float または `None`）
- `pnl`: トレード単位の損益（例: リターン, float または `None`）

未決済トレードの扱い:

- 未決済ポジションが残っている場合は、`exit_*` と `pnl` を `None` にして **「未決済トレード」として記録**し、  
  同時に `metrics["open_position_at_end"] = True` とすることを推奨します。

#### 3.3 `equity_series`（資産曲線）

- 型: `list[dict[str, Any]]`
- 推奨形式:

```python
[
  {"index": 0, "equity": 1000000.0},
  {"index": 1, "equity": 1001200.0},
  ...
]
```

仕様:

- `index`: バーインデックス（`bars` の行番号と対応, 0 始まり）
- `equity`: 当該バーの **時価評価後の資産残高**（含み損益込み）
  - ポジション保有中は `close` を使って mark-to-market を行うことを推奨。
  - 例（ロングの場合）:
    - 前バー close: `close_{i-1}`
    - 現バー close: `close_i`
    - バーリターン: `(close_i - close_{i-1}) / close_{i-1}`
    - 資産更新: `equity *= (1 + position_{i-1} * bar_ret)`

`max_drawdown` は、この `equity_series` に基づいて算出すると、含み損も反映されたリスク評価になります。

---

### 4. 利用可能な入力列と日時の扱い

#### 4.1 価格・出来高

`bars` には少なくとも以下の列を用意してください。

- `open`（必須）: 始値
- `close`（必須）: 終値
- `high`（任意）: 高値
- `low`（任意）: 安値
- `volume`（任意）: 出来高

#### 4.2 日時列

TradingView との比較や期間絞り込みのため、**以下のいずれか 1 列以上**を含めることを推奨します。

- `timestamp`: ISO8601 文字列（例: `"2023-01-01T00:00:00Z"`）や UNIX 時刻など
- `time`: UNIX タイムスタンプ（秒）
- `datetime` / `date`: Python `datetime` / 日付文字列など

バックテストエンジン側では、期間指定（`start_date` / `end_date`）において:

- 優先的に `timestamp` 列を使用
- それが無ければ `time`（UNIX 秒）を UTC として解釈

戦略内で `entry_time` / `exit_time` に利用する場合も、

- 元の値を `str(...)` で文字列化して保存する形がシンプルで扱いやすいです。

---

### 5. TradingView 比較用の実装ルール（推奨）

TradingView の Strategy Tester と結果を比較しやすくするため、以下のルールを推奨します（必須ではありません）。

- **約定価格**
  - シグナルがバー `i` で出た場合、**約定は次バー `i+1` の `open`** で行う。
  - 最終バーで出たシグナルは `i+1` が存在しないため、**約定しない**。

- **ポジション定義**
  - 1 シンボル・1 ポジション前提（シンプルなロングオンリーやフルレバレッジなど）で始める。
  - TradingView の `strategy.position_size` に近い形で「常にフルロング or ノーポジ」等に揃えると比較しやすい。

- **資産曲線 / drawdown**
  - 各バーで `close` を使い mark-to-market した equity から drawdown を計算。
  - TradingView の「最大ドローダウン（資産曲線ベース）」に近い指標になるよう合わせる。

- **手数料・スリッページ**
  - まずは両者とも 0 にして差分を減らす。
  - その後、同じパラメータ（率 or 定額）で追加する。

---

### 6. エラー処理

戦略内で例外を投げた場合、バックテストエンジンはそれをラップして HTTP 500 等として返します。

推奨:

- **入力バリデーションエラー**（必須列が無いなど）は、`ValueError` / `TypeError` などの標準例外で明示的に投げる。
  - 例:
    ```python
    if "close" not in bars.columns:
        raise ValueError("Dataset must contain 'close' column.")
    ```
- 複雑な検証を行う場合は、独自例外クラスを使っても構いませんが、メッセージは原因が分かるようにしてください。
- 戻り値の型が仕様と異なる場合（`metrics` が dict ではない等）は、**必ず例外にして落とす**こと（中途半端な結果を返さない）。

---

### 7. 非推奨事項

- グローバル変数に状態を持ち続ける実装（並列実行時に壊れやすいため）
- `bars` を破壊的に変更して返り値にそのまま含めること（他戦略との共用を阻害する）
- ランダム性を含む処理でシードを固定しないこと（再現性が失われる）
- 返り値のキー構造を変える（`metrics` / `trades` / `equity_series` 以外をトップレベルに置く）こと

---

### 8. 推奨事項

- **再現性**
  - 乱数を使う場合は `settings` 経由でシードを受け取り、`numpy.random.seed` などで固定する。
- **可読性**
  - エントリー・エグジットロジックは関数に分割するなどして、TradingView 版との見比べがしやすい構造にする。
- **TradingView との 1:1 対応**
  - Pine Script と Python で同じ名称の変数・コメントを使うと、diff を取りやすい。
- **メトリクスの充実**
  - 必要に応じて、`sharpe_ratio`, `sortino_ratio`, `max_consecutive_losses`, `expectancy` なども `metrics` に追加する。

---

### 9. 最小サンプル

以下は、最小限の moving average クロス戦略のサンプルです（構造の参考用）。

```python
import pandas as pd


def backtest(bars: pd.DataFrame, params, settings):
    params = params or {}
    settings = settings or {}

    fast_window = int(params.get("fast_window", 9))
    slow_window = int(params.get("slow_window", 21))
    initial_capital = float(settings.get("initial_capital", 10000))

    if "open" not in bars.columns or "close" not in bars.columns:
        raise ValueError("Dataset must contain 'open' and 'close' columns.")

    df = bars.copy().reset_index(drop=True)

    df["fast_ma"] = df["close"].rolling(window=fast_window, min_periods=fast_window).mean()
    df["slow_ma"] = df["close"].rolling(window=slow_window, min_periods=slow_window).mean()

    df["long_entry"] = (df["fast_ma"] > df["slow_ma"]) & (
        df["fast_ma"].shift(1) <= df["slow_ma"].shift(1)
    )
    df["long_exit"] = (df["fast_ma"] < df["slow_ma"]) & (
        df["fast_ma"].shift(1) >= df["slow_ma"].shift(1)
    )

    time_col = None
    for candidate in ("timestamp", "time", "datetime", "date"):
        if candidate in df.columns:
            time_col = candidate
            break

    trades = []
    realized_pnls = []

    in_position = False
    entry_price = None
    entry_index = None
    entry_time = None

    n = len(df)
    equity = initial_capital

    # トレード生成（シグナルバー i, 約定は i+1 の open）
    for i in range(n - 1):
        row = df.iloc[i]
        next_row = df.iloc[i + 1]

        if time_col is not None:
            raw_time = next_row[time_col]
            exec_time = None if pd.isna(raw_time) else str(raw_time)
        else:
            exec_time = None

        if not in_position and bool(row["long_entry"]):
            in_position = True
            entry_price = float(next_row["open"])
            entry_index = i + 1
            entry_time = exec_time
        elif in_position and bool(row["long_exit"]):
            exit_price = float(next_row["open"])
            exit_index = i + 1
            exit_time = exec_time

            pnl = (exit_price - entry_price) / entry_price  # type: ignore[operator]
            realized_pnls.append(float(pnl))

            trades.append(
                {
                    "entry_index": int(entry_index),  # type: ignore[arg-type]
                    "exit_index": int(exit_index),
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "entry_price": float(entry_price),  # type: ignore[arg-type]
                    "exit_price": float(exit_price),
                    "pnl": float(pnl),
                },
            )

            in_position = False
            entry_price = None
            entry_index = None
            entry_time = None

    # equity_series（時価評価）の計算
    position = [0] * n
    for t in trades:
        e = int(t["entry_index"])
        x = int(t["exit_index"])
        for j in range(e, min(x, n - 1) + 1):
            position[j] = 1

    equity_series = []
    equity = initial_capital
    if n > 0:
        equity_series.append({"index": 0, "equity": float(equity)})

    for i in range(1, n):
        close_prev = float(df.loc[i - 1, "close"])
        close_cur = float(df.loc[i, "close"])
        bar_ret = (close_cur - close_prev) / close_prev if close_prev != 0 else 0.0
        equity *= 1.0 + position[i - 1] * bar_ret
        equity_series.append({"index": int(i), "equity": float(equity)})

    # メトリクス
    wins = [x for x in realized_pnls if x > 0]
    losses = [x for x in realized_pnls if x <= 0]

    total_trades = len(realized_pnls)
    win_rate = (len(wins) / total_trades) if total_trades > 0 else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = -sum(losses) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    # max_drawdown
    max_dd = 0.0
    if equity_series:
        peak = equity_series[0]["equity"]
        for pt in equity_series:
            eq = pt["equity"]
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd

    final_equity = float(equity)
    net_profit = float(final_equity - initial_capital)

    metrics = {
        "net_profit": net_profit,
        "final_equity": final_equity,
        "max_drawdown": float(max_dd),
        "total_trades": int(total_trades),
        "win_rate": float(win_rate),
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "open_position_at_end": bool(in_position),
    }

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_series": equity_series,
    }
```

---

### 10. 今後の拡張候補

- マルチシンボル対応（`bars` をマルチシンボル化、または複数 `bars` を渡す）
- ショートポジションやレバレッジ対応（`position` を -1 / 0 / +1 等で扱う）
- 複数ポジション同時保有（ポジションサイズと PnL 計算を拡張）
- 手数料・スリッページ・税金などの詳細モデリング
- リアルタイム実行を意識したインターフェース（シグナルストリーム方式など）

これらは今後の要件に応じてインターフェースを拡張する予定です。

