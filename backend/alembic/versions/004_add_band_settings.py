"""Add band_settings table

Revision ID: 004_add_band_settings
Revises: 003_add_weather_history
Create Date: 2026-10-22 10:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '004_add_band_settings'
down_revision: Union[str, None] = '003_add_weather_history'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'band_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_mac', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('event_reminders', sqlmodel.sql.sqltypes.AutoString(), server_default='[]', nullable=True),
        sa.Column('alarms', sqlmodel.sql.sqltypes.AutoString(), server_default='[]', nullable=True),
        sa.Column('world_clocks', sqlmodel.sql.sqltypes.AutoString(), server_default='[]', nullable=True),
        sa.Column('lift_wrist_mode', sqlmodel.sql.sqltypes.AutoString(), server_default='all_day', nullable=False),
        sa.Column('lift_wrist_start', sqlmodel.sql.sqltypes.AutoString(), server_default='07:00', nullable=False),
        sa.Column('lift_wrist_end', sqlmodel.sql.sqltypes.AutoString(), server_default='22:00', nullable=False),
        sa.Column('lift_wrist_speed', sqlmodel.sql.sqltypes.AutoString(), server_default='normal', nullable=False),
        sa.Column('night_mode', sqlmodel.sql.sqltypes.AutoString(), server_default='sunset', nullable=False),
        sa.Column('night_mode_start', sqlmodel.sql.sqltypes.AutoString(), server_default='22:00', nullable=False),
        sa.Column('night_mode_end', sqlmodel.sql.sqltypes.AutoString(), server_default='07:00', nullable=False),
        sa.Column('dnd_mode', sqlmodel.sql.sqltypes.AutoString(), server_default='smart', nullable=False),
        sa.Column('wear_location', sqlmodel.sql.sqltypes.AutoString(), server_default='left', nullable=False),
        sa.Column('language', sqlmodel.sql.sqltypes.AutoString(), server_default='pt_BR', nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('band_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_band_settings_device_mac'), ['device_mac'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('band_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_band_settings_device_mac'))
    op.drop_table('band_settings')
