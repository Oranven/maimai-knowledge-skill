#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 OneCat 官方谱面站（https://dw.moant.cn:34225/onecat/）的最新定数刷新已提交快照。

只改写 `ds` / `ds_source` 和由定数换算出的显示等级 `value`，
曲目范围、别名、谱师、音符数、标签全部保留。

用法：
    python scripts/sync_onecat.py --dry-run
    python scripts/sync_onecat.py
    python scripts/sync_onecat.py --input /path/getMusicData.json

定数不可用时保留原值，不做猜测；写入前跑完整 validate_snapshot。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import update_knowledge_base as core


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="本地 OneCat getMusicData JSON；缺省在线抓取")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="只报告变更，不写文件")
    parser.add_argument("--report", type=Path, help="可选：把逐条变更写入 JSON")
    args = parser.parse_args()

    songs = json.loads(core.SONGS_FILE.read_text(encoding="utf-8"))
    rows = core.load_old_rows()
    payload = core.load_onecat(args.input, args.timeout)

    before = {(r["type"], r["id"], r["difficulty"]): (r["value"], r["ds"]) for r in rows}
    songs, rows, stats = core.apply_onecat(songs, rows, payload)

    changes = []
    for row in rows:
        old = before.get((row["type"], row["id"], row["difficulty"]))
        if not old:
            continue
        old_value, old_ds = old
        if old_value != row["value"] or old_ds != row["ds"]:
            changes.append({
                "type": row["type"],
                "id": row["id"],
                "title": row["title"],
                "difficulty": row["difficulty"],
                "old_value": old_value,
                "new_value": row["value"],
                "old_ds": old_ds,
                "new_ds": row["ds"],
            })

    core.validate_snapshot(songs, rows)
    print(f"歌曲记录: {len(songs)}；谱面记录: {len(rows)}")
    print(f"统计: {dict(sorted(stats.items(), key=lambda kv: -kv[1]))}")
    print(f"变更谱面: {len(changes)}（其中定数变化 "
          f"{stats.get('补全定数', 0) + stats.get('修正定数', 0)}，显示等级变化 {stats.get('修正显示等级', 0)}）")

    if args.report:
        args.report.write_text(json.dumps(changes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"变更明细: {args.report}")

    if args.dry_run:
        print("dry-run：未写入任何文件")
        return

    core.write_snapshot(songs, rows)
    print("✅ 已更新 level_index.json、songs.json 与 knowledge_base/*.md")


if __name__ == "__main__":
    main()
