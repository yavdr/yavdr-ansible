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
        screen = line.split(':', maxsplit=1)[0].split()[-1]
        new_screen = True
        print('Screen: {}'.format(screen))

    elif new_screen and not new_connection and ' connected ' in line:
        connection = line.split()[0]
        new_screen = False
        new_connection = True
        print('Connection: {}'.format(connection))
        resolutions = {}

    elif new_connection and line.startswith(' '):
        resolution, *refreshrates = line.split()
        res_x, res_y = resolution.split('x')
        resolution = (int(res_x), int(res_y))
        r = []
        for refreshrate in refreshrates:
            if '+' in refreshrate:
                current_mode = (resolution,
                                cleanup_refreshrate(refreshrate))
                print('Current Mode: {}@{}'.format(*current_mode))
            if '*' in refreshrate:
                preferred_mode = (resolution,
                                  cleanup_refreshrate(refreshrate))
                print('Preferred Mode: {}@{}'.format(*preferred_mode))
            r.append(cleanup_refreshrate(refreshrate))
        resolutions[resolution] = r

print_modelines(resolutions)
