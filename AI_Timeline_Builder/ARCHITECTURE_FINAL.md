# ARCHITECTURE_FINAL —— 改造后的架构

日期：2026-08-30
配套文档：`ARCHITECTURE_AUDIT.md`（改造前的逐文件审计）。
本文只写**已经实现并跑通**的形态；未实现的写在末尾「边界与未做」。

## 1. 数据流

```
素材 (assets/, out/demo.mp4, out/demo1.mp4)
   │
   ├─ AssetManager ──► asset_manifest.json ──► AssetRegistry（语义分类 / 查询）
   │
GUI (PyQt5) ─┐
             ├─► TimelineModel ──► core/sparse.py ──► 稀疏 Timeline JSON
EditingDecision（AI / 脚本 / 人）─► EditingPlanner ─┘        │
                                                            ├─► TimelineValidator
                                                            │      （NaN → Schema → 语义 → RuleEngine）
                                                            │
                                                     RemotionExporter
                                                            │
                                              remotion/ (React + TSX Runtime)
                                                            │
                                                    render_batch.mjs ─► MP4
                                                            │
                                          ffprobe / 抽帧 / 黑帧 / 音量 探针 ─► 报告
```

两条硬规矩：

- **AI 不产出 TSX，也不直接产出 Timeline JSON** —— 它只出 `EditingDecision`。
- **Timeline JSON 是唯一的中间产物** —— GUI 与 Planner 都往它收敛，
  渲染只认它，验收只量它渲出来的 MP4。

## 2. 模块分层

### core/ —— DSL 与语义

- `timeline.py`：元素工厂 + 全部 Runtime 默认值（唯一一份）
- `sparse.py`：Canonical Sparse 序列化（落盘前最后一道）
- `timeline_model.py`：可撤销的编辑模型，`to_dict()` 就是要落盘的那份
- `timeline_validator.py`：分层校验（NaN → jsonschema → 语义 → 规则引擎）
- `rule_engine.py`：剪辑规则 + 规则 id 与实现的**双向**一致性报告
- `resolution.py`：4 种比例 × 分辨率档位（按短边索引）
- `safe_area.py`：4 个平台安全区档位（四边不对称，只影响预览与规则）
- `editing_planner.py`：EditingDecision → 元素（deepcopy，绝不改输入）
- `voice.py`：VoiceProvider 抽象 + 系统 SAPI 实现 + 词时间轴（估算要标记）
- `migrations/`：v1↔v2，降级损失显式列出
- `time_utils.py` / `markers.py` / `undo_manager.py` / `asset_manager.py` /
  `project_manager.py` / `demo_project.py` / `tts.py` / `jianying_import.py`

### libraries/ —— 可选内容目录

`effect_registry.py` / `transition_registry.py`（名字与 Runtime 一一对应，
node 测试双向校验）、`effect_library.py` / `transition_library.py`、
`caption_library.py`（8 个字幕模板）、`animation_library.py`、
`template_library.py`（4 个一键组合）、`sound_library.py`、
`asset_registry.py`（10 种语义类型）、`param_spec.py`、`asset_library.py`

### gui/ —— 编辑器

`main_window.py` 装配与菜单/工具条；`timeline_widget.py` 自绘轨道画布
（坐标 / 命中 / 磁吸 / 拖放拆到 `timeline_coordinate.py`、`timeline_snap.py`、
`timeline_interaction.py`、`asset_placement.py`）；`property_panel.py` 属性面板
（只读生效值，绝不 setdefault 回写）；`preview_widget.py` 预览
（动作 93% / 标题 90% + 平台安全区）；`json_panel.py` 实时稀疏 JSON；
`dialogs/` 项目设置（比例 / 分辨率 / 安全区档位联动）。

### render/ + remotion/ —— 出片

`remotion_exporter.py` 负责拷素材 + 写 inputProps；
`remotion/src` 是分层 Runtime（`lib/timeline.ts` 纯函数、
`effects/` 14 个特效、`transitions/` 11 个转场、各类 Layer 组件）。
node 测试 74 个，`tsc --noEmit` 干净。

### tools/ + tests/ + out/acceptance/ —— 生成与验收

- `tools/build_catalog.py`：14 份目录 / 能力 / 提示词文件，全部**从源码生成**
- `tools/build_fixtures.py`：16 份 fixture（build / check / probe 三个子命令）
- `tests/`：pytest 套件（805 项）
- `out/acceptance/`：155 用例的真实渲染 + 探针 + GUI 真机脚本

## 3. 一致性是怎么保证的（不靠人记）

- 特效 / 转场名字：Python Registry ↔ TSX Registry 双向测试
- 规则 id：`schemas/rules.json` ↔ 实现源码双向扫描
- 文档：`docs/*` 由 `build_catalog.py` 生成，`tests/test_catalog.py` 守着漂移
- fixture：磁盘文件 ↔ 生成器输出逐字节比对
- 稀疏性：fixture + GUI 双向守门（拖一下就多字段会立刻红）
- 帧准确性：判据统一走 `time_utils.seconds_to_frames`，不比小数

## 4. 边界与未做

- **v1 不接任何 AI API**。EditingDecision 由人 / 脚本 / 外部模型产出。
- 安全区内缩数值是实测估算，不是平台官方规格；Remotion 侧不读它。
- 预览没有音频通路，音量控件改的是导出音量 `meta.master_volume`。
- 配音走系统 SAPI，拿不到词级时间戳，所以时间轴是 `estimated`。
- v2 的 `group` 元素只有 Schema 与迁移支持，Runtime 未实现分组渲染
  （见 `SCHEMA_V2_MIGRATION_GAPS.md`）。
