"""organization-level platform credentials and channel accounts

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12 01:00:00
"""
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY_OBJECT = sa.text("'{}'")


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.create_table(
        "platform_credentials",
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("client_id", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("live_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.UniqueConstraint("organization_id", "platform"),
    )
    with op.batch_alter_table("platform_credentials") as batch_op:
        batch_op.create_index(batch_op.f("ix_platform_credentials_organization_id"), ["organization_id"], unique=False)

    op.create_table(
        "channel_accounts",
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("external_account_id", sa.String(length=500), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", sa.JSON(), nullable=False, server_default=EMPTY_OBJECT),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.UniqueConstraint("organization_id", "platform", "external_account_id"),
    )
    with op.batch_alter_table("channel_accounts") as batch_op:
        batch_op.create_index(batch_op.f("ix_channel_accounts_organization_id"), ["organization_id"], unique=False)

    with op.batch_alter_table("channel_connections") as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_channel_connections_account_id"), ["account_id"], unique=False)
        batch_op.create_foreign_key("fk_channel_connections_account_id", "channel_accounts", ["account_id"], ["id"])

    _move_project_tokens_to_accounts()


def _move_project_tokens_to_accounts() -> None:
    """Connections authorized per project become organization accounts, so existing logins keep working everywhere."""
    bind = op.get_bind()
    meta = sa.MetaData()
    connections = sa.Table("channel_connections", meta, autoload_with=bind)
    projects = sa.Table("projects", meta, autoload_with=bind)
    accounts = sa.Table("channel_accounts", meta, autoload_with=bind)
    rows = bind.execute(
        sa.select(connections.c.id, connections.c.platform, connections.c.external_account_id, connections.c.config, projects.c.organization_id)
        .join(projects, projects.c.id == connections.c.project_id)
        .where(connections.c.enabled.is_(True), connections.c.platform != "local")
        .order_by(connections.c.id)
    ).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    by_key: dict[tuple[int, str, str], int] = {}
    for row in rows:
        config = row.config or {}
        if not config.get("access_token_encrypted"):
            continue
        key = (row.organization_id, row.platform, row.external_account_id)
        if key in by_key:
            # Later authorizations carry fresher tokens.
            bind.execute(accounts.update().where(accounts.c.id == by_key[key]).values(config=config, updated_at=now))
        else:
            by_key[key] = bind.execute(
                accounts.insert().values(
                    organization_id=row.organization_id,
                    platform=row.platform,
                    external_account_id=row.external_account_id,
                    display_name="",
                    enabled=True,
                    config=config,
                    created_at=now,
                    updated_at=now,
                )
            ).inserted_primary_key[0]
        bind.execute(connections.update().where(connections.c.id == row.id).values(account_id=by_key[key], config={}))


def downgrade() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    connections = sa.Table("channel_connections", meta, autoload_with=bind)
    accounts = sa.Table("channel_accounts", meta, autoload_with=bind)
    linked = bind.execute(
        sa.select(connections.c.id, accounts.c.config).join(accounts, accounts.c.id == connections.c.account_id)
    ).all()
    for row in linked:
        bind.execute(connections.update().where(connections.c.id == row.id).values(config=row.config or {}))
    with op.batch_alter_table("channel_connections") as batch_op:
        batch_op.drop_constraint("fk_channel_connections_account_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_channel_connections_account_id"))
        batch_op.drop_column("account_id")
    op.drop_table("channel_accounts")
    op.drop_table("platform_credentials")
