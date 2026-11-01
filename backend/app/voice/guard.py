from typing import Literal

from pydantic import BaseModel

from app.claims import numbers
from app.prompts import as_data, load

MeaningLabel = Literal["SAME", "MINOR_DIFF", "CHANGED"]


class MeaningVerdict(BaseModel):
    index: int
    label: MeaningLabel


class MeaningResult(BaseModel):
    verdicts: list[MeaningVerdict] = []


def numbers_match(source: str, translated: str) -> bool:
    """Free, and it catches the mistake that costs a citizen most, so it runs first."""
    source_numbers = numbers.parse(source)
    translated_numbers = numbers.parse(translated)
    return numbers.is_subset(source_numbers, translated_numbers) and numbers.is_subset(
        translated_numbers, source_numbers
    )


def meaning_prompt(pairs: list[tuple[str, str]]) -> str:
    items = "\n".join(
        f'<pair index="{index}">\n<english>{as_data(source)}</english>\n'
        f"<translation>{as_data(translated)}</translation>\n</pair>"
        for index, (source, translated) in enumerate(pairs)
    )
    return load("meaning").replace("{pairs}", items)
