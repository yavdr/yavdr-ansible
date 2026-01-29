import re
from typing import Annotated
from pydantic import AfterValidator, BaseModel, Field

from helpers.models.generic import NonEmptyString


HOSTNAME_REGEX = re.compile(
    r"^(?!-)[a-zA-Z0-9-]{1,63}(?<!-)(\.(?!-)[a-zA-Z0-9-]{1,63}(?<!-))*$"
)


def hostname_validator(v: str) -> str:
    if not HOSTNAME_REGEX.match(v):
        raise ValueError(f"'{v}' is not a valid hostname or local name.")
    return v


LocalHostname = Annotated[str, AfterValidator(hostname_validator)]


class NFSConfig(BaseModel):
    insecure: Annotated[
        bool, Field(description="Set NFS option 'insecure' - needed for MacOS")
    ] = False


class SambaConfig(BaseModel):
    workgroup: Annotated[
        NonEmptyString, Field(description="Name of the SAMBA Workgroup")
    ] = "YAVDR"
    windows_compatible: Annotated[
        bool | None,
        Field(
            description="Translate file and folder names to make then windows-compatible"
        ),
    ] = None
