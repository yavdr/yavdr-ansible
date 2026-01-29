from enum import StrEnum
import json
from collections.abc import Callable, Mapping
from pathlib import Path, PosixPath
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    FileUrl,
    FtpUrl,
    HttpUrl,
    NonNegativeInt,
    PositiveInt,
    IPvAnyAddress,
    IPvAnyNetwork,
    model_validator,
)
from pydantic.json_schema import GenerateJsonSchema

from ruamel import yaml

from helpers.models.locales import Locale
from helpers.models.generic import EmptyString
from helpers.models.network import LocalHostname, NFSConfig, SambaConfig
from helpers.models.system import (
    PPA,
    AnsibleConnection,
    GrubConfig,
    LanguagePack,
    SupportedFrontends,
    TimeZone,
    WakeupEnum,
)
from helpers.models.vdr import VDRConfig, VDRPlugin


# default values
REPOSITORIES = [
    "ppa:seahawk1986-hotmail/resolute-main",
    "ppa:seahawk1986-hotmail/vdr-2.7.7",
]
TIMEZONE = "Europe/Berlin"
LOCALE = "de_DE.UTF-8"
LOCALES = ["de_DE.UTF-8", "en_US.UTF-8"]
LANGUAGE_PACKS = ["language-pack-de", "language-pack-en"]
VDR_PLUGINS = ["vdr-plugin-devstatus", "vdr-plugin-markad-ng", "vdr-plugin-live"]
DEFAULT_LIFEGUARD_TCP: dict[str, list[int]] = {"vdr": [3000, 6419, 8008, 34890]}
LIFEGUARD_USERS = ["root"]
LIFEGUARD_PROCESSES = [
    "ansible-playbook",
    "ansible",
    "apt-get",
    "apt",
    "emacs",
    "flatpak",
    "nano",
    "snap",
    "vim",
]
MEDIA_DIRS = {
    "audio": PosixPath("/srv/audio"),
    "video": PosixPath("/srv/video"),
    "pictures": PosixPath("/srv/picture"),
    "files": PosixPath("/srv/files"),
    "backups": PosixPath("/srv/backups"),
}
# end of default values


class SOFTHDDEVICE_OUTPUT_METHODS(StrEnum):
    CPU = "cpu"
    CPU_GLX = "cpu-glx"
    CPU_EGL = "cpu-egl"
    VA_API = "va-api"
    VA_API_GLX = "va-api-glx"
    VA_API_EGL = "va-api-egl"
    NOOP = "noop"
    VDAPAU = "vdpau"
    VDPAU_GLX = "vdpau-glx"
    CUVID = "cuvid"
    CUVID_EGL = "cuvid-egl"
    NVDEC = "nvdec"
    NVDEC_EGL = "nvdec-egl"


def make_default_adder(
    default_value: str | list[Any] | Mapping[str, Any],
) -> Callable[[dict[str, Any]], None]:
    def add_default(schema: dict[str, Any]) -> None:
        schema["default"] = default_value

    return add_default


class StreamdevConfig(BaseModel):
    client_remote_ip: LocalHostname | IPvAnyAddress | EmptyString | None = Field(
        default=None
    )

    client_remote_port: Annotated[
        NonNegativeInt, Field(description="Port for streamdev")
    ] = 2004

    client_num_provided_systems: Annotated[
        NonNegativeInt,
        Field(
            description="number of parallel connections created for streamdev-client"
        ),
    ] = 1


def prefix_paths(v: str) -> str:
    _, part, _ = v.partition("://")
    if "://" != part:
        return f"file://{v}"
    return v


class yaVDRConfig(BaseModel):
    ansible_host: LocalHostname = "localhost"
    ansible_connection: AnsibleConnection = Field(
        default=AnsibleConnection.LOCAL,
        description="Connection mode, should be 'local' for regular use",
    )  # local, ssh, special ones for cloud services - I don't think we can validate this properly
    repositories: Annotated[
        list[PPA],
        Field(
            description="PPAs to add",
        ),
    ] = REPOSITORIES.copy()
    timezone: Annotated[
        TimeZone, Field(description="Timezone for System, e.g. 'Europe/Berlin'")
    ] = TIMEZONE  # TODO: can we verify this against the local tz databases in  /usr/share/zoneinfo/ ?
    default_locale: Annotated[
        Locale, Field(description="Default Locale, e.g. 'de_DE.UTF-8'")
    ] = LOCALE
    generate_locales: Annotated[
        list[Locale], Field(description="Locales to generate")
    ] = LOCALES.copy()
    language_packs: Annotated[
        list[LanguagePack],
        Field(description="Language support packages to install"),
    ] = LANGUAGE_PACKS

    vdr: Annotated[
        VDRConfig,
        Field(description="VDR Configuration"),
    ] = VDRConfig()
    vdr_channels_conf: Annotated[
        FileUrl | HttpUrl | FtpUrl | None,
        BeforeValidator(prefix_paths),
        Field(
            description="channels.conf file to import if VDR has none, use a http(s)://, ftp:// or file:// URL or a path",
        ),
    ] = None  # TODO: update playbook for this
    wait_for_dvb_devices: Annotated[
        list[NonNegativeInt],
        Field(description="Indices of DVB Devices to wait for", max_length=16),
    ] = []
    streamdev: Annotated[
        StreamdevConfig,
        Field(
            description="vdr-plugin-streamdev-client configuration",
        ),
    ] = StreamdevConfig()

    vdr_plugins: Annotated[
        list[VDRPlugin], Field(description="VDR Plugins to install")
    ] = VDR_PLUGINS

    selectedFrontend: Annotated[
        str | None, Field(description="Set the vdr frontend, e.g. 'softhddevice'")
    ] = None

    vdr_output_plugin: Annotated[
        str | None, Field(description="Set vdr output plugin")
    ] = None

    vdr_allowed_hosts: Annotated[
        list[IPvAnyNetwork | IPvAnyAddress],
        Field(description="List of allowed TCP clients - IP addresses or ranges"),
    ] = []

    vdr_svdrphosts: Annotated[
        list[IPvAnyNetwork | IPvAnyAddress] | None,
        Field(description="List of allowed SVDRP TCP clients - IP addresses or ranges"),
    ] = None

    xineliboutput_allowed_hosts: Annotated[
        list[IPvAnyNetwork | IPvAnyAddress] | None,
        Field(
            description="List of allowed xineliboutput TCP clients - IP addresses or ranges"
        ),
    ] = None

    vnsiserver_allowed_hosts: Annotated[
        list[IPvAnyNetwork | IPvAnyAddress] | None,
        Field(
            description="List of allowed vnsiserver TCP clients - IP addresses or ranges"
        ),
    ] = None
    streamdev_server_allowed_hosts: Annotated[
        list[IPvAnyNetwork | IPvAnyAddress] | None,
        Field(
            description="List of allowed streamdev TCP clients - IP addresses or ranges"
        ),
    ] = None

    media_dirs: Annotated[
        dict[str, PosixPath],
        Field(description="Media directories"),
    ] = {}
    nfs: Annotated[NFSConfig, Field(description="NFS configuration")] = NFSConfig()
    samba: Annotated[SambaConfig, Field(description="SMB configuration")] = (
        SambaConfig()
    )  # TODO: interpolate jinja values in yaml before parsing

    firefox_as_deb: Annotated[
        bool, Field(description="Install firefox from Mozilla repo")
    ] = True

    kodi_as_flatpak: Annotated[bool, Field(description="Install KODI as flatpak")] = (
        True
    )
    extra_packages: Annotated[
        list[str], Field(description="Packages to install on the system")
    ] = ["htop", "tree", "vim", "w-scan", "t2scan", "vdrpbd"]
    channellogos_languages: Annotated[
        list[str], Field(description="Languages for channellogos")
    ] = []

    frontend: Annotated[
        SupportedFrontends,
        Field(description="Frontend to use (currently only 'vdr')"),
    ] = SupportedFrontends.VDR

    vdr_shutdown_command: Annotated[str, Field(description="Shutdown Command")] = (
        "poweroff"
    )
    nvidia_force_dpi: Annotated[
        NonNegativeInt, Field(description="Set dpi for nvidia Xorg configuration")
    ] = 96

    # system: Annotated[SystemConfig, Field(description="")]

    wakup_method: Annotated[
        WakeupEnum,
        Field(
            description="Wakeup method for the system",
        ),
    ] = WakeupEnum.ACPIWAKEUP
    wakeup_start_ahead: PositiveInt = 5
    wakeup_days: str = ""
    wakeup_time: str = ""
    # TODO: add option for wakeup_max_margin_hours = 36
    wakeup_max_margin_hours: Annotated[
        int | None,
        Field(
            description=(
                "Wakeup maximum margin in hours. "
                "Ensure that the machine is woken up next time after this amount "
                "if next wakeup time is not within the margin."
            )
        ),
    ] = None

    kms_set_boot_edid: bool = False

    preferred_outputs: Annotated[
        list[str], Field(description="list of preferred outputs")
    ] = ["HDMI", "DP", "DVI", "VGA", "TV"]
    preferred_resolutions: Annotated[
        list[str], Field(description="list of preferred resolutions")
    ] = [
        "7680x4320",
        "3840x2160",
        "1920x1080",
        "1280x720",
        "720x576",
    ]
    preferred_refreshrates: Annotated[
        list[int], Field(description="list of preferred refresh rates")
    ] = [100, 50, 60]

    softhddevice_vaapi_output_method: Annotated[
        str, Field(description="output method for vdr-plugin-softhddevice")
    ] = "va-api-egl"

    """
    kms_boot_options: ""
    kms_set_boot_edid: false
    intel_driver: "intel"  # choose one of "intel" and "modesetting"
    softhddevice_vaapi_output_method: "va-api"  # choose one of va-api, va-api-glx, va-api-egl

    yavdr_frontend:
        attach_on_startup: auto  # choose one of auto, always or never
    """

    grub: GrubConfig = GrubConfig()
    standby_reload_dvb: Annotated[
        bool, Field(description="unload and reload dvb driver modules during resume")
    ] = True

    lifeguard_enable_nfs: Annotated[
        bool, Field(description="Block shutdown on active NFS clients")
    ] = True
    lifeguard_enable_samba: Annotated[
        bool, Field(description="Block shutdown on active SMB clients")
    ] = True
    lifeguard_enable_ssh: Annotated[
        bool, Field(description="Block shutdown on active SSH clients")
    ] = True

    lifeguard_hosts: Annotated[
        list[LocalHostname],
        Field(
            description="list of hostnames resp. IP addresses of active devices on the network that should block shutdown"
        ),
    ] = []

    lifeguard_users: Annotated[
        list[str], Field(description="List of users that block shutdown when logged in")
    ] = LIFEGUARD_USERS.copy()
    lifeguard_processes: Annotated[
        list[str], Field(description="List of process names that should block shutdown")
    ] = LIFEGUARD_PROCESSES.copy()

    lifeguard_tcp: Annotated[
        dict[str, list[int]],
        Field(description="Mapping of process names and connections of given ports"),
    ] = DEFAULT_LIFEGUARD_TCP

    serial_ir_device: str = "ttyS0"

    ansible_managed: str = """*** ANSIBLE MANAGED FILE ***\n template: {file}"""

    @model_validator(mode="after")
    def set_default_mediadirs(self) -> Self:
        self.media_dirs = {**self.media_dirs}
        MEDIA_DIRS.setdefault("recordings", PosixPath(self.vdr.recdir))
        for key, value in MEDIA_DIRS.items():
            self.media_dirs.setdefault(key, value)
        return self

    @model_validator(mode="after")
    def set_default_samba(self) -> Self:
        if self.vdr.safe_dirnames and self.samba.windows_compatible is None:
            self.samba.windows_compatible = self.vdr.safe_dirnames
        return self


class InlineSchemaGenerator(GenerateJsonSchema):
    def ref_template(self) -> str:
        # Disable $ref usage
        return "{model}"


if __name__ == "__main__":
    schema = yaVDRConfig.model_json_schema()
    Path("yaVDRConfig.schema.json").write_text(json.dumps(schema, indent=2))

    yaml_instance = yaml.YAML(typ="unsafe", pure=True)
    vdr_config = VDRConfig()
    print(VDRConfig.model_json_schema(schema_generator=InlineSchemaGenerator))
    print(vdr_config.model_dump_json())
    yavdr_config = yaVDRConfig()
    print(yavdr_config.model_dump_json())
