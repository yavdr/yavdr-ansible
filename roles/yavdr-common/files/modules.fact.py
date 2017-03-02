#!/usr/bin/env python2
# This script returns a list of currently loaded kernel modules
from __future__ import print_function
import json
import kmodpy

k = kmodpy.Kmod()

print(json.dumps([module[0] for module in k.loaded()]))
