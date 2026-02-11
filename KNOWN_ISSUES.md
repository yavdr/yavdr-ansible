This is an overview of the issues I encountered while adapting yavdr-ansible to Ubuntu 26.04 systems. Due to the ongoing development additional issues might be introduced.


# PPAs
The names of files for source entries in `/etc/apt/sources.list.d/` created by `add-apt-repository` and ansible's deb822 module differ: https://github.com/ansible/ansible/issues/86243

This can lead to problems when updating packages after adding a repository twice.

The custom add_ppa module should hopefully work like add-apt-repository and avoid conflicts

# Systemd
On slow systems, systemd units can time out when starting. You can give them more time by adding an override like this:
```conf
[Service]
StartTimeoutSec=infinite
```

# VDR
## Plugins
### vdr-plugin-restfulapi
If plugins invalidate device pointers, the plugin will crash when dereferencing an obsolete pointer.

### vdr-plugin-softhddrm/vaapi
FTBS - needs patches

### vdr-plugin-softhddevice


# Networking

## ntfy Server for vdr-plugin-eventpub
Best to integrate it with the nginx server and https certificate

## DONE Name Resolution

By default local name resolution seems to be disabled in Ubuntu 26.04 (which can affect e.g. the vdr-addon-avahi-linker).
To search certain domains when not using an FQDN, you can add them to the netplan configuration under the `nameservers` list - e.g. for `fritz.box` in `/etc/netplan/00-installer-config.yaml`:

```yml

# This is the network config written by 'subiquity'
network:
  ethernets:
    enp0s3:
      dhcp4: true
      dhcp6: true
      match:
        macaddress: 08:00:27:02:a6:c8
      set-name: enp0s3
      nameservers:
        search: [fritz.box]
  version: 2
```

<!-- This is the solution that made it into the playbook because it doesn't require to differentiate network adapters: -->

Run `the following command to update the actual configuration of systemd-resolved:
```shell
sudo netplan apply
```

Possible way to do this without the need for a device-specific config: https://wiki.archlinux.org/title/Systemd-resolved#systemd-resolved_does_not_resolve_hostnames_without_suffix


If you are using systemd-networkd, you might want the domain supplied by the DHCP server or IPv6 Router Advertisement to be used as a search domain. This is disabled by default, to enable it add to the interface's .network file (/etc/systemd/networkd.conf might also work)
```ini
[Network]
UseDomains=true
```
You can check what systemd-resolved has for each interface with:
```shell
$ resolvectl domain
```

## NFS
The kernel deprecates the `intr` option for NFS, so this needs to be replaced by something like `timeo=600,retrans=2` to prevents endless lockups on timeouts
This affects the `vdr-addon-avahi-linker`, which uses autofs to mount the remote NFS shares in the background.

## TODO avahi-linker
Error when the trying to update recording directories via dbus2vdr while vdr is not ready - make this a less servere loglevel

# Background services
## vdr-addon-lifeguard
crashes on exit - test with new package

## TEST udiskie
```
Dez 01 18:48:28 resolute-legacy udiskie[1610]: Traceback (most recent call last):
Dez 01 18:48:28 resolute-legacy udiskie[1610]:   File "/usr/lib/python3/dist-packages/udiskie/dbus.py", line 225, in callback
Dez 01 18:48:28 resolute-legacy udiskie[1610]:     return handler(object_path, *unpack_variant(parameters))
Dez 01 18:48:28 resolute-legacy udiskie[1610]:   File "/usr/lib/python3/dist-packages/udiskie/udisks2.py", line 941, in _job_completed
Dez 01 18:48:28 resolute-legacy udiskie[1610]:     self.trigger('job_failed', device, action, message)
Dez 01 18:48:28 resolute-legacy udiskie[1610]:     ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Dez 01 18:48:28 resolute-legacy udiskie[1610]:   File "/usr/lib/python3/dist-packages/udiskie/udisks2.py", line 768, in trigger
Dez 01 18:48:28 resolute-legacy udiskie[1610]:     super().trigger(event, device, *args)
Dez 01 18:48:28 resolute-legacy udiskie[1610]:     ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^
Dez 01 18:48:28 resolute-legacy udiskie[1610]:   File "/usr/lib/python3/dist-packages/udiskie/common.py", line 44, in trigger
Dez 01 18:48:28 resolute-legacy udiskie[1610]:     handler(*args)
Dez 01 18:48:28 resolute-legacy udiskie[1610]:     ~~~~~~~^^^^^^^
Dez 01 18:48:28 resolute-legacy udiskie[1610]:   File "/usr/lib/python3/dist-packages/udiskie/async_.py", line 107, in runner
Dez 01 18:48:28 resolute-legacy udiskie[1610]:     return ensure_future(func(*args, **kwargs))
Dez 01 18:48:28 resolute-legacy udiskie[1610]:                          ~~~~^^^^^^^^^^^^^^^^^
Dez 01 18:48:28 resolute-legacy udiskie[1610]: TypeError: DeviceCommand.__call__() takes 2 positional arguments but 4 were given
```

[Source code](https://github.com/coldfix/udiskie/blob/1199864718ca277a0324fa08a1e230424e331f58/udiskie/prompt.py#L207)

[Bug Report](https://github.com/coldfix/udiskie/issues/324#issuecomment-3638677906)

Also requires `gir1.2-notify-0.7` - added to the playbook

# Output

## Console
With the default font settings the Unicode characters used by systemd can't be shown properly on the TTY in late shutdown and replacement chars are rendered for things like progress bars instead. Changing to a font like Terminus (`sudo dpkg-reconfigure console-setup`) seems to fix this.

## Alsa
<!-- the Package in Version 1.2.15 copied from Debian needs to be tested -->
The alsa packages contains the `90-alsa-restore.rules` file that generates warnings regarding to the `alsa-restore_std` label. See Bug on Launchpad #215475 - this might be resolved with a later alsa version.

## pulseaudio

When upgrading from previous yavdr-ansible version, make sure to delete `{{ vdr.home }}/.config/systemd/user/dbus-pulsectl.service` to allow the systemd unit installed by dbus-pulsectl to start the correct python script.

The pulseaudio package installs an executable systemd user session unit, which generates a warning

## pipewire
Replacing pulseaudio with pipewire has huge advantages. The dynamic switching between output devices and profiles is easy - this is used by the webfrontend.

### Bluetooth headphones

Install the following packages:
```shell
sudo apt install bluez pipewire-audio-client-libraries
```

Pairing bluetooth headphones:
Start the system with the bluetooth adapter or make sure that bluetooth.service is running after it was plugged in

Use bluetoothctl to pair the bluetooth devices:

```shell
$ bluetoothctl
[bluetooth]# power on
[bluetooth]# agent NoInputNoOutput
[bluetooth]# default-agent
[bluetooth]# scan on
# make the device you want to pair visible and wait for it to show up
# use the ID for further steps, in this example for a pair of headphones with DE:AD:BE:EF:BE:AF
[bluetooth]# pair DE:AD:BE:EF:BE:AF
[bluetooth]# trust DE:AD:BE:EF:BE:AF
[bluetooth]# connect DE:AD:BE:EF:BE:AF
```

Then use pavucontrol, the vdr-plugin-pulsectl or the webfrontend to switch to it

## graphical output
### no support for multiple GPUs
Currently the automatic configuration of Xorg is limited to using a single GPU/IGP. If you want to configure more than one graphics card, you need to adapt the configuration by hand.

### old nvidia cards
Ubuntu 26.04 only has nvidia drivers version 580 and later - this excludes a lot of older nvidia cards.

Mesa also dropped support for VDPAU: https://www.phoronix.com/news/Mesa-Drops-VDPAU, so the only option is to user VAAPI with them.

So far I haven't been successful get any usable playback without artifacts, color distortion or kernel errors (tested with G210 and a GT630 Kepler card).

In case you find a usable player, you probably want to raise the performance profile of the card:

```shell
echo 0f | sudo tee /sys/kernel/debug/dri/1/pstate
```
Using `Option "DRI" "2"` could also help in case there are problems with gle.

### intel cards
There might be some trial and error involved to find a working combination of driver, glx version and softhddevice output method.

For old IGPs (e.g. Haswell Generation), using the `intel` driver and `va-api` works usually best up to Ubuntu 24.04

For a 13th generation Core i3, `va-api-egl` works best. Under Ubuntu 26.04 va-api-egl seems to be the best default choice.

The modesetting driver seems to be limited to a single display.

Under Ubuntu 26.04 there is a problem with German DVB-T2 for vaapi and cpu render methods if the dvb tuner drops out.

`libgl1-amber-dri` needs to be installed, too

### forcing connection status
Due to changes in the intel drivers, you can't force HDMI ports to be seen as connected by the Kernel. However there is an udev event sent if a drm connector changes due to Hotplug - this doesn't specify the connetor nor if it's a plugged in/out event:
```shell
$ udevadm monitor --kernel --subsystem-match=drm
monitor will print the received events for:
KERNEL - the kernel uevent

KERNEL[1521.180340] change   /devices/pci0000:00/0000:00:02.0/drm/card1 (drm)  # HDMI unplugged
KERNEL[1526.345601] change   /devices/pci0000:00/0000:00:02.0/drm/card1 (drm)  # HDMI plugged in again
```

So we create an udev rule that starts a sytemd unit in that case:
```
ACTION=="change", SUBSYSTEM=="drm", ENV{HOTPLUG}=="1", \
  RUN+="/usr/bin/systemctl --user start drm-hotplug.service"
```

Then we need to tell xorg to configure the display(s) (if the connectors are been connected) - e.g.:
```shell
/usr/bin/xrandr --output HDMI-1 --auto --primary
```

To get the Xorg connector name, we have to look at `/etc/ansible/facts.d/drm.fact`.

<!-- TODO: complete handling of unconnected display -->
This is currently partially implented in the yavdr-frontend script - Still missing:
Prevent attaching the frontend if not connected
Check if deta/atta is needed after running the xrandr command

We also need to improve the conditions under which `update-initramfs` are called

# GUI Software and Configuration

## Openbox
The `rc.xml` points to a menu file in `/var/lib/vdr/openbox.xml` that file doesn't exist in recent openbox packages

# yavdr-frontend
## vdr-sxfe
vdr-sxfe isn't started successfully after vdr starts - still unclear why this happens
## stopping yavdr-frontend before the X-Server
This is done via yavdr-frontend with the on_xorg_stop method called via dbus

# KODI
The shutdown menu allows to shutdown the system - can we block this with an inhibitor?

## TODO Firefox
<!-- TODO: this was implemented in the role "firefox" - needs still to be tested with a system that has an nvidia card (GT1030 or better) -->
By default there is no Hardware acceleration for Nvidia GPUs in Firefox. For GPUs that support NVDEC and an nvidia-driver > 470 it is possible to use
[nvidia-vaapi-driver](https://github.com/elFarto/nvidia-vaapi-driver) as a workaround.

To use this: install firefox from Mozilla's debian repository: https://support.mozilla.org/en-US/kb/install-firefox-linux#w_install-firefox-deb-package-for-debian-based-distributions-recommended
It' recommended to uninstall the snap version to avoid mixups: `sudo snap remove firefox`

Install the package `nvidia-vaapi-driver` from this PPA: https://launchpad.net/~ubuntuhandbook1/+archive/ubuntu/nvidia-vaapi

```shell
sudo add-apt-repository ppa:ubuntuhandbook1/nvidia-vaapi
sudo apt install nvidia-vaapi-driver
```

Set the necessary environment variables - e.g. at the end of the `/var/lib/vdr/.bashrc`:
```shell
LIBVA_DRIVER_NAME=nvidia
MOZ_DISABLE_RDD_SANDBOX=1
CUDA_DISABLE_PERF_BOOST=1
```

Adapt the firefox configuration as described in https://github.com/elFarto/nvidia-vaapi-driver?tab=readme-ov-file#firefox

After a reboot firefox should be able to use hardware acceleration - you can check this on the `about:support` page in Firefox - a GT1030 should support hardware-decoding for H264, VP9 and HEVC.
