from __future__ import annotations

import json
from typing import Any

import streamlit as st

from app_utils.api import fetch_json, load_datasets, load_strategies

DEFAULT_RANGE_1_TO_100 = "1-100"


def _expand_range_token(token: str, *, value_type: type) -> list[Any]:
    """Expand range token.

    Supported:
    - start-end
    - start:end
    - start:end:step
    """
    t = token.strip()
    if not t:
        return []

    # `a-b` form
    if "-" in t and ":" not in t:
        left, right = t.split("-", 1)
        t = f"{left}:{right}"

    if ":" not in t:
        raise ValueError("not a range token")

    parts = [p.strip() for p in t.split(":") if p.strip()]
    if len(parts) < 2 or len(parts) > 3:
        raise ValueError(f"invalid range: {token}")

    if value_type is int:
        start = int(parts[0])
        end = int(parts[1])
        step = int(parts[2]) if len(parts) == 3 else (1 if end >= start else -1)
        if step == 0:
            raise ValueError("step must not be 0")
        # inclusive range
        stop = end + (1 if step > 0 else -1)
        return list(range(start, stop, step))

    if value_type is float:
        start = float(parts[0])
        end = float(parts[1])
        step = float(parts[2]) if len(parts) == 3 else (1.0 if end >= start else -1.0)
        if step == 0:
            raise ValueError("step must not be 0")
        values: list[float] = []
        cur = start
        eps = abs(step) * 1e-9
        if step > 0:
            while cur <= end + eps:
                values.append(float(cur))
                cur += step
        else:
            while cur >= end - eps:
                values.append(float(cur))
                cur += step
        return values

    raise ValueError("range is supported only for int/float")


def _parse_candidates(raw: str, *, default_value: Any) -> list[Any]:
    values: list[Any] = []
    value_type = bool if isinstance(default_value, bool) else type(default_value)

    for token in [t.strip() for t in raw.split(",") if t.strip()]:
        # int/float は範囲指定を先に試す
        if value_type in (int, float) and (":" in token or "-" in token):
            try:
                expanded = _expand_range_token(token, value_type=value_type)
                if expanded:
                    values.extend(expanded)
                    continue
            except Exception:
                # 単一値としての解釈にフォールバック
                pass

        if isinstance(default_value, bool):
            if token.lower() in ("true", "t", "1"):
                values.append(True)
            elif token.lower() in ("false", "f", "0"):
                values.append(False)
            else:
                raise ValueError(f"Invalid bool token: {token}")
        elif isinstance(default_value, int):
            values.append(int(token))
        elif isinstance(default_value, float):
            values.append(float(token))
        else:
            values.append(token)

    return values


def render() -> None:
    st.title("パラメータ最適化")
    st.caption(
        "この画面では、ストラテジーの候補パラメータを使って最適化ジョブを起動します。"
        " 結果の確認は「最適化ジョブ一覧」ページを利用してください。"
    )

    datasets = load_datasets()
    strategies = load_strategies()
    dataset_options = {f'{d["id"]}: {d["name"]}': d["id"] for d in datasets}
    strategy_options = {f'{s["id"]}: {s["name"]}': s for s in strategies}

    opt_warn_threshold = int(st.session_state.get("OPT_SEARCH_SPACE_WARNING_THRESHOLD", 5000))
    opt_hard_limit = int(st.session_state.get("OPT_SEARCH_SPACE_HARD_LIMIT", 100000))

    st.subheader("最適化を実行")
    st.info(
        "使い分けの目安: grid = 全探索（条件が小さいとき） / "
        "random = 指定 trial 数だけ探索（条件が大きいとき） / "
        "guided_random = 過去結果を参考に有望域へ寄せつつランダム探索"
    )
    st.caption(
        "最適化は手数料込みで評価されます。既定手数料は Bitget 先物 taker 0.06% / side です。"
        " 実運用条件に合わせて調整できます。"
    )

    selected_dataset = st.selectbox(
        "データセット",
        options=list(dataset_options.keys()),
        key="opt_dataset",
    ) if dataset_options else None
    selected_strategy = st.selectbox(
        "ストラテジー",
        options=list(strategy_options.keys()),
        key="opt_strategy",
    ) if strategy_options else None

    # 動的 search_space フォーム生成
    search_space: dict[str, list[Any]] = {}
    total_trials: int | None = None
    over_warning = False
    over_hard = False
    if selected_strategy:
        st.markdown("##### 最適化パラメータ (search_space)")
        st.caption(
            "指定方法: カンマ区切り (`5,10,15`) / 範囲 (`1-100` または `1:100`) / "
            "範囲+step (`1:100:5`)"
        )
        st_obj = strategy_options[selected_strategy]
        default_params_json = st_obj.get("default_params_json")
        try:
            default_params = (
                json.loads(default_params_json)
                if isinstance(default_params_json, str) and default_params_json.strip()
                else {}
            )
        except json.JSONDecodeError:
            default_params = {}

        if not default_params:
            raw_search_space = st.text_area(
                "最適化パラメータ (JSON)",
                value='{"fast_window": [5, 10, 15], "slow_window": [20, 30]}',
                height=100,
                key="opt_search_space_fallback",
            )
            try:
                search_space = (
                    json.loads(raw_search_space) if raw_search_space.strip() else {}
                )
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON in search_space: {exc}")
                search_space = {}
        else:
            for p_key, p_default in default_params.items():
                widget_key = f"opt_param_{st_obj['id']}_{p_key}"
                if isinstance(p_default, bool):
                    placeholder = "true,false"
                    default_value = placeholder
                elif isinstance(p_default, int):
                    placeholder = "1,2,3,...,100"
                    default_value = DEFAULT_RANGE_1_TO_100
                elif isinstance(p_default, float):
                    placeholder = "1,2,3,...,100"
                    default_value = DEFAULT_RANGE_1_TO_100
                else:
                    placeholder = "mode_a,mode_b"
                    default_value = placeholder

                raw = st.text_input(
                    p_key,
                    value=default_value,
                    key=widget_key,
                    help=(
                        "カンマ区切りまたは範囲指定で入力。"
                        " 例: 5,10,15 / 1-100 / 1:100 / 1:100:5"
                    ),
                )

                values: list[Any] = []
                try:
                    values = _parse_candidates(raw, default_value=p_default)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"{p_key}: 入力 '{raw}' を変換できません: {exc}")
                    values = []

                if values:
                    search_space[p_key] = values

    # search_mode / n_trials
    search_mode = st.selectbox(
        "探索モード (search_mode)",
        options=["grid", "random", "guided_random"],
        index=0,
        key="opt_search_mode",
    )

    n_trials: int | None = None
    trials_per_set: int | None = None
    set_count: int | None = None
    if search_mode in ("random", "guided_random"):
        exec_style = st.radio(
            "試行の指定方法",
            options=["単発 trial 数で実行", "セット分割で実行"],
            index=0,
            key="opt_exec_style",
            help="セット分割: 長時間の random 探索を小分けにし、各セット完了ごとに進捗とベスト結果を保存します。",
        )
        st.caption(
            "長時間の random 探索を小分けに実行します。各セット完了ごとに進捗とベスト結果を保存します。"
            " 例: 1000 × 10 = 合計 10000 trial。"
        )
        if exec_style == "単発 trial 数で実行":
            n_trials = st.number_input(
                "random search の試行数 (n_trials)",
                min_value=1,
                value=100,
                step=1,
                key="opt_n_trials",
            )
        else:
            c1, c2 = st.columns(2)
            with c1:
                trials_per_set = st.number_input(
                    "1セットあたりの trial 数 (trials_per_set)",
                    min_value=1,
                    value=1000,
                    step=1,
                    key="opt_trials_per_set",
                )
            with c2:
                set_count = st.number_input(
                    "セット数 (set_count)",
                    min_value=1,
                    value=10,
                    step=1,
                    key="opt_set_count",
                )
            total_plan = int(trials_per_set) * int(set_count)
            st.info(f"合計予定 trial 数: **{total_plan}** (= {trials_per_set} × {set_count})")

    # 各パラメータの候補数と総トライアル数を表示
    if search_space:
        summary = [f"{k}: {len(v)}候補" for k, v in search_space.items()]
        st.caption("候補数サマリ: " + ", ".join(summary))

        total_trials = 1
        for _, vals in search_space.items():
            total_trials *= max(len(vals), 1)

        fixed_params = [k for k, v in search_space.items() if len(v) == 1]
        varying_params = [k for k, v in search_space.items() if len(v) > 1]

        if fixed_params:
            st.caption("固定パラメータ: " + ", ".join(fixed_params))
        if varying_params:
            st.caption("最適化対象パラメータ: " + ", ".join(varying_params))

        if total_trials == 1:
            st.warning("この最適化は実質 1 trial です（全パラメータが固定値）。")
        else:
            st.caption(
                f"総組み合わせ数: {total_trials} trial "
                f"(推奨しきい値: {opt_warn_threshold}, ハード上限: {opt_hard_limit})",
            )
            st.caption(
                "random search は、この有限候補集合から重複なしでランダム抽出します。"
                " 過去に試行済みの組み合わせも可能な限り除外されます。",
            )

        if search_mode == "grid":
            if total_trials > opt_hard_limit:
                over_hard = True
                st.error(
                    "grid search では総組み合わせ数がハード上限を超えています。"
                    "パラメータ候補を減らしてください。",
                )
            elif total_trials > opt_warn_threshold:
                over_warning = True
                st.warning(
                    "grid search の総組み合わせ数が推奨しきい値を超えています。",
                )
        elif search_mode == "random":
            if total_trials > opt_hard_limit:
                st.info(
                    "総組み合わせ数は非常に大きいですが、random search は"
                    "指定 trial 数のみ抽出して実行するため実行可能です。",
                )
            elif total_trials > opt_warn_threshold:
                st.caption(
                    "候補空間が広いため、十分な探索には trial 数の追加が必要になる可能性があります。",
                )
        else:  # guided_random
            if total_trials > opt_hard_limit:
                st.info(
                    "総組み合わせ数は非常に大きいですが、guided_random は"
                    "過去結果を参考に有望域へ寄せつつ指定 trial 数だけ探索するため実行可能です。",
                )
            elif total_trials > opt_warn_threshold:
                st.caption(
                    "探索空間が広いため、guided_random でも十分な探索のために trial 数の追加が有効な場合があります。",
                )

    if search_mode in ("random", "guided_random") and total_trials is not None:
        if trials_per_set is not None and set_count is not None:
            st.caption(
                f"予定: セット分割 {int(trials_per_set)} × {int(set_count)} "
                f"/ 参考: 総組み合わせ数 {total_trials}",
            )
        elif n_trials is not None:
            st.caption(
                f"要求試行数 (n_trials): {int(n_trials)} / 参考: 総組み合わせ数 {total_trials}",
            )
        if search_mode == "random":
            st.caption(
                "random search は候補空間が大きくても、指定 trial 数だけ抽出して実行します。"
            )
        else:
            st.caption(
                "guided_random は過去の成功 trial を参考に、有望域から優先的に探索します（ただし一部は広い範囲も維持）。"
            )

    opt_settings_text = st.text_area(
        "プロパティ (JSON)",
        value='{"initial_capital": 1000000}',
        height=80,
        key="opt_settings",
    )
    opt_fee_percent = st.number_input(
        "手数料 (% / side)",
        min_value=0.0,
        value=0.06,
        step=0.01,
        format="%.4f",
        key="opt_fee_percent",
        help="内部では fee_rate (例: 0.0006) として trial 評価に使用します。",
    )
    st.caption(f"内部 fee_rate: {float(opt_fee_percent) / 100.0:.6f}（entry/exit 両側に適用）")
    objective_metric = st.text_input("最適化指標 (objective_metric)", value="net_profit")

    opt_start_date = st.text_input(
        "開始日 (YYYY-MM-DD, 任意・timestamp 列必須)",
        value="2023-01-01",
        key="opt_start_date",
    )
    opt_end_date = st.text_input(
        "終了日 (YYYY-MM-DD, 任意・timestamp 列必須)",
        value="2026-03-01",
        key="opt_end_date",
    )

    run_opt = st.button(
        "最適化ジョブを開始",
        disabled=bool(over_hard),
    )
    if run_opt:
        if not selected_dataset or not selected_strategy:
            st.error("Dataset and Strategy must be selected.")
        else:
            try:
                settings = (
                    json.loads(opt_settings_text) if opt_settings_text.strip() else None
                )
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON in settings: {exc}")
            else:
                settings = dict(settings or {})
                settings["fee_rate"] = float(opt_fee_percent) / 100.0
                st_obj = strategy_options[selected_strategy]
                payload: dict[str, Any] = {
                    "dataset_id": dataset_options[selected_dataset],
                    "strategy_id": st_obj["id"],
                    "search_space": search_space,
                    "settings": settings,
                    "objective_metric": objective_metric or None,
                    "search_mode": search_mode,
                    "start_date": opt_start_date or None,
                    "end_date": opt_end_date or None,
                }
                if search_mode in ("random", "guided_random"):
                    if trials_per_set is not None and set_count is not None:
                        payload["trials_per_set"] = int(trials_per_set)
                        payload["set_count"] = int(set_count)
                    else:
                        payload["n_trials"] = int(n_trials) if n_trials else None
                status, data = fetch_json("POST", "/optimizations", json=payload)
                st.write("Status:", status)
                if isinstance(data, (dict, list)):
                    st.json(data)
                else:
                    st.write(data)
                if status == 200 and isinstance(data, dict):
                    st.session_state.last_optimization_id = data.get("id")
                    st.success(
                        f"ジョブを登録しました (ID={data.get('id')})。"
                        " 「最適化ジョブ一覧」で進捗・結果を確認できます。",
                    )
