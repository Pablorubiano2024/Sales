"""add sale_alerts and market_gap_snapshots (opportunity_id, captured_at) index

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-10-22

Both already exist in production: sale_alerts via init_db's create_all,
the index created by hand (CONCURRENTLY) on 2026-10-22.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b2d4f6a8c0e1"
down_revision: Union[str, None] = "a1c3e5f7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sale_alerts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("message_ts", sa.Text(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sale_alerts_order_id", "sale_alerts", ["order_id"], unique=True)
    op.create_index(
        "ix_market_gap_snapshots_opp_captured",
        "market_gap_snapshots",
        ["opportunity_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_gap_snapshots_opp_captured", table_name="market_gap_snapshots")
    op.drop_index("ix_sale_alerts_order_id", table_name="sale_alerts")
    op.drop_table("sale_alerts")
