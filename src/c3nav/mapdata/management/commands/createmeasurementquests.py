from django.core.management.base import BaseCommand
from django.db import transaction

from c3nav.mapdata.models import Space
from c3nav.mapdata.models.geometry.space import BeaconMeasurement
from c3nav.mapdata.utils.geometry import good_representative_point, unwrap_geom


class Command(BaseCommand):
    help = ('Create one empty beacon measurement with fill_quest=True per indoor space that has none yet, '
            'so every room shows up as a Wifi/BLE positioning quest to be filled on site.')

    def add_arguments(self, parser):
        parser.add_argument('--outside', action='store_true', help='include spaces marked as outside')
        parser.add_argument('--dry-run', action='store_true', help='count only, then roll back')

    def handle(self, *args, **options):
        spaces = Space.objects.select_related('level').order_by('pk')
        if not options['outside']:
            spaces = spaces.filter(outside=False)
        have = set(BeaconMeasurement.objects.values_list('space_id', flat=True))
        created = skipped = 0
        with transaction.atomic():
            for space in spaces:
                if space.pk in have or not space.geometry:
                    skipped += 1
                    continue
                geometry = unwrap_geom(space.geometry)
                point = good_representative_point(geometry)
                if not geometry.contains(point):
                    # a corridor's centroid can lie outside it; representative_point never does
                    point = geometry.representative_point()
                BeaconMeasurement.objects.create(space=space, geometry=point, fill_quest=True)
                created += 1
            if options['dry_run']:
                transaction.set_rollback(True)
        verb = 'would be created' if options['dry_run'] else 'created'
        self.stdout.write(self.style.SUCCESS(
            f'{created} quests {verb}, {skipped} spaces skipped (already measured or no geometry)'))
