#!/usr/bin/bash
# use this script to configure a remote VDR host instead of localhost
set -e

ansible-playbook yavdr07.yml -i 'hosts' --ask-become-pass "$@"
