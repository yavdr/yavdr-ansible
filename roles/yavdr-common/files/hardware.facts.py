#!/usr/bin/env python3
# This script returns a list of Vendor- and Product-IDs for all connected usb
# and pci(e) devices in json format
import glob
import json
import os
import sys
import usb.core
from collections import namedtuple


Device = namedtuple("Device", ['idVendor', 'idProduct'])

def get_pci_devices():
    for device in glob.glob('/sys/devices/pci*/*:*:*/'):
        with open(os.path.join(device, 'device')) as d:
            product_id = int(d.read().strip(), 16)
        with open(os.path.join(device, 'vendor')) as d:
            vendor_id = int(d.read().strip(), 16)
        yield Device(idVendor=vendor_id, idProduct=product_id)

def format_device_list(iterator):
    return ["{:04x}:{:04x}".format(d.idVendor, d.idProduct) for d in iterator]


if __name__ == '__main__':
    usb_devices = format_device_list(usb.core.find(find_all=True))
    pci_devices = format_device_list(get_pci_devices())
    print(json.dumps({'usb': usb_devices, 'pci': pci_devices}))
