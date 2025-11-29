#!/usr/bin/python3
DOCUMENTATION = '''
---
module: satip_facts
short_description: "check if at least one SAT>IP server responds on the network"
description:
     - This script sends a multicast message and awaits responses by Sat>IP servers.
       Returns a list of detected SAT>IP servers with their name and capabilites.
'''
EXAMPLES = '''
- name: "detect SAT>IP Server on the network"
  action: satip_facts

- ansible.builtin.debug:
    var: satip_devices
'''

import socket
import time
from typing import Any
import xml.etree.ElementTree as ET
import requests
from contextlib import contextmanager
from ansible.module_utils.basic import AnsibleModule

SSDP_BIND = "0.0.0.0"
SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
# SSDP_MX = max delay for server response
# a value of 2s is recommended by the SAT>IP specification 1.2.2
SSDP_MX = 2
SSDP_ST = "urn:ses-com:device:SatIPServer:1"

ssdpRequest = "\r\n".join((
    "M-SEARCH * HTTP/1.1",
    "HOST: %s:%d" % (SSDP_ADDR, SSDP_PORT),
    "MAN: \"ssdp:discover\"",
    "MX: %d" % (SSDP_MX),
    "ST: %s" % (SSDP_ST),
    "\r\n")).encode('utf-8')

@contextmanager
def socket_manager(family: socket.AddressFamily | int = -1,
    type: socket.SocketKind | int = -1,
    proto: int = -1,
    fileno: int | None = None):
    """provide a context manager for socket"""
    sock = socket.socket(family, type, proto, fileno)
    sock.setblocking(False)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except socket.error:
        pass
    sock.settimeout(SSDP_MX + 0.5)
    sock.bind((SSDP_BIND, SSDP_PORT))
    try:
        yield sock
    finally:
        sock.close()


def parse_satip_xml(data: str)-> dict[str, Any]:
    """ Parse SAT>IP XML data.
    Args:
        data (str): XML input data..
    Returns:
        dict: Parsed SAT>IP device name and frontend information.
    """
    result: dict[str, Any] = {'name': '', 'frontends': {}}
    if data:
        root = ET.fromstring(data)
        name = root.find('.//*/{urn:schemas-upnp-org:device-1-0}friendlyName')
        if name is None or name.text is None:
            raise ValueError("Invalid SAT>UP device name")
        result['name'] = name.text
        satipcap = root.find('.//*/{urn:ses-com:satip}X_SATIPCAP')
        if satipcap is None or satipcap.text is None:
            raise ValueError("Invalid SAT>IP device description")
        caps: dict[str, int] = {}
        for system in satipcap.text.split(","):
            cap = system.split("-")
            if cap:
                count = int(cap[1])
                if cap[0] in caps:
                    count: int = count + caps[cap[0]]
                caps[cap[0]] = count
        result['frontends'] = caps
    return result


def main():
    description_urls: list[str] = []
    device_list: list[dict[str, Any]] = []
    module = AnsibleModule(argument_spec={}, supports_check_mode=True,)
    with socket_manager(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        # according to Sat>IP Specification 1.2.2, p. 20
        # a client should send three requests within 100 ms with a ttl of 2

        for _ in range(3):
            sock.sendto(ssdpRequest, (SSDP_ADDR, SSDP_PORT))
            time.sleep(0.03)
        try:
            response = sock.recv(1024).decode()
            if response and "SERVER:" in response:
                for line in response.splitlines():
                    if "LOCATION" in line:
                        url = line.split()[-1].strip()
                        if url not in description_urls:
                            description_urls.append(url)
                            info = requests.get(url, timeout=2)
                            device_list.append(parse_satip_xml(info.text))
            else:
                raise ValueError('No satip server detected')
        except (socket.timeout, ValueError, ET.ParseError):
            pass

    module.exit_json(changed=False, ansible_facts={'satip_devices': device_list})

if __name__ == '__main__':
    main()
