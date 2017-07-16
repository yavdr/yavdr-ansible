#!/usr/bin/env/python
# This Module collects the vendor- and device ids for USB- and PCI(e)-devices and currently loaded kernel modules.
DOCUMENTATION = '''
  ---
  module: hardware_facts
  short_description: collects facts for kernel modules, usb and pci devices
  description:
       - This Module collects the vendor- and device ids for USB- and PCI(e)-devices and
         currently loaded kernel modules.
  options:
      usb:
          required: False
          default: True
          description:
            - return a list of vendor- and device ids for usb devices in '04x:04x' notation

    pci:
        required: False
        default: True
        description:
          - return a list of vendor- and device ids for pci devices in '04x:04x' notation

    modules:
        required: False
        default: True
        description:
          - return a list of currently loaded kernel modules

    gpus:
        required: False
        default: True
        description:
          - return a list of devices of the pci gpu class (0x030000)
notes:
   - requres python-pyusb and python-kmodpy
requirements: [ ]
author: "Alexander Grothe <seahawk1986@gmx.de>"
'''

EXAMPLES = '''
- name: get information about usb and pci hardware and loaded kernel modules
  hardware_facts:
    usb: True
    pci: True
    modules: True
- debug:
    var: usb
- debug
    var: pci
- debug
    var: modules
- debug
    var: gpus
'''

import glob
import json
import os
import sys
import usb.core
from collections import namedtuple

import kmodpy
from ansible.module_utils.basic import *


PCIDevice = namedtuple("PCIDevice", 'idVendor idProduct idClass pciPath')

vendor_dict = {
    0x10de: 'nvidia',
    0x8086: 'intel',
    0x1002: 'amd',
    0x80ee: 'virtualbox',
    }

def get_pci_devices():
    for device in glob.glob('/sys/devices/pci*/*:*:*/*:*:*/'):
        try:
            with open(os.path.join(device, 'device')) as d:
                product_id = int(d.read().strip(), 16)
            with open(os.path.join(device, 'vendor')) as d:
                vendor_id = int(d.read().strip(), 16)
            with open(os.path.join(device, 'class')) as d:
                class_id = int(d.read().strip(), 16)
            yield PCIDevice(idVendor=vendor_id, idProduct=product_id, idClass=class_id, pciPath=device)
        except IOError:
            pass

def format_device_list(iterator):
    return ["{:04x}:{:04x}".format(d.idVendor, d.idProduct) for d in iterator]

def format_gpu_device_list(iterator):
    def get_entries(iterator):
        for d in iterator:
            if d.idClass == 0x030000:
                yield {"VendorName": vendor_dict.get(d.idVendor, "unknown"),
                       "VendorID": d.idVendor, "ProductID": d.idProduct}
    return [entry for entry in get_entries(iterator)]

arg_specs = {
    'usb': dict(default=True, type='bool', required=False),
    'pci': dict(default=True, type='bool', required=False),
    'modules': dict(default=True, type='bool', required=False),
    'gpus': dict(default=True, type='bool', required=False),
    }


def main():
    module = AnsibleModule(argument_spec=arg_specs, supports_check_mode=True,)
    collect_usb = module.params['usb']
    collect_pci = module.params['pci']
    collect_modules = module.params['modules']
    collect_gpus = module.params['gpus']
    if collect_usb:
        usb_devices = format_device_list(usb.core.find(find_all=True))
    else:
        usb_device = []
    if collect_pci:
        pci_devices = format_device_list(get_pci_devices())
    else:
        pci_devices = []
    if collect_modules:
        k = kmodpy.Kmod()
        modules = [m[0] for m in k.loaded()]
    else:
        modules = []
    if collect_gpus:
        gpus = format_gpu_device_list(get_pci_devices())
    else:
        gpus = []
    data = {'usb': usb_devices, 'pci': pci_devices, 'modules': modules, 'gpus': gpus}
    module.exit_json(changed=False, ansible_facts=data, msg=data)


if __name__ == '__main__':  
    main()
