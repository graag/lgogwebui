#!/usr/bin/env python3
# pylint: disable=invalid-name,bad-continuation,too-many-statements,
# pylint: disable=too-many-branches,too-many-locals
"""
Simple web interfaceDocker for
[lgogdownloader](https://github.com/Sude-/lgogdownloader), an gog.com download
manager for Linux.
"""

import json
import os
import logging
from threading import Timer
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, jsonify, request
from flask_autoindex import AutoIndex
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import or_

import config
import lgogdaemon
import models
from models import Game, Status, Session

app = Flask(__name__)
scheduler = ThreadPoolExecutor(max_workers=1)
# Create instance of AutoIndex used to display contents of game download
# directory. Explicitely disable add_url_rules as it would define some default
# routes for "/"
index = AutoIndex(app, config.lgog_library, add_url_rules=False)

# Define logger handlers and start update timer
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    _session = Session()
    # In production mode, add log handler to sys.stderr.
    app.logger.addHandler(logging.StreamHandler())
    app.logger.setLevel(logging.DEBUG)
    app.logger.info("Initialize lgogwebui ...")
    # Make sure that the database exists
    models.Base.metadata.create_all(models.engine)
    # Start update loop
    Timer(5, lgogdaemon.update_loop,
          (config.update_period, lgogdaemon.update, (scheduler,))).start()
    # Add to the download queue games marked in the DB
    _games = _session.query(Game).all()
    for _game in _games:
        if _game.state == Status.queued or _game.state == Status.running:
            app.logger.info("Found %s game for download: %s",
                            _game.name, _game.state)
            scheduler.submit(lgogdaemon.download, _game.name)
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
    # app.logger.debug("ROOT requested")
    # TODO store in some cache
    with open(os.path.join(
              config.lgog_cache, 'gamedetails.json'), encoding='utf-8') as f:
        data = json.load(f)
    if data is None:
        return "Unable to load the GOG games database.", 500

    _metadata = []
    for game_data in data['games']:
        _db_found = False
        _meta = {
                'gamename': game_data['gamename'],
                'title': game_data['title'],
                'icon': game_data['icon']
                }
        try:
            db_game = _session.query(Game).filter(
                Game.name == game_data['gamename']).one()
            _db_found = True
            # app.logger.debug("Game in DB: %s", db_game.name)
        except NoResultFound:
            db_game = Game()
            db_game.state = Status.new
            db_game.progress = 0
            db_game.done_count = 0
            db_game.missing_count = 0
            db_game.update_count = 0
            db_game.platform_ondisk = 0

        _meta['state'] = db_game.state.name
        _meta['progress'] = int(db_game.progress)
        _meta['done_count'] = int(db_game.done_count)
        _meta['missing_count'] = int(db_game.missing_count)
        _meta['update_count'] = int(db_game.update_count)
        _available = 0
        _selected = 0
        if 'installers' not in game_data:
            continue
        for inst in game_data['installers']:
            _available |= inst['platform']
        if db_game.state is not Status.new:
            _selected += db_game.platform
        else:
            _selected = _available
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
    return render_template('library.html', data=_metadata)


@app.route('/platform/<game>/<platform>')
def toggle_platform(game, platform):
    app.logger.info("Requesting toggle of %s platform: %s.", game, platform)
    _session = Session()
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
        # app.logger.debug("Game %s found in the DB.", game)
        if db_game.state == Status.running:
            return "Platform change during download is prohibited.", 400
        _state = db_game.platform & _platform
        if _state == _platform:
            # Disable platform
            _mask = ~ _platform
            db_game.platform = db_game.platform & _mask
        else:
            db_game.platform = db_game.platform | _platform
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
    except NoResultFound:
        # game not in DB - disable platform
        with open(os.path.join(
                config.lgog_cache, 'gamedetails.json'), encoding='utf-8') as f:
            data = json.load(f)
        if data is None:
            return "Unable to load the GOG games database.", 500
        _available = 0
        for game_data in data['games']:
            if game_data['gamename'] == game and 'installers' in game_data:
                for inst in game_data['installers']:
                    _available |= inst['platform']
        # app.logger.debug("Adding game %s to the DB.", game)
        db_game = Game()
        db_game.name = game
        db_game.state = Status.new
        _mask = ~ _platform
        db_game.platform = _available & _mask
        _session.add(db_game)
        _result['missing'] = True
    _session.commit()
    return jsonify(_result)


@app.route('/download/<game>')
def download(game):
    _session = Session()
    app.logger.info("Requesting download of: %s.", game)
    try:
        db_game = _session.query(Game).filter(Game.name == game).one()
        # app.logger.debug("Game %s found in the DB.", game)
    except NoResultFound:
        with open(os.path.join(
                  config.lgog_cache, 'gamedetails.json'),
                  encoding='utf-8') as f:
            data = json.load(f)
        if data is None:
            return "Unable to load the GOG games database.", 500
        _available = 0
        for game_data in data['games']:
            if game_data['gamename'] == game and 'installers' in game_data:
                for inst in game_data['installers']:
                    _available |= inst['platform']
        if _available == 0:
            return "Game %s not found in your collection" % game, 500
        db_game = Game()
        db_game.name = game
        db_game.state = Status.new
        db_game.platform = _available
        _session.add(db_game)
        # app.logger.debug("Adding game %s to the DB.", game)
    if db_game.state != Status.running:
        db_game.state = Status.queued
        db_game.progress = 0
        _session.commit()
    scheduler.submit(lgogdaemon.download, game)
    return "OK"


@app.route('/status', methods=['GET'])
def status_all():
    # app.logger.debug("List of active game downloads")
    games = _session.query(Game).filter(
        or_(Game.state == Status.queued, Game.state == Status.running)).all()
    result = [game.name for game in games]
    return jsonify(result)


@app.route('/status', methods=['POST'])
def status_selected():
    check_games = request.get_json()
    # app.logger.debug("Status of games requested: %s", check_games)
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


@app.route('/gog-repo/<path:path>')
def browse(path):
    return index.render_autoindex(path, endpoint='.browse')
