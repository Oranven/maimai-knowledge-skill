# 舞萌DX国服歌曲知识库

当前快照为 CN1.56-E，包含 1294 条歌曲记录、1293 个唯一标题、5520 张常规谱面，分为六个分类。查看 [INDEX.md](./INDEX.md) 获取分类、版本与标签统计。

歌曲范围与版本由国服曲库决定；精确定数与显示等级取 OneCat 官方谱面站，水鱼及备用 CSV 补充谱面 ID、谱师和音符数。别名合并在线和已有数据，历史配置标签保留。详细来源及更新规则见 [仓库 README](../README.md)。

优先查询 `../songs.json`（完整歌曲快照，含 `ds` 精确定数）和 `../level_index.json`（谱面索引，每行带 `ds`）；等级键区分 `12` 与 `12+`，显示等级由定数换算。同名曲按艺术家区分，标准和 DX 使用各自 ID。

Markdown 中的历史配置标签可能没有 SD/DX 归属，只作为歌曲层参考；具体谱面使用等级索引中的 `chart_tags`。本快照不收录宴谱。

```bash
python scripts/update_knowledge_base.py --dry-run
python scripts/update_knowledge_base.py
python scripts/update_knowledge_base.py --validate-only
python scripts/sync_onecat.py --dry-run
python scripts/sync_onecat.py
python scripts/update_knowledge_base.py --render-only
```

以上从仓库根目录运行。全量同步统一更新 JSON 和 Markdown，不再依赖旧 `maidata_kb.json` / `id_mapping.json`，不会因为缺少中间文件而生成虚构的顺序 ID。
