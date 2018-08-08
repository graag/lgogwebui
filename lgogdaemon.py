#!/usr/bin/env python3
"""
Module with implementation of the daemon part of lgogwebui.
"""

import os
import re
import json
from fcntl import fcntl, F_GETFL, F_SETFL
from subprocess import Popen, PIPE
from threading import Timer
from queue import Queue
from time import sleep
from sqlalchemy.orm.exc import NoResultFound

import config
from main import app
from models import Game, User, LoginStatus, Status, Session


msgQueue = Queue()


class LoginRequired(Exception):
    """
    Exception thrown when lgogdownloader requires login.
    """
    pass


class InteractivePopen(Popen):
    class BufferedStream:
        def __init__(self, stream):
            self.stream = stream
            self.buff = ""
            self.data = []

    def __init__(self, opts):
        super().__init__(opts, stdout=PIPE, stderr=PIPE, stdin=PIPE,
                         universal_newlines=True)
        # set the O_NONBLOCK flag of stdout and stderr file descriptors:
        _flags = fcntl(self.stdout, F_GETFL)  # get current p.stdout flags
        fcntl(self.stdout, F_SETFL, _flags | os.O_NONBLOCK)
        _flags = fcntl(self.stderr, F_GETFL)  # get current p.stderr flags
        fcntl(self.stderr, F_SETFL, _flags | os.O_NONBLOCK)

        self._out = self.BufferedStream(self.stdout)
        self._err = self.BufferedStream(self.stderr)

    def _scan(self, prompt, bstream):
        if bstream.data:
            return bstream.data.pop(0)
        bstream.buff += bstream.stream.read(1024)
        bstream.data = bstream.buff.split('\n')
        bstream.buff = bstream.data.pop()
        if re.search(prompt, bstream.buff):
            bstream.data.append(bstream.buff)
            bstream.buff = ''
        if bstream.data:
            return bstream.data.pop(0)
        return ''

    def monitor(self, wait=None):
        if wait is not None and self.empty():
            sleep(wait)
        # Split on ": " to capture lines with user input
        _out = self._scan(': $', self._out)
        _err = self._scan(': $', self._err)
        return _out, _err

    def empty(self):
        return not self._out.data and not self._err.data


def login(user, password):
    """
    Login into GOG.
    :param string user: - GOG user name
    :param string password: - GOG password
    """
    # All try block to get stack trace from worker thread
    try:
        _out = ""
        _err = ""
        _session = Session()
        _user = _session.query(User).one()
        _user.state = LoginStatus.running
        _session.commit()
        # Run in GOG library folder
        os.chdir(config.lgog_library)
        _opts = [
            'lgogdownloader',
            '--login',
            '--login-email',
            user,
            '--login-password',
            password
        ]
        app.logger.debug("Starting login ...")
        _result = 0
        _proc = InteractivePopen(_opts)
        while _proc.poll() is None or not _proc.empty():
            _out, _err = _proc.monitor(5)
            if not _out and not _err:
                continue
            # Handle login requests from lgogdownloader
            if 'Security code' in _err:
                _user.state = LoginStatus.running_2fa
                _session.commit()
                app.logger.debug("Wait for security code")
                _code = msgQueue.get()
                app.logger.debug("Enter the security code")
                _proc.stdin.write("%s\n" % _code)
                _proc.stdin.flush()
                _err = ""
            elif 'Login form contains reCAPTCHA' in _out:
                app.logger.error("Stop login as reCAPTCHA is required")
                _user.state = LoginStatus.recaptcha
                _session.commit()
                _proc.terminate()
                return
            elif 'HTTP: Login successful' in _err:
                _result += 1
            elif 'Galaxy: Login successful' in _err:
                _result += 1
            elif 'API: Login successful' in _err:
                _result += 1
        # Check return code. If lgogdowloader was not killed by signal
        # Popen will not rise an exception
        if _proc.returncode != 0:
            _err += _proc.stderr.read()
            raise OSError((
                _proc.returncode,
                "lgogdownloader returned non zero exit code."
                "\nOUT: %s\nERR: %s" %
                (_out, _err)
                ))
        if _result == 3:
            _user.state = LoginStatus.logon
            app.logger.info("Login successful")
        else:
            _user.state = LoginStatus.failed
            app.logger.warning("Login failed")
        _session.commit()
    except Exception:
        app.logger.error("Login raised an error", exc_info=True)
        _user.state = LoginStatus.failed
        _session.commit()
    finally:
        Session.remove()


def download(game_name):
    """
    Download a game form GOG.
    :param string game_name: - the name of a game to download
    """
    # All try block to get stack trace from worker thread
    try:
        _session = Session()
        _user = _session.query(User).one()
        if _user.state != LoginStatus.logon:
            app.logger.warning(
                "Cannot download game: %s. User not logged in to GOG.",
                game_name
            )
            return
        game = _session.query(Game).filter(Game.name == game_name).one()
        # Run in GOG library folder
        os.chdir(config.lgog_library)
        app.logger.debug("Download thread: %s", game.name)
        _platform = game.platform
        if _platform < 0:
            _platform = (game.platform_available & _user.platform)
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
        app.logger.debug("Game %s state changed to running", game.name)
        while _count < 5:
            try:
                _opts = [
                    'lgogdownloader',
                    '--directory', config.lgog_library,
                    '--progress-interval', '1000',
                    '--no-unicode',
                    '--no-color',
                    '--threads', '1',
                    '--exclude', 'e,c',
                    '--download',
                    '--platform', str(_platform),
                    '--game',
                    '^'+game.name+'$'
                ]
                app.logger.debug("Starting download: %s", _opts)
                _proc = Popen(_opts, stdout=PIPE, stderr=PIPE, stdin=PIPE,
                              universal_newlines=True)
                while _proc.poll() is None:
                    game = _session.query(Game).filter(Game.name == game_name).one()
                    if game.state == Status.stop:
                        app.logger.info("Game %s downloaded stopped", game.name)
                        _count = 100
                        _proc.terminate()
                        return
                    _out = _proc.stdout.readline()
                    _m_progress = _re_progress.search(_out)
                    _m_remain = _re_remain.search(_out)
                    if _m_remain is not None:
                        _waiting = int(_m_remain.groups()[0])
                        if _all == 0:
                            _all = _waiting + 1
                    if _m_progress is not None and _all != 0:
                        # For multiple files each gets equal part of progress
                        # bar
                        _part = 100.0/_all
                        # Calculate current file fraction of full progress bar
                        _current_part = \
                            _part * int(_m_progress.groups()[0]) / 100.0
                        # Calculate fraction of finished files and add current
                        # file progress
                        _progress = \
                            (_all - _waiting - 1) * _part + _current_part

                    # app.logger.debug(_out)
                    # app.logger.debug("PROGRESS: %s", _progress)
                    if _progress > 100:
                        app.logger.debug(
                            "Bad progress: %s for %s with %s parts.",
                            game.name, _progress, _all
                        )
                        app.logger.debug(_out)
                    game.progress = round(_progress, 1)
                    game.platform_ondisk = _platform
                    _session.commit()
                # Check return code. If lgogdowloader was not killed by signal
                # Popen will not rise an exception
                if _proc.returncode != 0:
                    _err = _proc.stderr.read()
                    if "Unable to read email and password" in _err:
                        app.logger.warning("Login required.")
                        _user.state = LoginStatus.logoff
                        game.state = Status.failed
                        _session.commit()
                        return
                    raise OSError((
                        _proc.returncode,
                        "lgogdownloader returned non zero exit code."
                        "\nOUT: %s\nERR: %s" %
                        (_out, _err)
                        ))
                break
            except Exception:
                app.logger.error(
                    "Execution of lgogdownloader for %s raised an error",
                    game.name, exc_info=True)
                _count += 1
        if _count == 5:
            app.logger.error("Download of %s failed", game.name)
            game.state = Status.failed
        elif _count > 5:
            app.logger.debug("Terminate raises exception")
            pass
        else:
            game.state = Status.done
            game.done_count = _all
            game.missing_count = 0
            app.logger.info("Game %s downloaded sucessfully", game.name)
        _session.commit()
    except Exception:
        app.logger.error("Download of %s raised an error", game.name,
                         exc_info=True)
    finally:
        Session.remove()


def status(game_name):
    """
    Check game status and store in the DB.
    :param string game_name: - the name of a game to download
    """
    # All try block to get stack trace from worker thread
    try:
        app.logger.debug("Check game status: %s", game_name)
        with open(os.path.join(config.lgog_cache, 'gamedetails.json'),
                  encoding='utf-8') as _file:
            data = json.load(_file)
        if data is None:
            app.logger.error("Game not found in lgogdownloader cache: %s",
                             game_name)
            return
        _available = 0
        for game_data in data['games']:
            if game_data['gamename'] == game_name and \
                    'installers' in game_data:
                for inst in game_data['installers']:
                    _available |= inst['platform']

        _session = Session()
        _user = _session.query(User).one()
        if _user.state != LoginStatus.logon:
            app.logger.warning(
                "Cannot check game status: %s. User not logged in to GOG.",
                game_name
            )
            return
        _res = [0, 0, 0]
        try:
            game = _session.query(Game).filter(Game.name == game_name).one()
            _selected = game.platform
            if _selected < 0:
                _selected = (game.platform_available & _user.platform)
            _res = status_query(game.name, _selected)
            app.logger.info(
                "Status check complete for %s. Selected platforms: %s.",
                game.name, _selected)
        except LoginRequired:
            _user.state = LoginStatus.logoff
            _session.commit()
            return
        except NoResultFound:
            app.logger.error("Game %s not found in the DB.", game_name)
            return
        if _res is None:
            app.logger.error(
                "No installers returned by GOG for game: %s, platforms: %s.",
                game.name, _selected)
            return
        # TODO add to platform_ondisk based on the directory scan (after db removal)
        game.done_count = _res[0]
        game.missing_count = _res[1]
        game.update_count = _res[2]
        _session.add(game)
        _session.commit()
    except Exception:
        app.logger.error("Unhandled exception in a worker thread!",
                         exc_info=True)
    finally:
        Session.remove()


def status_query(game_name, platform):
    """
    Execute status query for a game.
    :param string game_name: - the name of a game to download
    :param int platform: - selected platform bitmask
    """
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
        '--directory', config.lgog_library,
        '--no-unicode',
        '--no-color',
        '--exclude', 'e,c',
        '--status',
        '--platform', str(platform),
        '--game',
        '^'+game_name+'$'
    ]
    app.logger.debug("Query status: %s", _opts)
    _proc = Popen(_opts, stdout=PIPE, stderr=PIPE, universal_newlines=True)
    _full_out = ""
    while _proc.poll() is None:
        _out = _proc.stdout.readline()
        _full_out += _out
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
                app.logger.error("Unknown installer state %s for file: %s",
                                 _state, _m_status.groups()[1])
    # Check return code. If lgogdowloader was not killed by signal Popen
    # will not rise an exception
    if _proc.returncode != 0:
        _err = _proc.stderr.read()
        if "Unable to read email and password" in _err:
            app.logger.warning("Login required.")
            raise LoginRequired()
        raise OSError((
            _proc.returncode,
            "lgogdownloader returned non zero exit code."
            "\nOUT: %s\nERR: %s" %
            (_full_out, _err)
            ))
    if not _found:
        app.logger.error("No installers found")
        return None
    _result = (_done, _missing, _update)
    return _result


def update():
    """
    Execute lgogdownloader cache update.
    """
    # All try block to get stack trace from worker thread
    try:
        _session = Session()
        _user = _session.query(User).one()
        if _user.state != LoginStatus.logon:
            app.logger.warning(
                "Cannot update cache. User not logged in to GOG.")
            return
        _opts = [
            'lgogdownloader',
            '--update-cache'
        ]
        app.logger.info("Starting cache update: %s", _opts)
        _proc = Popen(_opts, stdout=PIPE, stderr=PIPE, universal_newlines=True)
        _out, _err = _proc.communicate(timeout=config.command_timeout)
        # Handle login requests from lgogdownloader
        if "Unable to read email and password" in _err:
            app.logger.error("Login required.")
            _user.state = LoginStatus.logoff
            _session.commit()
            _proc.terminate()
            return
        # Check return code. If lgogdowloader was not killed by signal Popen
        # will not rise an exception
        if _proc.returncode != 0:
            raise OSError((
                _proc.returncode,
                "lgogdownloader returned non zero exit code.\n%s\n%s" %
                (_out, _err)
                ))
    except Exception:
        app.logger.error("Cache update raised an error", exc_info=True)
    finally:
        Session.remove()


def update_loop(pause, function, functargs=()):
    """
    Function make a schedule a periodic action and execute it

    :param pause: time beetween executing sched action
    :param function: action to execute
    :param functags: params to the action
    """
    app.logger.info("Schedule next event after: %s seconds", pause)
    Timer(pause, update_loop, (pause, function, functargs)).start()
    # Execute the update function
    functargs[0].submit(function)
    # Execute status update for all downloaded games
    for _name in os.listdir(config.lgog_library):
        if os.path.isdir(os.path.join(config.lgog_library, _name)):
            functargs[0].submit(status, _name)
