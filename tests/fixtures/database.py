"""Fresh PostgreSQL databases owned by one test; never reset the supplied database."""

from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


@contextmanager
def temporary_postgres_database(admin_url: str):
    url = make_url(admin_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("TEST_POSTGRES_URL must select PostgreSQL")
    # No caller-provided identifier is interpolated into CREATE/DROP DATABASE.
    name = "cti_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        created = True
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        try:
            if created:
                with admin.connect() as connection:
                    connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            admin.dispose()
