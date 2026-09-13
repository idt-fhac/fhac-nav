# Features beyond the map

Things c3nav can do once a map exists, that are easy to miss because they only appear when enabled for a
user. For building the map itself see [mapping.md](mapping.md); for positioning see
[positioning.md](positioning.md).


## Quests

Quests are small on-site tasks — "what is the room number here?", "stand on this spot and scan" — shown as
markers on the map so that people walking the building can complete them from their phone, without touching
the editor.

Quests are **not stored objects**. Each quest type is a rule over existing map data ("every space whose
`internal_room_number` is empty"), and a marker exists exactly as long as the rule matches. Submitting the
quest's form writes the answer in its own changeset and applies it immediately; the marker then disappears.
So there is nothing to create or clean up: to make quests appear, put the data into the state the rule
looks for, and to make them go away, fill the data in — by quest or in the editor.

| Quest type | Marker on | Appears while | Asks for |
| --- | --- | --- | --- |
| Internal Room Number | space | `internal_room_number` empty | the room number on the door |
| Space identifyability | space | `identifyable` unset | can a visitor recognise this room? |
| Leave Description / Cross Description | door to a non-identifyable room | no description yet | "walk through the red door" |
| Wifi/BLE Positioning | `BeaconMeasurement` | `fill_quest` set | scanning on the spot (app only) |
| Ranging Beacon Identifier | `RangingBeacon` | `ap_name` set, no `addresses` | nothing — collects BSSIDs automatically (app only) |
| Ranging Beacon Altitude | `RangingBeacon` | `altitude_quest` set | mounting height |
| Media Panel Scouting | space | `media_panel_done` false | a checkbox |

### Enabling

Superusers see every quest type. Everyone else sees the types ticked under **Control panel → Users →
user → Available quests** (`UserPermissions.quests`). The list of open quests is cached for 15 minutes per
user.

### Using

On the map, logged in, an extra control appears top right (a ribbon icon) when the user has any quest type.
It opens a panel with one checkbox per type; ticking one loads its markers for the current level, clustered
when zoomed out. Tapping a marker opens the quest form. Types marked *app only* above show "This quest is
only available in the android app" in a desktop browser, because they need Wi-Fi scanning.

The *impolite quests* flag on a user skips the thank-you page after each quest, which is faster when
walking a whole building.

### Adding a type

A quest type is a dataclass in `c3nav/mapdata/quests/`, registered with `@register_quest`: a queryset of
unfinished objects, a `point`, a description, and a `ChangeSetModelForm`. `positioning.py` is the shortest
example.


## Positions and dynamic locations

A **Position** (`/positions/`, reached via *Manage custom positions* on the account page) is a movable marker owned by a user: a name, a
two-letter label, a secret, and the coordinates it was last set to. It is for things that move — an info
trolley, a first-aid team, a colleague — and can be searched and routed to like any location.

- **Create** it at `/positions/create/`. The detail page lets you rename it, set a timeout (seconds after
  which the position counts as unknown; 0 = never), unset the location, reset the secret, or delete it.
- **Move** it: click anywhere on the map, use *Set position* in the popup (only shown to users who own a
  position), pick the position. The map shows your own positions in a separate control.
- **Share** it: its ID is `m:<secret>`; anyone with that ID can search for it, see it, and route to it.
  Resetting the secret revokes that.
- **Feed it from a device** through the API, authenticated with an API secret (*Manage API secrets* on the account page, `/api-secrets/`):

  ```
  PUT /api/v2/map/positions/m:<secret>/
  {"coordinates_id": "c:<level id>:<x>:<y>", "timeout": 300}
  ```

  `GET` on the same URL reads it; `GET /api/v2/map/positions/my/` lists all of yours. Combine with
  `POST /api/v2/positioning/locate/` and a device can report its own position periodically.

A **Dynamic Location** (editor → *Dynamic Locations*) is the public face of a position: a normal location
with title, slug and groups that appears in search, whose place on the map is whatever the position with
the configured `position_secret` currently is. Use it when the thing that moves should be findable by name
without handing out the secret.


## Data overlays

Data overlays (editor → *Data Overlays*) are extra layers users can switch on in the map's layer control:
polygons, lines or points with their own colours and labels, kept separate from the map geometry. Features
can be drawn in the editor or pulled periodically from a URL (`pull_url`, `pull_interval`), which makes
them the place for live or external data — occupancy, sensor readings, event schedules — rather than for
anything that belongs in the map itself.
