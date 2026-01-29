from codecs import lookup
from pathlib import PosixPath
from typing import Annotated
from pydantic import BaseModel, Field, NonNegativeInt, AfterValidator

# default values
VDR_USER = "vdr"
VDR_GROUP = VDR_USER
VDR_UID = 666
VDR_GID = VDR_UID
VDR_HOME_DIR = PosixPath("/home/vdr")
VDR_ETC_DIR = PosixPath("/etc/vdr")
VDR_CONF_DIR = PosixPath("/var/lib/vdr")
VDR_REC_DIR = PosixPath("/srv/vdr/video")
VDR_HIDE_FIRST_RECORDING_LEVEL = False
VDR_SAFE_DIRNAMES = False
VDR_OVERRIDE_CHARSET = ""
VDR_INSTANCE_ID = 0


def vdr_plugin_validator(v: str) -> str:
    if not v.startswith("vdr-plugin-"):
        raise ValueError(f"'{v}' is not a vdr plugin name")
    return v


VDRPlugin = Annotated[str, AfterValidator(vdr_plugin_validator)]


def charset_validator(v: str) -> str:
    if len(v) > 0:
        try:
            lookup(v)
        except LookupError:
            raise ValueError("invalid charset")
    return v


ValidatedCharset = Annotated[
    str,
    AfterValidator(charset_validator),
]


class VDRConfig(BaseModel):
    user: str = Field(
        default=VDR_USER,
        min_length=1,
        max_length=32,
        description="Username of the VDR user",
    )

    group: str = Field(
        default=VDR_USER,
        min_length=1,
        max_length=32,
        description="Group name for the VDR user",
    )

    uid: NonNegativeInt = Field(default=VDR_UID, description="User-ID of the VDR user")

    gid: NonNegativeInt = Field(default=VDR_GID, description="Group-ID of the VDR user")

    home: PosixPath = Field(
        default=VDR_HOME_DIR, description="Home directory of the VDR user"
    )

    etc_confdir: PosixPath = Field(
        default=VDR_ETC_DIR,
        description="Config dir for VDR used by packages",
    )

    confdir: PosixPath = Field(default=VDR_CONF_DIR, description="CONFDIR of VDR")

    recdir: PosixPath = Field(default=VDR_REC_DIR, description="RECDIR of VDR")

    hide_first_recording_level: bool = Field(
        default=VDR_HIDE_FIRST_RECORDING_LEVEL,
        description="Enable the firstrecordinglevel patch functionality",
    )

    safe_dirnames: bool = Field(
        default=VDR_SAFE_DIRNAMES,
        description="Use escape characters in directory names (useful for windows clients and FAT/NTFS file systems)",
    )

    override_vdr_charset: ValidatedCharset = Field(
        default=VDR_OVERRIDE_CHARSET,
        description="Set the desired charset, e.g. 'ISO-8859-9'",
    )

    instance_id: NonNegativeInt = Field(
        default=VDR_INSTANCE_ID,
        description="Instance ID of the VDR '-i' in man 1 vdr",
    )
