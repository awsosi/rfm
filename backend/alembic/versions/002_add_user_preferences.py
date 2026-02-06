"""Add user_preferences table

Revision ID: 002
Revises: 001
Create Date: 2026-01-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create user_preferences table for storing individual user UI settings.
    """
    # Create user_preferences table
    op.create_table(
        'user_preferences',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('remember_last_paths', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_path_a', sa.String(length=1000), nullable=True),
        sa.Column('last_path_b', sa.String(length=1000), nullable=True),
        sa.Column('ui_theme', sa.String(length=50), nullable=False, server_default='light'),
        sa.Column('pane_layout', sa.String(length=50), nullable=False, server_default='horizontal'),
        sa.Column('custom_settings', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
    )

    # Create trigger for auto-updating updated_at
    op.execute("DROP TRIGGER IF EXISTS update_user_preferences_updated_at ON user_preferences;")
    op.execute("""
        CREATE TRIGGER update_user_preferences_updated_at
        BEFORE UPDATE ON user_preferences
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """
    Drop user_preferences table.
    """
    op.drop_table('user_preferences')
