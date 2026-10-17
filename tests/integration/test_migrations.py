from alembic import command
from alembic.config import Config
from sqlalchemy import inspect


def test_migration_round_trip_and_metadata_consistency(engine):
    config = Config("alembic.ini")
    assert {"assets", "jobs"} <= set(inspect(engine).get_table_names())
    command.check(config)
    command.downgrade(config, "base")
    assert "assets" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "jobs" in inspect(engine).get_table_names()
