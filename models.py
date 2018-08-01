#!/usr/bin/env python3
"""
SQLite DB models for lgogwebui.
"""

import logging
import enum
import config

from sqlalchemy import Column, Integer, String, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy import create_engine

logging.basicConfig(level=logging.DEBUG)

Base = declarative_base()  # pylint: disable=invalid-name


class Status(enum.Enum):
    """
    Enumarete for game states.
    """
    new = 1
    queued = 2
    running = 3
    done = 4
    missing = 5
    failed = 6


class LoginStatus(enum.Enum):
    """
    Enumerate for login states.
    """
    logoff = 1
    running = 2
    running_2fa = 3
    recaptcha = 4
    logon = 5


class Game(Base):
    """
    Table to store current game state and settings.
    """
    __tablename__ = 'games'
    game_id = Column(Integer, primary_key=True)
    #: lgogdowloader game name
    name = Column(String(250), nullable=False)
    #: bitmask defining selected platforms
    platform = Column(Integer, nullable=False)
    #: bitmask defining downloaded platforms
    platform_ondisk = Column(Integer, default=0)
    #: download progress
    progress = Column(Integer, default=0)
    #: game state
    state = Column(Enum(Status), default=Status.new)
    #: number downloade of files
    done_count = Column(Integer, default=0)
    #: number of missing files
    missing_count = Column(Integer, default=0)
    #: number of files ready for updates
    update_count = Column(Integer, default=0)


class User(Base):
    """
    Table that stores status of GOG user Session.
    """
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    #: login state
    state = Column(Enum(LoginStatus), default=LoginStatus.logoff)


# Create an engine that stores data in a sqlte db file.
# Store the database in the lgogdownoader cache directory.
ENGINE = create_engine("sqlite:///%s/lgog-daemon.db" % config.lgog_cache)

Base.metadata.bind = ENGINE

# Create scoped session factory for use in separate threads
SESSION_FACTORY = sessionmaker(bind=ENGINE)
Session = scoped_session(SESSION_FACTORY)  # pylint: disable=invalid-name
