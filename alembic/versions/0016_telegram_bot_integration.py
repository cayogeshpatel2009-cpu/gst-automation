"""telegram bot infrastructure

Revision ID: 0016_telegram_bot_integration
Revises: 0015_gst_monthly_execution_tracker
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016_telegram_bot_integration"
down_revision = "0015_gst_monthly_execution_tracker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(length=200), nullable=True),
        sa.Column("telegram_first_name", sa.String(length=200), nullable=True),
        sa.Column("telegram_last_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="operator"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_telegram_users_telegram_user_id", "telegram_users", ["telegram_user_id"])
    op.create_index("ix_telegram_users_telegram_chat_id", "telegram_users", ["telegram_chat_id"])
    op.create_index("ix_telegram_users_status", "telegram_users", ["status"])

    op.create_table(
        "telegram_messages",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("callback_data", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_telegram_messages_telegram_message_id", "telegram_messages", ["telegram_message_id"])
    op.create_index("ix_telegram_messages_telegram_user_id", "telegram_messages", ["telegram_user_id"])
    op.create_index("ix_telegram_messages_checkpoint_id", "telegram_messages", ["checkpoint_id"])
    op.create_index("ix_telegram_messages_job_id", "telegram_messages", ["job_id"])
    op.create_index("ix_telegram_messages_direction", "telegram_messages", ["direction"])
    op.create_index("ix_telegram_messages_created_at", "telegram_messages", ["created_at"])

    op.create_table(
        "telegram_audit",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_telegram_audit_telegram_user_id", "telegram_audit", ["telegram_user_id"])
    op.create_index("ix_telegram_audit_action", "telegram_audit", ["action"])
    op.create_index("ix_telegram_audit_created_at", "telegram_audit", ["created_at"])


def downgrade() -> None:
    op.drop_table("telegram_audit")
    op.drop_table("telegram_messages")
    op.drop_table("telegram_users")

