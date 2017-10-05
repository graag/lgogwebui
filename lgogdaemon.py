#!/usr/bin/env python3

import os
import logging
import re
import config
from models import Game, Status, Session
from subprocess import Popen, PIPE
from threading import Timer

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)
# logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)


def download(game_name):
    _session = Session()
    game = _session.query(Game).filter(Game.name == game_name).one()
    # Run in GOG library folder
    os.chdir(config.lgog_library)
    logger.debug("Download request: %s", game.name)
    _count = 0  # Number of retries
    _all = 0  # Number of files to download
    _progress = 0  # Progress in %
    _waiting = 0  # Number of files waiting in queue
    # Extract progress for active file
    _re_progress = re.compile(b"(\d+)%.*ETA")
    # Extract number of files in queue
    _re_remain = re.compile(b"Remaining:.*(\d+)")
    game.state = Status.running
    _session.commit()
    logger.debug("Game %s state changed to running", game.name)
    while _count < 5:
        try:
            _opts = [
                'lgogdownloader',
                '--progress-interval', '1000',
                '--no-unicode',
                '--no-color',
                '--threads', '1',
                '--exclude', 'e,c',
                '--download',
                '--platform', str(game.platform),
                '--game',
                '^'+game.name+'$'
            ]
            logger.debug("Starting download: %s", _opts)
            _proc = Popen(_opts, stdout=PIPE, stderr=PIPE)
            while _proc.poll() is None:
                _out = _proc.stdout.readline()
                _m_progress = _re_progress.search(_out)
                _m_remain = _re_remain.search(_out)
                if _m_remain:
                    _waiting = int(_m_remain.groups()[0])
                    if _all == 0:
                        _all = _waiting + 1
                if _m_progress and _all != 0:
                    # For multiple files each gets equal part of progress bar
                    _part = 100.0/_all
                    # Calculate current file fraction of full progress bar
                    _current_part = _part * int(_m_progress.groups()[0]) / 100.0
                    # Calculate fraction of finished files and add current file progress
                    _progress = (_all - _waiting - 1) * _part + _current_part

                #logger.debug(_out)
                #logger.debug("PROGRESS: %s", _progress)
                game.progress = _progress
                _session.commit()
            # Check return code. If lgogdowloader was not killed by signal Popen will
            # not rise an exception
            if _proc.returncode != 0:
                raise OSError((
                    _proc.returncode,
                    "lgogdownloader returned non zero exit code.\n%s" %
                    str(_out)
                    ))
            break
        except:
            logger.error("Download of %s raised an error", game.name, exc_info=True)
        _count += 1
    if _count == 5:
        logger.error("Download of %s failed", game.name)
        game.state = Status.failed
    else:
        game.state = Status.done
        logger.info("Game %s downloaded sucessfully", game.name)
    _session.commit()
    Session.remove()


def update():
    try:
        _opts = [
            'lgogdownloader',
            '--update-cache'
        ]
        logger.debug("Starting cache update: %s", _opts)
        _proc = Popen(_opts, stdout=PIPE, stderr=PIPE)
        _out = _proc.communicate(timeout=config.command_timeout)
        # Check return code. If lgogdowloader was not killed by signal Popen will
        # not rise an exception
        if _proc.returncode != 0:
            raise OSError((
                _proc.returncode,
                "lgogdownloader returned non zero exit code.\n%s" %
                str(_out)
                ))
    except:
        logger.error("Cache update raised an error", exc_info=True)

def update_loop(pause, function, functargs = ()):
    """
    Function make a schedule a periodic action and execute it

    :param pause: time beetween executing sched action
    :param function: action to execute
    :param functags: params to the action
    """
    logger.debug("Schedule next event after: %s seconds", pause)
    Timer(pause, update_loop, (pause, function, functargs)).start()
    logger.debug("Execute update")
    function()
