# Indoor positioning

How c3nav determines where a user is, and what you have to record to make it work.

This is the server-side reference. The Android app is required for recording (browsers cannot scan Wi-Fi);
its device setup, build configuration and JavaScript bridge are documented in the app repository
([c3nav-android](https://github.com/c3nav/c3nav-android), `FLOOR_MAPPING_HOWTO.md`). Everything about *what*
is recorded and *how the server uses it* lives here, so the two documents do not overlap.


## How it works

The app scans the Wi-Fi access points and BLE iBeacons around the phone and sends the result to
`POST /api/v2/positioning/locate/`. The server compares the scan against **reference measurements** —
scans that were recorded at known coordinates — and returns the most plausible position. No measurements,
no positioning; the quality of positioning is the quality of your measurements.

Objects involved (all under a `Space` in the editor):

| Object | What it is |
| --- | --- |
| `BeaconMeasurement` | a point on the map plus a list of scans recorded while standing on it |
| `RangingBeacon` | a known transmitter: Wi-Fi AP, iBeacon, or DECT antenna, with its identifiers and mounting height |
| `AutoBeaconMeasurement` | measurements the server collects itself from locate requests (not edited by hand) |

The locator (`c3nav.routing.locator`) is rebuilt by `processupdates`, so new measurements take effect only
after the map is processed, like geometry changes ([mapping.md](mapping.md#making-changes-take-effect)).


## Recording measurements

Requirements: the Android app, a logged-in user with editor access (creating measurements is refused for
anonymous users), and on the phone: location permission, Location Services on, Wi-Fi on, and — important —
**Wi-Fi scan throttling disabled** in the developer options, otherwise Android delivers at most four scans
per two minutes.

### In the editor

1. In the app open the editor, navigate to the level and space you are standing in.
2. *Beacon Measurements → create*, click the point on the map where you are standing.
3. The form shows a **scan collector** instead of the raw data field. Tap *Start*, stand still until a
   handful of scans have arrived (5–10 seconds without throttling), tap *Stop*, then save. The form cannot
   be saved before at least one scan is in.
4. Repeat every few metres in corridors and at least once per room. Apply the changeset.

The stored data is plain JSON, in case you want to generate it some other way:

```json
{"wifi":    [[{"bssid": "c3:42:13:37:ac:ab", "ssid": "eduroam", "rssi": -61, "frequency": 5180}, ...], ...],
 "ibeacon": [[{"uuid": "a142621a-...", "major": 1, "minor": 7, "distance": 2.3}, ...], ...]}
```

Each inner list is one scan; `frequency` is in MHz, `distance` in metres and optional.

### Via quests

If you would rather plan the measurement points from a desk and let someone walk them later:

1. Create the `BeaconMeasurement` points (editor or admin) with **"create a quest to fill this"** ticked and
   no data.
2. Enable the quest type *Wifi/BLE Positioning* for the walker (see [features.md](features.md#quests)).
3. In the app, the points appear as quest markers. Tapping one shows "start scanning"; the walker stands on
   the spot, waits for scans, submits. The measurement is filled and the marker disappears.

Different devices report different signal strengths. Mixing a few is fine, but the more consistent the
recording device, the better the result.


## Beacons

Positioning works on Wi-Fi access points you do not control — the scans simply contain whatever is on air.
`RangingBeacon` objects add knowledge about specific transmitters and are optional, but they improve
positioning and enable distance-based ranging.

| Field | Meaning |
| --- | --- |
| `beacon_type` | *Event WiFi AP* for access points, *DECT antenna*, or empty for a plain iBeacon |
| `addresses` | the BSSIDs the AP broadcasts (one per SSID/band) |
| `ap_name` | the AP's name in your Wi-Fi controller; used by the *Ranging Beacon Identifier* quest to collect the BSSIDs on site |
| `ibeacon_uuid`, `ibeacon_major`, `ibeacon_minor` | iBeacon identity |
| `altitude` | metres above the floor the device is mounted at; the *Ranging Beacon Altitude* quest asks for it if `altitude_quest` is set |
| `node_number`, `bluetooth_address`, `uwb_address` | for c3nav mesh nodes; leave empty otherwise |

### Existing Wi-Fi access points

Create a `RangingBeacon` per AP with `beacon_type = Event WiFi AP`. Either enter the BSSIDs yourself, or
enter only `ap_name` and let the *Ranging Beacon Identifier* quest fill them: someone stands next to the AP
with the app, and the quest submits itself once the BSSIDs have been seen.

`python3 manage.py findbeacons` and `bssid_from_scans_to_beacons` derive beacon entries from existing
measurements; `analyze_wifi_locate_precision` reports how well the current data locates.

### iBeacons

Any off-the-shelf BLE beacon whose iBeacon parameters can be configured works. The app only listens for
UUID **`a142621a-2f42-09b3-245b-e1ac6356e9b0`**, so set that, give every beacon a unique major/minor pair,
and create a `RangingBeacon` with those values at the mounting point. Scans then include `ibeacon` entries
with an estimated distance.

### c3nav mesh nodes

The `mesh` app (`/mesh/`, requires the `mesh_control` permission and `enable_mesh` in the config) manages
c3nav's own ESP32-based beacons: they connect over WebSocket, receive their configuration (node number,
iBeacon values, position) as mesh messages, and can be updated over the air. A `RangingBeacon` with the
matching `node_number` is linked automatically and takes its addresses from what the node reports.

The firmware and hardware for this are not part of this repository and are not currently published; treat
the mesh app as internal unless you have the devices.


## Checking your work

```
python3 manage.py shell -c "
from c3nav.mapdata.models import Space
from c3nav.mapdata.models.geometry.space import BeaconMeasurement, RangingBeacon
print('spaces', Space.objects.count())
ms = list(BeaconMeasurement.objects.all())
print('measurements', sum(1 for m in ms if m.data), 'unfilled', sum(1 for m in ms if not m.data))
print('spaces without measurement', Space.objects.filter(beacon_measurements__isnull=True).count())
print('beacons', RangingBeacon.objects.count())
"
```

Then run `processupdates`, open the app, tap the location button and walk: the marker should follow you
room by room.
