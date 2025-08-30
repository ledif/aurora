#!/usr/bin/env python3
import asyncio, subprocess
from dbus_next.aio import MessageBus
from dbus_next import BusType

NOTIFIER_SERVICE_NAME = "reboot-notifier-show.service"
SCREENSAVER_SERVICE = "org.freedesktop.ScreenSaver"
SCREENSAVER_PATH = "/ScreenSaver"
SCREENSAVER_INTERFACE = "org.freedesktop.ScreenSaver"

async def main():
    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    introspection = await bus.introspect(SCREENSAVER_SERVICE, SCREENSAVER_PATH)
    obj = bus.get_proxy_object(SCREENSAVER_SERVICE, SCREENSAVER_PATH, introspection)
    iface = obj.get_interface(SCREENSAVER_INTERFACE)

    def on_active_changed(active: bool):
        if not active:  # Active=false means user unlocked KScreenSaver
            subprocess.Popen(["systemctl", "--user", "start", NOTIFIER_SERVICE_NAME])

    iface.on_active_changed(on_active_changed)
    await asyncio.get_event_loop().create_future()

asyncio.run(main())