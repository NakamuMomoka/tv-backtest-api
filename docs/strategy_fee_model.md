# 戦略別手数料（fee_rate）適用モデル

`fee_rate` は **1 回の約定あたりのノーショナルに対する割合**（例: taker 0.06% → `0.0006`）。  
long / short で同じ率を用いる（対称）。ラウンドトリップでは **entry と exit で計 2 回**かかる前提で実装する。

共通ヘルパー: `app/services/strategy_fees.py`

| 戦略 | 実装ラベル (`fee_implementation`) | 根拠となる PnL 表現 | entry での手数料 | exit での手数料 | long/short | fixed qty / compounding |
|------|----------------------------------|---------------------|------------------|-----------------|------------|-------------------------|
| `sample_strategy_ma_cross` | `return_compound_roundtrip` | 価格比の **リターン** に `equity *= (1+pnl)` | リターンに **一括** `2 * fee_rate` を控除（ラウンドトリップ） | 同上（1トレード単位） | 同式 | **複利**（全額を再投資） |
| `rjv` | `return_compound_roundtrip` | 同上（TV 風トレードリスト） | 同上 | 同上 | 同式 | **複利** |
| `assistpass` | `equity_per_fill_side` | バーごとに価格で equity 更新後、約定で **乗数** | 約定のたび `equity *= (1 - fee_rate)`（ドテン等で連続する場合はその回数分） | 決済時も同様に 1 回 | 同じ乗数 | **複利**（エクイティ全体に対するサイド手数料） |
| `motu_chaos_mod_bf_bitget` | `absolute_notional_per_fill` | **固定数量**の価格差 PnL | `abs(price * qty * fee_rate)` を約定ごとに realized から減算 | クローズ時の PnL からも exit 分を減算（entry は別行で控除済み） | 同式 | **固定数量**（非複利） |

## fee_rate = 0 のとき

いずれのモデルも手数料項が **恒等**（リターン控除 0、乗算 1、絶対額 0）となり、手数料導入前と同じ数値になる。

## optimization_mode

`optimization_mode=True` では詳細配列の省略等の最適化があるが、**metrics の計算経路は同一**であり、`fee_rate` の扱いも変えない（検証は `scripts/verify_fee_model.py` を参照）。

## 実データスモーク

組み込み `datasets/builtins/1_BITGET_BTCUSDT.P_60.csv` で `fee_rate=0` と `0.0006` を比較する場合は `scripts/smoke_fee_real_data.py` を参照（`motu` は `use_test_period=False` で全期間を対象）。

※ `rjv` / `sample_strategy_ma_cross` の `gross_profit` / `gross_loss` は **実現リターンの合計**（比率ベース）であり、金額ではない。`net_profit` / `final_equity` は資本に対する結果。
