# yavdr-ansible
ansible playbooks for yaVDR

## What can yavdr-ansible do for me?
[Ansible](https://docs.ansible.com/ansible/latest/index.html) is an automation tool which can be used to configure systems and deploy software.
yavdr-ansible uses Ansible to set up a yaVDR System on top of an Ubuntu 18.04 Server installation (see below for details) and allows the user to fully customize the installation - have a look at the Ansible documentation if you want to learn how it works.

Please note that this is still work in progress and several features of yaVDR 0.6 haven't been implemented (yet).

## System Requirements and Compatiblity Notes
- RTC must be set to UTC in order for vdr-addon-acpiwakeup to work properly
- 32 Bit Installations are untested, but should work
- You need an IGP/GPU with support for VDPAU or VAAPI if you want to use software output plugins for VDR like softhddevice or vaapidevice
- xineliboutput/vdr-sxfe works with software rendering, too
- Can be used in a VirtualBox VM (VirtualBox 5.22 works better than Version 6.0.0)

## Usage:

Set up a Ubuntu Server 18.04.x Installation

NOTE: it is important to use the [alternative server installer](https://www.ubuntu.com/download/alternative-downloads#alternate-ubuntu-server-installer) or the [mini.iso](https://help.ubuntu.com/community/Installation/MinimalCD), otherwise the boot splash and Xorg won't work properly.

### Download yavdr-ansible
Run the following commands to download the current version of yavdr-ansible:
```
sudo apt-get install git
git clone https://github.com/yavdr/yavdr-ansible
cd yavdr-ansible
git checkout bionic
```

### Customizing the Playbooks and Variables
You can choose the roles run by the playbooks `yavdr07.yml` or ` yavdr07-headless.yml`.

If you want to customize the variables in [group_vars/all](group_vars/all), copy the file to `host_vars/localhost` before changing it. This way you can change the PPAs used and choose which extra vdr plugins and packages should be installed by default.

### Run the Playbook
If you want a system with Xorg output run:
```
sudo -H ./install-yavdr.sh
```
NOTE: on systems with a nvidia card unloading the noveau driver after installing the proprietary nvidia driver can fail (in this case ansible throws an error). If this happens please reboot your system to allow the nvidia driver to be loaded and run the install script again.

If you want a headless vdr server run:
```
sudo -H ./install-yavdr-headless.sh
```

## First Steps after the installation:

### Wait for local dvb adapters
The yaVDR VDR Package provides a systemd service `wait-for-dvb@.service` which allows to delay the start of vdr until all given locally connected dvb adapters have been initalized - e.g. to wait for `/dev/dvb/adapter0 .. /dev/dvb/adapter3`you can enable the required instances of this service like this:
```shell
systemctl enable wait-for-dvb@{0..3}.service
```
Please remember to adapt the enabled service instances if you change your configuration.

This should work foll all DVB adaptors for which udev events are generated. Note that devices with userspace drivers (e.g. by Sundtek) won't emit such events.

### Add a /var/lib/vdr/channels.conf

You can use the wirbelscan-Plugin, w_scan, t2scan (especially useful for DVB-T2) or ready-to-use channellists from http://channelpedia.yavdr.com/gen/

Important: vdr.service must be stopped if you want to edit VDR configuration files: `sudo stop vdr.service`

### Rescan displays
If you change the connected displays you may need to update the display configuration. This can be achived by running the `yavdr-xorg` role:
```shell
sudo -H ansible-playbook yavdr07.yml -b -i 'localhost_inventory' --connection=local --tags="yavdr-xorg"
```

### running single roles without a custom playbook
You can choose to (re-)run single roles included in a playbook by including their name in the `--tags` argument (see example above for rescanning displays with `yavdr-xorg`).
