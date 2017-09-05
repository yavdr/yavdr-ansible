#!/usr/bin/ env python3
import subprocess


xrandr_data = subprocess.check_output(['xrandr', '-q'], universal_newlines=True)


def print_modelines(resolutions):
    if resolutions:
        for resolution, refreshrates in reversed(sorted(resolutions.items())):
            for refreshrate in refreshrates:
                print("{}_{}".format(resolution, refreshrate))


def cleanup_refreshrate(refreshrate):
    return refreshrate.replace('+', '').replace('*', '')

resolutions = {}
for line in xrandr_data.splitlines():
    if line.startswith('Screen'):
        print_modelines(resolutions)
        new_connection = False
        screen = line.split(':', 1)[0].split()[-1]
        new_screen = True
        print('Screen: {}'.format(screen))
    elif ' connected ' in line:
        connection = line.split()[0]
        new_screen = False
        new_connection = True
        print('Display connected: {}'.format(connection))
        resolutions = {}
    elif ' disconnected ' in line:
        #Print debug information during detection
        connection = line.split()[0]
        print('Display disconnected: {}'.format(connection))
    elif line.startswith(' '):
        r = []
        connectionDetails = list(filter(None,line.split(' ')))
        #Get first entry with resolution. Rest can contain multiple refreshrates
        resolution = connectionDetails.pop(0)
        res_x, res_y = resolution.split('x')
        resolution = (int(res_x), int(res_y))
        for refreshrate in connectionDetails:
            if '+' in refreshrate:
                current_mode = (resolution, cleanup_refreshrate(refreshrate))
                print('Current Mode: {}@{}'.format(*current_mode))
            if '*' in refreshrate:
                preferred_mode = (resolution, cleanup_refreshrate(refreshrate))
                print('Preferred Mode: {}@{}'.format(*preferred_mode))
            r.append(cleanup_refreshrate(refreshrate))
        resolutions[resolution] = r

print_modelines(resolutions)
