import json
import logging
import subprocess
import sys

from pathlib import Path
from typing import Annotated
from pydantic import BaseModel, BeforeValidator, Field

# This has been implemented in the yavdr-frontend script

DRM_BASE_PATH = Path("/sys/class/drm/")


class Connector(BaseModel):
    drm_connector: str
    edid: str
    xrandr_connector: str


def falsy_to_none(x: Connector) -> Connector | None:
    return x or None


OptionalConnector = Annotated[Connector | None, BeforeValidator(falsy_to_none)]


class DRMData(BaseModel):
    ignored_outputs: list[str] = Field(default_factory=list)
    primary: OptionalConnector = None
    secondary: OptionalConnector = None


class DRMModel(BaseModel):
    drm: DRMData


def main() -> None:
    try:
        with open("/etc/ansible/facts.d/drm.fact") as json_fact:
            data = json.load(json_fact)
    except Exception as err:
        sys.exit(f"could not load '/etc/ansible/facts.d/drm.fact': {err}")
    try:
        logging.info(f"{data=}")
        drm_model = DRMModel(**data).drm
    except Exception as e:
        logging.exception(f"Invalid data: {e}")
        sys.exit(1)

    else:
        for connector in (drm_model.primary, drm_model.secondary):
            print(f"{connector=}")
            if connector:
                for e in DRM_BASE_PATH.glob(f"card*{connector.drm_connector}/status"):
                    if e.read_text().startswith("connected"):
                        subprocess.run(
                            [
                                "xrandr",
                                "-d",
                                ":0",
                                "--output",
                                connector.xrandr_connector,
                                "--auto",
                                "--primary",
                            ]
                        )


if __name__ == "__main__":
    main()
