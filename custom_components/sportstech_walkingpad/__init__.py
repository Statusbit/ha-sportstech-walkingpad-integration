"""Sportstech WalkingPad Home Assistant integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    CONF_DEVICE_NAME,
    # NEU: Konfigurationsschlüssel für ausgeschlossene Benutzer importieren
    CONF_EXCLUDED_USERS,
    CONF_MAC_ADDRESS,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .coordinator import WalkingPadCoordinator

_LOGGER = logging.getLogger(__name__)

# GEÄNDERT: Platform.SELECT hinzugefügt, damit die Benutzer-Dropdown-Entität geladen wird
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
]

_ATTR_SPEED = "speed"
_ATTR_INCLINE = "incline"
# NEU: Service-Parameter für die explizite Angabe eines Benutzernamens
_ATTR_USER = "user"

# NEU: Validierungsschemas für den optionalen user-Parameter beim Start und den assign_user-Service
_SERVICE_START_SCHEMA = vol.Schema({
    vol.Optional(_ATTR_USER): str,
})
_SERVICE_ASSIGN_USER_SCHEMA = vol.Schema({
    vol.Required(_ATTR_USER): str,
})
_SERVICE_SET_SPEED_SCHEMA = vol.Schema({
    vol.Required(_ATTR_SPEED): vol.All(vol.Coerce(float), vol.Range(min=0, max=25)),
})
_SERVICE_SET_INCLINE_SCHEMA = vol.Schema({
    vol.Required(_ATTR_INCLINE): vol.All(vol.Coerce(int), vol.Range(min=0, max=15)),
})


def _all_coordinators(hass: HomeAssistant) -> list[WalkingPadCoordinator]:
    return list(hass.data.get(DOMAIN, {}).values())


# NEU: Listener, der die Integration neu lädt, sobald in den Optionen Benutzer ausgeschlossen/freigegeben werden
async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options (e.g. excluded users) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sportstech WalkingPad from a config entry."""
    coordinator = WalkingPadCoordinator(
        hass,
        mac=entry.data[CONF_MAC_ADDRESS],
        device_name=entry.data.get(CONF_DEVICE_NAME, "WalkingPad"),
        poll_interval=entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        # NEU: Ausgeschlossene Benutzer-IDs aus den ConfigEntry-Optionen an den Coordinator übergeben
        excluded_user_ids=entry.options.get(CONF_EXCLUDED_USERS, []),
    )

    # NEU: Benutzerliste beim Einrichten der Integration einmalig aus Home Assistant laden
    await coordinator.async_refresh_users()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    # NEU: Auf Optionsänderungen über das Zahnrad-Menü reagieren
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once (guard against multiple config entries)
    if not hass.services.has_service(DOMAIN, "start"):
        # GEÄNDERT: Reicht sowohl call.context als auch den optionalen Parameter 'user' an async_start weiter
        async def _start(call: ServiceCall) -> None:
            user_name: str | None = call.data.get(_ATTR_USER)
            for coord in _all_coordinators(hass):
                await coord.async_start(context=call.context, user_name=user_name)

        async def _stop(_call: ServiceCall) -> None:
            for coord in _all_coordinators(hass):
                await coord.async_stop()

        async def _pause(_call: ServiceCall) -> None:
            for coord in _all_coordinators(hass):
                await coord.async_pause()

        async def _set_speed(call: ServiceCall) -> None:
            speed: float = call.data[_ATTR_SPEED]
            for coord in _all_coordinators(hass):
                await coord.async_set_speed(speed)

        async def _set_incline(call: ServiceCall) -> None:
            incline: int = call.data[_ATTR_INCLINE]
            for coord in _all_coordinators(hass):
                await coord.async_set_incline(incline)

        # NEU: Service-Handler zum nachträglichen oder laufenden Zuordnen eines Benutzers
        async def _assign_user(call: ServiceCall) -> None:
            user_name: str = call.data[_ATTR_USER]
            for coord in _all_coordinators(hass):
                coord.set_workout_user_by_name(user_name, explicit=True)

        # GEÄNDERT: Schema für den optionalen user-Parameter beim start-Service hinterlegt
        hass.services.async_register(DOMAIN, "start", _start, schema=_SERVICE_START_SCHEMA)
        hass.services.async_register(DOMAIN, "stop", _stop)
        hass.services.async_register(DOMAIN, "pause", _pause)
        hass.services.async_register(DOMAIN, "set_speed", _set_speed, schema=_SERVICE_SET_SPEED_SCHEMA)
        hass.services.async_register(DOMAIN, "set_incline", _set_incline, schema=_SERVICE_SET_INCLINE_SCHEMA)
        # NEU: Neuen Service 'assign_user' registrieren
        hass.services.async_register(DOMAIN, "assign_user", _assign_user, schema=_SERVICE_ASSIGN_USER_SCHEMA)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: WalkingPadCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()

    # Remove services when no entries remain
    if not hass.data.get(DOMAIN):
        # GEÄNDERT: Auch den neuen Service 'assign_user' beim Entladen sauber entfernen
        for service in ("start", "stop", "pause", "set_speed", "set_incline", "assign_user"):
            hass.services.async_remove(DOMAIN, service)

    return unload_ok
