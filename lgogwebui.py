#!/usr/bin/env python3

import json
import os
import config
from models import Game, Status, session
from flask import Flask, render_template, redirect, url_for
app = Flask(__name__)

@app.route('/')
def library():
    with open(os.path.join(config.lgog_cache, 'gamedetails.json'), encoding='utf-8') as f:
        data = json.load(f)
    if data is None:
        return "Unable to load the GOG games database."
    for game in data['games']:
        game['download'] = -1
        state = session.query(Game.state).filter(Game.name == game['gamename']).one()
        if state == 'queue':
            game['download'] = 0
        elif state == 'running':
            game['download'] = 0
        elif os.path.isdir(os.path.join(config.lgog_library, game['gamename'])):
            game['download'] = 1
    return render_template('library.html', data=data['games'])

@app.route('/download/<game>')
def download(game):
    db_game = session.query(Game).filter(Game.name == game).one()
    if db_game.state != 'running':
        db_game.state = 'queue'
        session.commit()
    return redirect(url_for('library'))
