# -*- coding: utf-8 -*-
"""把查询结果渲染成适合 QQ 的短文本。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .manual import aliases_by_scope
from .store import DIFF_LABEL, TYPE_LABEL, fmt_ds, norm

RULE = "─" * 14
SOURCE_LABEL = {"onecat": "OneCat 官方", "divingfish": "水鱼"}
PLACEHOLDERS = {None, "", "-", "—"}


def _alias_lines(song: Dict[str, Any], limit: int = 10) -> List[str]:
    """别名按作用域分行：通用 / 标准谱面专属 / DX 谱面专属。"""
    groups = aliases_by_scope(song)
    # 手动追加的别名排前面，否则官方曲目别名很多时会被截断、看不到自己加的
    added_keys = {norm(alias) for alias in
                  (song.get("alias_patch") or {}).get("added") or []}
    groups["shared"].sort(key=lambda alias: 0 if norm(alias) in added_keys else 1)

    def render(prefix: str, values: List[str]) -> str:
        values = [alias for alias in values if "(共" not in alias]
        if not values:
            return ""
        shown = "、".join(values[:limit])
        if len(values) > limit:
            shown += f" 等 {len(values)} 个"
        return f"{prefix}｜{shown}"

    return [line for line in (
        render("别名", groups["shared"]),
        render("别名（标准谱面）", groups["standard"]),
        render("别名（DX 谱面）", groups["dx"]),
    ) if line]


def _tags(chart: Dict[str, Any], limit: int = 3) -> str:
    tags = [tag for tag in chart.get("chart_tags") or [] if tag]
    if not tags:
        return ""
    shown = " ".join(tags[:limit])
    if len(tags) > limit:
        shown += " …"
    return f"｜{shown}"


def render_song(song: Dict[str, Any], charts: List[Dict[str, Any]],
                config: Optional[Dict[str, Any]] = None) -> str:
    config = config or {}
    manual = (song.get("manual") or {})
    lines = [f"🎵 {song['title']}",
             f"艺术家｜{song['artist']}",
             f"分类｜{song['category']}　版本｜{song['version']}"]
    if manual:
        lines.insert(0, "📝 手动录入")

    for typ in ("standard", "dx"):
        group = [chart for chart in charts if chart["type"] == typ]
        if not group:
            continue
        lines.append(RULE)
        song_id = group[0].get("song_id")
        # 「DX 谱面」要空格、「标准谱面」不要，直接按类型取词
        type_word = "标准谱面" if typ == "standard" else "DX 谱面"
        lines.append(f"{type_word}（{'手动' if song_id is None else '#' + str(song_id)}）")
        for chart in group:
            line = (f"  {DIFF_LABEL[chart['difficulty']]:<9} Lv.{chart['level']:<3} "
                    f"定数 {fmt_ds(chart['ds'])}")
            if config.get("show_charter", True) and chart.get("charter") not in PLACEHOLDERS:
                line += f"｜谱师 {chart['charter']}"
            if config.get("show_tags", True):
                line += _tags(chart)
            if config.get("show_notes", False) and chart.get("notes"):
                total = sum(int(value or 0) for value in chart["notes"].values())
                line += f"｜{total} 音符"
            if chart.get("patched"):
                line += "　📝 手动修正"
            lines.append(line)

    alias_lines = _alias_lines(song, int(config.get("alias_limit", 10)))
    if alias_lines:
        lines.append(RULE)
        lines.extend(alias_lines)
    alias_patch = song.get("alias_patch") or {}
    if alias_patch:
        scoped = [alias for values in (song.get("alias_scopes") or {}).values()
                  for alias in values or []]
        changes = len(set(list(alias_patch.get("added") or [])
                          + list(alias_patch.get("removed") or []) + scoped))
        author = alias_patch.get("author") or "未知"
        updated = str(alias_patch.get("updated_at") or "")[:10]
        lines.append(f"📝 别名修正 {changes} 条｜by {author}"
                     + (f" · 更新 {updated}" if updated else ""))
        lines.append("改归属：舞萌 加别名 曲名 | 别名 [| dx/标准]　删除：舞萌 删除别名 曲名 | 别名")
    if manual:
        author = manual.get("author") or "未知"
        updated = str(manual.get("updated_at") or "")[:10]
        lines.append(f"📝 手动录入｜by {author}" + (f" · 更新 {updated}" if updated else ""))
        lines.append("补谱面：舞萌 加谱面 曲名 | 紫 | 14+ | 14.9　删除：舞萌 删除歌曲 曲名")
    else:
        patches = [patch for patch in (song.get("patch") or {}).values() if patch]
        if patches:
            author = patches[0].get("author") or "未知"
            updated = str(patches[0].get("updated_at") or "")[:10]
            lines.append(RULE)
            lines.append(f"📝 手动修正 {len(patches)} 张谱面｜by {author}"
                         + (f" · 更新 {updated}" if updated else ""))
            lines.append("撤销：舞萌 删除谱面 曲名 | 类型 难度（如 dx 白）")
    return "\n".join(lines)


def render_candidates(results: List[Any], query: str, limit: int = 8) -> str:
    lines = [f"🔍 没有精确匹配「{query}」，可能是这些："]
    for _, song in results[:limit]:
        lines.append(f"· {song['title']}（{song['artist']}）")
    lines.append("直接发送「舞萌 <曲名>」查看谱面。")
    return "\n".join(lines)


def render_level(level: str, rows: List[Dict[str, Any]], limit: int = 15,
                 typ: Optional[str] = None, difficulty: Optional[str] = None) -> str:
    parts = []
    if typ:
        parts.append(TYPE_LABEL[typ])
    if difficulty:
        parts.append(DIFF_LABEL[difficulty])
    suffix = f"（{' '.join(parts)}）" if parts else ""
    if not rows:
        return f"没有找到 Lv.{level}{suffix} 的谱面，试试去掉筛选条件。"

    counts = {"standard": 0, "dx": 0}
    for row in rows:
        counts[row["type"]] += 1
    split = "" if typ else f"（标准 {counts['standard']} / DX {counts['dx']}）"
    lines = [f"📈 Lv.{level}{suffix} 共 {len(rows)} 张{split}"]
    for index, row in enumerate(rows[:limit], 1):
        mark = " 📝" if row.get("patch") else ""
        lines.append(f"{index:>2}. {row['title']} · {TYPE_LABEL[row['type']]} "
                     f"{DIFF_LABEL[row['difficulty']]} · {fmt_ds(row['ds'])}{mark}")
    if len(rows) > limit:
        hints = []
        if typ is None:
            hints.append("dx / 标准")
        if difficulty is None:
            hints.append("master / 紫")
        if hints:
            lines.append(f"… 还有 {len(rows) - limit} 张，可加「{' 或 '.join(hints)}」缩小范围")
        else:
            lines.append(f"… 还有 {len(rows) - limit} 张")
    return "\n".join(lines)


def render_ds_range(low: float, high: float, rows: List[Dict[str, Any]],
                    typ: Optional[str] = None,
                    difficulty: Optional[str] = None) -> str:
    parts = []
    if typ:
        parts.append(TYPE_LABEL[typ])
    if difficulty:
        parts.append(DIFF_LABEL[difficulty])
    suffix = f"（{' '.join(parts)}）" if parts else ""
    if not rows:
        return f"没有定数在 {low:.1f}–{high:.1f} 的谱面{suffix}。"
    lines = [f"🎯 定数 {low:.1f}–{high:.1f}{suffix}（按定数降序，最多 {len(rows)} 条）"]
    for row in rows:
        mark = " 📝" if row.get("patch") else ""
        lines.append(f"· {row['title']} · {TYPE_LABEL[row['type']]} "
                     f"{DIFF_LABEL[row['difficulty']]} · Lv.{row['value']} {fmt_ds(row['ds'])}{mark}")
    return "\n".join(lines)


def render_stats(meta: Dict[str, Any], song_count: int, chart_count: int) -> str:
    lines = ["📚 舞萌DX知识库"]
    if meta.get("version"):
        lines.append(f"快照｜国服 {meta['version']}（源更新 {meta.get('source_updated') or '未知'}，"
                     f"本地更新 {meta.get('updated_at') or '未知'}）")
    lines.append(f"收录｜{song_count} 首歌曲 / {chart_count} 张常规谱面")
    if meta.get("manual_songs"):
        lines.append(f"手动｜{meta['manual_songs']} 首歌曲 / {meta.get('manual_charts', 0)} 张谱面"
                     f"（聊天里录入，不随版本更新丢失）")
    lines.append(f"定数｜{meta.get('charts_with_ds', chart_count)} 张谱面带精确定数")
    sources = meta.get("ds_sources") or {}
    if sources:
        detail = "、".join(f"{SOURCE_LABEL.get(name, name)} {count}"
                          for name, count in sorted(sources.items(), key=lambda item: -item[1]))
        lines.append(f"来源｜{detail}")
    lines.append("数据源：国服曲库（范围/版本）+ OneCat 官方谱面站（定数）+ 水鱼（谱师/音符）")
    return "\n".join(lines)


def render_help(levels: Optional[List[str]] = None) -> str:
    lines = [
        "🎵 舞萌DX知识库",
        "舞萌 <曲名>　　　　　　 谱面、定数、别名",
        "舞萌 定数 <曲名> [难度]　只看定数（难度：绿/黄/红/紫/白，或 bas/adv/exp/mas/re）",
        "舞萌 13+ [dx] [master]　按显示等级查谱面",
        "舞萌 定数 13.5-13.9　　 按定数区间筛选",
        "舞萌 统计　　　　　　　 数据快照信息",
        "——— 手动录入（管理员）———",
        "舞萌 添加歌曲 曲名 | 艺术家 [| 分类] [| 版本] [| 别名] [| dx/标准]　建档（缺字段会追问）",
        "舞萌 加谱面 曲名 | 紫 | 14+ | 14.9　 补谱面（官方曲目也能补；前面加 dx/标准 指定类型）",
        "舞萌 改谱面信息 曲名 | dx 紫 | 谱师=某人 | 标签=a,b | 音符=1234　改谱师/标签/音符数",
        "舞萌 加别名 曲名 | 别名1, 别名2 [| dx 或 标准]　加别名（官方曲目也支持；末段=只在那种谱面生效）",
        "舞萌 删除别名 曲名 | 别名1 [| dx 或 标准]　　　 删别名（官方自带别名也能隐藏）",
        "舞萌 删除歌曲 曲名 / 舞萌 删除谱面 曲名 | 紫",
        "舞萌 手动列表　　　　　 看手动库",
        "舞萌 帮助　　　　　　　 本说明",
        "——— 普通用户 ———",
        "舞萌 提交 曲名 | 艺术家 | 紫 | 14+ | 14.9　提交给管理员审核",
    ]
    if levels:
        lines.append(f"可用等级：{' '.join(levels)}")
    return "\n".join(lines)
