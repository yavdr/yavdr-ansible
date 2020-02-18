#!/usr/bin/env python
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

    serial:
        required: False
        default: True
        description:
          - return a list of serial connections which provide an address and an interrupt

    acpi_power_modes:
        required: False
        default: True
        description:
          - return a list of supported acpi power saving modes
notes:
   - requires python3-pyusb and python3-kmodpy
requirements: [ ]
author: "Alexander Grothe <seahawk1986@gmx.de>"
'''

EXAMPLES = '''
- name: get information about usb and pci hardware and loaded kernel modules
  hardware_facts:
    usb: True
    pci: True
    serial: True
    modules: True
    acpi_power_modes: True
- debug:
    var: usb
- debug:
    var: pci
- debug:
    var: modules
- debug:
    var: serial
- debug:
    var: gpus
- debug:
    var: acpi_power_modes
'''

import glob
import json
import os
import sys
import usb.core
from collections import namedtuple
from itertools import chain

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
    for device in chain(glob.glob('/sys/devices/pci*/*:*:*/'), glob.glob('/sys/devices/pci*/*:*:*/*:*:*/')):
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


def get_serial_data(name):
    """
    get the I/O and IRQ numbers for the serial port
    using the /sys/class/tty/ttyS<X>/ device nodes
    """
    with open(os.path.join(name, 'irq')) as f:
        irq = int(f.read().rstrip())
    with open(os.path.join(name, 'port')) as f:
        port = int(f.read().rstrip(), base=16)
    return port, irq

def get_serial_devices():
    devices = {}
    p = '/sys/class/tty/'
    for d in sorted(glob.glob(os.path.join(p, 'ttyS[0-9]*'))):
        port, irq = get_serial_data(d)
        if port and irq:
            # TODO: check if a serial receiver is attached
            devices[os.path.basename(d)] = {'port': '0x{:x}'.format(port), 'irq': irq}
    return devices


def list_acpi_power_modes():
    acpi_power_modes = []
    try:
        with open('/sys/power/state') as f:
            acpi_power_modes = [l for l in f.readline().split()]
    except IOError:
        pass
    return acpi_power_modes

arg_specs = {
    'usb': dict(default=True, type='bool', required=False),
    'pci': dict(default=True, type='bool', required=False),
    'modules': dict(default=True, type='bool', required=False),
    'gpus': dict(default=True, type='bool', required=False),
    'serial': dict(default=True, type='bool', required=False),
    'acpi_power_modes': dict(default=True, type='bool', required=False),
    }


def main():
    module = AnsibleModule(argument_spec=arg_specs, supports_check_mode=True,)
    collect_usb = module.params['usb']
    collect_pci = module.params['pci']
    collect_modules = module.params['modules']
    collect_gpus = module.params['gpus']
    collect_serial = module.params['serial']
    collect_acpi_power_modes = module.params['acpi_power_modes']

    usb_devices = []
    pci_devices = []
    modules = []
    gpus = []
    nvidia_detected = False
    intel_detected = False
    amd_detected = False
    virtualbox_detected = False
    serial_devices = []
    acpi_power_modes = []

    if collect_usb:
        usb_devices = format_device_list(usb.core.find(find_all=True))

    if collect_pci:
        pci_devices = format_device_list(get_pci_devices())

    if collect_modules:
        k = kmodpy.Kmod()
        modules = [m[0] for m in k.loaded()]

    if collect_gpus:
        gpus = format_gpu_device_list(get_pci_devices())
        nvidia_detected = any((True for gpu in gpus if gpu['VendorName'] == 'nvidia'))
        intel_detected = any((True for gpu in gpus if gpu['VendorName'] == 'intel'))
        amd_detected = any((True for gpu in gpus if gpu['VendorName'] == 'amd'))
        virtualbox_detected = any((True for gpu in gpus if gpu['VendorName'] == 'virtualbox'))

    if collect_serial:
        serial_devices = get_serial_devices()

    if collect_acpi_power_modes:
        acpi_power_modes = list_acpi_power_modes()

    data = {'usb': usb_devices,
            'pci': pci_devices,
            'modules': modules,
            'gpus': gpus,
            'serial': serial_devices,
            'acpi_power_modes': acpi_power_modes,
            'nvidia_detected': nvidia_detected,
            'intel_detected': intel_detected,
            'amd_detected': amd_detected,
            'virtualbox_detected': virtualbox_detected,
    }
    module.exit_json(changed=False, ansible_facts=data, msg=data)


if __name__ == '__main__':
    main()
