# -*- coding: utf-8 -*-
"""手动录入的歌曲库（overlay）：与官方快照分开存放，版本更新不会覆盖。

- ``data/manual_songs.json``：已生效的手动条目，结构与 songs.json 的歌曲一致
- ``data/manual_pending.json``：普通用户提交、等待管理员审核的条目
- 两个文件都不进插件 zip（见 build_astrbot_plugin.SKIP_FILES），
  所以升级覆盖安装时不会清掉聊天里录进去的数据。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .text import (DIFFICULTIES, DIFF_LABEL, TYPE_LABEL, ds_label, norm,
                   parse_difficulty, parse_level, parse_type)

MANUAL_FILE = "manual_songs.json"
PENDING_FILE = "manual_pending.json"
# 官方快照已有曲目的「谱面补丁」：只覆盖/追加某一张谱面，不改官方 JSON
PATCH_FILE = "manual_charts.json"
# 官方快照已有曲目的「别名补丁」：追加/删除别名，并可把别名限定到
# 标准谱面或 DX 谱面（同样只在内存里合并，不改官方 JSON）
ALIAS_FILE = "official_aliases.json"
DEFAULT_CATEGORY = "舞萌"
DEFAULT_VERSION = "手动录入"
MAX_ENTRIES = 200

TITLE_LIMIT = 120
FIELD_LIMIT = 60


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 文件读写

def _read_list(path: Path) -> List[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write_list(path: Path, items: Sequence[Dict[str, Any]]) -> None:
    """原子写入：先写临时文件再替换，避免写一半断电留下坏 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False,
                                         dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with handle:
            json.dump(list(items), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- 数据校验

def _clean(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def describe(difficulty: str, typ: str) -> str:
    return f"{TYPE_LABEL[typ]} {DIFF_LABEL[difficulty]}"


def make_song(title: str, artist: str, category: str = "", version: str = "",
              aliases: Optional[Iterable[str]] = None, author: str = "") -> Dict[str, Any]:
    """按 songs.json 的结构造一首手动歌曲（id 为 None，表示无官方 ID）。"""
    title = _clean(title, TITLE_LIMIT)
    now = _now()
    alias_list = [title] + [_clean(alias, TITLE_LIMIT) for alias in aliases or []]
    return {
        "id": None,
        "std_id": None,
        "dx_id": None,
        "title": title,
        "artist": _clean(artist, FIELD_LIMIT),
        "category": _clean(category, FIELD_LIMIT) or DEFAULT_CATEGORY,
        "version": _clean(version, FIELD_LIMIT) or DEFAULT_VERSION,
        "aliases": list(dict.fromkeys(alias for alias in alias_list if alias)),
        # 别名作用域：standard / dx 各自专属的别名；aliases 里仍是全部别名的并集
        "alias_scopes": {"standard": [], "dx": []},
        "difficulty": {"standard": {}, "dx": {}},
        "ds": {"standard": {}, "dx": {}},
        "chart_tags": {},
        "tags": [],
        "manual": {"author": _clean(author, FIELD_LIMIT) or "未知", "created_at": now,
                   "updated_at": now},
    }


def set_chart(song: Dict[str, Any], typ: str, difficulty: str, level: str,
              ds: Optional[Any] = None) -> Tuple[bool, str]:
    """写入一张谱面；返回 (是否成功, 提示文案)。"""
    if typ not in ("standard", "dx"):
        return False, "类型只能是 dx / 标准（可省略，默认 dx）。"
    if difficulty not in DIFFICULTIES:
        return False, "难度只能是 绿/黄/红/紫/白（或 bas/adv/exp/mas/re）。"
    value = parse_level(level)
    if not value:
        return False, f"等级要写成 13 或 13+，收到的是「{level}」。"
    constant: Optional[float] = None
    if ds not in (None, ""):
        try:
            constant = round(float(str(ds).replace("＋", "+")), 1)
        except (TypeError, ValueError):
            return False, f"定数要写成 14.9 这样的数字，收到的是「{ds}」。"
        if not (1 <= constant <= 15):
            return False, "定数必须在 1.0–15.0 之间。"
        expected = ds_label(constant)
        if expected != value:
            return False, f"定数 {constant:.1f} 对应的显示等级是 {expected}，和 {value} 不一致。"
    else:
        previous = (song.get("ds") or {}).get(typ, {}).get(difficulty)
        constant = float(previous) if previous is not None else None

    song.setdefault("difficulty", {}).setdefault(typ, {})[difficulty] = value
    song.setdefault("ds", {}).setdefault(typ, {})[difficulty] = constant
    song.setdefault("manual", {})["updated_at"] = _now()
    suffix = "" if constant is not None else "（未填定数，显示为 —）"
    return True, f"已写入 {describe(difficulty, typ)} Lv.{value}{suffix}"


ALIAS_SPLIT_RE = re.compile(r"[,，、;；/／|｜\n]+")
ALIAS_SPACE_RE = re.compile(r"\s+")
MAX_ALIASES = 20
ALIAS_LIMIT = 60


def parse_aliases(text: Any, blocked_titles: Iterable[str] = ()) -> List[str]:
    """把「干脆面, 魔法士 / 面」切成别名列表。

    先按显式分隔符（逗号/顿号/分号/斜杠）切；整串没有分隔符时才按空格切，
    但如果整串本身就是另一首歌的曲名（如「HOT LIMIT」）就原样保留，
    否则会被拆成两段、绕过曲名冲突检查。
    """
    raw = _clean(text, ALIAS_LIMIT * 2)
    if not raw:
        return []
    parts = [_clean(chunk, ALIAS_LIMIT) for chunk in ALIAS_SPLIT_RE.split(raw)]
    parts = [part for part in parts if part]
    if len(parts) > 1:
        return parts
    whole = parts[0] if parts else ""
    if not whole:
        return []
    if norm(whole) in {norm(item) for item in blocked_titles if norm(item)}:
        return [whole]
    spaced = [_clean(chunk, ALIAS_LIMIT) for chunk in ALIAS_SPACE_RE.split(whole)]
    return [part for part in spaced if part]


SCOPES: Tuple[str, ...] = ("standard", "dx")
SCOPE_LABEL = {"standard": "标准谱面", "dx": "DX 谱面"}


def alias_scopes(song: Dict[str, Any]) -> Dict[str, List[str]]:
    """读出一首歌的别名作用域，缺字段时给空表（兼容旧手动库文件）。"""
    raw = song.get("alias_scopes") or {}
    return {typ: [alias for alias in (raw.get(typ) or []) if isinstance(alias, str)]
            for typ in SCOPES}


def aliases_by_scope(song: Dict[str, Any]) -> Dict[str, List[str]]:
    """把别名分成 通用 / 标准 / DX 三组，用于展示。"""
    title_key = norm(song.get("title"))
    scopes = alias_scopes(song)
    scoped = {norm(alias) for values in scopes.values() for alias in values}
    shared = [alias for alias in song.get("aliases") or []
              if norm(alias) != title_key and norm(alias) not in scoped]
    return {"shared": shared, **{typ: list(scopes[typ]) for typ in SCOPES}}


def alias_record_scopes(record: Dict[str, Any]) -> Dict[str, List[str]]:
    """读官方曲目别名补丁里的类型作用域，缺字段时给空表。"""
    raw = record.get("scopes") or {}
    return {typ: [alias for alias in (raw.get(typ) or []) if isinstance(alias, str)]
            for typ in SCOPES}


def _unique_aliases(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for alias in values:
        key = norm(alias)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(alias)
    return out


def overlay_aliases(song: Dict[str, Any], record: Dict[str, Any]
                    ) -> Tuple[List[str], Dict[str, List[str]]]:
    """把一条官方别名补丁合并到歌曲别名上，返回 (别名并集, 类型作用域)。

    - ``added`` 是追加的别名；``removed`` 是从官方别名里隐藏的条目；
    - ``scopes`` 里的别名会从通用别名移到对应类型下展示；
    - 曲名本身永远保留，删不掉。
    """
    removed = {norm(alias) for alias in record.get("removed") or []}
    title = song.get("title", "")
    title_key = norm(title)
    # Store 合并过内存数据后 aliases 里已经包含补丁追加项；有原始别名快照时优先用它，
    # 否则「加完再删」会把已合并的别名当成官方自带别名，删不掉。
    base_source = song.get("_official_aliases") or song.get("aliases") or []
    base = [alias for alias in base_source
            if norm(alias) not in removed or norm(alias) == title_key]
    added = [alias for alias in record.get("added") or [] if norm(alias) not in removed]
    scopes = {typ: [alias for alias in values if norm(alias) not in removed]
              for typ, values in alias_record_scopes(record).items()}
    scoped = [alias for values in scopes.values() for alias in values]
    merged = _unique_aliases([title] + base + added + scoped) if title else \
        _unique_aliases(base + added + scoped)
    return merged, scopes


def merge_aliases(title: str, existing: Iterable[str], candidates: Iterable[str],
                  blocked_titles: Iterable[str] = (),
                  scopes: Optional[Dict[str, List[str]]] = None,
                  scope: Optional[str] = None
                  ) -> Tuple[bool, str, List[str], List[str]]:
    """校验并合并别名，返回 (是否成功, 错误文案, 最终别名列表, 本次新增的别名)。

    ``scope`` 为 ``standard`` / ``dx`` 时，新增的别名只归属于该谱面类型；
    为空表示通用别名（标准与 DX 都能查到）。
    """
    title_key = norm(title)
    blocked = {norm(item) for item in blocked_titles if norm(item)}
    kept: List[str] = [title]
    seen = {title_key}
    for alias in existing:
        key = norm(alias)
        if key and key not in seen:
            kept.append(alias)
            seen.add(key)

    added: List[str] = []
    for alias in candidates:
        key = norm(alias)
        if not key or key in seen:
            continue
        if key in blocked:
            return False, f"「{alias}」已经是另一首歌的曲名，拿它当别名会让查询串台。", [], []
        kept.append(alias)
        seen.add(key)
        added.append(alias)

    if len(kept) - 1 > MAX_ALIASES:
        return False, f"别名最多 {MAX_ALIASES} 个，这样会有 {len(kept) - 1} 个。", [], []
    if not added:
        return False, "这些别名都已经有了（或为空），没有新增。", kept, []
    if scopes is not None and scope in SCOPES:
        bucket = scopes.setdefault(scope, [])
        for alias in added:
            if norm(alias) not in {norm(item) for item in bucket}:
                bucket.append(alias)
    return True, "", kept, added


def song_key(song: Dict[str, Any]) -> str:
    """手动歌曲在谱面索引里的唯一键：没有官方 ID，用 标题+艺术家 归一化值。"""
    return f"manual:{norm(song.get('title'))}|{norm(song.get('artist'))}"


def chart_rows(songs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把手动歌曲展开成 level_index.json 风格的谱面行。"""
    rows: List[Dict[str, Any]] = []
    for song in songs:
        aliases = list(song.get("aliases") or [])
        for typ in ("standard", "dx"):
            levels = (song.get("difficulty") or {}).get(typ) or {}
            constants = (song.get("ds") or {}).get(typ) or {}
            song_id = song.get("std_id") if typ == "standard" else song.get("dx_id")
            for difficulty in DIFFICULTIES:
                value = levels.get(difficulty)
                if not value:
                    continue
                rows.append({
                    "id": song_id,
                    "song_key": song_key(song),
                    "title": song.get("title", ""),
                    "aliases": aliases,
                    "artist": song.get("artist", ""),
                    "category": song.get("category", ""),
                    "version": song.get("version", ""),
                    "type": typ,
                    "difficulty": difficulty,
                    "value": value,
                    "ds": constants.get(difficulty),
                    "ds_source": "manual",
                    "detail_source": "manual",
                    "charter": None,
                    "notes": None,
                    "chart_tags": list(((song.get("chart_tags") or {}).get(difficulty)) or []),
                    "manual": True,
                })
    return rows


_SPLIT_RE = re.compile(r"[\s|,，、/]+")


def split_fields(text: str) -> List[str]:
    """把「曲名 | 艺术家 | 分类」这类输入切成字段，空字段保留占位。"""
    return [field.strip() for field in str(text or "").split("|")]


def parse_chart_line(text: str) -> Tuple[str, str, str, Optional[float]]:
    """解析一行谱面：``[dx|标准] <难度> <等级> [定数]``。

    返回 (类型, 难度, 显示等级, 定数原始值)；无法解析时抛 ValueError（文案可直接回给用户）。
    """
    tokens = [token for token in _SPLIT_RE.split(str(text or "").replace("＝", " ").replace("=", " ").strip())
              if token]
    if not tokens:
        raise ValueError("没看懂，谱面要写成：难度 等级 定数，例如「紫 14+ 14.9」。")
    typ = parse_type(tokens[0])
    if typ:
        tokens.pop(0)
    if not tokens:
        raise ValueError("缺难度，例如「紫 14+ 14.9」。")
    difficulty = parse_difficulty(tokens.pop(0))
    if not difficulty:
        raise ValueError("难度只能是 绿/黄/红/紫/白（或 bas/adv/exp/mas/re）。")
    if not tokens:
        raise ValueError("缺等级，例如「紫 14+ 14.9」。")
    level = parse_level(tokens.pop(0))
    if not level:
        raise ValueError("等级要写成 13 或 13+。")
    ds = tokens.pop(0) if tokens else None
    return typ or "dx", difficulty, level, ds


def same_song(song: Dict[str, Any], title: str,
              artist: Optional[str] = None) -> bool:
    if norm(song.get("title")) != norm(title):
        return False
    if not artist:
        return True
    return norm(song.get("artist")) == norm(artist)


# ---------------------------------------------------------------- 手动库

class ManualStore:
    """手动库的读写与校验；自身不缓存，改完由 Store.reload() 重新合并。"""

    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.path = self.dir / MANUAL_FILE
        self.pending_path = self.dir / PENDING_FILE
        self.patch_path = self.dir / PATCH_FILE
        self.alias_path = self.dir / ALIAS_FILE

    # -------------------------------------------------- 读

    def songs(self) -> List[Dict[str, Any]]:
        return _read_list(self.path)

    def pending(self) -> List[Dict[str, Any]]:
        return _read_list(self.pending_path)

    def patches(self) -> List[Dict[str, Any]]:
        return _read_list(self.patch_path)

    def alias_records(self) -> List[Dict[str, Any]]:
        """官方曲目的别名补丁记录。"""
        return _read_list(self.alias_path)

    def find_alias_record(self, title: str, artist: Optional[str] = None
                          ) -> Optional[Dict[str, Any]]:
        for item in self.alias_records():
            if same_song(item, title, artist):
                return item
        return None

    def find(self, title: str, artist: Optional[str] = None) -> Optional[Dict[str, Any]]:
        for song in self.songs():
            if same_song(song, title, artist):
                return song
        return None

    # -------------------------------------------------- 写：歌曲 / 谱面

    def add_song(self, title: str, artist: str, category: str = "", version: str = "",
                 author: str = "", official_songs: Iterable[Dict[str, Any]] = (),
                 limit: int = MAX_ENTRIES,
                 aliases: Any = "",
                 alias_scope: Optional[str] = None
                 ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        title, artist = _clean(title, TITLE_LIMIT), _clean(artist, FIELD_LIMIT)
        if not title:
            return False, "曲名不能为空。", None
        if not artist:
            return False, "艺术家不能为空（写「未知」也可以）。", None

        songs = self.songs()
        for song in songs:
            if same_song(song, title, artist):
                return (False, f"手动库里已经有「{song['title']}」了，"
                               f"要补谱面用「舞萌 加谱面 {song['title']} 紫 14+ 14.9」。", None)
        for song in official_songs:
            if same_song(song, title, artist):
                return (False, f"官方快照里已有「{song.get('title')}」，直接发「舞萌 {song.get('title')}」"
                               f"就能查到，不需要手动录。", None)
        if len(songs) >= limit:
            return False, f"手动库已满（上限 {limit} 首），先删掉一些再录。", None

        # 没写别名是合法的；写了才需要校验
        merged = [title]
        scopes: Dict[str, List[str]] = {"standard": [], "dx": []}
        blocked = ([item.get("title", "") for item in songs]
                   + [item.get("title", "") for item in official_songs])
        candidates = parse_aliases(aliases, blocked)
        if candidates:
            ok, error, merged, _ = merge_aliases(title, [], candidates, blocked,
                                                 scopes, alias_scope)
            if not ok:
                return False, error, None
        song = make_song(title, artist, category, version, aliases=merged, author=author)
        song["alias_scopes"] = scopes
        songs.append(song)
        _write_list(self.path, songs)
        return True, (f"已建档「{song['title']}」（{song['artist']}｜{song['category']}｜"
                      f"{song['version']}），接着加谱面：难度 等级 定数"), song

    def save_song(self, song: Dict[str, Any]) -> None:
        """把改过的歌曲写回文件（按 title+artist 定位，找不到就追加）。"""
        songs = self.songs()
        for index, item in enumerate(songs):
            if same_song(item, song.get("title", ""), song.get("artist", "")):
                songs[index] = song
                break
        else:
            songs.append(song)
        _write_list(self.path, songs)

    def add_chart(self, title: str, difficulty: str, level: str,
                  ds: Optional[Any] = None, typ: str = "dx",
                  author: str = "") -> Tuple[bool, str]:
        parsed = parse_difficulty(difficulty)
        if not parsed:
            return False, "难度只能是 绿/黄/红/紫/白（或 bas/adv/exp/mas/re）。"
        song = self.find(title)
        if song is None:
            return False, (f"手动库里没有「{title}」。先发「舞萌 添加歌曲 {title} | 艺术家」建档。")
        ok, message = set_chart(song, parse_type(typ) or typ, parsed, level, ds)
        if not ok:
            return False, message
        song.setdefault("manual", {})["author"] = (
            _clean(author, FIELD_LIMIT) or song.get("manual", {}).get("author") or "未知")
        self.save_song(song)
        return True, f"「{song['title']}」{message}"

    # -------------------------------------------------- 写：官方曲目的谱面补丁

    def find_patch(self, title: str, typ: str = "dx", difficulty: str = "master",
                   artist: str = "") -> Optional[Dict[str, Any]]:
        """按 (曲名, 艺术家, 类型, 难度) 找一条谱面补丁。"""
        title_key, artist_key = norm(title), norm(artist)
        parsed = parse_difficulty(difficulty) or difficulty
        for item in self.patches():
            if norm(item.get("title")) != title_key:
                continue
            if artist_key and norm(item.get("artist")) != artist_key:
                continue
            if item.get("type") != (parse_type(typ) or typ):
                continue
            if item.get("difficulty") != parsed:
                continue
            return item
        return None

    def add_patch(self, title: str, artist: str, typ: str, difficulty: str,
                  level: str, ds: Optional[Any] = None,
                  author: str = "", charter: Optional[str] = None,
                  notes: Optional[Dict[str, Any]] = None,
                  chart_tags: Optional[Iterable[str]] = None
                  ) -> Tuple[bool, str]:
        """给官方快照里的歌追加或修正一张谱面，保存在 manual_charts.json。

        ``charter`` / ``notes`` / ``chart_tags`` 只在显式传入时覆盖；只改等级/定数
        时保留原谱面的谱师、音符数与标签（由 Store._apply_patch_row 负责）。
        """
        title, artist = _clean(title, TITLE_LIMIT), _clean(artist, FIELD_LIMIT)
        if not title:
            return False, "曲名不能为空。"
        typ = parse_type(typ) or (typ or "dx")
        if typ not in ("standard", "dx"):
            return False, "类型只能是 dx / 标准（可省略，默认 dx）。"
        parsed = parse_difficulty(difficulty)
        if not parsed:
            return False, "难度只能是 绿/黄/红/紫/白（或 bas/adv/exp/mas/re）。"
        if charter is not None:
            charter = _clean(charter, FIELD_LIMIT)
        if notes is not None:
            if not isinstance(notes, dict):
                return False, "音符数要写成 tap, hold, slide, touch, break 五个数字，或一个总数。"
            clean_notes: Dict[str, int] = {}
            for key, value in notes.items():
                try:
                    count = int(value)
                except (TypeError, ValueError):
                    return False, f"音符数「{key}={value}」不是整数。"
                if count < 0:
                    return False, "音符数不能是负数。"
                clean_notes[str(key)] = count
            notes = clean_notes
        if chart_tags is not None:
            chart_tags = [_clean(tag, FIELD_LIMIT) for tag in chart_tags
                          if _clean(tag, FIELD_LIMIT)][:10]
        # 借用 set_chart 的等级/定数自洽校验，校验通过再落盘
        probe: Dict[str, Any] = {"difficulty": {"standard": {}, "dx": {}},
                                 "ds": {"standard": {}, "dx": {}}}
        ok, message = set_chart(probe, typ, parsed, level, ds)
        if not ok:
            return False, message
        value = probe["difficulty"][typ][parsed]
        constant = probe["ds"][typ].get(parsed)
        patches = self.patches()
        now = _now()
        # 注意必须在同一个 patches 列表里找，不能再用 self.find_patch() 读一次盘：
        # 那是另一个 dict 对象，改完再写回旧列表等于没更新。
        existing = next((
            item for item in patches
            if norm(item.get("title")) == norm(title)
            and item.get("type") == typ
            and item.get("difficulty") == parsed
            and (not artist or norm(item.get("artist")) == norm(artist))
        ), None)
        extras = {key: val for key, val in (("charter", charter), ("notes", notes),
                                            ("chart_tags", chart_tags))
                  if val is not None}
        if existing is not None:
            existing.update({"title": title, "artist": artist, "level": value,
                             "ds": constant, "updated_at": now})
            existing.update(extras)
            existing["author"] = _clean(author, FIELD_LIMIT) or existing.get("author") or "未知"
            _write_list(self.patch_path, patches)
            return True, (f"已更新「{title}」{describe(parsed, typ)} 的手动修正："
                          f"Lv.{value}（定数 {f'{constant:.1f}' if constant is not None else '—'}）")
        patches.append({
            "title": title, "artist": artist, "type": typ, "difficulty": parsed,
            "level": value, "ds": constant, **extras,
            "author": _clean(author, FIELD_LIMIT) or "未知",
            "created_at": now, "updated_at": now,
        })
        _write_list(self.patch_path, patches)
        return True, (f"已给官方条目「{title}」补上 {describe(parsed, typ)}："
                      f"Lv.{value}（定数 {f'{constant:.1f}' if constant is not None else '—'}）。"
                      f"撤销用「舞萌 删除谱面 {title} | {typ} {parsed}」")

    def remove_patch(self, title: str, typ: str = "dx", difficulty: str = "master",
                     artist: str = "") -> Tuple[bool, str]:
        patches = self.patches()
        target = self.find_patch(title, typ, difficulty, artist)
        if target is None:
            return False, (f"官方条目「{title}」没有这张手动修正的谱面（官方谱面本身"
                           f"不能删，只能加补丁覆盖）。")
        target_key = (norm(target.get("title")), norm(target.get("artist")),
                      target.get("type"), target.get("difficulty"))
        kept = [item for item in patches
                if (norm(item.get("title")), norm(item.get("artist")),
                    item.get("type"), item.get("difficulty")) != target_key]
        _write_list(self.patch_path, kept)
        return True, (f"已撤销「{title}」"
                      f"{describe(target['difficulty'], target['type'])} 的手动修正，"
                      f"恢复官方数据。")

    # -------------------------------------------------- 写：官方曲目别名补丁

    def _save_alias_record(self, record: Dict[str, Any]) -> None:
        records = self.alias_records()
        records = [item for item in records
                   if not same_song(item, record.get("title", ""),
                                    record.get("artist", ""))]
        # 空记录不落盘：别留下一条什么都没改的补丁
        if record.get("added") or record.get("removed") or any(
                alias_record_scopes(record).values()):
            records.append(record)
        if records:
            _write_list(self.alias_path, records)
        else:
            try:
                self.alias_path.unlink()
            except FileNotFoundError:
                pass

    def add_official_aliases(self, song: Dict[str, Any], raw: Any,
                             scope: Optional[str] = None, author: str = "",
                             official_songs: Iterable[Dict[str, Any]] = (),
                             manual_songs: Iterable[Dict[str, Any]] = ()
                             ) -> Tuple[bool, str]:
        """给官方快照里的歌加别名，或把已有别名改成标准/DX 专属。"""
        title = str(song.get("title") or "").strip()
        artist = str(song.get("artist") or "").strip()
        if not title:
            return False, "曲名不能为空。"
        title_key = norm(title)
        blocked = {norm(item.get("title")) for item in
                   list(official_songs) + list(manual_songs)
                   if norm(item.get("title")) and norm(item.get("title")) != title_key}
        candidates = parse_aliases(raw, blocked)
        if not candidates:
            return False, "别名不能为空。"

        record = self.find_alias_record(title, artist) or {
            "title": title, "artist": artist,
            "added": [], "scopes": {"standard": [], "dx": []},
            "removed": [], "created_at": _now(),
        }
        record.setdefault("added", [])
        record.setdefault("removed", [])
        record["scopes"] = alias_record_scopes(record)
        effective, _ = overlay_aliases(song, record)
        effective_keys = {norm(alias) for alias in effective}
        removed_keys = {norm(alias) for alias in record.get("removed") or []}
        scopes = record["scopes"]

        added: List[str] = []
        changed: List[str] = []
        for alias in candidates:
            key = norm(alias)
            if not key:
                continue
            if key == title_key:
                return False, "曲名本身不能当别名。"
            if key in blocked:
                return False, f"「{alias}」已经是另一首歌的曲名，拿它当别名会让查询串台。"
            in_scope = [typ for typ in SCOPES
                        if key in {norm(item) for item in scopes.get(typ) or []}]
            if key in effective_keys:
                if scope in SCOPES:
                    if in_scope == [scope]:
                        continue
                    for typ in SCOPES:  # 换归属：先从旧作用域移走
                        scopes[typ] = [item for item in scopes[typ]
                                       if norm(item) != key]
                    scopes[scope].append(alias)
                    changed.append(alias)
                elif in_scope:      # 不带类型 = 改回通用别名
                    for typ in SCOPES:
                        scopes[typ] = [item for item in scopes[typ]
                                       if norm(item) != key]
                    changed.append(alias)
                continue
            # 新别名：如果之前在 removed 里被隐藏，这次加回来
            if key in removed_keys:
                record["removed"] = [item for item in record["removed"]
                                     if norm(item) != key]
                removed_keys.discard(key)
            record["added"].append(alias)
            effective_keys.add(key)
            if scope in SCOPES:
                for typ in SCOPES:
                    scopes[typ] = [item for item in scopes[typ]
                                   if norm(item) != key]
                scopes[scope].append(alias)
            added.append(alias)

        if not added and not changed:
            return False, "这些别名都已经有了（或为空），没有新增。"
        if len(record["added"]) > MAX_ALIASES:
            return False, f"手动追加的别名最多 {MAX_ALIASES} 个，先删掉一些再加。"

        record["scopes"] = scopes
        record["author"] = _clean(author, FIELD_LIMIT) or record.get("author") or "未知"
        record["updated_at"] = _now()
        self._save_alias_record(record)

        where = f"（{SCOPE_LABEL[scope]}专属）" if scope in SCOPES else ""
        final, _ = overlay_aliases(song, record)
        pieces = []
        if added:
            pieces.append(f"已加别名{where}：{'、'.join(added)}")
        if changed:
            target = f"{SCOPE_LABEL[scope]}专属" if scope in SCOPES else "通用别名"
            pieces.append(f"已把 {'、'.join(changed)} 改为{target}")
        return True, (f"「{title}」" + "；".join(pieces)
                      + f"（共 {len(final) - 1} 个）")

    def remove_official_aliases(self, song: Dict[str, Any], raw: Any,
                                scope: Optional[str] = None,
                                official_songs: Iterable[Dict[str, Any]] = (),
                                manual_songs: Iterable[Dict[str, Any]] = ()
                                ) -> Tuple[bool, str]:
        """删除官方曲目的别名（含官方自带别名，只在插件里隐藏）。"""
        title = str(song.get("title") or "").strip()
        artist = str(song.get("artist") or "").strip()
        title_key = norm(title)
        blocked = {norm(item.get("title")) for item in
                   list(official_songs) + list(manual_songs)
                   if norm(item.get("title")) and norm(item.get("title")) != title_key}
        targets = {norm(alias) for alias in parse_aliases(raw, blocked)}
        targets.discard(title_key)
        if not targets:
            return False, "曲名本身不能当别名删。"

        record = self.find_alias_record(title, artist) or {
            "title": title, "artist": artist,
            "added": [], "scopes": {"standard": [], "dx": []},
            "removed": [], "created_at": _now(),
        }
        record.setdefault("added", [])
        record.setdefault("removed", [])
        record["scopes"] = alias_record_scopes(record)
        effective, _ = overlay_aliases(song, record)
        existing = {norm(alias): alias for alias in effective}
        scopes = record["scopes"]

        scope_keys = {norm(alias) for alias in scopes.get(scope) or []} if scope in SCOPES else None
        removed: List[str] = []
        for key in targets:
            if key not in existing:
                continue
            if scope_keys is not None and key not in scope_keys:
                continue
            removed.append(existing[key])
        if not removed:
            if scope in SCOPES:
                return False, (f"「{title}」的{SCOPE_LABEL[scope]}别名里没有"
                               f"{'、'.join(parse_aliases(raw)) or '（空）'}。")
            return False, f"「{title}」没有这些别名。"

        removed_keys = {norm(alias) for alias in removed}
        record["added"] = [alias for alias in record["added"]
                           if norm(alias) not in removed_keys]
        for typ in SCOPES:
            scopes[typ] = [alias for alias in scopes[typ]
                           if norm(alias) not in removed_keys]
        # 只有官方自带的别名才需要 tombstone；用户自己加完又删的不留隐藏记录
        base_keys = {norm(alias) for alias in
                     (song.get("_official_aliases") or song.get("aliases") or [])}
        record["removed"] = _unique_aliases(
            [alias for alias in list(record["removed"]) + removed
             if norm(alias) in base_keys])
        record["scopes"] = scopes
        record["author"] = record.get("author") or "未知"
        record["updated_at"] = _now()
        self._save_alias_record(record)

        final, _ = overlay_aliases(song, record)
        where = f"（{SCOPE_LABEL[scope]}专属）" if scope in SCOPES else ""
        return True, (f"「{title}」已删除别名{where}：{'、'.join(removed)}"
                      f"（剩 {len(final) - 1} 个）")

    def add_aliases(self, title: str, raw: Any,
                    official_songs: Iterable[Dict[str, Any]] = (),
                    scope: Optional[str] = None) -> Tuple[bool, str]:
        song = self.find(title)
        if song is None:
            return False, (f"手动库里没有「{title}」。先发「舞萌 添加歌曲 {title} | 艺术家」建档。")
        blocked = ([item.get("title", "") for item in self.songs()
                    if not same_song(item, song.get("title", ""), song.get("artist", ""))]
                   + [item.get("title", "") for item in official_songs])
        scopes = alias_scopes(song)
        ok, error, merged, added = merge_aliases(
            song.get("title", ""), song.get("aliases") or [],
            parse_aliases(raw, blocked), blocked, scopes, scope)
        if not ok:
            return False, error
        song["aliases"] = merged
        song["alias_scopes"] = scopes
        song.setdefault("manual", {})["updated_at"] = _now()
        self.save_song(song)
        where = f"（{SCOPE_LABEL[scope]}专属）" if scope in SCOPES else ""
        return True, (f"「{song['title']}」已加别名{where}：{'、'.join(added)}"
                      f"（共 {len(merged) - 1} 个）")

    def remove_alias(self, title: str, raw: Any,
                     scope: Optional[str] = None) -> Tuple[bool, str]:
        song = self.find(title)
        if song is None:
            return False, f"手动库里没有「{title}」。"
        scopes = alias_scopes(song)
        title_key = norm(song.get("title"))
        targets = {norm(alias) for alias in parse_aliases(raw)}
        targets.discard(title_key)
        if not targets:
            return False, "曲名本身不能当别名删。"

        # 指定了类型就只在该作用域里找，避免误删另一类型的同名别名
        removed: List[str] = []
        for typ in (scope,) if scope in SCOPES else SCOPES:
            for alias in scopes.get(typ) or []:
                if norm(alias) in targets:
                    removed.append(alias)
        if scope in SCOPES and not removed:
            return False, (f"「{song['title']}」的{SCOPE_LABEL[scope]}别名里没有"
                           f"{'、'.join(parse_aliases(raw)) or '（空）'}。")
        # 通用别名（不属于任何类型作用域）
        removed_keys = {norm(alias) for alias in removed}
        for alias in song.get("aliases") or []:
            key = norm(alias)
            if key in targets and key not in removed_keys:
                removed.append(alias)
                removed_keys.add(key)
        if not removed:
            return False, f"「{song['title']}」没有这些别名。发「舞萌 {song['title']}」看看现有别名。"

        kept = [song.get("title", "")]
        for alias in song.get("aliases") or []:
            key = norm(alias)
            if key in removed_keys:
                continue
            if key and key not in {norm(item) for item in kept}:
                kept.append(alias)
        for typ in SCOPES:
            scopes[typ] = [alias for alias in scopes.get(typ) or []
                           if norm(alias) not in removed_keys]
        song["aliases"] = kept
        song["alias_scopes"] = scopes
        song.setdefault("manual", {})["updated_at"] = _now()
        self.save_song(song)
        return True, (f"「{song['title']}」已删除别名：{'、'.join(removed)}"
                      f"（剩 {len(kept) - 1} 个）")

    # -------------------------------------------------- 写：删除

    def remove_song(self, title: str) -> Tuple[bool, str]:
        songs = self.songs()
        kept = [song for song in songs if not same_song(song, title)]
        if len(kept) == len(songs):
            return False, f"手动库里没有「{title}」。发「舞萌 手动列表」看看有哪些。"
        _write_list(self.path, kept)
        return True, f"已删除手动条目「{title}」。"

    def remove_chart(self, title: str, difficulty: str, typ: str = "dx") -> Tuple[bool, str]:
        parsed, kind = parse_difficulty(difficulty), parse_type(typ) or typ
        if not parsed:
            return False, "难度只能是 绿/黄/红/紫/白（或 bas/adv/exp/mas/re）。"
        song = self.find(title)
        if song is None:
            return False, f"手动库里没有「{title}」。"
        if not (song.get("difficulty", {}).get(kind) or {}).get(parsed):
            return False, f"「{song['title']}」没有{describe(parsed, kind)}谱面。"
        song["difficulty"][kind].pop(parsed, None)
        song.get("ds", {}).get(kind, {}).pop(parsed, None)
        song.setdefault("manual", {})["updated_at"] = _now()
        if not any(song["difficulty"].get("standard", {}).values()) and \
                not any(song["difficulty"].get("dx", {}).values()):
            kept = [item for item in self.songs()
                    if not same_song(item, song.get("title", ""), song.get("artist", ""))]
            _write_list(self.path, kept)
            return True, f"「{song['title']}」已经没有谱面了，整条手动条目已删除。"
        self.save_song(song)
        return True, f"已删除「{song['title']}」{describe(parsed, kind)}谱面。"

    # -------------------------------------------------- 写：提交与审核

    def submit(self, title: str, artist: str, difficulty: str, level: str,
               ds: Optional[Any] = None, typ: str = "dx", author: str = "",
               official_songs: Iterable[Dict[str, Any]] = (),
               limit: int = MAX_ENTRIES) -> Tuple[bool, str]:
        parsed = parse_difficulty(difficulty)
        if not parsed:
            return False, "难度只能是 绿/黄/红/紫/白（或 bas/adv/exp/mas/re）。"
        title, artist = _clean(title, TITLE_LIMIT), _clean(artist, FIELD_LIMIT)
        if not title or not artist:
            return False, "提交格式：舞萌 提交 曲名 | 艺术家 | 难度 | 等级 [| 定数]"
        for song in self.songs():
            if same_song(song, title, artist):
                return False, f"「{title}」已经在手动库里了，可以直接查到。"
        for song in official_songs:
            if same_song(song, title, artist):
                return False, f"「{song.get('title')}」官方快照已有，不用提交。"
        queue = self.pending()
        for item in queue:
            candidate = item.get("song") or {}
            if same_song(candidate, title, artist) and \
                    (candidate.get("difficulty", {}).get(parse_type(typ) or typ) or {}).get(parsed):
                return False, "这条谱面已经在待审核队列里了，等管理员处理。"

        song = make_song(title, artist, author=author)
        ok, message = set_chart(song, parse_type(typ) or typ, parsed, level, ds)
        if not ok:
            return False, message
        queue.append({
            "id": max((int(item.get("id") or 0) for item in queue), default=0) + 1,
            "submitter": _clean(author, FIELD_LIMIT) or "未知",
            "submitted_at": _now(),
            "song": song,
        })
        if len(queue) > limit:
            return False, f"待审核队列已满（上限 {limit} 条），等管理员清理后再提交。"
        _write_list(self.pending_path, queue)
        return True, (f"已提交给管理员审核：{song['title']}（{song['artist']}）"
                      f"{describe(parsed, parse_type(typ) or typ)} Lv.{song['difficulty'][parse_type(typ) or typ][parsed]}"
                      f"。通过后就能查到了。")

    def approve(self, entry: str) -> Tuple[bool, str]:
        """按编号通过一条待审核；同曲已存在时把手头谱面并进去。"""
        queue = self.pending()
        key = str(entry).strip().lstrip("#").strip()
        target = next((item for item in queue if str(item.get("id")) == key), None)
        if target is None:
            return False, f"待审核队列里没有编号 {key}。发「舞萌 待审核」看看。"
        pending_song = target.get("song") or {}
        songs = self.songs()
        existing = next((song for song in songs
                         if same_song(song, pending_song.get("title", ""),
                                      pending_song.get("artist", ""))), None)
        if existing is None:
            pending_song.setdefault("manual", {})["author"] = target.get("submitter") or "未知"
            songs.append(pending_song)
        else:
            for typ in ("standard", "dx"):
                for difficulty, level in (pending_song.get("difficulty", {}).get(typ) or {}).items():
                    existing.setdefault("difficulty", {}).setdefault(typ, {})[difficulty] = level
                    existing.setdefault("ds", {}).setdefault(typ, {})[difficulty] = \
                        (pending_song.get("ds", {}).get(typ) or {}).get(difficulty)
            existing.setdefault("manual", {})["updated_at"] = _now()
            pending_song = existing
        _write_list(self.path, songs)
        _write_list(self.pending_path, [item for item in queue if item is not target])
        labels = [f"{TYPE_LABEL[typ]} {DIFF_LABEL[difficulty]} {level}"
                  for typ in ("standard", "dx")
                  for difficulty, level in ((pending_song.get("difficulty") or {}).get(typ) or {}).items()]
        return True, (f"已通过「{pending_song.get('title')}」"
                      + (f"：{'、'.join(labels)}" if labels else "（无谱面）"))

    def reject(self, entry: str) -> Tuple[bool, str]:
        queue = self.pending()
        key = str(entry).strip().lstrip("#").strip()
        target = next((item for item in queue if str(item.get("id")) == key), None)
        if target is None:
            return False, f"待审核队列里没有编号 {key}。发「舞萌 待审核」看看。"
        _write_list(self.pending_path, [item for item in queue if item is not target])
        title = (target.get("song") or {}).get("title", "")
        return True, f"已驳回「{title}」（提交人 {target.get('submitter')}）。"


# ---------------------------------------------------------------- 渲染辅助

def render_manual_list(songs: Sequence[Dict[str, Any]],
                       patches: Sequence[Dict[str, Any]] = (),
                       alias_records: Sequence[Dict[str, Any]] = ()) -> str:
    if not songs and not patches and not alias_records:
        return ("📝 手动库里还没有条目。\n"
                "添加：舞萌 添加歌曲 曲名 | 艺术家 [| 分类] [| 版本]\n"
                "　　　然后按提示发「紫 14+ 14.9」这样的谱面行。\n"
                "官方曲目补谱面：舞萌 加谱面 <曲名> | 紫 | 14+ | 14.9")
    lines = [f"📝 手动录入的歌曲（{len(songs)} 首）"] if songs else []
    for song in songs:
        charts = []
        for typ in ("standard", "dx"):
            for difficulty in DIFFICULTIES:
                level = (song.get("difficulty") or {}).get(typ, {}).get(difficulty)
                if level:
                    charts.append(f"{TYPE_LABEL[typ]} {DIFF_LABEL[difficulty]} {level}")
        author = (song.get("manual") or {}).get("author") or "未知"
        aliases = [alias for alias in song.get("aliases") or [] if norm(alias) != norm(song.get("title"))]
        alias_text = f"｜别名 {len(aliases)} 个" if aliases else ""
        lines.append(f"· {song.get('title')}（{song.get('artist')}）"
                     f"{'｜' + ' '.join(charts) if charts else '｜无谱面'}{alias_text}｜by {author}")
    if patches:
        lines.append(f"📌 官方曲目的谱面补丁（{len(patches)} 条）")
        for patch in patches:
            typ, difficulty = patch.get("type", "dx"), patch.get("difficulty", "master")
            parsed = parse_difficulty(difficulty) or difficulty
            constant = patch.get("ds")
            lines.append(f"· {patch.get('title')}（{patch.get('artist') or '未知艺术家'}）"
                         f"｜{describe(parsed, typ)} Lv.{patch.get('level')}"
                         f"（定数 {ds_label(constant) if constant is not None else '—'}）"
                         f"｜by {patch.get('author') or '未知'}")
    if alias_records:
        lines.append(f"📌 官方曲目的别名修正（{len(alias_records)} 首）")
        for record in alias_records:
            scopes = alias_record_scopes(record)
            parts = []
            if record.get("added"):
                parts.append(f"追加 {'、'.join(record['added'][:5])}"
                             + (f" 等 {len(record['added'])} 个" if len(record["added"]) > 5 else ""))
            if scopes["standard"]:
                parts.append(f"标准专属 {'、'.join(scopes['standard'][:4])}")
            if scopes["dx"]:
                parts.append(f"DX 专属 {'、'.join(scopes['dx'][:4])}")
            if record.get("removed"):
                parts.append(f"隐藏 {'、'.join(record['removed'][:4])}")
            lines.append(f"· {record.get('title')}"
                         f"（{record.get('artist') or '未知艺术家'}）"
                         f"｜{'；'.join(parts) or '无变化'}"
                         f"｜by {record.get('author') or '未知'}")
    lines.append("删除：舞萌 删除歌曲 <曲名>　补充：舞萌 加谱面 <曲名> 紫 14+ 14.9")
    lines.append("改别名：舞萌 加别名 <曲名> | 别名 | dx/标准　删除别名：舞萌 删除别名 <曲名> | 别名")
    return "\n".join(lines)


def render_pending(queue: Sequence[Dict[str, Any]]) -> str:
    if not queue:
        return "📭 待审核队列是空的。"
    lines = [f"📬 待审核（{len(queue)} 条）"]
    for item in queue:
        song = item.get("song") or {}
        charts = []
        for typ in ("standard", "dx"):
            for difficulty, level in (song.get("difficulty", {}).get(typ) or {}).items():
                charts.append(f"{TYPE_LABEL[typ]} {DIFF_LABEL[difficulty]} {level}")
        lines.append(f"#{item.get('id')} {song.get('title')}（{song.get('artist')}）"
                     f" {' '.join(charts)}｜by {item.get('submitter')} {item.get('submitted_at')}")
    lines.append("通过：舞萌 通过 <编号>　驳回：舞萌 驳回 <编号>")
    return "\n".join(lines)
