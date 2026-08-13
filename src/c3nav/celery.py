import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'c3nav.settings')
os.environ.setdefault('C3NAV_DATABASE_CONN_MAX_AGE', '0')

from django.conf import settings  # noqa

app = Celery('c3nav')
app.config_from_object('django.conf:settings')
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)
