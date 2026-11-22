"""Select entities for the Sportstech WalkingPad integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WalkingPadCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WalkingPad select entities from a config entry."""
    coordinator: WalkingPadCoordinator = hass.data[DOMAIN][entry.entry_id]
    # NEU: Dropdown-Entität für die Auswahl des Trainingsbenutzers registrieren
    async_add_entities([WalkingPadWorkoutUserSelect(coordinator)])


def _device_info(coordinator: WalkingPadCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.mac)},
        name=coordinator.device_name,
        manufacturer="Sportstech",
        model="WalkingPad",
    )


# NEU: Select-Entität (analog zu einem input_select-Helfer, aber direkt am Gerät integriert)
class WalkingPadWorkoutUserSelect(
    CoordinatorEntity[WalkingPadCoordinator], SelectEntity, RestoreEntity
):
    """Dropdown entity to select or reassign the workout user."""

    _attr_has_entity_name = True
    _attr_translation_key = "workout_user"
    _attr_name = "Workout User"
    _attr_icon = "mdi:account-switch-outline"

    def __init__(self, coordinator: WalkingPadCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_workout_user"
        self._attr_device_info = _device_info(coordinator)

    async def async_added_to_hass(self) -> None:
        """Restore last selected user after a Home Assistant restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in self.options:
            self.coordinator.set_workout_user_by_name(last_state.state, explicit=False)

    @property
    def options(self) -> list[str]:
        """Return list of allowed HA user names plus 'Gast'."""
        return list(self.coordinator.data.available_users.values())

    @property
    def current_option(self) -> str | None:
        """Return the currently assigned user name."""
        return self.coordinator.data.active_user_name

    async def async_select_option(self, option: str) -> None:
        """Handle manual selection of a user in the UI or via service call."""
        self.coordinator.set_workout_user_by_name(option, explicit=True)
