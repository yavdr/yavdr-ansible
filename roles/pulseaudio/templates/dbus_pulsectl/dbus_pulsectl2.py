#!/usr/bin/env python3
import asyncio
import sdbus
import pulsectl


INTERFACE_NAME = "org.yavdr.PulseDBusCtl"
OBJECT_PATH = "/org/yavdr/PulseDBusCtl"

class PulseDBusControl(
        sdbus.DbusInterfaceCommonAsync,
        interface_name=INTERFACE_NAME):

    def __init__(self):
        self.pulse = pulse = pulsectl.Pulse("pulse_dbus_ctl")
        super().__init__()

    @sdbus.dbus_method_async(
        result_signature='a(ssa(ss)s)',
        flags=sdbus.DbusUnprivilegedFlag,
    )
    async def list_output_profiles(self):
        cards = self.pulse.card_list()
        result = []
        for card in cards:
            profiles = []
            for p in card.profile_list:
                if p.available and p.n_sinks > 0 and p.name.startswith('output:'):
                    profiles.append((p.name, p.description))
            result.append(
                (
                    card.name,
                    card.proplist['device.description'],
                    profiles,
                    card.profile_active.name,
                )
            )
        return result
    
    @sdbus.dbus_method_async(
        input_signature="ss",
        result_signature="b",
        flags=sdbus.DbusUnprivilegedFlag
    )
    async def set_profile(self, card_name: str, profile_name: str):
        card = self.pulse.get_card_by_name(card_name)
        profile = next((p for p in card.profile_list if p.name == profile_name)) # type: ignore
        self.pulse.card_profile_set(card, profile)
        return True

    @sdbus.dbus_method_async(
        result_signature="a(ssixbiadsb)s",
        flags=sdbus.DbusUnprivilegedFlag,
    )
    async def list_sinks(self):
        pulse = self.pulse
        default_sink_name = pulse.server_info().default_sink_name
        result = []

        for s in pulse.sink_list():
            result.append((
                s.name,
                s.description,
                s.index,
                s.card,
                bool(s.mute),
                s.channel_count,
                list(s.volume.values),
                s.port_active.available_state._value if s.port_active else 'unknown',
                s.name == default_sink_name,
            ))

        print(result)
        return (result, default_sink_name)
    
    @sdbus.dbus_method_async(
        input_signature="s",
        result_signature="b",
        flags=sdbus.DbusUnprivilegedFlag,
    )
    async def set_default_sink(self, sink_name: str) -> bool:
        try:
            target_sink = self.pulse.get_sink_by_name(sink_name)
        except Exception as e:
            print("could not get target sink", e)
            return False
        try:
            self.pulse.sink_default_set(target_sink)
        except Exception as e:
            print(e)
            return False

        # move all streams to the new default sink
        for stream in self.pulse.sink_input_list():
            self.pulse.sink_input_move(stream.index, target_sink.index)
        return True

async def main():
    # Open the system bus
    system_bus = sdbus.sd_bus_open_system()
    # Request a name on the system bus
    await system_bus.request_name_async(INTERFACE_NAME, 0)

    # Create and export the interface on the system bus
    interface = PulseDBusControl()
    handler = interface.export_to_dbus(OBJECT_PATH, system_bus)
    print("D-Bus service running on the system bus... Press Ctrl+C to stop.")

    # Keep the event loop running
    try:
        await asyncio.Future()
    finally:
        handler.stop()

if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
	    pass
