#!/usr/bin/env python3

import argparse
import time
import logging
import models
from models import Game, Status, session
from subprocess import Popen, PIPE, STDOUT, TimeoutExpired

logging.basicConfig(level=logging.DEBUG)

def main():
    # Create all tables in the engine. This is equivalent to "Create Table"
    # statements in raw SQL.
    models.Base.metadata.create_all(models.engine)

    update_countdown = 720
    while True:
        if update_countdown == 0:
            update()
            update_countdown = 720
        games = session.query(Game).all()
        logging.debug("Found %s games.", len(games))
        for game in games:
            if game.state == Status.queued or game.state == Status.running:
                download(session, game)
        time.sleep(5)
        update_countdown -= 1

def download(session, game):
    count = 0
    game.state = Status.running
    session.commit()
    while count < 5:
        try:
            # TODO change to PIPE
            _opts = [
                'lgogdownloader',
                '--download',
                '--game',
                '^'+game.name+'$'
            ]
            logger.debug("Starting download: %s", _opts)
            _proc = Popen(_opts, stdout=PIPE, stderr=PIPE)
            _out = _proc.communicate()
            _output = _out[0]
            logger.debug(_out)
            # Check return code. If qsub was not killed by signal Popen will
            # not rise an exception
            if _proc.returncode != 0:
                raise OSError((
                    _proc.returncode,
                    "lgogdownloader returned non zero exit code.\n%s" %
                    str(_out)
                    ))
            break
        except:
            logging.error("Download of %s raised an error", game, exc_info=True)
        count += 1
    if count == 5:
        game.state = Status.failed
    else:
        game.state = Status.done
    session.commit()

def update():
    # TODO run --list
    # For games in gog-repo run --status and add to redis
    # Run orphan check and remove ??
    pass

if __name__ == "__main__":
    main()
