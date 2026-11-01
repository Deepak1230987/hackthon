import asyncio
import hashlib
import uuid

from sqlalchemy import exists, select, update

from app.db.models import Run, Sentence
from app.graph.deps import Deps
from app.graph.state import RunState
from app.providers.errors import ProviderUnavailable

CONCURRENCY = 3


def audio_path(model: str, voice: str, language: str, text: str) -> str:
    key = hashlib.sha256(f"{model}|{voice}|{language}|{text}".encode()).hexdigest()
    return f"audio/{key}.mp3"


async def _already_stored(path: str, deps: Deps) -> bool:
    async with deps.sessions() as session:
        return bool(await session.scalar(select(exists().where(Sentence.audio_path == path))))


async def tts(state: RunState, deps: Deps) -> None:
    """Audio sentence by sentence. Without it the citizen still has the text, so nothing fails."""
    run_id = state["run_id"]
    language = state["language"]
    settings = deps.settings
    sarvam = deps.gateway.sarvam
    async with deps.sessions() as session:
        sentences = (
            await session.scalars(
                select(Sentence)
                .where(
                    Sentence.run_id == uuid.UUID(run_id),
                    Sentence.language == language,
                    Sentence.guard_status == "passed",
                    Sentence.audio_path.is_(None),
                )
                .order_by(Sentence.ordinal)
            )
        ).all()

    semaphore = asyncio.Semaphore(CONCURRENCY)
    failure: list[str] = []

    async def one(sentence: Sentence) -> None:
        path = audio_path(
            settings.tts_model, settings.voice_for(language), language, sentence.translated_text
        )
        async with semaphore:
            if failure:
                return
            if not await _already_stored(path, deps):
                try:
                    audio = await sarvam.tts(sentence.translated_text, language)
                    await deps.storage.put(path, audio, "audio/mpeg")
                except ProviderUnavailable as exc:
                    failure.append(str(exc))
                    return
                async with deps.sessions() as session:
                    await session.execute(
                        update(Run)
                        .where(Run.id == uuid.UUID(run_id))
                        .values(sarvam_chars=Run.sarvam_chars + len(sentence.translated_text))
                    )
                    await session.commit()
            async with deps.sessions() as session:
                await session.execute(
                    update(Sentence).where(Sentence.id == sentence.id).values(audio_path=path)
                )
                await session.commit()
            await deps.events.emit(run_id, "sentence_ready", {"sentence_id": str(sentence.id)})

    await asyncio.gather(*(one(sentence) for sentence in sentences))
    if failure:
        await deps.events.emit(
            run_id, "failover", {"from": "sarvam", "to": "text only", "reason": failure[0]}
        )
