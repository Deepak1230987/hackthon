from pathlib import Path

_HERE = Path(__file__).parent


def load(name: str) -> str:
    return (_HERE / f"{name}.md").read_text(encoding="utf-8")


def as_data(text: str) -> str:
    """Stop document text from closing the tag it's wrapped in and posing as instructions."""
    return text.replace("</", "< /")
