from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator


@cache
def supported_locales() -> set[str]:
    SUPPORTED_LOCALES_FILE = Path("/usr/share/i18n/SUPPORTED")
    locales: set[str] = set()
    if SUPPORTED_LOCALES_FILE.exists():
        for line in SUPPORTED_LOCALES_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # locale name is the first whitespace-separated field
            locale = line.split()[0]
            locales.add(locale)
    return locales


def locale_validator(v: str) -> str:
    if v not in supported_locales():
        raise ValueError(f"Locale '{v}' is not listed in /usr/share/i18n/SUPPORTED")
    return v


Locale = Annotated[
    str,
    AfterValidator(locale_validator),
]
