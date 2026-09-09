from __future__ import annotations

import random
from sqlalchemy.orm import Session

from app.models.tables import RiskControlRule


def parse_keywords(value: str | list | tuple | None) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value or "").replace("，", ",").replace(";", ",").replace("\n", ",").split(",")
    keywords: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        keyword = " ".join(str(item or "").split())
        lowered = keyword.casefold()
        if keyword and lowered not in seen:
            keywords.append(keyword)
            seen.add(lowered)
    return keywords


def match_risk_message(db: Session, prompts: list[str] | tuple[str, ...]) -> str | None:
    prompt_text = "\n".join(str(item or "") for item in prompts).casefold()
    if not prompt_text.strip():
        return None
    messages: list[str] = []
    rules = db.query(RiskControlRule).filter(RiskControlRule.status == "active").order_by(RiskControlRule.id.asc()).all()
    for rule in rules:
        keywords = parse_keywords(rule.keywords)
        if not keywords:
            continue
        if any(keyword.casefold() in prompt_text for keyword in keywords):
            message = " ".join(str(rule.error_message or "").split())
            if message:
                messages.append(message)
    return random.choice(messages) if messages else None
