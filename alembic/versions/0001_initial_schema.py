"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("college", sa.String(200), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), server_default="student", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "events",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("venue", sa.String(300), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registration_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer, nullable=False),
        sa.Column("registered_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("price", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "registrations",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(30), server_default="PENDING", nullable=False),
        sa.Column("qr_token", sa.String(100), nullable=True),
        sa.Column("ticket_number", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qr_token"),
        sa.UniqueConstraint("ticket_number"),
    )
    op.create_index("ix_registrations_user_id", "registrations", ["user_id"])
    op.create_index("ix_registrations_event_id", "registrations", ["event_id"])
    op.create_index("ix_registrations_qr_token", "registrations", ["qr_token"])

    op.create_table(
        "payments",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("registration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("razorpay_order_id", sa.String(100), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(100), nullable=True),
        sa.Column("razorpay_signature", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), server_default="INITIATED", nullable=False),
        sa.Column("webhook_event_id", sa.String(100), nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["registration_id"], ["registrations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration_id"),
        sa.UniqueConstraint("razorpay_order_id"),
        sa.UniqueConstraint("razorpay_payment_id"),
        sa.UniqueConstraint("webhook_event_id"),
    )

    op.create_table(
        "checkins",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("registration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("volunteer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("gate", sa.String(50), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["registration_id"], ["registrations.id"]),
        sa.ForeignKeyConstraint(["volunteer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration_id"),
    )


def downgrade() -> None:
    op.drop_table("checkins")
    op.drop_table("payments")
    op.drop_index("ix_registrations_qr_token", "registrations")
    op.drop_index("ix_registrations_event_id", "registrations")
    op.drop_index("ix_registrations_user_id", "registrations")
    op.drop_table("registrations")
    op.drop_table("events")
    op.drop_index("ix_users_email", "users")
    op.drop_table("users")
