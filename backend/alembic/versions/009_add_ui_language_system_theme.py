"""Add ui_language and system theme support

Revision ID: 009
Revises: 008
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    """Add ui_language column and update ui_theme to support system theme."""
    # Add ui_language column with default 'en'
    op.add_column('user_preferences', sa.Column('ui_language', sa.String(10), nullable=False, server_default='en'))

    # Note: We cannot directly change the default value of ui_theme in SQLite,
    # but new records will use the model default of 'system'.
    # Existing records keep their current theme preference (light/dark).


def downgrade():
    """Remove ui_language column."""
    op.drop_column('user_preferences', 'ui_language')
