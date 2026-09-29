"""JSON contract for OAIREGBOX Grok through a configured New API gateway."""
from app.services.model_capabilities import validate_grok


def build_payload(prompt, seconds, resolution, aspect_ratio, image_urls, model, reference_video_url=None):
    validate_grok(model, int(seconds), resolution, aspect_ratio, len(image_urls))
    if reference_video_url:
        raise ValueError("Grok 当前仅支持文生视频和图生视频")
    payload = {"model": model, "prompt": prompt, "seconds": str(int(seconds)),
               "resolution": resolution, "aspect_ratio": aspect_ratio}
    if len(image_urls) == 1:
        payload["image"] = image_urls[0]
    elif image_urls:
        payload["reference_images"] = list(image_urls)
    return payload
