# haos-zenmedia — Home Assistant Add-on Repository

Home Assistant add-ons for energy monitoring and cost calculation, focused on the
Austrian Wiener Netze Smart Meter ecosystem.

## Add-ons

### [WNSM Data Store](./haos-wnsm-store)

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

_Fetches Wiener Netze Smart Meter 15-minute consumption data and stores it locally so it
is available for variable-price energy cost calculations._

#### The problem it solves

The standard WNSM integration injects consumption data directly into Home Assistant's internal
statistics database. This makes data visible in the Energy Dashboard but **not accessible as
sensor states**, which means it cannot be used in templates, automations, or correlated with
hourly/quarter-hourly spot electricity prices from integrations such as Nordpool or aWATTar.

This add-on acts as a local data store:

- Fetches 15-minute consumption data from the WNSM API once daily.
- Persists every interval in a local SQLite database (`/data/wnsm.db`).
- Exposes a REST API on port **8099** so Home Assistant sensors and templates can query
  historical consumption data by timestamp.

A `rest` sensor pointing at `/consumption/current` creates a real `total_increasing` energy
entity compatible with the Energy Dashboard. The `/consumption/history` and `/consumption/day`
endpoints let templates multiply each 15-minute consumption value by the matching spot price —
enabling precise cost calculations.

#### Key features

- Auto-discovers all meter points on your account, or accepts an explicit list
- Configurable daily fetch time (default 04:00 — after WNSM publishes yesterday's data)
- Configurable history depth on first run (up to 3 years)
- Incremental updates — only fetches data newer than what is already stored
- Manual fetch trigger via `POST /fetch/trigger`
- Multi-architecture: `amd64` and `aarch64`

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
