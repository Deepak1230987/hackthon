from pydantic import BaseModel

from app.prompts import as_data, load

LANGUAGE_NAMES = {"hi": "Hindi", "bn": "Bengali", "mr": "Marathi"}


class TranslatedSentence(BaseModel):
    index: int
    text: str


class TranslationResult(BaseModel):
    translations: list[TranslatedSentence] = []


def translation_prompt(sentences: list[str], language: str) -> str:
    items = "\n".join(
        f'<sentence index="{index}">{as_data(text)}</sentence>'
        for index, text in enumerate(sentences)
    )
    return load("translate").replace("{language}", LANGUAGE_NAMES[language]).replace("{sentences}", items)
