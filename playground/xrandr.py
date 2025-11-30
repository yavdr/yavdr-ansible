#!/usr/bin/python3
from __future__ import print_function
import ast
import binascii
import csv
import re
import subprocess
from collections import defaultdict, namedtuple
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Generator, NamedTuple, cast

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = """
---
module: xrandr_facts
short_description: "gather facts about connected monitors and available modelines"
description:
     - This module needs a running x-server on a given display in
       order to successfully call xrandr. Returns the dictionary
       "xrandr", wich contains all screens with output states,
       connected displays, EDID info and their modes and a
       recommendation for the best fitting tv mode, the dictionary
       "xorg" with a recommendation for the primary and secondary
       output, a "drm" dictionary whose "primary" key associates
       the primary device name of the drm subsystem with the one from
       the xrandr output by comparing the edid data and a list of
       "ignored_devices". Note that the proprietary nvidia driver
       doesn't support KMS/drm, so in this case the dictionary is
       always empty.
       The "config" dictionary contains the Xorg connector name and
       the best fitting resolution and refreshrate for the primary
       (and if available: the secondary output).
options:
    display:
        required: False
        default: ":0"
        description:
          - the DISPLAY variable to use when calling xrandr
    preferred_outputs:
        required: False
        default: ["HDMI", "DP", "eDP", "DVI", "VGA", "TV", "Virtual"]
        description:
          - ranking of the preferred display connectors
    preferred_refreshrates:
        required: False
        default: ["50", "60", "75", "30", "25"]
        description:
          - ranking of the preferred display refreshrate
    preferred_resolutions:
        required: False
        default: ["7680x4320", "3840x2160", "1920x1080", "1280x720", "720x576"]
        description:
           - ranking of the preferred display resolutions
"""
EXAMPLES = """
- name: "collect facts for connected displays"
  action: xserver_facts
    display: ":0"

- ansible.builtin.debug:
    var: xrandr

- ansible.builtin.debug:
    var: xorg

- ansible.builtin.debug:
    var: drm

- ansible.builtin.debug:
    var: config
"""

ARG_SPECS: dict[str, dict[str, Any]] = {
    "display": dict(default=":0", type="str", required=False),
    "preferred_outputs": dict(
        default=["HDMI", "DP", "eDP", "DVI", "VGA", "TV", "Virtual"],
        type="list",
        elements="str",
        required=False,
    ),
    "preferred_refreshrates": dict(
        default=[50, 60, 75, 30, 25], type="list", elements="int", required=False
    ),
    "preferred_resolutions": dict(
        default=["7680x4320", "3840x2160", "1920x1080", "1280x720", "720x576"],
        type="list",
        elements="str",
        required=False,
    ),
}

SCREEN_REGEX = re.compile(r"^(?P<screen>Screen\s\d+:)(?:.*)")
CONNECTOR_REGEX = re.compile(
    r"^(?P<connector>(.*-?\d+)|default)\s(?P<connection_state>connected|disconnected)\s(?P<primary>primary)?"
)
MODE_REGEX = re.compile(r"^\s+(?P<resolution>\d{3,}x\d{3,}).*")

class Mode(NamedTuple):
    connection: str
    resolution: str
    refreshrate: int

# Mode = namedtuple("Mode", ["connection", "resolution", "refreshrate"])


@dataclass
class MonitorConfig:
    connector: str = ""
    resolution: str = ""
    refreshrate: int = 0


@dataclass
class OutputConfig:
    primary: MonitorConfig | None = None
    secondary: MonitorConfig | None = None


@dataclass
class XrandrMonitor:
    connector: str
    is_connected: bool = False
    drm_connector: str = ""
    edid: str = ""
    mode: str = ""
    model: str = ""
    modes: defaultdict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    modelines: dict[str, str] = field(default_factory=dict)
    refreshrate: int = 0
    resolution: str = ""
    vendor: str = ""
    preferred: str = ""
    preferred_resolution: str = ""
    preferred_refreshrate: int = 0
    current: str = ""
    auto: str = ""

    @property
    def edid_file(self):
        if not self.connector:
            raise ValueError("No connector defined")
        return Path(f"/etc/X11/edid.{self.connector}.bin")

    @property
    def binary_edid(self):
        return binascii.a2b_hex(self.edid)


def check_for_screen(line: str) -> str:
    """check line for screen information"""
    match = re.match(SCREEN_REGEX, line)
    if match:
        return match.groupdict()["screen"]
    raise ValueError("No screen found")


def check_for_connection(line: str) -> tuple[str, bool]:
    """check line for connection name and state"""
    connector = ""
    is_connected = False
    if match := re.match(CONNECTOR_REGEX, line):
        match = match.groupdict()
        connector: str = match["connector"]
        is_connected = True if match["connection_state"] == "connected" else False
    if not connector:
        raise ValueError("no connector found")
    return connector, is_connected


def get_indentation(line: str) -> int:
    """return the number of leading whitespace characters"""
    return len(line) - len(line.lstrip())


def parse_xrandr_verbose(lines: list[str], params: dict[str, Any]) -> dict[str, dict[str, XrandrMonitor]]:
    """parse the output of xrandr --verbose using an iterator delivering single lines"""
    xorg: dict[str, dict[str, XrandrMonitor]] = {}
    is_connected = False
    screen = "Screen 0:"
    connector = ""
    for line in (iterator := lines.__iter__()):
        if line.startswith("Screen"):
            screen = check_for_screen(line)
            xorg[screen] = {}
        elif "connected" in line:
            connector, is_connected = check_for_connection(line)
            xorg[screen][connector] = XrandrMonitor(
                connector=connector, is_connected=is_connected
            )
        elif is_connected and "EDID:" in line:
            edid_str = ""
            outer_indentation = get_indentation(line)
            while True:
                line: str = next(iterator)
                if get_indentation(line) > outer_indentation:
                    edid_str += line.strip()
                else:
                    break
            xorg[screen][connector].edid = edid_str
            # parse the EDID
            vendor, model, _mode_lines = parse_edid_bytes(edid_str)
            xorg[screen][connector].model = model.strip("'")
            xorg[screen][connector].vendor = vendor
        elif is_connected and "MHz" in line and "Interlace" not in line:
            if match := re.match(MODE_REGEX, line):
                match_resolution: str = match["resolution"]
                match = match.groupdict()
                preferred = bool("+preferred" in line)
                current = bool("*current" in line)
                _resolution, _mode_num, pixel_clk, *flags = line.split()
                flags = [
                    flag for flag in flags if flag not in ("*current", "+preferred")
                ]
                pixel_clk = pixel_clk[:-3]

                while True:
                    line = next(iterator).strip()
                  #   match line[0:2]:
                  #       case "h:":
                    if line.startswith("h:"):
                        h_width = h_start = h_end = h_total = _h_skew = h_clock = '?'
                        (
                            _,
                            _,
                            h_width,
                            _,
                            h_start,
                            _,
                            h_end,
                            _,
                            h_total,
                            _,
                            _h_skew,
                            _,
                            h_clock,
                        ) = line.split()
                        h_clock = h_clock[:-3]

                    elif line.startswith("v:"):
                        _, _, v_height, _, v_start, _, v_end, _, v_total, _, v_clock = (
                            line.split()
                        )
                        refresh_rate = ast.literal_eval(v_clock[:-2])
                        rrate = int(round(refresh_rate))
                        # if (
                        #     xorg[screen][connector].modes.get(match_resolution)
                        #     is None
                        # ):
                        #     xorg[screen][connector].modes[match_resolution] = []
                        xorg[screen][connector].modes[match_resolution].add(rrate)
                        mode_name = f"{match_resolution}_{rrate}"
                        if preferred:
                            xorg[screen][connector].preferred = mode_name
                            xorg[screen][
                                connector
                            ].preferred_resolution = match_resolution
                            xorg[screen][connector].preferred_refreshrate = rrate
                        if current:
                            xorg[screen][connector].current = mode_name
                        try:
                              modeline = f'Modeline "{mode_name}" {pixel_clk} {h_width} {h_start} {h_end} {h_total} {v_height} {v_start} {v_end} {v_total} {" ".join(flags)}'
                              print(f"Formatted Modeline: {modeline}")
                              xorg[screen][connector].modelines[mode_name] = modeline
                        except NameError as err:
                            print(f"unbound variable used: {err}")
                        break
    return xorg


class Modeline_Data(NamedTuple):
    pixelclock: str
    hdisp: str
    hsyncstart: str
    hsyncend: str
    htotal: str
    vdisp: str
    vsyncstart: str
    vsyncend: str
    vtotal: str
    flags: str


def parse_edid_bytes(edid_bytes: str):
    vendor = "Unknown"
    model = "Unknown"
    modelines: list[str] = []
    try:
        data = subprocess.check_output(
            ["edid-decode", "-LnpsX"],
            errors="replace",
            input=edid_bytes,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError:
        pass
    else:
        for line in data.splitlines():
            line = line.strip()
            if line.startswith("Manufacturer:"):
                _, _, vendor = line.partition(": ")
            elif line.startswith("Display Product Name:"):
                _, _, model = line.partition(": ")
            elif line.startswith("Modeline"):
                # For the fields of a modeline see
                # https://en.wikipedia.org/wiki/XFree86_Modeline
                print(line)
                # ignore 'Modeline "Mode N"' part of Modeline
                _, _, line = line.split('"', 2)
                if not line:
                    print("no timing information")
                    continue
                try:
                    mode = Modeline_Data(*line.split(None, 9))
                except (ValueError, TypeError):
                    print("invalid timing information")
                    continue
                refresh = round(
                    float(mode.pixelclock)
                    * 1e6
                    / (float(mode.htotal) * float(mode.vtotal))
                )
                interlaced = "i" if "Interlace" in mode.flags else ""
                refresh = int(refresh)
                modeline_name = f'"{mode.hdisp}x{mode.vdisp}_{refresh}{interlaced}"'
                modelines.append(f"Modeline {modeline_name} {line}")
    return vendor, model, modelines


def parse_edid_data(edid_path: str) -> tuple[str, str, list[str]]:
    vendor = "Unknown"
    model = "Unknown"
    modelines: list[str] = []
    # print(f"{edid_path=}")
    try:
        data = subprocess.check_output(
            ["edid-decode", "-LnpsX", edid_path],
            errors="replace",
            universal_newlines=True,
        )
    except subprocess.CalledProcessError:
        pass
    else:
        for line in data.splitlines():
            line = line.strip()
            if line.startswith("Manufacturer:"):
                _, _, vendor = line.partition(": ")
            elif line.startswith("Display Product Name:"):
                _, _, model = line.partition(": ")
            elif line.startswith("Modeline"):
                # For the fields of a modeline see
                # https://en.wikipedia.org/wiki/XFree86_Modeline
                print(line)
                # ignore 'Modeline "Mode N"' part of Modeline
                _, _, line = line.split('"', 2)
                if not line:
                    print("no timing information")
                    continue
                try:
                    mode = Modeline_Data(*line.split(None, 9))
                except (ValueError, TypeError):
                    print("invalid timing information")
                    continue
                refresh = round(
                    float(mode.pixelclock)
                    * 1e6
                    / (float(mode.htotal) * float(mode.vtotal))
                )
                interlaced = "i" if "Interlace" in mode.flags else ""
                refresh = int(refresh)
                modeline_name = f'"{mode.hdisp}x{mode.vdisp}_{refresh}{interlaced}"'
                modelines.append(f"Modeline {modeline_name} {line}")
    return vendor, model, modelines


def collect_nvidia_data():
    BusID_RE = re.compile(
        (
            r"(?P<domain>[0-9a-fA-F]+)"
            r":"
            r"(?P<bus>[0-9a-fA-F]+)"
            r":"
            r"(?P<device>[0-9a-fA-F]+)"
            r"\."
            r"(?P<function>[0-9a-fA-F]+)"
        )
    )
    try:
        data = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,pci.bus_id", "--format=csv", "-i", "0"],
            universal_newlines=True,
        )
    except subprocess.CalledProcessError:
        pass
    except OSError:
        # nvidia-smi is not installed
        pass
    else:
        for row in csv.DictReader(
            data.splitlines(), delimiter=",", skipinitialspace=True
        ):
            name = row["name"]
            bus_id = row["pci.bus_id"]
            # pci.bus_id structure as reported by nvidia-smi: "domain:bus:device.function", in hex.
            match = BusID_RE.search(bus_id)
            if match:
                domain, bus, device, function = (int(n, 16) for n in match.groups())
                bus_id = "PCI:{:d}@{:d}:{:d}:{:d}".format(bus, domain, device, function)
                return name, bus_id
    raise ValueError

@dataclass
class DRM_Output:
    edid: str = field(default='')
    drm_connector: str = field(default='')
    xrandr_connector: str = field(default='')

@dataclass
class DRM_Connectors:
    primary: DRM_Output = field(default_factory=DRM_Output)
    secondary: DRM_Output = field(default_factory=DRM_Output)
    ignored_outputs: list[str] = field(default_factory=list)


def find_drm_connectors(connections: dict[str, dict[str, Any]])-> dict[str, Any]:
    """
    returns a dict with the following schema (secondary may be empty):
    {
        'primary': {
            'edid': 'edid.HDMI-1.bin',
            'drm_connector': 'HDMI-A-1',
            'xrandr_connector': 'HDMI-1',
        },
        'secondary': {
            'edid': 'edid.eDP-1.bin',
            'drm_connector': 'eDP-1',
            'xrandr_connector': 'eDP-1',
        }
        'ignored_outputs': ['HDMI-A-2', 'DP-1']
    }
    """
    # STATUS_GLOB = '/sys/class/drm/card[0-9]*/status'
    CONNECTOR_RE = re.compile("card[0-9a-f]+-(?P<connector>[^/]+)/status")

    def read_edid_bytes(edid_file: str | Path):
        edid_bytes = b""
        try:
            edid_bytes = Path(edid_file).read_bytes()
        except IOError:
            pass
        return edid_bytes

    xrandr_edid_bytes = read_edid_bytes(connections.get("primary", {}).get("edid", ""))
    secondary_xrandr_edid_bytes = read_edid_bytes(
        connections.get("secondary", {}).get("edid", "")
    )

    drm = {"primary": {}, "secondary": {}, "ignored_outputs": []}
    # for status_p in glob(STATUS_GLOB):
    for status_p in Path("/sys/class/drm/").glob("card[0-9a-f]*/status"):
        match = re.search(CONNECTOR_RE, str(status_p))
        if match:
            drm_connector = match.group("connector")
        else:
            continue

        try:
            connected = status_p.read_text().strip() == "connected"
            # with open(status_p) as f:
            #    connected = f.read().strip() == 'connected'
        except IOError:
            continue

        if connected:
            edid = read_edid_bytes(status_p.parent / "edid")
            if edid:
                if edid == xrandr_edid_bytes:
                    drm["primary"] = {
                        "edid": Path(connections["primary"].get("edid", "")).name,
                        "drm_connector": drm_connector,
                        "xrandr_connector": connections["primary"].get("connector", ""),
                    }
                    continue
                if secondary_xrandr_edid_bytes:
                    drm["secondary"] = {
                        "edid": Path(connections["secondary"].get("edid", "")).name,
                        "drm_connector": drm_connector,
                        "xrandr_connector": connections["secondary"].get(
                            "connector", ""
                        ),
                    }
                    continue
        drm["ignored_outputs"].append(drm_connector)
    return drm


def output_data(xorg_data: dict[str, dict[str, XrandrMonitor]], params: dict[str, Any]):
    result = {}
    drm = {}
    config: OutputConfig = OutputConfig()

    def sort_mode(mode: Mode):
        """rate modes by several criteria"""
        connection_score = 0
        rrate_score = 0
        resolution_score = 0
        preferred_rrates = params["preferred_refreshrates"]
        # [50, 60]
        preferred_resolutions = params["preferred_resolutions"]
        # ["7680x4320", "3840x2160", "1920x1080", "1280x720", "720x576"]
        preferred_outputs = params["preferred_outputs"]
        # ["HDMI", "DP", "DVI", "VGA"]
        if mode.refreshrate in preferred_rrates:
            rrate_score = len(preferred_rrates) - preferred_rrates.index(mode.refreshrate)
        if mode.resolution in preferred_resolutions:
            resolution_score = len(preferred_resolutions) - preferred_resolutions.index(
                mode.resolution
            )
        x_resolution, y_resolution = (int(n) for n in mode.resolution.split("x"))
        connection = mode.connection.split("-")[0]
        if connection in preferred_outputs:
            connection_score = len(preferred_outputs) - preferred_outputs.index(connection)
        return (rrate_score, resolution_score, x_resolution, y_resolution, connection_score)

    if xorg_data:
        modes: list[Mode] = []
        for _, screen_data in xorg_data.items():
            for connector, connection_data in screen_data.items():
                if connection_data.edid:
                    connection_data.edid_file.write_bytes(connection_data.binary_edid)
                for resolution, refreshrates in connection_data.modes.items():
                    for refreshrate in refreshrates:
                        modes.append(Mode(connector, resolution, refreshrate))
        if modes:
            try:
                gpu_name, bus_id = collect_nvidia_data()
            except ValueError:
                gpu_name = None
                bus_id = None

            def create_entry(
                display_dict: dict[str, Any],
                name: str,
                connector: str,
                resolution: str,
                refreshrate: int,
                vendor: str,
                model: str,
                modelines: list[str],
            ):
                display_dict[name] = {
                    "connector": connector,
                    "resolution": resolution,
                    "refreshrate": refreshrate,
                    "edid": f"/etc/X11/edid.{connector}.bin",
                    "mode": f"{resolution}_{refreshrate}",
                    "vendor": vendor,
                    "model": model,
                    "modelines": modelines,
                }
                if gpu_name and bus_id:
                    result[name]["gpu_name"] = gpu_name
                    result[name]["bus_id"] = bus_id

            # for mode in modes:
            #    connector_edid = f'/etc/X11/edid.{mode.connector}.bin'
            #    vendor, model, modelines= parse_edid_data(connector_edid)
            #    create_entry(result, mode.connector, mode.connector, mode.resolution, mode.refreshrate, vendor, model, modelines)

            primary_mode = max(modes, key=sort_mode)
            connector_0_edid = f"/etc/X11/edid.{primary_mode.connection}.bin"
            vendor_0, model_0, modelines_0 = parse_edid_data(connector_0_edid)
            config.primary = MonitorConfig(
                connector=primary_mode.connection,
                resolution=primary_mode.resolution,
                refreshrate=primary_mode.refreshrate,
            )
            create_entry(
                result,
                "primary",
                primary_mode.connection,
                primary_mode.resolution,
                primary_mode.refreshrate,
                vendor_0,
                model_0,
                modelines_0,
            )

            # check if additional monitors exist
            other_modes = [mode for mode in modes if mode.connection != primary_mode.connection]
            print(f"{other_modes=}")
            if other_modes:
                secondary_mode: Mode = max(
                    other_modes, key=sort_mode
                )
                connector_1_edid = "/etc/X11/edid.{}.bin".format(secondary_mode.connection)
                vendor_1, model_1, modelines_1 = parse_edid_data(connector_1_edid)
                config.secondary = MonitorConfig(
                    connector=secondary_mode.connection,
                    resolution=secondary_mode.resolution,
                    refreshrate=secondary_mode.refreshrate,
                )
                create_entry(
                    result,
                    "secondary",
                    secondary_mode.connection,
                    secondary_mode.resolution,
                    secondary_mode.refreshrate,
                    vendor_1,
                    model_1,
                    modelines_1,
                )

            # TODO: get DRM outputs to ignore
            drm = find_drm_connectors(result)  # TODO: is this needed?

            def match_drm_connectors(
                data: dict[str, dict[str, XrandrMonitor]],
            ) -> None:
                CONNECTOR_RE = re.compile(
                    "card[0-9a-f]+-(?P<connector>[^/]+)/status"
                )
                for status_p in Path("/sys/class/drm/").glob(
                    "card[0-9a-f]*/status"
                ):
                    match = re.search(CONNECTOR_RE, str(status_p))
                    if match:
                        drm_connector = match.group("connector")
                    else:
                        continue

                    try:
                        connected = status_p.read_text().strip() == "connected"
                    except IOError:
                        continue

                    if connected:
                        match = re.search(CONNECTOR_RE, str(status_p))
                        if match:
                            drm_connector = match.group("connector")
                        else:
                            continue
                        # get the edid, if possible
                        edid_path = status_p.parent / "edid"
                        try:
                            drm_edid = edid_path.read_bytes()
                        except IOError:
                            continue

                        if not drm_edid:
                            continue
                        for screen, connector_dict in xorg_data.items():
                            for connector, monitor_data in connector_dict.items():
                                if not monitor_data.edid:
                                    continue
                                if drm_edid == monitor_data.binary_edid:
                                    # print(f"found matching edid for {drm_connector=} and {connector=}")
                                    data[screen][
                                        connector
                                    ].drm_connector = drm_connector
                                    break

            match_drm_connectors(xorg_data)

    # convert the dataclass instances to dicts
    xorg_result: defaultdict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for screen, connector_dict in xorg_data.items():
        for connector, connector_data in connector_dict.items():
            xorg_result[screen][connector] = asdict(connector_data)

    config_result = asdict(config)

    return {
        "xrandr": xorg_result,
        "xorg": result,
        "drm": drm,
        "XorgConfig": config_result,
    }


data = '''
Screen 0: minimum 320 x 200, current 1280 x 1024, maximum 16384 x 16384
DVI-D-1 connected primary 1280x1024+0+0 (0x46) normal (normal left inverted right x axis y axis) 338mm x 270mm
	Identifier: 0x42
	Timestamp:  6581173
	Subpixel:   unknown
	Gamma:      1.0:1.0:1.0
	Brightness: 1.0
	Clones:
	CRTC:       0
	CRTCs:      0 1 2 3
	Transform:  1.000000 0.000000 0.000000
	            0.000000 1.000000 0.000000
	            0.000000 0.000000 1.000000
	           filter:
	EDID:
		00ffffffffffff0004895d2320090000
		0f0d0103e0211b782ac5c6a3574a9c23
		124f5421080031404540614081800101
		010101010101302a009851002a403070
		1300520e1100001ea00f200031581c20
		28801400520e1100001e000000ff0033
		31355430324530323333360a000000fc
		0041444920413731350a20202020002b
	dithering depth: auto
		supported: auto, 6 bpc, 8 bpc
	dithering mode: auto
		supported: auto, off, static 2x2, dynamic 2x2, temporal
	scaling mode: None
		supported: None, Full, Center, Full aspect
	color vibrance: 150
		range: (0, 200)
	vibrant hue: 90
		range: (0, 180)
	underscan vborder: 0
		range: (0, 128)
	underscan hborder: 0
		range: (0, 128)
	underscan: off
		supported: auto, off, on
	link-status: Good
		supported: Good, Bad
	CTM: 	1.000000 0.000000 0.000000
		0.000000 1.000000 0.000000
		0.000000 0.000000 1.000000
	CONNECTOR_ID: 43
		supported: 43
	non-desktop: 0
		range: (0, 1)
  1280x1024 (0x46) 108.000MHz +HSync +VSync *current +preferred
        h: width  1280 start 1328 end 1440 total 1688 skew    0 clock  63.98KHz
        v: height 1024 start 1025 end 1028 total 1066           clock  60.02Hz
  1280x960 (0x47) 108.035MHz +HSync +VSync
        h: width  1280 start 1376 end 1488 total 1800 skew    0 clock  60.02KHz
        v: height  960 start  961 end  964 total 1000           clock  60.02Hz
  1280x800 (0x48) 71.130MHz +HSync -VSync
        h: width  1280 start 1328 end 1360 total 1440 skew    0 clock  49.40KHz
        v: height  800 start  803 end  809 total  823           clock  60.02Hz
  1280x720 (0x49) 64.043MHz +HSync -VSync
        h: width  1280 start 1328 end 1360 total 1440 skew    0 clock  44.47KHz
        v: height  720 start  723 end  728 total  741           clock  60.02Hz
  1024x768 (0x4a) 65.017MHz -HSync -VSync
        h: width  1024 start 1048 end 1184 total 1344 skew    0 clock  48.38KHz
        v: height  768 start  771 end  777 total  806           clock  60.02Hz
  1024x768 (0x4b) 65.000MHz -HSync -VSync
        h: width  1024 start 1048 end 1184 total 1344 skew    0 clock  48.36KHz
        v: height  768 start  771 end  777 total  806           clock  60.00Hz
  960x720 (0x4c) 117.038MHz -HSync +VSync DoubleScan
        h: width   960 start 1024 end 1128 total 1300 skew    0 clock  90.03KHz
        v: height  720 start  720 end  722 total  750           clock  60.02Hz
  928x696 (0x4d) 109.093MHz -HSync +VSync DoubleScan
        h: width   928 start  976 end 1088 total 1264 skew    0 clock  86.31KHz
        v: height  696 start  696 end  698 total  719           clock  60.02Hz
  896x672 (0x4e) 102.409MHz -HSync +VSync DoubleScan
        h: width   896 start  960 end 1060 total 1224 skew    0 clock  83.67KHz
        v: height  672 start  672 end  674 total  697           clock  60.02Hz
  1024x576 (0x4f) 42.140MHz +HSync -VSync
        h: width  1024 start 1072 end 1104 total 1184 skew    0 clock  35.59KHz
        v: height  576 start  579 end  584 total  593           clock  60.02Hz
  960x600 (0x50) 77.026MHz +HSync -VSync DoubleScan
        h: width   960 start  984 end 1000 total 1040 skew    0 clock  74.06KHz
        v: height  600 start  601 end  604 total  617           clock  60.02Hz
  960x540 (0x51) 37.375MHz +HSync -VSync
        h: width   960 start 1008 end 1040 total 1120 skew    0 clock  33.37KHz
        v: height  540 start  543 end  548 total  556           clock  60.02Hz
  800x600 (0x52) 40.000MHz +HSync +VSync
        h: width   800 start  840 end  968 total 1056 skew    0 clock  37.88KHz
        v: height  600 start  601 end  605 total  628           clock  60.32Hz
  800x600 (0x53) 38.412MHz +HSync +VSync
        h: width   800 start  824 end  896 total 1024 skew    0 clock  37.51KHz
        v: height  600 start  601 end  603 total  625           clock  60.02Hz
  840x525 (0x54) 59.635MHz +HSync -VSync DoubleScan
        h: width   840 start  864 end  880 total  920 skew    0 clock  64.82KHz
        v: height  525 start  526 end  529 total  540           clock  60.02Hz
  864x486 (0x55) 30.730MHz +HSync -VSync
        h: width   864 start  912 end  944 total 1024 skew    0 clock  30.01KHz
        v: height  486 start  489 end  494 total  500           clock  60.02Hz
  700x525 (0x56) 61.044MHz +HSync +VSync DoubleScan
        h: width   700 start  744 end  820 total  940 skew    0 clock  64.94KHz
        v: height  525 start  526 end  532 total  541           clock  60.02Hz
  800x450 (0x57) 48.908MHz +HSync -VSync DoubleScan
        h: width   800 start  824 end  840 total  880 skew    0 clock  55.58KHz
        v: height  450 start  451 end  454 total  463           clock  60.02Hz
  640x512 (0x58) 54.000MHz +HSync +VSync DoubleScan
        h: width   640 start  664 end  720 total  844 skew    0 clock  63.98KHz
        v: height  512 start  512 end  514 total  533           clock  60.02Hz
  700x450 (0x59) 43.351MHz +HSync -VSync DoubleScan
        h: width   700 start  724 end  740 total  780 skew    0 clock  55.58KHz
        v: height  450 start  451 end  456 total  463           clock  60.02Hz
  640x480 (0x5a) 25.208MHz -HSync -VSync
        h: width   640 start  656 end  752 total  800 skew    0 clock  31.51KHz
        v: height  480 start  490 end  492 total  525           clock  60.02Hz
  640x480 (0x5b) 25.175MHz -HSync -VSync
        h: width   640 start  656 end  752 total  800 skew    0 clock  31.47KHz
        v: height  480 start  490 end  492 total  525           clock  59.94Hz
  720x405 (0x5c) 22.130MHz +HSync -VSync
        h: width   720 start  768 end  800 total  880 skew    0 clock  25.15KHz
        v: height  405 start  408 end  413 total  419           clock  60.02Hz
  684x384 (0x5d) 36.225MHz +HSync -VSync DoubleScan
        h: width   684 start  708 end  724 total  764 skew    0 clock  47.41KHz
        v: height  384 start  385 end  390 total  395           clock  60.02Hz
  640x360 (0x5e) 17.957MHz +HSync -VSync
        h: width   640 start  688 end  720 total  800 skew    0 clock  22.45KHz
        v: height  360 start  363 end  368 total  374           clock  60.02Hz
  512x384 (0x5f) 32.508MHz -HSync -VSync DoubleScan
        h: width   512 start  524 end  592 total  672 skew    0 clock  48.38KHz
        v: height  384 start  385 end  388 total  403           clock  60.02Hz
  512x288 (0x60) 21.034MHz +HSync -VSync DoubleScan
        h: width   512 start  536 end  552 total  592 skew    0 clock  35.53KHz
        v: height  288 start  289 end  292 total  296           clock  60.02Hz
  480x270 (0x61) 18.687MHz +HSync -VSync DoubleScan
        h: width   480 start  504 end  520 total  560 skew    0 clock  33.37KHz
        v: height  270 start  271 end  274 total  278           clock  60.02Hz
  400x300 (0x62) 19.175MHz +HSync +VSync DoubleScan
        h: width   400 start  412 end  448 total  512 skew    0 clock  37.45KHz
        v: height  300 start  300 end  301 total  312           clock  60.02Hz
  432x243 (0x63) 15.365MHz +HSync -VSync DoubleScan
        h: width   432 start  456 end  472 total  512 skew    0 clock  30.01KHz
        v: height  243 start  244 end  247 total  250           clock  60.02Hz
  320x240 (0x64) 12.580MHz -HSync -VSync DoubleScan
        h: width   320 start  328 end  376 total  400 skew    0 clock  31.45KHz
        v: height  240 start  245 end  246 total  262           clock  60.02Hz
  360x202 (0x65) 11.038MHz +HSync -VSync DoubleScan
        h: width   360 start  384 end  400 total  440 skew    0 clock  25.09KHz
        v: height  202 start  204 end  206 total  209           clock  60.02Hz
  320x180 (0x66)  8.978MHz +HSync -VSync DoubleScan
        h: width   320 start  344 end  360 total  400 skew    0 clock  22.45KHz
        v: height  180 start  181 end  184 total  187           clock  60.01Hz
'''

data2 = '''Screen 0: minimum 320 x 200, current 1280 x 1024, maximum 16384 x 16384
HDMI-1 connected 1280x1024+0+0 (0x46) normal (normal left inverted right x axis y axis) 1600mm x 900mm
	Identifier: 0x43
	Timestamp:  6581173
	Subpixel:   unknown
	Gamma:      1.0:1.0:1.0
	Brightness: 1.0
	Clones:
	CRTC:       1
	CRTCs:      0 1 2 3
	Transform:  1.000000 0.000000 0.000000
	            0.000000 1.000000 0.000000
	            0.000000 0.000000 1.000000
	           filter:
	EDID:
		00ffffffffffff001e6d010001010101
		011f010380a05a780aee91a3544c9926
		0f5054a1080031404540614071408180
		d1c00101010108e80030f2705a80b058
		8a0040846300001e565e00a0a0a02950
		3020350040846300001e000000fd0018
		781e873c000a202020202020000000fc
		004c472054562053534352320a200148
		02034ff15a6160101f66650413051403
		021220212215015d5e5f6263643f4029
		0957071507505507006e030c002000b8
		3c2c00800102030468d85dc40178800b
		02e200cfe305c000e3060d01e20f3300
		00000000000000000000000000000000
		00000000000000000000000000000000
		000000000000000000000000000000aa
	dithering depth: auto
		supported: auto, 6 bpc, 8 bpc
	dithering mode: auto
		supported: auto, off, static 2x2, dynamic 2x2, temporal
	scaling mode: None
		supported: None, Full, Center, Full aspect
	color vibrance: 150
		range: (0, 200)
	vibrant hue: 90
		range: (0, 180)
	underscan vborder: 0
		range: (0, 128)
	underscan hborder: 0
		range: (0, 128)
	underscan: off
		supported: auto, off, on
	link-status: Good
		supported: Good, Bad
	CTM: 	1.000000 0.000000 0.000000
		0.000000 1.000000 0.000000
		0.000000 0.000000 1.000000
	CONNECTOR_ID: 45
		supported: 45
	non-desktop: 0
		range: (0, 1)
  4096x2160 (0x67) 297.000MHz +HSync +VSync
        h: width  4096 start 4184 end 4272 total 4400 skew    0 clock  67.50KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  30.00Hz
  4096x2160 (0x68) 297.000MHz +HSync +VSync
        h: width  4096 start 5064 end 5152 total 5280 skew    0 clock  56.25KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  25.00Hz
  4096x2160 (0x69) 297.000MHz +HSync +VSync
        h: width  4096 start 5116 end 5204 total 5500 skew    0 clock  54.00KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  24.00Hz
  4096x2160 (0x6a) 296.703MHz +HSync +VSync
        h: width  4096 start 4184 end 4272 total 4400 skew    0 clock  67.43KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  29.97Hz
  4096x2160 (0x6b) 296.703MHz +HSync +VSync
        h: width  4096 start 5116 end 5204 total 5500 skew    0 clock  53.95KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  23.98Hz
  3840x2160 (0x6c) 533.000MHz +HSync -VSync
        h: width  3840 start 3888 end 3920 total 4000 skew    0 clock 133.25KHz
        v: height 2160 start 2163 end 2168 total 2222           clock  59.97Hz
  3840x2160 (0x6d) 297.000MHz +HSync +VSync
        h: width  3840 start 4016 end 4104 total 4400 skew    0 clock  67.50KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  30.00Hz
  3840x2160 (0x6e) 297.000MHz +HSync +VSync
        h: width  3840 start 4896 end 4984 total 5280 skew    0 clock  56.25KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  25.00Hz
  3840x2160 (0x6f) 297.000MHz +HSync +VSync
        h: width  3840 start 5116 end 5204 total 5500 skew    0 clock  54.00KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  24.00Hz
  3840x2160 (0x70) 296.703MHz +HSync +VSync
        h: width  3840 start 4016 end 4104 total 4400 skew    0 clock  67.43KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  29.97Hz
  3840x2160 (0x71) 296.703MHz +HSync +VSync
        h: width  3840 start 5116 end 5204 total 5500 skew    0 clock  53.95KHz
        v: height 2160 start 2168 end 2178 total 2250           clock  23.98Hz
  3200x1800 (0x72) 373.000MHz +HSync -VSync
        h: width  3200 start 3248 end 3280 total 3360 skew    0 clock 111.01KHz
        v: height 1800 start 1803 end 1808 total 1852           clock  59.94Hz
  2880x1620 (0x73) 303.750MHz +HSync -VSync
        h: width  2880 start 2928 end 2960 total 3040 skew    0 clock  99.92KHz
        v: height 1620 start 1623 end 1628 total 1666           clock  59.97Hz
  2560x1600 (0x74) 268.500MHz +HSync -VSync
        h: width  2560 start 2608 end 2640 total 2720 skew    0 clock  98.71KHz
        v: height 1600 start 1603 end 1609 total 1646           clock  59.97Hz
  2560x1440 (0x75) 241.500MHz +HSync +VSync
        h: width  2560 start 2608 end 2640 total 2720 skew    0 clock  88.79KHz
        v: height 1440 start 1443 end 1448 total 1481           clock  59.95Hz
  2560x1440 (0x76) 241.500MHz +HSync -VSync
        h: width  2560 start 2608 end 2640 total 2720 skew    0 clock  88.79KHz
        v: height 1440 start 1443 end 1448 total 1481           clock  59.95Hz
  2048x1536 (0x77) 388.040MHz -HSync +VSync
        h: width  2048 start 2216 end 2440 total 2832 skew    0 clock 137.02KHz
        v: height 1536 start 1537 end 1540 total 1612           clock  85.00Hz
  2048x1536 (0x78) 340.480MHz -HSync +VSync
        h: width  2048 start 2216 end 2440 total 2832 skew    0 clock 120.23KHz
        v: height 1536 start 1537 end 1540 total 1603           clock  75.00Hz
  2048x1536 (0x79) 266.950MHz -HSync +VSync
        h: width  2048 start 2200 end 2424 total 2800 skew    0 clock  95.34KHz
        v: height 1536 start 1537 end 1540 total 1589           clock  60.00Hz
  1920x1440 (0x7a) 341.350MHz -HSync +VSync
        h: width  1920 start 2072 end 2288 total 2656 skew    0 clock 128.52KHz
        v: height 1440 start 1441 end 1444 total 1512           clock  85.00Hz
  1920x1440 (0x7b) 297.000MHz -HSync +VSync
        h: width  1920 start 2064 end 2288 total 2640 skew    0 clock 112.50KHz
        v: height 1440 start 1441 end 1444 total 1500           clock  75.00Hz
  1920x1440 (0x7c) 234.000MHz -HSync +VSync
        h: width  1920 start 2048 end 2256 total 2600 skew    0 clock  90.00KHz
        v: height 1440 start 1441 end 1444 total 1500           clock  60.00Hz
  1856x1392 (0x7d) 288.000MHz -HSync +VSync
        h: width  1856 start 1984 end 2208 total 2560 skew    0 clock 112.50KHz
        v: height 1392 start 1393 end 1396 total 1500           clock  75.00Hz
  1856x1392 (0x7e) 218.300MHz -HSync +VSync
        h: width  1856 start 1952 end 2176 total 2528 skew    0 clock  86.35KHz
        v: height 1392 start 1393 end 1396 total 1439           clock  60.01Hz
  1792x1344 (0x7f) 261.000MHz -HSync +VSync
        h: width  1792 start 1888 end 2104 total 2456 skew    0 clock 106.27KHz
        v: height 1344 start 1345 end 1348 total 1417           clock  75.00Hz
  1792x1344 (0x80) 204.800MHz -HSync +VSync
        h: width  1792 start 1920 end 2120 total 2448 skew    0 clock  83.66KHz
        v: height 1344 start 1345 end 1348 total 1394           clock  60.01Hz
  2048x1152 (0x81) 156.750MHz +HSync -VSync
        h: width  2048 start 2096 end 2128 total 2208 skew    0 clock  70.99KHz
        v: height 1152 start 1155 end 1160 total 1185           clock  59.91Hz
  1920x1200 (0x82) 154.000MHz +HSync -VSync
        h: width  1920 start 1968 end 2000 total 2080 skew    0 clock  74.04KHz
        v: height 1200 start 1203 end 1209 total 1235           clock  59.95Hz
  1920x1080 (0x83) 297.000MHz +HSync +VSync
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock 135.00KHz
        v: height 1080 start 1084 end 1089 total 1125           clock 120.00Hz
  1920x1080 (0x84) 297.000MHz +HSync +VSync
        h: width  1920 start 2448 end 2492 total 2640 skew    0 clock 112.50KHz
        v: height 1080 start 1084 end 1089 total 1125           clock 100.00Hz
  1920x1080 (0x85) 296.703MHz +HSync +VSync
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock 134.87KHz
        v: height 1080 start 1084 end 1089 total 1125           clock 119.88Hz
  1920x1080 (0x86) 148.500MHz -HSync -VSync
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  67.50KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  60.00Hz
  1920x1080 (0x87) 148.500MHz +HSync +VSync
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  67.50KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  60.00Hz
  1920x1080 (0x88) 148.500MHz +HSync +VSync
        h: width  1920 start 2448 end 2492 total 2640 skew    0 clock  56.25KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  50.00Hz
  1920x1080 (0x89) 148.352MHz +HSync +VSync
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  67.43KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  59.94Hz
  1920x1080 (0x8a) 138.500MHz +HSync -VSync
        h: width  1920 start 1968 end 2000 total 2080 skew    0 clock  66.59KHz
        v: height 1080 start 1083 end 1088 total 1111           clock  59.93Hz
  1920x1080i (0x8b) 74.250MHz +HSync +VSync Interlace
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  33.75KHz
        v: height 1080 start 1084 end 1094 total 1125           clock  60.00Hz
  1920x1080i (0x8c) 74.250MHz +HSync +VSync Interlace
        h: width  1920 start 2448 end 2492 total 2640 skew    0 clock  28.12KHz
        v: height 1080 start 1084 end 1094 total 1125           clock  50.00Hz
  1920x1080 (0x8d) 74.250MHz +HSync +VSync
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  33.75KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  30.00Hz
  1920x1080 (0x8e) 74.250MHz +HSync +VSync
        h: width  1920 start 2448 end 2492 total 2640 skew    0 clock  28.12KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  25.00Hz
  1920x1080 (0x8f) 74.250MHz +HSync +VSync
        h: width  1920 start 2558 end 2602 total 2750 skew    0 clock  27.00KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  24.00Hz
  1920x1080i (0x90) 74.176MHz +HSync +VSync Interlace
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  33.72KHz
        v: height 1080 start 1084 end 1094 total 1125           clock  59.94Hz
  1920x1080 (0x91) 74.176MHz +HSync +VSync
        h: width  1920 start 2008 end 2052 total 2200 skew    0 clock  33.72KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  29.97Hz
  1920x1080 (0x92) 74.176MHz +HSync +VSync
        h: width  1920 start 2558 end 2602 total 2750 skew    0 clock  26.97KHz
        v: height 1080 start 1084 end 1089 total 1125           clock  23.98Hz
  1600x1200 (0x93) 229.500MHz +HSync +VSync
        h: width  1600 start 1664 end 1856 total 2160 skew    0 clock 106.25KHz
        v: height 1200 start 1201 end 1204 total 1250           clock  85.00Hz
  1600x1200 (0x94) 202.500MHz +HSync +VSync
        h: width  1600 start 1664 end 1856 total 2160 skew    0 clock  93.75KHz
        v: height 1200 start 1201 end 1204 total 1250           clock  75.00Hz
  1600x1200 (0x95) 189.000MHz +HSync +VSync
        h: width  1600 start 1664 end 1856 total 2160 skew    0 clock  87.50KHz
        v: height 1200 start 1201 end 1204 total 1250           clock  70.00Hz
  1600x1200 (0x96) 175.500MHz +HSync +VSync
        h: width  1600 start 1664 end 1856 total 2160 skew    0 clock  81.25KHz
        v: height 1200 start 1201 end 1204 total 1250           clock  65.00Hz
  1600x1200 (0x97) 162.000MHz +HSync +VSync
        h: width  1600 start 1664 end 1856 total 2160 skew    0 clock  75.00KHz
        v: height 1200 start 1201 end 1204 total 1250           clock  60.00Hz
  1680x1050 (0x98) 119.000MHz +HSync -VSync
        h: width  1680 start 1728 end 1760 total 1840 skew    0 clock  64.67KHz
        v: height 1050 start 1053 end 1059 total 1080           clock  59.88Hz
  1400x1050 (0x99) 155.800MHz +HSync +VSync
        h: width  1400 start 1464 end 1784 total 1912 skew    0 clock  81.49KHz
        v: height 1050 start 1052 end 1064 total 1090           clock  74.76Hz
  1400x1050 (0x9a) 122.000MHz +HSync +VSync
        h: width  1400 start 1488 end 1640 total 1880 skew    0 clock  64.89KHz
        v: height 1050 start 1052 end 1064 total 1082           clock  59.98Hz
  1600x900 (0x9b) 97.500MHz +HSync -VSync
        h: width  1600 start 1648 end 1680 total 1760 skew    0 clock  55.40KHz
        v: height  900 start  903 end  908 total  926           clock  59.82Hz
  1280x1024 (0x9c) 157.500MHz +HSync +VSync
        h: width  1280 start 1344 end 1504 total 1728 skew    0 clock  91.15KHz
        v: height 1024 start 1025 end 1028 total 1072           clock  85.02Hz
  1280x1024 (0x9d) 135.000MHz +HSync +VSync
        h: width  1280 start 1296 end 1440 total 1688 skew    0 clock  79.98KHz
        v: height 1024 start 1025 end 1028 total 1066           clock  75.02Hz
  1280x1024 (0x46) 108.000MHz +HSync +VSync *current
        h: width  1280 start 1328 end 1440 total 1688 skew    0 clock  63.98KHz
        v: height 1024 start 1025 end 1028 total 1066           clock  60.02Hz
  1400x900 (0x9e) 86.500MHz +HSync -VSync
        h: width  1400 start 1448 end 1480 total 1560 skew    0 clock  55.45KHz
        v: height  900 start  903 end  913 total  926           clock  59.88Hz
  1280x960 (0x9f) 148.500MHz +HSync +VSync
        h: width  1280 start 1344 end 1504 total 1728 skew    0 clock  85.94KHz
        v: height  960 start  961 end  964 total 1011           clock  85.00Hz
  1280x960 (0xa0) 108.000MHz +HSync +VSync
        h: width  1280 start 1376 end 1488 total 1800 skew    0 clock  60.00KHz
        v: height  960 start  961 end  964 total 1000           clock  60.00Hz
  1440x810 (0xa1) 151.875MHz +HSync -VSync DoubleScan
        h: width  1440 start 1464 end 1480 total 1520 skew    0 clock  99.92KHz
        v: height  810 start  811 end  814 total  833           clock  59.97Hz
  1368x768 (0xa2) 72.250MHz +HSync -VSync
        h: width  1368 start 1416 end 1448 total 1528 skew    0 clock  47.28KHz
        v: height  768 start  771 end  781 total  790           clock  59.85Hz
  1280x800 (0xa3) 71.000MHz +HSync -VSync
        h: width  1280 start 1328 end 1360 total 1440 skew    0 clock  49.31KHz
        v: height  800 start  803 end  809 total  823           clock  59.91Hz
  1152x864 (0xa4) 108.000MHz +HSync +VSync
        h: width  1152 start 1216 end 1344 total 1600 skew    0 clock  67.50KHz
        v: height  864 start  865 end  868 total  900           clock  75.00Hz
  1152x864 (0xa5) 81.579MHz -HSync +VSync
        h: width  1152 start 1216 end 1336 total 1520 skew    0 clock  53.67KHz
        v: height  864 start  865 end  868 total  895           clock  59.97Hz
  1280x720 (0xa6) 74.250MHz +HSync +VSync
        h: width  1280 start 1390 end 1430 total 1650 skew    0 clock  45.00KHz
        v: height  720 start  725 end  730 total  750           clock  60.00Hz
  1280x720 (0xa7) 74.250MHz +HSync +VSync
        h: width  1280 start 1720 end 1760 total 1980 skew    0 clock  37.50KHz
        v: height  720 start  725 end  730 total  750           clock  50.00Hz
  1280x720 (0xa8) 74.176MHz +HSync +VSync
        h: width  1280 start 1390 end 1430 total 1650 skew    0 clock  44.96KHz
        v: height  720 start  725 end  730 total  750           clock  59.94Hz
  1280x720 (0xa9) 63.750MHz +HSync -VSync
        h: width  1280 start 1328 end 1360 total 1440 skew    0 clock  44.27KHz
        v: height  720 start  723 end  728 total  741           clock  59.74Hz
  1024x768 (0xaa) 94.500MHz +HSync +VSync
        h: width  1024 start 1072 end 1168 total 1376 skew    0 clock  68.68KHz
        v: height  768 start  769 end  772 total  808           clock  85.00Hz
  1024x768 (0xab) 78.750MHz +HSync +VSync
        h: width  1024 start 1040 end 1136 total 1312 skew    0 clock  60.02KHz
        v: height  768 start  769 end  772 total  800           clock  75.03Hz
  1024x768 (0xac) 75.000MHz -HSync -VSync
        h: width  1024 start 1048 end 1184 total 1328 skew    0 clock  56.48KHz
        v: height  768 start  771 end  777 total  806           clock  70.07Hz
  1024x768 (0x4b) 65.000MHz -HSync -VSync
        h: width  1024 start 1048 end 1184 total 1344 skew    0 clock  48.36KHz
        v: height  768 start  771 end  777 total  806           clock  60.00Hz
  1024x768i (0xad) 44.900MHz +HSync +VSync Interlace
        h: width  1024 start 1032 end 1208 total 1264 skew    0 clock  35.52KHz
        v: height  768 start  768 end  776 total  817           clock  86.96Hz
  960x720 (0xae) 170.675MHz -HSync +VSync DoubleScan
        h: width   960 start 1036 end 1144 total 1328 skew    0 clock 128.52KHz
        v: height  720 start  720 end  722 total  756           clock  85.00Hz
  960x720 (0xaf) 148.500MHz -HSync +VSync DoubleScan
        h: width   960 start 1032 end 1144 total 1320 skew    0 clock 112.50KHz
        v: height  720 start  720 end  722 total  750           clock  75.00Hz
  960x720 (0xb0) 117.000MHz -HSync +VSync DoubleScan
        h: width   960 start 1024 end 1128 total 1300 skew    0 clock  90.00KHz
        v: height  720 start  720 end  722 total  750           clock  60.00Hz
  928x696 (0xb1) 144.000MHz -HSync +VSync DoubleScan
        h: width   928 start  992 end 1104 total 1280 skew    0 clock 112.50KHz
        v: height  696 start  696 end  698 total  750           clock  75.00Hz
  928x696 (0xb2) 109.150MHz -HSync +VSync DoubleScan
        h: width   928 start  976 end 1088 total 1264 skew    0 clock  86.35KHz
        v: height  696 start  696 end  698 total  719           clock  60.05Hz
  896x672 (0xb3) 130.500MHz -HSync +VSync DoubleScan
        h: width   896 start  944 end 1052 total 1228 skew    0 clock 106.27KHz
        v: height  672 start  672 end  674 total  708           clock  75.05Hz
  896x672 (0xb4) 102.400MHz -HSync +VSync DoubleScan
        h: width   896 start  960 end 1060 total 1224 skew    0 clock  83.66KHz
        v: height  672 start  672 end  674 total  697           clock  60.01Hz
  1024x576 (0xb5) 42.000MHz +HSync -VSync
        h: width  1024 start 1072 end 1104 total 1184 skew    0 clock  35.47KHz
        v: height  576 start  579 end  584 total  593           clock  59.82Hz
  960x600 (0xb6) 77.000MHz +HSync -VSync DoubleScan
        h: width   960 start  984 end 1000 total 1040 skew    0 clock  74.04KHz
        v: height  600 start  601 end  604 total  617           clock  60.00Hz
  832x624 (0xb7) 57.284MHz -HSync -VSync
        h: width   832 start  864 end  928 total 1152 skew    0 clock  49.73KHz
        v: height  624 start  625 end  628 total  667           clock  74.55Hz
  960x540 (0xb8) 37.250MHz +HSync -VSync
        h: width   960 start 1008 end 1040 total 1120 skew    0 clock  33.26KHz
        v: height  540 start  543 end  548 total  556           clock  59.82Hz
  800x600 (0xb9) 94.500MHz +HSync +VSync DoubleScan
        h: width   800 start  832 end  928 total 1080 skew    0 clock  87.50KHz
        v: height  600 start  600 end  602 total  625           clock  70.00Hz
  800x600 (0xba) 87.750MHz +HSync +VSync DoubleScan
        h: width   800 start  832 end  928 total 1080 skew    0 clock  81.25KHz
        v: height  600 start  600 end  602 total  625           clock  65.00Hz
  800x600 (0xbb) 56.300MHz +HSync +VSync
        h: width   800 start  832 end  896 total 1048 skew    0 clock  53.72KHz
        v: height  600 start  601 end  604 total  631           clock  85.14Hz
  800x600 (0xbc) 50.000MHz +HSync +VSync
        h: width   800 start  856 end  976 total 1040 skew    0 clock  48.08KHz
        v: height  600 start  637 end  643 total  666           clock  72.19Hz
  800x600 (0xbd) 49.500MHz +HSync +VSync
        h: width   800 start  816 end  896 total 1056 skew    0 clock  46.88KHz
        v: height  600 start  601 end  604 total  625           clock  75.00Hz
  800x600 (0x52) 40.000MHz +HSync +VSync
        h: width   800 start  840 end  968 total 1056 skew    0 clock  37.88KHz
        v: height  600 start  601 end  605 total  628           clock  60.32Hz
  800x600 (0xbe) 36.000MHz +HSync +VSync
        h: width   800 start  824 end  896 total 1024 skew    0 clock  35.16KHz
        v: height  600 start  601 end  603 total  625           clock  56.25Hz
  840x525 (0xbf) 59.500MHz +HSync -VSync DoubleScan
        h: width   840 start  864 end  880 total  920 skew    0 clock  64.67KHz
        v: height  525 start  526 end  529 total  540           clock  59.88Hz
  864x486 (0xc0) 30.500MHz +HSync -VSync
        h: width   864 start  912 end  944 total 1024 skew    0 clock  29.79KHz
        v: height  486 start  489 end  494 total  500           clock  59.57Hz
  720x576 (0xc1) 27.000MHz -HSync -VSync
        h: width   720 start  732 end  796 total  864 skew    0 clock  31.25KHz
        v: height  576 start  581 end  586 total  625           clock  50.00Hz
  700x525 (0xc2) 77.900MHz +HSync +VSync DoubleScan
        h: width   700 start  732 end  892 total  956 skew    0 clock  81.49KHz
        v: height  525 start  526 end  532 total  545           clock  74.76Hz
  700x525 (0xc3) 61.000MHz +HSync +VSync DoubleScan
        h: width   700 start  744 end  820 total  940 skew    0 clock  64.89KHz
        v: height  525 start  526 end  532 total  541           clock  59.98Hz
  800x450 (0xc4) 48.750MHz +HSync -VSync DoubleScan
        h: width   800 start  824 end  840 total  880 skew    0 clock  55.40KHz
        v: height  450 start  451 end  454 total  463           clock  59.82Hz
  720x480 (0xc5) 27.027MHz -HSync -VSync
        h: width   720 start  736 end  798 total  858 skew    0 clock  31.50KHz
        v: height  480 start  489 end  495 total  525           clock  60.00Hz
  720x480 (0xc6) 27.000MHz -HSync -VSync
        h: width   720 start  736 end  798 total  858 skew    0 clock  31.47KHz
        v: height  480 start  489 end  495 total  525           clock  59.94Hz
  640x512 (0xc7) 78.750MHz +HSync +VSync DoubleScan
        h: width   640 start  672 end  752 total  864 skew    0 clock  91.15KHz
        v: height  512 start  512 end  514 total  536           clock  85.02Hz
  640x512 (0xc8) 67.500MHz +HSync +VSync DoubleScan
        h: width   640 start  648 end  720 total  844 skew    0 clock  79.98KHz
        v: height  512 start  512 end  514 total  533           clock  75.02Hz
  640x512 (0x58) 54.000MHz +HSync +VSync DoubleScan
        h: width   640 start  664 end  720 total  844 skew    0 clock  63.98KHz
        v: height  512 start  512 end  514 total  533           clock  60.02Hz
  700x450 (0xc9) 43.250MHz +HSync -VSync DoubleScan
        h: width   700 start  724 end  740 total  780 skew    0 clock  55.45KHz
        v: height  450 start  451 end  456 total  463           clock  59.88Hz
  640x480 (0xca) 36.000MHz -HSync -VSync
        h: width   640 start  696 end  752 total  832 skew    0 clock  43.27KHz
        v: height  480 start  481 end  484 total  509           clock  85.01Hz
  640x480 (0xcb) 31.500MHz -HSync -VSync
        h: width   640 start  664 end  704 total  832 skew    0 clock  37.86KHz
        v: height  480 start  489 end  492 total  520           clock  72.81Hz
  640x480 (0xcc) 31.500MHz -HSync -VSync
        h: width   640 start  656 end  720 total  840 skew    0 clock  37.50KHz
        v: height  480 start  481 end  484 total  500           clock  75.00Hz
  640x480 (0xcd) 25.200MHz -HSync -VSync
        h: width   640 start  656 end  752 total  800 skew    0 clock  31.50KHz
        v: height  480 start  490 end  492 total  525           clock  60.00Hz
  640x480 (0x5b) 25.175MHz -HSync -VSync
        h: width   640 start  656 end  752 total  800 skew    0 clock  31.47KHz
        v: height  480 start  490 end  492 total  525           clock  59.94Hz
  720x405 (0xce) 21.750MHz +HSync -VSync
        h: width   720 start  768 end  800 total  880 skew    0 clock  24.72KHz
        v: height  405 start  408 end  413 total  419           clock  58.99Hz
  720x400 (0xcf) 35.500MHz -HSync +VSync
        h: width   720 start  756 end  828 total  936 skew    0 clock  37.93KHz
        v: height  400 start  401 end  404 total  446           clock  85.04Hz
  720x400 (0xd0) 28.320MHz -HSync +VSync
        h: width   720 start  738 end  846 total  900 skew    0 clock  31.47KHz
        v: height  400 start  412 end  414 total  449           clock  70.08Hz
  684x384 (0xd1) 36.125MHz +HSync -VSync DoubleScan
        h: width   684 start  708 end  724 total  764 skew    0 clock  47.28KHz
        v: height  384 start  385 end  390 total  395           clock  59.85Hz
  640x400 (0xd2) 35.500MHz +HSync -VSync DoubleScan
        h: width   640 start  664 end  680 total  720 skew    0 clock  49.31KHz
        v: height  400 start  401 end  404 total  411           clock  59.98Hz
  640x400 (0xd3) 31.500MHz -HSync +VSync
        h: width   640 start  672 end  736 total  832 skew    0 clock  37.86KHz
        v: height  400 start  401 end  404 total  445           clock  85.08Hz
  576x432 (0xd4) 54.000MHz +HSync +VSync DoubleScan
        h: width   576 start  608 end  672 total  800 skew    0 clock  67.50KHz
        v: height  432 start  432 end  434 total  450           clock  75.00Hz
  640x360 (0xd5) 17.750MHz +HSync -VSync
        h: width   640 start  688 end  720 total  800 skew    0 clock  22.19KHz
        v: height  360 start  363 end  368 total  374           clock  59.32Hz
  640x350 (0xd6) 31.500MHz +HSync -VSync
        h: width   640 start  672 end  736 total  832 skew    0 clock  37.86KHz
        v: height  350 start  382 end  385 total  445           clock  85.08Hz
  512x384 (0xd7) 47.250MHz +HSync +VSync DoubleScan
        h: width   512 start  536 end  584 total  688 skew    0 clock  68.68KHz
        v: height  384 start  384 end  386 total  404           clock  85.00Hz
  512x384 (0xd8) 39.375MHz +HSync +VSync DoubleScan
        h: width   512 start  520 end  568 total  656 skew    0 clock  60.02KHz
        v: height  384 start  384 end  386 total  400           clock  75.03Hz
  512x384 (0xd9) 37.500MHz -HSync -VSync DoubleScan
        h: width   512 start  524 end  592 total  664 skew    0 clock  56.48KHz
        v: height  384 start  385 end  388 total  403           clock  70.07Hz
  512x384 (0xda) 32.500MHz -HSync -VSync DoubleScan
        h: width   512 start  524 end  592 total  672 skew    0 clock  48.36KHz
        v: height  384 start  385 end  388 total  403           clock  60.00Hz
  512x384i (0xdb) 22.450MHz +HSync +VSync Interlace DoubleScan
        h: width   512 start  516 end  604 total  632 skew    0 clock  35.52KHz
        v: height  384 start  384 end  388 total  408           clock  87.06Hz
  512x288 (0xdc) 21.000MHz +HSync -VSync DoubleScan
        h: width   512 start  536 end  552 total  592 skew    0 clock  35.47KHz
        v: height  288 start  289 end  292 total  296           clock  59.92Hz
  416x312 (0xdd) 28.642MHz -HSync -VSync DoubleScan
        h: width   416 start  432 end  464 total  576 skew    0 clock  49.73KHz
        v: height  312 start  312 end  314 total  333           clock  74.66Hz
  480x270 (0xde) 18.625MHz +HSync -VSync DoubleScan
        h: width   480 start  504 end  520 total  560 skew    0 clock  33.26KHz
        v: height  270 start  271 end  274 total  278           clock  59.82Hz
  400x300 (0xdf) 28.150MHz +HSync +VSync DoubleScan
        h: width   400 start  416 end  448 total  524 skew    0 clock  53.72KHz
        v: height  300 start  300 end  302 total  315           clock  85.27Hz
  400x300 (0xe0) 25.000MHz +HSync +VSync DoubleScan
        h: width   400 start  428 end  488 total  520 skew    0 clock  48.08KHz
        v: height  300 start  318 end  321 total  333           clock  72.19Hz
  400x300 (0xe1) 24.750MHz +HSync +VSync DoubleScan
        h: width   400 start  408 end  448 total  528 skew    0 clock  46.88KHz
        v: height  300 start  300 end  302 total  312           clock  75.12Hz
  400x300 (0xe2) 20.000MHz +HSync +VSync DoubleScan
        h: width   400 start  420 end  484 total  528 skew    0 clock  37.88KHz
        v: height  300 start  300 end  302 total  314           clock  60.32Hz
  400x300 (0xe3) 18.000MHz +HSync +VSync DoubleScan
        h: width   400 start  412 end  448 total  512 skew    0 clock  35.16KHz
        v: height  300 start  300 end  301 total  312           clock  56.34Hz
  432x243 (0xe4) 15.250MHz +HSync -VSync DoubleScan
        h: width   432 start  456 end  472 total  512 skew    0 clock  29.79KHz
        v: height  243 start  244 end  247 total  250           clock  59.57Hz
  320x240 (0xe5) 18.000MHz -HSync -VSync DoubleScan
        h: width   320 start  348 end  376 total  416 skew    0 clock  43.27KHz
        v: height  240 start  240 end  242 total  254           clock  85.18Hz
  320x240 (0xe6) 15.750MHz -HSync -VSync DoubleScan
        h: width   320 start  332 end  352 total  416 skew    0 clock  37.86KHz
        v: height  240 start  244 end  246 total  260           clock  72.81Hz
  320x240 (0xe7) 15.750MHz -HSync -VSync DoubleScan
        h: width   320 start  328 end  360 total  420 skew    0 clock  37.50KHz
        v: height  240 start  240 end  242 total  250           clock  75.00Hz
  320x240 (0xe8) 12.587MHz -HSync -VSync DoubleScan
        h: width   320 start  328 end  376 total  400 skew    0 clock  31.47KHz
        v: height  240 start  245 end  246 total  262           clock  60.05Hz
  360x202 (0xe9) 10.875MHz +HSync -VSync DoubleScan
        h: width   360 start  384 end  400 total  440 skew    0 clock  24.72KHz
        v: height  202 start  204 end  206 total  209           clock  59.13Hz
  360x200 (0xea) 17.750MHz -HSync +VSync DoubleScan
        h: width   360 start  378 end  414 total  468 skew    0 clock  37.93KHz
        v: height  200 start  200 end  202 total  223           clock  85.04Hz
  320x200 (0xeb) 15.750MHz -HSync +VSync DoubleScan
        h: width   320 start  336 end  368 total  416 skew    0 clock  37.86KHz
        v: height  200 start  200 end  202 total  222           clock  85.27Hz
  320x180 (0xec)  8.875MHz +HSync -VSync DoubleScan
        h: width   320 start  344 end  360 total  400 skew    0 clock  22.19KHz
        v: height  180 start  181 end  184 total  187           clock  59.32Hz
  320x175 (0xed) 15.750MHz +HSync -VSync DoubleScan
        h: width   320 start  336 end  368 total  416 skew    0 clock  37.86KHz
        v: height  175 start  191 end  192 total  222           clock  85.27Hz

'''

lines = [s for s in data2.splitlines()]

xorg_data = parse_xrandr_verbose(lines, {})

from pprint import pprint
pprint(xorg_data)

# TODO: Screen 0: minimum 320 x 200, current 1280 x 1024, maximum 16384 x 16384