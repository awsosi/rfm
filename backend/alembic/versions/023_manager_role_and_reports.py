"""Manager role, classification reports, double-dot file name rule

- ``userrole`` gains ``MANAGER``: a user who also sees the manager view
  (operation history with filters, reports). Only admins assign it.
- ``report_runs``: every classification report written to the Windows share,
  by the nightly job (SCHEDULED) or by a manager (MANUAL). The partial unique
  index lets exactly one API process claim a scheduled report.
- ``reports_*`` config: the monthly classification reports (off by default),
  seeded with the defaults Grzegorz Gutek asked for on 2026-10-07.
- ``push_validation_reject_double_dots`` (on): refuse files such as ``2..jpg``
  even while the PIM file name rule is off.

Only missing rows are inserted: a value an operator already set is kept.

Note on TODO.md rule 3 (consolidated migrations): as with 012-022, 001 is
already applied on live databases, so this arrives as its own revision.

Revision ID: 023
Revises: 022
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '023'
down_revision: Union[str, None] = '022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RECIPIENTS = [
    {"name": "Natalia", "username": "mizn"},
    {"name": "Lena", "username": "vzle"},
    {"name": "Ewa", "username": "vzwe"},
]

_COLUMNS = [
    {"header": "Nazwa", "field": "catalog_name"},
    {"header": "Projektant", "field": "product.designer"},
    {"header": "Płeć", "field": "product.gender"},
    {"header": "Data premiery", "field": "product.release_date"},
    {"header": "Data ostatniej wysyłki", "field": "product.last_send_date"},
]

# (key, value, config_type, description)
_CONFIG_SEED = [
    ('push_validation_reject_double_dots', 'true', 'BOOLEAN',
     'Refuse files whose name holds two dots in a row (e.g. 2..jpg), also while the PIM file name rule is off'),
    ('reports_auto_enabled', 'false', 'BOOLEAN',
     'Write the monthly classification reports to the Windows share every night'),
    ('reports_run_time', '02:00', 'STRING',
     'Local time (HH:MM) of the nightly report run'),
    ('reports_timezone', 'Europe/Warsaw', 'STRING',
     'Time zone of report days, months and the run time'),
    ('reports_retry_minutes', '60', 'INT',
     'Minutes before a failed nightly report is tried again (the same day)'),
    ('reports_recipients', json.dumps(_RECIPIENTS, ensure_ascii=False), 'JSON',
     'One report per person: {"name": used in the file name, "username": RFM user whose pushes it lists}'),
    ('reports_output_dir',
     r'\\radius1\Users\Iza.Horna\WAŻNE FOLDERY BEATA GRZESIEK\!RAPORTY KLASYFIKACJA\{year}\{month} {month_name}',
     'STRING',
     'UNC folder of a report. Placeholders: {year} {month} {month_name} {name} {username}'),
    ('reports_file_name', 'Raport_klasyfikacji_{name}_{year}_{month}.xlsx', 'STRING',
     'File name of a report. Placeholders: {year} {month} {month_name} {name} {username}'),
    ('reports_month_names',
     'STYCZEŃ,LUTY,MARZEC,KWIECIEŃ,MAJ,CZERWIEC,LIPIEC,SIERPIEŃ,WRZESIEŃ,PAŹDZIERNIK,LISTOPAD,GRUDZIEŃ',
     'STRING', '{month_name}: twelve comma-separated names, January first'),
    ('reports_smb_username', '', 'STRING',
     'Account that writes to the share, e.g. DOMAIN\\user'),
    ('reports_smb_password', '', 'STRING', 'Password of the share account'),
    ('reports_columns', json.dumps(_COLUMNS, ensure_ascii=False), 'JSON',
     'Report columns: {"header", "field"}; fields: catalog_name, pushed_at, username, '
     'file_count, operation_id, or product.<key> from the product details service'),
    ('reports_sheet_name', 'Raport', 'STRING', 'Worksheet name (at most 31 characters)'),
    ('reports_date_format', 'DD.MM.YYYY', 'STRING', 'Excel format of dates in the report'),
    ('reports_day_row_color', '#afd095', 'STRING', 'Background of the merged row that starts each day'),
    ('reports_late_row_color', '#ffa6a6', 'STRING',
     'Background of products pushed after the date in reports_late_field'),
    ('reports_late_field', 'product.release_date', 'STRING',
     'Date field a push day is compared with; empty turns the highlight off'),
    ('reports_exclude_pulled', 'true', 'BOOLEAN', 'Leave out pushes that were pulled back later'),
    ('reports_overwrite_foreign', 'false', 'BOOLEAN',
     'Overwrite a report file on the share that RFM did not create (otherwise the run fails)'),
    ('reports_product_url', '', 'STRING',
     'PolkaSQL RFM_ProductDetails web service URL; empty leaves product.* columns blank'),
    ('reports_product_api_key', '', 'STRING', 'API key of the product details service'),
    ('reports_product_timeout', '20', 'INT', 'Timeout in seconds of one product details request'),
]


def upgrade() -> None:
    # Allowed inside the migration transaction on PostgreSQL 12+, as long as
    # the new value is not used in the same transaction.
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'MANAGER'")

    op.create_table(
        'report_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('trigger', sa.String(16), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=True),
        sa.Column('report_month', sa.Date(), nullable=False),
        sa.Column('recipient', sa.Text(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('file_path', sa.Text(), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('requested_by', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'uq_report_runs_scheduled', 'report_runs', ['run_date', 'recipient', 'report_month'],
        unique=True, postgresql_where=sa.text("trigger = 'SCHEDULED'"),
    )
    op.create_index('ix_report_runs_started_at', 'report_runs', ['started_at'])

    conn = op.get_bind()
    for key, value, config_type, description in _CONFIG_SEED:
        conn.execute(
            sa.text(
                "INSERT INTO config (key, value, type, description) "
                "VALUES (:key, :value, CAST(:type AS configtype), :description) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value, "type": config_type, "description": description},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM config WHERE key = ANY(:keys)"),
        {"keys": [key for key, *_ in _CONFIG_SEED]},
    )
    op.drop_index('ix_report_runs_started_at', table_name='report_runs')
    op.drop_index('uq_report_runs_scheduled', table_name='report_runs')
    op.drop_table('report_runs')
    # PostgreSQL cannot drop an enum value: managers become users, MANAGER stays unused
    conn.execute(sa.text("UPDATE users SET role = 'USER' WHERE role = 'MANAGER'"))
