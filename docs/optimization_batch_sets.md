# セット分割最適化（random / guided_random）

## seen_job と previously_tested

- **`previously_tested`**: ジョブ開始時に DB 上の過去成功ジョブの trial から収集したパラメータ署名の集合。
- **`seen_job`**: `set(previously_tested)` をコピーして初期化し、**このジョブ内で実行した各 trial のたびに** `params_signature(params)` を追加。
- 各セットのサンプリング（`_sample_random_unseen_params` / `sample_guided_random_unseen_params`）には **`seen_job` を渡す**ため、**セットをまたいでも同一ジョブ内の重複は発生しない**。

## 途中再開（resume）

現状は未実装。将来的には `seen_job` 相当を result JSON から復元する設計が素直。
