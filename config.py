#!/usr/bin/env python3

import os

#: Path to lgogdownloader config
lgog_config = os.path.expanduser(os.environ.get("LGOG_CONFIG", "~/.config/lgogdownloader"))
#: Path to lgogdownloader cache
lgog_cache = os.path.expanduser(os.environ.get("LGOG_CACHE", "~/.cache/lgogdownloader"))
#: Path to GOG game library
lgog_library = os.path.expanduser(os.environ.get("GOG_DIR", "~/GOG"))
#: Wait for 10 minutes until command is finished
command_timeout = 600
#: Time between updates
update_period = 86400
