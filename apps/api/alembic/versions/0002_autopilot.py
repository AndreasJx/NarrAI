"""languages, research dossiers, shots, autopilot and learning loop

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11 16:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY_OBJECT = sa.text("'{}'")
EMPTY_LIST = sa.text("'[]'")


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.create_table(
        "autopilot_settings",
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("script_threshold", sa.Integer(), nullable=False),
        sa.Column("cadence_hours", sa.Integer(), nullable=False),
        sa.Column("auto_publish", sa.Boolean(), nullable=False),
        sa.Column("live_publish", sa.Boolean(), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("niche", sa.String(length=500), nullable=False),
        sa.Column("audience", sa.String(length=500), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("video_budget_cents", sa.Integer(), nullable=False),
        sa.Column("banned_topics", sa.JSON(), nullable=False),
        sa.Column("press_kit_urls", sa.JSON(), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_table(
        "playbook_rules",
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
    )
    with op.batch_alter_table("playbook_rules") as batch_op:
        batch_op.create_index(batch_op.f("ix_playbook_rules_organization_id"), ["organization_id"], unique=False)

    op.create_table(
        "research_dossiers",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("angles", sa.JSON(), nullable=False),
        sa.Column("hooks", sa.JSON(), nullable=False),
        sa.Column("controversies", sa.JSON(), nullable=False),
        sa.Column("video_moments", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    with op.batch_alter_table("research_dossiers") as batch_op:
        batch_op.create_index(batch_op.f("ix_research_dossiers_project_id"), ["project_id"], unique=False)

    op.create_table(
        "stage_runs",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    with op.batch_alter_table("stage_runs") as batch_op:
        batch_op.create_index(batch_op.f("ix_stage_runs_project_id"), ["project_id"], unique=False)

    op.create_table(
        "topic_suggestions",
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("predicted_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        *_base(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    with op.batch_alter_table("topic_suggestions") as batch_op:
        batch_op.create_index(batch_op.f("ix_topic_suggestions_organization_id"), ["organization_id"], unique=False)

    op.create_table(
        "scene_shots",
        sa.Column("scene_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("effect", sa.String(length=30), nullable=False),
        sa.Column("clip_start", sa.Float(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"]),
    )
    with op.batch_alter_table("scene_shots") as batch_op:
        batch_op.create_index(batch_op.f("ix_scene_shots_scene_id"), ["scene_id"], unique=False)

    op.create_table(
        "retention_curves",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("drops", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        *_base(),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"]),
        sa.UniqueConstraint("publication_id"),
    )

    with op.batch_alter_table("briefs") as batch_op:
        batch_op.add_column(sa.Column("language", sa.String(length=10), nullable=False, server_default="pt-BR"))
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(sa.Column("voices", sa.JSON(), nullable=False, server_default=EMPTY_OBJECT))
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("language", sa.String(length=10), nullable=False, server_default="pt-BR"))
        batch_op.add_column(sa.Column("autopilot", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("autopilot_stage", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("autopilot_reason", sa.Text(), nullable=True))
    with op.batch_alter_table("renders") as batch_op:
        batch_op.add_column(sa.Column("timeline", sa.JSON(), nullable=False, server_default=EMPTY_LIST))
    with op.batch_alter_table("script_versions") as batch_op:
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=False, server_default=EMPTY_OBJECT))


def downgrade() -> None:
    with op.batch_alter_table("script_versions") as batch_op:
        batch_op.drop_column("metadata")
    with op.batch_alter_table("renders") as batch_op:
        batch_op.drop_column("timeline")
    with op.batch_alter_table("projects") as batch_op:
        for column in ("autopilot_reason", "autopilot_stage", "autopilot", "language"):
            batch_op.drop_column(column)
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_column("voices")
    with op.batch_alter_table("briefs") as batch_op:
        batch_op.drop_column("language")
    for table in (
        "retention_curves",
        "scene_shots",
        "topic_suggestions",
        "stage_runs",
        "research_dossiers",
        "playbook_rules",
        "autopilot_settings",
    ):
        op.drop_table(table)
