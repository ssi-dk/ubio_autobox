"""SQLAlchemy persistence adapter."""

from .models import Base
from .repository import SqlAlchemyResultRepository

__all__ = ["Base", "SqlAlchemyResultRepository"]
