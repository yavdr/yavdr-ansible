#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright: (c) 2019, Alexander Grothe <seahawk1986@gmx.de>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type
from collections import OrderedDict
from collections.abc import Generator, Mapping
import traceback

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native


ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: rmmod
short_description: unload kernel modules with rmmod
version_added: 2.7
author:
    - Alexander Grothe
description:
    - Unload kernel modules and their dependencies with rmmod.
    - Builtin kernel modules can't be removed (will do nothing in this case).
options:
    name:
        required: true
        description:
            - Name of kernel module to remove.
'''

EXAMPLES = '''
- name: Unload nouveau module
  rmmod:
    name : nouveau
'''


def find_dependencies(
        module: str,
        dependency_map: Mapping[str, list[str]],
        dependencies: list[str]
):
    dependencies.append(module)
    if module in dependency_map:
        for dependency in dependency_map[module]:
            find_dependencies(dependency, dependency_map, dependencies)
    return dependencies


def module_dependency_gen() -> Generator[tuple[str, list[str]], None, None]:
    with open('/proc/modules') as f:
        for line in f:
            module_name, _, _, dependencies, *_ = line.split()
            yield module_name, list(
                filter(lambda x: x not in ('', '-'), dependencies.split(','))
            )


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
        ),
        supports_check_mode=True,
    )

    name = module.params['name']

    result = dict(
        changed=False,
        name=name,
        unloaded_modules = list()
    )

    # Check if module is loaded
    try:
        dependency_map = dict(module_dependency_gen())
    except IOError as e:
        module.fail_json(
            msg=to_native(e),
            exception=traceback.format_exc(), **result
        )
    else:
        is_loaded = True if name in dependency_map else False

    # remove module if it is loaded
    if is_loaded:
        if not module.check_mode:
            # get a list of unique elements that keeps the original order
            all_modules = list(
                OrderedDict.fromkeys(
                    reversed(
                        find_dependencies(name, dependency_map, [])
                    )
                )
            )
            for kernel_module in all_modules:
                rc, out, err = module.run_command(
                    [module.get_bin_path('rmmod', True), kernel_module]
                )
                if rc != 0:
                    module.fail_json(
                        msg=err,
                        rc=rc,
                        stdout=out, stderr=err, **result
                    )
                else:
                    result['unloaded_modules'].append(kernel_module)
            if result['unloaded_modules']:
                result['changed'] = True

    module.exit_json(**result)


if __name__ == '__main__':
    main()
