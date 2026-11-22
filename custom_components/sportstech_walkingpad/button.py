"""Button entities for the Sportstech WalkingPad integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
# GEÄNDERT: Context importiert, um den drückenden Benutzer beim Start-Button zu erkennen
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WalkingPadCoordinator


@dataclass(frozen=True)
class WalkingPadButtonDescription(ButtonEntityDescription):
    """Extends ButtonEntityDescription with an async action."""

    # GEÄNDERT: Action-Signatur nimmt jetzt zusätzlich den Context entgegen
    action: Any = None  # Callable[[WalkingPadCoordinator, Context | None], Coroutine]


BUTTON_DESCRIPTIONS: tuple[WalkingPadButtonDescription, ...] = (
    WalkingPadButtonDescription(
        key="start",
        translation_key="start",
        name="Start",
        icon="mdi:play",
        # GEÄNDERT: Reicht self._context an coord.async_start weiter
        action=lambda coord, ctx: coord.async_start(context=ctx),
    ),
    WalkingPadButtonDescription(
        key="stop",
        translation_key="stop",
        name="Stop",
        icon="mdi:stop",
        # GEÄNDERT: Context-Parameter der Einheitlichkeit halber ergänzt
        action=lambda coord, _ctx: coord.async_stop(),
    ),
    WalkingPadButtonDescription(
        key="pause",
        translation_key="pause",
        name="Pause",
        icon="mdi:pause",
        # GEÄNDERT: Context-Parameter der Einheitlichkeit halber ergänzt
        action=lambda coord, _ctx: coord.async_pause(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WalkingPad button entities from a config entry."""
    coordinator: WalkingPadCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WalkingPadButton(coordinator, desc) for desc in BUTTON_DESCRIPTIONS
    )


def _device_info(coordinator: WalkingPadCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.mac)},
        name=coordinator.device_name,
        manufacturer="Sportstech",
        model="WalkingPad",
    )


class WalkingPadButton(CoordinatorEntity[WalkingPadCoordinator], ButtonEntity):
    """A button that sends a control command to the WalkingPad."""

    entity_description: WalkingPadButtonDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WalkingPadCoordinator,
        description: WalkingPadButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.mac}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        # GEÄNDERT: Übergibt self._context (enthält die HA-User-ID des Klickenden) an die Button-Aktion
        await self.entity_description.action(self.coordinator, self._context)
