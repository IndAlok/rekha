from rekha.db.session import sqlalchemy_url


def test_sqlalchemy_url_rewrites_railway_postgres():
    assert sqlalchemy_url("postgres://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert sqlalchemy_url("postgresql://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert sqlalchemy_url("postgresql+psycopg://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert sqlalchemy_url("sqlite+pysqlite:////tmp/x.db") == "sqlite+pysqlite:////tmp/x.db"
