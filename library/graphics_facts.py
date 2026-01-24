import binascii
from collections import defaultdict, deque
import logging
from pathlib import Path
from pydantic import BaseModel, Field
import re
import subprocess
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
  action: graphics_facts
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

logger = logging.getLogger(__name__)


class Connector(BaseModel):
    xrandr_name: str
    is_connected: bool = False
    edid: str | None = None
    xorg_modelines: dict[str, str] = Field(default_factory=dict[str, str])
    edid_modelines: dict[str, str] = Field(default_factory=dict[str, str])
    all_modelines: dict[str, str] = Field(default_factory=dict[str, str])
    modes: dict[str, list[int]] = Field(default_factory=dict[str, list[int]])
    pci_id: str | None = None
    drm_name: str | None = None
    vendor: str | None = None
    model: str | None = None

    def __hash__(self):
        return hash((self.xrandr_name, self.is_connected, self.edid, self.pci_id))


class MonitorConfig(BaseModel):
    connector: str = ""
    resolution: str = ""
    refreshrate: int = 0


class GraphicsConfig(BaseModel):
    primary: None | MonitorConfig = None
    secondary: None | MonitorConfig = None


class Preferences(BaseModel):
    refreshrates: list[int] = Field(default_factory=lambda: [50, 60])
    resolutions: list[str] = Field(
        default_factory=lambda: [
            "7680x4320",
            "3840x2160",
            "1920x1080",
            "1280x720",
            "720x576",
        ]
    )
    outputs: list[str] = Field(default_factory=lambda: ["HDMI", "DP", "DVI", "VGA"])


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


def get_xrandr_verbose_output(display: str = ":0") -> deque[str] | None:
    try:
        d = subprocess.check_output(
            ["xrandr", "-d", display, "--verbose"],
            errors="replace",
            universal_newlines=True,
        )
    except Exception:
        logging.exception("calling xrandr --verbose failed")
    else:
        return deque(d.splitlines())


def parse_xrandr_edid(data: deque[str]) -> str:
    edid_lines: list[str] = []
    last_indent = 0
    while data:
        line = data.popleft()
        indentation = len(line) - len(line.lstrip())
        if indentation >= last_indent:
            edid_lines.append(line.strip())
        else:
            data.appendleft(line)
            break
        last_indent = indentation
    return "".join(edid_lines)


def parse_edid_bytes(edid_bytes: str) -> tuple[str, str, dict[str, str]]:
    vendor = "Unknown"
    model = "Unknown"
    modelines: dict[str, str] = {}
    try:
        data = subprocess.check_output(
            ["edid-decode", "-LnpsX"],
            errors="replace",
            input=edid_bytes,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError:
        logging.exception("could not decode edid data")
        pass
    else:
        for line in data.splitlines():
            line = line.strip()
            if line.startswith("Manufacturer:"):
                _, _, vendor = line.partition(": ")
            elif line.startswith("Display Product Name:"):
                _, _, model = line.partition(": ")
                model = model.strip("'\"")
            elif line.startswith("Modeline"):
                # For the fields of a modeline see
                # https://en.wikipedia.org/wiki/XFree86_Modeline
                # ignore 'Modeline "Mode N"' part of Modeline
                _, _mode_name, line = line.split('"', 2)
                if not line:
                    logging.debug("no timing information")
                    continue
                try:
                    mode = Modeline_Data(*line.split(maxsplit=9))
                    if len(mode) < 9:
                        raise ValueError("invalid modeline")
                except (ValueError, TypeError):
                    logging.warning("invalid timing information")
                    continue
                refresh = (
                    float(mode.pixelclock)
                    * 1e6
                    / (float(mode.htotal) * float(mode.vtotal))
                )

                interlaced = "i" if "Interlace" in mode.flags else ""
                if interlaced:
                    continue
                refresh = int(refresh + 0.5)
                modeline_name = f"{mode.hdisp}x{mode.vdisp}_{refresh}{interlaced}"
                modelines[modeline_name.strip('"').replace(".00", "")] = (
                    f'Modeline "{modeline_name}" {" ".join(mode)}'
                )
    return vendor, model, modelines


def find_xrandr_edid(data: deque[str]) -> bytes | None:
    while data:
        line = data.popleft()
        if line.lstrip().startswith("EDID:"):
            edid = parse_xrandr_edid(data)
            return edid.encode("ascii")
        elif line.lstrip().startswith("non-desktop"):
            return


def find_next_mode(data: deque[str]) -> tuple[str, str] | None:
    while data:
        line = data.popleft()
        if m := re.match(r"\s+(?P<resolution>\d+x\d+)", line):
            resolution = m.group("resolution")
            # get pixel clock and flags
            _, _, pixel_clock, *flags = line.strip().split()
            pixel_clock = pixel_clock[:-3]
            if "Interlace" in flags or "DoubleScan" in flags:  # skip those modes
                return None
            flags = [f for f in flags if f not in ("+preferred", "*current")]
            # look for horizontal info
            if (h_line := data.popleft()).lstrip().startswith("h:"):
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
                    _h_clock,
                ) = h_line.split()
                if (v_line := data.popleft()).lstrip().startswith("v:"):
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
                        _v_clock,
                    ) = v_line.split()
                    refresh = (
                        float(pixel_clock) * 1e6 / (float(h_total) * float(v_total))
                    )

                    refresh_rate = int(refresh + 0.5)

                    # return mode
                    mode_name = f"{resolution}_{refresh_rate}"
                    return mode_name, (
                        f'Modeline "{mode_name}" '
                        f"{pixel_clock} "
                        f"{h_width} {h_start} {h_end} {h_total} "
                        f"{v_height} {v_start} {v_end} {v_total} "
                        f"{' '.join(flags)}"
                    )


def find_edid(edid: bytes | None, xorg_connector: str) -> None | tuple[str, str]:
    if edid:
        edid = binascii.a2b_hex(edid)
        for edid_path in Path("/sys/class/drm/").glob("card*/edid"):
            # logging.debug(f"{edid=} == {edid_path.read_bytes()=}")
            if edid == edid_path.read_bytes():
                card, _, drm_connector = edid_path.parent.name.partition("-")
                # get the BusID
                dev_path = edid_path.parent.parent / card / "dev"
                real_dev_path = dev_path.resolve()
                pci_id = real_dev_path.parent.parent.parent.name
                return drm_connector, pci_id

    for edid_path in Path("/sys/class/drm/").glob("card*/edid"):
        # logging.debug(f"{edid=} == {edid_path.read_bytes()=}")
        card, _, drm_connector = edid_path.parent.name.partition("-")
        if drm_connector == xorg_connector:
            # get the BusID
            dev_path = edid_path.parent.parent / card / "dev"
            real_dev_path = dev_path.resolve()
            pci_id = real_dev_path.parent.parent.parent.name
            return drm_connector, pci_id

    return None


def sort_by_resolution(item: tuple[str, set[int]]) -> tuple[int, int]:
    resolution, _ = item
    x, _, y = resolution.partition("x")
    return (int(x), int(y))


def find_next_connector(data: deque[str]) -> Connector | None:
    while data:
        line = data.popleft()
        if m := re.match(
            r"(?P<output>(?P<connector>\S+-?\d)\s(?P<connected>(connected|disconnected)))",
            line,
        ):
            # parse the connector data
            xorg_connector_name = m.group("connector")
            connected = m.group("connected") == "connected"
            logging.info(f"found {xorg_connector_name=}: {connected=}")
            if connected:
                xorg_modes: dict[str, str] = {}
                edid = find_xrandr_edid(data)
                drm_connector = pci_id = vendor = model = None
                edid_modes: dict[str, str] = {}
                if r := find_edid(edid, xorg_connector_name):
                    drm_connector, pci_id = r
                if edid is not None:
                    edid = edid.decode()
                    vendor, model, edid_modes = parse_edid_bytes(edid)

                logging.info(f"{edid=}")
                while data and len(data[0]) > len(data[0].lstrip()):
                    if r := find_next_mode(data):
                        mode_name, mode = r
                        xorg_modes[mode_name] = mode

                # join the modelines
                combined_modelines: dict[str, str] = {}
                for name, modeline in edid_modes.items():
                    m_data = modeline.rsplit('"', maxsplit=1)[-1]
                    combined_modelines[m_data] = name

                for name, modeline in xorg_modes.items():
                    m_data = modeline.rsplit('"', maxsplit=1)[-1]
                    combined_modelines[m_data] = name

                joined_modelines: dict[str, str] = {}
                for key in sorted(combined_modelines.values()):
                    modeline = xorg_modes.get(key) or edid_modes.get(key)
                    if modeline:
                        # logging.debug(key, modeline)
                        joined_modelines[key] = modeline
                modes: defaultdict[str, set[int]] = defaultdict(set[int])
                for mode_name in combined_modelines.values():
                    resolution, _, refreshrate = mode_name.partition("_")
                    if not refreshrate:
                        continue
                    modes[resolution].add(int(refreshrate))

                sorted_modes: dict[str, list[int]] = {}
                for mode, refreshrates in sorted(
                    modes.items(), key=sort_by_resolution, reverse=True
                ):
                    sorted_modes[mode] = sorted(refreshrates, reverse=True)

                return Connector(
                    xrandr_name=xorg_connector_name,
                    is_connected=connected,
                    edid=edid,
                    xorg_modelines=xorg_modes,
                    edid_modelines=edid_modes,
                    all_modelines=joined_modelines,
                    modes=sorted_modes,
                    drm_name=drm_connector,
                    pci_id=pci_id,
                    vendor=vendor,
                    model=model,
                )


def parse_xrandr_verbose(data: deque[str]) -> dict[str, Connector]:
    connectors: dict[str, Connector] = {}
    while data:
        if connector := find_next_connector(data):
            connectors[connector.drm_name or connector.xrandr_name] = connector

    return connectors


Rating = tuple[int, int, int, int, int]


def rate_mode(
    resolution: str, refreshrate: int, output: str, preferences: Preferences
) -> Rating:
    """rate modes by several criteria"""
    connection_score = 0
    rrate_score = 0
    resolution_score = 0
    preferred_rrates = preferences.refreshrates
    # [50, 60]
    preferred_resolutions = preferences.resolutions
    # ["7680x4320", "3840x2160", "1920x1080", "1280x720", "720x576"]
    preferred_outputs = preferences.outputs
    # ["HDMI", "DP", "DVI", "VGA"]
    if refreshrate in preferred_rrates:
        rrate_score = len(preferred_rrates) - preferred_rrates.index(refreshrate)
    if resolution in preferred_resolutions:
        resolution_score = len(preferred_resolutions) - preferred_resolutions.index(
            resolution
        )
    x_resolution, y_resolution = (int(n) for n in resolution.split("x"))
    connection, _, _ = output.partition("-")
    if connection in preferred_outputs:
        connection_score = len(preferred_outputs) - preferred_outputs.index(connection)
    return (
        rrate_score,
        resolution_score,
        x_resolution,
        y_resolution,
        connection_score,
    )


def auto_config(
    connectors: dict[str, Connector], preferences: Preferences
) -> GraphicsConfig:
    xorg_config: GraphicsConfig = GraphicsConfig()

    scores: dict[tuple[Connector, str], Rating] = {}
    for connector in connectors.values():
        for resolution, refreshrates in connector.modes.items():
            for refreshrate in refreshrates:
                scores[(connector, f"{resolution}_{refreshrate}")] = rate_mode(
                    resolution, refreshrate, connector.xrandr_name, preferences
                )

    sorted_modes = sorted(scores.items(), key=lambda x: x[1])

    if len(sorted_modes) > 0:
        *secondary_candidates, ((primary, mode_name), _) = sorted_modes
        resolution, _, refreshrate = mode_name.partition("_")
        xorg_config.primary = MonitorConfig(
            connector=primary.drm_name,
            resolution=resolution,
            refreshrate=int(refreshrate),
        )
        if secondary_candidates := list(
            filter(
                lambda x: x[0][0].xrandr_name != primary.xrandr_name,
                secondary_candidates,
            )
        ):
            *_, ((secondary, secondary_mode_name), _) = secondary_candidates
            resolution, _, refreshrate = secondary_mode_name.partition("_")
            xorg_config.secondary = MonitorConfig(
                connector=secondary.drm_name,
                resolution=resolution,
                refreshrate=int(refreshrate),
            )
    # else:
    #     xorg_config.primary =

    return xorg_config


if __name__ == "__main__":
    module = AnsibleModule(
        argument_spec=ARG_SPECS,
        supports_check_mode=False,
    )

    params = cast(dict[str, Any], module.params)
    logging.basicConfig(filename="/tmp/graphics_facts.log", level=logging.DEBUG)
    if xrandr_verbose_output := get_xrandr_verbose_output(
        display=":0"
    ):  # params["display"]):
        connectors = parse_xrandr_verbose(xrandr_verbose_output)
        xorg_config = auto_config(
            connectors,
            Preferences(
                refreshrates=params["preferred_refreshrates"],
                resolutions=params["preferred_resolutions"],
                outputs=params["preferred_outputs"],
            ),
        )
        module.exit_json(
            changed=True,
            ansible_facts={
                "graphics_outputs": {
                    key: value.model_dump() for (key, value) in connectors.items()
                },
                "graphics_config": xorg_config.model_dump(),
            },
        )
