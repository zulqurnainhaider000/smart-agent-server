"""
app/extensions.py
-----------------
Initializes Flask extension singletons.
Isolating extensions here prevents circular imports between models, routes, and the application factory.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

db = SQLAlchemy()
cors = CORS()
