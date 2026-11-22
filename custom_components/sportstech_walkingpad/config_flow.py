"""Config flow for the Sportstech WalkingPad integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
# NEU: HomeAssistant, callback und selector für die Benutzer-Mehrfachauswahl importieren
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_NAME,
    # NEU: Konfigurationsschlüssel für ausgeschlossene Benutzer importieren
    CONF_EXCLUDED_USERS,
    CONF_MAC_ADDRESS,
    DEFAULT_DEVICE_NAME,
    DOMAIN,
    WALKINGPAD_SERVICE_UUID,
)

_LOGGER = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


# NEU: Hilfsfunktion, die alle aktiven, nicht-systemgenerierten Home-Assistant-Benutzer lädt
async def _get_selectable_ha_users(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Return all non-system Home Assistant users as SelectOptionDict list."""
    # Alle Benutzer aus der HA-Authentifizierung abrufen
    users = await hass.auth.async_get_users()
    options: list[selector.SelectOptionDict] = []
    for user in users:
        # Interne System-Accounts (z. B. Supervisor, Home Assistant Content) und deaktivierte User überspringen
        if user.system_generated or not user.is_active:
            continue
        # Anzeigenamen verwenden (Fallback auf die User-ID, falls kein Name gesetzt ist)
        label = user.name or user.id
        options.append(selector.SelectOptionDict(value=user.id, label=label))
    # Alphabetisch nach Anzeigenamen sortieren
    options.sort(key=lambda item: item["label"].lower())
    return options


class WalkingPadConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Sportstech WalkingPad."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_devices: dict[str, str] = {}  # mac -> name
        self._mac: str | None = None
        self._name: str | None = None

    # NEU: Verknüpft den OptionsFlow ("Konfigurieren"-Button in der Integration) mit diesem ConfigFlow
    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> WalkingPadOptionsFlow:
        """Return the options flow handler."""
        return WalkingPadOptionsFlow()

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
        """Handle device discovered via bluetooth integration."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._mac = discovery_info.address
        self._name = discovery_info.name or DEFAULT_DEVICE_NAME

        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Confirm a bluetooth-discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._name or DEFAULT_DEVICE_NAME,
                data={
                    CONF_MAC_ADDRESS: self._mac,
                    CONF_DEVICE_NAME: self._name,
                },
                # NEU: Ausgewählte ausgeschlossene Benutzer direkt in entry.options speichern
                options={
                    CONF_EXCLUDED_USERS: user_input.get(CONF_EXCLUDED_USERS, []),
                },
            )

        # NEU: HA-Benutzer für das Auswahlfeld im Bestätigungsdialog laden
        user_options = await _get_selectable_ha_users(self.hass)
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._name, "mac": self._mac},
            # GEÄNDERT: Mehrfachauswahl für auszuschließende Benutzer (z. B. Tablet, MQTT) ergänzt
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_EXCLUDED_USERS, default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=user_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        discovered = bluetooth.async_discovered_service_info(self.hass)
        for info in discovered:
            if WALKINGPAD_SERVICE_UUID.lower() in [s.lower() for s in info.service_uuids]:
                self._discovered_devices[info.address] = info.name or info.address

        return await self.async_step_manual(user_input)

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle manual MAC address entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = user_input[CONF_MAC_ADDRESS].upper().strip()
            if not _MAC_RE.match(mac):
                errors[CONF_MAC_ADDRESS] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME),
                    data={
                        CONF_MAC_ADDRESS: mac,
                        CONF_DEVICE_NAME: user_input.get(CONF_DEVICE_NAME, DEFAULT_DEVICE_NAME),
                    },
                    # NEU: Ausgeschlossene Benutzer auch bei manueller Einrichtung speichern
                    options={
                        CONF_EXCLUDED_USERS: user_input.get(CONF_EXCLUDED_USERS, []),
                    },
                )

        # NEU: HA-Benutzer für das Auswahlfeld im manuellen Einrichtungsdialog laden
        user_options = await _get_selectable_ha_users(self.hass)
        return self.async_show_form(
            step_id="manual",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC_ADDRESS): str,
                    vol.Optional(CONF_DEVICE_NAME, default=DEFAULT_DEVICE_NAME): str,
                    # NEU: Mehrfachauswahl für auszuschließende Benutzer (z. B. Tablet, MQTT)
                    vol.Optional(CONF_EXCLUDED_USERS, default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=user_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )


# NEU: OptionsFlow-Klasse, damit die Benutzerliste jederzeit nachträglich in HA geändert werden kann
class WalkingPadOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow to exclude/include Home Assistant users."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the WalkingPad options."""
        if user_input is not None:
            # Speichert die aktualisierte Ausschlussliste in config_entry.options
            return self.async_create_entry(
                title="",
                data={
                    CONF_EXCLUDED_USERS: user_input.get(CONF_EXCLUDED_USERS, []),
                },
            )

        # Aktuelle HA-Benutzer laden und bereits gespeicherte Ausschlüsse vorbelegen
        user_options = await _get_selectable_ha_users(self.hass)
        valid_ids = {opt["value"] for opt in user_options}
        current_excluded = [
            uid
            for uid in self.config_entry.options.get(CONF_EXCLUDED_USERS, [])
            if uid in valid_ids
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_EXCLUDED_USERS,
                        default=current_excluded,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=user_options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
