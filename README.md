# Sportstech WalkingPad – Home Assistant Integration (Fork)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
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
   ```text
   /config/custom_components/sportstech_walkingpad/
