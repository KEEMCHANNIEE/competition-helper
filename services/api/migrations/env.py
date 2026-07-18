"""Alembic 환경 설정.

target_metadata 는 공유 계약(contest_helper_core.models.Base)에서, DB URL 은
설정(get_settings().app_db_url)에서 가져온다. 마이그레이션은 App DB 만 대상.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from contest_helper_core.config import get_settings
from contest_helper_core.models import Base
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 설정에서 실제 App DB URL 주입(alembic.ini 에는 비워 둠).
config.set_main_option("sqlalchemy.url", get_settings().app_db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
