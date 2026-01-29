import ansible_runner
from pprint import pprint

from helpers.models.config import yaVDRConfig


def get_vars():
    private_data_dir = "example-playbook/"
    inventory_file = "example-playbook/inventory/hosts"
    target_host = "localhost"

    result = ansible_runner.interface.get_inventory(
        action="host",
        inventories=[inventory_file],
        host=target_host,
        private_data_dir=private_data_dir,
        response_format="json",
    )

    pprint(f"{result[0]=}")
    print("*" * 100)
    # Die Hostvariablen sind im stdout enthalten
    cfg = yaVDRConfig(**result[0])
    pprint(cfg.model_dump())


def run_playbook():
    pass
