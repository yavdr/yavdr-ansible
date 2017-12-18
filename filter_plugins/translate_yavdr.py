# Copyright (c) 2017 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)


from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'yavdr'
}

import gettext
from ansible.errors import AnsibleFilterError
from ansible.utils import helpers


def translate_yavdr(text):
    gettext.textdomain('yavdr')
    try:
        return gettext.gettext(text)
    except:
        return text

# ---- Ansible filters ----
class FilterModule(object):
    ''' URI filter '''

    def filters(self):
        return {
            'translate': translate_yavdr
        }
