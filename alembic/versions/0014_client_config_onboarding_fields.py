"""client config onboarding fields

Revision ID: 0014_client_config_onboarding_fields
Revises: 0013_hardening_exec_reports_and_selector_health
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_client_config_onboarding_fields"
down_revision = "0013_hardening_exec_reports_and_selector_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_configs",
        sa.Column("financial_year", sa.String(length=16), nullable=False, server_default="2025-26"),
    )
    op.add_column(
        "client_configs",
        sa.Column("preferred_run_window", sa.Integer(), nullable=False, server_default="18"),
    )
    op.add_column("client_configs", sa.Column("tags", sa.Text(), nullable=True))
    op.add_column("client_configs", sa.Column("notes", sa.Text(), nullable=True))
    op.create_index("ix_client_configs_financial_year", "client_configs", ["financial_year"])
    op.create_index("ix_client_configs_preferred_run_window", "client_configs", ["preferred_run_window"])


def downgrade() -> None:
    op.drop_index("ix_client_configs_preferred_run_window", table_name="client_configs")
    op.drop_index("ix_client_configs_financial_year", table_name="client_configs")
    op.drop_column("client_configs", "notes")
    op.drop_column("client_configs", "tags")
    op.drop_column("client_configs", "preferred_run_window")
    op.drop_column("client_configs", "financial_year")

