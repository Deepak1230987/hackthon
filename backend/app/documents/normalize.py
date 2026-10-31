import re
import unicodedata

_DIGITS = {
    **{0x0966 + i: str(i) for i in range(10)},  # Devanagari
    **{0x09E6 + i: str(i) for i in range(10)},  # Bengali
}
_QUOTES = {
    **dict.fromkeys(map(ord, "“”„‟″"), '"'),
    **dict.fromkeys(map(ord, "‘’‚‛′"), "'"),
}
_ZERO_WIDTH = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD))

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_BENGALI = re.compile(r"[ঀ-৿]")
_LATIN = re.compile(r"[A-Za-z]")
_MARATHI_WORDS = re.compile(r"(?<!\S)(आहे|आहेत|आणि|करण्यात|यांनी|यांच्या|नाही|करावे)(?!\S)")
_HINDI_WORDS = re.compile(r"(?<!\S)(है|हैं|और|के|का|की|में|से|नहीं|किया)(?!\S)")


def normalize(text: str) -> str:
    """The form used for every verification comparison. The UI shows the original text."""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_DIGITS).translate(_QUOTES).translate(_ZERO_WIDTH)
    return " ".join(text.split()).casefold()


def detect_language(text: str) -> str:
    devanagari = len(_DEVANAGARI.findall(text))
    bengali = len(_BENGALI.findall(text))
    latin = len(_LATIN.findall(text))
    if bengali > devanagari and bengali > latin:
        return "bn"
    if devanagari > latin:
        marathi = len(_MARATHI_WORDS.findall(text))
        return "mr" if marathi > len(_HINDI_WORDS.findall(text)) else "hi"
    return "en"
