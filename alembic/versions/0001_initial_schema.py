"""Initial schema — all PropFlow tables

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # PostgreSQL-only extensions
    if dialect == "postgresql":
        op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # landlords
    # ------------------------------------------------------------------
    op.create_table(
        "landlords",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(50), nullable=False),
        sa.Column("whatsapp_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("language", sa.String(10), nullable=False, server_default="de"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email", name="uq_landlords_email"),
        sa.UniqueConstraint("phone_number", name="uq_landlords_phone_number"),
    )

    # ------------------------------------------------------------------
    # buildings
    # ------------------------------------------------------------------
    op.create_table(
        "buildings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("landlord_id", sa.Uuid(), sa.ForeignKey("landlords.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("whatsapp_number", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("whatsapp_number", name="uq_buildings_whatsapp_number"),
    )

    # ------------------------------------------------------------------
    # tenants
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("building_id", sa.Uuid(), sa.ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("landlord_id", sa.Uuid(), sa.ForeignKey("landlords.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(50), nullable=False),
        sa.Column("unit_number", sa.String(20), nullable=False),
        sa.Column("rent_amount", sa.Numeric(10, 2)),
        sa.Column("rent_due_day", sa.Integer),
        sa.Column("lease_start", sa.Date),
        sa.Column("lease_end", sa.Date),
        sa.Column("language", sa.String(10), nullable=False, server_default="de"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("phone_number", name="uq_tenants_phone_number"),
    )
    op.create_index("ix_tenants_phone_number", "tenants", ["phone_number"])

    # ------------------------------------------------------------------
    # contractors
    # ------------------------------------------------------------------
    op.create_table(
        "contractors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("landlord_id", sa.Uuid(), sa.ForeignKey("landlords.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone_number", sa.String(50), nullable=False),
        sa.Column("specialties", sa.JSON),
        sa.Column("notes", sa.Text),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # tickets
    # ------------------------------------------------------------------
    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("building_id", sa.Uuid(), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("contractor_id", sa.Uuid(), sa.ForeignKey("contractors.id"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="new"),
        sa.Column("category", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("urgency", sa.String(50), nullable=False, server_default="medium"),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("ai_diagnosis", sa.Text),
        sa.Column("media_urls", sa.JSON),
        sa.Column("landlord_approval", sa.Boolean, nullable=True),
        sa.Column("locked_by", sa.String(50), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tickets_tenant_id", "tickets", ["tenant_id"])
    op.create_index("ix_tickets_building_id", "tickets", ["building_id"])
    op.create_index("ix_tickets_status", "tickets", ["status"])

    # ------------------------------------------------------------------
    # conversation_states
    # ------------------------------------------------------------------
    op.create_table(
        "conversation_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("phone_number", sa.String(50), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("current_ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id"), nullable=True),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("context", sa.JSON),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("phone_number", name="uq_conv_states_phone_number"),
    )
    op.create_index("ix_conversation_states_phone_number", "conversation_states", ["phone_number"])


def downgrade() -> None:
    op.drop_index("ix_conversation_states_phone_number", "conversation_states")
    op.drop_table("conversation_states")
    op.drop_index("ix_tickets_status", "tickets")
    op.drop_index("ix_tickets_building_id", "tickets")
    op.drop_index("ix_tickets_tenant_id", "tickets")
    op.drop_table("tickets")
    op.drop_table("contractors")
    op.drop_index("ix_tenants_phone_number", "tenants")
    op.drop_table("tenants")
    op.drop_table("buildings")
    op.drop_table("landlords")
