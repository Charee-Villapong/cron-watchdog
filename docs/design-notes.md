# 仕様メモ

## 状態判定

- 状態判定の式：`now <= 最終成功 + 周期 + 許容遅延 → 成功`、
  それ以外は失敗（期限超過）。境界（ちょうど期限時刻）は成功側に
  倒す。分岐の全体はテスト契約（`tests/interfaces.md` §2）が正。

## 定義表の形式

- 定義表の形式は **JSON** とする。
  - ランタイム定義: `~/workspace/cron-watchdog-data/definitions.json`
    （リポジトリ外）
  - サンプル: `config/definitions.sample.json`

## モジュール構成

- モジュールはリポジトリ直下のフラットな `watchdog/` パッケージに
  置く（import は `watchdog.xxx`）。
- テスト契約の6モジュール（definitions / status / ledger /
  heartbeat / masking / notify）に、snapshot（スナップショット
  取り込み）・state（状態ストアの累積マージ）・cli・clock
  （現在時刻の解決）を加えた構成である。

## マスキング上限

- `mask_sensitive` の既定上限は 200 文字である。
- 台帳・通知向け抜粋の上限 120 文字は
  `watchdog.masking.EXCERPT_MAX_LENGTH` として定数化してある
  （利用箇所で `max_length` に渡す）。

## スナップショットの個人情報対策

- `watchdog.snapshot` は `result_summary` を一切読まない・保存しない。
  使うのは status / finished_at 等のメタ情報と、`error_text`
  （マスキング後のみ）だけである。
