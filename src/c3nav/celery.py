import os

from celery import Celery
from celery.signals import task_prerun

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'c3nav.settings')
os.environ.setdefault('C3NAV_DATABASE_CONN_MAX_AGE', '0')

from django.conf import settings  # noqa

app = Celery('c3nav')
app.config_from_object('django.conf:settings')
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


@task_prerun.connect
def clear_per_request_cache(**kwargs):
    # per_request_cache is only cleared by the request middleware. Without this, a worker process keeps the
    # first map update cache key it read for its whole life, so e.g. ColorManager never picks up new group colors.
    from c3nav.mapdata.utils.cache.local import per_request_cache
    per_request_cache.clear()
