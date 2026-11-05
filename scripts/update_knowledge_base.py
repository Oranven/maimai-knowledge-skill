#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键同步舞萌DX国服知识库。

数据优先级：
1. 曲目范围 / 分类 / 版本：CrazyKidCN/maimaiDX-CN-songs-database
2. 定数与显示等级（最新版）：OneCat 官方谱面站 /api/getMusicData
3. ID / 谱师 / 音符数：Diving-Fish /music_data（无需 Developer-Token）
4. 别名：YuzuChan alias API
5. Diving-Fish 暂时不可用时：Choimoe/dxdataViewer sheets.csv 作为谱面元数据备用源

原则：
- 定数以 OneCat 最新数据为准；显示等级按官方边界（定数 x.6 及以上进位为 x+）由定数换算，两者必须一致。
- OneCat 未收录的谱面保留快照原值，不回退到会与显示等级冲突的旧定数。
- 谱面特征 chart_tags 不是实时 API 数据，更新时保留仓库已有标签。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys_path_root = Path(__file__).resolve().parent
if str(sys_path_root) not in sys.path:
    sys.path.insert(0, str(sys_path_root))

import compat_http as requests  # noqa: E402  (requests 缺失时自动退回 urllib)

ROOT = Path(__file__).resolve().parents[1]
LEVEL_INDEX = ROOT / "level_index.json"
KB_DIR = ROOT / "knowledge_base"
SONGS_FILE = ROOT / "songs.json"
SNAPSHOT_META = ROOT / "snapshot_meta.json"
TITLE_EQUIVALENTS = {"Link(CoF)": "Link"}


def identity(title: str, artist: str) -> Tuple[str, str]:
    return title_norm(TITLE_EQUIVALENTS.get(title, title)), norm(artist)


def load_annotations() -> Dict[Tuple[str, str], Dict[str, Any]]:
    """旧 Markdown 的标签未区分 SD/DX；只保留在歌曲层，不能猜测谱面归属。"""
    if SONGS_FILE.exists():
        songs = json.loads(SONGS_FILE.read_text(encoding="utf-8"))
    else:
        songs = []
        for filename in CATEGORY_FILE.values():
            text = (KB_DIR / filename).read_text(encoding="utf-8")
            for block in text.split("\n---"):
                title = re.findall(r"^## (.+)$", block, re.M)
                artist = re.search(r"^\*\*艺术家\*\*: (.+)$", block, re.M)
                if not title or not artist:
                    continue
                tags = {d.lower(): t.split(", ") for d, t in
                        re.findall(r"^\*\*(BASIC|ADVANCED|EXPERT|MASTER|REMASTER)\*\*: (.+)$", block, re.M)}
                aliases = re.search(r"^\*\*别名\*\*: (.+)$", block, re.M)
                songs.append({"title": title[-1], "artist": artist[1], "chart_tags": tags,
                              "aliases": re.sub(r" \(共\d+个\)$", "", aliases[1]).split(", ") if aliases else []})
    return {identity(s["title"], s["artist"]): s for s in songs}

CN_MAIDATA_URL = (
    "https://raw.githubusercontent.com/CrazyKidCN/"
    "maimaiDX-CN-songs-database/main/maidata.json"
)
DIVING_FISH_MUSIC_URL = "https://www.diving-fish.com/api/maimaidxprober/music_data"
ALIAS_URL = "https://www.yuzuchan.moe/api/maimaidx/maimaidxalias"
DETAIL_FALLBACK_URL = (
    "https://raw.githubusercontent.com/Choimoe/dxdataViewer/"
    "main/data/csv/merged/sheets.csv"
)
ONECAT_MUSIC_URL = "https://dw.moant.cn:34225/api/getMusicData"
ONECAT_TYPE = {"SD": "standard", "DX": "dx"}
UTAGE_TITLE = re.compile(r"^\[.\]")

DIFFICULTIES = ["basic", "advanced", "expert", "master", "remaster"]
DIFF_LABEL = {
    "basic": "Basic",
    "advanced": "Advanced",
    "expert": "Expert",
    "master": "Master",
    "remaster": "Re:Master",
}
CN_KEYS = {
    "std": ["lev_bas", "lev_adv", "lev_exp", "lev_mas", "lev_remas"],
    "dx": ["dx_lev_bas", "dx_lev_adv", "dx_lev_exp", "dx_lev_mas", "dx_lev_remas"],
}
TYPE_OUT = {"std": "standard", "dx": "dx"}

CATEGORY_FILE = {
    "流行&动漫": "流行and动漫.md",
    "niconico＆VOCALOID™": "niconicoandVOCALOID.md",
    "舞萌": "舞萌.md",
    "东方Project": "东方Project.md",
    "其他游戏": "其他游戏.md",
    "音击/中二节奏": "音击-中二节奏.md",
}
VERSION_ORDER = [
    "maimai", "maimai PLUS", "GreeN", "GreeN PLUS", "ORANGE", "ORANGE PLUS",
    "PiNK", "PiNK PLUS", "MURASAKi", "MURASAKi PLUS", "MiLK", "MiLK PLUS",
    "FiNALE", "舞萌DX", "舞萌DX 2021", "舞萌DX 2022", "舞萌DX 2023",
    "舞萌DX 2024", "舞萌DX 2025", "舞萌DX 2026",
]


def fetch_json(url: str, timeout: int) -> Any:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_text(url: str, timeout: int) -> str:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def norm(value: str) -> str:
    return re.sub(r"[\s（）()・･·]", "", (value or "").lower())


def artist_matches(left: str, right: str) -> bool:
    if norm(left) == norm(right):
        return True
    # 仅接受括号说明的增减，不把偶然包含的短艺术家名当作同一人。
    left, right = (re.sub(r"\s", "", s.lower()).replace("（", "(") for s in (left, right))
    return bool(left and right) and any(right.startswith(left + suffix) or left.startswith(right + suffix)
                                        for suffix in ("(", "feat.", "feat．"))


def title_norm(value: str) -> str:
    value = norm(value).replace(".", "").replace("．", "")
    return value.replace("bandver", "")


def ds_label(value: Any) -> Optional[str]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not 1 <= number <= 15:
        return None
    integer = int(number)
    tenth = round((number - integer) * 10)
    # 官方显示等级：7 级及以上才有 “+”，定数 x.0-x.5 为 x，x.6-x.9 进位为 x+；1-6 级只用整数档。
    if integer < 7:
        return str(integer)
    return f"{integer}+" if tenth >= 6 else str(integer)


def load_old_rows() -> List[Dict[str, Any]]:
    if not LEVEL_INDEX.exists():
        return []
    data = json.loads(LEVEL_INDEX.read_text(encoding="utf-8"))
    return [row for rows in data.values() for row in rows]


def detail_rows_from_divingfish(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for song in data:
        if song.get("type") not in ("SD", "DX"):
            continue
        typ = "std" if str(song.get("type", "")).upper() == "SD" else "dx"
        levels = song.get("level") or []
        ds_values = song.get("ds") or []
        charts = song.get("charts") or []
        info = song.get("basic_info") or {}
        for i, level in enumerate(levels[:5]):
            chart = charts[i] if i < len(charts) else {}
            notes = chart.get("notes") or []
            names = ["tap", "hold", "slide", "touch", "break"] if typ == "dx" else ["tap", "hold", "slide", "break"]
            note_dict = {
                name: int(notes[j]) if j < len(notes) and notes[j] is not None else 0
                for j, name in enumerate(names)
            }
            rows.append({
                "source": "divingfish",
                "songId": str(song.get("id", "")),
                "songTitle": song.get("title", ""),
                "artist": info.get("artist", ""),
                "sheetType": typ,
                "difficulty": DIFFICULTIES[i],
                "level": str(level),
                "internalLevelValue": ds_values[i] if i < len(ds_values) else None,
                "noteDesigner": chart.get("charter"),
                "notes": note_dict,
            })
    return rows


def detail_rows_from_csv(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        typ = row.get("sheetType", "")
        if typ not in ("std", "dx"):
            continue
        notes = {
            "tap": int(row.get("noteTap") or 0),
            "hold": int(row.get("noteHold") or 0),
            "slide": int(row.get("noteSlide") or 0),
        }
        if typ == "dx":
            notes["touch"] = int(row.get("noteTouch") or 0)
        notes["break"] = int(row.get("noteBreak") or 0)
        rows.append({
            "source": "fallback",
            "songId": row.get("songId", ""),
            "songTitle": row.get("songTitle", ""),
            "artist": row.get("artist", ""),
            "sheetType": typ,
            "difficulty": row.get("difficulty", ""),
            "level": row.get("level", ""),
            "internalLevelValue": row.get("internalLevelValue") or None,
            "noteDesigner": row.get("noteDesigner") or None,
            "notes": notes,
        })
    return rows


def build_alias_map(payload: Any) -> Dict[str, List[str]]:
    if isinstance(payload, dict) and payload.get("code") == 0:
        payload = payload.get("content", [])
    result: Dict[str, List[str]] = {}
    if not isinstance(payload, list):
        return result
    for item in payload:
        sid = str(item.get("SongID", ""))
        aliases = item.get("Alias") or []
        if sid and isinstance(aliases, list):
            result[sid] = [str(x) for x in aliases if x]
    return result


def choose_group(
    song: Dict[str, Any],
    typ: str,
    by_title: Dict[str, List[Dict[str, Any]]],
    all_detail_rows: List[Dict[str, Any]],
) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    candidates = [r for r in by_title.get(song["title"], []) if r["sheetType"] == typ]
    if not candidates:
        candidates = [r for r in by_title.get(title_norm(song["title"]), []) if r["sheetType"] == typ]
    if not candidates and song["title"] == "Help me, ERINNNNNN!!" and typ == "std":
        candidates = [
            r for r in all_detail_rows
            if r.get("songTitle") == "Help me, ERINNNNNN!!（Band ver.）" and r["sheetType"] == "std"
        ]
    if not candidates:
        return None

    # 同名曲必须核对艺术家；Link(CoF) 在国服中也显示为 Link。
    artist = norm(song.get("artist", ""))
    exact = [r for r in candidates if norm(r.get("artist", "")) == artist]
    candidates = exact or [r for r in candidates if artist_matches(song.get("artist", ""), r.get("artist", ""))]
    if not candidates:
        return None

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        groups[str(row["songId"])].append(row)

    scored = []
    for sid, rows in groups.items():
        score = 0
        left, right = norm(song.get("artist", "")), norm(rows[0].get("artist", ""))
        if left == right:
            score += 100
        elif left and right and (left in right or right in left):
            score += 60
        for i, diff in enumerate(DIFFICULTIES):
            current = song.get(CN_KEYS[typ][i]) or ""
            detail = next((r for r in rows if r["difficulty"] == diff), None)
            if current and detail and current == detail.get("level"):
                score += 10
            elif not current and detail is None:
                score += 1
        scored.append((score, sid, rows))

    scored.sort(reverse=True, key=lambda item: item[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    _, sid, rows = scored[0]
    return sid, rows


def render_song(song: Dict[str, Any]) -> str:
    lines = [f"## {song['title']}", ""]
    lines.append(f"**ID**: {song.get('id') if song.get('id') is not None else '未知'}")
    if song.get("std_id") and song.get("dx_id") and song["std_id"] != song["dx_id"]:
        lines.append(f"**DX ID**: {song['dx_id']}")
    lines.extend([
        f"**艺术家**: {song['artist']}",
        f"**分类**: {song['category']}",
        f"**版本**: {song['version']}",
        "",
    ])

    aliases = song.get("aliases") or []
    if aliases:
        shown = ", ".join(aliases[:12])
        if len(aliases) > 12:
            shown += f" (共{len(aliases)}个)"
        lines.extend([f"**别名**: {shown}", ""])

    lines.extend(["### 难度信息", ""])
    constants = song.get("ds") or {}
    for typ, label in (("standard", "标准谱面"), ("dx", "DX谱面")):
        data = song["difficulty"][typ]
        if any(data.values()):
            lines.append(f"**{label}**:")
            for diff in DIFFICULTIES:
                value = data.get(diff) or "无"
                ds = (constants.get(typ) or {}).get(diff)
                suffix = f"（定数 {ds:.1f}）" if ds is not None else ""
                lines.append(f"- {DIFF_LABEL[diff]}: {value}{suffix}")
            lines.append("")

    chart_tags = song.get("chart_tags") or {}
    if chart_tags:
        lines.extend(["### 谱面特征", ""])
        for diff in DIFFICULTIES:
            tags = chart_tags.get(diff) or []
            if tags:
                lines.append(f"**{diff.upper()}**: {', '.join(tags)}")
        lines.append("")

    tags = song.get("tags") or []
    if tags:
        lines.extend([f"**标签**: {', '.join(tags)}", ""])
    lines.extend(["---", ""])
    return "\n".join(line.rstrip() for line in lines)


def build_snapshot(timeout: int, cn_file: Optional[Path] = None,
                   details_file: Optional[Path] = None, aliases_file: Optional[Path] = None,
                   fallback_file: Optional[Path] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cn = json.loads(cn_file.read_text(encoding="utf-8")) if cn_file else fetch_json(CN_MAIDATA_URL, timeout)
    if not isinstance(cn, list) or not cn:
        raise ValueError("国服曲库为空或格式错误，拒绝写入")
    old_rows = load_old_rows()
    annotations = load_annotations()
    title_counts = Counter(song["title"] for song in cn)

    old_exact: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    old_loose: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for row in old_rows:
        old_exact[(*identity(row.get("title", ""), row.get("artist", "")), row.get("type"), row.get("difficulty"))] = row
        old_loose[(row.get("title"), row.get("type"), row.get("difficulty"))] = row

    def old_for(song: Dict[str, Any], typ: str, diff: str) -> Optional[Dict[str, Any]]:
        row = old_exact.get((*identity(song["title"], song.get("artist", "")), TYPE_OUT[typ], diff))
        if row is None and title_counts[song["title"]] == 1:
            candidate = old_loose.get((song["title"], TYPE_OUT[typ], diff))
            if candidate and artist_matches(song.get("artist", ""), candidate.get("artist", "")):
                row = candidate
        return row

    try:
        payload = json.loads(details_file.read_text(encoding="utf-8")) if details_file and details_file.suffix == ".json" else None
        detail_rows = (detail_rows_from_csv(details_file.read_text(encoding="utf-8")) if details_file and details_file.suffix == ".csv"
                       else detail_rows_from_divingfish(payload if payload is not None else fetch_json(DIVING_FISH_MUSIC_URL, timeout)))
        if not detail_rows:
            raise ValueError("谱面详情为空")
        print(f"[detail] Diving-Fish: {len(detail_rows)} chart rows")
    except Exception as exc:
        print(f"[detail] Diving-Fish unavailable, fallback to dxdataViewer: {exc}")
        detail_rows = detail_rows_from_csv(fallback_file.read_text(encoding="utf-8") if fallback_file
                                          else fetch_text(DETAIL_FALLBACK_URL, timeout))
        if not detail_rows:
            raise ValueError("主源与备用谱面详情均不可用，拒绝写入")

    by_title: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in detail_rows:
        by_title[row["songTitle"]].append(row)
        by_title[title_norm(row["songTitle"])].append(row)
        if row["songTitle"] in TITLE_EQUIVALENTS:
            by_title[TITLE_EQUIVALENTS[row["songTitle"]]].append(row)

    # 水鱼可能缺少仍在国服的曲目；只用备用源补齐安全匹配的缺失组。
    fallback_rows = []
    fallback_by_title: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if any(any(song.get(k) for k in CN_KEYS[typ]) and choose_group(song, typ, by_title, detail_rows) is None
           for song in cn for typ in ("std", "dx")):
        try:
            fallback_rows = detail_rows_from_csv(fallback_file.read_text(encoding="utf-8") if fallback_file
                                                else fetch_text(DETAIL_FALLBACK_URL, timeout))
            for row in fallback_rows:
                fallback_by_title[row["songTitle"]].append(row)
                fallback_by_title[title_norm(row["songTitle"])].append(row)
                if row["songTitle"] in TITLE_EQUIVALENTS:
                    fallback_by_title[TITLE_EQUIVALENTS[row["songTitle"]]].append(row)
            print(f"[detail] 备用源补缺: {len(fallback_rows)} chart rows")
        except Exception as exc:
            print(f"[detail] 备用源不可用，未匹配详情保留 null: {exc}")

    try:
        alias_map = build_alias_map(json.loads(aliases_file.read_text(encoding="utf-8")) if aliases_file else fetch_json(ALIAS_URL, timeout))
        if not alias_map:
            raise ValueError("别名响应为空或格式错误")
        print(f"[alias] live entries: {len(alias_map)}")
    except Exception as exc:
        print(f"[alias] live API unavailable, keep local aliases: {exc}")
        alias_map = {}

    songs: List[Dict[str, Any]] = []
    level_rows: List[Dict[str, Any]] = []

    for song in cn:
        annotation = annotations.get(identity(song["title"], song.get("artist", "")), {})
        if not annotation:
            matches = [s for (title, artist), s in annotations.items()
                       if title == title_norm(song["title"]) and artist_matches(song.get("artist", ""), s.get("artist", ""))]
            if len(matches) == 1:
                annotation = matches[0]
        chosen = {
            typ: (choose_group(song, typ, by_title, detail_rows)
                  or choose_group(song, typ, fallback_by_title, fallback_rows))
                  if any(song.get(k) for k in CN_KEYS[typ]) else None
            for typ in ("std", "dx")
        }
        ids = {typ: (chosen[typ][0] if chosen[typ] else None) for typ in ("std", "dx")}
        for typ in ("std", "dx"):
            if ids[typ] is None:
                old_ids = {str(r["id"]) for diff in DIFFICULTIES
                           if song.get(CN_KEYS[typ][DIFFICULTIES.index(diff)])
                           for r in [old_for(song, typ, diff)] if r and r.get("id") is not None}
                if len(old_ids) == 1:
                    ids[typ] = next(iter(old_ids))

        aliases = [song["title"]]
        aliases.extend(annotation.get("aliases") or [])
        for sid in (ids["std"], ids["dx"]):
            aliases.extend(alias_map.get(str(sid), []))
        for row in old_rows:
            if row.get("title") == song["title"] and (
                norm(row.get("artist", "")) == norm(song.get("artist", ""))
                or (title_counts[song["title"]] == 1 and artist_matches(song.get("artist", ""), row.get("artist", "")))
            ):
                aliases.extend(row.get("aliases") or [])
                break
        aliases = list(dict.fromkeys(re.sub(r"[\r\n]+", " ", alias).strip() for alias in aliases if alias.strip()))

        difficulty = {"standard": {}, "dx": {}}
        tags_by_diff: Dict[str, List[str]] = {d: list(t) for d, t in (annotation.get("chart_tags") or {}).items()}

        for typ in ("std", "dx"):
            group_rows = chosen[typ][1] if chosen[typ] else []
            for i, diff in enumerate(DIFFICULTIES):
                value = song.get(CN_KEYS[typ][i]) or None
                difficulty[TYPE_OUT[typ]][diff] = value
                if not value:
                    continue

                detail = next((r for r in group_rows if r["difficulty"] == diff), None)
                old = old_for(song, typ, diff)

                ds = None
                ds_source = None
                if detail and detail.get("internalLevelValue") is not None:
                    candidate = detail["internalLevelValue"]
                    if ds_label(candidate) == value:
                        ds = float(candidate)
                        ds_source = detail["source"]
                # 最新源冲突时不回填旧定数，以免把过时值当作国服精确定数。
                if detail is None and old and old.get("ds") is not None and ds_label(old["ds"]) == value:
                    ds = float(old["ds"])
                    ds_source = "local"

                chart_tags = list(dict.fromkeys((old or {}).get("chart_tags") or []))
                if chart_tags:
                    tags_by_diff[diff] = list(dict.fromkeys(tags_by_diff.get(diff, []) + chart_tags))

                notes = detail.get("notes") if detail else (old or {}).get("notes")
                charter = (detail or {}).get("noteDesigner") or (old or {}).get("charter")

                sid = ids[typ]
                if sid is None and old and old.get("id") is not None:
                    sid = str(old["id"])
                level_rows.append({
                    "id": int(sid) if sid and str(sid).isdigit() else sid,
                    "title": song["title"],
                    "aliases": aliases,
                    "artist": song.get("artist", ""),
                    "category": song.get("category", ""),
                    "version": song.get("version", ""),
                    "type": TYPE_OUT[typ],
                    "difficulty": diff,
                    "value": value,
                    "ds": ds,
                    "ds_source": ds_source,
                    "detail_source": detail["source"] if detail else "local" if old else None,
                    "charter": charter,
                    "notes": notes,
                    "chart_tags": chart_tags,
                })

        tags = {song.get("artist", ""), song.get("category", ""), song.get("version", "")}
        for sep in ("&", "＆", "/"):
            if sep in song.get("category", ""):
                tags.update(part.strip() for part in song["category"].split(sep) if part.strip())
        for values in tags_by_diff.values():
            tags.update(values)

        primary = ids["std"] or ids["dx"]
        songs.append({
            "id": int(primary) if primary and str(primary).isdigit() else primary,
            "std_id": int(ids["std"]) if ids["std"] and str(ids["std"]).isdigit() else ids["std"],
            "dx_id": int(ids["dx"]) if ids["dx"] and str(ids["dx"]).isdigit() else ids["dx"],
            "title": song["title"],
            "artist": song.get("artist", ""),
            "category": song.get("category", ""),
            "version": song.get("version", ""),
            "aliases": aliases,
            "image_file": song.get("image_file", ""),
            "difficulty": difficulty,
            "ds": {"standard": {}, "dx": {}},
            "chart_tags": tags_by_diff,
            "tags": sorted(tag for tag in tags if tag),
        })

    sync_song_charts(songs, level_rows)
    return songs, level_rows


def load_onecat(payload_path: Optional[Path], timeout: int) -> List[Dict[str, Any]]:
    """读取 OneCat 官方谱面站 music 数据；兼容 {success, data} 包装与纯列表。"""
    payload = (json.loads(payload_path.read_text(encoding="utf-8"))
               if payload_path else fetch_json(ONECAT_MUSIC_URL, timeout))
    if isinstance(payload, dict):
        payload = payload.get("data") or []
    if not isinstance(payload, list) or not payload:
        raise ValueError("OneCat 谱面数据为空或格式错误")
    return payload


def onecat_index(payload: List[Dict[str, Any]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """按 (谱面类型, 曲目ID) 建索引。宴谱（宴会場 / [X] 标题）不收录。"""
    index: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for entry in payload:
        typ = ONECAT_TYPE.get(str(entry.get("type", "")).upper())
        if typ is None:
            continue
        try:
            song_id = int(entry["id"])
        except (KeyError, TypeError, ValueError):
            continue
        genre = (entry.get("basic_info") or {}).get("genre") or ""
        # 宴谱（100000+ ID、宴会場分类、[X] 标题）不收录；常规谱面里的 “[X]” 这类曲名要保留。
        if genre == "宴会場" or (song_id >= 100000 and UTAGE_TITLE.match(entry.get("title") or "")):
            continue
        index[(typ, song_id)] = entry
    return index


def sync_song_charts(songs: List[Dict[str, Any]], level_rows: List[Dict[str, Any]]) -> None:
    """把谱面行的显示等级与精确定数回写到歌曲快照，保持两份数据一致。"""
    levels = {(row["type"], row["id"], row["difficulty"]): row.get("value") for row in level_rows}
    constants = {(row["type"], row["id"], row["difficulty"]): row.get("ds") for row in level_rows}
    for song in songs:
        if "ds" not in song:
            ordered: Dict[str, Any] = {}
            for key, value in song.items():
                ordered[key] = value
                if key == "difficulty":
                    ordered["ds"] = {"standard": {}, "dx": {}}
            ordered.setdefault("ds", {"standard": {}, "dx": {}})
            song.clear()
            song.update(ordered)
        for typ, song_id in (("standard", song.get("std_id")), ("dx", song.get("dx_id"))):
            bucket = song.setdefault("ds", {}).setdefault(typ, {})
            for diff in DIFFICULTIES:
                key = (typ, song_id, diff)
                level = levels.get(key)
                if song_id is not None and level and typ in song.get("difficulty", {}):
                    song["difficulty"][typ][diff] = level
                bucket[diff] = constants.get(key)


def apply_onecat(songs: List[Dict[str, Any]], level_rows: List[Dict[str, Any]],
                 payload: List[Dict[str, Any]], source: str = "onecat"
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Counter]:
    """用 OneCat 最新定数覆盖快照，并按官方边界换算显示等级。"""
    index = onecat_index(payload)
    stats: Counter = Counter()
    for row in level_rows:
        try:
            song_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            stats["无ID"] += 1
            continue
        entry = index.get((row["type"], song_id))
        if entry is None:
            stats["源未收录"] += 1
            continue
        position = DIFFICULTIES.index(row["difficulty"])
        values = entry.get("ds") or []
        candidate = values[position] if position < len(values) else None
        try:
            ds = float(candidate)
        except (TypeError, ValueError):
            stats["源无定数"] += 1
            continue
        value = ds_label(ds)
        if value is None:
            stats["定数越界"] += 1
            continue
        if row.get("ds") is None:
            stats["补全定数"] += 1
        elif abs(float(row["ds"]) - ds) > 1e-9:
            stats["修正定数"] += 1
        else:
            stats["定数一致"] += 1
        if row.get("value") != value:
            stats["修正显示等级"] += 1
        row["ds"] = ds
        row["ds_source"] = source
        row["value"] = value
    sync_song_charts(songs, level_rows)
    return songs, level_rows, stats


def add_missing_charts(songs: List[Dict[str, Any]], level_rows: List[Dict[str, Any]],
                       payload: List[Dict[str, Any]], detail_rows: Optional[List[Dict[str, Any]]] = None
                       ) -> List[Dict[str, Any]]:
    """补上 OneCat 已有、快照缺失的谱面（典型：国服尚未收录的新增 Re:MASTER）。"""
    index = onecat_index(payload)
    details: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for row in detail_rows or []:
        details[(str(row.get("sheetType")), str(row.get("songId")), row.get("difficulty"))] = row
    have = {(row["type"], str(row["id"]), row["difficulty"]) for row in level_rows}
    added: List[Dict[str, Any]] = []
    for song in songs:
        for typ, song_id in (("standard", song.get("std_id")), ("dx", song.get("dx_id"))):
            try:
                song_id = int(song_id)
            except (TypeError, ValueError):
                continue
            entry = index.get((typ, song_id))
            if entry is None:
                continue
            for position, ds in enumerate(entry.get("ds") or []):
                diff = DIFFICULTIES[position]
                if ds is None or (typ, str(song_id), diff) in have:
                    continue
                value = ds_label(ds)
                if value is None:
                    continue
                detail = details.get(("std" if typ == "standard" else "dx", str(song_id), diff)) or {}
                row = {
                    "id": song_id,
                    "title": song["title"],
                    "aliases": list(song.get("aliases") or []),
                    "artist": song.get("artist", ""),
                    "category": song.get("category", ""),
                    "version": song.get("version", ""),
                    "type": typ,
                    "difficulty": diff,
                    "value": value,
                    "ds": float(ds),
                    "ds_source": "onecat",
                    "detail_source": detail.get("source") or "onecat",
                    "charter": detail.get("noteDesigner"),
                    "notes": detail.get("notes"),
                    "chart_tags": [],
                }
                level_rows.append(row)
                have.add((typ, str(song_id), diff))
                added.append(row)
    if added:
        sync_song_charts(songs, level_rows)
    return added


def write_snapshot_meta(songs: List[Dict[str, Any]], level_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """刷新 snapshot_meta.json 的统计字段，保留版本号等人工维护字段。"""
    meta: Dict[str, Any] = {}
    if SNAPSHOT_META.exists():
        try:
            meta = json.loads(SNAPSHOT_META.read_text(encoding="utf-8"))
        except ValueError:
            meta = {}
    meta.update({
        "updated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
        "songs": len(songs),
        "unique_titles": len({song["title"] for song in songs}),
        "categories": len({song["category"] for song in songs}),
        "charts": len(level_rows),
        "charts_with_ds": sum(1 for row in level_rows if row["ds"] is not None),
        "ds_sources": dict(Counter(row["ds_source"] for row in level_rows)),
        "detail_sources": dict(Counter(row["detail_source"] for row in level_rows)),
    })
    SNAPSHOT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def validate_snapshot(songs: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> None:
    """写入前验证曲目唯一性、完整谱面集合、等级/定数、ID 和音符数据。"""
    keys = [identity(s["title"], s["artist"]) for s in songs]
    if len(keys) != len(set(keys)):
        raise ValueError("重复歌曲身份")
    expected = {(identity(s["title"], s["artist"]), typ, diff, value)
                for s in songs for typ, values in s["difficulty"].items()
                for diff, value in values.items() if value}
    actual = [(identity(r["title"], r["artist"]), r["type"], r["difficulty"], r["value"]) for r in rows]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("重复、缺失或多余谱面")
    constants = {(r["type"], r["id"], r["difficulty"]): r["ds"] for r in rows}
    for song in songs:
        for typ, song_id in (("standard", song.get("std_id")), ("dx", song.get("dx_id"))):
            for diff in DIFFICULTIES:
                level = (song["difficulty"].get(typ) or {}).get(diff)
                ds = ((song.get("ds") or {}).get(typ) or {}).get(diff)
                if song_id is None:
                    if level or ds is not None:
                        raise ValueError("无ID却有谱面数据")
                    continue
                if (level is None) != (constants.get((typ, song_id, diff)) is None):
                    raise ValueError("歌曲定数与谱面索引不一致")
                if ds != constants.get((typ, song_id, diff)):
                    raise ValueError("歌曲定数与谱面索引不一致")
    ids = {}
    songs_by_key = {identity(s["title"], s["artist"]): s for s in songs}
    for s in songs:
        if s["category"] not in CATEGORY_FILE:
            raise ValueError(f"未知分类: {s['category']}")
    for r in rows:
        expected_id = songs_by_key[identity(r["title"], r["artist"])]["std_id" if r["type"] == "standard" else "dx_id"]
        if r["id"] != expected_id:
            raise ValueError("歌曲与谱面ID不一致")
        if not re.fullmatch(r"(?:[1-9]|1[0-4])\+?|15", r["value"]):
            raise ValueError(f"无效显示等级: {r['value']}")
        if r["ds"] is not None and ds_label(r["ds"]) != r["value"]:
            raise ValueError("定数与显示等级不一致")
        if r["id"] is not None:
            owner = (identity(r["title"], r["artist"]), r["type"])
            if r["id"] in ids and ids[r["id"]] != owner:
                raise ValueError(f"ID误配: {r['id']}")
            ids[r["id"]] = owner
        if r["notes"] is not None and any(not isinstance(n, int) or n < 0 for n in r["notes"].values()):
            raise ValueError("音符数必须是非负整数")
        if not isinstance(r["aliases"], list) or not isinstance(r["chart_tags"], list):
            raise ValueError("别名/标签格式错误")


def write_snapshot(songs: List[Dict[str, Any]], level_rows: List[Dict[str, Any]]) -> None:
    validate_snapshot(songs, level_rows)
    SONGS_FILE.write_text(json.dumps(songs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    def level_key(value: str) -> Tuple[int, str]:
        match = re.match(r"^(\d+)(\+)?", value)
        if not match:
            return (999, value)
        return (int(match.group(1)) * 2 + (1 if match.group(2) else 0), value)

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in level_rows:
        grouped[row["value"]].append(row)
    ordered: Dict[str, List[Dict[str, Any]]] = {}
    for key in sorted(grouped, key=level_key):
        ordered[key] = sorted(
            grouped[key],
            key=lambda row: (row["title"], row["type"], DIFFICULTIES.index(row["difficulty"])),
        )
    LEVEL_INDEX.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    KB_DIR.mkdir(exist_ok=True)
    version_rank = {version: i for i, version in enumerate(VERSION_ORDER)}
    for category, filename in CATEGORY_FILE.items():
        current = [song for song in songs if song["category"] == category]
        by_version: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for song in current:
            by_version[song["version"]].append(song)
        parts = [f"# {category}\n\n本分类共有 {len(current)} 条歌曲记录。\n"]
        for version in sorted(by_version, key=lambda v: (version_rank.get(v, 999), v)):
            items = by_version[version]
            parts.append(f"\n## {version} ({len(items)}首)\n")
            parts.extend("\n" + render_song(song) for song in items)
        (KB_DIR / filename).write_text("".join(parts), encoding="utf-8")

    version_count = Counter(song["version"] for song in songs)
    category_count = Counter(song["category"] for song in songs)
    tagged = sum(1 for song in songs if song["chart_tags"])
    associations = sum(
        sum(len(values) for values in song["chart_tags"].values())
        for song in songs
    )
    all_tags = sorted({
        tag
        for song in songs
        for values in song["chart_tags"].values()
        for tag in values
    })

    lines = [
        "# 舞萌DX歌曲知识库索引",
        "",
        f"共有 **{len(songs)} 条歌曲记录**（{len({song['title'] for song in songs})} 个唯一标题）。",
        f"共有 **{len(level_rows)} 张常规谱面**。",
        "",
        "曲目、分类和版本以国服曲库为准；精确定数与显示等级取 OneCat 官方谱面站的最新数据。",
        "",
        "## 按版本分类",
        "",
    ]
    for version in sorted(version_count, key=lambda v: (version_rank.get(v, 999), v)):
        lines.append(f"- **{version}**: {version_count[version]} 首歌曲")
    lines.extend(["", "## 按分类分类", ""])
    for category, filename in CATEGORY_FILE.items():
        lines.append(f"- [{category}](./{filename}): {category_count[category]} 首歌曲")
    lines.extend([
        "", "## 别名统计", "",
        f"- 包含别名的歌曲: {sum(bool(s['aliases']) for s in songs)} 首",
        f"- 总别名数量（含标题）: {sum(len(s['aliases']) for s in songs)} 个",
    ])
    lines.extend([
        "", "## 谱面特征统计", "",
        f"- 包含谱面特征的歌曲: {tagged} 首",
        f"- 总标签关联数（每首歌曲各难度内去重）: {associations} 个",
        "", "## 可用的谱面特征标签", "",
    ])
    lines.extend(f"- {tag}" for tag in all_tags)
    missing_ds = sum(1 for row in level_rows if row["ds"] is None)
    ds_note = ("全部谱面都有精确定数。" if missing_ds == 0
               else f"{missing_ds} 张谱面无可用定数，level_index.json 中的 ds 为 null，不做猜测。")
    lines.extend([
        "", "## 搜索提示", "",
        "可以按标题、别名、艺术家、分类、版本、显示等级和谱面特征进行组合查询。",
        f"精确定数与显示等级取 OneCat 官方谱面站最新值（显示等级由定数换算）；{ds_note}",
        "",
    ])
    (KB_DIR / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    write_snapshot_meta(songs, level_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cn-file", type=Path, help="使用本地国服源 JSON")
    parser.add_argument("--details-file", type=Path, help="使用本地水鱼 JSON 或备用 CSV")
    parser.add_argument("--fallback-file", type=Path, help="使用本地备用 CSV 补缺")
    parser.add_argument("--aliases-file", type=Path, help="使用本地别名 JSON；空列表表示保留现有别名")
    parser.add_argument("--onecat-file", type=Path, help="使用本地 OneCat getMusicData JSON 刷新定数")
    parser.add_argument("--validate-only", action="store_true", help="离线校验已提交快照")
    parser.add_argument("--render-only", action="store_true", help="离线重建 Markdown 和索引")
    args = parser.parse_args()

    if args.validate_only or args.render_only:
        songs = json.loads(SONGS_FILE.read_text(encoding="utf-8"))
        level_rows = load_old_rows()
    else:
        songs, level_rows = build_snapshot(args.timeout, args.cn_file, args.details_file, args.aliases_file, args.fallback_file)
        try:
            payload = load_onecat(args.onecat_file, args.timeout)
        except Exception as exc:
            print(f"[onecat] 定数源不可用，保留快照现有定数: {exc}")
        else:
            songs, level_rows, onecat_stats = apply_onecat(songs, level_rows, payload)
            print(f"[onecat] {dict(onecat_stats)}")
    validate_snapshot(songs, level_rows)
    print(f"歌曲记录: {len(songs)}；谱面记录: {len(level_rows)}")
    if args.dry_run or args.validate_only:
        return
    write_snapshot(songs, level_rows)
    print("✅ level_index.json 与 knowledge_base/*.md 已更新")


if __name__ == "__main__":
    main()
