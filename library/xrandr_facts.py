#!/usr/bin/python3
from __future__ import print_function
import ast
import binascii
import csv
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, NamedTuple, cast

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
    modelines: dict[str, str] = field(default_factory=dict[str, str])
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


def parse_xrandr_verbose(
    lines: list[str], params: dict[str, Any]
) -> dict[str, dict[str, XrandrMonitor]]:
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
                    if line.startswith("h:"):
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

                        line = next(iterator).strip()

                        if line.startswith("v:"):
                            (
                                _,
                                _,
                                v_height,
                                _,
                                v_start,
                                _,
                                v_end,
                                _,
                                v_total,
                                _,
                                v_clock,
                            ) = line.split()
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
                                modeline = f'Modeline "{mode_name}" {pixel_clk} {h_width} {h_start} {h_end} {h_total} {v_height} {v_start} {v_end} {v_total} {" ".join(flags)}'
                                xorg[screen][connector].modelines[mode_name] = modeline
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
    edid: str | None = field(default=None)
    drm_connector: str = field(default="")
    xrandr_connector: str = field(default="")


@dataclass
class DRM_Connectors:
    primary: DRM_Output = field(default_factory=DRM_Output)
    secondary: DRM_Output = field(default_factory=DRM_Output)
    ignored_outputs: list[str] = field(default_factory=list[str])
    all_outputs: list[DRM_Output] = field(default_factory=list[DRM_Output])


def find_drm_connectors(connections: dict[str, dict[str, Any]]) -> dict[str, Any]:
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
        'all_outputs': [DRM_Output1, ...]
    }
    """
    # STATUS_GLOB = '/sys/class/drm/card[0-9]*/status'
    CONNECTOR_RE = re.compile("card[0-9a-f]+-(?P<connector>[^/]+)")

    def read_edid_bytes(edid_file: str | Path):
        edid_bytes = b""
        try:
            edid_bytes = Path(edid_file).read_bytes()
        except IOError:
            pass
        return edid_bytes or None

    xrandr_edid_bytes = read_edid_bytes(connections.get("primary", {}).get("edid", ""))
    secondary_xrandr_edid_bytes = read_edid_bytes(
        connections.get("secondary", {}).get("edid", "")
    )

    drm: dict[str, dict[str, Any] | list[Any]] = {
        "primary": {},
        "secondary": {},
        "ignored_outputs": [],
        "all_outputs": [],
    }
    # for status_p in glob(STATUS_GLOB):
    for status_p in Path("/sys/class/drm/").glob("card[0-9a-f]*/status"):
        match = re.search(CONNECTOR_RE, status_p.parent.name)
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

        edid = read_edid_bytes(status_p.parent / "edid")
        drm["all_outputs"].append(
            {
                "drm_connector": drm_connector,
                "connected": connected,
                "edid": edid.hex() if edid is not None else edid,
            }
        )
        if connected:
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
    result: dict[str, Any] = {}
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
            rrate_score = len(preferred_rrates) - preferred_rrates.index(
                mode.refreshrate
            )
        if mode.resolution in preferred_resolutions:
            resolution_score = len(preferred_resolutions) - preferred_resolutions.index(
                mode.resolution
            )
        x_resolution, y_resolution = (int(n) for n in mode.resolution.split("x"))
        connection = mode.connection.split("-")[0]
        if connection in preferred_outputs:
            connection_score = len(preferred_outputs) - preferred_outputs.index(
                connection
            )
        return (
            rrate_score,
            resolution_score,
            x_resolution,
            y_resolution,
            connection_score,
        )

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
            ) -> None:
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
            other_modes = [
                mode for mode in modes if mode.connection != primary_mode.connection
            ]
            print(f"{other_modes=}")
            if other_modes:
                secondary_mode: Mode = max(other_modes, key=sort_mode)
                connector_1_edid = "/etc/X11/edid.{}.bin".format(
                    secondary_mode.connection
                )
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
                CONNECTOR_RE = re.compile("card[0-9a-f]+-(?P<connector>[^/]+)/status")
                for status_p in Path("/sys/class/drm/").glob("card[0-9a-f]*/status"):
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

    module.exit_json(
        changed=True,
        ansible_facts={
            "xrandr": xorg_result,
            "xorg": result,
            "drm": drm,
            "XorgConfig": config_result,
        },
    )


if __name__ == "__main__":
    module = AnsibleModule(
        argument_spec=ARG_SPECS,
        supports_check_mode=False,
    )

    params = cast(dict[str, str], module.params)
    try:
        d = subprocess.check_output(
            ["xrandr", "-d", params["display"], "--verbose"],
            errors="replace",
            universal_newlines=True,
        ).splitlines()
    except subprocess.CalledProcessError:
        xorg_data = {}
    else:
        xorg_data = parse_xrandr_verbose(d, params)
    output_data(xorg_data, params)
