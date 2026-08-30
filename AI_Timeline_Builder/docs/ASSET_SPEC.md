# ASSET_SPEC —— 素材

实现在 `core/asset_manager.py`（扫盘与清单）与 `libraries/asset_registry.py`
（语义分类与查询）。清单文件是 `asset_manifest.json`，导出时按
`RemotionExporter` 的规则拷进 `remotion/public/<asset.path>`。

## 语义类型

`libraries/asset_registry.py:SEMANTIC_TYPES`：

`video` `image` `sticker` `overlay` `transition_material` `effect_material`
`music`（A1）`voice`（A2）`sfx`（A3）`font`

分类来源有两条，都从清单本身推：

- 目录语义 `DIR_SEMANTICS`：`transitions/` → `transition_material`、
  `effects/` → `effect_material`、`overlays/` → `sticker`；
- 分类名：`MUSIC_CATEGORIES = bgm, music`、
  `VOICE_CATEGORIES = tts, voice, vo, narration`。

## Registry API

`AssetRegistry.from_manifest(manifest, root)` 之后可用：
`get` `has` `all` `by_type` `by_category` `by_tag` `categories_of`
`count_by_type` `search` `first_of` `missing_files` `summary` `export`。

`record_of()` 输出结构化条目，**省掉值为 0 的字段**（比如图片没有时长），
和 Timeline 的稀疏原则保持一致。

## 当前仓库实测

`missing_files()` 为空（清单里的每个文件都真的在磁盘上）。
按语义类型的数量见 `docs/AI_CAPABILITIES.json` 的 `assets` 段 ——
那份是 `tools/build_catalog.py` 生成的，永远与仓库同步；
本文档不复制数字，避免出现第二个「事实来源」。

## 给 AI 的约束

AI 只能引用 `docs/AI_CAPABILITIES.json` 里列出的 asset id。
`core/editing_planner.py` 会拒绝不存在的素材（`_asset_ok`），
Validator 的 `RULE_ASSET_*` 再兜一层：id 不存在 / 文件不存在 / 时长不够都会报错。
