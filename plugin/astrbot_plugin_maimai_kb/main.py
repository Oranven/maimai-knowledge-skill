# -*- coding: utf-8 -*-
"""舞萌DX知识库插件入口：指令 + 手动录入 + LLM 工具 + 对话内注入。"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

from .core.answer import answer, injection_text
from .core.manual import (describe, parse_chart_line, render_manual_list,
                         render_pending, split_fields)
from .core.store import Store
from .core.text import norm, parse_difficulty, parse_type

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_NAME = "astrbot_plugin_maimai_kb"
COMMAND_WORDS = {"舞萌", "maimai", "mai", "查歌"}
PREFIX_RE = re.compile(r"^[/!！。.]")

# 手动录入相关的子词 → 处理分支（都跟在「舞萌」后面）
MANUAL_WORDS = {
    "添加歌曲": "add", "录歌": "add", "加歌": "add", "新增歌曲": "add",
    "加谱面": "chart", "添加谱面": "chart", "改谱面": "chart",
    "改谱面信息": "chart_info", "谱面信息": "chart_info", "改属性": "chart_info",
    "加别名": "alias_add", "添加别名": "alias_add", "别名+": "alias_add",
    "删除别名": "alias_remove", "删别名": "alias_remove",
    "删除歌曲": "del_song", "删歌": "del_song",
    "删除谱面": "del_chart", "删谱面": "del_chart",
    "手动列表": "list", "手动库": "list", "手动歌曲": "list",
    "提交": "submit",
    "待审核": "pending", "审核队列": "pending",
    "通过": "approve", "驳回": "reject",
    "取消": "cancel",
}
CANCEL_WORDS = {"取消", "退出", "算了", "不录了", "cancel"}
DONE_WORDS = {"完成", "结束", "好了", "没了", "done", "ok", "保存"}


def _all_message_types():
    """跨版本兼容：新版有 EventMessageType.ALL，老版本用组成项自己拼。"""
    types = getattr(filter, "EventMessageType", None)
    if types is None:
        return None
    if hasattr(types, "ALL"):
        return types.ALL
    try:
        return types.GROUP_MESSAGE | types.PRIVATE_MESSAGE
    except (AttributeError, TypeError):
        return getattr(types, "GROUP_MESSAGE", None)


ALL_MESSAGES = _all_message_types()


def _plugin_data_dir() -> str:
    """手动库目录：优先 AstrBot 的持久插件数据目录（覆盖安装不丢），否则插件 data/。"""
    try:
        from astrbot.api.star import StarTools

        getter = getattr(StarTools, "get_data_dir", None)
        if getter is not None:
            return str(getter(PLUGIN_NAME))
    except Exception as exc:  # 老版本没有 StarTools.get_data_dir
        logger.debug("[maimai_kb] 无法使用 AstrBot 插件数据目录，退回 data/: %s", exc)
    return os.path.join(PLUGIN_DIR, "data")


class Main(Star):
    """舞萌DX歌曲知识库：显示等级、精确定数、别名与谱面属性，离线确定性查询。"""

    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config: Dict[str, Any] = dict(config or {})
        manual_dir = str(self.config.get("manual_dir") or "").strip() or _plugin_data_dir()
        self.store = Store(os.path.join(PLUGIN_DIR, "data"), manual_dir)
        self.sessions: Dict[str, Dict[str, Any]] = {}
        logger.info("[maimai_kb] 已加载 %s 首歌曲 / %s 张谱面（快照 %s，手动 %s 首）",
                    self.store.song_count, self.store.chart_count,
                    self.store.snapshot().get("version", "未知"),
                    self.store.manual_song_count)

    # ------------------------------------------------------------ 工具方法

    @staticmethod
    def _payload(event: AstrMessageEvent) -> str:
        # 全角空格在 QQ 输入法里很常见，统一成半角再切参数
        text = PREFIX_RE.sub("", (event.message_str or "").replace("\u3000", " ").strip())
        head, _, rest = text.partition(" ")
        if head.strip().lower() in COMMAND_WORDS:
            return rest.strip()
        return text

    def _reply(self, text: str) -> str:
        # 单条消息过长时截断，避免被平台丢弃
        limit = int(self.config.get("max_message_chars", 3000))
        return text if len(text) <= limit else text[:limit - 20] + "\n…（内容过长已截断）"

    # ------------------------------------------------------------ 手动录入：配置与权限

    def _manual_enabled(self) -> bool:
        return bool(self.config.get("manual_enabled", True))

    def _manual_limit(self) -> int:
        try:
            return max(1, int(self.config.get("manual_max", 200)))
        except (TypeError, ValueError):
            return 200

    def _session_ttl(self) -> int:
        try:
            return max(30, int(self.config.get("manual_session_ttl", 300)))
        except (TypeError, ValueError):
            return 300

    @staticmethod
    def _sender_id(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_sender_id() or "")
        except Exception:
            return ""

    @staticmethod
    def _sender_name(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_sender_name() or "")
        except Exception:
            return ""

    def _admin_ids(self) -> set:
        raw = str(self.config.get("admin_qq", "") or "")
        return {part.strip() for part in re.split(r"[,，、\s]+", raw) if part.strip()}

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """白名单 QQ 或平台判定为管理员（AstrBot 的 event.is_admin()）都能写。"""
        if self.config.get("allow_all_edit"):
            return True
        sender = self._sender_id(event)
        if sender and sender in self._admin_ids():
            return True
        try:
            return bool(event.is_admin())
        except Exception:
            return False

    def _no_permission(self) -> str:
        if not self.config.get("user_submit", True):
            return "手动录入只允许管理员操作。"
        return ("添加/修改只允许管理员操作。\n"
                "普通用户可以这样提交，管理员审核通过后就能查到：\n"
                "舞萌 提交 曲名 | 艺术家 | 紫 | 14+ | 14.9")

    # ------------------------------------------------------------ 手动录入：会话状态

    def _session_key(self, event: AstrMessageEvent) -> str:
        origin = getattr(event, "unified_msg_origin", "") or ""
        return f"{origin}|{self._sender_id(event) or self._sender_name(event)}"

    def _live_session(self, event: AstrMessageEvent) -> Optional[Dict[str, Any]]:
        key = self._session_key(event)
        session = self.sessions.get(key)
        if not session:
            return None
        if time.time() - float(session.get("ts") or 0) > self._session_ttl():
            self.sessions.pop(key, None)
            return None
        return session

    def _start_session(self, event: AstrMessageEvent, step: str,
                       title: str = "", artist: str = "") -> None:
        self.sessions[self._session_key(event)] = {
            "step": step, "title": title, "artist": artist, "ts": time.time()}

    def _drop_session(self, event: AstrMessageEvent) -> None:
        self.sessions.pop(self._session_key(event), None)

    # ------------------------------------------------------------ 手动录入：命令实现

    def _create_song(self, event: AstrMessageEvent,
                     fields: List[str]) -> Tuple[bool, str, str, str]:
        fields = list(fields) + [""] * (6 - len(fields))
        title, artist = fields[0], fields[1]
        category, version, aliases = fields[2], fields[3], fields[4]
        alias_scope = parse_type(fields[5]) if fields[5].strip() else None
        if fields[5].strip() and not alias_scope:
            return False, f"别名归属只认「dx」或「标准」，没看懂「{fields[5]}」。", "", ""
        if alias_scope and not aliases.strip():
            return False, "写了别名归属（dx/标准）但没写别名。", "", ""
        ok, message, _ = self.store.manual.add_song(
            title, artist, category, version, author=self._sender_name(event),
            official_songs=self.store.official_songs, limit=self._manual_limit(),
            aliases=aliases, alias_scope=alias_scope)
        if ok:
            self.store.reload()
        return ok, message, title.strip(), artist.strip()

    def _cmd_add(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._manual_enabled():
            return "手动录入功能已在配置里关闭（manual_enabled）。"
        if not self._is_admin(event):
            return self._no_permission()
        fields = split_fields(rest) if rest else [""]
        title = fields[0] if fields else ""
        artist = fields[1] if len(fields) > 1 else ""
        if not title or not artist:
            self._start_session(event, "info")
            return ("🎙 手动录歌开始。\n"
                    "请发一条：曲名 | 艺术家 | 分类(可空) | 版本(可空) | 别名(可空) | 别名归属(可空)\n"
                    "例如：千本樱 | 黒うさP | 流行&动漫 | 手动录入 | 葱歌、千本桜\n"
                    "别名归属填 dx 或 标准，表示这些别名只对那类谱面生效；不填就是通用别名。\n"
                    "随时发「取消」退出。")
        ok, message, title, artist = self._create_song(event, fields)
        if not ok:
            return message
        self._start_session(event, "charts", title, artist)
        return (message + "\n接着发谱面：难度 等级 定数，一行一张，如「紫 14+ 14.9」；"
                         "发「完成」结束。")

    def _cmd_chart(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._manual_enabled():
            return "手动录入功能已在配置里关闭（manual_enabled）。"
        if not self._is_admin(event):
            return self._no_permission()
        fields = split_fields(rest)
        if len(fields) < 2:
            return ("格式：舞萌 加谱面 曲名 | 紫 | 14+ | 14.9\n"
                    "（定数可省略，省略时该谱面定数显示为 —）")
        # 「曲名@艺术家」用于官方库里同名曲的定位
        title, spec = fields[0], " ".join(fields[1:])
        title, _, artist = title.partition("@")
        title, artist = title.strip(), artist.strip()
        try:
            typ, difficulty, level, ds = parse_chart_line(spec)
        except ValueError as exc:
            return str(exc)
        if self.store.manual.find(title, artist or None) is not None:
            ok, message = self.store.manual.add_chart(
                title, difficulty, level, ds, typ, author=self._sender_name(event))
        else:
            # 手动库没有 → 官方快照里找，打一张「谱面补丁」
            ok, message = self._patch_official(
                title, artist, typ, difficulty, level, ds, event)
        if ok:
            self.store.reload()
        return message

    def _patch_official(self, title: str, artist: str, typ: str, difficulty: str,
                        level: str, ds: Any, event: AstrMessageEvent) -> Tuple[bool, str]:
        """给官方已有曲目追加/修正一张谱面（写入 manual_charts.json）。"""
        if not title:
            return False, "曲名不能为空。"
        matches = self.store.official_match(title)
        if artist:
            matches = [song for song in matches
                       if norm(song.get("artist")) == norm(artist)]
        if not matches:
            return False, (f"「{title}」不在官方快照里，也不在手动库。\n"
                           f"新歌先建档：舞萌 添加歌曲 {title} | 艺术家")
        if len(matches) > 1:
            names = "、".join(dict.fromkeys(song.get("artist") or "未知" for song in matches))
            return False, (f"官方库里有 {len(matches)} 首同名「{title}」：{names}。\n"
                           f"用「舞萌 加谱面 {title}@艺术家 | {typ} {difficulty} {level}"
                           f"{' ' + str(ds) if ds not in (None, '') else ''}」指定是哪首")
        song = matches[0]
        ok, message = self.store.manual.add_patch(
            song.get("title", title), song.get("artist", ""), typ, difficulty,
            level, ds, author=self._sender_name(event))
        if ok:
            message += "\n官方快照文件不动，查询里这张谱面带 📝 手动修正。"
        return ok, message

    @staticmethod
    def _parse_notes(value: str) -> Tuple[Optional[Dict[str, int]], str]:
        """解析音符数：总数，或 5 个数（tap/hold/slide/touch/break），或 key=数字。"""
        parts = [part for part in re.split(r"[,，、/\s]+", value or "") if part]
        if not parts:
            return None, "音符数不能为空。"
        keys = ("tap", "hold", "slide", "touch", "break")
        if len(parts) == 1 and "=" not in parts[0]:
            try:
                return {"total": int(parts[0])}, ""
            except ValueError:
                return None, f"音符数「{parts[0]}」不是整数。"
        if all("=" in part for part in parts):
            result: Dict[str, int] = {}
            for part in parts:
                key, _, raw = part.partition("=")
                try:
                    result[key.strip().lower()] = int(raw)
                except ValueError:
                    return None, f"音符数「{part}」不是整数。"
            return result, ""
        if len(parts) == 5:
            try:
                return dict(zip(keys, (int(part) for part in parts))), ""
            except ValueError:
                return None, "音符数的五个值都必须是整数。"
        return None, "音符数写成总数（如 1234）或五个数（tap,hold,slide,touch,break）。"

    @staticmethod
    def _parse_tags(value: str) -> List[str]:
        return [part for part in re.split(r"[,，、/\s]+", value or "") if part]

    def _cmd_chart_info(self, rest: str, event: AstrMessageEvent) -> str:
        """改官方谱面的谱师 / 标签 / 音符数，同时保留等级、定数。"""
        if not self._manual_enabled():
            return "手动录入功能已在配置里关闭（manual_enabled）。"
        if not self._is_admin(event):
            return self._no_permission()
        fields = split_fields(rest)
        if len(fields) < 2 or not fields[0].strip():
            return ("格式：舞萌 改谱面信息 曲名 | dx 紫 | 谱师=某人 | 标签=底力,体力 | 音符=1234\n"
                    "（字段可任选；不写字段就查看当前值。音符也可写 5 个数：tap,hold,slide,touch,break）")
        title_field, spec = fields[0].strip(), fields[1]
        title, _, artist = title_field.partition("@")
        title, artist = title.strip(), artist.strip()
        typ, difficulty = "dx", ""
        for token in re.split(r"[\s|,，、/]+", spec):
            if not token:
                continue
            if parse_type(token):
                typ = parse_type(token) or typ
            elif parse_difficulty(token):
                difficulty = parse_difficulty(token) or ""
        if not difficulty:
            return "没看懂难度，例如：舞萌 改谱面信息 Oshama Scramble! | dx 紫 | 谱师=Jack"

        song, error = self._official_song(title, artist)
        if song is None:
            return error
        if self.store.manual.find(title, artist or None) is not None:
            return "手动条目暂不支持改谱师/标签/音符数；这些字段只对官方快照曲目生效。"
        chart = self.store.chart_of(song, typ, difficulty)
        if chart is None:
            return (f"官方快照里「{song.get('title')}」没有 {describe(difficulty, typ)} 谱面。\n"
                    f"先用「舞萌 加谱面 {song.get('title')} | {typ} {difficulty} 等级 定数」补上。")

        updates: Dict[str, Any] = {}
        for raw in fields[2:]:
            raw = raw.strip()
            if not raw:
                continue
            match = re.match(r"^([^=:：\s]+)\s*[=:：]?\s*(.*)$", raw)
            if not match:
                continue
            key, value = match.group(1).strip().lower(), match.group(2).strip()
            if key in ("谱师", "charter", "谱师名"):
                updates["charter"] = value
            elif key in ("标签", "tag", "tags"):
                updates["chart_tags"] = self._parse_tags(value)
            elif key in ("音符", "note", "notes"):
                notes, note_error = self._parse_notes(value)
                if notes is None:
                    return note_error
                updates["notes"] = notes
            else:
                return (f"没看懂字段「{match.group(1)}」。支持：谱师= / 标签= / 音符=。")

        current = chart.get("notes") or {}
        if not updates:
            total = sum(int(value or 0) for value in current.values()) if current else 0
            breakdown = "、".join(f"{key} {value}" for key, value in current.items()) or "—"
            return (f"🎼 {song.get('title')} · {describe(difficulty, typ)}\n"
                    f"谱师｜{chart.get('charter') or '—'}\n"
                    f"标签｜{'、'.join(chart.get('chart_tags') or []) or '—'}\n"
                    f"音符｜{total}（{breakdown}）")

        ok, message = self.store.manual.add_patch(
            song.get("title", title), song.get("artist", artist), typ, difficulty,
            chart.get("level", ""), chart.get("ds"), author=self._sender_name(event),
            **updates)
        if ok:
            self.store.reload()
        return message

    @staticmethod
    def _split_alias_scope(fields: List[str]) -> Tuple[List[str], Optional[str]]:
        """把别名参数里的尾段类型（dx/标准）摘出来，其余仍是别名文本。"""
        alias_fields = [field for field in fields if field.strip()]
        if len(alias_fields) > 1:
            scope = parse_type(alias_fields[-1])
            if scope:
                return alias_fields[:-1], scope
        elif len(alias_fields) == 1:
            # 会话里是「别名 甲,乙 dx」这种一整段，类型在末尾的空格后
            head, _, tail = alias_fields[0].rpartition(" ")
            scope = parse_type(tail) if head.strip() else None
            if scope:
                return [head.strip()], scope
        return alias_fields, None

    def _official_song(self, query: str, artist: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
        """在官方快照里按曲名/别名定位一首歌；同名多首时要求 ``曲名@艺术家``。"""
        matches = self.store.official_match(query)
        if artist:
            matches = [song for song in matches
                       if norm(song.get("artist")) == norm(artist)]
        if not matches:
            return None, (f"「{query}」不在官方快照里，也不在手动库。\n"
                          f"新歌先建档：舞萌 添加歌曲 {query} | 艺术家")
        if len(matches) > 1:
            names = "、".join(dict.fromkeys(song.get("artist") or "未知" for song in matches))
            return None, (f"官方库里有 {len(matches)} 首同名「{query}」：{names}。\n"
                          f"用「舞萌 加别名 {query}@艺术家 | 别名」指定是哪首")
        return matches[0], ""

    def _cmd_alias_add(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._manual_enabled():
            return "手动录入功能已在配置里关闭（manual_enabled）。"
        if not self._is_admin(event):
            return self._no_permission()
        fields = split_fields(rest)
        if len(fields) < 2 or not fields[0].strip():
            return ("格式：舞萌 加别名 曲名 | 别名1, 别名2 [| dx 或 标准]\n"
                    "（最后一段填 dx/标准 就是该类型专属别名，不填是通用别名；\n"
                    " 官方快照里的歌也能改，别名只在插件里生效，不改官方 JSON）")
        alias_fields, scope = self._split_alias_scope(fields[1:])
        if not alias_fields:
            return "别名不能为空。"
        title_field = fields[0].strip()
        title, _, artist = title_field.partition("@")
        title, artist = title.strip(), artist.strip()
        manual = self.store.manual.find(title, artist or None)
        if manual is not None:
            ok, message = self.store.manual.add_aliases(
                title, " ".join(alias_fields), official_songs=self.store.official_songs,
                scope=scope)
        else:
            song, error = self._official_song(title, artist)
            if song is None:
                return error
            ok, message = self.store.manual.add_official_aliases(
                song, " ".join(alias_fields), scope=scope,
                author=self._sender_name(event),
                official_songs=self.store.official_songs,
                manual_songs=self.store.manual.songs())
            if ok:
                message += "\n官方快照文件不动，查询里会带上 📝 别名修正。"
        if ok:
            self.store.reload()
        return message

    def _cmd_alias_remove(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._manual_enabled():
            return "手动录入功能已在配置里关闭（manual_enabled）。"
        if not self._is_admin(event):
            return self._no_permission()
        fields = split_fields(rest)
        if len(fields) < 2 or not fields[0].strip():
            return "格式：舞萌 删除别名 曲名 | 别名1, 别名2 [| dx 或 标准]"
        alias_fields, scope = self._split_alias_scope(fields[1:])
        if not alias_fields:
            return "别名不能为空。"
        title_field = fields[0].strip()
        title, _, artist = title_field.partition("@")
        title, artist = title.strip(), artist.strip()
        manual = self.store.manual.find(title, artist or None)
        if manual is not None:
            ok, message = self.store.manual.remove_alias(
                title, " ".join(alias_fields), scope)
        else:
            song, error = self._official_song(title, artist)
            if song is None:
                return error
            ok, message = self.store.manual.remove_official_aliases(
                song, " ".join(alias_fields), scope,
                official_songs=self.store.official_songs,
                manual_songs=self.store.manual.songs())
            if ok:
                message += "\n只改插件内的查询结果，官方快照文件没动。"
        if ok:
            self.store.reload()
        return message

    def _cmd_del_song(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._is_admin(event):
            return self._no_permission()
        title = rest.replace("|", " ").strip()
        if not title:
            return "格式：舞萌 删除歌曲 曲名"
        ok, message = self.store.manual.remove_song(title)
        if ok:
            self.store.reload()
        return message

    def _cmd_del_chart(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._is_admin(event):
            return self._no_permission()
        fields = split_fields(rest)
        if len(fields) < 2:
            return "格式：舞萌 删除谱面 曲名 | 紫（类型可加 dx / 标准）"
        title = fields[0]
        typ = "dx"
        difficulty_token = ""
        # 「dx 白」这种一段里带空格的写法也要能拆
        for token in re.split(r"[\s|]+", " ".join(fields[1:])):
            if not token:
                continue
            if parse_type(token):
                typ = parse_type(token) or typ
            elif parse_difficulty(token):
                difficulty_token = token
        if not difficulty_token:
            return "没看懂难度，例如：舞萌 删除谱面 曲名 | 紫"
        if self.store.manual.find(title) is not None:
            ok, message = self.store.manual.remove_chart(title, difficulty_token, typ)
        else:
            # 手动库没有这张 → 试着撤销官方条目的谱面补丁
            ok, message = self.store.manual.remove_patch(title, typ, difficulty_token)
        if ok:
            self.store.reload()
        return message

    def _cmd_list(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._is_admin(event):
            return self._no_permission()
        return render_manual_list(self.store.manual.songs(), self.store.manual.patches(),
                                  self.store.manual.alias_records())

    def _cmd_submit(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._manual_enabled() or not self.config.get("user_submit", True):
            return "暂不接受普通用户提交。"
        fields = split_fields(rest)
        if len(fields) < 4:
            return ("格式：舞萌 提交 曲名 | 艺术家 | 紫 | 14+ | 14.9\n"
                    "（最后一项定数可省略；难度可用 绿/黄/红/紫/白）")
        title, artist = fields[0], fields[1]
        try:
            typ, difficulty, level, ds = parse_chart_line(" ".join(fields[2:]))
        except ValueError as exc:
            return str(exc)
        ok, message = self.store.manual.submit(
            title, artist, difficulty, level, ds, typ, author=self._sender_name(event),
            official_songs=self.store.official_songs, limit=self._manual_limit())
        return message

    def _cmd_pending(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._is_admin(event):
            return "待审核队列只有管理员能看。"
        return render_pending(self.store.manual.pending())

    def _cmd_approve(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._is_admin(event):
            return "只有管理员能审核。"
        if not rest.strip():
            return "格式：舞萌 通过 <编号>（编号见「舞萌 待审核」）"
        ok, message = self.store.manual.approve(rest)
        if ok:
            self.store.reload()
        return message

    def _cmd_reject(self, rest: str, event: AstrMessageEvent) -> str:
        if not self._is_admin(event):
            return "只有管理员能审核。"
        if not rest.strip():
            return "格式：舞萌 驳回 <编号>（编号见「舞萌 待审核」）"
        return self.store.manual.reject(rest)[1]

    def _manual_command(self, word: str, rest: str, event: AstrMessageEvent) -> Optional[str]:
        action = MANUAL_WORDS.get(word)
        if action is None:
            return None
        if action == "cancel":
            self._drop_session(event)
            return "已退出录歌流程。已建档的条目仍在手动库里，可用「舞萌 删除歌曲 曲名」删除。"
        handler = {
            "add": self._cmd_add, "chart": self._cmd_chart,
            "chart_info": self._cmd_chart_info,
            "alias_add": self._cmd_alias_add, "alias_remove": self._cmd_alias_remove,
            "del_song": self._cmd_del_song, "del_chart": self._cmd_del_chart,
            "list": self._cmd_list, "submit": self._cmd_submit,
            "pending": self._cmd_pending, "approve": self._cmd_approve,
            "reject": self._cmd_reject,
        }.get(action)
        if handler is None:
            return None
        return handler(rest, event)

    # ------------------------------------------------------------ 指令

    @filter.command("舞萌", alias={"maimai", "mai", "查歌"})
    async def maimai(self, event: AstrMessageEvent):
        """查询舞萌DX谱面：舞萌 <曲名> / 舞萌 13+ / 舞萌 统计 / 舞萌 帮助"""
        payload = self._payload(event)
        word, _, rest = payload.partition(" ")
        try:
            manual = self._manual_command(word.strip().lower(), rest.strip(), event)
            text = manual if manual is not None else answer(payload, self.store, self.config)
        except Exception as exc:  # 不让单次查询异常打穿消息流程
            logger.error("[maimai_kb] 查询失败: %s", exc)
            text = "查询出错了，换个曲名试试，或发送「舞萌 帮助」查看用法。"
        yield event.plain_result(self._reply(text))

    # ------------------------------------------------------------ 录歌引导（接住后续消息）

    @filter.event_message_type(ALL_MESSAGES)
    async def manual_session(self, event: AstrMessageEvent):
        session = self._live_session(event)
        if session is None:
            return
        text = PREFIX_RE.sub("", (event.message_str or "").replace("\u3000", " ").strip())
        if not text:
            return
        head = text.split(" ", 1)[0].strip().lower()
        if head in COMMAND_WORDS:
            return  # 带「舞萌」的输入交给指令处理器（引导中的「取消」等仍按内容处理）
        event.stop_event()
        try:
            reply = self._session_step(event, session, text)
        except Exception as exc:
            logger.error("[maimai_kb] 录歌流程失败: %s", exc)
            self._drop_session(event)
            reply = "录歌出错了，已退出流程。可以重新发「舞萌 添加歌曲」。"
        if reply:
            yield event.plain_result(self._reply(reply))

    def _session_step(self, event: AstrMessageEvent, session: Dict[str, Any],
                      text: str) -> str:
        lowered = text.lower().strip()
        if text in CANCEL_WORDS or lowered in CANCEL_WORDS:
            self._drop_session(event)
            return "已退出录歌流程。已建档的条目仍在手动库里，可用「舞萌 删除歌曲 曲名」删除。"
        if not self._manual_enabled():
            self._drop_session(event)
            return "手动录入功能已在配置里关闭（manual_enabled）。"

        if session.get("step") == "info":
            fields = split_fields(text)
            ok, message, title, artist = self._create_song(event, fields)
            if not ok:
                return message + "\n再发一次「曲名 | 艺术家」，或发「取消」退出。"
            self._start_session(event, "charts", title, artist)
            return (message + "\n接着发谱面：难度 等级 定数，例如「紫 14+ 14.9」；"
                              "发「完成」结束。")

        if text in DONE_WORDS or lowered in DONE_WORDS:
            title = session.get("title", "")
            self._drop_session(event)
            song = self.store.manual.find(title, session.get("artist") or None)
            charts = sum(len(values or {}) for values in (song or {}).get("difficulty", {}).values())
            return (f"✅ 「{title}」已保存，共 {charts} 张谱面。\n"
                    f"发「舞萌 {title}」看看效果；还能继续用「舞萌 加谱面 {title} | 紫 | 14+ | 14.9」补谱面。")

        alias_head, _, alias_rest = text.partition(" ")
        if alias_head.strip().lower() in ("别名", "alias") and alias_rest.strip():
            alias_fields, scope = self._split_alias_scope(split_fields(alias_rest))
            if not alias_fields:
                return "别名不能为空。\n继续发谱面或别名，发「完成」结束。"
            ok, message = self.store.manual.add_aliases(
                session.get("title", ""), " ".join(alias_fields),
                official_songs=self.store.official_songs, scope=scope)
            if ok:
                self.store.reload()
                session["ts"] = time.time()
            return message + ("\n继续发谱面（如「紫 14+ 14.9」「标准 红 12 12.2」），"
                              "别名可加类型（如「别名 甲,乙 dx」），或发「完成」结束。")

        try:
            typ, difficulty, level, ds = parse_chart_line(text)
        except ValueError as exc:
            return (f"{exc}\n谱面写成「紫 14+ 14.9」（换类型就写「标准 紫 14 14.2」），"
                    "别名写成「别名 干脆面, 魔法士」，或发「完成」结束。")
        ok, message = self.store.manual.add_chart(
            session.get("title", ""), difficulty, level, ds, typ,
            author=self._sender_name(event))
        if not ok:
            return message + "\n改一下再发，或发「完成」结束。"
        self.store.reload()
        session["ts"] = time.time()
        return message + "\n继续发下一张，或发「完成」结束。"

    # ------------------------------------------------------------ LLM 工具

    @filter.llm_tool(name="maimai_lookup")
    async def maimai_lookup(self, event: AstrMessageEvent, query: str,
                            kind: str = "auto") -> str:
        """查询舞萌DX（maimai DX）歌曲的显示等级、精确定数、别名与谱面属性。

        Args:
            query (string): 曲名或别名；kind 为 level 时填显示等级（如 13+），为 ds 时也可填定数区间（如 13.5-13.9）
            kind (string): 查询类型：auto 自动判断、song 按曲名、ds 只要定数、level 按等级、stats 数据统计
        """
        kind = (kind or "auto").strip().lower()
        if kind == "stats":
            command = "统计"
        elif kind in ("song", "ds", "level"):
            command = f"{kind} {query}".strip()
        else:
            command = (query or "").strip()
        try:
            return answer(command, self.store, self.config)
        except Exception as exc:
            logger.error("[maimai_kb] 工具查询失败: %s", exc)
            return f"查询失败：{exc}"

    # ------------------------------------------------------------ 自动注入

    @filter.on_llm_request()
    async def inject_chart_info(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not self.config.get("inject_enabled", True):
            return
        try:
            songs = self.store.mentioned(
                event.message_str or "", int(self.config.get("inject_max_songs", 1)))
            block = injection_text(self.store, songs)
        except Exception as exc:
            logger.warning("[maimai_kb] 注入谱面资料失败: %s", exc)
            return
        if block:
            req.system_prompt = f"{req.system_prompt or ''}\n\n{block}"

    async def terminate(self):
        """插件卸载/重载时释放索引。"""
        self.sessions.clear()
        self.store = None  # type: ignore[assignment]
