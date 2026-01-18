{{ ansible_managed.format(file=template_path) | comment }}
export VDR_ID={{ vdr.instance_id | default(0) }}
