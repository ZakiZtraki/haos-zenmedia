# Home Assistant Add-on: WNSM Data Store

## Installation

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**.
2. Click the three-dot menu (top right) → **Repositories** and add the path to this local add-on
   store (or it will appear automatically if it is already in your local add-ons folder).
3. Find **WNSM Data Store** and click **Install**.

## Configuration

| Option | Default | Description |
| ------ | ------- | ----------- |
| `username` | _(required)_ | Your Wiener Netze online account e-mail address |
| `password` | _(required)_ | Your Wiener Netze online account password |
| `zaehlpunkte` | `[]` | List of meter-point IDs to monitor (e.g. `AT0030000000000000000000012345678`). Leave empty to fetch **all** meter points found on your account automatically. |
| `update_hour` | `4` | Hour of day (0–23) when the daily fetch runs. WNSM only publishes data once per day; a value between 3 and 6 is recommended to ensure yesterday's data is available. |
| `history_days` | `730` | Days of history to fetch on the **first** run (30–1 095). Large values may take a few minutes. |
| `api_port` | `8099` | TCP port the REST API listens on. Must also be mapped in the add-on network settings. |

### Minimal configuration example

```yaml
username: me@example.at
password: mysecretpassword
```

All other options use their defaults. On first start the add-on will discover your meter points
automatically and fetch 2 years of historical data.

### Explicit meter-point configuration

```yaml
username: me@example.at
password: mysecretpassword
zaehlpunkte:
  - AT0030000000000000000000012345678
update_hour: 4
history_days: 365
api_port: 8099
```

---

## REST API reference

The add-on exposes a local HTTP API. Replace `<ha-host>` with your Home Assistant host name or IP
address (e.g. `homeassistant.local`).

### `GET /health`

Health check. Returns add-on version and the result of the last fetch attempt.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "last_fetch": {
    "id": 3,
    "fetched_at": "2024-01-16 04:00:05",
    "status": "ok",
    "message": "Fetched 96 new records for 1 zaehlpunkt(e)",
    "records_added": 96
  }
}
```

### `GET /consumption/current`

Cumulative kWh sum across all stored intervals. Use this as the value of a
`state_class: total_increasing` Home Assistant energy sensor.

Query parameters (all optional):

| Parameter | Description |
| --------- | ----------- |
| `zaehlpunkt` | Filter by a specific meter-point ID |

```json
{
  "kwh": 12345.678900,
  "unit": "kWh",
  "zaehlpunkt": null,
  "updated_at": "2024-01-15T23:45:00+01:00"
}
```

### `GET /consumption/history`

Returns raw 15-minute records. All parameters are optional.

| Parameter | Format | Description |
| --------- | ------ | ----------- |
| `from` | ISO 8601 | Start of the time window (inclusive), e.g. `2024-01-15T00:00:00` |
| `to` | ISO 8601 | End of the time window (inclusive), e.g. `2024-01-15T23:45:00` |
| `zaehlpunkt` | string | Filter by meter-point ID |

```json
{
  "count": 96,
  "records": [
    {
      "zaehlpunkt": "AT0030000000000000000000012345678",
      "interval_start": "2024-01-15T00:00:00+01:00",
      "interval_end":   "2024-01-15T00:15:00+01:00",
      "kwh": 0.1234,
      "estimated": 0
    }
  ]
}
```

### `GET /consumption/day`

Convenience wrapper: all 15-minute records for a single date (up to 96 records per meter point).

| Parameter | Format | Description |
| --------- | ------ | ----------- |
| `date` | `YYYY-MM-DD` | **(required)** The date to query |
| `zaehlpunkt` | string | Filter by meter-point ID |

```bash
curl "http://homeassistant.local:8099/consumption/day?date=2024-01-15"
```

### `GET /consumption/latest`

Returns the single most recent 15-minute record stored.

### `GET /zaehlpunkte`

Lists all meter-point IDs that have stored data.

```json
{ "zaehlpunkte": ["AT0030000000000000000000012345678"] }
```

### `POST /fetch/trigger`

Manually triggers an immediate data fetch. Returns `409 Conflict` if a fetch is already running.

```bash
curl -X POST http://homeassistant.local:8099/fetch/trigger
```

### `GET /fetch/status`

Returns the result of the most recent fetch attempt.

---

## Integrating with Home Assistant

### Step 1 — Energy sensor (total_increasing)

Add the following to your `configuration.yaml`. This creates a real sensor entity that Home
Assistant's Energy Dashboard and any automation can use.

```yaml
sensor:
  - platform: rest
    name: WNSM Consumption Meter
    resource: http://homeassistant.local:8099/consumption/current
    value_template: "{{ value_json.kwh }}"
    unit_of_measurement: kWh
    device_class: energy
    state_class: total_increasing
    scan_interval: 3600   # poll once per hour — data only changes once a day
```

If you have multiple meter points, add one sensor per `zaehlpunkt`:

```yaml
sensor:
  - platform: rest
    name: WNSM Meter AT003…5678
    resource: "http://homeassistant.local:8099/consumption/current?zaehlpunkt=AT0030000000000000000000012345678"
    value_template: "{{ value_json.kwh }}"
    unit_of_measurement: kWh
    device_class: energy
    state_class: total_increasing
    scan_interval: 3600
```

After restarting Home Assistant, go to **Settings → Dashboards → Energy** and add the new sensor
as a grid consumption source. From this point on the Energy Dashboard can also apply an energy
price to calculate costs.

### Step 2 — Cost calculation with variable prices (Nordpool / aWATTar)

Because every 15-minute interval is queryable by timestamp, you can combine the stored consumption
data with a spot-price sensor using a Home Assistant template or automation.

**Example: daily cost for yesterday using a REST call in a template sensor**

```yaml
# configuration.yaml
sensor:
  - platform: template
    sensors:
      wnsm_cost_yesterday:
        friendly_name: "WNSM Cost Yesterday"
        unit_of_measurement: "EUR"
        value_template: >-
          {# This template is illustrative — use an automation or script
             to perform the HTTP call and store the result in an input_number. #}
          {{ states('input_number.wnsm_calculated_cost_yesterday') }}
```

**Recommended pattern — automation that runs after the daily fetch:**

```yaml
automation:
  - alias: "Calculate WNSM energy cost after daily fetch"
    trigger:
      - platform: time
        at: "04:30:00"   # after the add-on's scheduled fetch at 04:00
    action:
      - service: rest_command.calculate_wnsm_cost
```

The `rest_command` (or a Python script / AppDaemon app) would:

1. Query `GET /consumption/day?date=<yesterday>` to get the 96 quarter-hour consumption values.
2. For each record, look up the matching price from the `sensor.nordpool_energy_prices_raw`
   history (or your aWATTar sensor's stored state history).
3. Multiply `kwh × price_per_kwh` per slot and sum for the total daily cost.
4. Store the result in an `input_number` helper for display in a dashboard card.

---

## Data storage

The SQLite database is stored at `/data/wnsm.db` inside the add-on container, which maps to the
add-on's persistent data directory. It is **not** deleted when the add-on is restarted or updated.

The database contains two tables:

**`consumption`** — one row per 15-minute interval per meter point:

| Column | Type | Description |
| ------ | ---- | ----------- |
| `zaehlpunkt` | TEXT | Meter-point ID |
| `interval_start` | TEXT | ISO 8601 start of the 15-min slot |
| `interval_end` | TEXT | ISO 8601 end of the 15-min slot |
| `kwh` | REAL | Energy consumed in this slot (kWh) |
| `estimated` | INTEGER | `1` if the WNSM API marked this value as estimated |
| `imported_at` | TEXT | Timestamp when this record was inserted |

**`fetch_log`** — one row per fetch attempt, useful for diagnosing problems.

---

## Troubleshooting

**Add-on fails to start**
Check that `username` and `password` are set in the configuration. The add-on will log a fatal
error and exit if either is missing.

**No data after first start**
The initial history fetch can take a few minutes for large `history_days` values. Check the add-on
log for progress messages like `[AT003…] Initial fetch: 730 days of history`.

**`curl http://homeassistant.local:8099/health` times out**
Ensure port `8099` is mapped in the add-on's **Network** settings tab in the HA UI. The port
mapping must match the `api_port` option.

**REST sensor shows `unavailable`**
1. Confirm the add-on is running.
2. Confirm the port mapping.
3. Try the URL directly from a browser or `curl`.
4. If your HA instance is accessed via HTTPS but the add-on uses plain HTTP, make sure your
   browser/template is not redirecting. Use the local IP address of your host instead of
   `homeassistant.local` if needed.

**WNSM login fails**
The WNSM API uses OAuth2 PKCE. Verify your credentials by logging in to
<https://smartmeter-web.wienernetze.at/> manually. If the login works there but the add-on still
fails, check the log for the specific error message.
