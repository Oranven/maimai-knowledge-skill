#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
舞萌DX知识库版本更新：一条命令完成抓取 → 定数刷新 → 校验 → 写入 → 测试。

默认流程（推荐）：
    python scripts/update_all.py --dry-run     # 先看会变什么，不写文件
    python scripts/update_all.py               # 备份 → 更新 → 测试

常用选项：
    --add-missing-charts   补上 OneCat 已有但快照缺失的谱面（如新增 Re:MASTER）
    --no-backup            不写 .backups/<时间戳>/ 备份
    --no-onecat            不拉 OneCat，只用国服库 + 水鱼
    --no-docs              不改动 README/SKILL.md 里的版本与统计
    --skip-tests           不跑单元测试
    --version CN1.57       手动指定国服版本号（默认自动读取国服源 README）
    --offline              完全离线：必须同时给 --cn-file / --details-file / --onecat-file
    --force                新快照比旧快照少 20% 以上时仍然写入

数据来源：国服曲库（曲目/分类/版本） + OneCat 官方谱面站（定数/显示等级） + 水鱼（ID/谱师/音符数/别名）。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import update_knowledge_base as core

CN_README_URL = ("https://raw.githubusercontent.com/CrazyKidCN/"
                 "maimaiDX-CN-songs-database/main/README.md")
BACKUP_DIR = core.ROOT / ".backups"
META_FILE = core.SNAPSHOT_META
DIFFS = core.DIFFICULTIES
PLUGIN_DIR = core.ROOT / "plugin" / "astrbot_plugin_maimai_kb"


# ---------------------------------------------------------------- 辅助

def stage(index: int, total: int, text: str) -> None:
    print(f"\n[{index}/{total}] {text}")


def key_of(row: Dict[str, Any]) -> Tuple[str, str, str]:
    return (row["type"], str(row["id"]), row["difficulty"])


def snapshot_signature(songs: List[Dict[str, Any]],
                       rows: List[Dict[str, Any]]) -> Tuple[Dict[Any, Any], Dict[Any, Any]]:
    song_map = {(song["title"], song["artist"]): song for song in songs}
    row_map = {key_of(row): row for row in rows}
    return song_map, row_map


def rank(value: str) -> int:
    base = int(str(value).rstrip("+"))
    return base * 2 + (1 if str(value).endswith("+") else 0)


def detect_cn_version(timeout: int) -> Tuple[Optional[str], Optional[str]]:
    """读取国服源 README 的版本号与更新日期；失败返回 (None, None)。"""
    try:
        text = core.fetch_text(CN_README_URL, timeout)
    except Exception as exc:  # 网络问题不应阻断更新
        print(f"  ! 无法读取国服源 README（{exc}），保留旧版本号")
        return None, None
    version = re.search(r"CN\d+\.\d+(?:-[A-Za-z0-9]+)?", text)
    date = re.search(r"最后更新：(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    parsed_date = f"{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}" if date else None
    return (version.group(0) if version else None), parsed_date


def backup_snapshot() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / stamp
    target.mkdir(parents=True, exist_ok=False)
    for name in ("songs.json", "level_index.json", "snapshot_meta.json"):
        source = core.ROOT / name
        if source.exists():
            shutil.copy2(source, target / name)
    if core.KB_DIR.exists():
        shutil.copytree(core.KB_DIR, target / "knowledge_base")
    return target


def diff_snapshot(before: Tuple[Dict, Dict], songs: List[Dict[str, Any]],
                  rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    old_songs, old_rows = before
    new_songs = {(song["title"], song["artist"]): song for song in songs}
    new_rows = {key_of(row): row for row in rows}

    added_songs = [new_songs[k] for k in new_songs.keys() - old_songs.keys()]
    removed_songs = [old_songs[k] for k in old_songs.keys() - new_songs.keys()]
    added_rows = [new_rows[k] for k in new_rows.keys() - old_rows.keys()]
    removed_rows = [old_rows[k] for k in old_rows.keys() - new_rows.keys()]

    ds_changed, level_changed, filled = [], [], []
    for key in new_rows.keys() & old_rows.keys():
        new, old = new_rows[key], old_rows[key]
        if old.get("ds") is None and new.get("ds") is not None:
            filled.append((new, old))
        elif new.get("ds") != old.get("ds"):
            ds_changed.append((new, old))
        if new.get("value") != old.get("value"):
            level_changed.append((new, old))

    return {
        "songs_before": len(old_songs), "songs_after": len(new_songs),
        "charts_before": len(old_rows), "charts_after": len(new_rows),
        "added_songs": added_songs, "removed_songs": removed_songs,
        "added_charts": added_rows, "removed_charts": removed_rows,
        "filled_ds": filled, "ds_changed": ds_changed, "level_changed": level_changed,
    }


def print_diff(report: Dict[str, Any]) -> None:
    print(f"  歌曲：{report['songs_before']} → {report['songs_after']}　"
          f"谱面：{report['charts_before']} → {report['charts_after']}")
    print(f"  新曲 {len(report['added_songs'])} 首，移除 {len(report['removed_songs'])} 首；"
          f"新谱面 {len(report['added_charts'])} 张，移除 {len(report['removed_charts'])} 张")
    print(f"  补全定数 {len(report['filled_ds'])} 张，修正定数 {len(report['ds_changed'])} 张，"
          f"修正显示等级 {len(report['level_changed'])} 张")

    for song in report["added_songs"][:10]:
        print(f"    + {song['title']} / {song['artist']}（{song['version']}）")
    if len(report["added_songs"]) > 10:
        print(f"    … 另外 {len(report['added_songs']) - 10} 首新曲")
    for song in report["removed_songs"][:10]:
        print(f"    - {song['title']} / {song['artist']}（{song['version']}）")
    for row in report["added_charts"][:10]:
        print(f"    + 谱面 {row['title']} [{row['type']}/{row['difficulty']}] {row['value']}({row['ds']})")
    if len(report["added_charts"]) > 10:
        print(f"    … 另外 {len(report['added_charts']) - 10} 张新谱面")
    for row, old in report["ds_changed"][:10]:
        print(f"    ~ 定数 {row['title']} [{row['type']}/{row['difficulty']}] {old['ds']} → {row['ds']}")
    if len(report["ds_changed"]) > 10:
        print(f"    … 另外 {len(report['ds_changed']) - 10} 张定数变化")


def jsonable(report: Dict[str, Any]) -> Dict[str, Any]:
    def row_brief(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: row.get(k) for k in ("title", "type", "difficulty", "value", "ds", "ds_source")}

    return {
        "songs_before": report["songs_before"], "songs_after": report["songs_after"],
        "charts_before": report["charts_before"], "charts_after": report["charts_after"],
        "added_songs": [{k: s.get(k) for k in ("title", "artist", "version")} for s in report["added_songs"]],
        "removed_songs": [{k: s.get(k) for k in ("title", "artist", "version")} for s in report["removed_songs"]],
        "added_charts": [row_brief(r) for r in report["added_charts"]],
        "removed_charts": [row_brief(r) for r in report["removed_charts"]],
        "filled_ds": [{"new": row_brief(n), "old_ds": o.get("ds")} for n, o in report["filled_ds"]],
        "ds_changed": [{"new": row_brief(n), "old_ds": o.get("ds")} for n, o in report["ds_changed"]],
        "level_changed": [{"new": row_brief(n), "old": o.get("value")} for n, o in report["level_changed"]],
    }


def _stats_context(meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    missing_titles = list(dict.fromkeys(
        row["title"] for row in rows if row["ds_source"] != "onecat" and row["ds"] is not None))
    ds_note = (f"{meta['charts']} 张谱面全部有定数，无 `null`。"
               if meta["charts_with_ds"] == meta["charts"]
               else f"{meta['charts']} 张谱面中 {meta['charts_with_ds']} 张有定数，其余为 `null`。")
    missing_note = (f"，{len(missing_titles)} 首（{'、'.join(missing_titles)}）的谱面 OneCat 未收录，保留原水鱼定数"
                    if missing_titles else "")
    return {
        "version": meta.get("version") or "未知版本",
        "date": meta.get("source_updated") or meta.get("updated_at"),
        "updated": meta.get("updated_at"),
        "songs": meta["songs"], "titles": meta["unique_titles"],
        "charts": meta["charts"], "categories": meta["categories"],
        "onecat": meta["ds_sources"].get("onecat", 0),
        "ds_line": ds_note, "missing_note": missing_note,
    }


README_SNAPSHOT = re.compile(
    r"当前全量快照：\*\*(.+?)\*\*（国服源更新于 ([\d-]+)），\*\*(\d+) 条歌曲记录、"
    r"(\d+) 个唯一标题、(\d+) 张常规谱面、(\d+) 个分类\*\*。")
README_ONECAT = re.compile(r"定数与显示等级已按 \[OneCat 官方谱面站\]\([^)]+\) 刷新（[\d-]+）：[^。）]*。")
README_ID_LINE = re.compile(r"本快照全部 \d+ 张谱面已匹配 ID；.*?不要把空定数解释为 0。")
SKILL_SNAPSHOT = re.compile(r"当前知识库为国服 (.+?)：(\d+) 条歌曲记录、(\d+) 个唯一标题、(\d+) 张常规谱面。")
KB_README_SNAPSHOT = re.compile(r"当前快照为 (.+?)，包含 (\d+) 条歌曲记录、(\d+) 个唯一标题、(\d+) 张常规谱面")


def sync_docs(meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[str]:
    """把版本号与统计数字同步进 README / SKILL / knowledge_base README。"""
    ctx = _stats_context(meta, rows)
    onecat_url = "https://dw.moant.cn:34225/onecat/#/official"
    patches: List[Tuple[Path, Any]] = [
        (core.ROOT / "README.md",
         [(README_SNAPSHOT,
           f"当前全量快照：**{{version}}**（国服源更新于 {{date}}），**{{songs}} 条歌曲记录、"
           f"{{titles}} 个唯一标题、{{charts}} 张常规谱面、{{categories}} 个分类**。"),
          (README_ONECAT,
           f"定数与显示等级已按 [OneCat 官方谱面站]({onecat_url}) 刷新（{{updated}}）：{{ds_line}}"),
          (README_ID_LINE,
           "本快照全部 {charts} 张谱面已匹配 ID；{onecat} 张的 `ds` 来自 OneCat{missing_note}。"
           "`ds_source` 和 `detail_source` 分别记录定数与谱面详情来源；不要把空定数解释为 0。")]),
        (core.ROOT / "SKILL.md",
         [(SKILL_SNAPSHOT,
           "当前知识库为国服 {version}：{songs} 条歌曲记录、{titles} 个唯一标题、{charts} 张常规谱面。")]),
        (core.KB_DIR / "README.md",
         [(KB_README_SNAPSHOT,
           "当前快照为 {version}，包含 {songs} 条歌曲记录、{titles} 个唯一标题、{charts} 张常规谱面")]),
    ]
    touched: List[str] = []
    for path, replacements in patches:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        updated = text
        for pattern, template in replacements:
            updated = pattern.sub(lambda m: template.format(**ctx), updated, count=1)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            touched.append(str(path.relative_to(core.ROOT)).replace("\\", "/"))
    return touched


def _run_suite(target: str) -> bool:
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", target],
                            cwd=str(core.ROOT), capture_output=True, text=True)
    tail = (result.stderr or result.stdout).strip().splitlines()
    print("\n".join(tail[-6:]))
    return result.returncode == 0


def run_tests() -> bool:
    ok = _run_suite("tests")
    probe = subprocess.run([sys.executable, "-c", "import astrbot"],
                           capture_output=True, text=True)
    if probe.returncode == 0:
        ok = _run_suite("plugin/tests") and ok
    else:
        print("（跳过插件测试：当前解释器没有装 astrbot）")
    return ok


def sync_plugin() -> Optional[str]:
    """把新快照同步进插件数据目录，并重打可上传的插件 zip（与 build 脚本共用一套逻辑）。"""
    if not PLUGIN_DIR.is_dir():
        return None
    import build_astrbot_plugin as builder

    zip_path = builder.build(sync=True)
    info = builder.inspect(zip_path)
    return (f"{zip_path.name}（{info['files']} 个文件，{info['size_mb']} MB，"
            f"校验通过）")


# ---------------------------------------------------------------- 主流程

def main() -> int:
    parser = argparse.ArgumentParser(description="舞萌DX知识库版本更新")
    parser.add_argument("--dry-run", action="store_true", help="只抓取并报告差异，不写文件")
    parser.add_argument("--offline", action="store_true", help="离线：所有源都用本地文件")
    parser.add_argument("--cn-file", type=Path, help="国服 maidata.json")
    parser.add_argument("--details-file", type=Path, help="水鱼 music_data.json 或备用 CSV")
    parser.add_argument("--fallback-file", type=Path, help="备用谱面 CSV")
    parser.add_argument("--aliases-file", type=Path, help="别名 JSON；[] 表示保留现有别名")
    parser.add_argument("--onecat-file", type=Path, help="OneCat getMusicData JSON")
    parser.add_argument("--onecat-url", help="覆盖 OneCat 数据地址")
    parser.add_argument("--add-missing-charts", action="store_true",
                        help="补上 OneCat 已有、快照缺失的谱面")
    parser.add_argument("--no-onecat", action="store_true", help="不拉取 OneCat")
    parser.add_argument("--no-backup", action="store_true", help="不生成 .backups 备份")
    parser.add_argument("--no-docs", action="store_true", help="不改动文档中的版本与统计")
    parser.add_argument("--no-plugin", action="store_true", help="不同步 AstrBot 插件数据与 zip")
    parser.add_argument("--skip-tests", action="store_true", help="不运行单元测试")
    parser.add_argument("--version", help="手动指定国服版本号，如 CN1.57")
    parser.add_argument("--report", type=Path, help="把变更明细写成 JSON")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--force", action="store_true", help="数据量骤减时仍然写入")
    args = parser.parse_args()

    if args.offline and not (args.cn_file and args.details_file):
        parser.error("--offline 需要同时提供 --cn-file 与 --details-file")
    if args.onecat_url:
        core.ONECAT_MUSIC_URL = args.onecat_url

    total = 6
    before_songs = json.loads(core.SONGS_FILE.read_text(encoding="utf-8")) if core.SONGS_FILE.exists() else []
    before_rows = core.load_old_rows()
    before = snapshot_signature(before_songs, before_rows)
    meta = {}
    if META_FILE.exists():
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))

    stage(1, total, "识别国服版本")
    version, source_date = args.version, None
    if not args.offline:
        detected, source_date = detect_cn_version(args.timeout)
        version = args.version or detected or meta.get("version")
    else:
        version = args.version or meta.get("version")
    print(f"  版本：{version or '未知'}（国服源更新于 {source_date or meta.get('source_updated') or '未知'}）")

    stage(2, total, "抓取国服曲库 / 水鱼详情 / 别名，并生成谱面快照")
    songs, rows = core.build_snapshot(args.timeout, args.cn_file, args.details_file,
                                      args.aliases_file, args.fallback_file)
    print(f"  歌曲 {len(songs)}，谱面 {len(rows)}")

    stage(3, total, "用 OneCat 刷新定数与显示等级")
    payload: Optional[List[Dict[str, Any]]] = None
    if args.no_onecat:
        print("  已跳过（--no-onecat），保留构建阶段得到的定数")
    else:
        try:
            payload = core.load_onecat(args.onecat_file, args.timeout)
        except Exception as exc:
            print(f"  ! OneCat 不可用，保留构建阶段得到的定数：{exc}")
        else:
            songs, rows, stats = core.apply_onecat(songs, rows, payload)
            print(f"  {dict(sorted(stats.items(), key=lambda kv: -kv[1]))}")

    if args.add_missing_charts:
        if payload is None:
            print("  ! 未取到 OneCat 数据，跳过补谱面")
        else:
            detail_rows = None
            try:
                detail_rows = core.detail_rows_from_divingfish(
                    core.fetch_json(core.DIVING_FISH_MUSIC_URL, args.timeout))
            except Exception as exc:
                print(f"  ! 水鱼详情不可用，新谱面音符数留空：{exc}")
            added = core.add_missing_charts(songs, rows, payload, detail_rows)
            print(f"  补上 {len(added)} 张谱面" + (f"：{', '.join(r['title'] for r in added[:5])}" if added else ""))

    stage(4, total, "校验快照")
    core.validate_snapshot(songs, rows)
    print("  校验通过")

    stage(5, total, "对比上一版快照")
    report = diff_snapshot(before, songs, rows)
    print_diff(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print(f"  变更明细：{args.report}")

    if before[0] and len(songs) < len(before[0]) * 0.8 and not args.force:
        print("  ✗ 新快照歌曲数比上一版少 20% 以上，疑似源异常，已中止（确认无误可加 --force）")
        return 2

    if args.dry_run:
        print("\ndry-run：未写入任何文件")
        return 0

    stage(6, total, "写入快照、重建文档")
    if args.no_backup:
        print("  已跳过备份（--no-backup）")
    else:
        backup = backup_snapshot()
        print(f"  备份：{backup}")
    core.write_snapshot(songs, rows)
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    meta["version"] = version or meta.get("version")
    if source_date:
        meta["source_updated"] = source_date
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  已写入 songs.json / level_index.json / knowledge_base/（{meta['charts']} 张谱面，"
          f"{meta['charts_with_ds']} 张有定数）")
    if not args.no_docs:
        touched = sync_docs(meta, rows)
        print(f"  文档已同步：{', '.join(touched) if touched else '无需要修改的统计行'}")

    if not args.skip_tests:
        print("\n运行单元测试 …")
        if not run_tests():
            print("✗ 测试未通过：数据已写入，可用 .backups 中的备份回滚；未重新打包插件")
            return 1
        print("✓ 测试通过")

    # 测试放到打包之前：只有校验通过的数据才进 zip，且保证 data/ 与最终快照逐字节一致
    if not args.no_plugin:
        plugin_info = sync_plugin()
        print(f"  插件已同步：{plugin_info}" if plugin_info
              else "  未找到 plugin/ 目录，跳过插件同步")

    print("\n✅ 版本更新完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
