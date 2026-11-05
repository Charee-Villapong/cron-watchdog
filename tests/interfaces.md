# 想定インターフェース一覧（テスト係が最小限定義）

被テストパッケージ名は `watchdog` とする。実装はこのインターフェースに
合わせること。テストは外部サービス（Sheets・ネットワーク・実 cron）に
依存せず、時刻はすべて `now` 引数で注入する。

> 注記: テストモジュールは収集（`--collect-only`）時に `watchdog` を
> import しない。各テスト関数の内部で初めて import する。これにより
> 実装が無い段階でも収集エラーにならず、実行時に初めて失敗する。

## 1. `watchdog.definitions` — 定義表の読み込み（必須要件1）

```python
class DefinitionError(ValueError):
    """定義表の必須項目欠落・無効値に対する明示的なエラー。"""

@dataclass(frozen=True)
class Definition:
    name: str                 # 定例の識別名（例: "daily-fortune"）
    evidence_type: str        # 成功の証跡の種類（例: "log_success"）
    period: str               # 予定周期の文字列表現（例: "1d", "7d", "24h", "6h", "30m"）
    tolerance_seconds: int    # 許容遅延（秒）
    timezone: str             # 判定に使うタイムゾーン名（例: "Asia/Tokyo"）

    @property
    def period_timedelta(self) -> timedelta: ...

def load_definitions(rows: Iterable[Mapping[str, Any]]) -> list[Definition]:
    """定義表（dict の列）を読む。必須項目（name / evidence_type /
    period / tolerance_seconds / timezone）のいずれかが欠落・空の場合は
    DefinitionError を送出する。"""

def parse_period(value: str) -> timedelta:
    """ "1d"->1日, "7d"/"1w"->7日, "24h"->24時間, "6h"->6時間,
    "30m"->30分 を返す。解釈できない表現は DefinitionError を送出する
    （呼び出し側で「判定不能」として扱う道も許容する。テスト側は
    エラー送出 か 判定不能 のどちらかであれば合格とする）。"""
```

定義 dict の形式（フィクスチャ形式）:

```python
{
    "name": "daily-fortune",
    "evidence_type": "log_success",
    "period": "1d",
    "tolerance_seconds": 7200,
    "timezone": "Asia/Tokyo",
}
```

## 2. `watchdog.status` — 状態判定（必須要件2）

```python
class Status(str, Enum):
    NOT_RUN = "未実行"
    RUNNING = "実行中"
    SUCCESS = "成功"
    FAILURE = "失敗"        # 期限超過を含む
    UNKNOWN = "判定不能"

def evaluate_status(
    definition: Definition,
    last_success_at: datetime | None,
    now: datetime,
    *,
    running: bool = False,
    evidence_available: bool = True,
) -> Status:
    """判定規則:
    - evidence_available is False            -> UNKNOWN（失敗と混ぜない）
    - running is True                        -> RUNNING（失敗と混ぜない）
    - last_success_at is None（履歴なし）    -> NOT_RUN
    - now <= last_success_at + period + tolerance -> SUCCESS
    - それ以外（期限 = 周期 + 許容遅延 を超過）  -> FAILURE
    境界（ちょうど期限時刻）は SUCCESS 側に倒す。
    """
```

## 3. `watchdog.ledger` — 台帳・次回予定・連続失敗・期限超過検出

```python
@dataclass(frozen=True)
class RunRecord:
    finished_at: datetime
    succeeded: bool

@dataclass(frozen=True)
class JobState:
    definition: Definition
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    running: bool = False
    evidence_available: bool = True

@dataclass(frozen=True)
class LedgerRow:
    name: str
    period: str                    # 予定周期（定義の文字列表現）
    last_success_at: datetime | None
    consecutive_failures: int
    next_due_at: datetime | None   # 次回予定
    status: Status

def compute_next_due(
    definition: Definition,
    last_success_at: datetime | None,
) -> datetime | None:
    """last_success_at + period。last_success_at が None なら None。"""

def count_consecutive_failures(runs: Iterable[RunRecord]) -> int:
    """時系列（古い順）の末尾に連続する失敗の数。成功が最後なら 0、
    成功以降の失敗だけを数える。空なら 0。"""

def build_ledger_row(state: JobState, now: datetime) -> LedgerRow:
    """1エントリから「予定周期・最終成功時刻・連続失敗回数・
    次回予定・状態」を含む行を生成する。状態は evaluate_status、
    次回予定は compute_next_due で求める。"""

def detect_overdue(states: Iterable[JobState], now: datetime) -> list[LedgerRow]:
    """状態が FAILURE（期限超過）になるエントリだけを台帳行として返す。
    RUNNING / UNKNOWN / NOT_RUN は含めない。"""
```

## 4. `watchdog.heartbeat` — 見守り自身の死活記録（必須要件3）

```python
def record_heartbeat(path: str | Path, now: datetime) -> None:
    """見守り対象の台帳とは別のローカルファイルへ最終実行時刻を書く。
    台帳ファイルには一切触れない。"""

def read_heartbeat(path: str | Path) -> datetime | None:
    """書き込まれた最終実行時刻を読み戻す。ファイルが無ければ
    例外ではなく None を返す。読み戻した値は timezone-aware で、
    書き込んだ now と等しいこと。"""
```

## 5. `watchdog.masking` — エラー情報のマスキング（必須要件4）

```python
@dataclass(frozen=True)
class SanitizedError:
    error_type: str            # エラー種別（残す）
    occurred_at: datetime      # 発生時刻（残す）
    has_log: bool              # 該当ログの有無（残す）
    message: str               # マスキング・切り捨て済みの短い文字列

def mask_sensitive(text: str, *, max_length: int = 200) -> str:
    """メールアドレスらしい文字列、トークンらしい文字列
    （Bearer ... / token=... / 長い英数字・APIキー風文字列など）を
    除去または置換し、結果を max_length 以下に切り捨てる。
    ログ原文をそのまま返してはならない。"""

def sanitize_error(
    raw_message: str,
    *,
    error_type: str,
    occurred_at: datetime,
    has_log: bool,
) -> SanitizedError:
    """一次切り分け用のエラー情報を作る。error_type / occurred_at /
    has_log は保持し、message は mask_sensitive を通したものにする。"""
```

## 6. `watchdog.notify` — 通知とシャドーモード（必須要件5）

```python
@dataclass(frozen=True)
class NotificationPayload:
    should_notify: bool             # 実際に通知を送るべきか
    text: str                       # 通知本文
    suppressed_reason: str | None   # 抑止理由（例: "shadow"）。抑止時以外は None
    detections: tuple[LedgerRow, ...]  # 検出された期限超過など

def build_notification(
    rows: Iterable[LedgerRow],
    *,
    shadow_mode: bool = False,
) -> NotificationPayload | None:
    """規則:
    - shadow_mode=True: 検出があっても通知しない。戻り値は None、
      または should_notify=False かつ suppressed_reason に
      シャドーである旨（"shadow" を含む文字列）が明示されること。
      （テストはこのどちらでも合格とする）
    - shadow_mode=False かつ検出あり: should_notify=True で、
      本文に検出対象の名前が含まれる。
    - 検出なし（正常）: 生成される場合、本文は「異常なし」相当のみで、
      個別の定例名や「期限超過」を含まない。None を返す実装も許容する。
    """
```
