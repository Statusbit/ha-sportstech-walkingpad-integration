"""Sensor entities for the Sportstech WalkingPad integration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, GUEST_USER_ID
from .coordinator import WalkingPadCoordinator


@dataclass(frozen=True)
class WalkingPadSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with a value accessor."""

    value_fn: Any = None  # Callable[[WalkingPadData], StateType]


# ---------------------------------------------------------------------------
# Session sensors (reset on each belt stop)
# ---------------------------------------------------------------------------

SENSOR_DESCRIPTIONS: tuple[WalkingPadSensorDescription, ...] = (
    WalkingPadSensorDescription(
        key="state",
        translation_key="state",
        name="State",
        icon="mdi:walk",
        value_fn=lambda d: d.state,
    ),
    WalkingPadSensorDescription(
        key="speed",
        translation_key="speed",
        name="Speed",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.speed,
    ),
    WalkingPadSensorDescription(
        key="incline",
        translation_key="incline",
        name="Incline",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:slope-uphill",
        value_fn=lambda d: d.incline,
    ),
    WalkingPadSensorDescription(
        key="heart_rate",
        translation_key="heart_rate",
        name="Heart Rate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heart-pulse",
        value_fn=lambda d: d.heart if d.heart > 0 else None,
    ),
    WalkingPadSensorDescription(
        key="workout_time",
        translation_key="workout_time",
        name="Workout Time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: round(d.time / 60, 2),
    ),
    WalkingPadSensorDescription(
        key="distance",
        translation_key="distance",
        name="Distance",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.distance,
    ),
    WalkingPadSensorDescription(
        key="calories",
        translation_key="calories",
        name="Calories",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:fire",
        suggested_display_precision=1,
        value_fn=lambda d: d.calories,
    ),
    WalkingPadSensorDescription(
        key="steps",
        translation_key="steps",
        name="Steps",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:foot-print",
        value_fn=lambda d: d.steps,
    ),
)

# ---------------------------------------------------------------------------
# Diagnostic sensors — device limits, populated after PARAM query on connect
# ---------------------------------------------------------------------------

DIAGNOSTIC_SENSOR_DESCRIPTIONS: tuple[WalkingPadSensorDescription, ...] = (
    WalkingPadSensorDescription(
        key="max_speed",
        translation_key="max_speed",
        name="Max Speed",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda d: d.max_speed if d.params_received else None,
    ),
    WalkingPadSensorDescription(
        key="max_incline",
        translation_key="max_incline",
        name="Max Incline",
        native_unit_of_measurement="%",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:slope-uphill",
        value_fn=lambda d: d.max_incline if d.params_received else None,
    ),
)

# ---------------------------------------------------------------------------
# Total (lifetime) sensors — accumulate across sessions, persist across reboots
# ---------------------------------------------------------------------------

TOTAL_SENSOR_DESCRIPTIONS: tuple[WalkingPadSensorDescription, ...] = (
    WalkingPadSensorDescription(
        key="total_workout_time",
        translation_key="total_workout_time",
        name="Total Workout Time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: round(d.time / 60, 2),
    ),
    WalkingPadSensorDescription(
        key="total_distance",
        translation_key="total_distance",
        name="Total Distance",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.distance,
    ),
    WalkingPadSensorDescription(
        key="total_calories",
        translation_key="total_calories",
        name="Total Calories",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:fire",
        suggested_display_precision=1,
        value_fn=lambda d: d.calories,
    ),
    WalkingPadSensorDescription(
        key="total_steps",
        translation_key="total_steps",
        name="Total Steps",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:foot-print",
        value_fn=lambda d: d.steps,
    ),
)

# ---------------------------------------------------------------------------
# Per-user lifetime sensors (excludes Guest; for statistics by user)
# ---------------------------------------------------------------------------

USER_TOTAL_METRICS: tuple[dict[str, Any], ...] = (
    {
        "metric": "distance",
        "translation_key": "user_distance",
        "unit": UnitOfLength.METERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "icon": None,
        "precision": 0,
    },
    {
        "metric": "workout_time",
        "translation_key": "user_workout_time",
        "unit": UnitOfTime.MINUTES,
        "device_class": SensorDeviceClass.DURATION,
        "icon": None,
        "precision": 2,
    },
    {
        "metric": "calories",
        "translation_key": "user_calories",
        "unit": "kcal",
        "device_class": None,
        "icon": "mdi:fire",
        "precision": 1,
    },
    {
        "metric": "steps",
        "translation_key": "user_steps",
        "unit": None,
        "device_class": None,
        "icon": "mdi:foot-print",
        "precision": 0,
    },
)


def _slug_user(user_name: str, user_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", user_name.lower()).strip("_")
    return slug or user_id[:8].lower()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WalkingPad sensor entities from a config entry."""
    coordinator: WalkingPadCoordinator = hass.data[DOMAIN][entry.entry_id]

    user_entities: list[SensorEntity] = []
    for uid, uname in coordinator.data.available_users.items():
        if uid == GUEST_USER_ID:
            continue
        for metric_cfg in USER_TOTAL_METRICS:
            user_entities.append(
                WalkingPadUserTotalSensor(
                    coordinator=coordinator,
                    user_id=uid,
                    user_name=uname,
                    metric_cfg=metric_cfg,
                )
            )

    async_add_entities([
        *(WalkingPadSensor(coordinator, desc) for desc in SENSOR_DESCRIPTIONS),
        *(WalkingPadSensor(coordinator, desc) for desc in DIAGNOSTIC_SENSOR_DESCRIPTIONS),
        *(WalkingPadTotalSensor(coordinator, desc) for desc in TOTAL_SENSOR_DESCRIPTIONS),
        WalkingPadLastWorkoutSensor(coordinator),
        *user_entities,
    ])


# ---------------------------------------------------------------------------
# Entity classes
# ---------------------------------------------------------------------------

def _device_info(coordinator: WalkingPadCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.mac)},
        name=coordinator.device_name,
        manufacturer="Sportstech",
        model="WalkingPad",
    )


class WalkingPadSensor(CoordinatorEntity[WalkingPadCoordinator], SensorEntity):
    """Live session sensor — resets when the belt stops."""

    entity_description: WalkingPadSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WalkingPadCoordinator,
        description: WalkingPadSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.mac}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.data.available

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)


class WalkingPadTotalSensor(CoordinatorEntity[WalkingPadCoordinator], RestoreSensor):
    """Lifetime accumulator sensor."""

    entity_description: WalkingPadSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WalkingPadCoordinator,
        description: WalkingPadSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.mac}_{description.key}"
        self._attr_device_info = _device_info(coordinator)
        self._attr_native_value: float = 0.0
        self._last_session_value: float = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_data = await self.async_get_last_sensor_data()
        if last_data and last_data.native_value is not None:
            self._attr_native_value = float(last_data.native_value)

    @callback
    def _handle_coordinator_update(self) -> None:
        current = float(self.entity_description.value_fn(self.coordinator.data) or 0)
        if self._last_session_value > 0 and current == 0:
            self._attr_native_value = (self._attr_native_value or 0) + self._last_session_value
        self._last_session_value = current
        self.async_write_ha_state()


class WalkingPadLastWorkoutSensor(CoordinatorEntity[WalkingPadCoordinator], SensorEntity):
    """Sensor holding the last completed workout and its assigned user."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_workout"
    _attr_icon = "mdi:history"
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_device_class = SensorDeviceClass.DISTANCE

    def __init__(self, coordinator: WalkingPadCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_last_workout"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int | None:
        """Return distance of the last workout as primary sensor state."""
        if self.coordinator.data.last_workout is None:
            return None
        return self.coordinator.data.last_workout.distance_m

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return user, duration, calories, steps and timestamps as DB attributes."""
        if self.coordinator.data.last_workout is None:
            return None
        return self.coordinator.data.last_workout.as_dict()


class WalkingPadUserTotalSensor(CoordinatorEntity[WalkingPadCoordinator], RestoreSensor):
    """Cumulative workout sensor for a specific HA user (excludes Guest)."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: WalkingPadCoordinator,
        user_id: str,
        user_name: str,
        metric_cfg: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._user_id = user_id
        self._user_name = user_name
        self._metric: str = metric_cfg["metric"]
        self._precision: int = metric_cfg["precision"]

        slug = _slug_user(user_name, user_id)
        self._attr_unique_id = f"{coordinator.mac}_user_{slug}_{self._metric}"
        self._attr_translation_key = metric_cfg["translation_key"]
        self._attr_translation_placeholders = {"user_name": user_name}
        self._attr_native_unit_of_measurement = metric_cfg["unit"]
        self._attr_device_class = metric_cfg["device_class"]
        if metric_cfg["icon"]:
            self._attr_icon = metric_cfg["icon"]
        if self._precision > 0:
            self._attr_suggested_display_precision = self._precision
        self._attr_device_info = _device_info(coordinator)

        self.coordinator.ensure_user_totals(self._user_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_data = await self.async_get_last_sensor_data()
        if last_data and last_data.native_value is not None:
            try:
                restored_val = float(last_data.native_value)
                self.coordinator.set_restored_user_total(
                    self._user_id, self._metric, restored_val
                )
            except (TypeError, ValueError):
                pass

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | int:
        totals = self.coordinator.user_totals.get(self._user_id)
        val = totals.get(self._metric, 0.0) if totals else 0.0
        if self._precision == 0:
            return int(round(val))
        return round(float(val), self._precision)
