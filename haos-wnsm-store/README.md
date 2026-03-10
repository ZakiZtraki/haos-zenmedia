# Home Assistant Add-on: WNSM Data Store

_Stores Wiener Netze Smart Meter 15-minute consumption data for variable-price energy cost calculations._

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

## Why this add-on exists

The official [WNSM custom integration][wnsm-integration] injects consumption data directly into Home
Assistant's internal statistics database. While this makes data visible in the Energy Dashboard, the
data is **not accessible as sensor states**, which means:

- You cannot use it in templates or automations.
- You cannot correlate it with hourly/quarter-hourly spot electricity prices (e.g. from a Nordpool
  or aWATTar integration).
- Precise cost calculations using variable tariffs are impossible.

This add-on solves the problem by acting as a **local data store**:

1. It fetches your 15-minute consumption data from the WNSM API once daily.
2. It persists every interval in a local SQLite database (`/data/wnsm.db`).
3. It exposes a lightweight REST API on port **8099** so Home Assistant sensors and templates can
   query the data by timestamp.

A `rest` sensor pointing at `/consumption/current` creates a real `total_increasing` energy entity
that the Energy Dashboard and any automation can use. The full history endpoint lets you build
templates that multiply each 15-minute consumption value by the matching spot price — enabling
cent-accurate cost calculations.

## Features

- Automatic discovery of all meter points on your account (or a fixed list if you prefer)
- Configurable daily fetch time (default 04:00 — after WNSM publishes yesterday's data)
- Configurable history depth on first run (up to 3 years / 1 095 days)
- Incremental updates: only fetches data newer than what is already stored
- Manual fetch trigger via REST (`POST /fetch/trigger`)
- Multi-architecture: `amd64` and `aarch64`

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[wnsm-integration]: https://github.com/mampfes/hacs_waste_collection_schedule
