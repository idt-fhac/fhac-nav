from pathlib import Path

from django.core.management.base import BaseCommand

from c3nav.mapdata.exchange.measurements import export_measurements


class Command(BaseCommand):
    help = ('Export ranging beacons and beacon measurements (WiFi / iBeacon scans) to a JSON file. '
            'Spaces are referenced by slug, so the file survives a map re-import.')

    def add_arguments(self, parser):
        parser.add_argument('output', type=str, help='JSON file to write')

    def handle(self, *args, **options):
        data = export_measurements()
        Path(options['output']).write_text(data.model_dump_json(indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(
            'Exported %d ranging beacons and %d beacon measurements to %s'
            % (len(data.ranging_beacons), len(data.beacon_measurements), options['output'])
        ))
