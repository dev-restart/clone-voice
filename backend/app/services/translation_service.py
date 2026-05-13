import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import Settings


LANGUAGE_LABELS = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
}


@dataclass(frozen=True)
class TranslationResult:
    translations: dict[str, str]
    provider: str
    model: str


def build_translation_prompt(text: str, languages: list[str]) -> str:
    language_lines = [f'- "{code}": {LANGUAGE_LABELS.get(code, code)}' for code in languages]
    return (
        "Translate the source text for multilingual voice generation.\n"
        "Return only a compact JSON object where each key is the requested language code and each value is the translated text.\n"
        "Do not include markdown, explanations, or extra keys.\n\n"
        f"Source text:\n{text}\n\n"
        "Target languages:\n"
        + "\n".join(language_lines)
    )


def parse_translation_choices(content: str, languages: list[str]) -> dict[str, str]:
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise RuntimeError("Translation response did not contain JSON.")
    payload = json.loads(match.group(0), strict=False)
    if not isinstance(payload, dict):
        raise RuntimeError("Translation response JSON must be an object.")
    result: dict[str, str] = {}
    for code in languages:
        value = payload.get(code)
        if isinstance(value, str) and value.strip():
            result[code] = value.strip()
    if not result:
        raise RuntimeError("Translation response did not include any requested languages.")
    return result


class OpenAICompatibleTranslator:
    def __init__(self, settings: Settings):
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self.timeout = settings.llm_timeout_seconds

    def translate(self, text: str, languages: list[str]) -> TranslationResult:
        prompt = build_translation_prompt(text, languages)
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a precise translation engine for TTS scripts."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Translation provider is not reachable: {exc}") from exc
        content = payload["choices"][0]["message"]["content"]
        return TranslationResult(
            translations=parse_translation_choices(content, languages),
            provider="openai-compatible",
            model=self.model,
        )
