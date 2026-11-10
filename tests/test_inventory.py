"""監視対象の差分検知（inventory / 分類ロジック）のテスト。

分類は純粋関数として固定する：実在する定例ジョブ名の集合と
定義表の対象名の集合から、一致／未登録／消滅の3分類を作る。
ローダは cron 定義の投影ファイル（frontmatter の id / enabled /
schedule.kind）を読み、runonce と無効化済みを「実在する定例」から
除き、アーカイブ済みコピーを無視することを固定する。

すべて架空データ・tmp_path 配下で実行し、実データには触れない。
"""

from __future__ import annotations


def write_cron_file(root, *parts, job_id, kind, enabled=True):
    """投影ファイル形式の cron 定義ファイルを書く。"""
    path = root.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {job_id}\n"
        "title: fixture\n"
        f"enabled: {'true' if enabled else 'false'}\n"
        "schedule:\n"
        f"  kind: {kind}\n"
        "  timezone: Asia/Tokyo\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    return path


# --- 分類ロジック（純粋関数） ---


def test_classify_matched_only():
    from watchdog.inventory import classify_diff

    diff = classify_diff(["job-a", "job-b"], ["job-b", "job-a"])

    assert diff.matched == ["job-a", "job-b"]
    assert diff.unregistered == []
    assert diff.missing == []


def test_classify_unregistered_present():
    from watchdog.inventory import classify_diff

    diff = classify_diff(["job-a", "job-new"], ["job-a"])

    assert diff.matched == ["job-a"]
    assert diff.unregistered == ["job-new"]
    assert diff.missing == []


def test_classify_missing_present():
    from watchdog.inventory import classify_diff

    diff = classify_diff(["job-a"], ["job-a", "job-gone"])

    assert diff.matched == ["job-a"]
    assert diff.unregistered == []
    assert diff.missing == ["job-gone"]


def test_classify_mixed_unregistered_and_missing():
    from watchdog.inventory import classify_diff

    diff = classify_diff(["job-a", "job-new"], ["job-a", "job-gone"])

    assert diff.matched == ["job-a"]
    assert diff.unregistered == ["job-new"]
    assert diff.missing == ["job-gone"]


def test_classify_empty_inputs():
    from watchdog.inventory import classify_diff

    diff = classify_diff([], [])

    assert diff.matched == []
    assert diff.unregistered == []
    assert diff.missing == []


def test_classify_results_are_sorted():
    from watchdog.inventory import classify_diff

    diff = classify_diff(["job-z", "job-m"], ["job-m", "job-a"])

    assert diff.matched == ["job-m"]
    assert diff.unregistered == ["job-z"]
    assert diff.missing == ["job-a"]


# --- ローダ（投影ファイルの読み取り） ---


def test_load_inventory_reads_frontmatter(tmp_path):
    from watchdog.inventory import load_inventory

    write_cron_file(
        tmp_path,
        "goal-x",
        "crons",
        "daily",
        "job-a__daily@07:00:00.md",
        job_id="job-a",
        kind="daily",
    )

    jobs = load_inventory([tmp_path])

    assert [(j.name, j.kind, j.enabled) for j in jobs] == [("job-a", "daily", True)]


def test_load_inventory_reads_flat_cron_d_style_tree(tmp_path):
    from watchdog.inventory import load_inventory

    write_cron_file(
        tmp_path,
        "hourly",
        "job-b__interval@6h.md",
        job_id="job-b",
        kind="interval",
    )

    jobs = load_inventory([tmp_path])

    assert [j.name for j in jobs] == ["job-b"]


def test_load_inventory_ignores_archive_subtree(tmp_path):
    from watchdog.inventory import load_inventory

    write_cron_file(
        tmp_path,
        "_archive",
        "job-old__daily@07:00:00.md",
        job_id="job-old",
        kind="daily",
    )

    assert load_inventory([tmp_path]) == []


def test_load_inventory_ignores_files_without_cron_frontmatter(tmp_path):
    from watchdog.inventory import load_inventory

    note = tmp_path / "goal-x" / "GOAL.md"
    note.parent.mkdir(parents=True)
    note.write_text("# just a note\n", encoding="utf-8")

    assert load_inventory([tmp_path]) == []


def test_load_inventory_missing_root_is_skipped(tmp_path):
    from watchdog.inventory import load_inventory

    assert load_inventory([tmp_path / "does-not-exist"]) == []


def test_load_inventory_dedupes_same_job_id(tmp_path):
    from watchdog.inventory import load_inventory

    write_cron_file(
        tmp_path, "a", "job-a__daily@07:00:00.md", job_id="job-a", kind="daily"
    )
    write_cron_file(
        tmp_path, "b", "job-a__daily@08:00:00.md", job_id="job-a", kind="daily"
    )

    jobs = load_inventory([tmp_path])

    assert [j.name for j in jobs] == ["job-a"]


# --- 「実在する定例」への絞り込み（runonce / 無効化の除外） ---


def test_recurring_names_excludes_runonce_and_disabled(tmp_path):
    from watchdog.inventory import load_inventory, recurring_names

    write_cron_file(
        tmp_path, "daily", "job-a__daily@07:00:00.md", job_id="job-a", kind="daily"
    )
    write_cron_file(
        tmp_path,
        "runonce",
        "job-once__runonce@2026-11-05T12:00:00.md",
        job_id="job-once",
        kind="runonce",
    )
    write_cron_file(
        tmp_path,
        "daily",
        "job-off__daily@07:00:00.md",
        job_id="job-off",
        kind="daily",
        enabled=False,
    )
    write_cron_file(
        tmp_path,
        "weekly",
        "job-w__weekly@Mon-09:00:00.md",
        job_id="job-w",
        kind="weekly",
    )

    names = recurring_names(load_inventory([tmp_path]))

    assert names == ["job-a", "job-w"]


def test_recurring_names_from_job_objects():
    from watchdog.inventory import CronJob, recurring_names

    jobs = [
        CronJob(name="job-a", kind="daily", enabled=True),
        CronJob(name="job-once", kind="runonce", enabled=True),
        CronJob(name="job-off", kind="monthly", enabled=False),
    ]

    assert recurring_names(jobs) == ["job-a"]
