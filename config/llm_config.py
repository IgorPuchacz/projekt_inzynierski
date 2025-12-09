from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMProfile:
    """Konfiguracja dla konkretnego przypadku użycia LLM."""
    name: str
    system_prompt: str
    temperature: float
    max_tokens: int
    response_format: Optional[Dict[str, Any]] = None
    extra_payload: Dict[str, Any] = field(default_factory=dict)

    def apply_system_prompt(self, messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Dodaje system prompt na początku listy wiadomości"""
        messages_list = list(messages)
        if messages_list and (messages_list[0].get("role") == "system"):
            return messages_list
        return [{"role": "system", "content": self.system_prompt}, *messages_list]

    def build_payload(
            self,
            messages: Iterable[Dict[str, Any]],
            *,
            model: str,
            stream: bool = False,
            overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Tworzy payload kompatybilny z OpenAI/LM Studio."""
        payload: Dict[str, Any] = {
            "model": model,
            "messages": self.apply_system_prompt(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if self.response_format:
            payload["response_format"] = self.response_format
        if self.extra_payload:
            payload.update(self.extra_payload)
        if overrides:
            payload.update(overrides)
        return payload

PROCEDURE_EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["steps", "conditions", "exceptions", "notes", "deadlines", "submission_info"],
    "properties": {
        "steps": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "required": ["title", "description", "confidence"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "confidence": {"type": "number"}
                }
            }
        },
        "conditions": {"type": ["object", "null"]},
        "exceptions": {"type": ["object", "null"]},
        "notes": {"type": ["object", "null"]},
        "deadlines": {"type": ["array", "null"]},
        "submission_info": {"type": "object"}
    },
    "additionalProperties": False
}

RUNTIME_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["reply_to_user"],
    "properties": {
        "reply_to_user": {
            "type": "string",
            "description": "Treść odpowiedzi dla użytkownika w formacie Markdown."
        },
        "status": {
            "type": "string",
            "enum": ["ok", "brak_danych", "odmowa"],
            "description": "Status odpowiedzi."
        },
        "citations": {
            "type": "array",
            "description": "Lista źródeł użytych w odpowiedzi.",
            "items": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "url": {"type": "string"},
                    "quote": {"type": ["string", "null"]}
                }
            }
        },
        "downloads": {
            "type": "array",
            "description": "Lista plików do pobrania (PDF, docx).",
            "items": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "url": {"type": "string"}
                }
            }
        }
    },
    "additionalProperties": False
}



EXTRACTOR_PROFILE = LLMProfile(
    name="extractor",
    system_prompt=(
        "Jesteś ekstraktorem danych. Analizujesz HTML i wyciągasz strukturę procedury. "
        "Zwracasz wyłącznie JSON zgodny ze schematem `procedure_extraction`."
    ),
    temperature=0.0,
    max_tokens=8000,
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "procedure_extraction",
            "schema": PROCEDURE_EXTRACTION_SCHEMA,
        },
    },
)

RUNTIME_PROFILE = LLMProfile(
    name="runtime",
    system_prompt=(
        "Jesteś asystentem studenta Politechniki Gdańskiej. "
        "1. Odpowiadasz na podstawie dostarczonego kontekstu JSON. "
        "2. Twoja odpowiedź musi być w formacie JSON zawierającym pole 'reply_to_user'. "
        "3. W 'reply_to_user' używasz Markdown, piszesz zwięźle i po polsku. "
        "4. Jeśli korzystasz z fragmentów tekstu, dodaj je do listy 'citations'. "
    ),
    temperature=0.2,
    max_tokens=1024,
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "runtime_response",
            "schema": RUNTIME_RESPONSE_SCHEMA,
        },
    },
)

PROFILES: Dict[str, LLMProfile] = {
    p.name: p for p in [EXTRACTOR_PROFILE, RUNTIME_PROFILE]
}


def get_profile(name: str) -> LLMProfile:
    return PROFILES[name]



def convert_to_toon_format(context_data: Dict[str, Any]) -> str:
    """
    Convert context data to TOON (Token-Optimized Object Notation) format.
    """
    if not context_data:
        return "Brak kontekstu."

    if context_data.get("source_type") == "search_results":
        results = context_data.get("results", [])
        if not results:
            return "Brak wyników wyszukiwania."

        toon_lines = []
        for idx, result in enumerate(results, 1):
            breadcrumbs = result.get("title", [])
            if isinstance(breadcrumbs, list):
                breadcrumb_str = " > ".join(breadcrumbs) if breadcrumbs else "Brak tytułu"
            else:
                breadcrumb_str = str(breadcrumbs) if breadcrumbs else "Brak tytułu"

            score = result.get("score", 0.0)
            header = f"[{idx}] {breadcrumb_str} (score: {score:.2f})"

            text = result.get("text", "").strip()

            source = result.get("source", "")

            block = f"{header}\n{text}\nŹródło: {source}"
            toon_lines.append(block)

        return "\n\n".join(toon_lines)

    elif context_data.get("info"):
        return context_data["info"]
    elif context_data.get("error"):
        return f"Błąd: {context_data['error']}"
    else:
        return json.dumps(context_data, ensure_ascii=False, indent=2)


def build_runtime_messages(
        procedure_json: Dict[str, Any],
        question: str,
) -> List[Dict[str, str]]:
    """Tworzy prompt dla czatu na podstawie wiedzy."""

    context_str = convert_to_toon_format(procedure_json)

    user_content = (
        f"Oto wiedza o procedurze:\n{context_str}\n\n"
        f"Pytanie użytkownika: {question}\n\n"
        "Wygeneruj odpowiedź JSON zgodną ze schematem."
    )

    return [{"role": "user", "content": user_content}]


def parse_structured_response(content: str) -> Optional[Dict[str, Any]]:
    """Parses LLM answer (string JSON) to Python dictionary."""
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            return None

        if "reply_to_user" not in data:
            data["reply_to_user"] = "Przepraszam, wystąpił błąd formatowania odpowiedzi."

        if "citations" not in data:
            data["citations"] = []

        if "downloads" not in data:
            data["downloads"] = []

        return data
    except json.JSONDecodeError:
        logger.error(f"Failed to parse LLM JSON response. Content preview: {content[:100]}...")
        return None


def build_custom_payload(structured: Dict[str, Any]) -> Dict[str, Any]:
    """Converts runtime answer into Frontendu format (Rasa custom payload)."""

    custom = {
        "text": structured.get("reply_to_user", ""),
        "status": structured.get("status", "ok"),
    }

    citations = structured.get("citations", [])
    if citations:
        custom["sources"] = [
            {"title": c.get("title") or c.get("url"), "url": c.get("url")}
            for c in citations if c.get("url")
        ]

    downloads = structured.get("downloads", [])
    if downloads:
        custom["downloads"] = downloads

        if downloads[0].get("url"):
            custom["pdf_url"] = downloads[0]["url"]
            custom["pdf_title"] = downloads[0].get("title", "Pobierz plik")

    return custom