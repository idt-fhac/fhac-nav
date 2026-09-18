import json
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, models, transaction
from shapely.geometry import shape

from c3nav.mapdata.exchange.manifest import FORMAT_VERSION, ExportManifest, build_default_file_entries
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.utils.cache.changes import changed_geometries


def update_id_remap(id_remap, model_class, old_id, new_id):
    for base in model_class.mro():
        if issubclass(base, models.Model) and hasattr(base, '_meta') and not base._meta.abstract:
            id_remap[base._meta.label][old_id] = new_id


def deserialize_and_create(model_class, data_dict, id_remap, command=None):
    m2m_data = {}
    init_data = {}

    # The model's own primary key must always be assigned by the database, never taken from
    # import data. For plain models that's just 'id', but c3nav's LocationSlug subclasses
    # (Space, Level, Area, POI, LocationGroup, ...) use multi-table inheritance, so their real
    # pk is the parent link field (e.g. 'locationslug_ptr'), which is a OneToOneField and would
    # otherwise be caught by the ForeignKey branch below and have its value copied straight into
    # init_data - i.e. the new row's own primary key set from export data. Checking against
    # _meta.pk.name (and, belt-and-braces, membership in _meta.parents.values()) catches that
    # field regardless of its name.
    # The inherited 'id' of the multi-table base (LocationSlug.id) is a concrete field of the
    # child too, and its value is the child's pk as well: a POI(id=4419) whose save() finds
    # LocationSlug 4419 already there (a Space's) UPDATEs that shared row and hangs the new
    # POI off it. So every pk name up the concrete inheritance chain is off limits.
    pk_field_names = {f.name for f in model_class._meta.parents.values()}
    for base in model_class.mro():
        if issubclass(base, models.Model) and hasattr(base, '_meta') and not base._meta.abstract:
            pk_field_names.add(base._meta.pk.name)

    for field in model_class._meta.get_fields():
        if field.auto_created and not field.concrete and not isinstance(field, models.ManyToManyField):
            continue

        if field.name not in data_dict:
            continue

        val = data_dict[field.name]

        if field.name in pk_field_names:
            # Don't trust the incoming primary key/parent link - but if it disagrees with the
            # record's declared 'id', the export is corrupt: importing it anyway would silently
            # save this record over whatever unrelated row that parent-link value belongs to
            # (Django's _save_table() sees an existing pk and UPDATEs instead of INSERTs). Warn
            # loudly instead of importing it quietly.
            incoming_id = data_dict.get('id')
            if val is not None and incoming_id is not None and val != incoming_id:
                message = (f"Record {model_class._meta.label} id={incoming_id} has a conflicting "
                           f"{field.name}={val} - this export is corrupt, discarding that value "
                           f"instead of letting it overwrite an unrelated existing row.")
                if command is not None:
                    command.stdout.write(command.style.WARNING(message))
                else:
                    print(f"WARNING: {message}")
            continue

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

    def clear_existing(self, sections_filter):
        entries = [entry for entry in reversed(build_default_file_entries())
                   if not sections_filter or entry.section.value in sections_filter]

        # Delete through the ORM first, in reverse dependency order, so on_delete handlers of
        # models outside the export (Report.location is SET_NULL, control.* CASCADE) run.
        for entry in entries:
            apps.get_model(entry.model).objects.all().delete()

        # The ORM only sees rows its joins can reach: the custom managers select_related()
        # non-null foreign keys and multi-table inheritance joins every parent table, so a row
        # whose parent is missing or shared with another child (what the pk-taking importmap
        # used to produce) survives .delete() and later collides with the imported ids. Sweep
        # the tables raw, m2m through tables before their model.
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            for entry in entries:
                model_class = apps.get_model(entry.model)
                for field in model_class._meta.local_many_to_many:
                    cursor.execute(f'DELETE FROM {quote(field.remote_field.through._meta.db_table)}')
                cursor.execute(f'DELETE FROM {quote(model_class._meta.db_table)}')

            # Concrete bases that are not exported themselves (LocationSlug): drop the rows no
            # child claims any more. Children outside the export (DynamicLocation) keep theirs.
            exported = {apps.get_model(entry.model) for entry in entries}
            bases = {parent for model_class in exported for parent in model_class._meta.get_parent_list()
                     if parent not in exported}
            for base in bases:
                claimed = ' UNION '.join(
                    f'SELECT {quote(child._meta.parents[base].column)} FROM {quote(child._meta.db_table)}'
                    for child in apps.get_models() if base in child._meta.parents
                )
                cursor.execute(f'DELETE FROM {quote(base._meta.db_table)} '
                               f'WHERE {quote(base._meta.pk.column)} NOT IN ({claimed})')

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
                        self.clear_existing(sections_filter)
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
                            obj, m2m_data = deserialize_and_create(model_class, record, id_remap, command=self)
                            obj.save()
                            update_id_remap(id_remap, model_class, old_id, obj.id)

                            if m2m_data:
                                m2m_pending.append((obj, m2m_data))

                        for obj, m2m_data in m2m_pending:
                            for field_name, new_ids in m2m_data.items():
                                getattr(obj, field_name).set(new_ids)

                    # A --clear delete doesn't necessarily remove every row sharing a multi-table-
                    # inheritance base table (e.g. LocationSlug subtypes not covered by
                    # build_default_file_entries()), which can leave that shared table's sequence
                    # behind the true max id left in it. Reset every mapdata model's sequence (covers
                    # base tables like LocationSlug too, which MTI children don't have one of their
                    # own for) so post-import object creation in the editor never collides with a
                    # stale sequence value.
                    all_mapdata_models = list(apps.get_app_config('mapdata').get_models())
                    with connection.cursor() as cursor:
                        for sql in connection.ops.sequence_reset_sql(no_style(), all_mapdata_models):
                            cursor.execute(sql)

                    if options['dry_run']:
                        self.stdout.write("Dry run, rolling back transaction...")
                        transaction.set_rollback(True)
                        return

                    MapUpdate.objects.create(type='importmap')
                    self.stdout.write(self.style.SUCCESS('Successfully imported map data.'))

        finally:
            if temp_dir:
                temp_dir.cleanup()
