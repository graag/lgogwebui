#!/usr/bin/env python3
# pylint: disable=invalid-name,bad-continuation,too-many-statements,
# pylint: disable=too-many-branches,too-many-locals,broad-except
"""
Module with implementation of the daemon part of lgogwebui.
"""

import os
import logging
import re
import json
from subprocess import Popen, PIPE
from threading import Timer
from sqlalchemy.orm.exc import NoResultFound

import config
from models import Game, Status, Session

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)
# logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)


def download(game_name):
    # All try block to get stack trace from worker thread
    try:
        _session = Session()
        game = _session.query(Game).filter(Game.name == game_name).one()
        # Run in GOG library folder
        os.chdir(config.lgog_library)
        logger.debug("Download thread: %s", game.name)
        _count = 0  # Number of retries
        _all = 0  # Number of files to download
        _progress = 0  # Progress in %
        _waiting = 0  # Number of files waiting in queue
        # Extract progress for active file
        _re_progress = re.compile(r"(\d+)%.*ETA")
        # Extract number of files in queue
        _re_remain = re.compile(r"Remaining:.*(\d+)")
        game.state = Status.running
        _session.commit()
        logger.debug("Game %s state changed to running", game.name)
        while _count < 5:
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
            _proc = Popen(_opts, stdout=PIPE, stderr=PIPE,
                          universal_newlines=True)
            while _proc.poll() is None:
                _out = _proc.stdout.readline()
                _m_progress = _re_progress.search(_out)
                _m_remain = _re_remain.search(_out)
                if _m_remain is not None:
                    _waiting = int(_m_remain.groups()[0])
                    if _all == 0:
                        _all = _waiting + 1
                if _m_progress is not None and _all != 0:
                    # For multiple files each gets equal part of progress bar
                    _part = 100.0/_all
                    # Calculate current file fraction of full progress bar
                    _current_part = \
                        _part * int(_m_progress.groups()[0]) / 100.0
                    # Calculate fraction of finished files and add current
                    # file progress
                    _progress = (_all - _waiting - 1) * _part + _current_part

                # logger.debug(_out)
                # logger.debug("PROGRESS: %s", _progress)
                if _progress > 100:
                    logger.debug("Bad progress: %s for %s with %s parts.",
                                 game.name, _progress, _all)
                    logger.debug(_out)
                game.progress = round(_progress, 1)
                game.platform_ondisk = game.platform
                _session.commit()
            # Check return code. If lgogdowloader was not killed by signal
            # Popen will not rise an exception
            if _proc.returncode != 0:
                raise OSError((
                    _proc.returncode,
                    "lgogdownloader returned non zero exit code.\n%s" %
                    str(_out)
                    ))
            _count += 1
        if _count == 5:
            logger.error("Download of %s failed", game.name)
            game.state = Status.failed
        else:
            game.state = Status.done
            game.done_count = _all
            logger.info("Game %s downloaded sucessfully", game.name)
        _session.commit()
        Session.remove()
    except Exception:
        logger.error("Download of %s raised an error", game.name,
                     exc_info=True)


def status(game_name):
    # All try block to get stack trace from worker thread
    try:
        logger.debug("Check game status: %s", game_name)
        with open(os.path.join(config.lgog_cache, 'gamedetails.json'),
                  encoding='utf-8') as f:
            data = json.load(f)
        if data is None:
            logger.error("Game not found in lgogdownloader cache: %s",
                         game_name)
            return
        _available = 0
        for game_data in data['games']:
            if game_data['gamename'] == game_name and \
                    'installers' in game_data:
                for inst in game_data['installers']:
                    _available |= inst['platform']

        _session = Session()
        _res = [0, 0, 0]
        try:
            game = _session.query(Game).filter(Game.name == game_name).one()
            _res = status_query(game.name, game.platform)
        except NoResultFound:
            game = Game()
            game.name = game_name
            game.progress = 0
            _platform = 0
            for _p in (1, 2, 4):
                if _p & _available == 0:
                    continue
                _part_res = status_query(game.name, _p)
                if _part_res is None:
                    _res = None
                    break
                if _part_res[0] > 0:
                    _platform |= _p
                    _res[0] += _part_res[0]
                    _res[1] += _part_res[1]
                    _res[2] += _part_res[2]
            game.platform = _platform
            game.platform_ondisk = _platform
            game.state = Status.done
            if _res is not None and _res[1] > 0:
                game.state = Status.missing
            logger.debug("Platforms found on disk for %s: %s", game.name,
                         game.platform)
        if _res is None:
            logger.error(
                "No installers returned by GOG for game: %s, platforms: %s.",
                game.name, game.platform)
            Session.remove()
            return
        game.done_count = _res[0]
        game.missing_count = _res[1]
        game.update_count = _res[2]
        _session.add(game)
        _session.commit()
        Session.remove()
    except Exception:
        logger.error("Unhandled exception in a worker thread!", exc_info=True)


def status_query(game_name, platform):
    # All try block to get stack trace from worker thread
    try:
        # Run in GOG library folder
        os.chdir(config.lgog_library)
        _found = False  # At leas one installer file returned by GOG API
        _missing = 0  # Number of missing installer files
        _update = 0  # Number of installer files that require update
        _done = 0  # Number of downloaded installer files
        # Extract file state
        _re_status = re.compile(r"(\w\w\w?) %s (\S+)" % game_name)
        _opts = [
            'lgogdownloader',
            '--no-unicode',
            '--no-color',
            '--exclude', 'e,c',
            '--status',
            '--platform', str(platform),
            '--game',
            '^'+game_name+'$'
        ]
        logger.debug("Query status: %s", _opts)
        _proc = Popen(_opts, stdout=PIPE, stderr=PIPE, universal_newlines=True)
        while _proc.poll() is None:
            _out = _proc.stdout.readline()
            _m_status = _re_status.search(_out)
            if _m_status is not None:
                _found = True
                _state = _m_status.groups()[0]
                if _state == "ND" or _state == "FS":
                    _missing += 1
                elif _state == "MD5":
                    _update += 1
                elif _state == "OK":
                    _done += 1
                else:
                    logger.error("Unknown installer state %s for file: %s",
                                 _state, _m_status.groups()[1])
        # Check return code. If lgogdowloader was not killed by signal Popen
        # will not rise an exception
        if _proc.returncode != 0:
            raise OSError((
                _proc.returncode,
                "lgogdownloader returned non zero exit code.\n%s" %
                str(_out)
                ))
        if not _found:
            logger.error("No installers found")
            return None
        _result = (_done, _missing, _update)
        return _result
    except Exception:
        logger.error("Status query of %s raised an error",
                     game_name, exc_info=True)
        return None


def update():
    # All try block to get stack trace from worker thread
    try:
        _opts = [
            'lgogdownloader',
            '--update-cache'
        ]
        logger.info("Starting cache update: %s", _opts)
        _proc = Popen(_opts, stdout=PIPE, stderr=PIPE)
        _out = _proc.communicate(timeout=config.command_timeout)
        # Check return code. If lgogdowloader was not killed by signal Popen
        # will not rise an exception
        if _proc.returncode != 0:
            raise OSError((
                _proc.returncode,
                "lgogdownloader returned non zero exit code.\n%s" %
                str(_out)
                ))
    except Exception:
        logger.error("Cache update raised an error", exc_info=True)


def update_loop(pause, function, functargs=()):
    """
    Function make a schedule a periodic action and execute it

    :param pause: time beetween executing sched action
    :param function: action to execute
    :param functags: params to the action
    """
    logger.info("Schedule next event after: %s seconds", pause)
    Timer(pause, update_loop, (pause, function, functargs)).start()
    # Execute the update function
    function()
    # Execute status update for all downloaded games
    for _name in os.listdir(config.lgog_library):
        if os.path.isdir(os.path.join(config.lgog_library, _name)):
            functargs[0].submit(status, _name)
