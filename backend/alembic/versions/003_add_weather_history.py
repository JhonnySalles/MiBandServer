"""Add weather_history table

Revision ID: 003_add_weather_history
Revises: 002_add_scheduler_fields
Create Date: 2026-10-22 09:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '003_add_weather_history'
down_revision: Union[str, None] = '002_add_scheduler_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'weather_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('city', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('temp', sa.Integer(), nullable=False),
        sa.Column('temp_min', sa.Integer(), nullable=True),
        sa.Column('temp_max', sa.Integer(), nullable=True),
        sa.Column('condition', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('humidity', sa.Integer(), nullable=True),
        sa.Column('wind_speed', sa.Integer(), nullable=True),
        sa.Column('weather_code', sa.Integer(), nullable=True),
        sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(), server_default='Open-Meteo', nullable=False),
        sa.Column('source', sqlmodel.sql.sqltypes.AutoString(), server_default='SYNC', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('weather_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_weather_history_timestamp'), ['timestamp'], unique=False)
        batch_op.create_index(batch_op.f('ix_weather_history_city'), ['city'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('weather_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_weather_history_city'))
        batch_op.drop_index(batch_op.f('ix_weather_history_timestamp'))
    op.drop_table('weather_history')
