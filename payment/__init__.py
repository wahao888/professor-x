# /professor-x/payment/__init__.py
from flask import Blueprint

payment_bp = Blueprint('payment', __name__)

from . import routes
