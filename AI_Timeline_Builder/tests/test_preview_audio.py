"""预览音频混音的单元测试。

这里测的是 `render/preview_audio.py` 里的**纯函数**：哪些元素该出声、
音量怎么算、ffmpeg 滤镜链怎么拼。不需要 Qt，也不需要真的跑 ffmpeg。

判定依据是 Remotion 侧的实现（`AudioLayer.tsx` / `VideoLayer.tsx`），
所以这些用例同时也是「预览和成片语义一致」的锁。
"""

from __future__ import annotations

from core import timeline as tl
from render import preview_audio as pa


def _resolve(asset_id: str) -> str:
    """假的素材路径解析：登记过的都给一个假路径。"""
    return f"C:/fake/{asset_id}.mp4"


def _timeline_with_audio() -> dict:
    data = tl.empty_timeline("音频测试", fps=30, width=540, height=960)
    data["elements"].append(
        tl.make_video("clip_001", "video_001", "V1", start=0.0, source_start=1.0, source_end=3.0)
    )
    data["elements"].append(
        tl.make_audio("audio_001", "bgm_001", "A1", start=0.0, duration=2.0, volume=0.4)
    )
    data["meta"]["duration"] = 2.0
    return data


def test_视频与音频都会出声():
    jobs = pa.audio_jobs(_timeline_with_audio(), _resolve)
    assert [job["element_id"] for job in jobs] == ["audio_001", "clip_001"]
    video = next(job for job in jobs if job["element_id"] == "clip_001")
    assert video["source_start"] == 1.0
    assert video["take"] == 2.0
    assert video["volume"] == 1.0


def test_文字字幕特效转场叠加层定格都不出声():
    data = tl.empty_timeline("只有画面", fps=30)
    data["elements"] = [
        tl.make_text("text_001", "hi", "T2", 0.0, 1.0),
        tl.make_caption("caption_001", "hi", "T1", 0.0, 1.0),
        tl.make_overlay("overlay_001", "overlay_001", "V3", 0.0, 1.0),
        tl.make_effect("effect_001", "zoom", "V1", 0.0, 1.0),
        tl.make_freeze("freeze_001", "clip_001", 0.5, 0.0, 1.0, "V1"),
    ]
    assert pa.audio_jobs(data, _resolve) == []


def test_audio_enabled_为假的视频被静音():
    data = _timeline_with_audio()
    clip = data["elements"][0]
    clip["audio"] = {"enabled": False}
    ids = [job["element_id"] for job in pa.audio_jobs(data, _resolve)]
    assert "clip_001" not in ids
    assert "audio_001" in ids


def test_元素音量为零不出声但不是错误():
    data = _timeline_with_audio()
    data["elements"][1]["volume"] = 0
    ids = [job["element_id"] for job in pa.audio_jobs(data, _resolve)]
    assert ids == ["clip_001"]


def test_master_volume_为零时整片静音():
    data = _timeline_with_audio()
    data["meta"]["master_volume"] = 0
    assert pa.audio_jobs(data, _resolve) == []


def test_master_volume_按乘法进入每一路():
    data = _timeline_with_audio()
    data["meta"]["master_volume"] = 0.5
    jobs = pa.audio_jobs(data, _resolve)
    bgm = next(job for job in jobs if job["element_id"] == "audio_001")
    assert bgm["volume"] == 0.2      # 0.4 × 0.5
    video = next(job for job in jobs if job["element_id"] == "clip_001")
    assert video["volume"] == 0.5    # 1.0 × 0.5


def test_master_volume_上限与_remotion_一致():
    data = _timeline_with_audio()
    data["meta"]["master_volume"] = 99
    jobs = pa.audio_jobs(data, _resolve)
    video = next(job for job in jobs if job["element_id"] == "clip_001")
    assert video["volume"] == pa.MASTER_VOLUME_CEILING


def test_master_volume_不是数字时按默认值():
    data = _timeline_with_audio()
    data["meta"]["master_volume"] = "loud"
    jobs = pa.audio_jobs(data, _resolve)
    video = next(job for job in jobs if job["element_id"] == "clip_001")
    assert video["volume"] == 1.0


def test_变速按倍率多取源长度():
    data = tl.empty_timeline("变速", fps=30)
    data["elements"].append(
        tl.make_video("clip_001", "video_001", "V1", start=0.0,
                      source_start=0.0, source_end=4.0, speed=2.0)
    )
    job = pa.audio_jobs(data, _resolve)[0]
    assert job["speed"] == 2.0
    assert job["duration"] == 2.0
    assert job["take"] == 4.0        # 2 秒画面 × 2 倍速 = 4 秒源


def test_没有音轨的素材直接跳过():
    data = _timeline_with_audio()
    jobs = pa.audio_jobs(data, _resolve, has_audio=lambda aid: aid != "video_001")
    assert [job["element_id"] for job in jobs] == ["audio_001"]


def test_找不到文件的素材直接跳过():
    data = _timeline_with_audio()
    jobs = pa.audio_jobs(data, lambda aid: "" if aid == "bgm_001" else _resolve(aid))
    assert [job["element_id"] for job in jobs] == ["clip_001"]


def test_滤镜链把落点写成_adelay():
    data = _timeline_with_audio()
    data["elements"][1]["start"] = 0.5
    jobs = pa.audio_jobs(data, _resolve)
    graph = pa.build_filter_complex(jobs)
    assert "adelay=500:all=1" in graph


def test_滤镜链带淡入淡出():
    data = tl.empty_timeline("淡入淡出", fps=30)
    data["elements"].append(
        tl.make_audio("audio_001", "bgm_001", "A1", start=0.0, duration=4.0,
                      fade_in=0.5, fade_out=1.0)
    )
    graph = pa.build_filter_complex(pa.audio_jobs(data, _resolve))
    assert "afade=t=in:st=0:d=0.5000" in graph
    assert "afade=t=out:st=3.0000:d=1.0000" in graph


def test_混音不做归一化():
    """amix 默认 normalize=1 会把每一路除以路数，和 Remotion 的直接相加不符。"""
    graph = pa.build_filter_complex(pa.audio_jobs(_timeline_with_audio(), _resolve))
    assert "amix=inputs=2:normalize=0" in graph


def test_变速拆成多级_atempo():
    assert pa._atempo_chain(1.0) == []
    assert pa._atempo_chain(1.5) == ["atempo=1.500000"]
    chain = pa._atempo_chain(4.0)
    assert len(chain) == 2 and all(step.startswith("atempo=") for step in chain)


def test_极端倍率拆不出来时如实放弃变速():
    assert pa._atempo_chain(0.01) == []


def test_命令行没有音频时是空的():
    data = tl.empty_timeline("无声", fps=30)
    assert pa.mix_command("ffmpeg", pa.audio_jobs(data, _resolve), 2.0, "out.wav") == []


def test_命令行按路数给出多个输入():
    jobs = pa.audio_jobs(_timeline_with_audio(), _resolve)
    command = pa.mix_command("ffmpeg.exe", jobs, 2.0, "out.wav")
    assert command.count("-i") == 2
    assert command[-1] == "out.wav"
    assert "pcm_s16le" in command
    assert str(pa.MIX_SAMPLE_RATE) in command


def test_指纹只跟声音有关():
    data = _timeline_with_audio()
    base = pa.mix_signature(pa.audio_jobs(data, _resolve), 2.0)

    # 改画面位置不该触发重混
    data["elements"][0]["transform"] = {"x": 0.7}
    assert pa.mix_signature(pa.audio_jobs(data, _resolve), 2.0) == base

    # 改音量必须触发重混
    data["elements"][1]["volume"] = 0.9
    assert pa.mix_signature(pa.audio_jobs(data, _resolve), 2.0) != base
