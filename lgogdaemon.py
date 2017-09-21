#!/usr/bin/env python3

import os
import time
import logging
import re
import models
import config
from models import Game, Status, session
from subprocess import Popen, PIPE, STDOUT, TimeoutExpired

logging.basicConfig(level=logging.DEBUG)

def main():
    # Run in GOG library folder
    os.chdir(config.lgog_library)
    # Create all tables in the engine. This is equivalent to "Create Table"
    # statements in raw SQL.
    models.Base.metadata.create_all(models.engine)

    while True:
        session.expire_all()
        games = session.query(Game).all()
        logging.debug("Found %s games.", len(games))
        for game in games:
            logging.debug("%s : %s", game.name, game.state)
            if game.state == Status.queued or game.state == Status.running:
                download(session, game)
        time.sleep(5)

def download(session, game):
    logging.debug("Download request: %s", game.name)
    _count = 0  # Number of retries
    _all = 0  # Number of files to download
    _progress = 0  # Progress in %
    _waiting = 0  # Number of files waiting in queue
    _re_progress = re.compile(b"(\d+)%.*ETA")  # Extract progress for active file
    _re_remain = re.compile(b"Remaining:.*(\d+)")  # Extract number of files in queue
    game.state = Status.running
    session.commit()
    logging.debug("Game %s state changed to running", game.name)
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
            logging.debug("Starting download: %s", _opts)
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

                #logging.debug(_out)
                #logging.debug("PROGRESS: %s", _progress)
                game.progress = _progress
                session.commit()
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
            logging.error("Download of %s raised an error", game.name, exc_info=True)
        _count += 1
    if _count == 5:
        logging.error("Download of %s failed", game.name)
        game.state = Status.failed
    else:
        game.state = Status.done
        logging.info("Game %s downloaded sucessfully", game.name)
    session.commit()

def update():
    try:
        _opts = [
            'lgogdownloader',
            '--update-cache'
        ]
        logging.debug("Starting cache update: %s", _opts)
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
        logging.error("Cache update raised an error", exc_info=True)

def update_loop(scheduler, pause, function, functargs = ()):
    """
    Function make a schedule a periodic action and execute it

    :param sched: instance of scheduler
    :param pause: time beetween executing sched action
    :param function: action to execute
    :param functags: params to the action
    """
    scheduler.enter(pause, 1, update_loop, argument=(scheduler, pause, function, functargs))
    function()

if __name__ == "__main__":
    main()
