import json
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from shapely.geometry import shape

from c3nav.mapdata.exchange.manifest import FORMAT_VERSION, ExportManifest, build_default_file_entries
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.utils.cache.changes import changed_geometries


def update_id_remap(id_remap, model_class, old_id, new_id):
    for base in model_class.mro():
        if issubclass(base, models.Model) and hasattr(base, '_meta') and not base._meta.abstract:
            id_remap[base._meta.label][old_id] = new_id


def deserialize_and_create(model_class, data_dict, id_remap):
    m2m_data = {}
    init_data = {}

    for field in model_class._meta.get_fields():
        if field.auto_created and not field.concrete and not isinstance(field, models.ManyToManyField):
            continue

        if field.name not in data_dict:
            continue

        val = data_dict[field.name]

        if isinstance(field, models.ForeignKey):
            if val is not None:
                new_id = id_remap.get(field.related_model._meta.label, {}).get(val, val)
                init_data[field.attname] = new_id
            else:
                init_data[field.attname] = None
        elif isinstance(field, models.ManyToManyField):
            if val is not None:
                m2m_data[field.name] = [id_remap.get(field.related_model._meta.label, {}).get(v, v) for v in val]
        elif field.__class__.__name__ == 'GeometryField':
            if val is not None:
                init_data[field.name] = shape(val)
            else:
                init_data[field.name] = None
        elif field.__class__.__name__ == 'I18nField':
            init_data[field.attname] = val
        else:
            if field.name != 'id':
                init_data[field.name] = val

    obj = model_class(**init_data)
    return obj, m2m_data


class Command(BaseCommand):
    help = 'Import map data from a directory or tar.gz archive'

    def add_arguments(self, parser):
        parser.add_argument('input_dir', type=str, help='directory or .tar.gz to import from')
        parser.add_argument('--sections', type=str, help='comma-separated section filter')
        parser.add_argument('--dry-run', action='store_true', help='validate without writing')
        parser.add_argument('--clear', action='store_true', help='delete existing data before import (DANGEROUS)')
        parser.add_argument('--no-input', action='store_true', help='do not prompt for confirmation')

    def handle(self, *args, **options):
        input_path = Path(options['input_dir'])
        temp_dir = None

        if input_path.is_file() and input_path.name.endswith('.tar.gz'):
            temp_dir = tempfile.TemporaryDirectory()
            with tarfile.open(input_path, "r:gz") as tar:
                # filter='data' rejects members with absolute or ../ paths, which would otherwise
                # let a crafted bundle write anywhere. It is the default from python 3.14 on.
                tar.extractall(path=temp_dir.name, filter='data')

            # Find manifest.json, it might be in a subdirectory
            manifest_path = Path(temp_dir.name) / 'manifest.json'
            if not manifest_path.exists():
                for p in Path(temp_dir.name).rglob('manifest.json'):
                    manifest_path = p
                    break

            import_dir = manifest_path.parent
        else:
            import_dir = input_path
            manifest_path = import_dir / 'manifest.json'

        if not manifest_path.exists():
            raise CommandError(f"manifest.json not found in {import_dir}")

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)
            manifest = ExportManifest.model_validate(manifest_data)

        # Format version check
        if manifest.format_version.split('.')[0] != FORMAT_VERSION.split('.')[0]:
            raise CommandError(f"Incompatible format version: {manifest.format_version} (expected {FORMAT_VERSION})")

        sections_filter = None
        if options.get('sections'):
            sections_filter = set(options['sections'].split(','))

        if options['clear']:
            if not options['no_input']:
                confirm = input("This will DELETE existing map data. Are you sure? [y/N]: ")
                if confirm.lower() != 'y':
                    raise CommandError("Import cancelled.")

        try:
            with transaction.atomic():
                with MapUpdate.lock():
                    changed_geometries.reset()

                    if options['clear']:
                        # Delete in reverse dependency order
                        for entry in reversed(build_default_file_entries()):
                            if sections_filter and entry.section.value not in sections_filter:
                                continue
                            model_class = apps.get_model(entry.model)
                            model_class.objects.all().delete()
                        self.stdout.write("Existing data cleared.")

                    id_remap = defaultdict(dict)

                    for entry in manifest.files:
                        if sections_filter and entry.section.value not in sections_filter:
                            continue

                        file_path = import_dir / entry.filename
                        if not file_path.exists():
                            self.stdout.write(self.style.WARNING(f"File {entry.filename} missing, skipping."))
                            continue

                        model_class = apps.get_model(entry.model)
                        self.stdout.write(f"Importing {entry.model}...")

                        with open(file_path, 'r', encoding='utf-8') as f:
                            records = json.load(f)

                        # Handle level on_top_of logic if present
                        if model_class.__name__ == 'Level':
                            records = sorted(records, key=lambda r: r.get('on_top_of') is not None)

                        m2m_pending = []

                        for record in records:
                            old_id = record['id']
                            obj, m2m_data = deserialize_and_create(model_class, record, id_remap)
                            obj.save()
                            update_id_remap(id_remap, model_class, old_id, obj.id)

                            if m2m_data:
                                m2m_pending.append((obj, m2m_data))

                        for obj, m2m_data in m2m_pending:
                            for field_name, new_ids in m2m_data.items():
                                getattr(obj, field_name).set(new_ids)

                    if options['dry_run']:
                        self.stdout.write("Dry run, rolling back transaction...")
                        transaction.set_rollback(True)
                        return

                    MapUpdate.objects.create(type='importmap')
                    self.stdout.write(self.style.SUCCESS('Successfully imported map data.'))

        finally:
            if temp_dir:
                temp_dir.cleanup()
