#!/usr/bin/env python3
import ast
import binascii
import logging
import re
from collections import defaultdict
from pprint import pprint
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Generator
import subprocess
from typing import NamedTuple


@dataclass
class Connector:
    xrandr_name: str
    is_connected: bool = False
    edid: bytes | None = None
    xorg_modelines: dict[str, str] = field(default_factory=dict[str, str])
    edid_modelines: dict[str, str] = field(default_factory=dict[str, str])
    joined_modelines: dict[str, str] = field(default_factory=dict[str, str])
    modes: defaultdict[str, set[int]] = field(
        default_factory=lambda: defaultdict(set[int])
    )
    drm_name: str | None = None
    vendor: str | None = None
    model: str | None = None


LINE_CLASSIFIER = re.compile(
    (  # Screen:\s(?P<screen>\d): |
        r"(?P<output>(?P<connector>\S+-?\d)\s(?P<connected>(connected|disconnected)))|"
        r"(?P<edid_start>\s+EDID:)|"
        r"(?P<mode_start>\s+(?P<resolution>\d+x\d+)\s)|"
        r"(?P<horizontal>\s+h: )|"
        r"(?P<vertical>\s+v: )"
    )
)


def read_edid(line_generator: Generator[str, None, None]) -> bytes:
    edid_lines: list[bytes] = []
    last_indentation = 0
    for line in line_generator:
        indentation = len(line) - len(line.lstrip())
        if indentation < last_indentation:  # We left the EDID block
            break
        line = line.strip()
        edid_lines.append(line.encode("ascii"))
        last_indentation = indentation
    edid = b"".join(edid_lines[:-1])
    return edid


class ModeData(NamedTuple):
    resolution: str
    pixel_clock: str
    flags: list[str]
    current: bool
    preferred: bool


class hData(NamedTuple):
    width: str
    start: str
    end: str
    total: str
    clock: str


class vData(NamedTuple):
    height: str
    start: str
    end: str
    total: str
    clock: str
    refresh_rate: float


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


def parse_edid_bytes(edid_bytes: bytes):
    vendor = "Unknown"
    model = "Unknown"
    modelines: dict[str, str] = {}
    try:
        data = subprocess.check_output(
            ["edid-decode", "-LnpsX"],
            errors="replace",
            input=edid_bytes.decode(),
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
                # print(line)
                # ignore 'Modeline "Mode N"' part of Modeline
                _, _mode_name, line = line.split('"', 2)
                if not line:
                    logging.debug("no timing information")
                    continue
                try:
                    mode = Modeline_Data(*line.split(None, 9))
                except (ValueError, TypeError):
                    logging.warning("invalid timing information")
                    continue
                refresh = round(
                    float(mode.pixelclock)
                    * 1e6
                    / (float(mode.htotal) * float(mode.vtotal))
                )
                interlaced = "i" if "Interlace" in mode.flags else ""
                refresh = int(refresh)
                modeline_name = f"{mode.hdisp}x{mode.vdisp}_{refresh}{interlaced}"
                modelines[modeline_name.strip('"').replace(".00", "")] = (
                    f'Modeline "{modeline_name}" {" ".join(mode)}'
                )
    return vendor, model, modelines


class ModeBuilder:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        logging.debug("resetting ModeBuilder")
        self.mode_data: ModeData
        self.h_data: hData | None = None
        self.v_data: vData | None = None
        self.clock: str | None = None

    def new_mode(self, line: str):
        self.reset()
        resolution, _id, pixel_clock, *flags = line.split()
        clock = pixel_clock[:-3]
        preferred = bool("+preferred" in line)
        current = bool("*current" in line)
        flags = [flag for flag in flags if flag not in ("*current", "+preferred")]

        self.mode_data = ModeData(resolution, clock, flags, current, preferred)

    def add_horizontal_data(self, line: str) -> None:
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
        self.h_data = hData(h_width, h_start, h_end, h_total, h_clock)

    def add_vertical_data(self, line: str) -> None:
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
        rrate = ast.literal_eval(v_clock[:-2])
        refresh_rate = int(rrate)
        self.v_data = vData(v_height, v_start, v_end, v_total, v_clock, refresh_rate)

    def finalize(self) -> tuple[str, str]:
        if self.mode_data and self.v_data and self.h_data:
            if (
                "Interlace" in self.mode_data.flags
                or "DoubleScan" in self.mode_data.flags
            ):
                raise ValueError("skipping double scan and interlace modes")
            modeline = (
                f'Modeline "{self.mode_data.resolution}_{round(self.v_data.refresh_rate, 2)}" '
                f"{self.mode_data.pixel_clock} "
                f"{self.h_data.width} {self.h_data.start} {self.h_data.end} {self.h_data.total} "
                f"{self.v_data.height} {self.v_data.start} {self.v_data.end} {self.v_data.total} "
                f"{' '.join(self.mode_data.flags)}"
            )
            logging.debug(
                (f"{self.mode_data.resolution}_{self.v_data.refresh_rate}"), modeline
            )
            return (f"{self.mode_data.resolution}_{self.v_data.refresh_rate}"), modeline
        raise ValueError("inclomplete mode data")


class ConnectorBuilder:
    def __init__(self) -> None:
        self.mode_builder = ModeBuilder()
        self.reset()

    def reset(self) -> None:
        self.mode_builder.reset()
        self.xorg_name: str | None = None
        self.is_connected: bool = False
        self.edid: bytes | None = None
        self.xorg_modelines: dict[str, str] = {}
        self.modes: defaultdict[str, set[int]] = defaultdict(set[int])
        self.preferred_mode: str | None = None
        self.preferred_refreshrate: float | None = None
        self.preferred_resolution: str | None = None

    def new_mode(self, line: str) -> None:
        self.mode_builder.new_mode(line)

    def add_horizontal_data(self, line: str):
        self.mode_builder.add_horizontal_data(line)

    def add_vertical_data(self, line: str) -> None:
        self.mode_builder.add_vertical_data(line)
        try:
            if self.mode_builder.v_data:
                logging.debug("add vertical data")
                (key, modeline) = self.mode_builder.finalize()
                self.xorg_modelines[key] = modeline
                if self.mode_builder.mode_data.preferred:
                    self.preferred_resolution = self.mode_builder.mode_data.resolution
                    self.preferred_refreshrate = self.mode_builder.v_data.refresh_rate
                    self.preferred_mode = (
                        f"{self.preferred_resolution}_{self.preferred_refreshrate}"
                    )
        except ValueError as err:
            logging.debug("Could not create modeline", err)

    def find_edid(self) -> None | str:
        if self.edid is None:
            return None
        edid = binascii.a2b_hex(self.edid)
        for edid_path in Path("/sys/class/drm/").glob("card*/edid"):
            # logging.debug(f"{edid=} == {edid_path.read_bytes()=}")
            if edid == edid_path.read_bytes():
                _, _, drm_connector = edid_path.parent.name.partition("-")
                return drm_connector

        return None

    def finalize(self) -> Connector:
        if self.xorg_name is None:
            raise ValueError("Connector name not set")
        drm_connector = self.find_edid()

        if self.edid:
            vendor, model, edid_modelines = parse_edid_bytes(self.edid)
        else:
            edid_modelines = {}
            vendor = None
            model = None

        # join the modelines
        combined_modelines: dict[str, str] = {}
        for name, modeline in edid_modelines.items():
            m_data = modeline.rsplit('"', maxsplit=1)[-1]
            combined_modelines[m_data] = name

        for name, modeline in self.xorg_modelines.items():
            m_data = modeline.rsplit('"', maxsplit=1)[-1]
            combined_modelines[m_data] = name

        joined_modelines: dict[str, str] = {}
        for key in sorted(combined_modelines.values()):
            modeline = self.xorg_modelines.get(key) or edid_modelines.get(key)
            if modeline:
                print(key, modeline)
                joined_modelines[key] = modeline

        for mode_name in combined_modelines.values():
            resolution, _, refreshrate = mode_name.partition("_")
            if not refreshrate:
                continue
            print(refreshrate)
            if refreshrate.endswith("i"):
                print(f"{refreshrate=}")
                refreshrate = refreshrate[:-1]
            self.modes[resolution].add(int(refreshrate))
        return Connector(
            xrandr_name=self.xorg_name,
            is_connected=self.is_connected,
            edid=self.edid,
            xorg_modelines=self.xorg_modelines,
            edid_modelines=edid_modelines,
            joined_modelines=joined_modelines,
            modes=self.modes,
            drm_name=drm_connector,
            vendor=vendor,
            model=model,
        )


def parse_xrandr_verbose_output(data: str) -> dict[str, Connector]:
    connectors: dict[str, Connector] = {}
    line_generator = (line for line in data.splitlines())
    con = ConnectorBuilder()
    for line in line_generator:
        if m := LINE_CLASSIFIER.match(line):
            match m.lastgroup:
                case "output":
                    logging.debug("new output")
                    try:
                        if con.xorg_name:
                            connectors[con.xorg_name] = con.finalize()
                    except ValueError as err:
                        logging.debug("could not create Connector", err)
                        pass
                    else:
                        con.reset()
                    connector = m.group("connector")
                    is_connected = m.group("connected") == "connected"
                    con.xorg_name = connector
                    con.is_connected = is_connected
                    if not is_connected:
                        connectors[connector] = con.finalize()
                        con.reset()

                case "edid_start":
                    logging.debug("new edid")
                    con.edid = read_edid(line_generator)

                case "mode_start":
                    logging.debug("start of mode")
                    con.new_mode(line)

                case "horizontal":
                    logging.debug("horizontal mode data")
                    con.add_horizontal_data(line)

                case "vertical":
                    logging.debug("vertical mode data")
                    con.add_vertical_data(line)

                case _:
                    logging.debug(f"unhandled match {m.lastgroup=}")
                    pass
    try:
        if con.xorg_name:
            connectors[con.xorg_name] = con.finalize()
    except ValueError as err:
        logging.exception("could not create connector:", stack_info=True)

    pprint(connectors, width=160, sort_dicts=True)
    return connectors


if __name__ == "__main__":
    xrandr_verbose_path = Path.home() / "xrandr_verbose.log"
    parse_xrandr_verbose_output(xrandr_verbose_path.read_text())
