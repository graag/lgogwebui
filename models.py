#!/usr/bin/env python3

import logging
import enum
import config

from sqlalchemy import Column, ForeignKey, Integer, String, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy import create_engine

logging.basicConfig(level=logging.DEBUG)

Base = declarative_base()

class Status(enum.Enum):
    new = 1
    queued = 2
    running = 3
    done = 4
    failed = 5

class Game(Base):
    __tablename__ = 'games'
    # Here we define columns for the table person
    # Notice that each column is also a normal Python instance attribute.
    id = Column(Integer, primary_key=True)
    name = Column(String(250), nullable=False)
    platform = Column(Integer, nullable=False)
    progress = Column(Integer)
    state = Column(Enum(Status))

# Create an engine that stores data in the local directory's
# sqlalchemy_example.db file.
engine = create_engine("sqlite:///%s/lgog-daemon.db" % config.lgog_cache)

# Bind the engine to the metadata of the Base class so that the
# declaratives can be accessed through a DBSession instance
Base.metadata.bind = engine

session_factory = sessionmaker(bind=engine)
session = session_factory()
