#!/usr/bin/env python2
from __future__ import print_function
import ast
import binascii
import re
import subprocess
from collections import namedtuple

from ansible.module_utils.basic import *

DOCUMENTATION = '''
---
module: xrandr_facts
short_description: "gather facts about connected monitors and available modelines"
description:
     - This module needs a running x-server on a given display in order to successfully call xrandr.
       Returns the dictionary "xrandr", wich contains all screens with output states, connected displays,
       EDID info and their modes and a recommendation for the best fitting tv mode.
options:
    display:
        required: False
        default: ":0"
        description:
          - the DISPLAY variable to use when calling xrandr
    multi_display:
        required: False
        default: "False"
        description:
          - check additional screens (:0.0 .. :0.n) until xrandr fails to collect information
    preferred_outpus:
        required: False
        default: ["HDMI", "DP", "DVI", "VGA", "TV": 0]
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
'''
EXAMPLES = '''
- name: "collect facts for connected displays"
  action: xserver_facts
    display: ":0"

- debug:
    var: xrandr
'''

ARG_SPECS = {
    'display': dict(default=":0", type='str', required=False),
    'multi_display': dict(default=False, type='bool', required=False),
    'preferred_outputs': dict(
        default=["HDMI", "DP", "DVI", "VGA", "TV"], type='list', required=False),
    'preferred_refreshrates': dict(
        default=[50, 60, 75, 30, 25], type='list', required=False),
    'preferred_resolutions': dict(
        default=[
            "7680x4320", "3840x2160", "1920x1080", "1280x720", "720x576"],
        type='list', required=False),
    'write_edids': dict(default=True, type='bool', required=False),
    }

SCREEN_REGEX = re.compile("^(?P<screen>Screen\s\d+:)(?:.*)")
CONNECTOR_REGEX = re.compile(
    "^(?P<connector>.*-\d+)\s(?P<connection_state>connected|disconnected)\s(?P<primary>primary)?")
MODE_REGEX = re.compile("^\s+(?P<resolution>\d{3,}x\d{3,}).*")

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
    x_resolution, y_resolution = (int(n) for n in  mode.resolution.split('x'))
    connection = mode.connection.split('-')[0]
    if connection in preferred_outputs:
        connection_score = len(preferred_outputs) - preferred_outputs.index(connection)
    return (rrate_score, resolution_score, x_resolution, y_resolution, connection_score)

def parse_xrandr_verbose(iterator):
    """parse the output of xrandr --verbose using an iterator delivering single lines"""
    xorg = {}
    is_connected = False
    for line in iterator:
        if line.startswith('Screen'):
            screen = check_for_screen(line)
            xorg[screen] = {}
        elif 'connected' in line:
            connector, is_connected = check_for_connection(line)
            xorg[screen][connector] = {
                'is_connected': is_connected,
                'EDID': '',
                'modes': {},
                'preferred': '',
                'current': '',
                'auto': '',
                }
        elif is_connected and 'EDID:' in line:
            edid_str = ""
            outer_indentation = get_indentation(line)
            while True:
                line = next(iterator)
                if get_indentation(line) > outer_indentation:
                    edid_str += line.strip()
                else:
                    break
            xorg[screen][connector]['EDID'] = edid_str
        elif is_connected and "MHz" in line and not "Interlace" in line:
            match = re.match(MODE_REGEX, line)
            if match:
                match = match.groupdict()
                preferred = bool("+preferred" in line)
                current = bool("*current" in line)

                while True:
                    line = next(iterator)
                    if line.strip().startswith('v:'):                        
                        refresh_rate = ast.literal_eval(line.split()[-1][:-2])
                        rrate = int(round(refresh_rate))
                        if xorg[screen][connector]['modes'].get(match['resolution']) is None:
                            xorg[screen][connector]['modes'][match['resolution']] = []
                        if rrate not in xorg[screen][connector]['modes'][match['resolution']]:
                            xorg[screen][connector]['modes'][match['resolution']].append(rrate)
                        if preferred:
                            xorg[screen][connector]['preferred'] = "{}_{}".format(
                                match['resolution'], rrate)
                        if current:
                            xorg[screen][connector]['current'] = "{}_{}".format(
                                match['resolution'], rrate)
                        break
    return xorg

def output_data(data, write_edids=True):
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
            best_mode = max(modes, key=sort_mode)
            data['best_tv_mode'] = best_mode

    #print(json.dumps(data, sort_keys=True, indent=4))
    module.exit_json(changed=True if write_edids else False, ansible_facts={'xrandr': data})

if __name__ == '__main__':
    module = AnsibleModule(argument_spec=ARG_SPECS, supports_check_mode=False,)
    try:
        d = subprocess.check_output(['xrandr', '-d', module.params['display'], '--verbose'], universal_newlines=True).splitlines()
    except subprocess.CalledProcessError:
        xorg_data = {}
    else:
        xorg_data = parse_xrandr_verbose(iter(d))
    output_data(xorg_data, module.params['write_edids'])
