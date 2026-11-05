# 実装メモ（設計との差分）

## 状態判定の計算式（テスト契約を優先）

- 本実装の状態判定は、テスト契約（`tests/interfaces.md`）の式で実装した:
  `now <= 最終成功 + 周期 + 許容遅延 → 成功`、それ以外は失敗（期限超過）。
  境界（ちょうど期限時刻）は成功側に倒す。
- `docs/design.md` §4 の「予定表ベース判定」（直近の予定発火時刻 + 猶予で
  判定する方式）は、weekly の金→月（72時間）や monthly のような
  不等間隔スケジュールで「最終成功 + 固定周期」が誤判定しうるため、
  将来の改善候補として記録する。現時点では実装していない。
  - 改善する場合は、定義表にスケジュール情報（曜日・日など）を追加し、
    テスト契約の更新と合わせて行うこと。

## 定義表の形式（コーディネーター裁定）

- 設計書 §3 は YAML（`config/targets.yaml`）を第一案としていたが、
  裁定により **JSON**（Python 標準ライブラリのみ、追加依存ゼロ）とした。
  - ランタイム定義: `~/workspace/cron-watchdog-data/definitions.json`
    （リポジトリ外）
  - サンプル: `config/definitions.sample.json`

## モジュール構成の差分

- 設計書 §10.1 の `src/watchdog/` レイアウトではなく、リポジトリ直下の
  フラットな `watchdog/` パッケージとした（テストの import が
  `watchdog.xxx` であり、リポジトリルートからそのまま実行できるため）。
- テスト契約の6モジュール（definitions / status / ledger / heartbeat /
  masking / notify）に、追加モジュールとして snapshot（スナップショット
  取り込み）・state（状態ストアの累積マージ）・cli を加えた。
  これは契約の変更ではなく追加である。
- 設計書 §10.2 の詳細なデータ型（Judgement、AnomalyEvent 等）は、
  テスト契約の型（LedgerRow 等）を正とし、必要最小限に留めた。

## マスキング上限

- テスト契約の `mask_sensitive` 既定上限は 200 文字（契約どおり）。
- 設計書 §7 の台帳・通知向け抜粋上限 120 文字は
  `watchdog.masking.EXCERPT_MAX_LENGTH` として定数化してある
  （利用箇所で `max_length` に渡す）。

## スナップショットの個人情報対策

- `watchdog.snapshot` は `result_summary` を一切読まない・保存しない。
  使うのは status / finished_at 等のメタ情報と、`error_text`
  （マスキング後のみ）だけである。
