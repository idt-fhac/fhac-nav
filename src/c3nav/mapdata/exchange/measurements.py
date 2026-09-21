"""
Exchange format for positioning data: ranging beacons (located access points) and beacon
measurements (WiFi / iBeacon scans taken at a known point).

This is deliberately separate from the map export (exportmap / importmap). The map is
regenerated from its sources and re-imported with new primary keys on every release, while the
scans are collected once by walking the building. So this file references spaces by slug, with
the level slug and the point as a fallback, and never by pk.
"""
import datetime
import decimal
from typing import Optional

from django.contrib.auth import get_user_model
from pydantic import BaseModel
from shapely.geometry import mapping, shape

from c3nav.mapdata.models import Level, Space
from c3nav.mapdata.models.geometry.space import BeaconMeasurement, RangingBeacon
from c3nav.mapdata.utils.geometry import unwrap_geom

FORMAT_VERSION = 1


class SpaceRef(BaseModel):
    """Where a point lives: the space by slug, and the level + point to find it again if the
    slug is gone."""
    slug: Optional[str] = None
    level: str
    geometry: dict


class RangingBeaconRecord(SpaceRef):
    import_tag: Optional[str] = None
    beacon_type: Optional[str] = None
    node_number: Optional[int] = None
    addresses: list[str] = []
    bluetooth_address: Optional[str] = None
    ibeacon_uuid: Optional[str] = None
    ibeacon_major: Optional[int] = None
    ibeacon_minor: Optional[int] = None
    uwb_address: Optional[str] = None
    altitude: float = 0
    ap_name: Optional[str] = None
    comment: Optional[str] = None
    altitude_quest: bool = True
    num_clients: int = 0
    max_observed_num_clients: int = 0


class BeaconMeasurementRecord(SpaceRef):
    import_tag: Optional[str] = None
    author: Optional[str] = None
    comment: Optional[str] = None
    data: dict = {}
    fill_quest: bool = False


class MeasurementsFile(BaseModel):
    format: str = "c3nav-measurements"
    format_version: int = FORMAT_VERSION
    exported_at: Optional[datetime.datetime] = None
    ranging_beacons: list[RangingBeaconRecord] = []
    beacon_measurements: list[BeaconMeasurementRecord] = []


RANGING_BEACON_FIELDS = tuple(f for f in RangingBeaconRecord.model_fields if f not in SpaceRef.model_fields)
BEACON_MEASUREMENT_FIELDS = tuple(f for f in BeaconMeasurementRecord.model_fields
                                  if f not in SpaceRef.model_fields and f != 'author')


def _plain(val):
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, BaseModel):
        return val.model_dump(mode='json')
    if isinstance(val, list):
        return [_plain(v) for v in val]
    if val is not None and not isinstance(val, (str, int, float, bool, dict)):
        return str(val)
    return val


def _space_ref(obj) -> dict:
    return {
        'slug': obj.space.slug,
        'level': obj.space.level.effective_slug,
        'geometry': mapping(unwrap_geom(obj.geometry)),
    }


def export_measurements() -> MeasurementsFile:
    result = MeasurementsFile(exported_at=datetime.datetime.now(datetime.timezone.utc))
    for beacon in RangingBeacon.objects.select_related('space', 'space__level').order_by('pk'):
        result.ranging_beacons.append(RangingBeaconRecord(
            **_space_ref(beacon),
            **{f: _plain(getattr(beacon, f)) for f in RANGING_BEACON_FIELDS},
        ))
    for m in BeaconMeasurement.objects.select_related('space', 'space__level', 'author').order_by('pk'):
        result.beacon_measurements.append(BeaconMeasurementRecord(
            **_space_ref(m),
            author=m.author.username if m.author else None,
            **{f: _plain(getattr(m, f)) for f in BEACON_MEASUREMENT_FIELDS},
        ))
    return result


class SpaceResolver:
    """Find the space a record belongs to: by slug, else the space on its level containing
    its point."""

    def __init__(self):
        self.by_slug = {s.slug: s for s in Space.objects.select_related('level') if s.slug}
        self.levels = {lv.effective_slug: lv for lv in Level.objects.all()}
        self._level_spaces = {}

    def resolve(self, ref: SpaceRef) -> tuple[Optional[Space], str]:
        space = self.by_slug.get(ref.slug) if ref.slug else None
        if space is not None:
            return space, 'slug'
        level = self.levels.get(ref.level)
        if level is None:
            return None, 'no level %r' % ref.level
        if level.pk not in self._level_spaces:
            self._level_spaces[level.pk] = [(s, unwrap_geom(s.geometry)) for s in level.spaces.all()]
        point = shape(ref.geometry)
        for space, geom in self._level_spaces[level.pk]:
            if geom.contains(point):
                return space, 'point'
        return None, 'no space on %s contains %s' % (ref.level, (round(point.x, 2), round(point.y, 2)))


def import_measurements(data: MeasurementsFile, log=lambda msg: None) -> dict:
    """Create the records; returns counts. Caller wraps in a transaction and rebuilds."""
    resolver = SpaceResolver()
    users = {u.username: u for u in get_user_model().objects.all()}
    counts = {'ranging_beacons': 0, 'beacon_measurements': 0, 'by_point': 0, 'skipped': 0}

    for rec in data.ranging_beacons:
        space, how = resolver.resolve(rec)
        if space is None:
            counts['skipped'] += 1
            log('skipping ranging beacon %s: %s' % (rec.ap_name or rec.addresses, how))
            continue
        counts['by_point'] += how == 'point'
        fields = rec.model_dump(exclude=set(SpaceRef.model_fields))
        RangingBeacon.objects.create(space=space, geometry=shape(rec.geometry), **fields)
        counts['ranging_beacons'] += 1

    for rec in data.beacon_measurements:
        space, how = resolver.resolve(rec)
        if space is None:
            counts['skipped'] += 1
            log('skipping measurement at %s: %s' % (rec.geometry.get('coordinates'), how))
            continue
        counts['by_point'] += how == 'point'
        fields = rec.model_dump(exclude=set(SpaceRef.model_fields) | {'author'})
        # save() folds the scan's BSSIDs into the beacons of the same AP name, so the
        # beacons go first (above) and this is not a bulk_create
        BeaconMeasurement.objects.create(space=space, geometry=shape(rec.geometry),
                                         author=users.get(rec.author), **fields)
        counts['beacon_measurements'] += 1
    return counts
