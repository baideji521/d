# GUI 时间线交互验收报告（阶段 7 收口）

本报告只写**跑出来的结果**。每一节都给出证据文件路径，任何没能自动化的地方
写在第 17 节，不用「看起来没问题」代替 PASS。

- 验收脚本：`out/acceptance/gui_drag.py`、`out/acceptance/gui_roundtrip.py`
- 结构化日志：`out/acceptance/logs/gui_drag.json`、`gui_drag_dpi_1_25|1_5|1_75.json`、`gui_roundtrip.json`
- 渲染日志：`out/acceptance/logs/render_gui.json`、`render_gui_p8.json`
- 素材：只读源视频 `out/demo.mp4`（58.771s / 810×1080）、`out/demo1.mp4`（95.1s / 810×1080）

所有 GUI 用例都是**给真实控件发真实 Qt 事件**（QDragEnter / QDragMove / QDrop /
QMouseEvent），坐标换算、命中测试、磁吸、轨道校验、落库全部走生产代码。
窗口用 `WA_DontShowOnScreen` 离屏运行：布局与事件分发照常，但不占用桌面、不抢焦点。

## 1. 统一坐标系

`gui/timeline_coordinate.py` 是唯一的换算入口：`time_to_x` / `x_to_time` /
`track_to_y` / `element_to_rect` / `element_to_hit_rect`。视图状态（缩放 pps +
滚动 scroll_x + 轨道显示序）由 `ViewState` 生成**快照**再交给交互层，
所以「当前视图」与「一次手势用的坐标」是两份，拖动过程中刷新界面不会把手势带歪。

## 2. 落点精度（缩放 × 滚动）

20 组组合：pps ∈ {20, 50, 100, 200, 400} × scroll ∈ {0, 1000, 3000, 5000}px，
目标 20.0s 落点。**最大误差 0.0s**（阈值 0.01s）。0 秒落点单独验过：start = 0.0。
这一节刻意**关掉磁吸**——要量的是换算本身，磁吸开着会把误差吸掉。
证据：`logs/gui_drag.json` → 「落点精度（缩放 × 滚动）」的 `rows` 与 `max_error`。

## 3. 拖动已有片段：抓点偏移守恒

抓在片段内部 12.5s 处拖到 30.0s → start = 27.5s（误差 0）；再抓 30.0s 拖到 40.0s →
start = 37.5s。**时长不变**，抓点相对位置守恒。撤销一次回到 27.5s。
跨轨道拖动落到 V2；不合法目标轨被拒绝且元素留在原处。

## 4. 磁吸

管线固定为 raw → snap → **帧对齐放最后**。目标集合：零点 / 播放头 / 片段头 /
片段尾 / 片段中心 / 标记 / 标尺刻度；头尾竞争由 `snap_span` 决定。
常量：`SNAP_PIXELS = 10.0`、`MAX_SNAP_SECONDS = 0.12`、`RULER_STEPS = (0.5, 1, 2, 5, 10)`。
关掉磁吸时同一手势落在 9.967s，开着时吸到目标位——两条路都验过。
渲染用例 `gui_snap`：第一段末尾 1.0s，第二段吸到 `start = 1.0`，严丝合缝。

## 5. 裁剪（边缘）

左边缘 10 → 12：start 12.0、duration 8.0、`source.start` 同步 2.0（源起点跟着走）。
右边缘 20 → 18：start 不动、duration 6.0。最短时长 0.05s 由交互层兜住。
极窄片段（0.04s，视觉宽 3.2px）的**命中区被撑宽到 16px**，整体按 body 处理，
所以窄片段能被移动而不是永远只能裁剪。

## 6. 落位策略（AssetPlacementPolicy）

`gui/asset_placement.py` 是唯一的落位来源：视频→V1（占用则顺延 V2/V3/V4）、
图片→V3、overlay→V4、音乐→A1、语音（含 tts）→A2、音效→A3、字幕→T1、文字→T2。
GUI 里没有第二处硬编码轨道名。鼠标悬在某条轨上时**尊重用户**，
只在 kind 不匹配时拒绝，并在状态栏说明「该放哪」。

## 7. 九条轨道 × 元素类型矩阵

9 条轨道 × {视频素材, 音频素材, 字幕模板} 的合法性判定全部符合预期
（audio 只在 audio 轨合法，video 只在 video 轨合法）。
再跑一遍**真实落地**：9 条轨道各落一个对应元素，共 9 个元素，
每个都落在自己那条轨上。证据：`logs/gui_drag.json` → `matrix` / `landed`。

## 8. 明确拒绝，不静默失败

音频拖到 V1：`preview_valid = false`、`move_accepted = false`（明确 ignore）、
状态栏给出原因「音频只能放到 audio 轨，V1 是 video 轨」、**不落库**。
锁定轨道同理：原因是「V1 已锁定」。删除走 GUI 删除入口，元素数归 0。

## 9. 缩放档位与滚动

档位 25 / 50 / 75 / 100 / 150 / 200 / 400 / 800%，Ctrl+滚轮以**鼠标处时间为锚**。
滚动优先走真实滚动条；内容宽度不够时退回设置视图偏移，日志如实记录走了哪条路
（`scroll.path` = scrollbar / view），不把「没滚动」说成「滚动过」。

## 10. 播放器与播放头

播放 / 暂停、逐帧前后、跳首尾、时间码 `00:00:12.500`、进度条、音量与静音。
播放头 Player ↔ Timeline 双向同步（拖进度条动播放头，拖播放头动预览）。
**音量与静音是导出音量**：写进 `meta.master_volume`，控件上明确标注
「导出音量（预览无声）」——预览通道本身没有音频输出，见第 17 节。

## 11. 标记（兼容扩展）

标记写在 `meta.markers`，类型 normal / highlight / transition / caption / sfx /
ai_highlight。默认（空列表）时**整个键不出现**，v1/v2 schema 都显式允许它，
Remotion 侧忽略它——所以这是兼容扩展，不是 schema 破坏。
快捷键 M / Shift+M / Ctrl+← / Ctrl+→，另有「标记」菜单。
画布上旗杆压在标记时间上（旗面朝右），磁吸把标记当目标之一。

## 12. 画面比例与分辨率

`core/resolution.py` 是唯一真相源：3:4 = 810×1080 / 1080×1440 / 1440×1920，
9:16 = 720×1280 / 1080×1920 / 1440×2560。链路
GUI 比例下拉 → `meta.width/height` → Remotion Composition → MP4 → ffprobe 全程贯通，
真实渲染核对见 `reports/FINAL_RENDER_MATRIX.md`。

**本轮发现并修掉的一个真 bug**：`ProjectSettingsDialog._reload_resolutions` 原来用
`QComboBox.findData((w, h))` 找当前档位。Qt 对「Python 对象」型 data 只按**对象同一性**
比较，等值但不同对象的元组一律找不到，于是打开一个 1080×1440 的项目时下拉停在
第一档 810×1080，用户什么都没改、只点一下确定，分辨率就被悄悄换掉了。
现在改成按值比较（`_index_of_resolution`），并在验收里加了回归点：
改完分辨率后**重开一次对话框**，下拉必须停在同一档。

## 13. 素材库 / 特效库 / 转场库 / 音效库

素材库条目带缩略图、文件名、时长、分辨率、fps、格式；音频显示波形。
转场库从**真实源码**扫出来（11 个：fade / crossfade / flash / whip / zoom /
wipe / slide / push / spin / blur / glitch），不是手写清单。
音效库把「系统支持的音效类型」（13 类）与「本地实际存在的文件」（240 个，缺失 0）
分开列：支持但本地没文件的类型显示「本地暂无文件（类型受支持）」，
不虚构本地文件。目录文档由 `tools/build_catalog.py` 生成，`--check` 能查漂移。

## 14. GUI 每一步都进 JSON

Timeline JSON 是**剪辑意图**，AI 永远不产出 TSX。JSON Inspector 支持「只看选中」，
显示的是稀疏后的元素本体，被省略的字段列在摘要行里（不污染 JSON 正文）。
撤销 / 重做作用在 TimelineModel 上，覆盖拖动 / 裁剪 / 落位 / 属性修改 / 标记 / 全局音量。

## 15. 稀疏 JSON 与往返

GUI 拖出一个视频片段后，元素键只有
`asset / duration / id / source / start / track / type`——省略的都是 Runtime 默认值。
编辑器里 9 条轨道，导出的 JSON 只保留真正用到的轨道（`tracks = ["V1"]`）。
读进去再导出**逐字节一致**（`roundtrip_stable = true`），校验 0 error。
连续存取 ×5 不漂移，只读操作不污染工程（`gui_roundtrip.json`）。

## 16. DPI 复核

Qt 的缩放倍率只能在 QApplication 建立前定，所以 125% / 150% / 175% 各起一个进程，
每次跑坐标相关的 4 组用例（落点 / 拖动 / 磁吸 / 裁剪），三轮全 PASS。
日志：`logs/gui_drag_dpi_1_25.json`、`gui_drag_dpi_1_5.json`、`gui_drag_dpi_1_75.json`。

## 17. 没能自动化的部分（如实列出）

1. **预览没有音频输出通道**。预览是逐帧合成的图像，不解码播放音频。
   所以播放器上的音量 / 静音**只作用于导出**（`meta.master_volume`），
   控件文案已如实标注。音量真的生效由渲染后的响度对比证明
   （同一份时间线只改 `master_volume`，实测响度差见 `FINAL_RENDER_MATRIX.md`），
   而不是靠「听一下」。
2. **真人手感（拖动是否顺滑、吸附是否"舒服"）无法自动判定**。
   能自动化的是数字：落点误差、吸附目标、时长守恒、帧对齐，本报告全部给了数值。
3. **DPI 只覆盖 125 / 150 / 175%**，且是 `QT_SCALE_FACTOR` 模拟，
   不等于在真实高分屏物理设备上运行。
4. **拖动过程绝不触发重活**：拖动只走坐标换算与命中测试，
   不调 FFmpeg、不解码、不起 Remotion、不碰 AI。这一点由代码路径保证
   （交互层不持有解码器/渲染器引用），没有做「拖动时的 CPU 采样」这类性能实测。
