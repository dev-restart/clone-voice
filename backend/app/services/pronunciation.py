"""Deterministic, language-scoped aliases applied only to synthesis text."""

import re
import unicodedata

from app.schemas import PronunciationRule


def apply_pronunciations(text: str, rules: list[PronunciationRule], language: str) -> str:
    # A language-specific entry takes precedence over an all-language entry.
    entries = {rule.source: rule.replacement for rule in rules if rule.language == "all"}
    entries.update({rule.source: rule.replacement for rule in rules if rule.language == language})
    if not entries:
        return text
    alternatives = []
    for source in sorted(entries, key=len, reverse=True):
        start = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", source[0]) else ""
        end = r"(?![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", source[-1]) else ""
        alternatives.append(f"{start}{re.escape(source)}{end}")
    pattern = re.compile("|".join(alternatives))
    # Preserve inline direction tags; replace in one pass so aliases never cascade.
    parts = re.split(r"(\[[^\]\n]*\])", unicodedata.normalize("NFC", text))
    return "".join(
        part if index % 2 else pattern.sub(lambda match: entries[match.group()], part)
        for index, part in enumerate(parts)
    )


def preview_excerpt(text: str, limit: int = 160) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    excerpt = cleaned[:limit]
    boundaries = list(re.finditer(r"[.!?。！？](?:\s|$)|\n", excerpt))
    if boundaries:
        return excerpt[:boundaries[-1].end()].strip()
    last_space = excerpt.rfind(" ")
    return excerpt[:last_space].strip() if last_space > limit // 2 else excerpt
