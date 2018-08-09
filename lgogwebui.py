#!/usr/bin/env python3
# pylint: disable=invalid-name,bad-continuation,too-many-statements,
# pylint: disable=too-many-branches,too-many-locals
"""
Simple web interfaceDocker for
[lgogdownloader](https://github.com/Sude-/lgogdownloader), an gog.com download
manager for Linux.
"""

import sys
import json
import os
from threading import Timer
from concurrent.futures import ThreadPoolExecutor

from flask import render_template, jsonify, request, redirect, url_for
from flask_autoindex import AutoIndex
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import or_

import config
import main
import lgogdaemon
import models
from models import Game, User, LoginStatus, Status, Session

app = main.app
download_scheduler = ThreadPoolExecutor(max_workers=2)
update_scheduler = ThreadPoolExecutor(max_workers=2)
# Create instance of AutoIndex used to display contents of game download
# directory. Explicitely disable add_url_rules as it would define some default
# routes for "/"
index = AutoIndex(app, config.lgog_library, add_url_rules=False)

# Define logger handlers and start update timer
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    _session = Session()
    app.logger.info("Initialize lgogwebui ...")
    app.logger.info(sys.version)
    # Make sure that the database exists
    models.Base.metadata.create_all(models.ENGINE)
    # Make sure that login state exists in the DB
    try:
        _user = _session.query(User).one()
    except NoResultFound:
        _user = User()
        _session.add(_user)
        _session.commit()
    if _user.state != LoginStatus.logon:
        _user.state = LoginStatus.logoff
        _session.commit()
    # Start update loop
    Timer(5, lgogdaemon.update_loop,
          (config.update_period, lgogdaemon.update,
              (update_scheduler,))).start()
    # Add to the download queue games marked in the DB
    _games = _session.query(Game).all()
    for _game in _games:
        if _game.state == Status.queued or _game.state == Status.running:
            app.logger.info("Found %s game for download: %s",
                            _game.name, _game.state)
            download_scheduler.submit(lgogdaemon.download, _game.name)
    Session.remove()


@app.after_request
def session_cleaner(response):
    """Cleanup session ater each request."""
    Session.remove()
    return response


@app.route('/')
def library():
    """Display the main page."""
    _session = Session()
    # TODO store in some cache
    data = {
        'games': []
    }
    try:
        with open(os.path.join(
                  config.lgog_cache, 'gamedetails.json'),
                  encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        pass

    _user = _session.query(User).one()
    _user_data = {
            'state': _user.state.name,
            'selected': {}
            }
    _user_data['selected']['windows'] = (_user.platform & 1 == 1)
    _user_data['selected']['macos'] = (_user.platform & 2 == 2)
    _user_data['selected']['linux'] = (_user.platform & 4 == 4)
    _metadata = []
    for game_data in data['games']:
        _db_found = False
        _available = 0
        _selected = 0
        _meta = {
                'gamename': game_data['gamename'],
                'title': game_data['title'],
                'icon': game_data['icon']
                }

        if 'installers' not in game_data:
            continue
        for inst in game_data['installers']:
            _available |= inst['platform']

        try:
            db_game = _session.query(Game).filter(
                Game.name == game_data['gamename']).one()
            _db_found = True
            if db_game.platform_available != _available:
                db_game.platform_available = _available
                _session.add(db_game)
            # app.logger.debug("Game in DB: %s", db_game.name)
        except NoResultFound:
            _name = game_data['gamename']
            db_game = Game()
            db_game.name = _name
            db_game.state = Status.new
            db_game.platform_available = _available
            _game_dir = os.path.join(config.lgog_library, _name)
            if os.path.isdir(_game_dir):
                _platform_linux = False
                _platform_mac = False
                _platform_windows = False
                # Search for downloaded installers
                for _file in os.listdir(_game_dir):
                    if not os.path.isdir(os.path.join(_game_dir, _file)):
                        if _file.endswith('.sh'):
                            _platform_linux = True
                        elif _file.endswith('.exe'):
                            _platform_windows = True
                        elif _file.endswith('.pkg'):
                            _platform_mac = True
                        elif _file.endswith('.dmg'):
                            _platform_mac = True
                _platform = 0
                if _platform_windows:
                    _platform |= 1
                if _platform_mac:
                    _platform |= 2
                if _platform_linux:
                    _platform |= 4
                if _platform > 0:
                    db_game.platform_ondisk = _platform
                    db_game.state = Status.done
            _session.add(db_game)
        _session.commit()

        _meta['state'] = db_game.state.name
        _meta['progress'] = int(db_game.progress)
        _meta['done_count'] = int(db_game.done_count)
        _meta['missing_count'] = int(db_game.missing_count)
        _meta['update_count'] = int(db_game.update_count)
        _meta['user_selected'] = False
        if db_game.platform >= 0:
            _selected = db_game.platform
            _meta['user_selected'] = True
        else:
            _selected = (_available & _user.platform)
        if _meta['missing_count'] == 0 and _selected != (db_game.platform_ondisk & _selected):
            _meta['missing_count'] = 1
        _ondisk = db_game.platform_ondisk
        _meta['available'] = {}
        _meta['selected'] = {}
        _meta['ondisk'] = {}
        _meta['available']['windows'] = (_available & 1 == 1)
        _meta['available']['macos'] = (_available & 2 == 2)
        _meta['available']['linux'] = (_available & 4 == 4)
        _meta['selected']['windows'] = (_selected & 1 == 1)
        _meta['selected']['macos'] = (_selected & 2 == 2)
        _meta['selected']['linux'] = (_selected & 4 == 4)
        _meta['ondisk']['windows'] = (_ondisk & 1 == 1)
        _meta['ondisk']['macos'] = (_ondisk & 2 == 2)
        _meta['ondisk']['linux'] = (_ondisk & 4 == 4)
        # app.logger.debug("%s\n%s\n%s", game_data["gamename"],
        #                  game_data["selected"], game_data["available"])
        _metadata.append(_meta)
        if _db_found and db_game.state == Status.done and \
                db_game.platform != (
                    db_game.platform_ondisk & db_game.platform
                ):
            db_game.state = Status.missing
            _session.add(db_game)
        _session.commit()

    # app.logger.debug(_metadata)
    return render_template('library.html', data=_metadata, user=_user_data)


@app.route('/platform/<game>/<platform>')
def toggle_platform(game, platform):
    """
    Toggle active state of platfrom for a game.
    :param game: - game name
    :param platform: - platform id (1 - windows, 2 - macos, 4 - linux)
    """
    app.logger.info("Requesting toggle of %s platform: %s.", game, platform)
    _session = Session()
    _user = _session.query(User).one()
    _result = {
            'missing': False
            }
    _platform_list = [1, 2, 4]
    _platform = int(platform)
    if _platform not in _platform_list:
        app.logger.error(
            "Unknown platform requested for %s: %s", game, platform)
        return "Unknown platform requested", 400
    app.logger.info(
        "Requesting change of platform for %s: %s.", game, platform)
    try:
        # Game in db - toggle platfrom
        db_game = _session.query(Game).filter(Game.name == game).one()
    except NoResultFound:
        app.logger.error("Game %s not found in DB.", game)
        return "Unable to find game in the database.", 500
    # app.logger.debug("Game %s found in the DB.", game)
    if db_game.state == Status.running:
        return "Platform change during download is prohibited.", 400
    _selected = db_game.platform
    if _selected < 0:
        _selected = (db_game.platform_available & _user.platform)
    _state = _selected & _platform
    if _state == _platform:
        # Disable platform
        _mask = ~ _platform
        db_game.platform = _selected & _mask
    else:
        db_game.platform = _selected | _platform
    if db_game.platform != (db_game.platform_ondisk & db_game.platform):
        app.logger.debug("Game %s missing platforms.", game)
        if db_game.state != Status.queued or \
                db_game.state != Status.running:
            db_game.state = Status.missing
            _result['missing'] = True
    else:
        app.logger.debug("Game %s has all platforms.", game)
        if db_game.state == Status.missing:
            db_game.state = Status.done
    _session.commit()
    return jsonify(_result)


@app.route('/default_platform/<platform>')
def toggle_default_platform(platform):
    """
    Toggle active state of platfrom for a game.
    :param game: - game name
    :param platform: - platform id (1 - windows, 2 - macos, 4 - linux)
    """
    app.logger.info("Requesting toggle of default platform: %s.", platform)
    _session = Session()
    _user = _session.query(User).one()
    _result = {}
    _platform_list = [1, 2, 4]
    _platform = int(platform)
    if _platform not in _platform_list:
        app.logger.error(
            "Unknown platform requested: %s", platform)
        return "Unknown platform requested", 400
    app.logger.info(
        "Requesting change of platform: %s.", platform)
    app.logger.debug("Current: %s", _user.platform)
    _state = _user.platform & _platform
    if _state == _platform:
        # Disable platform
        _mask = ~ _platform
        _user.platform = _user.platform & _mask
    else:
        _user.platform = _user.platform | _platform
    # Game in db - toggle platfrom
    db_games = _session.query(Game).filter(
        Game.platform_available.op('&')(_platform) == _platform).all()
    for db_game in db_games:
        # app.logger.debug("Game %s found in the DB.", game)
        if db_game.state == Status.running:
            return "Platform change during download is prohibited.", 400
        _selected = db_game.platform
        if _selected < 0:
            if (_user.platform & db_game.platform_available) != \
                    (db_game.platform_ondisk & _user.platform & db_game.platform_available) \
                    and db_game.state != Status.queued and \
                    db_game.state != Status.running:
                _result[db_game.name] = {'missing': True}
            else:
                _result[db_game.name] = {'missing': False}
    _session.commit()
    return jsonify(_result)


@app.route('/download/<game>')
def download(game):
    """
    Request game download
    :param game: - game name
    """
    _session = Session()
    app.logger.info("Requesting download of: %s.", game)
    try:
        db_game = _session.query(Game).filter(Game.name == game).one()
        # app.logger.debug("Game %s found in the DB.", game)
    except NoResultFound:
        app.logger.error("Game %s not found in DB.", game)
        return "Unable to find the game in the database.", 500
    if db_game.state != Status.running:
        db_game.state = Status.queued
        db_game.progress = 0
        _session.commit()
    download_scheduler.submit(lgogdaemon.download, game)
    return "OK"


@app.route('/stop/<game>')
def stop(game):
    """
    Stop game download
    :param game: - game name
    """
    _session = Session()
    app.logger.info("Requesting stop of: %s.", game)
    try:
        db_game = _session.query(Game).filter(Game.name == game).one()
        # app.logger.debug("Game %s found in the DB.", game)
    except NoResultFound:
        return "Unable to find game in the database.", 500
    if db_game.state == Status.running or db_game.state == Status.queued:
        db_game.state = Status.stop
        _session.commit()
    return "OK"


@app.route('/status', methods=['GET'])
def status_all():
    """
    Get status of all active downloads.
    """
    # app.logger.debug("List of active game downloads")
    _session = Session()
    games = _session.query(Game).filter(
        or_(Game.state == Status.queued, Game.state == Status.running)).all()
    result = [game.name for game in games]
    return jsonify(result)


@app.route('/status', methods=['POST'])
def status_selected():
    """
    Get status of selected downloads.
    The list of games to check should be sent as POST data.
    """
    check_games = request.get_json()
    # app.logger.debug("Status of games requested: %s", check_games)
    _session = Session()
    games = _session.query(Game).filter(
        Game.name.in_(check_games)).all()
    result = {}
    # logging.debug("Found %s games.", len(games))
    for game in games:
        game_res = {
                'state': game.state.name,
                'progress': game.progress
                }
        # logging.debug("%s : %s", game.name, game.state)
        if game.state == Status.done:
            game_res['progress'] = 100
        elif game.state != Status.queued and game.state != Status.running:
            game_res['progress'] = 0
        result[game.name] = game_res
    return jsonify(result)


@app.route('/user_status', methods=['GET'])
def user_status():
    """
    Get status of user session
    """
    _session = Session()
    _user = _session.query(User).one()
    _last_update = _user.last_update
    if _last_update is not None:
        _last_update = int(_last_update.timestamp())
    else:
        _last_update = 0
    result = {
            'user_status': _user.state.name,
            'last_update': _last_update
            }
    return jsonify(result)


@app.route('/login', methods=['POST'])
def login():
    """
    Execute login to GOG.com
    """
    user = request.form['user']
    password = request.form['password']
    update_scheduler.submit(lgogdaemon.login, user, password)
    return redirect(url_for('library'))


@app.route('/login_2fa', methods=['POST'])
def login_2fa():
    """
    Set 2FA code for GOG.com
    """
    code = request.form['code']
    app.logger.debug("Security code recieved: %s", code)
    lgogdaemon.msgQueue.put(code)
    _session = Session()
    _user = _session.query(User).one()
    _user.state = LoginStatus.running
    _session.commit()
    return redirect(url_for('library'))


@app.route('/gog-repo/<path:path>')
def browse(path):
    """
    Load directory view for selected path.
    """
    return index.render_autoindex(path, endpoint='.browse')
