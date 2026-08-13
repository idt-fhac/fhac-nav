# Building a map

How to get from an empty c3nav instance to a map that renders, searches and routes.

For installation see [manual.md](manual.md). This document assumes you have a running instance and a user
with the `editor_access`, `base_mapdata_access` and `direct_edit` permissions (set them in the control panel
under `/control/`, or on the `UserPermissions` object of your user).

Everything below is done in the editor at `/editor/`, unless a management command is given.

**The one rule that explains most confusion:** c3nav infers almost nothing. Walls, floor heights and routes
are all derived from objects you draw explicitly. A room does not connect to the corridor because they touch —
it connects because there is a door, and it is only routable because there are graph nodes and an edge.


## What a map is made of

| Object | What it is | Where in the editor |
| --- | --- | --- |
| `Level` | one floor | `/editor/levels/create` |
| `Source` | georeferenced floorplan image to trace against | `/editor/sources/` |
| `Building` | the outline of the building on a level | level → buildings |
| `Space` | walkable floor: room, corridor, stairwell, lift car | level → spaces |
| `Door` | thin polygon in a wall opening, connecting two spaces | level → doors |
| `Area` | named polygon inside a space | space → areas |
| `POI` | named point inside a space | space → POIs |
| `Stair` | line across the walking direction; splits floor heights | space → stairs |
| `Ramp` | polygon that interpolates between two heights | space → ramps |
| `AltitudeMarker` | pins a real height to one piece of floor | space → altitude markers |
| `GroundAltitude` | a reusable named height | `/editor/groundaltitudes/` |
| `Obstacle`, `LineObstacle`, `Column`, `Hole` | subtract from the walkable area | space → … |
| `GraphNode`, `GraphEdge` | the routing graph | level or space → graph |
| `WayType` | stairs / escalator / lift, with speed and avoidance | `/editor/waytypes/` |
| `LocationGroupCategory`, `LocationGroup` | icons, colors, categories, grouped search | `/editor/locationgroupcategories/`, `/editor/locationgroups/` |
| `LabelSettings` | at which zoom a label is shown, and how big | `/editor/labelsettings/` |
| `AccessRestriction` | hides objects from the public | `/editor/accessrestrictions/` |

Rendering works by subtraction: **walls are `building − spaces − doors`**. If a space touches the building
edge, there is no wall there. If two spaces are separated by a gap with no door in it, that gap renders as
wall and the spaces are not connected.


## Order of work

Each phase depends on the ones before it. Skipping ahead mostly works until it doesn't — in particular,
drawing the routing graph before the floors and doors are final means drawing it twice.

### 1. Levels

One `Level` per floor, created before anything else.

- `base_altitude` — the real height of the floor in metres. Must be unique per level, and should be
  realistic, because it is the fallback height for everything on that level.
- `level_index` — used in coordinates and URLs. Letters, digits, `_`, `.`, `-`.
- `short_label` — what the level switcher shows.
- `default_height` / `door_height` — room and door height, used by the 3D-ish render.

Do not create levels for staircases yet — see phase 4.

### 2. Sources

Upload the floorplan image per floor and give it `left` / `bottom` / `right` / `top` in metres. This is
what you trace everything against, so get the scale right once: measure a known distance (a door is
usually 0.8–1.0 m, a corridor 1.5–2.5 m) and set the bounds so the image matches reality. Every later
object inherits this error if you get it wrong.

Sources are only visible to users with the `sources_access` permission.

### 3. Building, spaces, doors

Per level, in this order:

1. **Building** — the outline. Interior courtyards should be holes in the polygon, not separate buildings.
2. **Spaces** — one per room, plus the corridors. Simple polygons, inset from the walls so the wall has
   somewhere to be rendered. Spaces on the same level must not overlap.
3. **Doors** — a thin polygon sitting in the wall gap, roughly door width × wall thickness, and
   **overlapping both adjacent spaces a little**. A door that merely abuts the two spaces depends on their
   coordinates coinciding exactly, and any sub-millimetre gap leaves the spaces unconnected; a small overlap
   costs nothing and is robust. A door that sits fully inside one space connects nothing at all.

Corridors are not optional. A floor of rooms with no corridor space between them cannot be connected by
doors at all, and no amount of later graph work will fix it.

### 4. Levels for staircases

A staircase between two floors does not belong to either floor. It gets **its own level**, stacked on the
lower one:

- create it from the lower level with *create level on top*
  (`/editor/levels/<id>/levels_on_top/create`), which sets `on_top_of`
- give it `base_altitude` about a metre above the lower floor
- name it after the transition, e.g. `level_index` `0-1`, short label `0-1`, title `EG → 1. OG`

Then draw the staircase itself as a `Space` on that intermediate level, and draw `Stair` lines across it —
one line per step or per short run of steps, perpendicular to the direction you walk. Stairs are what allow
the floor to change height: each line cuts the walkable area into pieces that can sit at different
altitudes.

Escalators work the same way. **Lifts do not** — see below.

### 5. Altitudes

Define a `GroundAltitude` for each real floor height, then place `AltitudeMarker`s:

- at least one on each floor
- at the bottom and the top of every staircase, on the pieces the stair lines cut apart

c3nav interpolates the altitude of everything in between, and a `Ramp` interpolates smoothly between the
two altitudes at its ends. `processupdates` logs an error for any marker that ended up outside an
accessible area — that log is the only feedback you get, so read it.

### 6. Vocabulary: way types, groups, labels

Create these before drawing content, so you can tag objects as you draw them instead of revisiting
hundreds of them later.

**Way types** for everything that isn't level walking. Each carries `speed`, `speed_up`,
`extra_seconds`, an icon, and `avoid_by_default` — that last flag is what a barrier-free routing option
actually switches on. A typical set: `stairs`, `escalator`, `elevator`, `freight elevator`.

**Location group categories**, then groups within them. Categories decide what a group can be attached to
(`allow_levels`, `allow_spaces`, `allow_areas`, `allow_pois`) and whether an object may have only one group
from that category (`single`). A workable set, as used by the 39c3 deployment:

| Category | `single` | Applies to | Purpose |
| --- | --- | --- | --- |
| Location Group | no | everything | free tagging: lecture halls, bars, projects |
| Space Type | yes | spaces | what a room *is*: elevator, freight elevator |
| Area Type | yes | areas | what an area *is* |
| Point Group | no | POIs | gates, cameras, help desks |
| WC Group | no | spaces | the toilet taxonomy |
| Color group | no | spaces, areas | appearance only, no search meaning |

Groups carry `icon`, `color`, `label_settings`, `can_search` and `can_describe`, and everything tagged with
the group inherits them. This is the intended way to style a map — set it once on the group, not on 400
objects.

**Label settings** are a zoom range plus a font size. Without them every label is drawn at every zoom and
the map becomes unreadable when there are more than a few dozen. Make a handful of tiers, from
"few things, large, visible when zoomed out" to "many things, small, only when zoomed right in", and attach
them to location groups.

### 7. Lifts

A lift is *not* an intermediate level. Draw a small `Space` for the car on **every** level it serves, tag
each with a single-choice space type group (e.g. *Elevator*), and connect them with graph edges in the next
phase using the `elevator` way type. The same applies to anything else that moves people vertically without
a walkable slope.

### 8. The routing graph

Nothing routes until this exists — not searching, not "route from A to B". The graph is drawn by hand.

- **Inside a space**: `/editor/spaces/<id>/graph/` lets you click to place `GraphNode`s. Place them along
  the line people actually walk, and connect consecutive ones. A corridor needs a chain of nodes; a small
  room needs one.
- **Through doors**: the door's edit page offers every pair of nodes on either side of it as a single list,
  which is much faster than connecting them one by one.
- **Between levels**: open the level graph at `/editor/levels/<id>/graph/`, select a node, switch to the
  other level, and click the node there. Set the way type on the edge before connecting — `stairs` for the
  staircase runs (floor → intermediate level → floor), `elevator` between the lift cars.

Edges are directed. The editor creates them both ways unless you tick *create one way edges*, which is what
you want for escalators.

Order that works well: corridors first, then the vertical connections, then the rooms. That gets you a
routable building early, and every room you add afterwards is one node and one edge.

### 9. Searchable content

Rooms are geometry; what people actually search for is names. Add:

- an `Area` for anything with a name that lives inside a room — a lecture hall, a lab, a library section
- a `POI` for anything that is really a point — an entrance, a help desk, a printer, a coffee machine

Both are searchable locations with their own title, icon, groups and label settings. On a mature map these
outnumber the spaces several times over. Turn `can_search` off for spaces that are only structural
(corridors, service rooms), so search results stay meaningful.

### 10. Polish

- `LeaveDescription` and `CrossDescription` give turn-by-turn instructions real wording
  ("leave the room and turn left"). The quest system collects these, plus internal room numbers, in small
  crowdsourceable steps: open quests are listed by `GET /api/v2/map/quests/` and each one links to a single
  form at `/editor/quests/<quest_type>/<identifier>/`. A user only sees the quest types listed in their
  `UserPermissions.quests`.
- `Obstacle`, `LineObstacle`, `Column` and `Hole` keep routes away from furniture, pillars and voids.
- `grid_rows` / `grid_cols` in `c3nav.cfg` add a coordinate grid, after which every location gets a square
  reference like `E1-L4` in its subtitle.
- `AccessRestriction` hides staff-only areas from the public map.


## Making changes take effect

Editor changes go into a **changeset** which has to be applied, unless you have the `direct_edit`
permission and have enabled direct editing — then they are written immediately.

Either way, geometry changes do not reach the rendered map until the map is processed:

```
python3 manage.py processupdates
```

This recalculates altitude areas, level render data, the router and the locator. If you have no external
cache configured (the default for a small deployment) you also have to restart the instance afterwards —
the command reminds you.


## Checking your work

```
python3 manage.py shell -c "
from c3nav.mapdata.models import Level, Building, Space, Door, Source
from c3nav.mapdata.models.geometry.space import Area, POI, Stair, Ramp, AltitudeMarker
from c3nav.mapdata.models.graph import GraphNode, GraphEdge, WayType
from c3nav.mapdata.models.locations import LocationGroup, LabelSettings
for m in (Level, Building, Space, Door, Area, POI, Stair, Ramp, AltitudeMarker,
          GraphNode, GraphEdge, WayType, LocationGroup, LabelSettings, Source):
    print(f'{m.__name__:18} {m.objects.count()}')
"
```

For a finished two-floor building, none of these should be `0`. A count of zero is not a small gap — it is
a feature that silently does not exist:

- no `Stair` / `AltitudeMarker` → the map is flat, staircases are just rooms
- no `WayType` → routes cannot distinguish stairs from corridors, and barrier-free routing cannot work
- no `GraphNode` / `GraphEdge` → nothing routes at all
- no `Area` / `POI` → nothing to search for except room numbers
- no `LabelSettings` → every label at every zoom

Then walk the map: switch levels, search for a room, and route between two rooms on different floors. Those
three interactions exercise nearly everything above.
