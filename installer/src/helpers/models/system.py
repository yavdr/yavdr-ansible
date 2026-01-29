from enum import StrEnum
import re
from typing import Annotated
from zoneinfo import ZoneInfo
from pydantic import AfterValidator, BaseModel, Field, NonNegativeInt


class SystemConfig(BaseModel):
    shutdown: Annotated[str, Field(description="Shutdown command")] = "poweroff"


class WakeupEnum(StrEnum):
    ACPIWAKEUP = "acpiwakeup"
    STM32WAKEUP = "st32wakeup"


class GrubConfig(BaseModel):
    timeout: Annotated[
        NonNegativeInt, Field(description="Grub menu timeout. Set 0 to disable")
    ] = 0
    boot_options: str = "quiet splash"


class AnsibleConnection(StrEnum):
    LOCAL = "local"
    SSH = "ssh"


class SupportedFrontends(StrEnum):
    VDR = "vdr"


PPA_REGEX = re.compile(r"^(ppa:)?([a-zA-Z0-9-_.]+/[a-zA-Z0-9-_.]+)$")


def ppa_validator(v: str) -> str:
    if not PPA_REGEX.match(v):
        raise ValueError(f"'{v}' does not follow the scheme [ppa:]owner/ppa")
    return v


PPA = Annotated[str, AfterValidator(ppa_validator)]


def tz_validator(v: str) -> str:
    try:
        ZoneInfo(v)
    except Exception:
        raise ValueError("Invalid Timezone")
    return v


TimeZone = Annotated[
    str, AfterValidator(tz_validator), Field(description="Timezone like Europe/Berlin")
]


def language_pack_validator(v: str) -> str:
    if not v.startswith("language-pack-"):
        raise ValueError("invalid language pack name")
    return v


LanguagePack = Annotated[str, AfterValidator(language_pack_validator)]
