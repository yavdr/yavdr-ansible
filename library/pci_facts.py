#!/usr/bin/env python
# This module parses the output of lspci for detailed information about available (sub) devices.
DOCUMENTATION = '''
  ---
  module: pci_facts
  short_description: parses lspci output for detailed (sub) devices data
  description:
      - This module parses the output of lspci for detailed information about available (sub) devices.
      - returns a list with a dict for each device

notes:
    - requires lspci (package pciutils)

'''

EXAMPLES = '''
- name: get detailled pci device infos
  pci_facts:

- debug:
    var: pci_devices
'''


import argparse
import shlex
import subprocess
from collections import namedtuple

from ansible.module_utils.basic import *

def convert2hex(arg):
    arg = arg.strip('"')
    if arg:
        return int(arg, 16)
    else:
        return None

def parse_lspci_data():
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--revision', help='revision', type=convert2hex)
    parser.add_argument('-p', '--progif', help='proginf', type=convert2hex)
    parser.add_argument('slot')
    parser.add_argument('device_class', type=convert2hex)
    parser.add_argument('vendor_id', type=convert2hex)
    parser.add_argument('device_id', type=convert2hex)
    parser.add_argument('sub_vendor_id', type=convert2hex)
    parser.add_argument('sub_device_id', type=convert2hex)
    parser.add_argument('other', nargs='*', default=[])

    devices = []
    for line in subprocess.check_output(['lspci', '-nm'], universal_newlines=True).splitlines():
        args = parser.parse_args(args=shlex.split(line))
        devices.append(vars(args))
    return devices


def main():
    arg_specs = {}
    module = AnsibleModule(argument_spec=arg_specs, supports_check_mode=True,)
    try:
        pci_devices = parse_lspci_data()
    except:
        module.fail_json(msg="Something fatal happened")
    data = {'pci_devices': pci_devices}
    module.exit_json(changed=False, ansible_facts=data, msg=data)

if __name__ == '__main__':
    main()
