# 設計書：稼働見守り台帳

本書は現行の動作仕様を記述する。型と関数の定義はテスト契約
`tests/interfaces.md` が正であり、本書では重複して定義しない。

## 1. 全体構成

### 1.1 コンポーネント

| # | コンポーネント | 種別 | 役割 |
|---|---|---|---|
| C1 | 定義表 | JSON ファイル（リポジトリ外） | 対象ごとの周期・許容遅延・タイムゾーン。本体はこれを読むだけ |
| C2 | 収集係 | エージェント実行（本プログラムの外） | `cron.status`／`cron.runs` を対象分だけ呼び、結果をスナップショット JSON（§8.1）に落とす |
| C3 | 判定プログラム | Python（純粋処理・標準ライブラリのみ） | 定義表＋スナップショット＋前回状態から状態5区分・期限超過・連続失敗・次回予定を判定し、台帳行を JSON／CSV で出力する。外部通信を一切しない |
| C4 | 状態ストア | VM ローカル JSON（リポジトリ外） | 対象ごとの累積状態（観測した最終成功時刻など。§4.3） |
| C5 | 死活記録 | VM ローカルファイル（リポジトリ外） | 見守り自身の実行記録。台帳とは別の場所に置く（§5） |
| C6 | 通知ペイロード | Python（生成と記録のみ） | 検出結果から通知ペイロードを生成し、outbox へ記録する。送信はしない（§7） |

### 1.2 データの流れ

```text
[定義表 JSON] ──┐
                ▼
収集係 ── cron.status / cron.runs（対象分のみ）
  │
  └→ スナップショット JSON
                ▼
判定プログラム（Python）←── 状態ストア（前回の累積状態）
  ├→ 台帳行 JSON／CSV（標準出力、または --out ファイル）
  ├→ 状態ストア更新（最終成功は単調増加でマージ。§4.3）
  ├→ 死活記録（last-run.txt と watchdog-heartbeat.jsonl）
  └→ 通知ペイロードを outbox/notifications.jsonl へ記録（送信しない）
```

### 1.3 動作原則

- 判定はコードに固定し、条件は定義表に外出しする：周期・許容遅延は
  定義表の値を使い、判定ロジック側に閾値を直書きしない。マスキングは
  コード側に固定し、設定で弱められない（§6）。
- 判定プログラムは純粋処理とする：入力はファイル、出力もファイル
  または標準出力。ネットワーク・Sheets・cron ツールに触れない。
- 台帳行の出力先は標準出力と `--out` ファイルのみで、Sheets への
  書き込みは行わない。
- 本プログラムは外部への送信機能を持たない。通知はペイロードの
  生成と outbox への記録までである。

## 2. 定義表の形式

- 形式は JSON とする。必須項目・周期表記・検証とエラー扱いは
  テスト契約 `tests/interfaces.md` §1 が正である（項目は
  `name`／`evidence_type`／`period`／`tolerance_seconds`／
  `timezone` の5項目）。
- 同梱物：サンプルは `config/definitions.sample.json`、自己試験用は
  `fixtures/definitions.json`。実定義はリポジトリ外のランタイム
  JSON（`~/workspace/cron-watchdog-data/definitions.json`）に置く。

## 3. 判定ロジック

### 3.1 判定式

- 正本：テスト契約 `tests/interfaces.md` §2 と
  `docs/design-notes.md`「状態判定」。

### 3.2 状態5区分の条件

- 正本：テスト契約 `tests/interfaces.md` §2。状態値は
  未実行／実行中／成功／失敗／判定不能の5値である。
- 最終成功が一度も無い対象は「未実行」であり、失敗にはならない。
  実行中・判定不能を失敗に混ぜない。

### 3.3 次回予定の算出

- 正本：テスト契約 `tests/interfaces.md` §3（最終成功＋周期）。
  スケジューラの `next_run_at` は判定・台帳には使わない。

### 3.4 連続失敗回数の数え方

- 関数としての正本：テスト契約 `tests/interfaces.md` §3。
- CLI 経路ではその関数を使わず、スナップショットが持つ status の
  `consecutive_failures` 実値をそのまま採用する
  （`watchdog/snapshot.py`）。

## 4. 実行履歴・証跡の取得方式

### 4.1 証跡の種類

- 正本：テスト契約 `tests/interfaces.md` §1。`evidence_type` は
  自由文字列であり、検証されるのは「空でない文字列」であること
  だけである。

### 4.2 スナップショットから使う情報

- `watchdog/snapshot.py` は status／runs のメタ情報のみを使う。
  `result_summary` は一切読まない・保存しない。`error_text` は
  マスキング後（§6）のみ取り出す。
- 最終成功は status の `last_success_at` を優先し、無い場合は
  runs の成功 run の `finished_at` の最大値から復元する。
- 対象がスナップショットに無い、または `collect_errors` に
  含まれる対象は、証跡なし（判定不能）として扱う。

### 4.3 履歴切り捨てへの対策（累積状態）

- 判定のたびに、観測した `last_success_at` を状態ストアへ
  単調増加でマージする（過去に戻らない）。一度観測した最終成功は
  以後の判定でも失われない。
- 判定時は、状態ストアに新しい最終成功があればそちらを採用する。

## 5. 見守り自身の死活記録

- 正本：テスト契約 `tests/interfaces.md` §4 と README のデータ表。
- 実態は2本立てである：最新1件は `last-run.txt`（プレーンテキストで
  ISO 時刻1行）、実行記録は CLI が追記する
  `watchdog-heartbeat.jsonl`（`run_id`／`mode`／`started_at`／
  `finished_at`／`result`／`targets_checked`／`anomalies`／
  `snapshot` を持つ JSONL）。集計・`stale` 判定は行わない。

## 6. エラーマスキングのルール

一次切り分けで出す情報は、コード側に固定し、設定で緩められない。
対象は `error_text` のみ。`result_summary` は一切使わない・
転載しない。

### 6.1 出力する項目

- 正本：テスト契約 `tests/interfaces.md` §5。出力型は同節の
  `SanitizedError` で、`error_type` は呼び出し側が与える文字列である。
- 上限は2つ併存する：`mask_sensitive` の既定上限は200文字、
  台帳・通知向け抜粋の上限は定数
  `watchdog.masking.EXCERPT_MAX_LENGTH` の120文字である。
  利用側は用途に応じて `max_length` に渡す。

### 6.2 除去・置換パターン（コード内固定の正規表現群）

| 種別 | 処理 |
|---|---|
| メールアドレス形式の文字列 | `[masked-email]` へ置換 |
| Bearer トークン | `Bearer [masked]` へ置換 |
| 認証情報系キーワード（token／secret／password／passwd／api_key／apikey／authorization／cookie／session 等）を含む「キー=値」「キー: 値」 | 値を `[masked]` へ置換 |
| `sk-` で始まるキー風文字列 | `[masked]` へ置換 |
| UUID 形式、長い英数字列（20文字以上） | `[masked-id]` へ置換 |
| 電話番号形式（日本の市外局番・ハイフン区切りの数字列） | `[masked-number]` へ置換 |
| ホームディレクトリ配下の絶対パス | `/home/<ユーザー名>`／`/Users/<ユーザー名>` の部分を `~` へ置換 |
| URL のクエリ文字列 | クエリを除去（スキーム＋ホスト＋パスまで） |
| 制御文字・改行 | 空格へ置換（1行化） |

- 処理順：上記のパターン置換 → 1行化 → 上限で切り捨てる。上限の
  値は §6.1（既定200／抜粋120）に従い、呼び出し側が
  `max_length` に渡す。
- 生の `error_text` はスナップショット JSON（VM ローカル、
  リポジトリ外）にのみ残る。

## 7. シャドー運用の実装

通知ペイロードの契約の正本はテスト契約 `tests/interfaces.md` §6。
実装はシャドー時もペイロードを返し（`should_notify=False`、
`suppressed_reason` に shadow の旨）、CLI が outbox に
`would_notify`／`suppressed_reason`／本文／検出名を記録する。
非シャドーで検出なしの場合は本文「異常なし」で
`should_notify=False` を返す。

### 7.1 フラグの持ち方

- 通知可否はランタイムフラグファイル
  `~/workspace/cron-watchdog-data/notify-flag.json` で持つ
  （リポジトリ外）。

```json
{"notify": false, "mode": "shadow", "changed_at": "2026-11-05T00:00:00+09:00", "note": "シャドー中"}
```

- ファイルが無い場合、および内容が読めない場合は
  `notify: false`（シャドー）として扱う（fail-safe：既定は
  通知しない）。有効になるのは `notify` が `true` の場合のみである。
- ゲートはこのフラグの単一判定であり、切替は手動編集のみである。
  自動有効化の経路は無い。

### 7.2 シャドー中の出力先

| 出力 | シャドー中 | 通知有効化後 |
|---|---|---|
| 台帳行（標準出力／`--out`） | 出力する | 出力する |
| ローカル記録（状態・heartbeat・スナップショット） | 残す | 残す |
| 通知ペイロード | `outbox/notifications.jsonl` に `would_notify: false` と `suppressed_reason`（shadow の旨）付きで記録する | `would_notify` はペイロードの `should_notify` に従う。本プログラムは送信しない |

### 7.3 通知有効化への切り替え手順（手動のみ）

1. 本人が確認したら、運用者が `notify-flag.json` の `notify` を
   `true` に、`changed_at` と `note`（確認日・確認経路）を更新する
   （1ファイルの手動編集のみ。コード変更は不要）。
2. 戻し方：同じファイルの `notify` を `false` に戻すだけである。

## 8. モジュール構成とインターフェース

- モジュールはリポジトリ直下のフラットな `watchdog/` パッケージ
  とする。一覧は README の構成表を参照。
- 関数・型の正本：テスト契約 `tests/interfaces.md` §1〜§6
  （型は `Definition`／`JobState`／`LedgerRow`／
  `SanitizedError`／`NotificationPayload` 等）。
- 依存：追加依存は無し（`pyproject.toml` の `dependencies = []`、
  Python 標準ライブラリのみ）。
- CLI の正本：README「使い方」（`check`／`heartbeat`／
  `shadow-status` の3コマンドと終了コード）。
- ランタイムデータはリポジトリ外に置く（置き場所は README の
  データ表が正）。

### 8.1 スナップショット JSON の形式（収集係との契約）

収集係（エージェント）はこの形式で書く。判定側はこの形式だけを読む。
読み込み側は構造検証のみを行い、`error_text` はマスキング後
（`sanitized_snapshot_errors` 経由）でのみ取り出す。
`result_summary` は一切読まない。

```json
{
  "collected_at": "2026-11-05T18:38:02+09:00",
  "collector": "cron-agent",
  "targets": {
    "daily-fortune-ensemble": {
      "status": {
        "enabled": true, "in_flight": false,
        "last_run_at": "2026-11-05T07:33:03+09:00", "last_status": "succeeded",
        "last_success_at": "2026-11-05T07:33:03+09:00",
        "consecutive_failures": 0,
        "next_run_at": "2026-11-06T07:08:00+09:00",
        "resolved_timezone": "Asia/Tokyo"
      },
      "runs": [
        {"run_id": "...", "status": "succeeded",
         "scheduled_for": "2026-11-05T07:08:00+09:00",
         "started_at": "2026-11-05T07:08:00+09:00",
         "finished_at": "2026-11-05T07:33:03+09:00",
         "attempt": 1, "trigger_reason": "scheduled", "error_text": null}
      ]
    }
  },
  "collect_errors": {"<job_id>": "SOURCE_MISSING"}
}
```

- 時刻はすべて ISO 8601（オフセット付き）。epoch 秒で来た値は
  収集係が変換する。
- `error_text` は生のまま入れてよい（保存先は VM ローカル限定）。
- 対象が取得できなかった場合は `targets` から省き、
  `collect_errors` に理由コードを入れる（判定側が判定不能にする）。

## 9. 試験方法

実在の定例は止めず、試験用定義と偽スナップショットだけで検証する。
手順とコマンドは README「自己試験」節のとおりである。

- `fixtures/definitions.json` と `fixtures/snapshot.json` を使う。
- `watchdog-selftest-overdue`（最終成功が3日前）だけが
  「失敗（期限超過）」として検出され、`watchdog-selftest-fresh` は
  「成功」になることを確認する。
- シャドー前提のため、通知は outbox の記録止まりで、実送信は
  起きないことを確認する。
