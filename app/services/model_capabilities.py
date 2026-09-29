"""Shared creation capabilities; never infer upstream billing resolution from pixels."""
GROK_MODELS = ("grok-imagine-video", "grok-imagine-video-1.5-preview")
RATIOS = ("9:16", "16:9", "1:1")


def capabilities(provider: str, model: str, seconds: int = 10) -> dict:
    if provider == "oaire_grok":
        if model not in GROK_MODELS:
            raise ValueError("请选择支持的 Grok 模型")
        preview = model == GROK_MODELS[1]
        return {"resolutions": ["480p", "720p", *(["1080p"] if preview else [])],
                "ratios": list(RATIOS), "seconds": list(range(1, 16)),
                "default_seconds": 6, "default_resolution": "480p",
                "max_images": {"480p": 7 if preview else 1, "720p": 7 if preview else 1, "1080p": 1},
                "image_policy": "ratio"}
    return {"resolutions": ["720p"], "ratios": list(RATIOS[:2]),
            "seconds": [seconds], "default_seconds": seconds, "default_resolution": "720p",
            "max_images": {"720p": {"oaire_omni": 5, "flow_omni": 6, "veo_omni": 6}.get(provider, 1)},
            "image_policy": "readable" if provider in {"flow_omni", "oaire_omni"} else "legacy"}


def matches_ratio(width: int, height: int, ratio: str) -> bool:
    w, h = map(int, ratio.split(":"))
    return width > 0 and height > 0 and abs((width / height) / (w / h) - 1) <= 0.01


def requested_size(resolution: str, ratio: str) -> str:
    """Nominal dimensions for legacy displays; actual output comes from media probing."""
    short = int(resolution.removesuffix("p"))
    w, h = map(int, ratio.split(":"))
    return f"{round(short * w / min(w, h) / 2) * 2}x{round(short * h / min(w, h) / 2) * 2}"


def validate_grok(model: str, seconds: int, resolution: str, ratio: str, image_count: int = 0) -> dict:
    spec = capabilities("oaire_grok", model)
    if seconds not in spec["seconds"]:
        raise ValueError("Grok 时长必须为 1–15 秒整数")
    if resolution not in spec["resolutions"] or ratio not in spec["ratios"]:
        raise ValueError("当前模型不支持所选清晰度或画幅比例")
    maximum = spec["max_images"][resolution]
    if image_count > maximum:
        raise ValueError(f"当前模型 {resolution} 最多支持 {maximum} 张参考图，请调整素材")
    return spec
