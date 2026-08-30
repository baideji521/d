# GUI Timeline 交互坐标审计（阶段 7 起点）

审计范围：`gui/`（全部）、`core/timeline.py`、`core/timeline_model.py`、`core/time_utils.py`、`core/sparse.py`、`schemas/`、`remotion/`。
审计方式：只读源码，不做修改。结论按「事实 + 文件:行号」记录，推断部分明确标注。

关键事实先行：**所有时间↔像素的换算目前都只出现在 `gui/timeline_widget.py` 一个文件里**（`ViewState`），
`preview_widget.py` / `property_panel.py` / `json_panel.py` / `core/*` / `remotion/*` 都不含 `pixels_per_second`。
所以问题不是"多套坐标系互相打架"，而是：

1. 同一套公式被**复制**成了 5 处（下面第 13 问），改一处不会同步；
2. 换算本身正确，但**手势期间视图会被别的信号横向滚走**（第 17 问，真因之一）；
3. 拖放（drop）路径**完全不经过磁吸、没有任何落点预览**（第 9、11 问）；
4. 每一次 `mouseMoveEvent` 都直接写模型 + 全量校验 + 全量重绘（第 30 问相关，真因之二）。

---

## 1. Timeline 左边缘在哪里？

三块画布放在 `QAbstractScrollArea` 的 viewport 里，用 `QGridLayout` 排（`timeline_widget.py:839-859`）：

```
(0,0) corner 168×26   (0,1) RulerCanvas
(1,0) HeaderCanvas    (1,1) TrackCanvas
(2,0..1) 底部工具条
```

- 轨道内容的左边缘 = `TrackCanvas` 自己的 `x=0`。
- `HEADER_WIDTH = 168`（`:58`）只是布局里的一列宽度，**不参与坐标换算**——因为 `event.pos()` 是相对 `TrackCanvas` 的局部坐标，Qt 已经把 168 减掉了。
- 所以代码里没有 `+ HEADER_WIDTH` 的偏移，这一点是干净的。

## 2. 时间尺起点在哪里？

`RulerCanvas` 和 `TrackCanvas` 是同一列（column 1）里的两个控件，宽度一致、左边缘对齐，
两者共享同一个 `ViewState`（`:848-850`），所以 `x=0` 对应的时间在刻度与轨道上是同一个值：
`ViewState.time_for_x(0) = scroll_x / pps`。

## 3. 每秒多少像素？

`ViewState.pixels_per_second`，初值 `60.0`（`:112`），范围 `MIN_PPS=8.0` ~ `MAX_PPS=600.0`（`:62-63`）。

```python
def x_for_time(self, seconds):    return seconds * self.pixels_per_second - self.scroll_x   # :116
def time_for_x(self, x):          return max(0.0, (x + self.scroll_x) / self.pixels_per_second)  # :119
def width_for_duration(self, s):  return max(1.0, s * self.pixels_per_second)  # :122
```

问题：`time_for_x` 里的 `max(0.0, ...)` 把负时间钳成 0，所以 `x_to_time` 不是 `time_to_x` 的严格逆函数
（`x < scroll_x` 区间全部塌成 0），往返测试无法在负半轴上成立；`width_for_duration` 的 `max(1.0, ...)`
让 0 时长也占 1px，属于绘制兜底，但它同时被 `_element_rect()` 用于**命中判定**（第 8 问）。

## 4. Zoom 如何改变？

三条入口，各自独立写 `pixels_per_second`：

- 滑块：`_on_zoom_slider()`（`:966`），对数映射 `_slider_to_zoom()`（`:961`）；
- 按钮 / 快捷键：`zoom(factor)`（`:1026`），乘 1.25 / 0.8；
- `Ctrl + 滚轮`：`TrackCanvas.wheelEvent()`（`:767-780`），以鼠标位置为锚点，缩放后重算 `scroll_x`。

`zoom_to_fit()`（`:1033`）用 `available / duration`，其中 `available = canvas.width() - 20`（magic number 20）。
没有档位概念，也没有 `fit_selection`。滚轮缩放直接改 `ViewState` 后再 `zoomChanged` 通知外层同步滑块，
即"数据先变、UI 后追"，多处状态需要手工保持一致。

## 5. 横向滚动如何影响？

`horizontalScrollBar().valueChanged` → `_on_h_scroll()` → `self._view.scroll_x = float(value)`（`:1069`）。
滚动条范围由 `_sync_scrollbars()` 给：`range = content_width() - page`，
`content_width() = (max(duration,10) + 4.0) * pps`（`:405-407`，magic number 4.0 = 尾部留白秒数）。
`scrollContentsBy()` 被重写成只重绘、不做像素搬移（`:1081`），所以滚动只通过 `scroll_x` 生效，这一点是自洽的。

## 6. Track 高度在哪里定义？

`ROW_HEIGHT = 38`、`ROW_GAP = 2`（`:60-61`），行距 = 40px。轨道头与轨道内容各自用同一组常量算 top
（`:228`、`:412`、`:475`），没有第二套高度。

## 7. Y 坐标如何映射到 Track？

```python
def _track_at_y(self, y):
    index = int((y + self._view.scroll_y) // (ROW_HEIGHT + ROW_GAP))   # :415-420
    tracks = list(reversed(self._model.tracks()))                      # :399
```

- 轨道显示顺序是 `reversed(tracks)`（列表越靠后 = 越上层，`:399`），所以 index→track 必须经过这个反转，
  两处（`HeaderCanvas._track_at` `:294`、`TrackCanvas._track_at_y` `:415`）各写了一遍。
- `_row_top()` 用 `- int(scroll_y)`（取整），`_track_at_y()` 用 `+ scroll_y`（不取整）。
  当前 `scroll_y` 来自整数滚动条，两者数值相等，但这是**巧合**而不是约束。
- 越界时返回 `""`（空轨道 id），调用方要各自判空。

## 8. Element 的 X 坐标怎么算？

```python
def _element_rect(self, element):                     # :422-428
    x = self._view.x_for_time(element["start"])
    width = self._view.width_for_duration(element["duration"])
    return QRectF(x, top + 2, width, ROW_HEIGHT - 4)
```

命中判定直接用这个**视觉矩形**：`_element_at()` → `rect.contains(pos.x(), pos.y())`（`:430-440`）。
后果：

- 0.2s 的片段在 20px/s 下宽 4px，几乎点不到；
- `EDGE_GRAB = 6`（`:64`）在左右各占 6px，**宽度小于 12px 的片段没有"移动区"**，
  只要按下就一定被判成 trim_left / trim_right —— 与用户反馈的"鼠标在元素中间，拖动却从左边缘开始算"一致；
- 没有 hit rect / visual rect 之分。

## 9. Drop 到 Timeline 后 start 怎么计算？

```python
def dropEvent(self, event):                                   # :800-814
    track_id  = self._track_at_y(event.pos().y())
    drop_time = self._view.time_for_x(event.pos().x())
    self.itemDropped.emit(payload, track_id, drop_time)
```
→ `MainWindow._on_item_dropped()`：`start = max(0.0, round(float(time_seconds), 3))`（`main_window.py:476`）
→ `_add_asset_element()` 用 `tl.make_video(..., start, 0.0, source_end)`（`main_window.py:495-529`）
→ `TimelineModel.add_element()`。

结论：**语义已经是"左边缘对准鼠标"**（符合第六条要求），但：

- `dropEvent` 里没有任何磁吸调用，`_snap_time()` 只服务于已有片段的 move/trim；
- `dragEnterEvent` / `dragMoveEvent` 只做 `acceptProposedAction()`（`:792-798`），
  既不高亮目标轨道，也不画 ghost，松手前用户拿不到任何反馈；
- 素材面板发起 QDrag 时 `drag.setPixmap(icon.pixmap(104×68))` 且**没有 `setHotSpot`**（`asset_panel.py:66-71`），
  默认热点 (0,0) 会让缩略图从光标向右下铺开，正好盖住落点附近的刻度；
- `round(..., 3)` 之后模型里还会再做一次 `snap_to_frame`（见第 11 问），两级量化叠加。

## 10. 拖动 Element 时 offset 怎么计算？

按下时记 `_drag_origin = event.pos()`、`_drag_start_time = element["start"]`（`:640-644`），
移动时 `delta_seconds = (pos.x() - _drag_origin.x()) / pps`，`new_start = _drag_start_time + delta`（`:664-669`）。

这等价于 `grab_offset = mouse_time - element.start` 并保持不变，**语义是对的**（符合第七条要求）。
但整个 offset 依赖 `_drag_origin` 与后续 `event.pos()` 处在**同一个 `scroll_x` 下**——见第 17 问，这个前提当前会被破坏。

## 11. Snap 在哪个阶段发生？

三级，且互不知情：

1. GUI 磁吸：`_snap_time()` / `_snap_move()`（`:356-390`），容差 `SNAP_PIXELS=8 / pps`（`:361`），
   目标只有 `0.0`、播放头、其它元素的首尾（`_snap_targets()` `:345-354`）。没有中心点、没有刻度、没有 marker。
2. 模型帧对齐：`move_element()` / `resize_element()` 内部 `snap_to_frame(new_start, fps)`（`timeline_model.py:468`、`:496`），
   `time_utils.snap_to_frame` = `round(round(s*fps)/fps, 6)`（`time_utils.py:22-24`）。
3. DSL 毫秒量化：写 JSON 时 `core/timeline.py` 把时间 round 到 3 位（既有约束，阶段 6.5 已记录）。

drop 路径只经过 2、3，跳过 1。

## 12. Preview 与 Timeline 是否使用不同坐标？

不是。`gui/preview_widget.py` 里没有任何 `pixels_per_second` / `x_for_time`（全仓库 grep 只命中 `timeline_widget.py`）。
预览只吃 `model.playhead`（秒）并渲染该时刻的一帧，因此不存在第二套时间→像素映射，
也就不存在"Timeline 与 Preview 对不上"的坐标分叉。

## 13. 是否存在重复的时间→像素转换公式？

有，`seconds * pixels_per_second` 这一形式在 `ViewState` 之外被**手写了 4 次**：

- `wheelEvent`：`anchor_time * pps - event.pos().x()`（`:776`）
- `_ensure_playhead_visible`：`seconds * pps - left_margin`（`:1005`）
- `scroll_to_time`：`seconds * pps - canvas.width()/2`（`:1048`）
- `content_width`：`(duration + 4.0) * pps`（`:407`）

刻度步长选择的循环 `for step in (0.1, ... 60.0): if step * pps >= 62` 在 `RulerCanvas._paint`（`:147`）与
`TrackCanvas._paint_grid`（`:487`）里**逐字重复**，两份都写着 magic number 62。

## 14. 是否存在 magic number？

`62`（刻度密度阈值，×2 处）、`4.0`（内容尾部留白秒）、`0.02`（最小时长，`:672`/`:679`）、
`20`（fit 时的边距，`:1035`）、`26`（宽于 26px 才画文字，`:557`）、`2`/`4`（矩形内缩，`:428`）、
`0.1`/`0.85`（跟随播放头的左右边界比例，`:1001-1002`）、`3`（框选阈值，`:725`）、
`EDGE_GRAB=6`、`SNAP_PIXELS=8`。前几个没有名字，散在绘制与交互代码里。

## 15. DPI / Windows 缩放是否影响？

`main.py:68-71` 只做 `QApplication(sys.argv)`，**没有** `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps`。
Qt5 默认不缩放，于是逻辑像素 = 物理像素：

- 好处：鼠标坐标与绘制坐标天然同一单位，不会因为 1.25/1.5/1.75 产生偏移；
- 代价：在 125%~175% 的 Windows 11 上整个界面按物理像素显示，实际显示尺寸偏小（38px 行高在 150% 屏上约等于 25 逻辑像素的观感），
  片段更难点中——这属于"可用性受 DPI 影响"，不属于"坐标偏移"。

## 16. Qt devicePixelRatio 是否影响？

代码里没有一处读 `devicePixelRatio`，也没有把 `QPixmap` 当画布缓存（全部是 `QPainter` 直接画到控件）。
唯一涉及 pixmap 的是拖拽缩略图（`asset_panel.py:70`），它不参与坐标计算。
因此 DPR 不进入换算链；结合第 15 问，当前 DPR 恒为 1。

## 17. 滚动后 Drop 是否仍然准确？

换算本身与 `scroll_x` 无关地正确（`time_for_x` 已含 `+scroll_x`）。但存在一条**会在手势中途改变 `scroll_x`** 的路径：

```
TrackCanvas.mousePressEvent  (:632)  self._model.select(id)
        └─ TimelineModel.selectionChanged
                 └─ MainWindow._on_selection_changed  (main_window.py:448-451)
                          └─ timeline.scroll_to_time(element.start)   ← 改 scroll_x
```

`select()` 在 `:632` 被调用，而 `rect = self._element_rect(element)` 在 `:637` 才取——
即**先把视图滚走、再用新 `scroll_x` 算出的矩形去和旧的 `event.pos()` 比边缘**（`:647-652`）。
于是：点击片段中间可能被判成 trim；同时片段会在按下瞬间横向跳到视口中央，视觉上"跑掉了"。
这是本次报障"很难拖准"的第一真因，且**越是滚动过的位置、越靠视口边缘点击，跳动越明显**。

（`drop` 路径不经过 `select()`，所以 drop 的 `start` 数值是准的；不准的是"用户看不到会落在哪"。）

## 18. Zoom 后 Drop 是否仍然准确？

`time_for_x` 用当前 `pps`，缩放后仍然正确。两个附带问题：

- 绘制统一 `int(x)` 取整（`:164`、`:495`、`:591`），而 `_element_rect` 用浮点 `x`，
  于是在极大缩放（600px/s）下刻度线与片段左边缘可能差 1px；
- 极小缩放（8px/s）时 `SNAP_PIXELS=8` 折算成 1.0s 的时间容差，磁吸会"糊成一片"，
  但因为 drop 不走磁吸，用户感知不到；一旦给 drop 接上磁吸，必须同时给容差设时间上限。

---

## 真因小结（按影响排序）

1. **手势期间视图被 `selectionChanged → scroll_to_time` 横向滚走**，导致按下瞬间片段跳位、move/trim 误判（`main_window.py:448`）。
2. **每次 `mouseMoveEvent` 直接落库**：`move_element`/`resize_element` 各自 `_begin()` 深拷贝整条时间线做撤销快照并 `_commit(structural=True)`
   （`timeline_model.py:463-516`），`timelineChanged` 又触发 `json_panel.issue_map()` 全量 jsonschema + 规则校验
   （`main_window.py:443-446`）。一次拖动 = 几十次全量校验 + 几十条撤销记录 → 卡顿 + 撤销不可用。
3. **drop 全程零反馈**：无 ghost、无轨道高亮、无磁吸，缩略图还盖住落点（`timeline_widget.py:792-814`、`asset_panel.py:66-71`）。
4. **命中区 = 视觉区**，短片段点不到、也移不动（`:422-440` + `EDGE_GRAB`）。
5. **公式复制 5 份 + 一堆 magic number**，任何一处改动都不会传播到其它处。
6. `time_for_x` 的 `max(0.0, ...)` 让往返换算在负半轴不可逆，无法做 property-based 往返测试。

## 不动的边界（本阶段不碰）

- `core/timeline.py` / `core/timeline_model.py` 的公开 API 与语义、`core/sparse.py` 的省略规则、
  `schemas/*.json`、`remotion/**` 全部保持原样；GUI 只允许通过既有 `add_element / move_element / resize_element /
  set_element_field / select / set_playhead` 落库。
- `snap_to_frame` 的帧对齐与 DSL 的毫秒量化保持现状（阶段 6.5 已验收的行为）。
