# Install c3nav manually

## Installation

This is just a simple temporary setup. There will be more information soon.

### Install dependencies

Install the needed dependencies.

#### Debian

```
apt-get install -y build-essential gettext gfortran libfreetype6-dev libgeos-dev \
    libjpeg-dev libmemcached-dev liblapack-dev libmysqlclient-dev libopenblas-dev \
    libpq-dev librsvg2-bin pkg-config python3 python3-dev python3-pip python3-venv
```

Feel free to add guides for other operating systems.

### Clone the repository

Create a folder for all your c3nav stuff and clone the c3nav repository.

```
mkdir c3nav
cd c3nav
git clone https://github.com/c3nav/c3nav.git
cd c3nav
```

### Create a virtual environment

This will create a virtual environment so the installed python packages are not installed globally on your system.

```
virtualenv -p python3 env
source env/bin/activate
```

Always run the latter command before executing anything from c3nav.


### Install python dependencies

```
cd src/
pip3 install -U pip wheel setuptools
pip3 install -r requirements.txt
```

*Skip to the next step if you just want a development setup or use the editor.*

Wanna use redis, mysql, postgres, memcached or deploy c3nav in a public place?

pip3 install -r requirements/mysql.txt -r requirements/postgres.txt \
             -r requirements/memcached.txt -r requirements/redis.txt gunicorn

### Add Configuration

You need this to configure your own database, memcached, and the message queue. You can skip this step for now for a development setup – everything will work out of the box.

Configuration is read from the first of these that exists: `/etc/c3nav/c3nav.cfg`, `~/.c3nav.cfg`, or a
`c3nav.cfg` in the directory you run `manage.py` from. Set `C3NAV_CONFIG` to point somewhere else. The
file is INI-style, with one section per topic:

```
[c3nav]
svg_renderer = rsvg-convert

[django]
debug = false
allowed_hosts = nav.example.com

[database]
backend = postgresql
```

Every option and its default is listed in
[src/c3nav/settings.py](../src/c3nav/settings.py); some can also be set as environment variables, which
take precedence and are named there next to the option.

Two settings decide how tiles get rendered:

* `image_renderer` is `svg` (default) or `opengl` (needs `requirements/opengl.txt`)
* `svg_renderer` is `rsvg-convert` (default, the binary from `librsvg2-bin`), `rsvg` (in-process, needs
  `requirements/rsvg-pygobject.txt`) or `inkscape` (the inkscape binary)

If tiles come back as a server error complaining about a missing file, this is usually why.

### Migrate the database

This will create the needed database tables (and a temporary database, if you did not configure a different one) or update the database layout if needed. You should always execute this command after pulling from upstream.

```
python3 manage.py migrate
```

### Create a user

You need an account to reach the editor and the control panel.

```
python3 manage.py createsuperuser
```

A superuser can do everything through the control panel at `/control/`, including granting permissions to
other accounts. Mapping needs at least `editor_access`, `base_mapdata_access` (for the routing graph) and
`sources_access` (to see the floorplan images you trace against); `direct_edit` lets you skip the
changeset review cycle, which is what you want on a single-person instance.

### Build the translations

You can skip this step if English is enough for you.

```
python3 manage.py compilemessages
```

### Build the map

See [mapping.md](mapping.md) for what a map is made of and in which order to build it.

### Run a development server

```
python3 manage.py runserver
```

You can now reach your c3nav instance at [localhost:8000/](http://localhost:8000/). The editor can be found at [localhost:8000/editor/](http://localhost:8000/editor/). **Never use this server for production purposes!**

The control panel is at [localhost:8000/control/](http://localhost:8000/control/) and an overview of the
API, including a documented schema, at [localhost:8000/api/](http://localhost:8000/api/).

### Apply your changes

The rendered map, the routing graph and the search index are all built ahead of time, so map changes only
become visible after:

```
python3 manage.py processupdates
```

Without an external cache configured — the default for a small instance — you also have to restart the
server afterwards. The command tells you when that is the case.

