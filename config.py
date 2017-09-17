#!/usr/bin/env python3

import os

#: Path to lgogdownloader config
lgog_config = os.path.realpath(os.environ.get("LGOG_CONFIG", "~/.config/lgogdownloader"))
#: Path to lgogdownloader cache
lgog_cache = os.path.realpath(os.environ.get("LGOG_CACHE", "~/.cache/lgogdownloader"))
#: Path to GOG game library
lgog_library = os.path.realpath(os.environ.get("GOG_DIR", "~/GOG"))

