#!/usr/bin/env python3

import json
import os
import logging
import sched
import time

from flask import Flask, render_template, redirect, url_for
from flask.ext.autoindex import AutoIndex
from sqlalchemy.orm.exc import NoResultFound

import config
from models import Game, Status, session
from lgogdaemon import update_loop, update

app = Flask(__name__)
index = AutoIndex(app, config.lgog_library, add_url_rules=False)

@app.before_first_request
def setup_logging():
    if not app.debug:
        # In production mode, add log handler to sys.stderr.
        app.logger.addHandler(logging.StreamHandler())
        app.logger.setLevel(logging.DEBUG)

@app.before_first_request
def setup_updater():
    scheduler = sched.scheduler(time.time, time.sleep)
    update_loop(scheduler, config.update_period, update, None)
    scheduler.run()

@app.route('/')
def library():
    session.expire_all()
    with open(os.path.join(config.lgog_cache, 'gamedetails.json'), encoding='utf-8') as f:
        data = json.load(f)
    if data is None:
        return "Unable to load the GOG games database."
    for game_data in data['games']:
        game = game_data['gamename']
        game_data['download'] = -1
        try:
            db_game = session.query(Game).filter(Game.name == game).one()
        except NoResultFound as e:
            db_game = Game()
            db_game.state = None
        if db_game.state == Status.queued:
            game_data['download'] = 0
            game_data['progress'] = int(db_game.progress)
        elif db_game.state == Status.running:
            game_data['download'] = 0
            game_data['progress'] = int(db_game.progress)
        elif db_game.state == Status.failed:
            game_data['download'] = -1
        elif os.path.isdir(os.path.join(config.lgog_library, game)):
            game_data['download'] = 1
        _available = 0
        _selected = 0
        if 'installers' not in game_data:
            game_data['hidden'] = True
            continue
        for inst in game_data['installers']:
            _available |= inst['platform']
        if db_game.state != None:
            _selected += db_game.platform
        else:
            _selected = _available
        game_data['available'] = {}
        game_data['selected'] = {}
        game_data['available']['windows'] = (_available & 1 == 1)
        game_data['available']['macos'] = (_available & 2 == 2)
        game_data['available']['linux'] = (_available & 4 == 4)
        game_data['selected']['windows'] = (_selected & 1 == 1)
        game_data['selected']['macos'] = (_selected & 2 == 2)
        game_data['selected']['linux'] = (_selected & 4 == 4)
    return render_template('library.html', data=data['games'])

@app.route('/platform/<game>/<platform>')
def toggle_platform(game, platform):
    _platform_list = [1,2,4]
    _all = 7
    _platform = int(platform)
    if _platform not in _platform_list:
        app.logger.error("Unknown platform requested for %s: %s", game, platform)
        return redirect(url_for('library'))
    app.logger.info("Requesting change of platform for %s: %s.", game, platform)
    try:
        # Game in db - toggle platfrom
        db_game = session.query(Game).filter(Game.name == game).one()
        app.logger.debug("Game %s found in the DB.", game)
        _state = db_game.platform & _platform
        if _state == _platform:
            # Disable platform
            _mask = ~ _platform
            db_game.platform = db_game.platform & _mask
        else:
            db_game.platform = db_game.platform | _platform
    except NoResultFound as e:
        # game not in DB - disable platform
        app.logger.debug("Adding game %s to the DB.", game)
        db_game = Game()
        db_game.name = game
        db_game.state = Status.new
        app.logger.debug("PLATFORM: %s", _platform)
        _mask = ~ _platform
        app.logger.debug("MASK: %s", _mask)
        db_game.platform = _all & _mask
        app.logger.debug("ALL: %s", _all)
        app.logger.debug("NEW: %s", db_game.platform)
        session.add(db_game)
    session.commit()
    return redirect(url_for('library')+"/#"+game)

@app.route('/download/<game>')
def download(game):
    app.logger.info("Requesting download of: %s.", game)
    try:
        db_game = session.query(Game).filter(Game.name == game).one()
        app.logger.debug("Game %s found in the DB.", game)
    except NoResultFound as e:
        with open(os.path.join(config.lgog_cache, 'gamedetails.json'), encoding='utf-8') as f:
            data = json.load(f)
        if data is None:
            return "Unable to load the GOG games database."
        _available = 0
        for game_data in data['games']:
            if game_data['gamename'] == game and 'installers' in game_data:
                for inst in game_data['installers']:
                    _available |= inst['platform']
        db_game = Game()
        db_game.name = game
        db_game.state = Status.new
        db_game.platform = _available
        session.add(db_game)
        app.logger.debug("Adding game %s to the DB.", game)
    if db_game.state != Status.running:
        db_game.state = Status.queued
        db_game.progress = 0
        session.commit()
    return redirect(url_for('library')+"/#"+game)

@app.route('/gog-repo/<path:path>')
def browse(path):
    return index.render_autoindex(path, endpoint='.browse')
