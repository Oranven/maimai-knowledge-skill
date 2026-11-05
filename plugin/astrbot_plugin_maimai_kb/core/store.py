# -*- coding: utf-8 -*-
"""舞萌DX知识库查询核心：纯标准库、离线、确定性查询。

官方快照（songs.json / level_index.json）与手动录入库（manual_songs.json）
在加载时合并：手动条目不会写进官方快照，版本更新覆盖 data/ 也不会丢。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .manual import (ManualStore, alias_scopes as manual_alias_scopes,
                     chart_rows as manual_chart_rows, overlay_aliases,
                     song_key as manual_song_key)
from .text import (DIFF_ALIASES, DIFF_LABEL, DIFFICULTIES, LEVEL_RE, STRIP_RE,
                   TYPE_ALIASES, TYPE_LABEL, ds_label, fmt_ds, level_rank, norm,
                   parse_difficulty, parse_level, parse_type)

__all__ = [
    "DIFF_ALIASES", "DIFF_LABEL", "DIFFICULTIES", "LEVEL_RE", "STRIP_RE", "Store",
    "TYPE_ALIASES", "TYPE_LABEL", "ds_label", "fmt_ds", "level_rank", "norm",
    "parse_difficulty", "parse_level", "parse_type",
]

MANUAL_TAG = "手动录入"


class Store:
    """加载官方快照 + 手动库，提供确定性查询。"""

    def __init__(self, data_dir: str | Path, manual_dir: str | Path | None = None):
        self.data_dir = Path(data_dir)
        # 手动库放在独立目录（AstrBot 的 data/plugin_data/<插件名>），
        # 覆盖安装插件不会清掉；没给就用 data/ 自身（便于脚本/测试）。
        self.manual = ManualStore(manual_dir or self.data_dir)

        self.official_songs: List[Dict[str, Any]] = json.loads(
            (self.data_dir / "songs.json").read_text(encoding="utf-8"))
        self.level_index: Dict[str, List[Dict[str, Any]]] = json.loads(
            (self.data_dir / "level_index.json").read_text(encoding="utf-8"))
        meta_path = self.data_dir / "snapshot_meta.json"
        self.meta: Dict[str, Any] = (json.loads(meta_path.read_text(encoding="utf-8"))
                                     if meta_path.exists() else {})

        # 别名补丁：官方曲目追加/删除别名，并支持标准 / DX 谱面专属
        self.official_alias_count: int = self._apply_official_aliases()

        # 谱面补丁：官方已有的歌追加/修正某一张谱面（只动内存，官方 JSON 不变）
        self.patches: List[Dict[str, Any]] = self.manual.patches()
        self.applied_patches: int = self._apply_patches()

        # 手动条目：与官方歌曲同结构，合并进查询索引
        self.manual_songs: List[Dict[str, Any]] = self.manual.songs()
        self.songs: List[Dict[str, Any]] = self.official_songs + self.manual_songs
        self.manual_rows: List[Dict[str, Any]] = manual_chart_rows(self.manual_songs)

        # 谱面行按 (类型, 曲目ID, 难度) 索引，用于取谱师与音符数
        self.chart_rows: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for rows in self.level_index.values():
            for row in rows:
                self.chart_rows[(row["type"], str(row["id"]), row["difficulty"])] = row
        # 手动条目没有官方 ID，用 标题+艺术家 的键，避免多首手动歌共用 "None" 互相覆盖
        for row in self.manual_rows:
            self.chart_rows[(row["type"], row["song_key"], row["difficulty"])] = row
            self.level_index.setdefault(row["value"], []).append(row)

        self.exact_title: Dict[str, List[Dict[str, Any]]] = {}
        self.exact_alias: Dict[str, List[Dict[str, Any]]] = {}
        self.fuzzy_keys: List[Tuple[str, Dict[str, Any]]] = []
        self._song_keys: Dict[int, Tuple[str, List[str]]] = {}
        for song in self.songs:
            title_key = norm(song["title"])
            alias_keys = sorted({norm(alias) for alias in song.get("aliases") or []
                                 if "(共" not in str(alias)} - {""})
            self._song_keys[id(song)] = (title_key, alias_keys)
            if title_key:
                self.exact_title.setdefault(title_key, []).append(song)
            for alias_key in alias_keys:
                self.exact_alias.setdefault(alias_key, []).append(song)
            # 单字符键只参与精确匹配，避免包含匹配把无关曲目召回（emoji 别名属此类）
            for key in ({title_key} if title_key else set()) | set(alias_keys):
                if len(key) >= 2:
                    self.fuzzy_keys.append((key, song))
        self.fuzzy_keys.sort(key=lambda item: len(item[0]), reverse=True)

    def _apply_official_aliases(self) -> int:
        """把 official_aliases.json 合并进官方内存数据，返回生效条数。"""
        records = self.manual.alias_records()
        if not records:
            return 0
        by_title: Dict[str, List[Dict[str, Any]]] = {}
        for song in self.official_songs:
            by_title.setdefault(norm(song.get("title")), []).append(song)
        applied = 0
        for record in records:
            candidates = by_title.get(norm(record.get("title")), [])
            if record.get("artist"):
                candidates = [song for song in candidates
                              if norm(song.get("artist")) == norm(record.get("artist"))]
            if not candidates:
                # 官方删了这首歌或改了名：别名补丁悬空，文件保留但不生效
                continue
            song = candidates[0]
            song.setdefault("_official_aliases", list(song.get("aliases") or []))
            merged, scopes = overlay_aliases(song, record)
            song["aliases"] = merged
            song["alias_scopes"] = scopes
            song["alias_patch"] = {
                "author": record.get("author") or "未知",
                "updated_at": record.get("updated_at") or record.get("created_at") or "",
                "added": list(record.get("added") or []),
                "removed": list(record.get("removed") or []),
            }
            applied += 1
        return applied

    def _apply_patches(self) -> int:
        """把 manual_charts.json 的补丁合并进官方内存数据，返回生效条数。"""
        if not self.patches:
            return 0
        by_title: Dict[str, List[Dict[str, Any]]] = {}
        for song in self.official_songs:
            by_title.setdefault(norm(song.get("title")), []).append(song)
        applied = 0
        for patch in self.patches:
            typ, diff = patch.get("type"), patch.get("difficulty")
            level = str(patch.get("level") or "")
            if typ not in ("standard", "dx") or diff not in DIFFICULTIES or not level:
                continue
            candidates = by_title.get(norm(patch.get("title")), [])
            if patch.get("artist"):
                candidates = [song for song in candidates
                              if norm(song.get("artist")) == norm(patch.get("artist"))]
            if not candidates:
                # 官方删了这首歌或改了名：补丁悬空，文件保留但不生效
                continue
            song = candidates[0]
            song.setdefault("difficulty", {}).setdefault(typ, {})[diff] = level
            song.setdefault("ds", {}).setdefault(typ, {})[diff] = patch.get("ds")
            song.setdefault("patch", {})[f"{typ}|{diff}"] = dict(patch)
            self._apply_patch_row(song, patch)
            applied += 1
        return applied

    def _apply_patch_row(self, song: Dict[str, Any], patch: Dict[str, Any]) -> None:
        """让补丁谱面也出现在等级/定数区间检索里（替换掉官方那一行）。"""
        typ, diff = patch["type"], patch["difficulty"]
        song_id = song.get("std_id") if typ == "standard" else song.get("dx_id")
        original: Dict[str, Any] = {}
        for rows in self.level_index.values():
            for row in rows:
                if (row.get("type") == typ
                        and str(row.get("id")) == str(song_id)
                        and row.get("difficulty") == diff):
                    original = row
                    break
            if original:
                break
        # 只改等级/定数时保留原谱面的谱师、音符数与标签，不能因为打补丁就把它们抹掉
        def keep(field: str, fallback: Any) -> Any:
            return patch[field] if patch.get(field) is not None else fallback

        for rows in self.level_index.values():
            rows[:] = [row for row in rows
                       if not (row.get("type") == typ
                               and str(row.get("id")) == str(song_id)
                               and row.get("difficulty") == diff)]
        self.level_index.setdefault(str(patch["level"]), []).append({
            "id": song_id,
            "title": song.get("title", ""),
            "aliases": list(song.get("aliases") or []),
            "artist": song.get("artist", ""),
            "category": song.get("category", ""),
            "version": song.get("version", ""),
            "type": typ,
            "difficulty": diff,
            "value": str(patch["level"]),
            "ds": patch.get("ds"),
            "ds_source": "manual",
            "detail_source": "manual",
            "charter": keep("charter", original.get("charter")),
            "notes": keep("notes", original.get("notes")),
            "chart_tags": keep("chart_tags", list(original.get("chart_tags") or [])),
            "patch": True,
        })

    def reload(self) -> "Store":
        """手动库改完后重建索引（官方快照不重读以外，行为与新建一致）。"""
        self.__init__(self.data_dir, self.manual.dir)  # type: ignore[misc]
        return self

    # ------------------------------------------------------------ 基本信息

    @property
    def song_count(self) -> int:
        return len(self.songs)

    @property
    def chart_count(self) -> int:
        return len(self.chart_rows)

    @property
    def official_song_count(self) -> int:
        return len(self.official_songs)

    @property
    def manual_song_count(self) -> int:
        return len(self.manual_songs)

    @property
    def manual_chart_count(self) -> int:
        return len(self.manual_rows)

    def snapshot(self) -> Dict[str, Any]:
        meta = dict(self.meta)
        meta["manual_songs"] = self.manual_song_count
        meta["manual_charts"] = self.manual_chart_count
        meta["patched_charts"] = self.applied_patches
        meta["alias_overrides"] = self.official_alias_count
        return meta

    def levels(self) -> List[str]:
        return sorted(self.level_index, key=level_rank)

    def charts_of(self, song: Dict[str, Any]) -> List[Dict[str, Any]]:
        """一首歌的全部谱面，标准谱面在前。"""
        charts: List[Dict[str, Any]] = []
        is_manual = bool(song.get("manual"))
        for typ in ("standard", "dx"):
            song_id = song.get("std_id") if typ == "standard" else song.get("dx_id")
            levels = (song.get("difficulty") or {}).get(typ) or {}
            constants = (song.get("ds") or {}).get(typ) or {}
            for diff in DIFFICULTIES:
                level = levels.get(diff)
                if not level:
                    continue
                lookup = manual_song_key(song) if is_manual else str(song_id)
                row = self.chart_rows.get((typ, lookup, diff)) or {}
                patched = {} if is_manual else \
                    (song.get("patch") or {}).get(f"{typ}|{diff}") or {}
                charts.append({
                    "type": typ,
                    "type_label": TYPE_LABEL[typ],
                    "song_id": song_id,
                    "manual": is_manual,
                    "patched": bool(patched),
                    "difficulty": diff,
                    "difficulty_label": DIFF_LABEL[diff],
                    "level": str(level),
                    "ds": (patched.get("ds") if patched
                           else row.get("ds", constants.get(diff))),
                    "charter": row.get("charter"),
                    "notes": row.get("notes"),
                    "chart_tags": row.get("chart_tags") or [],
                })
        return charts

    def chart_of(self, song: Dict[str, Any], typ: Optional[str],
                 difficulty: Optional[str]) -> Optional[Dict[str, Any]]:
        for chart in self.charts_of(song):
            if typ and chart["type"] != typ:
                continue
            if difficulty and chart["difficulty"] != difficulty:
                continue
            return chart
        return None

    # ------------------------------------------------------------ 搜索

    def find(self, query: str) -> List[Tuple[int, Dict[str, Any]]]:
        """按标题/别名查找，返回 [(分数, song)]，分数降序。"""
        key = norm(query)
        if not key:
            return []
        scored: Dict[int, Tuple[int, Dict[str, Any]]] = {}
        for song in self.exact_title.get(key, []):
            scored[id(song)] = (100, song)
        for song in self.exact_alias.get(key, []):
            scored.setdefault(id(song), (95, song))
        for song in self.songs:
            if id(song) in scored or len(key) < 2:
                continue
            title, aliases = self._song_keys[id(song)]
            score = 0
            if title and (title.startswith(key) or (len(title) >= 3 and key.startswith(title))):
                score = 80
            elif any(alias.startswith(key) for alias in aliases if len(alias) >= 2):
                score = 70
            elif title and key in title:
                score = 60
            elif any(key in alias for alias in aliases if len(alias) >= 2):
                score = 50
            if score:
                scored[id(song)] = (score, song)
        return sorted(scored.values(), key=lambda item: (-item[0], item[1]["title"]))[:20]

    def alias_scope(self, song: Dict[str, Any], query: str) -> Optional[str]:
        """查询词若是某首歌的「类型专属别名」，返回该类型。

        例：把「某曲DX名」设为 DX 专属别名后，用这个名字查只显示 DX 谱面。
        官方曲目与手动条目都适用。同名别名同时挂在两种类型下、或查询词就是
        曲名时返回 None。
        """
        key = norm(query)
        if not key or key == norm(song.get("title")):
            return None
        scopes = manual_alias_scopes(song)
        hits = [typ for typ in ("standard", "dx")
                if any(norm(alias) == key for alias in scopes.get(typ) or [])]
        return hits[0] if len(hits) == 1 else None

    def manual_alias_scope(self, song: Dict[str, Any], query: str) -> Optional[str]:
        """向后兼容旧调用名。"""
        return self.alias_scope(song, query)

    def official_match(self, query: str) -> List[Dict[str, Any]]:
        """在官方快照里按曲名/别名精确匹配（给谱面补丁定位用）。"""
        key = norm(query)
        if not key:
            return []
        hits = [song for song in self.official_songs if norm(song.get("title")) == key]
        if hits:
            return hits
        return [song for song in self.official_songs
                if any(norm(alias) == key for alias in song.get("aliases") or [])]

    def find_one(self, query: str) -> Optional[Dict[str, Any]]:
        results = self.find(query)
        return results[0][1] if results else None

    def mentioned(self, text: str, limit: int = 1) -> List[Dict[str, Any]]:
        """从一句话里认出被提到的曲目：长名优先，短英文键跳过以防误命中。"""
        key = norm(text)
        if len(key) < 2:
            return []
        found: List[Dict[str, Any]] = []
        for needle, song in self.fuzzy_keys:  # 已按长度降序
            if needle.isascii() and len(needle) < 3:
                continue
            if needle not in key:
                continue
            if any(song is item for item in found):
                continue
            found.append(song)
            if len(found) >= limit:
                break
        return found

    # ------------------------------------------------------------ 等级检索

    def level_rows(self, level: str, typ: Optional[str] = None,
                   difficulty: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = list(self.level_index.get(parse_level(level) or str(level), []))
        if typ:
            rows = [row for row in rows if row["type"] == typ]
        if difficulty:
            rows = [row for row in rows if row["difficulty"] == difficulty]
        rows.sort(key=lambda row: (-float(row["ds"] or 0), row["title"]))
        return rows

    def ds_range(self, low: float, high: float, typ: Optional[str] = None,
                 difficulty: Optional[str] = None, limit: int = 15) -> List[Dict[str, Any]]:
        rows = [row for rows in self.level_index.values() for row in rows
                if row["ds"] is not None and low <= float(row["ds"]) <= high
                and (typ is None or row["type"] == typ)
                and (difficulty is None or row["difficulty"] == difficulty)]
        rows.sort(key=lambda row: (-float(row["ds"]), row["title"]))
        return rows[:limit]
