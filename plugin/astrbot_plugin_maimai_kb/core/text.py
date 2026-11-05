# -*- coding: utf-8 -*-
"""文本归一化与等级/难度/类型解析：纯标准库，插件内共用。

单独成模块是为了让 store / manual 都能引用，避免循环导入。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional, Tuple

DIFFICULTIES: Tuple[str, ...] = ("basic", "advanced", "expert", "master", "remaster")

DIFF_LABEL = {
    "basic": "BASIC",
    "advanced": "ADVANCED",
    "expert": "EXPERT",
    "master": "MASTER",
    "remaster": "Re:MASTER",
}

DIFF_ALIASES = {
    "basic": "basic", "bas": "basic", "绿": "basic", "绿谱": "basic",
    "advanced": "advanced", "adv": "advanced", "黄": "advanced", "黄谱": "advanced",
    "expert": "expert", "exp": "expert", "红": "expert", "红谱": "expert",
    "master": "master", "mas": "master", "紫": "master", "紫谱": "master",
    "remaster": "remaster", "remas": "remaster", "re": "remaster",
    "白": "remaster", "白谱": "remaster",
}

TYPE_LABEL = {"standard": "标准", "dx": "DX"}

TYPE_ALIASES = {
    "standard": "standard", "std": "standard", "sd": "standard", "标准": "standard",
    "旧": "standard", "旧谱": "standard", "旧曲": "standard",
    "dx": "dx", "新": "dx", "新谱": "dx", "新曲": "dx",
}

LEVEL_RE = re.compile(r"^(1[0-5]|[1-9])\+?$")
STRIP_RE = re.compile(r"[\s（）()\[\]【】・･·:：\-—_/\\'\"’‘“”!！?？*＊♪☆★~～、,，.。]")


def norm(value: Any) -> str:
    """归一化：NFKC、小写、去掉空白与常见标点。"""
    if value is None:
        return ""
    return STRIP_RE.sub("", unicodedata.normalize("NFKC", str(value)).lower())


def parse_difficulty(token: str) -> Optional[str]:
    return DIFF_ALIASES.get(norm(token))


def parse_type(token: str) -> Optional[str]:
    return TYPE_ALIASES.get(norm(token))


def parse_level(token: str) -> Optional[str]:
    """把 13 / 13+ / １３＋ 归一化成 level_index.json 的键。"""
    text = unicodedata.normalize("NFKC", str(token)).replace(" ", "").upper()
    return text if LEVEL_RE.match(text) else None


def fmt_ds(ds: Optional[float]) -> str:
    return "—" if ds is None else f"{float(ds):.1f}"


def level_rank(value: str) -> Tuple[int, int]:
    return (int(value.rstrip("+")), 1 if value.endswith("+") else 0)


def ds_label(ds: Any) -> Optional[str]:
    """官方显示等级：1-6 级没有 + 档；7 级及以上定数 x.6 起进位为 x+。"""
    try:
        number = float(ds)
    except (TypeError, ValueError):
        return None
    if not (1 <= number <= 15):
        return None
    integer = int(number)
    tenth = round((number - integer) * 10)
    if integer < 7:
        return str(integer)
    return f"{integer}+" if tenth >= 6 else str(integer)
