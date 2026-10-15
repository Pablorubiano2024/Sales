"""Add listing_catalog_matches (catalog products verified as ours)

Revision ID: a1c3e5f7b9d2
Revises: 79343d91d477
Create Date: 2026-10-15 18:30:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c3e5f7b9d2"
down_revision: Union[str, None] = "79343d91d477"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "listing_catalog_matches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("marketplace_product_id", sa.String(length=36), nullable=False),
        sa.Column("catalog_product_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["marketplace_product_id"], ["marketplace_products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("marketplace_product_id", "catalog_product_id"),
    )
    op.create_index(
        op.f("ix_listing_catalog_matches_marketplace_product_id"),
        "listing_catalog_matches",
        ["marketplace_product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_listing_catalog_matches_marketplace_product_id"),
        table_name="listing_catalog_matches",
    )
    op.drop_table("listing_catalog_matches")
