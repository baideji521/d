"""导入剪映（JianYing / CapCut）的文本，转成本项目的字幕行。

支持三种来源，按扩展名和内容自动判断：

1. 剪映草稿 draft_content.json（Windows）/ draft_info.json（macOS）
   字幕文本在 materials.texts[]，时间在 type 为 "text" 的轨道 segments 里，
   target_timerange 的 start / duration 单位是**微秒**。
2. 剪映导出的 .srt 字幕（最稳，推荐；剪映里「导出 → 字幕文件」就能拿到）
3. 纯文本 .txt，一行一句，没有时间，按固定节奏顺排

新版剪映的 draft_content.json 有可能不是明文 JSON（加密/压缩），
这种情况解析会失败，本模块给出明确提示，让用户改走导出 SRT 的路子。

解析结果统一是这样的行列表（时间单位：秒）：
    [{"index": 1, "text": "第一句", "start": 0.0, "end": 3.0}, ...]
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

# 剪映时间单位：微秒
MICROS = 1_000_000.0

# 没有时间信息时（纯文本导入）每行的默认时长与间隔
DEFAULT_LINE_DURATION = 2.5
DEFAULT_LINE_GAP = 0.2

SUPPORTED_FILTER = (
    "剪映字幕来源 (*.json *.srt *.txt);;"
    "剪映草稿 (draft_content.json draft_info.json *.json);;"
    "SRT 字幕 (*.srt);;"
    "纯文本 (*.txt);;"
    "所有文件 (*.*)"
)


def _strip_markup(raw: str) -> str:
    """去掉剪映富文本里的标签与控制符，只留可朗读的文字。"""
    text = raw or ""
    # <font id=".." path="..">文字</font> 这类标签
    text = re.sub(r"<[^>]*>", "", text)
    # [[...]] / {{...}} 之类的占位标记
    text = re.sub(r"\[\[.*?\]\]|\{\{.*?\}\}", "", text)
    # 剪映的富文本有时用 \u0000 之类做分隔
    text = text.replace("\x00", "").replace("\r", "")
    return text.strip()


def _text_of_material(material: Dict[str, Any]) -> str:
    """取一条 text 素材的文字。

    content 字段有三种形态：纯字符串、JSON 字符串（含 "text" 键）、富文本标签串。
    """
    content = material.get("content")
    if isinstance(content, dict):
        return _strip_markup(str(content.get("text", "")))
    if isinstance(content, str):
        stripped = content.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict) and "text" in parsed:
                    return _strip_markup(str(parsed.get("text", "")))
            except (ValueError, TypeError):
                pass
        return _strip_markup(content)
    # 少数版本把文字放在 base_content / words 里
    for key in ("base_content", "text"):
        value = material.get(key)
        if isinstance(value, str) and value.strip():
            return _strip_markup(value)
    return ""


def parse_draft(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """解析剪映草稿 JSON，返回按时间排序的字幕行。"""
    materials = (data.get("materials") or {}).get("texts") or []
    text_by_id: Dict[str, str] = {}
    for material in materials:
        if not isinstance(material, dict):
            continue
        material_id = str(material.get("id", ""))
        if material_id:
            text_by_id[material_id] = _text_of_material(material)

    rows: List[Tuple[float, float, str]] = []
    for track in data.get("tracks") or []:
        if not isinstance(track, dict) or track.get("type") != "text":
            continue
        for segment in track.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            text = text_by_id.get(str(segment.get("material_id", "")), "")
            if not text:
                continue
            timerange = segment.get("target_timerange") or {}
            start = float(timerange.get("start", 0) or 0) / MICROS
            duration = float(timerange.get("duration", 0) or 0) / MICROS
            if duration <= 0:
                duration = DEFAULT_LINE_DURATION
            rows.append((round(start, 3), round(start + duration, 3), text))

    # 有些草稿只有 materials.texts、没挂在文本轨上，那就只能顺排
    if not rows and text_by_id:
        cursor = 0.0
        for text in text_by_id.values():
            if not text:
                continue
            rows.append((round(cursor, 3), round(cursor + DEFAULT_LINE_DURATION, 3), text))
            cursor += DEFAULT_LINE_DURATION + DEFAULT_LINE_GAP

    rows.sort(key=lambda item: item[0])
    return [
        {"index": i, "start": start, "end": end, "text": text}
        for i, (start, end, text) in enumerate(rows, start=1)
    ]


_SRT_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


def _srt_seconds(token: str) -> float:
    match = _SRT_TIME.search(token)
    if not match:
        return 0.0
    hours, minutes, seconds, millis = match.groups()
    return round(
        int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000.0,
        3,
    )


def parse_srt(content: str) -> List[Dict[str, Any]]:
    """解析 SRT。剪映导出的字幕就是这个格式，时间最准。"""
    rows: List[Dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        time_index = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                time_index = i
                break
        if time_index < 0:
            continue
        left, _, right = lines[time_index].partition("-->")
        start = _srt_seconds(left)
        end = _srt_seconds(right)
        text = _strip_markup(" ".join(lines[time_index + 1 :]))
        if not text:
            continue
        if end <= start:
            end = round(start + DEFAULT_LINE_DURATION, 3)
        rows.append({"index": len(rows) + 1, "start": start, "end": end, "text": text})
    return rows


def parse_plain(content: str) -> List[Dict[str, Any]]:
    """纯文本：一行一句，时间按固定节奏顺排。"""
    rows: List[Dict[str, Any]] = []
    cursor = 0.0
    for line in content.replace("\r\n", "\n").split("\n"):
        text = _strip_markup(line)
        if not text:
            continue
        rows.append(
            {
                "index": len(rows) + 1,
                "start": round(cursor, 3),
                "end": round(cursor + DEFAULT_LINE_DURATION, 3),
                "text": text,
            }
        )
        cursor += DEFAULT_LINE_DURATION + DEFAULT_LINE_GAP
    return rows


def parse_file(path: str) -> Tuple[List[Dict[str, Any]], str]:
    """按文件类型解析，返回 (字幕行, 说明/错误信息)。

    解析失败时返回空列表 + 中文原因，调用方直接把原因给用户看。
    """
    if not path or not os.path.isfile(path):
        return [], f"找不到文件：{path}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
    except OSError as exc:
        return [], f"读不了这个文件：{exc}"

    extension = os.path.splitext(path)[1].lower()
    if extension == ".srt":
        rows = parse_srt(content)
        return rows, "" if rows else "这个 SRT 里没解析出字幕行"

    if extension == ".json" or content.lstrip().startswith("{"):
        try:
            data = json.loads(content)
        except ValueError:
            return [], (
                "这个 JSON 读不出来（新版剪映的 draft_content.json 常常不是明文）。\n"
                "改个稳的做法：在剪映里「导出 → 字幕文件（SRT）」，再导入那个 .srt。"
            )
        if not isinstance(data, dict):
            return [], "JSON 结构不是剪映草稿的样子"
        rows = parse_draft(data)
        if rows:
            return rows, ""
        return [], (
            "草稿里没找到文本素材。确认这个项目里有字幕/文本，"
            "或者直接在剪映里导出 SRT 再导入。"
        )

    rows = parse_plain(content)
    return rows, "" if rows else "这个文本里没有可用的行"


def summarize(rows: List[Dict[str, Any]]) -> str:
    """给对话框显示的一句话概览。"""
    if not rows:
        return "没有解析到字幕行"
    total = rows[-1]["end"] - rows[0]["start"]
    chars = sum(len(row["text"]) for row in rows)
    return f"共 {len(rows)} 行，覆盖 {total:.2f} 秒，合计 {chars} 个字"
