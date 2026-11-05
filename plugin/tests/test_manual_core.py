# -*- coding: utf-8 -*-
"""手动录入核心（core/manual.py + Store 合并）测试：不依赖 astrbot。

运行：python -m unittest discover -s plugin/tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "astrbot_plugin_maimai_kb"
sys.path.insert(0, str(PLUGIN_DIR.parent))

from astrbot_plugin_maimai_kb.core.answer import answer  # noqa: E402
from astrbot_plugin_maimai_kb.core.manual import (MAX_ALIASES, ManualStore,  # noqa: E402
                                                  aliases_by_scope, parse_aliases,
                                                  parse_chart_line, render_manual_list,
                                                  render_pending, set_chart)
from astrbot_plugin_maimai_kb.core.render import render_song  # noqa: E402
from astrbot_plugin_maimai_kb.core.store import Store  # noqa: E402


class ManualCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(PLUGIN_DIR / "data", self.tmp / "data")
        self.data = self.tmp / "data"
        self.manual = ManualStore(self.data)
        self.official = json.loads((self.data / "songs.json").read_text(encoding="utf-8"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    # -------------------------------------------------- 标准 / DX 双谱面

    def _dual_chart_song(self):
        ok, message, _ = self.manual.add_song(
            "双谱面曲", "艺术家", author="t", official_songs=self.official)
        self.assertTrue(ok, message)
        self.assertTrue(self.manual.add_chart("双谱面曲", "紫", "14", 14.2, "standard")[0])
        self.assertTrue(self.manual.add_chart("双谱面曲", "紫", "14+", 14.8, "dx")[0])

    def test_same_song_standard_and_dx_charts_coexist(self):
        self._dual_chart_song()
        store = Store(self.data)
        song = store.find_one("双谱面曲")
        charts = store.charts_of(song)
        self.assertEqual(len(charts), 2)
        self.assertEqual({chart["type"] for chart in charts}, {"standard", "dx"})
        standard = song["difficulty"]["standard"]["master"]
        dx = song["difficulty"]["dx"]["master"]
        self.assertEqual((standard, dx), ("14", "14+"))
        self.assertEqual((song["ds"]["standard"]["master"], song["ds"]["dx"]["master"]),
                         (14.2, 14.8))

    def test_alias_scopes_keep_standard_and_dx_apart(self):
        self._dual_chart_song()
        ok, message = self.manual.add_aliases(
            "双谱面曲", "通用名", official_songs=self.official)
        self.assertTrue(ok, message)
        ok, message = self.manual.add_aliases(
            "双谱面曲", "标准名", official_songs=self.official, scope="standard")
        self.assertTrue(ok, message)
        self.assertIn("标准谱面专属", message)
        ok, message = self.manual.add_aliases(
            "双谱面曲", "DX名", official_songs=self.official, scope="dx")
        self.assertTrue(ok, message)

        store = Store(self.data)
        song = store.find_one("双谱面曲")
        groups = aliases_by_scope(song)
        self.assertEqual(groups["shared"], ["通用名"])
        self.assertEqual(groups["standard"], ["标准名"])
        self.assertEqual(groups["dx"], ["DX名"])
        # 三种别名都能查到这首歌
        for alias in ("通用名", "标准名", "DX名"):
            self.assertEqual(store.find_one(alias)["title"], "双谱面曲")
        # 只有类型专属别名会锁定谱面类型
        self.assertIsNone(store.manual_alias_scope(song, "通用名"))
        self.assertIsNone(store.manual_alias_scope(song, "双谱面曲"))
        self.assertEqual(store.manual_alias_scope(song, "标准名"), "standard")
        self.assertEqual(store.manual_alias_scope(song, "DX名"), "dx")

    def test_scoped_alias_query_filters_charts(self):
        self._dual_chart_song()
        self.manual.add_aliases("双谱面曲", "DX名", official_songs=self.official, scope="dx")
        store = Store(self.data)
        config = {"alias_limit": 10}
        text = answer("DX名", store, config)
        self.assertIn("双谱面曲", text)
        self.assertIn("14.8", text)
        self.assertNotIn("14.2", text)          # 标准谱面被类型别名挡掉
        self.assertIn("DX 谱面专属别名", text)
        # 通用查询照常两行都在
        text = answer("双谱面曲", store, config)
        self.assertIn("14.2", text)
        self.assertIn("14.8", text)

    def test_remove_alias_respects_scope(self):
        self._dual_chart_song()
        self.manual.add_aliases("双谱面曲", "标准名", official_songs=self.official,
                                scope="standard")
        # 类型对不上就是「没有」，不会误删
        ok, message = self.manual.remove_alias("双谱面曲", "标准名", scope="dx")
        self.assertFalse(ok)
        self.assertIn("DX 谱面别名里没有", message)
        ok, message = self.manual.remove_alias("双谱面曲", "标准名", scope="standard")
        self.assertTrue(ok, message)
        song = Store(self.data).find_one("双谱面曲")
        self.assertNotIn("标准名", song["aliases"])
        self.assertEqual(aliases_by_scope(song)["standard"], [])

    def test_add_song_with_scoped_alias_field(self):
        ok, message, song = self.manual.add_song(
            "建档带类型", "艺术家", author="t", official_songs=self.official,
            aliases="DX专属名", alias_scope="dx")
        self.assertTrue(ok, message)
        self.assertEqual(aliases_by_scope(song)["dx"], ["DX专属名"])
        self.assertEqual(aliases_by_scope(song)["shared"], [])
        self.assertEqual(Store(self.data).manual_alias_scope(song, "DX专属名"), "dx")

    # -------------------------------------------------- 官方曲目的谱面补丁

    def _official_title(self):
        return self.official[0]["title"]

    def test_patch_adds_dx_chart_to_official_song(self):
        title = self._official_title()
        artist = self.official[0]["artist"]
        before = (self.data / "songs.json").read_bytes()
        ok, message = self.manual.add_patch(title, artist, "dx", "白", "15", 15.0)
        self.assertTrue(ok, message)
        self.assertEqual((self.data / "songs.json").read_bytes(), before,
                         "补丁不能写回官方 songs.json")

        store = Store(self.data)
        self.assertEqual(store.applied_patches, 1)
        song = store.official_match(title)[0]
        charts = store.charts_of(song)
        added = [chart for chart in charts if chart["difficulty"] == "remaster"
                 and chart["type"] == "dx"]
        self.assertEqual(len(added), 1)
        self.assertTrue(added[0]["patched"])
        self.assertEqual(added[0]["level"], "15")
        self.assertEqual(added[0]["ds"], 15.0)
        # 等级 / 定数区间检索也能命中
        self.assertIn(title, [row["title"] for row in store.level_rows("15")])
        self.assertIn(title, [row["title"] for row in store.ds_range(15.0, 15.0)])

    def test_patch_can_override_existing_chart(self):
        title = self.official[0]["title"]
        artist = self.official[0]["artist"]
        store = Store(self.data)
        song = store.official_match(title)[0]
        original = [(c["type"], c["difficulty"], c["ds"]) for c in store.charts_of(song)]
        ok, message = self.manual.add_patch(title, artist, "dx", "紫", "13+", 13.7)
        self.assertTrue(ok, message)

        store = Store(self.data)
        song = store.official_match(title)[0]
        charts = [(c["type"], c["difficulty"], c["ds"], c["patched"])
                  for c in store.charts_of(song)]
        target = [item for item in charts if item[0] == "dx" and item[1] == "master"]
        self.assertEqual(target[0][2], 13.7)
        self.assertTrue(target[0][3])
        # 官方其他谱面不受影响
        self.assertEqual(len(charts), len(original))

    def test_patch_removal_restores_official(self):
        title = self.official[0]["title"]
        artist = self.official[0]["artist"]
        self.manual.add_patch(title, artist, "dx", "白", "15", 15.0)
        self.assertEqual(len(Store(self.data).manual.patches()), 1)
        ok, message = self.manual.remove_patch(title, "dx", "白")
        self.assertTrue(ok, message)
        store = Store(self.data)
        self.assertEqual(store.applied_patches, 0)
        song = store.official_match(title)[0]
        self.assertFalse([c for c in store.charts_of(song)
                          if c["difficulty"] == "remaster" and c["type"] == "dx"])
        self.assertNotIn("patch", song)

    def test_patch_validation_and_unknown_song(self):
        title = self.official[0]["title"]
        artist = self.official[0]["artist"]
        ok, message = self.manual.add_patch(title, artist, "dx", "紫", "14", 14.9)
        self.assertFalse(ok)
        self.assertIn("14+", message)          # 定数与等级不自洽，拒绝
        ok, message = self.manual.add_patch(title, artist, "xx", "紫", "14", 14.5)
        self.assertFalse(ok)
        # 官方没有这首歌：补丁文件可以写，但不会生效
        ok, _ = self.manual.add_patch("官方根本没有的曲", "谁", "dx", "紫", "14", 14.5)
        self.assertTrue(ok)
        self.assertEqual(Store(self.data).applied_patches, 0)

    def test_patch_survives_reload_and_stays_out_of_official_snapshot(self):
        title = self.official[0]["title"]
        artist = self.official[0]["artist"]
        self.manual.add_patch(title, artist, "dx", "白", "15", 15.0)
        store = Store(self.data)
        store.reload()
        self.assertEqual(store.applied_patches, 1)
        official = json.loads((self.data / "songs.json").read_text(encoding="utf-8"))
        self.assertNotIn("patch", official[0])

    def test_patch_can_override_every_chart_of_a_song(self):
        """任意歌曲的标准 / DX 谱面都能逐张改，不限于补一张新谱面。"""
        title = "Oshama Scramble!"
        artist = "t+pazolite"
        ok, message = self.manual.add_patch(title, artist, "standard", "紫", "14+", 14.7)
        self.assertTrue(ok, message)
        ok, message = self.manual.add_patch(title, artist, "dx", "紫", "14", 14.1)
        self.assertTrue(ok, message)
        store = Store(self.data)
        song = store.official_match(title)[0]
        charts = {(chart["type"], chart["difficulty"]): chart for chart in store.charts_of(song)}
        self.assertEqual(charts[("standard", "master")]["level"], "14+")
        self.assertEqual(charts[("standard", "master")]["ds"], 14.7)
        self.assertEqual(charts[("dx", "master")]["level"], "14")
        self.assertEqual(charts[("dx", "master")]["ds"], 14.1)
        self.assertTrue(charts[("standard", "master")]["patched"])
        self.assertTrue(charts[("dx", "master")]["patched"])
        # 只改等级/定数时，原谱面的谱师、音符数、标签不能丢
        self.assertEqual(charts[("standard", "master")]["charter"], "Jack")
        self.assertTrue(charts[("standard", "master")]["chart_tags"])
        self.assertTrue(charts[("standard", "master")]["notes"])
        # 等级索引里不会同时留下旧等级
        self.assertFalse(any(row["title"] == title and row["type"] == "dx"
                             and row["difficulty"] == "master"
                             for row in store.level_rows("13+", "dx")))

    def test_patch_can_edit_chart_metadata(self):
        title, artist = "Oshama Scramble!", "t+pazolite"
        ok, message = self.manual.add_patch(
            title, artist, "dx", "master", "13+", 13.6,
            charter="测试谱师", notes={"total": 1234},
            chart_tags=["测试标签", "底力谱"])
        self.assertTrue(ok, message)
        store = Store(self.data)
        chart = store.chart_of(store.official_match(title)[0], "dx", "master")
        self.assertEqual(chart["charter"], "测试谱师")
        self.assertEqual(chart["notes"], {"total": 1234})
        self.assertEqual(chart["chart_tags"], ["测试标签", "底力谱"])
        # 只再改等级/定数，不应抹掉刚写的谱师/音符/标签
        ok, message = self.manual.add_patch(title, artist, "dx", "master", "13+", 13.8)
        self.assertTrue(ok, message)
        chart = Store(self.data).chart_of(
            Store(self.data).official_match(title)[0], "dx", "master")
        self.assertEqual(chart["charter"], "测试谱师")
        self.assertEqual(chart["notes"], {"total": 1234})
        self.assertEqual(chart["chart_tags"], ["测试标签", "底力谱"])
        self.assertEqual(chart["ds"], 13.8)

    # -------------------------------------------------- 官方曲目的别名补丁

    def _official_song(self, title: str, artist: str = "") -> dict:
        for song in self.official:
            if song["title"] == title and (not artist or song["artist"] == artist):
                return song
        self.fail(f"官方快照里没有 {title}")

    def test_official_alias_shared_and_scoped(self):
        title, artist = "Oshama Scramble!", "t+pazolite"
        song = self._official_song(title, artist)
        ok, message = self.manual.add_official_aliases(
            song, "新别名甲", official_songs=self.official)
        self.assertTrue(ok, message)
        ok, message = self.manual.add_official_aliases(
            song, "DX专属名", scope="dx", official_songs=self.official)
        self.assertTrue(ok, message)
        self.assertIn("DX 谱面专属", message)

        store = Store(self.data)
        merged = store.official_match(title)[0]
        groups = aliases_by_scope(merged)
        self.assertIn("新别名甲", groups["shared"])
        self.assertEqual(groups["dx"], ["DX专属名"])
        self.assertEqual(store.find_one("新别名甲")["title"], title)
        self.assertEqual(store.find_one("DX专属名")["title"], title)
        self.assertEqual(store.alias_scope(merged, "DX专属名"), "dx")
        self.assertIsNone(store.alias_scope(merged, "新别名甲"))
        self.assertEqual(store.official_alias_count, 1)

        # DX 专属别名查询只显示 DX 谱面
        text = answer("DX专属名", store, {})
        self.assertIn(title, text)
        self.assertIn("13.6", text)
        self.assertNotIn("14.5", text)
        self.assertIn("DX 谱面专属别名", text)
        # 曲名查询两种谱面都在
        both = answer(title, store, {})
        self.assertIn("13.6", both)
        self.assertIn("14.5", both)
        self.assertIn("别名（DX 谱面）", both)
        self.assertIn("📝 别名修正", both)

    def test_official_alias_scope_can_change_and_revert(self):
        title, artist = "Oshama Scramble!", "t+pazolite"
        song = self._official_song(title, artist)
        # 官方自带别名「标奶」：先限定到 DX，再改回通用
        ok, message = self.manual.add_official_aliases(
            song, "标奶", scope="dx", official_songs=self.official)
        self.assertTrue(ok, message)
        merged = Store(self.data).official_match(title)[0]
        self.assertEqual(aliases_by_scope(merged)["dx"], ["标奶"])
        self.assertNotIn("标奶", aliases_by_scope(merged)["shared"])
        self.assertIn("13.6", answer("标奶", Store(self.data), {}))
        self.assertNotIn("14.5", answer("标奶", Store(self.data), {}))

        ok, message = self.manual.add_official_aliases(
            song, "标奶", official_songs=self.official)
        self.assertTrue(ok, message)
        self.assertIn("通用别名", message)
        merged = Store(self.data).official_match(title)[0]
        self.assertIn("标奶", aliases_by_scope(merged)["shared"])
        self.assertEqual(aliases_by_scope(merged)["dx"], [])

    def test_official_alias_remove_restores_hidden_alias(self):
        title, artist = "Oshama Scramble!", "t+pazolite"
        song = self._official_song(title, artist)
        ok, message = self.manual.remove_official_aliases(song, "标奶")
        self.assertTrue(ok, message)
        store = Store(self.data)
        merged = store.official_match(title)[0]
        self.assertNotIn("标奶", merged["aliases"])
        # 再删一次：已经没有这个别名
        ok, message = self.manual.remove_official_aliases(song, "标奶")
        self.assertFalse(ok)
        self.assertIn("没有这些别名", message)
        # 重新加回来会清掉 removed
        ok, message = self.manual.add_official_aliases(
            song, "标奶", official_songs=self.official)
        self.assertTrue(ok, message)
        merged = Store(self.data).official_match(title)[0]
        self.assertIn("标奶", merged["aliases"])

    def test_official_alias_remove_respects_scope(self):
        title, artist = "Oshama Scramble!", "t+pazolite"
        song = self._official_song(title, artist)
        self.manual.add_official_aliases(
            song, "标准专属名", scope="standard", official_songs=self.official)
        ok, message = self.manual.remove_official_aliases(song, "标准专属名", scope="dx")
        self.assertFalse(ok)
        self.assertIn("DX 谱面别名里没有", message)
        ok, message = self.manual.remove_official_aliases(song, "标准专属名",
                                                          scope="standard")
        self.assertTrue(ok, message)
        merged = Store(self.data).official_match(title)[0]
        self.assertNotIn("标准专属名", merged["aliases"])

    def test_official_alias_rejects_another_title_and_keeps_snapshot(self):
        title, artist = "Oshama Scramble!", "t+pazolite"
        song = self._official_song(title, artist)
        other_title = next(item["title"] for item in self.official
                           if item["title"] != title)
        before = (self.data / "songs.json").read_bytes()
        ok, message = self.manual.add_official_aliases(
            song, other_title, official_songs=self.official)
        self.assertFalse(ok)
        self.assertIn("串台", message)
        ok, message = self.manual.add_official_aliases(
            song, "别名乙", official_songs=self.official)
        self.assertTrue(ok, message)
        self.assertEqual((self.data / "songs.json").read_bytes(), before,
                         "别名补丁不能写回官方 songs.json")

    def test_official_alias_survives_reload(self):
        title, artist = "Oshama Scramble!", "t+pazolite"
        song = self._official_song(title, artist)
        self.manual.add_official_aliases(song, "持久别名", scope="standard",
                                         official_songs=self.official)
        store = Store(self.data)
        store.reload()
        self.assertEqual(store.official_alias_count, 1)
        merged = store.official_match(title)[0]
        self.assertEqual(aliases_by_scope(merged)["standard"], ["持久别名"])
        official = json.loads((self.data / "songs.json").read_text(encoding="utf-8"))
        self.assertNotIn("alias_patch", official[0])

    # -------------------------------------------------- 解析

    def test_parse_chart_line_variants(self):
        self.assertEqual(parse_chart_line("紫 14+ 14.9"), ("dx", "master", "14+", "14.9"))
        self.assertEqual(parse_chart_line("standard 红 12 12.7"),
                         ("standard", "expert", "12", "12.7"))
        self.assertEqual(parse_chart_line("白 13"), ("dx", "remaster", "13", None))
        self.assertEqual(parse_chart_line("mas 15=15.0"), ("dx", "master", "15", "15.0"))
        self.assertEqual(parse_chart_line("紫谱 13"), ("dx", "master", "13", None))

    def test_parse_chart_line_rejects_bad_input(self):
        for bad in ("", "14+", "紫", "紫 十四", "xx 12"):
            with self.assertRaises(ValueError):
                parse_chart_line(bad)

    # -------------------------------------------------- 别名

    def test_parse_aliases(self):
        self.assertEqual(parse_aliases("干脆面, 魔法士 / 面、mián"),
                         ["干脆面", "魔法士", "面", "mián"])
        self.assertEqual(parse_aliases("  "), [])

    def test_add_song_with_aliases(self):
        ok, message, song = self.manual.add_song(
            "别名曲", "艺术家", author="t", official_songs=self.official,
            aliases="小干脆面、魔法士")
        self.assertTrue(ok, message)
        self.assertEqual(song["aliases"][0], "别名曲")
        self.assertIn("小干脆面", song["aliases"])

        store = Store(self.data)
        self.assertEqual(store.find_one("小干脆面")["title"], "别名曲")
        self.assertEqual(store.find_one("魔法士")["title"], "别名曲")

    def test_add_aliases_then_remove(self):
        self.manual.add_song("别名曲2", "艺术家", author="t", official_songs=self.official)
        ok, message = self.manual.add_aliases("别名曲2", "甲乙, 丙丁",
                                              official_songs=self.official)
        self.assertTrue(ok, message)
        store = Store(self.data)
        self.assertEqual(store.find_one("甲乙")["title"], "别名曲2")

        ok, message = self.manual.remove_alias("别名曲2", "甲乙")
        self.assertTrue(ok, message)
        self.assertTrue(self.manual.find("别名曲2") is not None)
        store = Store(self.data)
        self.assertIsNone(store.find_one("甲乙"))
        self.assertEqual(store.find_one("丙丁")["title"], "别名曲2")

    def test_alias_duplicate_and_conflict(self):
        self.manual.add_song("别名曲3", "艺术家", author="t", official_songs=self.official,
                             aliases="小名")
        ok, message = self.manual.add_aliases("别名曲3", "小名", official_songs=self.official)
        self.assertFalse(ok)
        self.assertIn("已经有了", message)

        official_title = self.official[0]["title"]
        ok, message = self.manual.add_aliases("别名曲3", official_title,
                                              official_songs=self.official)
        self.assertFalse(ok)
        self.assertIn("串台", message)

    def test_alias_limit(self):
        self.manual.add_song("别名曲4", "艺术家", author="t", official_songs=self.official)
        too_many = "、".join(f"别名{index}" for index in range(MAX_ALIASES + 1))
        ok, message = self.manual.add_aliases("别名曲4", too_many,
                                              official_songs=self.official)
        self.assertFalse(ok)
        self.assertIn("最多", message)

    def test_remove_alias_keeps_title_entry(self):
        self.manual.add_song("别名曲5", "艺术家", author="t", official_songs=self.official,
                             aliases="小五")
        ok, message = self.manual.remove_alias("别名曲5", "别名曲5")
        self.assertFalse(ok)  # 曲名本身不算可删的别名
        self.assertEqual(self.manual.find("别名曲5")["aliases"][0], "别名曲5")
        self.assertTrue(self.manual.find("别名曲5")["aliases"])

    def test_remove_alias_unknown(self):
        self.manual.add_song("别名曲6", "艺术家", author="t", official_songs=self.official)
        ok, message = self.manual.remove_alias("别名曲6", "不存在的别名")
        self.assertFalse(ok)
        self.assertIn("没有这些别名", message)

    # -------------------------------------------------- 定数 ↔ 显示等级

    def test_set_chart_enforces_level_constant_rule(self):
        song = {"difficulty": {"standard": {}, "dx": {}}, "ds": {"standard": {}, "dx": {}}}
        ok, message = set_chart(song, "dx", "master", "14+", 14.9)
        self.assertTrue(ok, message)
        self.assertEqual(song["difficulty"]["dx"]["master"], "14+")
        self.assertEqual(song["ds"]["dx"]["master"], 14.9)

        ok, message = set_chart(song, "dx", "expert", "14", 14.9)  # 14.9 应该是 14+
        self.assertFalse(ok)
        self.assertIn("14+", message)

        ok, message = set_chart(song, "dx", "basic", "6", 6.9)  # 1-6 级没有 + 档
        self.assertTrue(ok, message)

        ok, message = set_chart(song, "dx", "master", "15", 15.0)
        self.assertTrue(ok, message)

    # -------------------------------------------------- 增删改

    def test_add_song_and_chart(self):
        ok, message, song = self.manual.add_song("测试曲目", "测试艺术家", author="tester",
                                                 official_songs=self.official)
        self.assertTrue(ok, message)
        self.assertEqual(song["title"], "测试曲目")
        self.assertIsNone(song["id"])
        self.assertEqual(song["manual"]["author"], "tester")

        ok, message = self.manual.add_chart("测试曲目", "紫", "14+", 14.9, "dx")
        self.assertTrue(ok, message)
        stored = self.manual.find("测试曲目")
        self.assertEqual(stored["difficulty"]["dx"]["master"], "14+")
        self.assertEqual(stored["ds"]["dx"]["master"], 14.9)

        # 大写/标点不同的标题也要能定位到同一首
        ok, message = self.manual.add_chart("测试曲目", "红", "12", 12.2, "标准")
        self.assertTrue(ok, message)
        self.assertEqual(self.manual.find("测试曲目")["difficulty"]["standard"]["expert"], "12")

    def test_add_song_rejects_official_duplicate(self):
        title = self.official[0]["title"]
        artist = self.official[0]["artist"]
        ok, message, _ = self.manual.add_song(title, artist, official_songs=self.official)
        self.assertFalse(ok)
        self.assertIn("官方快照", message)

    def test_add_song_rejects_manual_duplicate(self):
        self.manual.add_song("重复曲", "某人", official_songs=self.official)
        ok, message, _ = self.manual.add_song("重复曲", "某人", official_songs=self.official)
        self.assertFalse(ok)
        self.assertIn("手动库", message)

    def test_missing_artist_asks_for_it(self):
        ok, message, _ = self.manual.add_song("只有曲名", "", official_songs=self.official)
        self.assertFalse(ok)
        self.assertIn("艺术家", message)

    def test_remove_chart_then_song(self):
        self.manual.add_song("删我", "某人", official_songs=self.official)
        self.manual.add_chart("删我", "紫", "13", 13.5)
        ok, message = self.manual.remove_chart("删我", "紫")
        self.assertTrue(ok, message)
        self.assertIn("整条手动条目已删除", message)
        self.assertIsNone(self.manual.find("删我"))

    def test_limit(self):
        ok, message, _ = self.manual.add_song("超限曲", "某人",
                                              official_songs=self.official, limit=0)
        self.assertFalse(ok)
        self.assertIn("上限", message)

    # -------------------------------------------------- 审核流

    def test_submit_then_approve(self):
        ok, message = self.manual.submit("待审曲", "提交者", "紫", "13+", 13.8,
                                         author="普通用户", official_songs=self.official)
        self.assertTrue(ok, message)
        queue = self.manual.pending()
        self.assertEqual(len(queue), 1)
        self.assertEqual(self.manual.find("待审曲"), None)  # 未审核前查不到

        ok, message = self.manual.approve(str(queue[0]["id"]))
        self.assertTrue(ok, message)
        song = self.manual.find("待审曲")
        self.assertIsNotNone(song)
        self.assertEqual(song["difficulty"]["dx"]["master"], "13+")
        self.assertEqual(song["manual"]["author"], "普通用户")
        self.assertEqual(self.manual.pending(), [])

    def test_submit_then_reject(self):
        self.manual.submit("驳回曲", "提交者", "紫", "13", 13.0,
                           author="普通用户", official_songs=self.official)
        entry = self.manual.pending()[0]
        ok, message = self.manual.reject(entry["id"])
        self.assertTrue(ok, message)
        self.assertIn("驳回", message)
        self.assertEqual(self.manual.pending(), [])
        self.assertIsNone(self.manual.find("驳回曲"))

    def test_submit_duplicate_queued(self):
        self.manual.submit("重提曲", "提交者", "紫", "13", 13.0,
                           author="u", official_songs=self.official)
        ok, message = self.manual.submit("重提曲", "提交者", "紫", "13", 13.0,
                                         author="u", official_songs=self.official)
        self.assertFalse(ok)
        self.assertIn("待审核队列", message)

    # -------------------------------------------------- Store 合并与渲染

    def test_store_merges_manual_into_queries(self):
        self.manual.add_song("合并测试曲", "艺术家X", "流行&动漫", "手动录入",
                             author="tester", official_songs=self.official)
        self.manual.add_chart("合并测试曲", "紫", "14+", 14.9)
        store = Store(self.data)

        self.assertEqual(store.manual_song_count, 1)
        self.assertEqual(store.manual_chart_count, 1)
        self.assertEqual(store.song_count, store.official_song_count + 1)

        found = store.find_one("合并测试曲")
        self.assertIsNotNone(found)
        self.assertTrue(found.get("manual"))

        charts = store.charts_of(found)
        self.assertEqual(charts[0]["level"], "14+")
        self.assertEqual(charts[0]["ds"], 14.9)
        self.assertTrue(charts[0]["manual"])

        # 等级查询与定数区间都能看到手动谱面
        rows = store.level_rows("14+", "dx")
        self.assertTrue(any(row["title"] == "合并测试曲" for row in rows))
        ranged = store.ds_range(14.8, 15.0, "dx")
        self.assertTrue(any(row["title"] == "合并测试曲" for row in ranged))

        text = render_song(found, charts, {})
        self.assertIn("手动录入", text)
        self.assertIn("14.9", text)

        # 官方快照统计不受影响（snapshot_meta 仍是官方数字）
        self.assertEqual(store.snapshot()["songs"], len(self.official))
        self.assertEqual(store.snapshot()["manual_songs"], 1)

    def test_two_manual_songs_do_not_share_chart_rows(self):
        # 回归：手动条目没有官方 ID，谱面索引曾经用 str(None) 做键，多首手动歌互相覆盖
        for title, level, ds in (("甲曲", "14+", 14.9), ("乙曲", "13+", 13.8)):
            self.manual.add_song(title, "同一艺术家", author="t", official_songs=self.official)
            ok, message = self.manual.add_chart(title, "紫", level, ds)
            self.assertTrue(ok, message)
        store = Store(self.data)
        first = {chart["difficulty"]: chart["ds"]
                 for chart in store.charts_of(store.find_one("甲曲"))}
        second = {chart["difficulty"]: chart["ds"]
                  for chart in store.charts_of(store.find_one("乙曲"))}
        self.assertEqual(first["master"], 14.9)
        self.assertEqual(second["master"], 13.8)

    def test_reload_picks_up_new_entries(self):
        store = Store(self.data)
        self.assertEqual(store.manual_song_count, 0)
        self.manual.add_song("重载曲", "艺术家Y", author="tester", official_songs=self.official)
        store.reload()
        self.assertEqual(store.manual_song_count, 1)
        self.assertIsNotNone(store.find_one("重载曲"))

    def test_missing_manual_file_is_fine(self):
        (self.data / "manual_songs.json").unlink(missing_ok=True)
        store = Store(self.data)
        self.assertEqual(store.manual_song_count, 0)

    def test_render_helpers(self):
        self.assertIn("还没有条目", render_manual_list([]))
        self.assertIn("队列是空的", render_pending([]))
        self.manual.add_song("列表曲", "艺术家Z", author="tester", official_songs=self.official)
        self.manual.add_chart("列表曲", "紫", "13", 13.5)
        text = render_manual_list(self.manual.songs())
        self.assertIn("列表曲", text)
        self.assertIn("MASTER 13", text)


if __name__ == "__main__":
    unittest.main()
