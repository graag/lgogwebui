lgogwebui
=========

Simple web interface for [lgogdownloader](https://github.com/Sude-/lgogdownloader), an gog.com download manager for Linux.

The recommended way to run the lgogwebui is to use a Docker image: [docker-lgogwebui](https://github.com/graag/docker-lgogwebui).

To run lgogwebui without docker follow instructions below:

Setup
-----

1. Install [lgogdownloader](https://github.com/Sude-/lgogdownloader)
2. Install lgogwebui and required python packages
```
git clone https://github.com/graag/lgogwebui.git
cd lgogwebui
pip3 install -r requirements.txt
```

Running
-------

Use builtin flask web server:
```
cd lgogwebui
export FLASK_APP=lgogwebui.py
python3 -m flask run
```

Use gunicorn webserver:
```
pip3 install json-logging-py gunicorn gevent
cd lgogwebui
gunicorn -b :8585 -t 2 -k gthread --reload lgogwebui:app
```

Settings
--------

Following environment variables govern lgogwebui behaviour:
- LGOG_CONFIG: Path to lgogdownloader config (default: "~/.config/lgogdownloader")
- LGOG_CACHE: Path to lgogdownloader cache (default: "~/.cache/lgogdownloader")
- LGOG_URL: Base url when running behind reverse proxy.
- GOG_DIR: Path to GOG game library (default: "~/GOG")

The lgogdownloader settings can be adjusted by modifing the ~/.config/lgogdownloader/config.cfg.
Currently the exclude pattern is hard coded at: extras,covers.

For example to enable additional languages change the language setting, e.g for polish:
```
language = pl,en
```

Issues
------

Too many login attempts can prompt a reCAPTCHA challenge, which the
lgogdownloader cannot handle. Wait for at least an 1 hour and try again. It is
also possible to export cookies from a bromwser and import them into
lgogdownloader.
