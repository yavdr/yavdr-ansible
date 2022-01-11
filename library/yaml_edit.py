#!/usr/bin/env python3
import copy
import sys
from pathlib import Path
from typing import List, IO, Any, Optional
import ruamel.yaml
from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = '''
---
module: yaml_edit
short_description: "change the value of a key in a yaml file"
description:
     - This module changes the value of a given key (if nested in the form 'a.b.c')
       to the given value and type (choose one of the <type>_value arguments). You can set formatting options to get the desired
       layout, so the change is non-intrusive.
options:
    path: 
        required: True
        type: path
        description:
            - the path of the yaml file you want to edit
    
    key:
        required: True
        type: str
        description:
            - the key you want to change. Nested keys can be specified in dot notation, e.g. 'a.b.c'

    str_value:
        required: False
        type: str
        description:
            - set a string value

    int_value:
        required: False
        type: int
        description:
            - set an int value

    bool_value:
        required: False
        type: bool
        description:
            - set a boolean value

    list_value:
        required: False
        type: list
        description:
            - set a list value

    float_value:
        required: False
        type: float
        description:
            - set a float value

    float_value:
        required: False
        type: dict
        description:
            - set a dict value

    preserve_quotes:
        required: False
        type: bool
        default: True
        description:
            - preserve quotes in the yaml file

    explicit_start:
        required: False
        type: bool
        default=True
        description:
            - start yaml file with '---'

    boolean_representation:
        required: False
        type: list
        elements: str
        default: ["False", "True"]
        description:
            - set the representation of boolean values in the yaml file

    mapping_indent:
        required: False
        type: int
        default: 4
        description:
            - set the indentation for mappings

    sequence_indent:
        required: False
        type: int
        default=4
        description:
            - set the indentation for sequences

    offset_indent:
        required: False
        type: int
        default=2
        description:
            - set the indentation offset - se ruaml.yaml documentation for details
'''

EXAMPLES = '''
- name: set vdr instance id for yavdr-frontend
  yaml_edit:
    path: /etc/yavdr-frontend/config.yml
    key: vdr.id
    int_value: "{{ vdr.instance_id }}"
'''

debug_output = []


class yamlInPlaceEditor():
    def __init__(
        self,
        filename: Path,
        preserve_quotes: bool = True,
        explicit_start: bool = True,
        boolean_representation: Optional[List[str]] = None,
        mapping_indent: int = 4,
        sequence_indent: int = 4,
        offset_indent: int = 2,
    ) -> None:
        self.changed = False
        self.filename = Path(filename)
        self.yaml = ruamel.yaml.YAML()
        self.yaml.preserve_quotes = preserve_quotes
        self.yaml.explicit_start = explicit_start
        self.yaml.boolean_representation = ["False", "True"] if not boolean_representation else boolean_representation
        self.yaml.indent(
            mapping=mapping_indent,
            sequence=sequence_indent,
            offset=offset_indent
        )
        self.load_file(self.filename)

    def __enter__(self) -> "yamlInPlaceEditor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.changed:
            self.dump_file(self.filename)

    def set_dict_value(self, key: str, value: Any) -> None:
        d = copy.deepcopy(self.data)
        w = d
        parts = key.split('.')
        debug_output.append(f"called set_dict_value with {key=}, {value=}")
        debug_output.append(f"{type(self.data)=}: {self.data}")
        for p in parts[:-1]:  # the last part of the key is the value we want to change
            if not (t := w.get(p)):
                w[p] = dict()
                self.changed = True
            else:
                w = t
        if w[parts[-1]] != value:
            self.changed = True
        w[parts[-1]] = value
        self.data.update(d)
        print(f"{self.changed=}")

    def load_file(self, fd: IO) -> None:
        self.data = self.yaml.load(fd)

    def dump_file(self, fd: IO = sys.stdout):
        self.yaml.dump(self.data, fd)


def run_module():
    changed = False
    module_args = dict(
        path=dict(type='path', required=True),
        key=dict(type='str', required=True),
        str_value=dict(type='str'),
        int_value=dict(type='int'),
        bool_value=dict(type='bool'),
        list_value=dict(type='list'),
        float_value=dict(type='float'),
        dict_value=dict(type='dict'),
        
        preserve_quotes=dict(type='bool', default=True),
        explicit_start=dict(type='bool', default=True),
        boolean_representation=dict(type='list', elements='str', default=[]),
        mapping_indent=dict(type='int', default=4),
        sequence_indent=dict(type='int', default=4),
        offset_indent=dict(type='int', default=2),
    )
    module = AnsibleModule(
        module_args,
        required_one_of=[[
            'str_value',
            'int_value',
            'bool_value',
            'list_value',
            'float_value',
            'json_value',
            'dict_value',
        ]],
        supports_check_mode=False,
    )
    try:
        with yamlInPlaceEditor(
                filename=module.params['path'],
                preserve_quotes=module.params['preserve_quotes'],
                explicit_start=module.params['explicit_start'],
                boolean_representation=module.params['boolean_representation'],
                mapping_indent=module.params['mapping_indent'],
                sequence_indent=module.params['sequence_indent'],
                offset_indent=module.params['offset_indent'],
           ) as e:
            for k, v in module.params.items():
                if not k.endswith('_value'):
                    continue
                if v is not None:  # only one of the *_value variables must be not None
                    e.set_dict_value(module.params['key'], v)
                    break
            changed = e.changed or changed
    except Exception as err:
        changed = False
        module.fail_json(msg=str(err) + '\n' + "\n".join(debug_output))
    else:
        module.exit_json(changed=changed)
    

def main():
    run_module()


if __name__ == '__main__':
    main()
