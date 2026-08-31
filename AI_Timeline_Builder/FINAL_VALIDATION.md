# FINAL_VALIDATION —— 总改造收口验收

本文件是**人工汇总**的总闸门表。每一行都对应一次真实执行，日志路径写在后面。
逐用例明细由脚本生成，见 `out/acceptance/reports/FINAL_VALIDATION.md` 与
`out/acceptance/reports/FINAL_RENDER_MATRIX.md`。

- 环境：Windows 11 / PowerShell 5.1 / Python 3.12.10 / Node 在 `C:\Program Files\nodejs`
- ffmpeg / ffprobe：`%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe`
- 渲染：Remotion（`@remotion/bundler` + `renderMedia`），Composition `TimelineVideo`
- 素材：只用真实文件 `out/demo.mp4`（58.771s）、`out/demo1.mp4`（95.100s），只读未改动

## 1. 闸门总表

- `python -m pytest -q` → **807 passed / 0 failed**
- `node --test src/lib/timeline.test.ts src/effects/registry.test.ts src/transitions/registry.test.ts`
  → **74 tests / 74 pass / 0 fail**
- `node node_modules/typescript/bin/tsc --noEmit` → **0 error**
- 特征用例全量 `python out/acceptance/analyze.py final`
  → **PASS 155 / FAIL 0**（SKIPPED 11、NOT_IMPLEMENTED 2，全部逐条声明理由）
- 元素夹具 `python tools/build_fixtures.py probe` → **16/16 OK，非预期黑帧 0**
  （`out/acceptance/logs/fixtures_probe.json`）
- GUI 成片探针（同一 `probe_one()`）→ **11/11 OK，FAIL 0**
  （`out/acceptance/logs/probe_gui_final.json`）
- GUI 交互冒烟 `python out/acceptance/gui_drag.py` → **11 组全 PASS**（`logs/gui_drag.json`）
- GUI 往返 `python out/acceptance/gui_roundtrip.py` → **4 组全 PASS**（`logs/gui_roundtrip.json`）
- 退出路径 `python out/acceptance/exit_paths.py` → **3 条全 PASS**（`logs/exit_paths.json`）
- DPI 125% / 150% / 175% → 每轮 5 组坐标用例，**三轮全 PASS**
- 文档漂移 `python tools/build_catalog.py --check` → 无漂移（由 `tests/test_catalog.py` 守着）

## 2. 保留清单（改造前后都在，且都有测试覆盖）

Schema v1 / v2、v1↔v2 迁移、TimelineModel、TimelineValidator、Sparse JSON、
EffectRegistry（14 个 program effect + 10 个素材特效叠加层）、Transition Runtime（11 个）、
Freeze、Caption / CaptionGroup、Video / Audio / Overlay / Text / Image、Transform、
Keyframe、Marker、GUI 全部面板、Remotion 渲染链路。

**没有删除任何既有能力，也没有重写任何模块** —— 全部是在既有源码上增量改造。

## 3. 稀疏序列化（铁律）

`core/sparse.py` 的唯一判据是「值 == Runtime 默认值」，**从不做真假值判断**：

- `opacity = 0`、`enabled = false`、`volume = 0`、`master_volume = 0` 都是**有意义的显式值**，必须落盘
- 用户没设置 → JSON 不写；设置了 → 写；改回默认 → 再删掉
- `meta.markers` 空列表、`meta.safe_area` 只有 `preset` 且等于通用档 → 省略
- `meta.safe_area` 带额外键时**整体保留**（不做半省略）

验证方式：读入 → 导出，逐字节一致（`roundtrip_stable = true`），连续存取 ×5 不漂移；
GUI 全流程用例额外断言「**没动过的片段身上不能出现 `transform` / `speed` / `audio` / `keyframes`**」。

## 4. 两层校验与规则一致性

顺序固定：NaN / Inf 预检 → jsonschema → 语义校验 → RuleEngine。

`core.rule_engine.consistency_report()` 双向核对（实跑数字）：

- 声明规则 39 条 + 豁免声明 1 条 = **40**
- 源码里实现到的规则 id = **40**
- `declared_not_implemented = 0`
- `implemented_not_declared = 0`

即：**声明的规则都实现了，实现的规则都声明了**，没有"文档写了代码没做"或反之。
规则实现分布在 `core/timeline_validator.py`（37 条）与 `core/rule_engine.py`（3 条：
`RULE_CLIP_001` / `RULE_CLIP_002` / `RULE_SAFE_AREA_001`）。

## 5. AI 边界（硬约束）

`docs/AI_CAPABILITIES.json` 是能力白名单（14 类媒体能力、4 类动作、5 条规则、
4 个安全区档位、6 项 voice 能力、3 项 asset 能力、3 项分辨率能力、6 条 contract、
5 步 pipeline、2 个示例）。

链路是单向的：

```
AI → EditingDecision → EditingPlanner → TimelineModel → 稀疏 JSON → Remotion → MP4
```

**AI 绝对不能直接生成 TSX**，也不能直接写 JSON —— 它只能产出 EditingDecision，
由 `core/editing_planner.py` 翻译成模型操作，任何白名单外的特效 / 转场 / 音效 / 动作
在 Planner 入口就被拒。v1 不接任何外部 AI API。

## 6. 分辨率与安全区

- 预置档位 **17** 个，四种比例（3:4 / 9:16 / 16:9 / 1:1）**全部真实渲染过**
- 真实渲染并 ffprobe 核对的具体档位：810×1080、1080×1440、1080×1920、1920×1080、
  1080×1080，另有非预置的 540×960 小画布
- 安全区 4 档：`tiktok` / `youtube_shorts` / `instagram_reels` / `generic`，
  链路完整（数据 → schema → 校验规则 → 稀疏省略 → 项目设置对话框 → 预览叠加层 → 测试）

## 7. 无声数据丢失的处理（§33）

v2 → v1 降级不再静默丢字段：`TimelineModel.set_timeline()` 调 `downgrade_losses()`，
把每一条丢失写进 `report["downgrade_losses"]` 并逐条 `logMessage.emit()`。
无损降级时**不写**这个字段（避免噪音）。由 `tests/test_timeline_model.py` 两条用例锁死。

## 8. 明确的局限（不当成 PASS）

1. **预览通道没有音频输出**。播放器上的音量 / 静音只作用于导出（`meta.master_volume`），
   控件文案已如实标注。音量真的生效由渲染后响度差证明：`gui_sfx` 与 `gui_master_volume`
   是同一条时间线只差 `master_volume = 0.5`，实测差 **6.0dB**，理论 20·log₁₀(0.5) = **6.02dB**。
2. 17 个预置分辨率里**只渲染了 5 个**。四种比例已全覆盖，未渲染的 12 个都是同比例下的
   其它像素档（720 / 1440 / 2160）。理由与替代验证见 `docs/FINAL_RENDER_MATRIX.md` 第 4 节。
3. **安全区数值是实测估算，不是官方规格**，而且 **Remotion 侧不读 `meta.safe_area`** ——
   它只影响预览叠加层与校验提示，不影响成片像素。
4. DPI 只覆盖 125 / 150 / 175%，用 `QT_SCALE_FACTOR` 模拟，不等于真实高分屏物理设备。
5. 「拖动是否顺滑」这类手感无法自动判定；能自动化的数字（落点误差、吸附目标、
   时长守恒、帧对齐）都给了实测值。拖动过程不触发 FFmpeg / 解码 / Remotion / AI
   由代码路径保证（交互层不持有解码器与渲染器引用），未做拖动时的 CPU 采样实测。
6. VoiceProvider 只落地了架构与本机 TTS 通道（`core/tts.py` + `core/tts_synth.ps1`），
   云端 provider 是接口占位，**没有实跑过任何云端合成**。
7. 黑帧判定依赖时间线 JSON 推导的两类豁免（fade / flash 转场窗口、无画面主体区间）。
   这是有意的设计而非白名单，但它的前提是「JSON 描述与渲染器行为一致」——
   如果将来某个转场改成不经过纯色，豁免窗口会偏保守（漏报而非误报）。
8. 抽帧探针是**采样**（每片 8 个时间点），不是逐帧全扫；逐帧全扫只在
   `analyze.py` 的 155 条特征用例里做过（抽帧总数 2646）。
