"""BLE coordinator for the Sportstech WalkingPad integration.

Protocol: FitHome/F37 proprietary BLE (service FFF0, notify FFF1, write FFF2).

Frame format (both directions):
    [0x02]  payload bytes  XOR(payload)  [0x03]

Periodic poll (protocol 1 – treadmill):
    TX: [0x02, 0x51, 0x51, 0x03]
    RX: [0x02, 0x51, state, speed, incline, time_lo, time_hi,
             dist_lo, dist_hi, cal_lo, cal_hi, steps_lo, steps_hi,
             heart, …, checksum, 0x03]

Param query (protocol 1):
    Speed limits TX:   [0x02, 0x50, 0x02, 0x52, 0x03]
    Speed limits RX:   [0x02, 0x50, 0x02, maxSpeed*10, minSpeed*10, …]
    Incline limits TX: [0x02, 0x50, 0x03, 0x53, 0x03]
    Incline limits RX: [0x02, 0x50, 0x03, maxIncline, minIncline, …]

Source: reverse-engineered from com.fithome.bluetooth.BLEDevice
        in Sportstech Live 5.1.9 APK.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CHAR_RECV_UUID,
    CHAR_SEND_UUID,
    CMD_PARAM_INCLINE,
    CMD_PARAM_SPEED,
    CMD_PAUSE,
    CMD_START,
    CMD_STOP,
    DATA_STATES,
    DOMAIN,
    EVENT_WORKOUT_COMPLETED,
    EVENT_WORKOUT_REASSIGNED,
    FRAME_ETX,
    FRAME_STX,
    GUEST_USER_ID,
    GUEST_USER_NAME,
    RAW_STATE_MAP,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPING,
    STATE_UNKNOWN,
)

_LOGGER = logging.getLogger(__name__)

_POLL_TIMEOUT = 10.0   # seconds to wait for a STATE notification
_PARAM_TIMEOUT = 5.0   # seconds to wait for a PARAM notification

ACTIVE_WORKOUT_STATES = {STATE_STARTING, STATE_RUNNING, STATE_PAUSED, STATE_STOPPING}


def _empty_user_totals() -> dict[str, float]:
    """Return a fresh zeroed accumulator dict for a workout user."""
    return {
        "distance": 0.0,
        "workout_time": 0.0,
        "calories": 0.0,
        "steps": 0.0,
    }


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class WorkoutRecord:
    """Represents a completed workout session."""

    user_id: str
    user_name: str
    duration_s: int
    distance_m: int
    calories: float
    steps: int
    started_at: str | None
    ended_at: str

    def as_dict(self) -> dict[str, Any]:
        """Convert the workout record into a dictionary for HA attributes and events."""
        return {
            "user_id": self.user_id,
            "user": self.user_name,
            "duration_s": self.duration_s,
            "duration_min": round(self.duration_s / 60, 2),
            "distance_m": self.distance_m,
            "calories": self.calories,
            "steps": self.steps,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


@dataclass
class WalkingPadData:
    """Latest snapshot from the WalkingPad."""

    available: bool = False
    state: str = STATE_IDLE

    # Live metrics – only valid when state is RUNNING / PAUSED
    speed: float = 0.0      # km/h  (0.0–max, resolution 0.1)
    incline: int = 0        # %     (0–15)
    heart: int = 0          # bpm   (0 = no sensor)

    # Session-cumulative metrics (reset on STOP)
    time: int = 0           # s
    distance: int = 0       # m
    calories: float = 0.0   # kcal
    steps: int = 0          # step count

    # Device limits (populated from PARAM query on connect)
    max_speed: float = 6.0   # km/h
    min_speed: float = 0.5   # km/h
    max_incline: int = 15    # %
    min_incline: int = 0     # %
    params_received: bool = False

    # Peripheral state (optimistic – no feedback from device)
    light_on: bool = False

    # Active user, allowed users (incl. Guest in select), and last workout
    active_user_id: str = GUEST_USER_ID
    active_user_name: str = GUEST_USER_NAME
    available_users: dict[str, str] = field(
        default_factory=lambda: {GUEST_USER_ID: GUEST_USER_NAME}
    )  # Mapping: user_id -> Anzeigename
    last_workout: WorkoutRecord | None = None


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------


def _build_frame(payload: bytes) -> bytes:
    """Wrap *payload* in STX + payload + XOR(payload) + ETX."""
    checksum = 0
    for b in payload:
        checksum ^= b
    return bytes([FRAME_STX]) + payload + bytes([checksum & 0xFF, FRAME_ETX])


def _validate_frame(data: bytes) -> bool:
    """Return True if *data* has correct framing and XOR checksum."""
    if len(data) < 4 or data[0] != FRAME_STX or data[-1] != FRAME_ETX:
        return False
    xor = 0
    for b in data[1:-1]:
        xor ^= b
    return xor == 0


# Pre-built poll frame (sent to FFF2)
_FRAME_STATE_QUERY = _build_frame(bytes([0x51]))


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class WalkingPadCoordinator(DataUpdateCoordinator[WalkingPadData]):
    """Manages the BLE connection and periodic state polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        mac: str,
        device_name: str,
        poll_interval: int = 5,
        excluded_user_ids: list[str] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{mac}",
            update_interval=timedelta(seconds=poll_interval),
        )
        self.mac = mac
        self.device_name = device_name
        self._excluded_user_ids: set[str] = set(excluded_user_ids or [])

        self._client: BleakClient | None = None
        self._notification_ready = asyncio.Event()
        self._param_ready = asyncio.Event()
        self.data: WalkingPadData = WalkingPadData()

        # NEU: Kumulierte Summen pro HA-Benutzer (ohne Gast): user_id -> {metric: value}
        self.user_totals: dict[str, dict[str, float]] = {}

        # Wrap detection: device timer resets at 99 min 99 s (6039 s)
        self._raw_time: int = 0
        self._time_offset: int = 0

        # Statusvariablen zur Erkennung von Start, Ende und manueller Zuweisung einer Session
        self._session_started_at: str | None = None
        self._session_in_progress: bool = False
        self._user_assigned_for_current_session: bool = False

    # ------------------------------------------------------------------
    # Benutzerverwaltung, Summen & Zuordnung
    # ------------------------------------------------------------------

    def ensure_user_totals(self, user_id: str) -> dict[str, float]:
        """Ensure an accumulator dict exists for a non-guest user_id."""
        if user_id == GUEST_USER_ID:
            return _empty_user_totals()
        if user_id not in self.user_totals:
            self.user_totals[user_id] = _empty_user_totals()
        return self.user_totals[user_id]

    def set_restored_user_total(self, user_id: str, metric: str, value: float) -> None:
        """Restore a persisted per-user total without overwriting higher live values."""
        if user_id == GUEST_USER_ID:
            return
        totals = self.ensure_user_totals(user_id)
        if metric not in totals:
            totals[metric] = 0.0
        if value > totals[metric]:
            totals[metric] = value

    def _record_workout_for_user(self, record: WorkoutRecord) -> None:
        """Add completed workout metrics to the user's totals (skipping Guest)."""
        if record.user_id == GUEST_USER_ID:
            return
        totals = self.ensure_user_totals(record.user_id)
        totals["distance"] = round(totals["distance"] + float(record.distance_m), 2)
        totals["workout_time"] = round(
            totals["workout_time"] + round(record.duration_s / 60, 2), 2
        )
        totals["calories"] = round(totals["calories"] + float(record.calories), 2)
        totals["steps"] = round(totals["steps"] + float(record.steps), 0)

    async def async_refresh_users(self) -> None:
        """Load active non-system HA users minus excluded ones, plus Guest."""
        users = await self.hass.auth.async_get_users()
        allowed: dict[str, str] = {}
        for user in users:
            if user.system_generated or not user.is_active:
                continue
            if user.id in self._excluded_user_ids:
                continue
            allowed[user.id] = user.name or user.id

        for uid in allowed:
            self.ensure_user_totals(uid)

        sorted_allowed = dict(
            sorted(allowed.items(), key=lambda item: item[1].lower())
        )
        sorted_allowed[GUEST_USER_ID] = GUEST_USER_NAME
        self.data.available_users = sorted_allowed

        if self.data.active_user_id not in sorted_allowed:
            self.data.active_user_id = GUEST_USER_ID
            self.data.active_user_name = GUEST_USER_NAME

    def set_workout_user_by_name(self, user_name: str, explicit: bool = True) -> bool:
        """Assign workout user by display name (used by select entity & service)."""
        for uid, name in self.data.available_users.items():
            if name == user_name:
                self._apply_user(uid, name, explicit=explicit)
                return True
        _LOGGER.warning("Unknown or excluded workout user: %s", user_name)
        return False

    def set_workout_user_by_id(self, user_id: str, explicit: bool = True) -> bool:
        """Assign workout user by HA user_id (or GUEST_USER_ID)."""
        if user_id not in self.data.available_users:
            return False
        self._apply_user(user_id, self.data.available_users[user_id], explicit=explicit)
        return True

    def _apply_user(self, user_id: str, user_name: str, explicit: bool) -> None:
        """Update active user and retroactively update last completed workout if idle."""
        self.data.active_user_id = user_id
        self.data.active_user_name = user_name
        if explicit:
            self._user_assigned_for_current_session = True

        if not self._session_in_progress and self.data.last_workout is not None:
            old_user_id = self.data.last_workout.user_id
            if old_user_id != user_id:
                rec = self.data.last_workout
                # Falls das letzte Workout vorher einem echten Benutzer zugeordnet war,
                # diesen Betrag wieder abziehen und auf den neuen Benutzer (falls nicht Gast) übertragen.
                if old_user_id != GUEST_USER_ID and old_user_id in self.user_totals:
                    old_t = self.user_totals[old_user_id]
                    old_t["distance"] = max(0.0, round(old_t["distance"] - float(rec.distance_m), 2))
                    old_t["workout_time"] = max(
                        0.0, round(old_t["workout_time"] - round(rec.duration_s / 60, 2), 2)
                    )
                    old_t["calories"] = max(0.0, round(old_t["calories"] - float(rec.calories), 2))
                    old_t["steps"] = max(0.0, round(old_t["steps"] - float(rec.steps), 0))

                rec.user_id = user_id
                rec.user_name = user_name
                self._record_workout_for_user(rec)

                self.hass.bus.async_fire(
                    EVENT_WORKOUT_REASSIGNED,
                    {
                        "mac": self.mac,
                        "device_name": self.device_name,
                        **rec.as_dict(),
                    },
                )

        self.async_set_updated_data(self.data)

    def _try_auto_assign_from_context(self, context: Context | None) -> None:
        """If started by an allowed HA user, assign them; otherwise fall back to Guest."""
        if context and context.user_id and context.user_id in self.data.available_users:
            self.set_workout_user_by_id(context.user_id, explicit=True)
        elif not self._user_assigned_for_current_session:
            self.set_workout_user_by_id(GUEST_USER_ID, explicit=False)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> WalkingPadData:
        """Called by HA every *update_interval* seconds."""
        try:
            await self._ensure_connected()
            await self._poll_state()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Poll failed for %s: %s", self.mac, exc)
            self.data.available = False
        return self.data

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _ensure_connected(self) -> None:
        """(Re-)connect to the device if needed."""
        if self._client and self._client.is_connected:
            return

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.mac, connectable=False
        )
        if ble_device is None:
            raise UpdateFailed(f"WalkingPad {self.mac} not found via BLE scanner")

        _LOGGER.debug("Connecting to %s (%s)", self.device_name, self.mac)
        self._client = await establish_connection(
            BleakClient,
            ble_device,
            self.mac,
            disconnected_callback=self._on_disconnected,
        )
        await self._client.start_notify(CHAR_RECV_UUID, self._on_notification)
        _LOGGER.debug("Connected to %s", self.device_name)
        await self._query_params()

    def _on_disconnected(self, _client: BleakClient) -> None:
        _LOGGER.debug("WalkingPad %s disconnected", self.mac)
        self.data.available = False
        self._client = None
        self._notification_ready.set()
        self._param_ready.set()

    # ------------------------------------------------------------------
    # Param query (device limits)
    # ------------------------------------------------------------------

    async def _query_params(self) -> None:
        """Query speed and incline limits from the device."""
        if not self._client or not self._client.is_connected:
            return
        try:
            self._param_ready.clear()
            await self._client.write_gatt_char(
                CHAR_SEND_UUID, _build_frame(CMD_PARAM_SPEED), response=False
            )
            await asyncio.wait_for(self._param_ready.wait(), timeout=_PARAM_TIMEOUT)
            self._param_ready.clear()
            await self._client.write_gatt_char(
                CHAR_SEND_UUID, _build_frame(CMD_PARAM_INCLINE), response=False
            )
            await asyncio.wait_for(self._param_ready.wait(), timeout=_PARAM_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.debug("No PARAM reply from %s – using defaults", self.mac)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_state(self) -> None:
        """Send a STATE query and wait up to *_POLL_TIMEOUT* s for the reply."""
        if not self._client or not self._client.is_connected:
            return

        self._notification_ready.clear()
        await self._client.write_gatt_char(CHAR_SEND_UUID, _FRAME_STATE_QUERY, response=False)

        try:
            await asyncio.wait_for(self._notification_ready.wait(), timeout=_POLL_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.debug("No STATE reply from %s within %.0f s", self.mac, _POLL_TIMEOUT)

    # ------------------------------------------------------------------
    # Notification handler
    # ------------------------------------------------------------------

    def _on_notification(self, _handle: int, data: bytes) -> None:
        """Called by bleak on every FFF1 notification."""
        if not _validate_frame(data):
            _LOGGER.debug("Bad frame from %s: %s", self.mac, data.hex())
            return

        msg_type = data[1]
        if msg_type == 0x51:
            self._parse_state_response(data)
            self._notification_ready.set()
        elif msg_type == 0x50:
            self._parse_param_response(data)
            self._param_ready.set()

    def _parse_state_response(self, data: bytes) -> None:
        """Parse a protocol-1 STATE response frame."""
        if len(data) < 5:
            return

        raw_state = data[2] & 0xFF
        ha_state = RAW_STATE_MAP.get(raw_state, STATE_UNKNOWN)

        self.data.state = ha_state
        self.data.available = True

        if ha_state in ACTIVE_WORKOUT_STATES and not self._session_in_progress:
            self._session_in_progress = True
            self._session_started_at = datetime.now(timezone.utc).isoformat()
            if not self._user_assigned_for_current_session:
                self.data.active_user_id = GUEST_USER_ID
                self.data.active_user_name = GUEST_USER_NAME

        if ha_state in DATA_STATES and len(data) > 15:
            self.data.speed    = round((data[3] & 0xFF) * 0.1, 1)
            self.data.incline  = data[4] & 0xFF
            self.data.heart    = data[13] & 0xFF

            if ha_state == STATE_RUNNING:
                raw_time = (data[5] & 0xFF) | ((data[6] & 0xFF) << 8)
                if raw_time < self._raw_time:
                    self._time_offset += self._raw_time
                self._raw_time = raw_time
                self.data.time     = self._time_offset + raw_time
                self.data.distance = (data[7] & 0xFF) | ((data[8] & 0xFF) << 8)
                self.data.calories = round(((data[9] & 0xFF) | ((data[10] & 0xFF) << 8)) * 0.1, 1)
                self.data.steps    = (data[11] & 0xFF) | ((data[12] & 0xFF) << 8)
        elif ha_state == STATE_IDLE:
            if self._session_in_progress and (self.data.time > 0 or self.data.distance > 0):
                record = WorkoutRecord(
                    user_id=self.data.active_user_id,
                    user_name=self.data.active_user_name,
                    duration_s=self.data.time,
                    distance_m=self.data.distance,
                    calories=self.data.calories,
                    steps=self.data.steps,
                    started_at=self._session_started_at,
                    ended_at=datetime.now(timezone.utc).isoformat(),
                )
                self.data.last_workout = record
                # NEU: Summen für den Benutzer (sofern nicht Gast) fortschreiben
                self._record_workout_for_user(record)

                self.hass.bus.async_fire(
                    EVENT_WORKOUT_COMPLETED,
                    {
                        "mac": self.mac,
                        "device_name": self.device_name,
                        **record.as_dict(),
                    },
                )

            self._session_in_progress = False
            self._session_started_at = None
            self._user_assigned_for_current_session = False

            self.data.speed = 0.0
            self.data.time = 0
            self._raw_time = 0
            self._time_offset = 0
            self.data.distance = 0
            self.data.calories = 0.0
            self.data.steps = 0
            self.data.heart = 0

    def _parse_param_response(self, data: bytes) -> None:
        """Parse a protocol-1 PARAM response frame."""
        if len(data) < 6:
            return

        sub_cmd = data[2] & 0xFF

        if sub_cmd == 0x02 and len(data) >= 7:
            self.data.max_speed = round((data[3] & 0xFF) / 10.0, 1)
            self.data.min_speed = round((data[4] & 0xFF) / 10.0, 1)
            self.data.params_received = True
            _LOGGER.debug(
                "Params from %s: max_speed=%.1f min_speed=%.1f",
                self.mac, self.data.max_speed, self.data.min_speed,
            )
        elif sub_cmd == 0x03 and len(data) >= 7:
            self.data.max_incline = data[3] & 0xFF
            self.data.min_incline = data[4] & 0xFF
            self.data.params_received = True
            _LOGGER.debug(
                "Params from %s: max_incline=%d min_incline=%d",
                self.mac, self.data.max_incline, self.data.min_incline,
            )

    # ------------------------------------------------------------------
    # Control commands
    # ------------------------------------------------------------------

    async def async_start(
        self,
        context: Context | None = None,
        user_name: str | None = None,
    ) -> None:
        """Start the walking belt."""
        if user_name:
            self.set_workout_user_by_name(user_name, explicit=True)
        else:
            self._try_auto_assign_from_context(context)

        await self._ensure_connected()
        await self._send(CMD_START)

    async def async_stop(self) -> None:
        """Stop the walking belt."""
        await self._ensure_connected()
        await self._send(CMD_STOP)

    async def async_pause(self) -> None:
        """Pause the walking belt."""
        await self._ensure_connected()
        await self._send(CMD_PAUSE)

    async def async_set_speed(self, speed_kmh: float) -> None:
        """Set belt speed in km/h (e.g. 3.5 → byte value 35)."""
        await self._ensure_connected()
        speed_byte = max(0, min(255, round(speed_kmh * 10)))
        incline_byte = self.data.incline & 0xFF
        await self._send(bytes([0x53, 0x02, speed_byte, incline_byte]))

    async def async_set_incline(self, incline: int) -> None:
        """Set belt incline level (0–max_incline), keeping current speed."""
        await self._ensure_connected()
        speed_byte = max(0, min(255, round(self.data.speed * 10)))
        incline_byte = max(0, min(self.data.max_incline, incline)) & 0xFF
        await self._send(bytes([0x53, 0x02, speed_byte, incline_byte]))

    async def async_set_light(self, on: bool) -> None:
        """Turn the LED light on or off. State is tracked optimistically."""
        await self._ensure_connected()
        value = 0x01 if on else 0x00
        await self._send(bytes([0x5C, 0x01, value, 0x00, 0x00, 0x00]))
        self.data.light_on = on

    async def _send(self, payload: bytes) -> None:
        if not self._client or not self._client.is_connected:
            _LOGGER.warning("Cannot send command – not connected to %s", self.mac)
            return
        frame = _build_frame(payload)
        _LOGGER.debug("TX → %s: %s", self.mac, frame.hex())
        await self._client.write_gatt_char(CHAR_SEND_UUID, frame, response=False)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_disconnect(self
