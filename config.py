#!/usr/bin/env python3

import os

#: Path to SQLite database
database_name = os.path.realpath(os.environ("LGOG_DBNAME", "lgog-daemon.db"))
