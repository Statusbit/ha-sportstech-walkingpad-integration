# Sportstech WalkingPad – Home Assistant Integration (Fork)

[![License](https://img.shields.io/github/license/Statusbit/ha-sportstech-walkingpad-integration)](LICENSE)

> **Unofficial community integration (Personal Fork).**  
> This project is a fork of [deniskie/ha-sportstech-walkingpad-integration](https://github.com/deniskie/ha-sportstech-walkingpad-integration).  
> Special thanks to **[deniskie](https://github.com/deniskie)** for reverse-engineering the FitHome/F37 BLE protocol and creating the original integration!  
> This project is not affiliated with, endorsed by, or connected to Sportstech Brands GmbH. "Sportstech" is a registered trademark of its respective owner.

Custom integration for **Sportstech WalkingPad** treadmills.  
Connects via Bluetooth Low Energy, reads live metrics, allows belt & incline control, and tracks **per-user workout statistics** natively in Home Assistant without external helpers.  
No cloud, no account, fully local.

> **Protocol:** Reverse-engineered from the Sportstech Live APK (v5.1.9) — `com.fithome.bluetooth.BLEDevice`

---

## What's New in This Fork

Compared to the upstream repository (`deniskie/ha-sportstech-walkingpad-integration`), this fork adds:

- **Multi-User Workout Assignment (`select.walkingpad_workout_user`):**
  - Automatically loads active Home Assistant users (plus a fallback `"Gast"` / Guest option).
  - Allows excluding system/utility accounts (e.g., wall tablets, MQTT users) during setup and via integration options.
  - Auto-assigns the user who triggered `sportstech_walkingpad.start` via Home Assistant context, or falls back to Guest when started manually on the treadmill.
  - Supports retroactive user reassignment right after a workout finishes.
- **Per-User Lifetime Statistics Sensors (without HA Helpers):**
  - Automatically creates persistent `total_increasing` sensors (`distance`, `workout_time`, `calories`, `steps`) for each allowed Home Assistant user (excluding Guest).
  - Fully compatible with Home Assistant's native long-term statistics and cards like `Statistics Graph Chart Card` (Day / Week / Month / Year).
- **Last Workout Sensor & Home Assistant Events:**
  - `sensor.walkingpad_last_workout` stores the distance and full session metadata (user, duration, calories, steps, timestamps) as attributes.
  - Fires `sportstech_walkingpad_workout_completed` and `sportstech_walkingpad_workout_reassigned` events on the HA event bus.
- **Extended Controls & Localization:**
  - Added `number` entities for speed and incline control, `button` entities for Start / Stop / Pause, diagnostic limit sensors (`max_speed`, `max_incline`), and German/English translations.

---

## Installation

### Option A – HACS (recommended)

1. Open **HACS** in Home Assistant.
2. Click **⋮ → Custom repositories**.
3. Add `https://github.com/Statusbit/ha-sportstech-walkingpad-integration` as **Integration**.
4. Search for **Sportstech WalkingPad** and install.
5. Restart Home Assistant.

### Option B – Manual

1. Download or clone this repository.
2. Copy the `custom_components/sportstech_walkingpad/` folder to your HA config directory:

    /config/custom_components/sportstech_walkingpad/

3. Restart Home Assistant.

### Setup & Options

After restart, go to **Settings → Devices & Services → Add Integration** and search for **Sportstech WalkingPad**.

- If your WalkingPad is powered on and nearby, it may be **auto-discovered** via Bluetooth.
- Otherwise, enter the **MAC address** manually (visible in your router's device list or a BLE scanner app).
- During setup (or later via the **Configure** gear icon), you can select Home Assistant user accounts to **exclude** from the workout user selector and per-user statistics.

---

## Entities

### Live Session Sensors

| Entity | Unit | Description |
|--------|------|-------------|
| `sensor.walkingpad_state` | — | Belt state: `idle`, `starting`, `running`, `paused`, `sleep`, `error` |
| `sensor.walkingpad_speed` | km/h | Current belt speed |
| `sensor.walkingpad_incline` | % | Current incline level |
| `sensor.walkingpad_heart_rate` | bpm | Heart rate (requires accessory; `unavailable` if no sensor) |
| `sensor.walkingpad_workout_time` | min | Elapsed time of current session |
| `sensor.walkingpad_distance` | m | Distance covered in current session |
| `sensor.walkingpad_calories` | kcal | Calories burned in current session |
| `sensor.walkingpad_steps` | — | Step count of current session |

Session metrics (time, distance, calories, steps) reset when the belt is stopped.

> **Note:** The device timer resets after ~99:59 min. The integration detects this and continues accumulating the correct elapsed time.

### Total & Last Workout Sensors

| Entity | Unit | Description |
|--------|------|-------------|
| `sensor.walkingpad_total_workout_time` | min | Overall lifetime accumulated workout time |
| `sensor.walkingpad_total_distance` | m | Overall lifetime accumulated distance |
| `sensor.walkingpad_total_calories` | kcal | Overall lifetime accumulated calories |
| `sensor.walkingpad_total_steps` | — | Overall lifetime accumulated step count |
| `sensor.walkingpad_last_workout` | m | Distance of the last completed workout (with user, duration, calories, steps & timestamps in attributes) |

### Per-User Lifetime Sensors

Created automatically for each enabled Home Assistant user (excluding `Gast`):

| Entity pattern | Unit | Description |
|----------------|------|-------------|
| `sensor.walkingpad_<user>_distance` | m | Lifetime accumulated distance for `<user>` (`total_increasing`) |
| `sensor.walkingpad_<user>_workout_time` | min | Lifetime accumulated workout time for `<user>` (`total_increasing`) |
| `sensor.walkingpad_<user>_calories` | kcal | Lifetime accumulated calories for `<user>` (`total_increasing`) |
| `sensor.walkingpad_<user>_steps` | — | Lifetime accumulated steps for `<user>` (`total_increasing`) |

All total and per-user sensors persist across Home Assistant restarts.

### Controls & Diagnostics

| Entity | Description |
|--------|-------------|
| `select.walkingpad_workout_user` | Select the active user for the current or last completed workout |
| `button.walkingpad_start` | Start the belt |
| `button.walkingpad_pause` | Pause the belt |
| `button.walkingpad_stop` | Stop the belt |
| `number.walkingpad_speed` | Set target belt speed (km/h) |
| `number.walkingpad_incline` | Set target belt incline (%) |
| `switch.walkingpad_light` | Turn the WalkingPad LED light on or off |
| `sensor.walkingpad_max_speed` | Diagnostic: maximum belt speed reported by device |
| `sensor.walkingpad_max_incline` | Diagnostic: maximum incline reported by device |

---

## Services & Events

### Services

| Service | Parameter | Description |
|---------|-----------|-------------|
| `sportstech_walkingpad.start` | `user` (optional, string) | Start the belt and optionally assign a user |
| `sportstech_walkingpad.stop` | — | Stop the belt |
| `sportstech_walkingpad.pause` | — | Pause the belt |
| `sportstech_walkingpad.set_speed` | `speed` (float, km/h) | Set belt speed, e.g. `3.5` |
| `sportstech_walkingpad.set_incline` | `incline` (int, %) | Set belt incline, e.g. `3` |
| `sportstech_walkingpad.assign_user` | `user` (required, string) | Assign the active or last completed workout to a user |

### Events

- `sportstech_walkingpad_workout_completed`: Fired when a workout ends (`STATE_IDLE`), containing `mac`, `device_name`, `user_id`, `user`, `duration_s`, `duration_min`, `distance_m`, `calories`, `steps`, `started_at`, and `ended_at`.
- `sportstech_walkingpad_workout_reassigned`: Fired when the last completed workout is reassigned to another user.

---

## Supported Devices

Any Sportstech WalkingPad that advertises the FitHome/F37 BLE service (`0000fff0-...`):

- Sportstech WalkingPad WP100
- Sportstech WalkingPad WP200
- Sportstech sTread Fold Pro
- Other FitHome-based OEM treadmills

> **Note:** This integration uses the proprietary FitHome BLE protocol and is **not** compatible
> with treadmills using the standard Bluetooth FTMS profile.

---

## Protocol

**BLE profile (FitHome/F37):**

| Role | UUID |
|------|------|
| Service | `0000fff0-0000-1000-8000-00805f9b34fb` |
| Notify (device → phone) | `0000fff1-0000-1000-8000-00805f9b34fb` |
| Write (phone → device) | `0000fff2-0000-1000-8000-00805f9b34fb` |

**Frame format:** `[0x02]` + payload + XOR(payload) + `[0x03]`

---

## Requirements

- Home Assistant **2024.1** or newer
- HA **Bluetooth** integration enabled (requires a compatible Bluetooth adapter or ESPHome proxy)
- `bleak-retry-connector` (declared in `manifest.json`, installed automatically by HA)

---

## Credits & License

- Original integration and protocol reverse-engineering by **[deniskie](https://github.com/deniskie/ha-sportstech-walkingpad-integration)**.
- Fork maintained by **[Statusbit](https://github.com/Statusbit/ha-sportstech-walkingpad-integration)**.
- Licensed under the **MIT License** – see [LICENSE](LICENSE).
