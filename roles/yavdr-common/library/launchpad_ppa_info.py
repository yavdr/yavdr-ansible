
#!/usr/bin/python
# Make coding more python3-ish, this is required for contributions to Ansible
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.module_utils.basic import AnsibleModule

from pathlib import Path
from urllib.request import urlretrieve
from launchpadlib.launchpad import Launchpad


def get_ppa_fingerprint(ppa_name: str) -> tuple[str, str, str]:
    cache_dir = Path.home() / "launchpadlib" / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    launchpad = Launchpad.login_anonymously('yavdr-ansible', 'production', cache_dir, version="devel")
    ppa_owner, ppa_name = ppa_name.removeprefix('ppa:').split('/')

    person = launchpad.people[ppa_owner]
    ppa = person.getPPAByName(name=ppa_name)
    return ppa_owner, ppa_name, ppa.lp_get_parameter('signing_key_fingerprint')

def get_signing_key_url(fingerprint: str) -> str:
    url = f"https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x{fingerprint}"
    return url


def run_module():
    module_args = dict(
        ppa=dict(type='str', required=True),
    )

    result = dict(
        changed=False,

    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    print(f"{module.params=}")
    ppa_input = module.params['ppa']

    try:
        owner, ppa_name, fingerprint = get_ppa_fingerprint(ppa_input)
    except Exception as e:
        module.fail_json(msg=str(e))

    result = {
        "changed": False,
        "owner": owner,
        "name": ppa_name,
        "signing_key_id": fingerprint,
        "signing_key_url": f"https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x{fingerprint}"
    }

    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()