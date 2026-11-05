# 設計書：稼働見守り台帳（AI組織 Issue #3）

- 役割：開発部 Architect（本書は設計のみ。コードは書かない）
- 親 Issue：GitHub リポジトリ `Charee-Villapong/ai-organization` Issue #3「[企画] 稼働見守り台帳」（承認済み→実行中）
- 正本規約：同リポジトリ `docs/組織設計書.md` §5（開発部規約）
- 作成日：2026-11-05
- 状態：Executor／テスト係への引き渡し用・確定設計（§12 の未確定事項はコーディネーター判断待ち）

## 0. 設計の前提（実物確認済みの事実）

設計に先立ち、以下を実物で確認した。本書の判断はすべてこの事実に基づく。

1. **cron 定義**は Markdown＋YAML frontmatter（`id`／`title`／`enabled`／`owner`／`mode`／`schedule{kind, timezone, time, dow, dom, every}`／`delivery`）として `~/workspace/cron.d/**` と `~/workspace/goals/*/crons/**` に投影コピーが存在する。ただしこれらは**読み取り専用の投影**であり、定義の正本ではない（編集しても実ジョブは変わらない）。
2. **cron 実行履歴はファイルとして存在しない。** エージェントの `cron.runs`／`cron.status` ツール経由でのみ取得できる。素の Python プログラムからは直接読めない。
3. `cron.status`（ジョブ単位）は次を返す：`enabled`、`in_flight`、`running_runs`、`queued_runs`、`last_run_at_*`、`last_status`、**`last_success_at_*`**、**`consecutive_failures`**、**`next_run_at_*`**、`blocked`、`schedule`。つまり「最終成功時刻・連続失敗回数・次回予定」は status だけで一次取得できる。
4. `cron.runs` は run ごとに `run_id`、`job_id`、`status`（`succeeded`／`failed` 等）、`scheduled_for_utc`／`scheduled_for_local`、`started_at_utc`、`finished_at_utc`（epoch 秒）、`attempt`、`error_text`（null 可）、`result_summary`、`trigger_reason`（`scheduled` 等）、`timezone` を返す。
5. `cron.runs` の応答には **`history_may_be_truncated: true`** が付く。履歴の保持深さは保証されない。→ 見守り側は取得のたびに自前の累積状態へ取り込み、履歴だけに依存しない構造が必須（§5.4）。
6. **`result_summary` には個人情報を含みうる本文がそのまま入る**（実データで確認）。→ 台帳・報告へは `result_summary` を一切転載しない。一次切り分けに使うのは `error_text` のみ、かつマスキング必須（§7）。これは IT 必須フィードバック4件目の実証的根拠でもある。
7. 対象候補5本は定義ファイルを実読して確認した（§3.3）。うち `threads-tech-collection` は 2026-11-04 の実行が失敗しており（`last_status=failed`、`consecutive_failures=1`、最終成功 2026-11-02）、シャドー期間の実地ケースとして使える。
8. Google Sheets コネクタは利用可（作成・読み書き・書式）。ただしコネクタは**エージェントのツール**であり、Python ライブラリではない。→ シート書き込みはエージェント層が担う（§5.3）。
9. 既存の定例 cron 本体には一切変更を加えない。送信・削除等の不可逆操作は行わない。費用は0円（既存VM・cron・Sheets・既存ログのみ）。

---

## 1. 全体構成

### 1.1 コンポーネント

| # | コンポーネント | 種別 | 役割 |
|---|---|---|---|
| C1 | 定義表 `config/targets.yaml` | 設定ファイル（Git管理） | 対象ごとの「成功の定義」。本体はこれを読むだけ（IT必須1） |
| C2 | 収集係（Collector） | エージェント実行（見守り cron の前段手順） | `cron.status`／`cron.runs` を対象分だけ呼び、結果をスナップショット JSON に落とす。`@user.current` のタイムゾーンを収集時点で IANA 名へ解決して記録する |
| C3 | 証跡プローブ（Probe） | Python（純粋処理） | 成果物ファイルの有無・更新時刻、成果物 JSON のキー時刻を VM ローカルで確認する |
| C4 | 判定プログラム（Judge） | Python（純粋処理・標準ライブラリ＋PyYAML のみ） | 定義表＋スナップショット＋プローブ結果＋前回状態 → 状態5区分・期限超過・連続失敗・次回予定を判定し、台帳行・異常イベント・週次要約の**データ**を JSON で出力する。外部通信を一切しない |
| C5 | 状態ストア（State Store） | VMローカル JSON | 対象ごとの累積状態（観測した最終成功時刻など）。履歴切り捨てへの耐性を持つ（§5.4） |
| C6 | 死活記録（Heartbeat Store） | VMローカル JSONL | 見守り自身の実行記録。台帳（Sheets）とは別の場所（IT必須3、§6） |
| C7 | 台帳ライタ（Ledger Writer） | エージェント実行（見守り cron の後段手順） | Judge の出力 JSON を受け、Sheets コネクタで台帳へ書き込み、読み戻して検証する |
| C8 | 報告係（Reporter） | エージェント実行（週次 cron＋異常時） | 週次要約を組み立てて届ける。通知フラグを再確認してから送る二重ゲート（§9）。一次切り分け（§7のマスキング済み情報の範囲内）もここが担う |
| C9 | 見守り cron（check） | 新規 cron（エージェント実行） | C2→C4→C7 をつなぐ定期実行。初期は6時間ごと（§5.5） |
| C10 | 週次要約 cron | 新規 cron（エージェント実行） | C8 を週1回実行する。check とは別ジョブにし、片方が止まってももう片方から異常に気づける余地を残す |

### 1.2 データの流れ

```text
[定義表 targets.yaml]──┐
▼
見守り cron 起動 → C2 収集係 ── cron.status / cron.runs（対象分のみ）
│ │
│ └→ スナップショット JSON（data/snapshots/）
▼
C4 Judge（Python）←── C3 Probe（成果物ファイル/JSON の時刻）
│ ←── C5 State Store（前回の累積状態）
├→ 判定結果 JSON（状態・期限・連続失敗・次回予定・マスク済みエラー）
├→ C5 State Store 更新（最終成功は単調増加でマージ）
├→ C6 Heartbeat 追記（見守り自身の実行記録）
└→ 台帳行 JSON / 異常イベント JSON / 通知下書き（outbox）
▼
C7 台帳ライタ ── Sheets コネクタ → [台帳スプレッドシート]
└→ 読み戻し検証（行数・状態セルの一致）

週次 cron 起動 → C8 Reporter ←── C6 Heartbeat（過去7日）＋ 異常イベント蓄積
└→ 週次要約（異常の有無＋見守り自身の稼働状況）
※ 通知フラグ ON のときだけ配信。シャドー中は §9 の扱い
```

### 1.3 設計原則

- **判定はコードに固定、条件は定義表に外出し**：閾値・周期・許容遅延はすべて定義表と設定ファイルの変数に置く（変数化の徹底規約）。判定ロジック自体（状態遷移・マスキング）はコード側に固定し、設定で弱められないようにする。
- **Judge は純粋処理**：入力はファイル、出力もファイル。ネットワーク・Sheets・cron ツールに触れない。よってテスト係が fixture だけで全判定を検証できる。
- **エージェント層は「手」だけ**：収集（cron ツール呼び出し）と書き込み（Sheets コネクタ）はエージェントが担い、判断はしない。エージェントの注意力に依存するのは転送部分のみに限定する。
- **正常時は静か**：check 実行はチャットへ何も届けない（シートとローカル記録のみ）。届くのは週次要約と、通知有効化後の異常報告だけ。

---

## 2. コードの置き場所

### 2.1 判断：新規の非公開リポジトリを作成する

- **リポジトリ名（第一案）：`cron-watchdog`**（個人アカウント側、非公開）
- 既存リポジトリの命名（`ai-organization`、`mac-connection`、`kids-mac-notify`、`fortune`）と同じ英語ケバブケースにそろえた。対象が cron 全般であり、特定の定例に紐づかないため、対象名を含まない名前が適切。
- 代替名：`watchdog-ledger`（台帳寄り）、`cron-ledger`（記録寄り）。「検知する仕組み」であることが伝わる `cron-watchdog` を推す。
- 作業コピーは既存慣例どおり `~/workspace/github-mirrors/cron-watchdog`。
- 組織側 Issue #3 を**親**とし、新リポジトリ側に作業 Issue を作って相互リンクする（組織設計書 §4「実行が別リポジトリにまたがる企画は、本リポジトリの Issue を親としてリンク」）。
- ブランチは Issue 番号に紐づける（組織設計書 §5.1 Executor 規約）。push 前検閲スクリプト通過時のみ push 可（同 §5.1 Reporter 規約）。
- **ランタイムデータはリポジトリに入れない**：状態・スナップショット・死活記録・通知フラグ・台帳スプレッドシートID等の環境値は `~/workspace/cron-watchdog-data/`（リポジトリ外）と `config.local.json`（.gitignore 対象）に置く。リポジトリに入るのはコード・定義表・テスト・README のみ。

### 2.2 代替案との比較

| 案 | 内容 | 長所 | 短所 | 判定 |
|---|---|---|---|---|
| A | **新規リポジトリ `cron-watchdog`** | 1プロジェクト=1リポジトリの既存慣例（fortune／mac-connection／kids-mac-notify）に一致。独立したテスト・履歴・検閲ゲートを持てる。VM が差し替わっても復元できる | リポジトリが1つ増える | **採用** |
| B | `ai-organization` リポジトリ内にコードを置く | 親 Issue と同じ場所で見通しが良い | 組織リポジトリは設計書・環境台帳・決定履歴という「管理の正本」。実行コードを混ぜると正本の性格が濁り、push 前検閲や変更管理の単位も混線する。組織設計書 §4 自身が「実行が他リポジトリにまたがる」形を前提にしている | 不採用 |
| C | 既存リポジトリ（`mac-connection` 等）へ相乗り | 新規作成が不要 | ドメインが無関係（Mac GUI自動化と cron 監視）。履歴・README が混ざり将来の棚卸しで必ず困る | 不採用 |
| D | リポジトリを作らず VM ローカルのみに置く | 最速で始められる | VM は差し替わりうる（環境台帳）。版管理・バックアップ・検閲ゲートが無く、組織の規約（GitHub で管理、push 前検閲）にも反する | 不採用 |

---

## 3. 定義表の形式

### 3.1 形式の選択

- **YAML ファイル `config/targets.yaml`**（新リポジトリ内、Git 管理）。
- 理由：cron 定義自体が YAML frontmatter であり、書式の学習コストが無い。Git の差分で「いつ・どの条件を変えたか」が残り、シャドー期間の調整履歴そのものになる。シート側には §8 の「定義」タブへ写しを置き、閲覧はシートでもできるようにする（正本は YAML）。
- 代替案（シート自体を定義表にする）は、版管理ができず、プログラムからの読み取りがエージェント経由になり判定の純粋性（§1.3）が崩れるため不採用。代替案（JSON）は手編集時の可読性で YAML に劣るため不採用。
- 本体（Judge）は定義表を読むだけ。**判定条件の調整＝このファイルの変更**で済む構造にする（IT必須1）。

### 3.2 全項目

| 項目 | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | ○ | 対象 cron のジョブ ID（cron 定義の `id` と完全一致させる。Judge はこの ID でスナップショットを引く） |
| `display_name` | string | ○ | 台帳の表示名（cron 定義の `title` を基本とする。人名・連絡先は入れない） |
| `enabled` | bool | ○ | 見守りの有効／無効。`false` の行は判定・台帳更新の対象外（定義タブにのみ残る） |
| `schedule.kind` | enum | ○ | `daily`／`weekly`／`monthly`／`interval`／`yearly`（cron の schedule.kind と同じ語彙） |
| `schedule.time` | string `HH:MM:SS` | kind により必須 | daily／weekly／monthly／yearly の発火時刻 |
| `schedule.dow` | list[string] | weekly 時必須 | `Mon`〜`Sun` |
| `schedule.dom` | list[int] | monthly 時必須 | 日（1〜31） |
| `schedule.every` | string | interval 時必須 | `30m`／`6h` 等（cron の `every` 表記をそのまま） |
| `timezone` | string | ○ | 判定に使うタイムゾーン。IANA 名（例 `Asia/Tokyo`）か `@user.current`。`@user.current` の場合は収集係が収集時点の解決済み IANA 名をスナップショットに記録し、Judge はそれを使う（IT必須1の「判定タイムゾーン」） |
| `grace` | string（期間） | ○ | 許容遅延。`120m`／`3h` の形。予定時刻＋この猶予を過ぎても成功が無ければ期限超過候補（§4） |
| `evidence.kind` | enum | ○ | 成功の証跡の種類：`cron_status`／`artifact_file`／`artifact_json`／`cron_or_artifact`／`cron_and_artifact`（§5.2） |
| `evidence.path` | string | artifact 系で必須 | 成果物ファイルのパス（`~` 展開可）。日付入りの場合は `evidence.glob` を使う |
| `evidence.glob` | string | 任意 | 日付プレースホルダ `{date}`（対象タイムゾーンの日付 `YYYY-MM-DD`）を含むパターン |
| `evidence.json_key` | string | artifact_json で必須 | 成果物 JSON 内の「最終更新を示すキー」のドットパス（例 `last_batch.collected_at`）。キー値が ISO 8601 時刻、またはファイル更新時刻で代替する場合は `mtime` と書く |
| `failure_threshold` | int | 任意（既定 2） | 連続失敗がこの回数以上で、期限超過とは独立に「失敗」とする閾値（§4.4）。周期内に複数回走る interval 系で効く |
| `expected_duration` | string（期間） | 任意（既定 `60m`） | 1回の実行にかかる想定上限。「実行中」判定の打ち切り（§4.2）に使う。cron 側に `timeout_secs` がある対象はそれに合わせる |
| `notes` | string | 任意 | 定義上の注意（例：成果物が無い日も正常な理由）。個人情報は書かない |

### 3.3 定義例（実在確認済み5本）

いずれも定義ファイルを実読して確認した値である（発火時刻・曜日・タイムゾーンは実定義どおり）。

```yaml
targets:
- id: daily-fortune-ensemble
display_name: 毎朝のアンサンブル占い
enabled: true
schedule: { kind: daily, time: "07:08:00"}
timezone: Asia/Tokyo # 実定義も Asia/Tokyo 明示
grace: 120m # 実績では発火から完了まで約25分。初期値は余裕を持ちシャドーで調整
evidence:
kind: cron_or_artifact
glob: "~/workspace/goals/goal-4/hidden_files/fortune-{date}.pdf"
failure_threshold: 2
expected_duration: 60m
notes: 成果物PDFの日付は対象日のもの。当日分ファイルの存在を cron 成功の裏取りに使う

- id: diary-daily-reminder
display_name: 日記リマインド（毎日22時頃）
enabled: true
schedule: { kind: daily, time: "22:08:00"}
timezone: "@user.current" # 実定義が @user.current。収集時に解決して記録
grace: 120m
evidence:
kind: cron_status # その日すでに記入済みなら何も送らず正常終了するため、成果物では判定できない
failure_threshold: 2
expected_duration: 30m
notes: 成功の定義は「run が succeeded であること」そのもの

- id: threads-tech-collection
display_name: Threads技術情報の定期収集（月・水・金）
enabled: true
schedule: { kind: weekly, time: "09:08:00", dow: [Mon, Wed, Fri]}
timezone: "@user.current"
grace: 180m # timeout 3600s の長尺ジョブ。実績の所要は約30分
evidence:
kind: cron_or_artifact
path: "~/workspace/goals/threads/hidden_files/state.json"
json_key: mtime # state.json の更新時刻を証跡にする（キー時刻の確定は Executor の初回調査で）
failure_threshold: 2
expected_duration: 60m
notes: 2026-11-04 実行分が失敗中（連続失敗1）。シャドー期間の実地ケースになる

- id: protein-reminder-morning
display_name: プロテイン通知（朝）
enabled: true
schedule: { kind: daily, time: "09:00:00"}
timezone: Asia/Tokyo
grace: 120m
evidence:
kind: cron_status # チャット通知のみで成果物ファイルは無い
failure_threshold: 2
expected_duration: 15m

- id: protein-reminder-night
display_name: プロテイン通知（夜）
enabled: true
schedule: { kind: daily, time: "23:30:00"}
timezone: Asia/Tokyo
grace: 120m # 日付をまたぐため、判定は日付ではなく日時で行う（§4.5）
evidence:
kind: cron_status
failure_threshold: 2
expected_duration: 15m
```

- 導入は上記5本から開始し、安定後に残りの定例（電気・売電・水道の月次、Gmail 月次整理、上場ウォッチ、CBT 週次 等）へ広げる。**runonce（単発）は対象外**。`enabled: false` のジョブ（例：現在無効化されている監視系ジョブ）は定義に載せない／載せる場合は `enabled: false` とする。

---

## 4. 判定ロジック

### 4.1 入力と基本量

判定は対象ごとに、判定時刻 `now`（対象タイムゾーンへ変換した aware datetime）に対して以下を計算する。

- `last_due`：`now` 以前で最も新しい予定発火時刻（§4.5 の算出）。予定が1つも無い場合は `None`。
- `next_due`：`now` より後で最も近い予定発火時刻。
- `deadline = last_due + grace`（`last_due` が無い場合は定義登録時刻＋最初の周期で代替せず、§4.2 の未実行扱い）。
- `last_success_at`：次のうち最も新しいもの（すべて対象タイムゾーンへ正規化）。
1. `cron.status` の `last_success_at`
2. 状態ストアに累積された観測済み最終成功（履歴切り捨て対策、§5.4）
3. 証跡が artifact 系を含む場合、成果物から得た成功時刻（その成果物が `last_due` 以降の回に対応する場合のみ有効。日次ファイルなら対象日が `last_due` の日付と一致すること）
- `consecutive_failures`：§4.4 の数え方。
- `covers_last_due = (last_success_at is not None and last_success_at >= last_due)`

「期限超過」の定義（企画書の「最終成功＋周期＋許容遅延」と等価な、予定表ベースの形で実装する）：

> **期限超過 ⇔ `now > deadline` かつ `covers_last_due == False`**
> （＝直近の予定回について、許容遅延を過ぎても成功の証跡が無い）

予定表ベースにする理由：weekly（金→月は72時間）や monthly では「周期」が一定でなく、「最終成功＋固定周期」では誤判定するため。daily のような等間隔では両者は一致する。台帳には参考値として「最終成功からの経過時間」も出すが、判定には使わない。

### 4.2 状態5区分の決定手順

上から順に評価し、最初に該当したものを状態とする（IT必須2。実行中・判定不能を失敗に混ぜない）。

| 順 | 状態 | 条件 |
|---|---|---|
| 1 | **判定不能** | スナップショットに対象が無い／収集自体が失敗した／スケジュール定義が解釈できない／タイムゾーンを解決できない／証跡の所在が読めない（パーミッション等）——のいずれかで、他の証跡からも代替判定できない場合。理由コードを必ず付ける（`SOURCE_MISSING`、`COLLECT_FAILED`、`SCHEDULE_UNPARSEABLE`、`TZ_UNRESOLVED`、`EVIDENCE_UNREADABLE`） |
| 2 | **実行中** | `cron.status` の `in_flight == true` または `running_runs > 0`。または最新の run が `started_at` を持ち `finished_at` が無く、`now < started_at + expected_duration`。打ち切り（`expected_duration` 超過）後は実行中とはせず、次段以降で判定する（止まった実行を「実行中」と偽り続けない） |
| 3 | **未実行** | run 記録が1件も無く、かつ `now <= deadline`（初回の期限内）。登録直後・初回発火前がここに入る。run が無く期限も過ぎていれば未実行ではなく次段の失敗（理由 `NEVER_RAN_OVERDUE`） |
| 4 | **成功** | `covers_last_due == True` かつ連続失敗が閾値未満。直近の予定回が成功でカバーされている正常状態 |
| 5 | **失敗** | 次のいずれか：(a) 期限超過（§4.1）＝理由 `OVERDUE`／一度も成功が無く期限超過＝`NEVER_RAN_OVERDUE`、(b) `consecutive_failures >= failure_threshold` かつ最新の完了 run が失敗＝理由 `CONSECUTIVE_FAILURES`、(c) 最新の予定回の run が失敗として完了し、`now > last_due + grace`（成功の見込みが無い）＝理由 `LAST_RUN_FAILED` |

補足ルール：

- 状態とは別に `reason_code`（上記の英語コード）と、人の言葉の短い補足を必ず保持し、台帳の「一次切り分け」列に出す。
- `enabled: false` の実ジョブは収集結果にそう出る。定義側 `enabled: true` なのに実ジョブが無効化されている場合は、失敗ではなく **判定不能（理由 `JOB_DISABLED`）** とし、週次要約で「対象ジョブが無効化されている」ことを別行で知らせる（止めたのは故障とは限らないため）。
- 前回状態との差分（成功→失敗、失敗→成功）は §8 の異常イベントとして記録する。状態が失敗のまま続く間は、イベントを毎回追加しない（初回検出と回復のみ）。

### 4.3 次回予定の算出

- 第一情報源は `cron.status` の `next_run_at`（スケジューラの実値）。台帳にはこれを使う。
- status が取得できない場合のフォールバックとして、定義表のスケジュールから §4.5 で計算した `next_due` を使い、台帳上は算出元を区別しない（判定不能の判断材料にはしない）。

### 4.4 連続失敗回数の数え方

1. 第一情報源は `cron.status` の `consecutive_failures`（スケジューラの実値）。
2. status が無い場合は `cron.runs` から自力で数える：完了した run を `finished_at` 降順に並べ、**予定回（`scheduled_for`）単位に束ねて**（リトライの `attempt` 違いを1回と数える）、直近から連続する「最終状態が失敗」の回数を数える。成功が現れた時点で止める。
3. 手動実行（`trigger_reason!= scheduled`）の成否は連続失敗に数えない（予定回の成否ではないため）。ただし手動成功で `last_success_at` が更新される点は §4.1 のとおり扱う。※この解釈は §12 の確認事項。
4. 状態ストアには観測した最大の連続失敗ではなく「最新の観測値」を保持する（リセットを検知するため）。

### 4.5 予定時刻の算出方法（`last_due`／`next_due`）

定義表のスケジュールを対象タイムゾーンで解釈する純粋関数として実装する（§10 の `last_due`／`next_due`）。

- `daily`：毎日 `time`。
- `weekly`：`dow` の曜日の `time`。
- `monthly`：`dom` の各日の `time`。存在しない日（31日指定で30日までの月など）はその月は発火しないものとして扱う（cron 実挙動との差異はシャドーで照合する）。
- `interval`：基準時刻が定義表だけでは決まらないため、`cron.status`／直近 run の `scheduled_for` から位相を取る。status が無ければ判定不能（`SCHEDULE_UNPARSEABLE` ではなく `SOURCE_MISSING`）。
- `yearly`：`dom`＋月（定義表に `month` を追加してよい）＋`time`。
- 計算は日付ではなく**日時**で行い、日付またぎ（23:30 発火＋猶予で翌日になる等）を自然に扱う。うるう年・月末は `datetime`／`zoneinfo` の暦計算に任せる。日本は DST が無いが、`zoneinfo` で一般化しておく。

---

## 5. 実行履歴・証跡の取得方式

### 5.1 方式の比較

| 案 | 方式 | 長所 | 短所 | 判定 |
|---|---|---|---|---|
| A | **ハイブリッド（エージェント収集＋純粋判定）**：見守り実行自体を cron のエージェント実行とし、収集係が `cron.runs`／`cron.status` の結果をスナップショット JSON に落として Judge へ渡す。成果物証跡は Judge が直接確認 | 実行履歴の実値（最終成功・連続失敗・次回予定）が使える唯一の現実解。判定は純粋処理でテスト可能。既存 cron に無変更 | エージェント実行のぶんトークン消費がある。収集手順はエージェントの実行品質に依存する（→ 手順を cron 本文に固定し、出力形式をスキーマ検証で縛る） | **第一案（採用）** |
| B | 成果物ファイルの更新時刻のみで判定（純粋 Python のみ） | 単純・高速・無コスト。エージェント不要 | 成果物の無い定例（日記リマインド＝記入済みなら無送信、プロテイン＝通知のみ）が判定できない。「処理は成功したが成果物が無い日」を誤検知する＝本企画最大のリスクを正面から踏む | 不採用（ただし証跡の一種として A に組み込む） |
| C | 各定例が自分のハートビートファイルを書く方式 | 最も確実な証跡 | **既存 cron 本体への変更が必要**であり、本企画の制約（既存定例に一切触れない）に反する | 不採用 |
| D | エージェント内部の記録DBを直接読む | ツールを介さず取得できる可能性 | 記録の形式・所在は非公開の実装詳細で、保証が無く、VM 差し替えやバージョン変更で壊れる。目的別ツール（`cron.runs`）がある以上、迂回はしない | 不採用（調査のみ。採用しない） |

### 5.2 証跡の種類と優先順位（定義表 `evidence.kind`）

| kind | 意味 | 向く対象 |
|---|---|---|
| `cron_status` | run の成否そのものを成功の定義とする | 成果物の無い通知系（プロテイン、日記リマインド） |
| `artifact_file` | 成果物ファイルの存在と更新時刻 | 日次でファイルを作る定例 |
| `artifact_json` | 成果物 JSON の更新（キー時刻またはファイル更新時刻） | 状態ファイルを持つ定例（Threads 収集） |
| `cron_or_artifact` | どちらか一方で成功とみなす（緩い） | 導入初期の既定。誤検知を避けたい対象 |
| `cron_and_artifact` | 両方そろって成功（厳しい） | 「run は成功したが成果物ができていない」を検出したい対象。シャドーで誤判定が無いと確認できてから切り替える |

### 5.3 Sheets 書き込みの担い手

- v1 では **エージェント層（台帳ライタ）が Sheets コネクタで書く**。Judge は台帳行を JSON で出すだけ。
- VM にはコネクタ CLI の実体があるため、Python からサブプロセスで呼ぶ案も技術的にはありうるが、認証文脈がエージェント実行と同一か未検証。**v1 では依存しない**。Executor の初期タスクとして可否を検証（spike）し、可能なら v2 で Judge からの直接書き込みへ寄せる（§12）。

### 5.4 履歴切り捨てへの対策（累積状態）

- Judge は毎回、観測した `last_success_at` を状態ストアへ**単調増加でマージ**する（過去に戻らない）。`cron.runs` の履歴が浅くなっても、見守りが一度観測した最終成功は失われない。
- 逆に、状態ストアの最終成功が古いまま `cron.status` が新しい成功を示せば status を優先する（§4.1 の max）。
- 状態ストアは VM ローカル（リポジトリ外）に置く。バックアップは週次要約 cron が状態の要約を台帳シート「定義」タブ脇へ書くことで代替し、専用の仕組みは作らない（過剰設計を避ける）。

### 5.5 見守り cron の実行設計

- check cron：**6時間ごと**（`:38` 分発火。既存定例の `:08`／`:00`／`:30` 集中を避ける）。1回の処理：対象数×（status 1回＋runs 1回）＋ Judge 実行＋シート更新。初期対象5本では軽い。
- 間隔は設定値（cron のスケジュール）であり、シャドー結果を見て 2回/日 へ落とす等の調整は PM 判断（§12）。
- 週次要約 cron：**月曜 08:38**（前週分の要約。占い 07:08 の後、Threads 収集 09:08 の前）。
- どちらの cron 本文にも「既存定例の変更禁止」「送信はフラグ確認後」等の線引きを明記し、本文は新リポジトリで版管理する（cron 本体の正本はスケジューラ側だが、手順書として控えを置く）。

---

## 6. 見守り自身の死活記録

- **保存先**：台帳（Sheets）とは別の場所として、VM ローカル `~/workspace/cron-watchdog-data/watchdog-heartbeat.jsonl`（追記専用 JSONL）。もう1ファイル `last-run.json` に最新1件を上書きで置く（IT必須3）。
- **1行の形式**：

```json
{"run_id":"<uuid>","mode":"check","started_at":"2026-11-05T18:38:02+09:00","finished_at":"2026-11-05T18:38:41+09:00","result":"ok","targets_checked":5,"anomalies":["threads-tech-collection"],"snapshot":"snapshots/2026-11-05T183802.json"}
```

- `result` は `ok`／`partial`（一部対象が判定不能）／`error`（収集または判定自体が失敗）。
- 個人情報・エラー原文は入れない。異常対象は ID のみ。
- **書き手**：check／週次どちらの見守り実行も、最後に必ず1行追記する（失敗時も `result: error` で追記するよう cron 本文に固定する。プロセス自体が起動しなかった場合は行が増えない＝それ自体が異常の証跡）。
- **週次要約への含め方**：週次要約 cron が過去7日の heartbeat を集計し、要約に独立した1行を必ず含める。
- 例：「見守り自体：最終実行 11/10 06:38、過去7日 28回中28回実行（異常なし）」
- 期待回数は check のスケジュールから算出する（6時間ごと＝28回/週）。実績が期待を下回る／最終実行が12時間より古い場合は、要約の先頭で「見守り自体が止まっている疑い」として目立たせる。
- **残存リスク**：check と週次要約の両方が止まると誰も知らせない（見守りの見守り問題）。v1 では受け入れ、将来課題として §12 に記録する。

---

## 7. エラーマスキングのルール

一次切り分けで出す情報は、**コード側に固定**し、設定で緩められない（IT必須4）。対象は `cron.runs` の `error_text` のみ。`result_summary` は理由を問わず一切使わない・転載しない（§0-6）。

### 7.1 出力する項目（これだけ）

| 項目 | 内容 |
|---|---|
| `error_category` | 下記 enum のいずれか：`TIMEOUT`／`RATE_LIMIT`／`CONNECTOR_ERROR`／`PERMISSION`／`NETWORK`／`VALIDATION`／`NOT_FOUND`／`RUNTIME`／`UNKNOWN`。`error_text` のキーワードから分類する単純な規則表（コード内固定） |
| `occurred_at` | 失敗した run の `finished_at`（対象タイムゾーン表記） |
| `has_error_log` | `error_text` が存在したか（真偽値） |
| `masked_excerpt` | マスキング後の抜粋。**最大120文字**、1対象につき1つまで。不要と判断したら `None` でよい |

### 7.2 除去・置換パターン（コード内固定の正規表現群）

| 種別 | 処理 |
|---|---|
| メールアドレス形式の文字列 | `[masked-email]` へ置換 |
| 認証情報系キーワード（token／secret／password／passwd／api_key／apikey／authorization／bearer／cookie／session 等）を含む「キー=値」「キー: 値」 | 値全体を `[masked]` へ置換。行にキーワードが含まれる場合は行ごと落とす |
| 長い英数字列（16文字以上の16進数、20文字以上の Base64 風文字列） | `[masked-id]` へ置換 |
| UUID 形式、数値IDの長い連なり | `[masked-id]` へ置換 |
| 電話番号形式（日本の市外局番・ハイフン区切りの数字列） | `[masked-number]` へ置換 |
| ホームディレクトリ配下の絶対パス | `~/...` へ短縮し、個人名を含むパス要素は出さない |
| URL のクエリ文字列 | クエリを除去（スキーム＋ホスト＋パスまで） |
| 制御文字・改行 | 空格へ置換（1行化してから切り捨てる） |

- 処理順：行単位のキーワード除去 → パターン置換 → 1行化 → **120文字で切り捨て**（末尾に `…`）。
- マスキングは台帳・週次要約・異常報告のすべてに同じ関数を通す。生の `error_text` はスナップショット JSON（VM ローカル、リポジトリ外）にのみ残り、Sheets・チャット・Git には出ない。
- テスト係向け：マスキングの fixture（認証情報風文字列、メールアドレス、長いID、パスを含むエラー文）をテスト仕様に含めること（§11）。

---

## 8. 台帳シートの構造

- スプレッドシート名：**「稼働見守り台帳」**（新規作成。ID は `config.local.json` に保持し、コードへ直書きしない）。
- 作成・書式設定は Sheets コネクタで行う。本人の規約どおり、**列幅・行高は内容から決め、変更後は読み戻して検証**する（下記の幅は 11px 前提の初期目安。実データで見切れる場合は広げる）。

### 8.1 タブ構成

| タブ | 役割 | 更新方式 |
|---|---|---|
| `台帳` | 現在状態（対象ごとに1行） | **全書き換え**（ヘッダー＋データ範囲を毎回 `values update`）。対象数が小さい（初期5本、将来も数十本規模）ため全書き換えが最も壊れにくい |
| `異常履歴` | 状態遷移イベント（検出／回復） | **追記のみ**（`values append`）。過去行は書き換えない |
| `週次要約` | 週次要約の控え（1週1行） | **追記のみ** |
| `定義` | 定義表（targets.yaml）の写し | 全書き換え（YAML が正本。シート側は閲覧用） |
| `説明` | この台帳の読み方・状態の意味・シャドー期間の注記 | 初回のみ作成 |

### 8.2 「台帳」タブの列定義

| 列 | 項目 | 内容 | 列幅目安(px) | 折り返し |
|---|---|---|---|---|
| A | 対象ID | 定義表の `id` | 190 | なし |
| B | 表示名 | `display_name` | 210 | あり |
| C | 状態 | 未実行／実行中／成功／失敗／判定不能 | 84 | なし |
| D | 最終成功 | `YYYY-MM-DD HH:MM`（対象タイムゾーン） | 140 | なし |
| E | 連続失敗 | 回数（整数） | 70 | なし |
| F | 次回予定 | `YYYY-MM-DD HH:MM` | 140 | なし |
| G | 判定時刻 | この行を判定した時刻 | 140 | なし |
| H | 証跡 | `evidence.kind` の表示名（例：cron／成果物 併用） | 110 | あり |
| I | 一次切り分け | 理由コードの和訳＋マスキング済みエラー（種別・発生時刻）。正常時は空か「—」 | 260 | あり（最長でも約5〜6行に収まる幅） |

- ヘッダー行は固定（フリーズ）＋太字＋背景色。状態セルは色分け（成功=緑系、失敗=赤系、判定不能=黄系、実行中=青系、未実行=灰系）を `batchUpdate` の条件付き書式またはセル背景で設定する（初回セットアップ時に一度設定し、以後は値の書き換えのみ）。
- 行高は I 列の折り返し行数に合わせて調整する（目安：行数×22px＋余白）。
- 書き込み後は **読み戻して検証**：行数、対象IDの集合、C列の値が Judge 出力と一致することを確認してから check 実行を正常終了とする。不一致なら heartbeat に `result: partial` を記録する。

### 8.3 「異常履歴」タブの列

| 列 | 項目 |
|---|---|
| A | 検出／回復の別（`検出`／`回復`） |
| B | 日時 |
| C | 対象ID |
| D | 表示名 |
| E | 状態（失敗／判定不能 等） |
| F | 理由（コード＋短い和訳） |
| G | 最終成功 |
| H | 一次切り分け（§7 のマスキング済み情報のみ） |

### 8.4 「週次要約」タブの列

| 列 | 項目 |
|---|---|
| A | 週（開始日〜終了日） |
| B | 要約文（異常の有無、対象別の異常件数） |
| C | 見守り自身の稼働（最終実行・期待回数と実績） |
| D | シャドー中かどうか（真偽値） |

---

## 9. シャドー期間の実装

### 9.1 フラグの持ち方（二重ゲート＋既定は通知なし）

- 通知可否は **ランタイムフラグファイル** `~/workspace/cron-watchdog-data/notify-flag.json` で持つ（リポジトリ外。Git の変更で誤って有効化される事故を防ぐ）。

```json
{"notify": false, "mode": "shadow", "changed_at": "2026-11-05T00:00:00+09:00", "note": "導入初期。シャドー期間中"}
```

- **ファイルが無い場合は `notify: false`（シャドー）として扱う**（fail-safe：既定は通知しない）。
- ゲートは2か所：(1) Judge／check 側はフラグを見て「通知下書き」を outbox に書くかどうかを決める。(2) Reporter（週次・異常報告を実際に届けるエージェント手順）は**送信直前にフラグを再読**し、`notify: true` でなければ送らない。片方の実装ミスでも誤通知しない構造。

### 9.2 シャドー中の出力先

| 出力 | シャドー中 | 通知有効化後 |
|---|---|---|
| 台帳シート（全タブ） | 更新する | 更新する |
| ローカル記録（状態・heartbeat・スナップショット） | 残す | 残す |
| 通知下書き | `data/outbox/notifications.jsonl` に `would_notify: true` 付きで記録（＝「送っていたはずの文面」の検証材料） | 実際に送信し、送信済みとして同じ outbox に記録 |
| 異常のチャット通知 | **送らない** | 期限超過・連続失敗の検出時に送る |
| 週次要約 | シャドー観測報告として届ける（下記） | 通常の週次要約として届ける |

- シャドー中の週次要約は、IT必須5の「検出しても通知せず、稼働実績と突き合わせて定義表を調整する」ための**観測報告**として、AI組織のチャットへ「シャドー観測報告」と明示して届ける。これは異常アラートではなく調整のための定例報告であり、アラート（異常時の即時通知）は送らない。※この線引きは §12 の確認事項（厳密解釈では週次も止める選択肢がある）。
- シャドー期間の目安：**14日間**かつ、その間に (a) 全対象で誤検知の有無を実績と突き合わせ済み、(b) §11 の意図的期限超過試験に合格、(c) 定義表の調整（`grace`・証跡種別）が一通り反映済み、を満たすこと。

### 9.3 通知有効化への切り替え手順（手動のみ。自動有効化の経路は作らない）

1. コーディネーターがシャドー観測報告と試験結果を添えて、本人へ有効化の確認を上げる。
2. **本人が確認**（AI組織チャットまたは親 Issue 上）したら、運用係が `notify-flag.json` の `notify` を `true`、`mode` を `weekly_plus_anomaly`、`changed_at` と `note`（確認日・確認経路）を更新する（1ファイルの手動編集のみ。コード変更は不要）。
3. 直後の週次要約に「通知は有効化済み（有効化日）」の1行を含め、有効化が伝わったことを確認できるようにする。
4. 戻し方：同じファイルの `notify` を `false` に戻すだけ。即時にシャドーへ戻る。見守り cron を止めれば台帳更新自体も止まる（既存定例への影響は無い）。

---

## 10. モジュール構成とインターフェース

Executor とテスト係は本節を契約とする。言語は Python（Black＋PEP 8、isort `profile=black`、Conventional Commits、pytest）。時刻はすべて **timezone-aware な `datetime`** で扱い、naive な時刻が入ったら `ValueError` とする。全モジュールは標準ライブラリ＋PyYAML のみ（PyYAML の要否検証は §12）。

### 10.1 リポジトリ構成

```text
cron-watchdog/
├── README.md # 日本語。目的・構成・運用（シャドー／有効化手順）
├── pyproject.toml
├── config/
│ ├── targets.yaml # 定義表（正本）
│ └── targets.example.yaml # 伏せ字テンプレート
├── config.local.json # 台帳スプレッドシートID等（.gitignore 対象・実ファイルは置かない）
├── src/watchdog/
│ ├── __init__.py
│ ├── models.py # データ型（§10.2）
│ ├── definitions.py # 定義表の読み込みと検証
│ ├── schedule_calc.py # 予定時刻の算出
│ ├── snapshot.py # スナップショット JSON の読み込みと検証
│ ├── probes.py # 成果物証跡の確認
│ ├── masking.py # エラーマスキング（§7）
│ ├── judge.py # 判定（§4）
│ ├── state.py # 状態ストア
│ ├── heartbeat.py # 死活記録
│ ├── ledger.py # 台帳行・異常イベント・週次要約データの組み立て
│ └── cli.py # エントリポイント
└── tests/ # テスト係が完了の定義から先に書く（§11）
```

ランタイムデータ（リポジトリ外）：`~/workspace/cron-watchdog-data/` 配下に `state.json`、`watchdog-heartbeat.jsonl`、`last-run.json`、`notify-flag.json`、`snapshots/`、`outbox/`。

### 10.2 データ型（`models.py`）

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

class State(Enum):
NOT_YET_RUN = "未実行"
RUNNING = "実行中"
SUCCEEDED = "成功"
FAILED = "失敗"
UNKNOWN = "判定不能"

class EvidenceKind(Enum):
CRON_STATUS = "cron_status"
ARTIFACT_FILE = "artifact_file"
ARTIFACT_JSON = "artifact_json"
CRON_OR_ARTIFACT = "cron_or_artifact"
CRON_AND_ARTIFACT = "cron_and_artifact"

@dataclass(frozen=True)
class ScheduleSpec:
kind: str # "daily"|"weekly"|"monthly"|"interval"|"yearly"
time: str | None # "HH:MM:SS"（interval では None）
dow: tuple[str,...] # weekly のみ
dom: tuple[int,...] # monthly/yearly のみ
every: timedelta | None # interval のみ

@dataclass(frozen=True)
class EvidenceSpec:
kind: EvidenceKind
path: str | None
glob: str | None # "{date}" プレースホルダ可
json_key: str | None

@dataclass(frozen=True)
class TargetDefinition:
id: str
display_name: str
enabled: bool
schedule: ScheduleSpec
timezone: str # IANA 名 or "@user.current"
grace: timedelta
evidence: EvidenceSpec
failure_threshold: int # 既定 2
expected_duration: timedelta # 既定 60分

@dataclass(frozen=True)
class RunRecord:
job_id: str
run_id: str
status: str # "succeeded"|"failed"|その他生値
scheduled_for: datetime
started_at: datetime | None
finished_at: datetime | None
attempt: int
trigger_reason: str # "scheduled" 等
error_text: str | None

@dataclass(frozen=True)
class StatusSnapshot:
job_id: str
enabled: bool
in_flight: bool
last_run_at: datetime | None
last_status: str | None
last_success_at: datetime | None
consecutive_failures: int
next_run_at: datetime | None
resolved_timezone: str # 収集時に解決した IANA 名

@dataclass(frozen=True)
class CollectorSnapshot:
collected_at: datetime
statuses: dict[str, StatusSnapshot] # job_id -> status
runs: dict[str, list[RunRecord]] # job_id -> runs（新しい順）

@dataclass(frozen=True)
class ArtifactProbe:
found: bool
observed_at: datetime | None # ファイル更新時刻 or JSON キー時刻
detail: str # 個人情報を含まない短い説明

@dataclass(frozen=True)
class MaskedError:
category: str # §7.1 の enum
occurred_at: datetime | None
has_log: bool
excerpt: str | None # 120文字以内・マスキング済み

@dataclass(frozen=True)
class Judgement:
target_id: str
state: State
reason_code: str # "OK"|"OVERDUE"|"NEVER_RAN_OVERDUE"|"CONSECUTIVE_FAILURES"|"LAST_RUN_FAILED"|"SOURCE_MISSING"|"COLLECT_FAILED"|"SCHEDULE_UNPARSEABLE"|"TZ_UNRESOLVED"|"EVIDENCE_UNREADABLE"|"JOB_DISABLED"|"RUNNING"|"NOT_YET_DUE"
last_success_at: datetime | None
consecutive_failures: int
next_run_at: datetime | None
deadline_at: datetime | None
error: MaskedError | None
judged_at: datetime

@dataclass(frozen=True)
class AnomalyEvent:
kind: str # "detected"|"recovered"
occurred_at: datetime
target_id: str
display_name: str
state: State
reason_code: str
last_success_at: datetime | None
error: MaskedError | None
```

### 10.3 主要関数の契約

```python
# definitions.py
def load_definitions(path: Path) -> list[TargetDefinition]:
"""定義表を読み、型・必須項目・スケジュール整合を検証する。
不正な定義が1件でもあれば DefinitionError（ValueError のサブクラス）で
全体を失敗させる（部分的に読み飛ばして静かに見守り漏れを作らない）。"""

# snapshot.py
def load_snapshot(path: Path) -> CollectorSnapshot:
"""収集係が出したスナップショット JSON を検証して型へ変換する。
形式不正は SnapshotError。個別対象の欠落はエラーにせず、
statuses/runs の欠落として Judge が判定不能を判断する。"""

# schedule_calc.py
def last_due(spec: ScheduleSpec, tz: ZoneInfo, now: datetime,
phase_anchor: datetime | None = None) -> datetime | None:
"""now 以前で最も新しい予定発火時刻。interval では phase_anchor
（直近 run の scheduled_for 等）を位相の基準とする。無ければ None。"""

def next_due(spec: ScheduleSpec, tz: ZoneInfo, after: datetime,
phase_anchor: datetime | None = None) -> datetime | None:
"""after より後で最も近い予定発火時刻。"""

# probes.py
def probe_artifact(spec: EvidenceSpec, tz: ZoneInfo, now: datetime) -> ArtifactProbe:
"""成果物の有無と観測時刻を返す。読めない場合は例外にせず
found=False, observed_at=None とし、detail に理由コードを含める。
Judge 側で EVIDENCE_UNREADABLE として扱うための情報を detail に残す。"""

# judge.py
def count_consecutive_failures(runs: list[RunRecord]) -> int:
"""§4.4：scheduled_for 単位に束ね、trigger_reason == 'scheduled' の
完了 run のみを対象に、直近から連続する失敗回数を返す。"""

def judge_target(defn: TargetDefinition,
status: StatusSnapshot | None,
runs: list[RunRecord],
probe: ArtifactProbe | None,
prev_last_success_at: datetime | None,
now: datetime) -> Judgement:
"""§4.2 の決定手順そのもの。純粋関数（I/O なし）。
status が None の場合は判定不能を基本とし、証跡（probe）が
cron 系でない場合に限り成果物だけで判定してよい。"""

# masking.py
def classify_error(error_text: str | None) -> str:
"""§7.1 のカテゴリ enum を返す。None/空なら 'UNKNOWN' ではなく
呼び出し側で has_log=False として扱うため、空入力では 'UNKNOWN' を返す契約にしない：
空入力は ValueError。"""

def mask_error(error_text: str | None, occurred_at: datetime | None) -> MaskedError:
"""§7.2 の除去・置換・120文字切り捨てを適用する。None は has_log=False を返す。"""

# state.py
@dataclass
class TargetState:
last_success_at: datetime | None
last_state: State | None
last_consecutive_failures: int
updated_at: datetime

@dataclass
class WatchdogState:
targets: dict[str, TargetState]

def load_state(path: Path) -> WatchdogState:... # 無ければ空で返す
def save_state(path: Path, state: WatchdogState) -> None:... # 一時ファイル経由で原子的書換
def merge_judgements(state: WatchdogState, judgements: list[Judgement],
now: datetime) -> WatchdogState:
"""last_success_at は単調増加（新しい観測でのみ前進）。状態と連続失敗は最新で上書き。"""

# heartbeat.py
def append_heartbeat(path: Path, record: dict) -> None:... # §6 の形式で1行追記
def read_heartbeats(path: Path, since: datetime) -> list[dict]:...
def summarize_self_health(records: list[dict], expected_runs: int,
now: datetime) -> dict:
"""{'last_run_at':..., 'executed':int, 'expected':int, 'stale':bool} を返す。
stale は最終実行が12時間より古い場合に True。"""

# ledger.py
def build_ledger_rows(defs: list[TargetDefinition],
judgements: list[Judgement]) -> list[list[str]]:
"""§8.2 の列順で、ヘッダーを除くデータ行を返す（シート書記用 JSON の元）。"""

def build_anomaly_events(prev: WatchdogState,
judgements: list[Judgement]) -> list[AnomalyEvent]:
"""状態遷移（成功→失敗／失敗→成功 等）だけをイベント化する。同状態の継続は出さない。"""

def build_weekly_summary(state: WatchdogState, events: list[AnomalyEvent],
self_health: dict, window_start: datetime,
window_end: datetime, shadow: bool) -> dict:
"""週次要約のデータ（文章化は Reporter の仕事。ここは件数・対象ID・自己稼働の構造化データまで）。"""

# cli.py
def main(argv: list[str] | None = None) -> int:
"""サブコマンド：
judge --definitions <path> --snapshot <path> --state <path> --data-dir <path> --out <path>
判定を実行し、状態を更新し、heartbeat を追記し、
{judgements, ledger_rows, anomaly_events, notify_drafts} の JSON を --out へ書く。
戻り値：0=正常、2=一部判定不能（partial）、1=実行自体の失敗。
weekly --data-dir <path> --out <path>
過去7日の heartbeat とイベントから週次要約データを --out へ書く。
"""
```

### 10.4 スナップショット JSON の形式（収集係との契約）

収集係（エージェント）はこの形式で書く。Judge はこの形式だけを読む。

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

- 時刻はすべて ISO 8601（オフセット付き）。epoch 秒で来た値は収集係が変換する。
- `error_text` は生のまま入れてよい（保存先は VM ローカル限定）。**Sheets・チャット・Git へ出す前に必ず `mask_error` を通す**ことはコードと cron 本文の双方で固定する。
- 対象が取得できなかった場合は `targets` から省き、`collect_errors` に理由コードを入れる（Judge が判定不能にする）。

---

## 11. 試験方法

### 11.1 「意図的な期限超過」試験（実在の定例を止めずに行う）

実在の cron は一切止めない・無効化しない。試験専用の定義エントリと偽データだけで Judge を通す。

1. **試験用定義**を定義表へ一時追加する（本番定義とは `id` で区別し、試験後に削除する。削除まで含めて試験手順とする）。

```yaml
- id: watchdog-selftest-overdue
display_name: 期限超過テスト
enabled: true
schedule: { kind: daily, time: "00:05:00"}
timezone: Asia/Tokyo
grace: 30m
evidence: { kind: cron_status}
failure_threshold: 2
expected_duration: 15m
```

2. **偽スナップショット**を用意する：上記 ID について、`last_success_at` を「3日前」、「直近の run は3日前に成功、以後なし」とした fixture JSON を作る（実在ジョブのスナップショット形式 §10.4 と同一形式）。
3. `cli judge` を fixture で実行し、次を確認する：
- 状態が **失敗／理由 `OVERDUE`** になること。
- 異常イベント（検出）が1件だけ生成されること。
- 台帳行に最終成功（3日前）・次回予定が正しく出ること。
- シャドー前提のため、通知は outbox の下書き（`would_notify: true`）止まりで、実送信が起きないこと。
4. **回復試験**：同じ ID の偽スナップショットを「最終成功＝直近の予定回」に差し替えて再実行し、状態が成功へ戻り、回復イベントが生成されることを確認する。
5. 実シートで確認する場合は、試験行を台帳に一度書いて目視し、試験後に台帳から試験行を取り除く（check の全書き換えで自然に消える）。
6. 補助手段として、成果物証跡の試験は fixture ファイルの更新時刻を過去日時に設定して行う（実在の成果物には触れない）。

### 11.2 完了の定義との対応

| 完了の定義 | 検証方法 |
|---|---|
| (a) 主要な定期実行が台帳に登録され、最終成功時刻が自動で更新される | 対象5本を台帳に載せ、24時間以上の運用で各行の最終成功が実績（`cron.status`）と一致し続けることを読み戻しで確認 |
| (b) わざと1件止めた試験で期限超過として検知・報告される | §11.1 の試験（実ジョブは止めず、試験用定義＋偽の最終成功で再現）。「報告」はシャドー中は台帳＋異常履歴＋outbox 下書きをもって充てる。通知有効化後は実通知でも再確認する |
| (c) 正常な週は「異常なし」以外の通知が負担にならない | シャドー14日間の週次観測報告が週1回のみで、check 実行がチャットへ何も出さないことを確認 |

### 11.3 テスト係への申し送り（仕様由来のテスト観点）

- 予定算出：weekly の金→月（72時間）、monthly の月末（31日指定と短い月）、daily の日付またぎ（23:30＋猶予）、interval の位相引き継ぎ。
- 判定：5区分すべての分岐、実行中の打ち切り、未実行→期限超過、判定不能の理由コード、対象ジョブ無効化（`JOB_DISABLED`）。
- 連続失敗：`attempt` 違いの束ね、手動実行の除外、成功でのリセット。
- 状態マージ：最終成功が後退しないこと。
- マスキング：§7.2 の全パターン種別、120文字切り捨て、`result_summary` を入力に含めても出力に出ないこと。
- シャドー：フラグファイル欠落時に通知下書き止まりになること。

---

## 12. リスクと未確定事項

### 12.1 リスクと対策

| リスク | 影響 | 対策（設計内） | 残存 |
|---|---|---|---|
| 「処理は成功したが記録方式が違う」ことによる誤検知（アラーム疲れ） | 本企画最大のリスク。誤報が続くと台帳自体が見られなくなる | 証跡種別の対象別選択、導入初期は `cron_or_artifact`（緩い）から、シャドー14日で実績照合、定義表だけで調整可能 | シャドーで潰し切る前提。0にはならない |
| `cron.runs` 履歴の保持深さが不明（`history_may_be_truncated`） | 間隔を空けると失敗 run を見落とす | 状態ストアへの累積マージ（§5.4）、check 間隔6時間、status の `last_success_at`／`consecutive_failures` を第一情報源に | 保持深さ自体はシャドー期間に実測して記録する |
| 見守り cron 自体の停止（見守りの見守り問題） | 全体が無言で止まる | heartbeat＋週次要約での自己言及（§6）、check と週次を別ジョブ化 | 両方止まれば検知不能。v1 では受容 |
| 収集係（エージェント）の手順ミス（形式違い・対象漏れ） | 判定不能の増加、誤判定 | スナップショット形式のスキーマ検証、不正なら全体を partial として heartbeat に残す。対象漏れは「判定不能」として見える化（静かに成功扱いにしない） | エージェント実行品質への依存は残る |
| `result_summary`／`error_text` 経由の個人情報混入 | 台帳・報告への漏洩 | §7 のマスキング固定、`result_summary` の全面不使用、push 前検閲 | マスキングの正規表現で拾い切れない形式は残りうる。抜粋自体を出さない選択（`excerpt: None`）も常時可能 |
| monthly の存在しない日・スケジューラ実挙動との差異 | 予定算出のずれ | シャドーで実績の `scheduled_for` と算出値を照合し、定義表／算出規則を調整 | 初期は monthly 対象を含めず、daily／weekly で型を固めてから追加してもよい |

### 12.2 コーディネーター判断が必要な点

1. **リポジトリ作成の承認**：新規非公開リポジトリ `cron-watchdog` の作成（§2）。作成は Executor フェーズの作業とし、本書の承認をもって進めてよいか。
2. **シャドー中の週次観測報告の扱い**（§9.2）：「検出しても通知せず」を、週1回の観測報告（調整用・AI組織チャット宛）は例外として届ける解釈でよいか。厳密解釈（週次も含め一切届けず、シートとローカル記録のみ）も選択肢として残す。
3. **手動実行の成功の扱い**（§4.4-3）：手動 run の成功を `last_success_at` に含める現設計（status の実値を優先）でよいか。含めると「予定回は失敗したが手動でやり直して成功」が正常に見える利点と、予定回の失敗が隠れる欠点がある。
4. **check の実行間隔とコスト**：初期6時間ごと（1日4回のエージェント実行）。トークン消費との兼ね合いで 1日2回から始める選択肢もある。検知遅延（最大で間隔＋猶予）とのトレードオフ。
5. **台帳スプレッドシートの新規作成**：作成自体は不可逆操作ではないが、新規ファイルが1つ増える。作成先アカウント・共有設定は既定（本人所有・非共有）でよいか。
6. **Sheets 直接書き込みの検証（spike）の要否**（§5.3）：v1 はエージェント経由で確定。コネクタ CLI を Python から呼ぶ検証を初期タスクに入れるかどうか。
7. **PyYAML 依存の可否**：定義表を YAML とする前提で PyYAML を使う。VM に導入済みかの確認は Executor の初回タスクとし、無ければ「標準ライブラリのみ＋JSON 定義」へ切り替える判断が要る。
8. **対象拡大の順序**：初期5本の次に、月次系（電気・売電・水道・Gmail整理・サブスク棚卸し）と interval 系（期日確認 24h 等）のどちらを先に足すか。monthly／interval は予定算出の癖が強いため、シャドー結果を見て PM が決める。

---

## 付録：IT必須フィードバック5件への対応表

| # | 必須内容 | 本設計での対応 |
|---|---|---|
| 1 | 定例ごとの「成功の定義」を定義表に持ち、本体は読むだけ | §3（targets.yaml、証跡種別・周期・許容遅延・タイムゾーンを全項目化） |
| 2 | 状態は5区分。実行中・判定不能を失敗と混ぜない | §4.2（決定手順を順序付きで固定） |
| 3 | 見守り自身の最終実行時刻を対象とは別の場所に残し、週次要約に含める | §6（VMローカル JSONL＋週次要約への必須1行） |
| 4 | エラー情報はマスキングと上限を設け、原文を転載しない | §7（出力項目4点に限定、パターン種別・120文字上限をコード固定。加えて `result_summary` は全面不使用） |
| 5 | 導入初期はシャドー期間とし、調整後に通知へ切り替える | §9（フラグファイル＋二重ゲート＋手動切替手順。既定は通知なし） |
