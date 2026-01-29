import yaml
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from ruamel.yaml import YAML

from installer.models.config import yaVDRConfig

app = FastAPI()

HOST_VARS_PATH = Path("/home/alexander/yavdr-ansible/host_vars/localhost")


@app.get("/vars")
def get_vars():
    yaml = YAML(typ="safe")
    # Load YAML - TODO: string interpolation
    raw: dict[str, Any] = yaml.load(HOST_VARS_PATH) or {}

    # Validate what’s there (missing fields become None)
    model = yaVDRConfig(**raw)

    return {
        "schema": yaVDRConfig.model_json_schema(),
        "values": model.model_json_schema(),  # important: return only what is defined
    }


@app.post("/vars")
def update_vars(new_values: dict[str, Any]) -> dict[str, str]:
    model = yaVDRConfig(**new_values)

    # Do not inject undefined vars into YAML
    cleaned = model.model_dump(exclude_none=True)

    yaml.safe_dump(cleaned, open(HOST_VARS_PATH, "w"))

    return {"status": "updated"}
