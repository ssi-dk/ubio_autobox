from sqlalchemy import create_mock_engine

from ubio_autobox.persistence import Base


def test_models_compile_for_sql_server_dialect() -> None:
    engine = create_mock_engine(
        "mssql+pyodbc://",
        lambda *args, **kwargs: None,
    )
    Base.metadata.create_all(engine)
    assert len(Base.metadata.tables) == 13
