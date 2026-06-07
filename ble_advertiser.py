from __future__ import annotations

import threading


BLUEZ_SERVICE_NAME = "org.bluez"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
ADVERTISEMENT_PATH = "/com/alive/demo/advertisement0"
ALIVE_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"


class BLEAdvertiser:
    def __init__(self, local_name: str = "ALIVE-T480") -> None:
        self.local_name = local_name[:20]
        self._mainloop = None
        self._thread: threading.Thread | None = None
        self._bus = None
        self._ad_manager = None
        self._advertisement = None
        self._registration_done = threading.Event()
        self._registration_ok = False
        self.active = False

    def start(self) -> bool:
        try:
            import dbus
            import dbus.mainloop.glib
            import dbus.service
            from gi.repository import GLib
        except Exception as exc:
            print(f"[BLE] BlueZ advertiser unavailable: {exc}")
            return False

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        try:
            self._bus = dbus.SystemBus()
            adapter_path = self._find_adapter_path(self._bus)
            if adapter_path is None:
                print("[BLE] No BlueZ adapter with LEAdvertisingManager1 found.")
                return False
            adapter = self._bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
            self._ad_manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)
            self._advertisement = _Advertisement(self._bus, self.local_name)
            self._mainloop = GLib.MainLoop()
            self._ad_manager.RegisterAdvertisement(
                ADVERTISEMENT_PATH,
                {},
                reply_handler=self._registered,
                error_handler=self._register_error,
            )
            self._thread = threading.Thread(target=self._mainloop.run, daemon=True)
            self._thread.start()
            self._registration_done.wait(timeout=1.0)
            self.active = self._registration_ok
            if self.active:
                print(f"[BLE] Advertising as {self.local_name}")
            return self.active
        except Exception as exc:
            print(f"[BLE] Could not start BLE advertising: {exc}")
            self.stop()
            return False

    def stop(self) -> None:
        if self._ad_manager is not None:
            try:
                self._ad_manager.UnregisterAdvertisement(ADVERTISEMENT_PATH)
            except Exception:
                pass
        if self._mainloop is not None:
            try:
                self._mainloop.quit()
            except Exception:
                pass
        self.active = False

    def _registered(self) -> None:
        self._registration_ok = True
        self._registration_done.set()

    def _register_error(self, error) -> None:
        print(f"[BLE] RegisterAdvertisement failed: {error}")
        self._registration_ok = False
        self.active = False
        self._registration_done.set()

    @staticmethod
    def _find_adapter_path(bus):
        import dbus

        manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE,
        )
        objects = manager.GetManagedObjects()
        for path, interfaces in objects.items():
            if LE_ADVERTISING_MANAGER_IFACE in interfaces:
                return path
        return None


class _Advertisement:
    def __init__(self, bus, local_name: str) -> None:
        import dbus
        import dbus.service

        class AdvertisementObject(dbus.service.Object):
            @dbus.service.method(
                DBUS_PROP_IFACE,
                in_signature="s",
                out_signature="a{sv}",
            )
            def GetAll(self, interface):
                import dbus

                if interface != LE_ADVERTISEMENT_IFACE:
                    raise dbus.exceptions.DBusException(
                        "Invalid interface",
                        name="org.freedesktop.DBus.Error.InvalidArgs",
                    )
                return {
                    "Type": dbus.String("peripheral"),
                    "ServiceUUIDs": dbus.Array(
                        [dbus.String(ALIVE_SERVICE_UUID)],
                        signature="s",
                    ),
                    "LocalName": dbus.String(local_name),
                    "Includes": dbus.Array([dbus.String("tx-power")], signature="s"),
                }

            @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
            def Release(self):
                return

        self.object = AdvertisementObject(bus, ADVERTISEMENT_PATH)
