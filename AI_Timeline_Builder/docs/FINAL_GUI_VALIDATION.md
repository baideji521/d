# 最终 GUI 验收（阶段 8 收口）

一次性列出所有闸门与实跑结果。所有命令都可复跑，日志路径在每一行后面。

## 1. 闸门总表

- `python -m pytest tests/ -q` → **638 passed / 0 failed**（`logs/p8_pytest_final.txt`）
- `node --test src/lib/timeline.test.ts src/effects/registry.test.ts src/transitions/registry.test.ts`
  → **74 tests / 74 pass / 0 fail**（`logs/p8_nodetest.txt`）
- `node node_modules/typescript/bin/tsc --noEmit` → **0 error**（`logs/p8_tsc.txt`）
- GUI 冒烟 `python out/acceptance/gui_drag.py`（离屏）→ **10 组用例全 PASS**（`logs/gui_drag.json`）
- DPI 复核 125% / 150% / 175% → 每轮 5 组坐标用例，**三轮全 PASS**
  （`logs/gui_drag_dpi_1_25.json` / `_1_5.json` / `_1_75.json`）
- GUI 往返 `python out/acceptance/gui_roundtrip.py` → **4 组全 PASS**（`logs/gui_roundtrip.json`）
- JSON 校验：GUI 产出的 10 份渲染 JSON **validator error 全为空**
- v1 → v2 迁移：`core/migrations/migration_v1_v2.py` 由 pytest 覆盖，round trip 无损
- 稀疏往返：读进去再导出逐字节一致（`roundtrip_stable = true`），连续存取 ×5 不漂移
- 特效矩阵：14 个 program effect 全部真实渲染
- 转场矩阵：11 个转场全部真实渲染（与运行时注册表一一对应）
- 分辨率矩阵：1080×1440 / 1080×1920 / 810×1080 / 540×960 真实渲染并 ffprobe 核对
- 真实 MP4 + ffprobe + 音频探针 + 抽帧探针：见 `docs/FINAL_RENDER_MATRIX.md`
- 特征用例全量：`analyze.py final` → **PASS 155 / FAIL 0**（SKIPPED 11、NOT_IMPLEMENTED 2）
- 文档漂移检查：`python tools/build_catalog.py --check` 由 `tests/test_catalog.py` 守着

汇总机器可读：`out/acceptance/logs/regression.json`。

## 2. 本轮由验收发现的真 bug（已修）

### 2.1 程序会自己崩掉（0xC0000409）—— 用户报障，已定位并修复

现象：打开 GUI 什么都不动，程序自己消失；有时表现为「未响应」后被系统关掉。
Windows 事件日志里交替出现 `APPCRASH`（Qt5Widgets.dll，0xc0000005）与 `AppHang`。

根因（两条，同一后果）：抽帧线程 `FrameWorker(QThread)` 在 `PreviewRenderer` 构造时
就开始跑，而

1. 停线程只写在 `MainWindow.closeEvent` 里。「文件 → 退出」、`app.quit()`、
   任务栏结束这些路径**不经过** closeEvent → Qt 去销毁一个仍在运行的 QThread
   → 进程级 fastfail。
2. 即使走 closeEvent，`shutdown()` 只 `wait(1500)`，而线程可能正卡在一次
   最长 60 秒的 `ffmpeg` 子进程调用里 → 等不到就往下走 → 同样 fastfail。
   这解释了「有时崩、有时不崩」。

修法：

- `main.py`：把收尾挂到 `app.aboutToQuit`，**任何**退出路径都会停线程
- `render/preview_renderer.py`：`shutdown()` 幂等，先停 notify 定时器、
  杀子进程、`wait(5000)`，仍不结束才 `terminate()` 兜底；
  `FrameWorker.stop()` 顺手清空队列并取消正在跑的 ffmpeg
- `render/ffmpeg.py`：`subprocess.run` 换成可杀的 `Popen`（`_run()` + `cancel()`），
  退出时能立刻掐掉正在解码的子进程

回归：新增 `out/acceptance/exit_paths.py`，起子进程跑三条真实退出路径
（quit / close / busy=抽帧正忙时退出）并检查**进程退出码**，
`logs/exit_paths.json`。三条全 PASS；把修复临时关掉做过反向验证 ——
quit 与 busy 立刻变成 `3221226505`（0xC0000409），证明这个用例真的能抓住它。

**为什么之前的验收没发现**：GUI 验收全部离屏运行，且脚本自己显式
`window.close()` 后才退出，正好绕开了 `app.quit()` 这条路；
而崩溃只体现在**进程退出码**里，Python 层没有任何 traceback，
pytest 与 GUI 用例都看不见。现在这条闸门补上了。

### 2.2 项目设置对话框会悄悄改掉分辨率

`gui/dialogs/project_dialog.py` 的分辨率下拉原来用 `QComboBox.findData((w, h))`
定位当前档位。Qt 对 Python 对象型 data 只按**对象同一性**比较，等值元组匹配不上，
于是打开一个 1080×1440 的项目时下拉停在第一档 810×1080 ——
用户什么都没改、只点一下「确定」，分辨率就被悄悄换成 810×1080。

修法：新增 `_index_of_resolution()` 按值比较。
回归点加在 GUI 验收里（改完分辨率后**重开一次对话框**，下拉必须停在同一档），
`logs/gui_drag.json → resolution[*].reopen_resolution_label` 就是证据。


## 3. GUI 每一步都进 JSON 的实测清单

阶段 8 新增的 5 个渲染用例，每一步都是真实控件事件，产物在 `out/acceptance/json/`：

- `gui_res_3x4` / `gui_res_9x16`：真实「项目设置」对话框改比例与分辨率
  → `meta.width/height` = 1080×1440、1080×1920
- `gui_sfx`：音效拖到 A3 + 属性面板真实数字框改
  `volume = 0.6`、`fade.in = 0.05`、`fade.out = 0.1`
- `gui_master_volume`：预览面板真实音量滑块（松手提交）→ `meta.master_volume = 0.5`
- `demo_full_timeline`：一条时间线里同时出现 8 种元素类型
  （video / overlay / audio / caption / caption_group / text / effect / transition），
  跨 7 条轨道（V1 / V2 / V3 / A1 / A3 / T1 / T2），并带一个 `meta.markers` 标记

## 4. 明确的局限（不当成 PASS）

1. 预览通道**没有音频输出**，播放器上的音量 / 静音只作用于导出
   （`meta.master_volume`），控件文案已如实标注；音量生效由渲染后响度差
   6.0dB（理论 6.02dB）证明，不靠人耳。
2. 6 个预置分辨率里有 3 个（720×1280 / 1440×1920 / 1440×2560）**没有逐个渲染**，
   理由与替代验证写在 `docs/FINAL_RENDER_MATRIX.md` 第 4 节。
3. DPI 只覆盖 125 / 150 / 175%，且用 `QT_SCALE_FACTOR` 模拟，
   不等于真实高分屏物理设备。
4. 「拖动是否顺滑」这类手感无法自动判定；能自动化的数字（落点误差 0.0s、
   吸附目标、时长守恒、帧对齐）全部给了实测值。
5. 拖动过程不触发 FFmpeg / 解码 / Remotion / AI 由代码路径保证
   （交互层不持有解码器与渲染器引用），未做拖动时的 CPU 采样实测。
