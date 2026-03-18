from __future__ import annotations

import json
from typing import Any

import streamlit as st

from app_utils.api import fetch_json, load_datasets, load_strategies
from app_utils.renderers import render_optimization_summary
from app_utils.trials_analysis import render_trials_ranking, render_trials_analysis


def render() -> None:
    st.title("パラメータ最適化")

    datasets = load_datasets()
    strategies = load_strategies()
    dataset_options = {f'{d["id"]}: {d["name"]}': d["id"] for d in datasets}
    strategy_options = {f'{s["id"]}: {s["name"]}': s for s in strategies}

    opt_warn_threshold = int(st.session_state.get("OPT_SEARCH_SPACE_WARNING_THRESHOLD", 5000))
    opt_hard_limit = int(st.session_state.get("OPT_SEARCH_SPACE_HARD_LIMIT", 100000))

    col_left, col_right = st.columns([2, 3])

    with col_left:
        st.subheader("最適化を実行")

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
                    elif isinstance(p_default, int):
                        placeholder = "20,28,36"
                    elif isinstance(p_default, float):
                        placeholder = "0.8,1.0,1.2"
                    else:
                        placeholder = "mode_a,mode_b"

                    raw = st.text_input(
                        p_key,
                        value=placeholder,
                        key=widget_key,
                        help="カンマ区切りで候補値を入力（例: 5,10,15）",
                    )

                    values: list[Any] = []
                    for token in [t.strip() for t in raw.split(",") if t.strip()]:
                        try:
                            if isinstance(p_default, bool):
                                if token.lower() in ("true", "t", "1"):
                                    values.append(True)
                                elif token.lower() in ("false", "f", "0"):
                                    values.append(False)
                                else:
                                    raise ValueError(f"Invalid bool token: {token}")
                            elif isinstance(p_default, int):
                                values.append(int(token))
                            elif isinstance(p_default, float):
                                values.append(float(token))
                            else:
                                values.append(token)
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"{p_key}: 値 '{token}' を変換できません: {exc}")
                            values = []
                            break

                    if values:
                        search_space[p_key] = values

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

            if total_trials > opt_hard_limit:
                over_hard = True
                st.error(
                    "総組み合わせ数がハード上限を超えています。"
                    "パラメータ候補を減らしてから実行してください。",
                )
            elif total_trials > opt_warn_threshold:
                over_warning = True
                st.warning(
                    "総組み合わせ数が推奨しきい値を超えています。"
                    "実行時間やレスポンスサイズに注意してください。",
                )

        # search_mode / n_trials
        search_mode = st.selectbox(
            "探索モード (search_mode)",
            options=["grid", "random"],
            index=0,
            key="opt_search_mode",
        )

        n_trials: int | None = None
        if search_mode == "random":
            n_trials = st.number_input(
                "random search の試行数 (n_trials)",
                min_value=1,
                value=100,
                step=1,
                key="opt_n_trials",
            )
            if total_trials is not None:
                st.caption(
                    f"要求試行数 (n_trials): {int(n_trials)} / 利用可能候補数: {total_trials}",
                )

        opt_settings_text = st.text_area(
            "プロパティ (JSON)",
            value='{"initial_capital": 1000000}',
            height=80,
            key="opt_settings",
        )
        objective_metric = st.text_input("最適化指標 (objective_metric)", value="net_profit")

        opt_start_date = st.text_input(
            "開始日 (YYYY-MM-DD, 任意・timestamp 列必須)",
            value="",
            key="opt_start_date",
        )
        opt_end_date = st.text_input(
            "終了日 (YYYY-MM-DD, 任意・timestamp 列必須)",
            value="",
            key="opt_end_date",
        )

        run_opt = st.button(
            "パラメータ最適化を実行",
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
                    st_obj = strategy_options[selected_strategy]
                    payload = {
                        "dataset_id": dataset_options[selected_dataset],
                        "strategy_id": st_obj["id"],
                        "search_space": search_space,
                        "settings": settings,
                        "objective_metric": objective_metric or None,
                        "search_mode": search_mode,
                        "n_trials": int(n_trials) if (search_mode == "random" and n_trials) else None,
                        "start_date": opt_start_date or None,
                        "end_date": opt_end_date or None,
                    }
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
                            " 「直近の最適化結果」で進捗を確認できます。",
                        )

    with col_right:
        st.subheader("直近の最適化結果")
        last_opt_id = st.session_state.get("last_optimization_id")
        if last_opt_id:
            if st.button("Load Last Optimization Result"):
                run_status, run_data = fetch_json("GET", f"/optimizations/{last_opt_id}")
                status, data = fetch_json("GET", f"/optimizations/{last_opt_id}/result")
                st.write("Status:", status)

                if run_status == 200 and isinstance(run_data, dict):
                    render_optimization_summary(run_data, data if isinstance(data, dict) else {})
                    st.write("search_mode:", run_data.get("search_mode", "grid"))
                    if run_data.get("requested_trials") is not None:
                        st.write("requested_trials:", run_data.get("requested_trials"))
                    if run_data.get("executed_trials") is not None:
                        st.write("executed_trials:", run_data.get("executed_trials"))
                        if (
                            run_data.get("requested_trials")
                            and run_data.get("executed_trials", 0)
                            < run_data.get("requested_trials")
                        ):
                            st.warning(
                                "未試行候補が尽きたため、要求試行数より少ない件数のみ実行されました。",
                            )
                    if run_data.get("message"):
                        st.info(str(run_data.get("message")))
                    if run_data.get("error_message"):
                        st.error(str(run_data.get("error_message")))

                if status == 200 and isinstance(data, dict):
                    trials = data.get("trials", [])
                    best_params = data.get("best_params", {})
                    best_score = data.get("best_score")
                    objective_metric_result = data.get("objective_metric")

                    if trials:
                        df_for_analysis = render_trials_ranking(
                            trials,
                            key_prefix="opt_trials_last",
                        )
                        if df_for_analysis is not None:
                            render_trials_analysis(
                                df_for_analysis,
                                key_prefix="opt_trials_last",
                            )

                    st.write("最適パラメータ")
                    st.json(best_params)
                    st.write("最適化スコア:", best_score)
                    st.write("最適化指標:", objective_metric_result)

                    if best_params is not None and run_status == 200 and isinstance(run_data, dict):
                        if st.button("この最適パラメータでバックテストを実行", key="opt_rerun_bt_last"):
                            settings = {}
                            raw_settings = run_data.get("settings_json")
                            if isinstance(raw_settings, str) and raw_settings:
                                try:
                                    settings = json.loads(raw_settings)
                                except Exception:  # noqa: BLE001
                                    settings = {}

                            bt_status, bt_data = fetch_json(
                                "POST",
                                "/backtests",
                                json={
                                    "dataset_id": run_data["dataset_id"],
                                    "strategy_id": run_data["strategy_id"],
                                    "params": best_params,
                                    "settings": settings,
                                },
                            )
                            if bt_status == 200 and isinstance(bt_data, dict):
                                st.session_state.last_backtest_id = bt_data.get("id")
                                st.success("バックテストを実行しました。左の「直近のテスト結果」で確認できます。")
                            else:
                                st.error(str(bt_data) if bt_data else "バックテストに失敗しました。")

