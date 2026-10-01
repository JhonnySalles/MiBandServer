"""Initial migration with DeviceConfig, IntegrationConfig, ActivityLog, SyncHistory

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-10-01 09:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Criação da tabela device_config
    op.create_table(
        'device_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mac_address', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('auth_key', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('device_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sync_intervals', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('auto_weather', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('device_config', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_device_config_mac_address'), ['mac_address'], unique=True)

    # Criação da tabela integration_config
    op.create_table(
        'integration_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('weather_provider', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('weather_api_token', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('weather_city', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('cache_ttl_minutes', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Criação da tabela activity_log
    op.create_table(
        'activity_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_mac', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('steps', sa.Integer(), nullable=False),
        sa.Column('distance_meters', sa.Integer(), nullable=False),
        sa.Column('calories', sa.Integer(), nullable=False),
        sa.Column('heart_rate', sa.Integer(), nullable=True),
        sa.Column('battery_level', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('activity_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_activity_log_device_mac'), ['device_mac'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_log_timestamp'), ['timestamp'], unique=False)

    # Criação da tabela sync_history
    op.create_table(
        'sync_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_mac', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('details', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sync_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sync_history_device_mac'), ['device_mac'], unique=False)


def downgrade() -> None:
    op.drop_table('sync_history')
    op.drop_table('activity_log')
    op.drop_table('integration_config')
    op.drop_table('device_config')
