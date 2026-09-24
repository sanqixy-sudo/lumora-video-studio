"""Available creation choices shared by administrators and the creation page."""
from sqlalchemy.orm import Session
from app.models.tables import ProviderKey
from app.services.provider_keys import PROVIDER_SECONDS, normalize_provider_name, provider_is_retired, model_id_for_seconds


def model_options(db: Session) -> list[dict]:
    options: list[dict] = []
    provider_keys = (
        db.query(ProviderKey)
        .filter(ProviderKey.status == "active")
        .order_by(ProviderKey.id.asc())
        .all()
    )
    for provider_key in provider_keys:
        provider_name = normalize_provider_name(provider_key.provider_name)
        if provider_is_retired(provider_name):
            continue
        seconds_values = PROVIDER_SECONDS.get(provider_name, ())
        for seconds in seconds_values:
            model_id = model_id_for_seconds(provider_key, seconds)
            if not model_id:
                continue
            options.append(
                {
                    "value": f"key:{provider_key.id}:{seconds}",
                    "provider_key_id": provider_key.id,
                    "provider_name": provider_name,
                    "provider_label": provider_key.name,
                    "seconds": seconds,
                    "model_id": model_id,
                    "label": f"{provider_key.name.strip()} · {model_id} · {'约 ' if provider_name in {'flow_omni', 'oaire_omni'} else ''}{seconds} 秒",
                }
            )
    return options

