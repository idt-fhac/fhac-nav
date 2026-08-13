import datetime
import decimal
import json
import os
import shutil
import tarfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models

from c3nav import __version__ as c3nav_version
from c3nav.mapdata.exchange.manifest import (FORMAT_VERSION, ExportManifest, GridInfo, ProjectionInfo,
                                             build_default_file_entries)
from c3nav.mapdata.models.source import Source
from c3nav.mapdata.utils.geometry import smart_mapping
from c3nav.mapdata.utils.json import format_geojson


def serialize_model_instance(obj, model_class):
    data = {}
    for field in model_class._meta.get_fields():
        if field.auto_created and not field.concrete and not isinstance(field, models.ManyToManyField):
            continue
        if isinstance(field, models.ForeignKey):
            data[field.name] = getattr(obj, field.attname)
        elif isinstance(field, models.ManyToManyField):
            data[field.name] = list(getattr(obj, field.name).values_list('pk', flat=True))
        elif field.__class__.__name__ == 'GeometryField':
            geom = getattr(obj, field.name)
            if geom:
                data[field.name] = format_geojson(smart_mapping(geom), rounded=False)
            else:
                data[field.name] = None
        elif field.__class__.__name__ == 'I18nField':
            data[field.name] = getattr(obj, field.attname)
        else:
            if hasattr(field, 'name'):
                val = getattr(obj, field.name)
                if isinstance(val, decimal.Decimal):
                    val = float(val)
                data[field.name] = val
    return data


class Command(BaseCommand):
    help = 'Export map data to a directory or tar.gz archive'

    def add_arguments(self, parser):
        parser.add_argument('output_dir', type=str, help='directory to write to')
        parser.add_argument('--sections', type=str, help='comma-separated section filter (e.g. geometry,graph)')
        parser.add_argument('--compress', action='store_true', help='create a .tar.gz of the output')

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'])
        if not options['compress']:
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            temp_dir = output_dir.with_name(output_dir.name + "_temp")
            temp_dir.mkdir(parents=True, exist_ok=True)
            export_dir = temp_dir

        if not options['compress']:
            export_dir = output_dir

        sections_filter = None
        if options.get('sections'):
            sections_filter = set(options['sections'].split(','))

        try:
            max_bounds = Source.max_bounds()
        except Exception:
            max_bounds = ((0.0, 0.0), (0.0, 0.0))

        projection_info = ProjectionInfo(
            pipeline=getattr(settings, 'PROJECTION_TRANSFORMER_STRING', None),
            proj4=getattr(settings, 'PROJECTION_PROJ4', None),
            zero_point=getattr(settings, 'PROJECTION_ZERO_POINT', None),
            rotation=getattr(settings, 'PROJECTION_ROTATION', None),
            rotation_matrix=getattr(settings, 'PROJECTION_ROTATION_MATRIX', None),
        )

        grid_info = None
        grid_rows_raw = getattr(settings, 'GRID_ROWS', None)
        grid_cols_raw = getattr(settings, 'GRID_COLS', None)
        if grid_rows_raw and grid_cols_raw:
            if isinstance(grid_rows_raw, str):
                grid_rows_raw = [float(x) for x in grid_rows_raw.split(',')]
            if isinstance(grid_cols_raw, str):
                grid_cols_raw = [float(x) for x in grid_cols_raw.split(',')]
            grid_info = GridInfo(rows=grid_rows_raw, cols=grid_cols_raw)

        manifest = ExportManifest(
            format_version=FORMAT_VERSION,
            c3nav_version=c3nav_version,
            exported_at=datetime.datetime.now(datetime.timezone.utc),
            projection=projection_info,
            bounds=max_bounds,
            grid=grid_info,
            initial_level=getattr(settings, 'INITIAL_LEVEL', None),
            initial_bounds=getattr(settings, 'INITIAL_BOUNDS', None),
            wifi_ssids=getattr(settings, 'WIFI_SSIDS', []),
            files=[]
        )

        file_entries = build_default_file_entries()

        for entry in file_entries:
            if sections_filter and entry.section.value not in sections_filter:
                continue

            model_class = apps.get_model(entry.model)
            objects = model_class.objects.all()

            # Special handling for level on_top_of to guarantee order if needed? The importer handles it.
            if model_class.__name__ == 'Level':
                # Order by on_top_of being None first
                objects = sorted(objects, key=lambda level: level.on_top_of_id is not None)

            records = []
            for obj in objects:
                records.append(serialize_model_instance(obj, model_class))

            entry.record_count = len(records)
            manifest.files.append(entry)

            file_path = export_dir / entry.filename
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2)

        with open(export_dir / 'manifest.json', 'w', encoding='utf-8') as f:
            f.write(manifest.model_dump_json(indent=2))

        if options['compress']:
            tar_path = str(output_dir)
            if not tar_path.endswith('.tar.gz'):
                tar_path += '.tar.gz'
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(export_dir, arcname=os.path.basename(tar_path).replace('.tar.gz', ''))

            shutil.rmtree(export_dir)

        self.stdout.write(self.style.SUCCESS('Successfully exported map data.'))
