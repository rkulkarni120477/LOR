"""AI-assisted authoring with human review.

Suggestions are drafted for outlines, objectives, summaries, quizzes, metadata, classification and
accessibility. A suggestion never changes an item by itself. A person must accept it, and the
person who requested it cannot be the one who accepts it.

Two generators:
  rules  deterministic, always available. The default, and the fallback for the model path.
  llm    Claude through the same Bedrock factory the agents use. Enabled with
         AI_AUTHORING_MODE=llm. If the model is unavailable or returns unusable output, the rules
         generator is used and the suggestion records that it fell back.
"""

import json
import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import AISuggestion, LearningObject, MetadataLOM, Vocabulary
from app.services import audit, taxonomy
from app.services.access import require_object
from app.services.rich_text import plain_text
from app.services.taxonomy import current_lom

KINDS = ("outline", "objectives", "summary", "quiz", "metadata", "classification", "accessibility")
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "before",
    "being",
    "between",
    "could",
    "every",
    "other",
    "should",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "under",
    "using",
    "where",
    "which",
    "while",
    "with",
    "would",
    "your",
    "learn",
    "learners",
    "will",
    "that",
    "from",
    "have",
    "into",
    "more",
    "than",
    "then",
    "when",
    "what",
    "were",
    "been",
    "does",
}
BLOOM_VERBS = ["Explain", "Apply", "Analyse", "Evaluate", "Describe"]
MAX_PAYLOAD_BYTES = 20_000


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 20]


def _headings(html: str) -> list[str]:
    return [
        plain_text(h).strip()
        for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.S | re.I)
        if plain_text(h).strip()
    ]


def _terms(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z-]{3,}", text.lower())
    counts = Counter(w for w in words if w not in STOPWORDS)
    return [w for w, _ in counts.most_common(limit)]


# --- context --------------------------------------------------------------------------------------


def build_context(session: Session, storage, lo: LearningObject) -> dict[str, Any]:
    meta = lo.metadata_record
    lom = (
        current_lom(meta) if meta is not None else {"title": lo.title, "keywords": [], "custom": {}}
    )
    html = ""
    if lo.kind == "rich_text":
        html = (lo.body or {}).get("html", "")
    elif lo.kind in {"quiz", "assessment"}:
        html = " ".join(q.get("prompt", "") for q in (lo.body or {}).get("questions", []))
    images = videos = images_without_alt = 0
    text = plain_text(html) if html else ""
    if lo.kind == "file" and lo.versions:
        latest = max(lo.versions, key=lambda v: v.version_number)
        if latest.content_type == "application/zip":
            text, images, videos, images_without_alt = _package_text(storage, latest.storage_key)
    if lo.kind == "rich_text":
        images = len(re.findall(r"<img\b", html, re.I))
        images_without_alt = len(re.findall(r"<img\b(?![^>]*\balt=)", html, re.I))
    description = lom.get("description") or ""
    return {
        "title": lo.title,
        "kind": lo.kind,
        "description": description,
        "keywords": list(lom.get("keywords") or []),
        "subject": lom.get("subject"),
        "learning_resource_type": lom.get("learning_resource_type"),
        "language": lom.get("language"),
        "text": (text or description)[:20_000],
        "headings": _headings(html) if html else [],
        "images": images,
        "images_without_alt": images_without_alt,
        "videos": videos,
        "alt_text_provided": lom.get("alt_text_provided"),
        "captions_provided": lom.get("captions_provided"),
    }


def _package_text(storage, key: str) -> tuple[str, int, int, int]:
    import io
    import zipfile

    try:
        data = storage.open(key).read()
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (FileNotFoundError, zipfile.BadZipFile, OSError):
        return "", 0, 0, 0
    names = archive.namelist()
    images = [
        n for n in names if n.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"))
    ]
    videos = [n for n in names if n.lower().endswith((".mp4", ".webm", ".mov"))]
    captions = {n.lower() for n in names if n.lower().endswith((".vtt", ".srt"))}
    text_parts: list[str] = []
    missing_alt = 0
    for name in names:
        if name.lower().endswith((".html", ".htm")) and len(text_parts) < 30:
            html = archive.read(name).decode("utf-8", "replace")[:200_000]
            text_parts.append(plain_text(html))
            missing_alt += len(re.findall(r"<img\b(?![^>]*\balt=)", html, re.I))
    archive.close()
    return " ".join(text_parts), len(images), len(videos) if not captions else 0, missing_alt


# --- rules generator -------------------------------------------------------------------------------  # noqa: E501


def rules(kind: str, ctx: dict[str, Any], vocabulary_subjects: list[str]) -> dict[str, Any]:
    text = ctx["text"]
    sentences = _sentences(text)
    terms = ctx["keywords"][:3] or _terms(text, 3) or [ctx["title"].lower()]
    if kind == "outline":
        sections = ctx["headings"] or [s[:70] for s in sentences[:6]] or [ctx["title"]]
        return {"sections": [f"{i + 1}. {s}" for i, s in enumerate(sections[:12])]}
    if kind == "objectives":
        objectives = [
            f"{BLOOM_VERBS[i % len(BLOOM_VERBS)]} {term}" for i, term in enumerate(terms[:5])
        ]
        return {
            "objectives": [
                f"By the end, learners will be able to {o[0].lower()}{o[1:]}." for o in objectives
            ]
        }
    if kind == "summary":
        summary = " ".join(sentences[:2])[:500] or ctx["description"] or ctx["title"]
        return {"summary": summary}
    if kind == "quiz":
        questions = []
        for i, sentence in enumerate(sentences[:3]):
            distractors = [s[:90] for j, s in enumerate(sentences) if j != i][:3]
            while len(distractors) < 3:
                distractors.append("None of the above")
            correct_index = i % 4
            options = distractors[:correct_index] + [sentence[:90]] + distractors[correct_index:]
            questions.append(
                {
                    "prompt": "Which statement from this material is correct?",
                    "type": "single_choice",
                    "options": options[:4],
                    "correct": correct_index,
                    "points": 1,
                    "explanation": "Taken from the material.",
                }
            )
        if not questions:
            raise ValidationFailure("there is not enough text to draft a quiz; add content first")
        return {"questions": questions}
    if kind == "metadata":
        proposed = {"keywords": ctx["keywords"] or _terms(text, 6)}
        if not ctx["description"]:
            proposed["description"] = " ".join(sentences[:2])[:500]
        guess = _resource_type_guess(text, ctx)
        if not ctx["learning_resource_type"] and guess:
            proposed["learning_resource_type"] = guess
        return proposed
    if kind == "classification":
        matched = [label for label in vocabulary_subjects if label.lower() in text.lower()]
        return {
            "subject": matched[0] if matched else None,
            "learning_resource_type": _resource_type_guess(text, ctx),
            "basis": "a controlled subject term appears in the text"
            if matched
            else "no controlled subject term appears in the text",
        }
    if kind == "accessibility":
        checks = [
            {
                "key": "alt_text",
                "passed": ctx["images"] == 0 or ctx["images_without_alt"] == 0,
                "detail": f"{ctx['images_without_alt']} of {ctx['images']} images lack alt text",
            },
            {
                "key": "captions",
                "passed": ctx["videos"] == 0,
                "detail": f"{ctx['videos']} video(s) without captions"
                if ctx["videos"]
                else "no uncaptioned video",
            },
            {
                "key": "headings",
                "passed": bool(ctx["headings"]) or len(sentences) < 4,
                "detail": "headings found"
                if ctx["headings"]
                else "no headings to structure the content",
            },
            {
                "key": "language",
                "passed": bool(ctx["language"]),
                "detail": "language is set" if ctx["language"] else "set a language",
            },
        ]
        return {
            "checks": checks,
            "alt_text_provided": True
            if ctx["images"] == 0 or ctx["images_without_alt"] == 0
            else None,
            "captions_provided": True if ctx["videos"] == 0 else None,
        }
    raise ValidationFailure("unknown suggestion kind")


def _resource_type_guess(text: str, ctx: dict[str, Any]) -> str | None:
    lowered = text.lower()
    if ctx["videos"] or "video" in lowered:
        return "video"
    if "quiz" in lowered or "question" in lowered:
        return "assessment"
    if ctx["kind"] == "rich_text":
        return "article"
    return "course" if text else None


# --- LLM generator ---------------------------------------------------------------------------------  # noqa: E501

LLM_SHAPES = {
    "outline": ("sections",),
    "objectives": ("objectives",),
    "summary": ("summary",),
    "quiz": ("questions",),
    "metadata": ("keywords",),
    "classification": ("subject",),
    "accessibility": ("checks",),
}


def llm(kind: str, ctx: dict[str, Any], settings: Settings) -> dict[str, Any]:
    from app.llm.bedrock import get_chat_model

    prompt = (
        f"You are helping an instructional designer. Task: draft a {kind} for this learning object.\n"  # noqa: E501
        "Return ONLY a JSON object. Do not invent facts that are not in the text.\n"
        f"Title: {ctx['title']}\nDescription: {ctx['description']}\nKeywords: {', '.join(ctx['keywords'])}\n"  # noqa: E501
        f"Text (truncated):\n{ctx['text'][:6000]}\n"
        f"Required keys: {', '.join(LLM_SHAPES[kind])}."
    )
    raw = str(get_chat_model(settings).invoke(prompt).content)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON in model output")
    data = json.loads(match.group(0))
    if any(key not in data for key in LLM_SHAPES[kind]):
        raise ValueError("model output is missing required keys")
    return data


def generate_payload(
    kind: str, ctx: dict[str, Any], settings: Settings, vocabulary_subjects: list[str]
) -> tuple[dict[str, Any], str]:
    if settings.ai_authoring_mode == "llm":
        try:
            return llm(kind, ctx, settings), "llm"
        except Exception:  # model unavailable, malformed output, or no credentials: fall back
            return rules(kind, ctx, vocabulary_subjects), "rules (fallback)"
    return rules(kind, ctx, vocabulary_subjects), "rules"


# --- requests and review ------------------------------------------------------------------------------  # noqa: E501


def request_suggestions(
    session: Session, storage, settings: Settings, actor: Principal, lo_id: str, kinds: list[str]
) -> list[AISuggestion]:
    require_object(session, lo_id, actor, "edit")
    lo = session.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    bad = [k for k in kinds if k not in KINDS]
    if bad or not kinds:
        raise ValidationFailure("unknown suggestion kind" if bad else "choose at least one kind")
    ctx = build_context(session, storage, lo)
    subjects = list(
        session.scalars(
            select(taxonomy.TaxonomyTerm.label)
            .join(Vocabulary, Vocabulary.name == taxonomy.TaxonomyTerm.scheme)
            .where(Vocabulary.name == "subject", taxonomy.TaxonomyTerm.status == "active")
        )
    )
    rows = []
    for kind in dict.fromkeys(kinds):
        payload, generator = generate_payload(kind, ctx, settings, subjects)
        if len(json.dumps(payload, default=str)) > MAX_PAYLOAD_BYTES:
            raise ValidationFailure("suggestion is too large")
        row = AISuggestion(
            lo_id=lo_id,
            kind=kind,
            payload=payload,
            generator=generator,
            status="pending",
            requested_by=actor.subject,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    audit.record(
        session,
        actor_subject=actor.subject,
        action="ai.suggest",
        entity_type="learning_object",
        entity_id=lo_id,
        details={"kinds": kinds},
    )
    session.commit()
    return rows


def get_suggestion(session: Session, suggestion_id: int) -> AISuggestion:
    row = session.get(AISuggestion, suggestion_id)
    if row is None:
        raise NotFoundError("suggestion not found")
    return row


def edit(
    session: Session, actor: Principal, suggestion_id: int, payload: dict[str, Any]
) -> AISuggestion:
    row = get_suggestion(session, suggestion_id)
    require_object(session, row.lo_id, actor, "edit")
    if row.status != "pending":
        raise ConflictError("only pending suggestions can be edited")
    if len(json.dumps(payload, default=str)) > MAX_PAYLOAD_BYTES:
        raise ValidationFailure("suggestion is too large")
    row.payload = payload
    row.edited = True
    session.commit()
    return row


def _apply(session: Session, actor: Principal, row: AISuggestion) -> str:
    """Applies an accepted suggestion. Returns 'applied', or 'note' when the item type cannot hold it."""  # noqa: E501
    from app.schemas.library import DraftIn, Question
    from app.schemas.lom import LOMMetadata
    from app.services import library as library_service
    from app.services import metadata as metadata_service

    lo = session.get(LearningObject, row.lo_id)
    payload = row.payload
    if row.kind in {"summary", "metadata", "classification", "accessibility"}:
        lom = current_lom(session.scalar(select(MetadataLOM).where(MetadataLOM.lo_id == lo.id)))
        if row.kind == "summary" and payload.get("summary"):
            lom["description"] = payload["summary"]
        if row.kind == "metadata":
            if payload.get("description"):
                lom["description"] = payload["description"]
            if payload.get("keywords"):
                lom["keywords"] = list(
                    dict.fromkeys([*lom.get("keywords", []), *payload["keywords"]])
                )
            if payload.get("learning_resource_type"):
                lom["learning_resource_type"] = payload["learning_resource_type"]
        if row.kind == "classification":
            if payload.get("subject"):
                lom["subject"] = payload["subject"]
            if payload.get("learning_resource_type"):
                lom["learning_resource_type"] = payload["learning_resource_type"]
        if row.kind == "accessibility":
            if payload.get("alt_text_provided") is not None:
                lom["alt_text_provided"] = payload["alt_text_provided"]
            if payload.get("captions_provided") is not None:
                lom["captions_provided"] = payload["captions_provided"]
        metadata_service.update_metadata(session, lo.id, LOMMetadata.model_validate(lom), actor)
        return "applied"
    # outline, objectives and quiz change the item's body, which only rich text and quizzes have.
    if row.kind in {"outline", "objectives"} and lo.kind == "rich_text":
        items = payload.get("sections") or payload.get("objectives") or []
        heading = "Outline" if row.kind == "outline" else "Learning objectives"
        html = (
            "<h2>"
            + heading
            + "</h2><ul>"
            + "".join(f"<li>{_escape(str(i))}</li>" for i in items)
            + "</ul>"
        )
        body_html = (lo.body or {}).get("html", "")
        library_service.save_draft(
            session, actor, lo.id, DraftIn(revision=lo.revision, html=body_html + html)
        )
        return "applied"
    if row.kind == "quiz" and lo.kind in {"quiz", "assessment"}:
        existing = list((lo.body or {}).get("questions", []))
        new = [Question.model_validate(q).model_dump() for q in payload.get("questions", [])]
        library_service.save_draft(
            session,
            actor,
            lo.id,
            DraftIn(
                revision=lo.revision, questions=[Question.model_validate(q) for q in existing + new]
            ),
        )
        return "applied"
    return "note"


def _escape(text: str) -> str:
    import html

    return html.escape(text, quote=True)


def decide(
    session: Session, actor: Principal, suggestion_id: int, decision: str, note: str | None
) -> AISuggestion:
    row = get_suggestion(session, suggestion_id)
    require_object(session, row.lo_id, actor, "edit")
    if row.status != "pending":
        raise ConflictError("this suggestion has already been decided")
    if decision == "accept":
        if actor.subject == row.requested_by:
            raise ValidationFailure(
                "a suggestion must be accepted by a second person, not the requester"
            )
        outcome = _apply(session, actor, row)
        row.status = "accepted"
        row.decision_note = (note or "") + (
            ""
            if outcome == "applied"
            else " [recorded only: this item type has no editable body for it]"
        )
    else:
        if not (note and note.strip()):
            raise ValidationFailure("a note is required when rejecting")
        row.status = "rejected"
        row.decision_note = note.strip()
    from datetime import UTC, datetime

    row.decided_by = actor.subject
    row.decided_at = datetime.now(UTC)
    audit.record(
        session,
        actor_subject=actor.subject,
        action=f"ai.{row.status}",
        entity_type="learning_object",
        entity_id=row.lo_id,
        details={
            "suggestion": row.id,
            "kind": row.kind,
            "generator": row.generator,
            "edited": row.edited,
        },
    )
    session.commit()
    return row
