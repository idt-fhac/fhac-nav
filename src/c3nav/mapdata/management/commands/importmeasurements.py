from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from c3nav.mapdata.exchange.measurements import FORMAT_VERSION, MeasurementsFile, import_measurements
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.geometry.space import BeaconMeasurement, RangingBeacon


class Command(BaseCommand):
    help = ('Import ranging beacons and beacon measurements written by exportmeasurements. '
            'Records are matched to spaces by slug, else by the point on the level; '
            'a MapUpdate is queued so processupdates rebuilds the locator.')

    def add_arguments(self, parser):
        parser.add_argument('input', type=str, help='JSON file written by exportmeasurements')
        parser.add_argument('--clear', action='store_true',
                            help='delete all existing ranging beacons and beacon measurements first')
        parser.add_argument('--dry-run', action='store_true', help='resolve and count, then roll back')

    def handle(self, *args, **options):
        path = Path(options['input'])
        if not path.is_file():
            raise CommandError('%s is not a file' % path)
        data = MeasurementsFile.model_validate_json(path.read_text(encoding='utf-8'))
        if data.format != 'c3nav-measurements' or data.format_version > FORMAT_VERSION:
            raise CommandError('not a c3nav measurements file I can read: %s v%s'
                               % (data.format, data.format_version))

        with transaction.atomic():
            if options['clear']:
                n_m, _ = BeaconMeasurement.objects.all().delete()
                n_b, _ = RangingBeacon.objects.all().delete()
                self.stdout.write('Deleted %d beacon measurements and %d ranging beacons' % (n_m, n_b))
            counts = import_measurements(data, log=lambda msg: self.stdout.write(self.style.WARNING(msg)))
            self.stdout.write('Imported %(ranging_beacons)d ranging beacons and %(beacon_measurements)d beacon '
                              'measurements (%(by_point)d found by point, %(skipped)d skipped)' % counts)
            if options['dry_run']:
                self.stdout.write('Dry run, rolling back transaction...')
                transaction.set_rollback(True)
                return
            MapUpdate.objects.create(type='importmeasurements', geometries_changed=False)
        self.stdout.write(self.style.SUCCESS('Done. Run processupdates to rebuild the locator.'))
