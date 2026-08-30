# CAPTION_SPEC —— 字幕与文字

实现在 `core/timeline.py`（`make_text` / `make_caption` / `make_caption_group`）、
`libraries/caption_library.py`（模板）与 `remotion/src` 的对应 Layer。

## 三种元素

- `text`：普通文字，放 `T2` 轨。`content.text` 是一段字符串。
- `caption`：整句字幕，放 `T1` 轨。带 `template` 与 `caption_style`。
- `caption_group`：逐词字幕，放 `T1` 轨。`content.words` 是词表，
  每个词 `{text, start, end}`，**时间是绝对时间线秒数**；
  元素自身的 `start` / `duration` 由首尾词推出（最短 0.04s）。

## 样式

`style` = `{fontFamily, fontSize, fontWeight, color, align, stroke:{width,color}}`。
`caption_group` 另有 `highlight` = `{color, backgroundColor, scale}`，
用来画「当前词」。

`caption_style` 决定播放方式，取值来自 `caption_library.CAPTION_STYLES`：
`plain` `word_by_word` `highlight_current` `karaoke` `char_by_char`
`bounce` `two_line`。

## 内置模板

`libraries/caption_library.py:BUILTIN_TEMPLATES`（8 个，按 `name` 索引）：
`bold_white` `highlight_yellow` `karaoke_green` `box_black`
`word_pop` `char_typing` `bounce_big` `two_line_split`。
GUI 里调好的样式可以存回 `assets/captions/`，自定义模板与内置同名时以自定义为准。

## 位置与安全区

字幕默认 `transform.y = 0.82`（贴下三分之一）。
元素上可写 `safe_area: true` 声明「我要待在安全区里」——
声明了就必须真的在区内，否则 `RULE_SAFE_AREA_001` 报错。
安全区档位从 `meta.safe_area.preset` 取，四边内缩不对称。

## 与配音的关系

`core/voice.py:words_to_caption_group()` 把配音的词时间轴转成 `caption_group`。
系统 SAPI 拿不到真实词级时间戳，所以那种时间轴标记为
`timing_source: "estimated"` —— **不允许**把估算说成引擎给的真值。
