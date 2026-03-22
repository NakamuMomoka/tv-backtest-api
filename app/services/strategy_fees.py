"""戦略横断の手数料（fee_rate）の共通定義。

Bitget 先物の **taker 基準** を想定し、``fee_rate`` は **1回の約定あたりのノーショナルに対する割合**
（例: 0.06% / side → ``0.0006``）として扱う。

long / short で手数料率は同じ（対称）。ラウンドトリップでは **entry + exit で 2 回** かかる。

実装パターン（戦略の PnL 表現に合わせて使い分け）:

1. **リターン比率モデル**（価格比・複利乗算）
   - 1トレードの **リターン** に対し、ラウンドトリップで ``2 * fee_rate`` を控除する。
   - 適用例: ``sample_strategy_ma_cross``, ``rjv``（エクイティは ``equity *= (1 + pnl)``）

2. **エクイティ乗数モデル**（バーごとに価格でエクイティを更新し、約定時に手数料を引く）
   - 約定のたびに ``equity *= (1 - fee_rate)`` を **サイドごとに 1 回**（entry と exit で計 2 回）。
   - 適用例: ``assistpass``

3. **固定数量・絶対額 P/L モデル**
   - 手数料 = ``|price * qty * fee_rate|`` を **約定ごと**に realized に加算（負のコスト）。
   - 適用例: ``motu_chaos_mod_bf_bitget``

``fee_rate == 0`` のとき、上記はいずれも恒等（手数料ゼロ）となり、手数料導入前と同じ計算になる。
"""

from __future__ import annotations

from typing import Any

from app.core.config import DEFAULT_FEE_RATE


def fee_rate_from_settings(settings: dict[str, Any] | None, *, default: float | None = None) -> float:
    """settings から fee_rate を取得。未指定なら default（省略時は DEFAULT_FEE_RATE）。"""
    d = default if default is not None else DEFAULT_FEE_RATE
    if not settings:
        return max(0.0, float(d))
    raw = settings.get("fee_rate", d)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return max(0.0, float(d))


def roundtrip_return_fee(fee_rate: float) -> float:
    """リターン比率モデルでラウンドトリップ分として控除する量（= 2 * fee_rate）。"""
    return 2.0 * max(0.0, float(fee_rate))


def per_side_return_fee(fee_rate: float) -> float:
    """リターン比率空間での 1 サイド分（未決済の含み益に entry 側のみ反映する場合など）。"""
    return max(0.0, float(fee_rate))


def apply_fee_to_return_pct(gross_return: float, fee_rate: float) -> float:
    """リターン（価格比ベース等）からラウンドトリップ手数料を控除。"""
    return float(gross_return) - roundtrip_return_fee(fee_rate)


def compound_equity_after_side_fee(equity: float, fee_rate: float) -> float:
    """エクイティ乗数モデル: 1回の約定（片側）あたり ``equity *= (1 - fee_rate)``。"""
    fr = max(0.0, float(fee_rate))
    return float(equity) * (1.0 - fr)


def per_side_notional_fee(price: float, qty: float, fee_rate: float) -> float:
    """固定数量モデル: 1回の約定あたりの手数料額（>=0）。"""
    return abs(float(price) * float(qty) * max(0.0, float(fee_rate)))


def fee_metrics_meta(fee_rate: float, *, implementation: str) -> dict[str, Any]:
    """metrics に載せる手数料メタ（全戦略でキー名を揃える）。

    implementation はコード上の適用形態のラベル（ドキュメント・デバッグ用）。
    """
    fr = max(0.0, float(fee_rate))
    return {
        "fee_rate_used": fr,
        "fee_percent_side": fr * 100.0,
        "fee_model": "taker_per_side",
        "fee_implementation": implementation,
    }
