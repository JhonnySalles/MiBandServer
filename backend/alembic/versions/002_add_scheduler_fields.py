"""Add sync_interval_hours, last_sync_time, and sync_schedule table

Revision ID: 002_add_scheduler_fields
Revises: 001_initial_schema
Create Date: 2026-10-01 10:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '002_add_scheduler_fields'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('device_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sync_interval_hours', sa.Integer(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('last_sync_time', sa.DateTime(), nullable=True))
        batch_op.alter_column('sync_intervals', existing_type=sa.String(), nullable=True)

    op.create_table(
        'sync_schedule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_mac', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scheduled_time', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sync_schedule', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sync_schedule_device_mac'), ['device_mac'], unique=False)
        batch_op.create_index(batch_op.f('ix_sync_schedule_scheduled_time'), ['scheduled_time'], unique=False)


def downgrade() -> None:
    op.drop_table('sync_schedule')
    with op.batch_alter_table('device_config', schema=None) as batch_op:
        batch_op.drop_column('last_sync_time')
        batch_op.drop_column('sync_interval_hours')
