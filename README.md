# cron-watchdog（稼働見守り台帳）

定例 cron が「最後にいつ成功したか」を台帳化し、周期と許容遅延を超えた
期限超過を検出する見守りプログラムです。判定は純粋な Python 処理で、
外部通信は行いません。導入初期はシャドー運用（検出しても通知しない）
が前提です。

- 親 Issue: https://github.com/Charee-Villapong/ai-organization/issues/3
- 設計書: `docs/design.md` / 実装メモ（設計との差分）: `docs/design-notes.md`
- テスト契約: `tests/interfaces.md`

## 構成

| モジュール | 役割 |
|---|---|
| `watchdog/definitions.py` | 定義表（JSON / dict 行）の読み込みと検証 |
| `watchdog/status.py` | 状態5区分の判定（未実行 / 実行中 / 成功 / 失敗 / 判定不能） |
| `watchdog/ledger.py` | 台帳行の生成、次回予定、連続失敗回数、期限超過検出 |
| `watchdog/snapshot.py` | 収集係スナップショット JSON から JobState を構築 |
| `watchdog/state.py` | 状態ストアへの累積マージ（最終成功は単調増加） |
| `watchdog/heartbeat.py` | 見守り自身の死活記録（台帳とは別ファイル） |
| `watchdog/masking.py` | エラー情報のマスキング（コード固定、設定で緩められない） |
| `watchdog/notify.py` | 通知ペイロードの生成とシャドーフラグの読み取り（送信はしない） |
| `watchdog/cli.py` | CLI（`python -m watchdog ...`） |

状態判定の定義は、テスト契約 `tests/interfaces.md` §2 と
`docs/design-notes.md`「状態判定の計算式」を正本とします。
本書では判定式を重複して記載しません（実行中・判定不能を
失敗に混ぜない点も同所が正です）。

## 使い方

```bash
# 判定 → 台帳行（JSON）を標準出力 + 状態ストア更新 + ハートビート記録
python -m watchdog check \
  --definitions ~/workspace/cron-watchdog-data/definitions.json \
  --snapshot <収集係が作ったスナップショット.json> \
  --state ~/workspace/cron-watchdog-data/state.json \
  --data-dir ~/workspace/cron-watchdog-data

# CSV 形式で出す場合
python -m watchdog check ... --format csv

# ハートビートのみ記録
python -m watchdog heartbeat --data-dir ~/workspace/cron-watchdog-data

# シャドーフラグの状態表示
python -m watchdog shadow-status --data-dir ~/workspace/cron-watchdog-data
```

終了コード: 0 = 正常、2 = 一部が判定不能（partial）、1 = 実行自体の失敗。

テスト:

```bash
python -m pytest tests/ -q
```

## データディレクトリ（リポジトリ外）

ランタイムデータはリポジトリには入れず、`~/workspace/cron-watchdog-data/`
に置きます。

| パス | 内容 |
|---|---|
| `definitions.json` | 実定義表（対象ごとの周期・許容遅延・タイムゾーン） |
| `state.json` | 状態ストア（観測した最終成功時刻の累積） |
| `watchdog-heartbeat.jsonl` | 見守り自身の実行記録（追記専用） |
| `last-run.txt` | 見守りの最終実行時刻（最新1件） |
| `notify-flag.json` | 通知フラグ（`{"notify": false, "mode": "shadow", ...}`） |
| `snapshots/` | 収集係が置くスナップショット JSON |
| `outbox/notifications.jsonl` | 通知の下書き・記録（送信はしない） |

スナップショット JSON の形式は `docs/design.md` §10.4 に従います。
スナップショット内の `result_summary` は個人情報を含みうるため、
本プログラムは一切読み取りません（使うのは status / finished_at 等の
メタ情報と、マスキング後の `error_text` のみ）。

## シャドー運用と通知の有効化

- 既定はシャドーです。`notify-flag.json` が無い場合もシャドーとして
  扱います（fail-safe: 既定は通知しない）。
- シャドー中、検出結果は台帳データと `outbox/notifications.jsonl` の
  下書き（`would_notify` / `suppressed_reason: shadow...`）にだけ残り、
  外部への送信は一切行いません。本プログラム自体にも送信機能は
  ありません（通知はペイロード生成まで）。
- 通知を有効化する場合は、**本人の確認後**に運用者が
  `notify-flag.json` の `notify` を `true` に手動で変更します
  （`mode` / `changed_at` / `note` も更新）。コード変更は不要です。
  戻す場合は `notify` を `false` に戻すだけです。

## 自己試験（期限超過の意図的検出）

実在の定例は止めず、試験用定義と偽スナップショットだけで検証します。

```bash
python -m watchdog check \
  --definitions fixtures/definitions.json \
  --snapshot fixtures/snapshot.json \
  --state /tmp/wd-state.json --data-dir /tmp/wd-data \
  --now 2026-11-05T12:00:00+09:00
```

`fixtures/` の `watchdog-selftest-overdue`（最終成功が3日前）だけが
「失敗（期限超過）」として検出され、`watchdog-selftest-fresh` は
「成功」になることを確認できます。
