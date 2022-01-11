#!/usr/bin/env python2
from __future__ import print_function
import ast
import binascii
import csv
import os
import re
import subprocess
from collections import namedtuple
from glob import glob

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = '''
---
module: xrandr_facts
short_description: "gather facts about connected monitors and available modelines"
description:
     - This module needs a running x-server on a given display in
       order to successfully call xrandr. Returns the dictionary
       "xrandr", wich contains all screens with output states,
       connected displays, EDID info and their modes and a
       recommendation for the best fitting tv mode, the dictionary
       "xorg" with a recommendation for the primary and secondary
       output and a "drm" dictionary whose "primary" key associates
       the primary device name of the drm subsystem with the one from
       the xrandr output by comparing the edid data and a list of
       "ignored_devices". Note that the proprietary nvidia driver
       doesn't support KMS/drm, so in this case the dictionary is
       always empty.
options:
    display:
        required: False
        default: ":0"
        description:
          - the DISPLAY variable to use when calling xrandr
    preferred_outputs:
        required: False
        default: ["HDMI", "DP", "eDP", "DVI", "VGA", "TV", "Virtual"]
        description:
          - ranking of the preferred display connectors
    preferred_refreshrates:
        required: False
        default: ["50", "60", "75", "30", "25"]
        description:
          - ranking of the preferred display refreshrate
    preferred_resolutions:
        required: False
        default: ["7680x4320", "3840x2160", "1920x1080", "1280x720", "720x576"]
        description:
           - ranking of the preferred display resolutions
    write_edids:
        required: False
        default: True
        description:
           - write edid data to /etc/X11/edid.{connector}.bin
           - the dictionary "drm" can only be filled with data if write_edids is enabled
'''
EXAMPLES = '''
- name: "collect facts for connected displays"
  action: xserver_facts
    display: ":0"

- debug:
    var: xrandr

- debug:
    var: xorg

- debug:
    var: drm
'''

ARG_SPECS = {
    'display': dict(default=":0", type='str', required=False),
    'preferred_outputs': dict(
        default=["HDMI", "DP", "eDP", "DVI", "VGA", "TV", "Virtual"],
        type='list', elements='str', required=False
    ),
    'preferred_refreshrates': dict(
        default=[50, 60, 75, 30, 25], type='list', elements='int', required=False),
    'preferred_resolutions': dict(
        default=[
            "7680x4320", "3840x2160", "1920x1080", "1280x720", "720x576"],
        type='list', elements='str', required=False),
    'write_edids': dict(default=True, type='bool', required=False),
}

SCREEN_REGEX = re.compile(r"^(?P<screen>Screen\s\d+:)(?:.*)")
CONNECTOR_REGEX = re.compile(
    r"^(?P<connector>.*-?\d+)\s(?P<connection_state>connected|disconnected)\s(?P<primary>primary)?")
MODE_REGEX = re.compile(r"^\s+(?P<resolution>\d{3,}x\d{3,}).*")

Mode = namedtuple('Mode', ['connection', 'resolution', 'refreshrate'])


def check_for_screen(line):
    """check line for screen information"""
    match = re.match(SCREEN_REGEX, line)
    if match:
        return match.groupdict()['screen']


def check_for_connection(line):
    """check line for connection name and state"""
    match = re.match(CONNECTOR_REGEX, line)
    connector = None
    is_connected = False
    if match:
        match = match.groupdict()
        connector = match['connector']
        is_connected = True if match['connection_state'] == 'connected' else False
    return connector, is_connected


def get_indentation(line):
    """return the number of leading whitespace characters"""
    return len(line) - len(line.lstrip())


def sort_mode(mode):
    """rate modes by several criteria"""
    connection_score = 0
    rrate_score = 0
    resolution_score = 0
    preferred_rrates = module.params['preferred_refreshrates']
    # [50, 60]
    preferred_resolutions = module.params['preferred_resolutions']
    # ["7680x4320", "3840x2160", "1920x1080", "1280x720", "720x576"]
    preferred_outputs = module.params['preferred_outputs']
    # ["HDMI", "DP", "DVI", "VGA"]
    if mode.refreshrate in preferred_rrates:
        rrate_score = len(preferred_rrates) - preferred_rrates.index(mode.refreshrate)
    if mode.resolution in preferred_resolutions:
        resolution_score = len(preferred_resolutions) - preferred_resolutions.index(mode.resolution)
    x_resolution, y_resolution = (int(n) for n in mode.resolution.split('x'))
    connection = mode.connection.split('-')[0]
    if connection in preferred_outputs:
        connection_score = len(preferred_outputs) - preferred_outputs.index(connection)
    return (rrate_score, resolution_score, x_resolution, y_resolution, connection_score)


def parse_xrandr_verbose(iterator):
    """parse the output of xrandr --verbose using an iterator delivering single lines"""
    xorg = {}
    is_connected = False
    for line in iterator:
        if line.startswith("Screen"):
            screen = check_for_screen(line)
            xorg[screen] = {}
        elif "connected" in line:
            connector, is_connected = check_for_connection(line)
            xorg[screen][connector] = {
                "is_connected": is_connected,
                "EDID": "",
                "modes": {},
                "modelines": {},
                "preferred": "",
                "current": "",
                "auto": "",
            }
        elif is_connected and "EDID:" in line:
            edid_str = ""
            outer_indentation = get_indentation(line)
            while True:
                line = next(iterator)
                if get_indentation(line) > outer_indentation:
                    edid_str += line.strip()
                else:
                    break
            xorg[screen][connector]["EDID"] = edid_str
        elif is_connected and "MHz" in line and "Interlace" not in line:
            match = re.match(MODE_REGEX, line)
            if match:
                match = match.groupdict()
                preferred = bool("+preferred" in line)
                current = bool("*current" in line)
                resolution, mode_num, pixel_clk, *flags = line.split()
                flags = [flag for flag in flags if flag not in ("*current", "+preferred")]
                pixel_clk = pixel_clk[:-3]

                while True:
                    line = next(iterator).strip()
                    if line.startswith("h:"):
                        _, _, h_width, _, h_start, _, h_end, _, h_total, _, h_skew, _, h_clock = (
                            line.split()
                        )
                        h_clock = h_clock[:-3]

                    if line.startswith("v:"):
                        _, _, v_height, _, v_start, _, v_end, _, v_total, _, v_clock = (
                            line.split()
                        )
                        refresh_rate = ast.literal_eval(v_clock[:-2])
                        rrate = int(round(refresh_rate))
                        if (
                            xorg[screen][connector]["modes"].get(match["resolution"])
                            is None
                        ):
                            xorg[screen][connector]["modes"][match["resolution"]] = []
                        if (
                            rrate
                            not in xorg[screen][connector]["modes"][match["resolution"]]
                        ):
                            xorg[screen][connector]["modes"][
                                match["resolution"]
                            ].append(rrate)
                        mode_name = f'{match["resolution"]}_{rrate}'
                        if preferred:
                            xorg[screen][connector]["preferred"] = mode_name
                        if current:
                            xorg[screen][connector]["current"] = mode_name
                        modeline = (
                            f'Modeline "{mode_name}"  {pixel_clk} {h_width} {h_start} {h_end} {h_total} {v_height} {v_start} {v_end} {v_total} {" ".join(flags)}'
                        )
                        xorg[screen][connector]["modelines"][mode_name] = modeline
                        break
    return xorg


Modeline_Data = namedtuple("Modeline", [
    "pixelclock",
    "hdisp", "hsyncstart", "hsyncend", "htotal",
    "vdisp", "vsyncstart", "vsyncend", "vtotal",
    "flags"])


def parse_edid_data(edid):
    vendor = "Unknown"
    model = "Unknown"
    modelines = []
    try:
        data = subprocess.check_output(["edid-decode", "-LnpsX", edid],
                                       errors='replace',
                                       universal_newlines=True)
    except subprocess.CalledProcessError:
        pass
    else:
        for line in data.splitlines():
            line = line.strip()
            if line.startswith("Manufacturer:"):
                _, _, vendor = line.partition(': ')
            elif line.startswith("Display Product Name:"):
                _, _, model = line.partition(': ')
            elif line.startswith("Modeline"):
                # For the fields of a modeline see
                # https://en.wikipedia.org/wiki/XFree86_Modeline
                print(line)
                # ignore 'Modeline "Mode N"' part of Modeline
                _, _, line = line.split('"', 2)
                if not line:
                    print("no timing information")
                    continue
                try:
                    mode = Modeline_Data(*line.split(None, 9))
                except (ValueError, TypeError):
                    print("invalid timing information")
                    continue
                refresh = round(float(mode.pixelclock) * 1E6 /
                                (float(mode.htotal) * float(mode.vtotal)))
                interlaced = "i" if "Interlace" in mode.flags else ""
                refresh = int(refresh)
                modeline_name = f'"{mode.hdisp}x{mode.vdisp}_{refresh}{interlaced}"'
                modelines.append(f'Modeline {modeline_name} {line}')
    return vendor, model, modelines


def collect_nvidia_data():
    BusID_RE = re.compile((
        r'(?P<domain>[0-9a-fA-F]+)'
        r':'
        r'(?P<bus>[0-9a-fA-F]+)'
        r':'
        r'(?P<device>[0-9a-fA-F]+)'
        r'\.'
        r'(?P<function>[0-9a-fA-F]+)'
    ))
    try:
        data = subprocess.check_output(["nvidia-smi", "--query-gpu=name,pci.bus_id",
                                        "--format=csv", "-i0"], universal_newlines=True)
    except subprocess.CalledProcessError:
        pass
    except OSError:
        # nvidia-smi is not installed
        pass
    else:
        for row in csv.DictReader(data.splitlines(), delimiter=',', skipinitialspace=True):
            name = row['name']
            bus_id = row['pci.bus_id']
            # pci.bus_id structure as reported by nvidia-smi: "domain:bus:device.function", in hex.
            match = BusID_RE.search(bus_id)
            if match:
                domain, bus, device, function = (int(n, 16) for n in match.groups())
                bus_id = "PCI:{:d}@{:d}:{:d}:{:d}".format(bus, domain, device, function)
                return name, bus_id
    raise ValueError


def find_drm_connectors(connections):
    """
    returns a dict with the following schema (secondary may be empty):
    {
        'primary': {
            'edid': 'edid.HDMI-1.bin',
            'drm_connector': 'HDMI-A-1',
            'xrandr_connector': 'HDMI-1',
        },
        'secondary': {
            'edid': 'edid.eDP-1.bin',
            'drm_connector': 'eDP-1',
            'xrandr_connector': 'eDP-1',
        }
        'ignored_outputs': ['HDMI-A-2', 'DP-1']
    }
    """
    STATUS_GLOB = '/sys/class/drm/card0*/status'
    CONNECTOR_RE = re.compile('card0-(?P<connector>[^/]+)/status')

    def read_edid_bytes(edid_file):
        edid_bytes = b''
        try:
            with open(edid_file, 'rb') as f:
                edid_bytes = f.read()
        except IOError:
            pass
        return edid_bytes

    xrandr_edid_bytes = read_edid_bytes(connections.get('primary', {}).get('edid', ""))
    secondary_xrandr_edid_bytes = read_edid_bytes(connections.get('secondary', {}).get('edid', ''))

    drm = {'primary': {}, 'secondary': {}, 'ignored_outputs': []}
    for status_p in glob(STATUS_GLOB):
        match = re.search(CONNECTOR_RE, status_p)
        if match:
            drm_connector = match.group('connector')
        else:
            continue

        try:
            with open(status_p) as f:
                connected = f.read().strip() == 'connected'
        except IOError:
            continue

        if connected:
            edid = read_edid_bytes(os.path.join(
                os.path.dirname(status_p), 'edid'))
            if edid:
                if edid == xrandr_edid_bytes:
                    drm['primary'] = {
                        'edid': os.path.basename(connections['primary'].get('edid', "")),
                        'drm_connector': drm_connector,
                        'xrandr_connector': connections['primary'].get('connector',''),
                    }
                    continue
                if secondary_xrandr_edid_bytes:
                    drm['secondary'] = {
                        'edid': os.path.basename(connections.get('secondary').get('edid', '')),
                        'drm_connector': drm_connector,
                        'xrandr_connector': connections['secondary'].get('connector',''),
                    }
                    continue
        drm['ignored_outputs'].append(drm_connector)
    return drm


def output_data(data, write_edids=True):
    result = {}
    drm = {}
    if data:
        modes = []
        for _, screen_data in data.items():
            for connector, connection_data in screen_data.items():
                if connection_data.get('EDID') and write_edids:
                    with open('/etc/X11/edid.{}.bin'.format(connector), 'wb') as edid:
                        edid.write(binascii.a2b_hex(connection_data['EDID']))
                for resolution, refreshrates in connection_data['modes'].items():
                    for refreshrate in refreshrates:
                        modes.append(Mode(connector, resolution, refreshrate))
        if modes:
            try:
                gpu_name, bus_id = collect_nvidia_data()
            except ValueError:
                gpu_name = None
                bus_id = None

            def create_entry(my_dict, name, connector, resolution, refreshrate, vendor, model, modelines):
                my_dict[name] = {
                    'connector': connector,
                    'resolution': resolution,
                    'refreshrate': refreshrate,
                    'edid': '/etc/X11/edid.{}.bin'.format(connector),
                    'mode': "{}_{}".format(resolution, refreshrate),
                    'vendor': vendor,
                    'model': model,
                    'modelines': modelines,
                }
                if gpu_name and bus_id:
                    result[name]['gpu_name'] = gpu_name
                    result[name]['bus_id'] = bus_id

            connector_0, resolution_0, refreshrate_0 = max(modes, key=sort_mode)[:3]
            connector_0_edid = '/etc/X11/edid.{}.bin'.format(connector_0)
            vendor_0, model_0, modelines_0 = parse_edid_data(connector_0_edid)
            create_entry(result, 'primary', connector_0, resolution_0,
                         refreshrate_0, vendor_0, model_0, modelines_0)

            # check if additional monitors exist
            other_modes = [mode for mode in modes if mode[0] != connector_0]
            if other_modes:
                connector_1, resolution_1, refreshrate_1 = max(other_modes, key=sort_mode)[:3]
                connector_1_edid = '/etc/X11/edid.{}.bin'.format(connector_1)
                vendor_1, model_1, modelines_1 = parse_edid_data(connector_1_edid)
                create_entry(result, 'secondary', connector_1, resolution_1,
                             refreshrate_1, vendor_1, model_1, modelines_1)

            if write_edids:
                drm = find_drm_connectors(result)


    module.exit_json(changed=True if write_edids else False,
                     ansible_facts={'xrandr': data, 'xorg': result, 'drm': drm})


if __name__ == '__main__':
    module = AnsibleModule(argument_spec=ARG_SPECS, supports_check_mode=False,)
    try:
        d = subprocess.check_output(['xrandr', '-d', module.params['display'], '--verbose'],
                                    errors='replace', universal_newlines=True).splitlines()
    except subprocess.CalledProcessError:
        xorg_data = {}
    else:
        xorg_data = parse_xrandr_verbose(iter(d))
    output_data(xorg_data, module.params['write_edids'])
