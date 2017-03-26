#!/usr/bin/env python2

DOCUMENTATION = '''
---
module: xorg_facts
short_description: "gather facts about connected monitors and available modelines"
description:
     - This script needs a running x-server on a given display in order to successfully call xrandr.
       The ranking uses the following factors:
       1. preferred_refreshrate
       2. preferred_resolution
       3. preferred_output
       For each element a dictionary of values (up to 4 bit [0 .. 256]) may be passed to the module.
       The rank is represented by this order of 4-Bit values:
       | rrate | resolution | output | internal score
       |    50 |  1920x1080 |   HDMI | 0b_0100_0100_0100 = 1092
       |    60 |   1280x720 |     DP | 0b_0011_0011_0011 =  819
       Returns the connected output, monitors and modelines and a suggestion for the most fitting mode in a dictionary 'xorg'
options:
    display:
        required: False
        default: ":0"
        description:
          - the DISPLAY variable to use when calling xrandr
    preferred_outpus:
        required: False
        default: {"HDMI": 4, "DP": 3, "DVI": 2, "VGA": 1, "TV": 0}
        description:
          - ranking of the preferred display connectors
    preferred_refreshrates:
        required: False
        default: {"50": 4, "60": 3, "75": 2, "30": 1, "25": 0}
        description:
          - ranking of the preferred display refreshrate
    preferred_resolutions:
        required: False
        default: {"7680x4320": 8, "3840x2160": 4, "1920x1080": 2, "1280x720": 1, "720x576": 0}
        description:
           - ranking of the preferred display resolutions
'''
EXAMPLES = '''
- name: "collect facts for connected displays"
  action: xserver_facts
    display: ":0"

- debug:
    var: xorg
'''

import ast
import json
import re
import subprocess
import sys
import time
from collections import OrderedDict, namedtuple

from ansible.module_utils.basic import *

arg_specs = {
    'display': dict(default=[":0", ":0.1"], type='list', required=False),
    'multi_display': dict(default=True, type='bool', required=False),
    'preferred_outputs': dict(default={"HDMI": 8, "DP": 4, "DVI": 2, "VGA": 1, "TV": 0}, type='dict', required=False),
    'preferred_refreshrates': dict(default={50: 8, 60: 4, 75: 3, 30: 2, 25: 1}, type='dict', required=False),
    'preferred_resolutions': dict(default={"7680x4320": 8, "3840x2160": 4, "1920x1080": 2, "1280x720": 1, "720x576": 0},
                                  type='dict', required=False),
    }

Mode = namedtuple('Mode', ['connection', 'resolution', 'refreshrate'])


class ModelineTools(object):
    def __init__(self, preferred_outputs, preferred_resolutions, preferred_refreshrates):
        self.preferred_outputs = preferred_outputs
        self.preferred_resolutions = preferred_resolutions
        self.preferred_refreshrates = preferred_refreshrates
        
    def get_score(self, connection, resolution, refreshrate):
        connection = connection.split('-')[0]
        score = self.preferred_refreshrates.get(int(refreshrate), 0)
        score = score << 4
        score += self.preferred_resolutions.get(resolution, 0)
        #score = score << 4
        #score += self.preferred_outputs.get(connection, 0)
        return score

    @staticmethod
    def cleanup_refreshrate(refreshrate):
        rrate = refreshrate.replace('+', '').replace('*', '').replace(' ', '').strip()
        return int(round(ast.literal_eval(rrate)))
    
    def sort_mode(self, mode):
        refreshrate_score = self.preferred_refreshrates.get(int(mode.refreshrate), 0)
        resolution_score = self.preferred_resolutions.get(mode.resolution, 0)
        x, y = mode.resolution.split('x')
        connection = mode.connection.split('-')[0]
        return (refreshrate_score, resolution_score, int(x), int(y), self.preferred_outputs.get(connection, 0))
    

def main():
    module = AnsibleModule(argument_spec=arg_specs, supports_check_mode=False,)
    display_list = module.params['display']
    preferred_outputs = module.params['preferred_outputs']
    preferred_resolutions = module.params['preferred_resolutions']
    preferred_refreshrates = module.params['preferred_refreshrates']
    mtools = ModelineTools(preferred_outputs, preferred_resolutions, preferred_refreshrates)
    modes = []
    displays = {}
    data = {}

    for display in display_list:
        # call xrandr
        try:
            xrandr_data = subprocess.check_output(['xrandr', '-q','-d', display],
                                                  universal_newlines=True)
        except: continue
    
        for line in xrandr_data.splitlines():
            if line.startswith('Screen'):
                screen = line.split(':')[0].split()[-1]
                screen = "Screen{}".format(screen)
                displays[screen] = {}

            elif 'connected' in line:
                connection = line.split()[0]
                displays[screen][connection] = {}
                if 'disconnected' in line:
                    displays[screen][connection]['connected'] = False
                else:
                    displays[screen][connection]['connected'] = True
                displays[screen][connection]['modes'] = OrderedDict(
                    sorted({}.items(), key=lambda t: t.split('_')[0]))
                display_modes = []

            elif line.startswith(' '):
                fields = filter(None, re.split(r'\s{2,}', line))
                resolution = fields[0]
                refreshrates = fields[1:]

                r = set()
                for refreshrate in refreshrates:
                    refreshrate = refreshrate.strip()
                    rrate = mtools.cleanup_refreshrate(refreshrate)
                    if len(refreshrate) < 2:
                        continue
                    if '*' in refreshrate:
                        current_mode = Mode(connection, resolution, rrate)
                        displays[screen][connection]['current_mode'] = current_mode
                    if '+' in refreshrate:
                        preferred_mode = Mode(connection, resolution, rrate)
                        displays[screen][connection]['preferred_mode'] = preferred_mode
                    r.add(mtools.cleanup_refreshrate(refreshrate))
                    modes.append(Mode(connection=connection, resolution=resolution, refreshrate=rrate))
                    display_modes.append(Mode(connection=connection, resolution=resolution, refreshrate=rrate))
                    displays[screen][connection]['modes'][resolution] = sorted(r)
                    displays[screen][connection]['best_mode'] = max(display_modes, key=mtools.sort_mode)


    data['displays'] = displays
    #data['modes'] = modes
    best_mode = max(modes, key=mtools.sort_mode)
    data["best_mode"] = {
        'connection': best_mode.connection,
        'resolution': best_mode.resolution,
        'refreshrate': best_mode.refreshrate,
    }

    module.exit_json(changed=False, ansible_facts={'xorg': data})


if __name__ == '__main__':
    main()
