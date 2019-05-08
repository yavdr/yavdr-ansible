#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2019, Alexander Grothe <seahawk1986@gmx.de>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type
import traceback

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
---
module: rmmod
short_description: unload kernel modules with rmmod
version_added: 2.7
author:
    - Alexander Grothe
description:
    - Unload kernel modules with rmmod.
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
    name: nouveau
'''


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
        ),
        supports_check_mode=True,
    )

    name = module.params['name']

    # FIXME: Adding all parameters as result values is useless
    result = dict(
        changed=False,
        name=name,
    )

    # Check if module is loaded
    try:
        is_loaded = False
        with open('/proc/modules') as modules:
            module_name = name.replace('-', '_') + ' '
            for line in modules:
                if line.startswith(module_name):
                    is_loaded = True
                    break
    except IOError as e:
        module.fail_json(msg=to_native(e), exception=traceback.format_exc(), **result)

    # remove module if it is loaded
    if is_loaded:
        if not module.check_mode:
            rc, out, err = module.run_command([module.get_bin_path('rmmod', True), name])
            if rc != 0:
                module.fail_json(msg=err, rc=rc, stdout=out, stderr=err, **result)
        result['changed'] = True

    module.exit_json(**result)


if __name__ == '__main__':
    main()
