# -*- coding: utf-8 -*-
"""意图解析与结果组装：不依赖 AstrBot，便于单独测试。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .render import (render_candidates, render_ds_range, render_help, render_level,
                     render_song, render_stats)
from .store import DIFF_LABEL, Store, fmt_ds, parse_difficulty, parse_level, parse_type

RANGE_RE = re.compile(r"^(\d{1,2}(?:\.\d)?)\s*[-~～至]\s*(\d{1,2}(?:\.\d)?)$")

SUBCOMMANDS = {
    "查询": "song", "查": "song", "查歌": "song", "搜": "song", "搜索": "song",
    "song": "song", "info": "song", "详情": "song", "谱面": "song",
    "定数": "ds", "ds": "ds", "常数": "ds", "拟合": "ds",
    "等级": "level", "level": "level", "lv": "level", "标级": "level",
    "统计": "stats", "stats": "stats", "状态": "stats", "快照": "stats",
    "帮助": "help", "help": "help", "说明": "help", "?": "help", "？": "help",
}

DEFAULTS = {
    "max_list": 15,
    "alias_limit": 10,
    "show_charter": True,
    "show_tags": True,
    "show_notes": False,
}


def _cfg(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(DEFAULTS)
    if config:
        merged.update({key: value for key, value in config.items() if value is not None})
    return merged


def _peel_filters(text: str) -> Tuple[str, Optional[str], Optional[str]]:
    """从尾部剥离类型/难度词，如「Oshama Scramble! dx master」。"""
    tokens = text.split()
    typ = difficulty = None
    while len(tokens) > 1:
        last = tokens[-1]
        candidate = parse_type(last)
        if candidate and not typ:
            typ = candidate
            tokens.pop()
            continue
        candidate = parse_difficulty(last)
        if candidate and not difficulty:
            difficulty = candidate
            tokens.pop()
            continue
        break
    return " ".join(tokens).strip(), typ, difficulty


def answer(text: str, store: Store, config: Optional[Dict[str, Any]] = None) -> str:
    """把一条命令文本解析成要回复的内容。"""
    config = _cfg(config)
    limit = max(1, int(config.get("max_list", 15)))
    command = (text or "").replace("\u3000", " ").strip()
    if not command:
        return render_help(store.levels())

    head, _, rest = command.partition(" ")
    mode = SUBCOMMANDS.get(head.lower(), "auto")
    payload = rest.strip() if mode != "auto" else command

    if mode == "help":
        return render_help(store.levels())
    if mode == "stats":
        return render_stats(store.snapshot(), store.song_count, store.chart_count)

    # 尾部类型/难度词（dx、标准、master、紫…）在所有分支之前统一剥一次，
    # 否则「定数 13.5-13.9 dx」这种「区间 + 筛选」会静默匹配失败。
    original = payload.strip()
    payload, typ, difficulty = _peel_filters(payload)

    # 显示等级 / 定数区间：任何模式下都优先识别
    first = payload.split()[0] if payload.split() else ""
    level = parse_level(first) if first else None
    if level and mode in ("auto", "level", "ds"):
        return render_level(level, store.level_rows(level, typ, difficulty),
                            limit, typ, difficulty)

    if mode == "level":
        return f"「等级」后面要跟具体等级，例如：舞萌 13+ / 舞萌 14 dx master"

    match = RANGE_RE.match(payload.replace(" ", "")) if payload else None
    if match and mode in ("auto", "ds"):
        low, high = sorted((float(match.group(1)), float(match.group(2))))
        return render_ds_range(low, high,
                               store.ds_range(low, high, typ, difficulty, limit=limit),
                               typ, difficulty)

    # 曲名查询：先按剥过筛选词的串找，找不到就把原串当曲名再试一次
    query = payload
    results = store.find(query) if query else []
    if not results and original and original != query:
        query, typ, difficulty = original, None, None
        results = store.find(query)
    if not results:
        return f"没有找到「{query}」对应的歌曲。发送「舞萌 帮助」查看用法。"

    song = results[0][1]
    scoped_type = (store.alias_scope(song, query)
                   if typ is None and difficulty is None else None)
    if scoped_type:
        typ = scoped_type
    charts = store.charts_of(song)
    if typ or difficulty:
        filtered = [chart for chart in charts
                    if (typ is None or chart["type"] == typ)
                    and (difficulty is None or chart["difficulty"] == difficulty)]
        if not filtered:
            labels = " ".join(part for part in (
                "DX" if typ == "dx" else "标准" if typ else "",
                DIFF_LABEL[difficulty] if difficulty else "") if part)
            return (f"「{song['title']}」没有{labels}谱面。"
                    f"发送「舞萌 {song['title']}」查看全部难度。")
        charts = filtered

    if mode == "ds":
        lines = [f"🎯 {song['title']}"]
        for chart in charts:
            lines.append(f"{chart['type_label']} {DIFF_LABEL[chart['difficulty']]}"
                         f" · Lv.{chart['level']} · 定数 {fmt_ds(chart['ds'])}")
        if scoped_type:
            lines.append(_scope_hint(query, scoped_type))
        return "\n".join(lines)

    if len(results) > 1 and results[0][0] == results[1][0] == 100:
        # 同名不同曲（如两首 Link）时都列出来
        return "\n\n".join(render_song(item[1], store.charts_of(item[1]), config)
                           for item in results[:2])
    if results[0][0] <= 60:
        return render_candidates(results, query)
    text = render_song(song, charts, config)
    if scoped_type:
        text += "\n" + _scope_hint(query, scoped_type)
    return text


def _scope_hint(query: str, typ: str) -> str:
    label = "标准谱面" if typ == "standard" else "DX 谱面"
    other = "dx" if typ == "standard" else "标准"
    sep = "" if typ == "standard" else " "
    return (f"ℹ️「{query}」是{sep}{label}专属别名，只显示了{sep}{label}；"
            f"看另一类型就发「舞萌 {query} {other}」。")


def injection_text(store: Store, songs: List[Dict[str, Any]]) -> str:
    """给 LLM 注入的谱面资料，口径与指令查询一致。"""
    if not songs:
        return ""
    meta = store.snapshot()
    head = "【舞萌DX知识库资料】"
    if meta.get("version"):
        head += f"（国服 {meta['version']}，定数来自 OneCat 官方谱面站）"
    lines = [head]
    for song in songs:
        groups = []
        for typ in ("standard", "dx"):
            charts = [chart for chart in store.charts_of(song) if chart["type"] == typ]
            if not charts:
                continue
            body = " ".join(
                f"{DIFF_LABEL[chart['difficulty']][0]}{fmt_ds(chart['ds'])}"
                f"(Lv.{chart['level']})" for chart in charts)
            groups.append(f"{'标准' if typ == 'standard' else 'DX'} {body}")
        lines.append(f"- {song['title']}（{song['artist']}｜{song['version']}）：" + "；".join(groups))
    lines.append("以上为知识库实测数据。资料不足时调用 maimai_lookup 工具查询，"
                 "不要凭记忆编造等级或定数。")
    return "\n".join(lines)
