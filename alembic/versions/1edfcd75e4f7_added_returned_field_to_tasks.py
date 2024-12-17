"""Added returned field to tasks

Revision ID: 1edfcd75e4f7
Revises: ce29e2d726fd
Create Date: 2024-12-12 17:05:20.225342

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1edfcd75e4f7'
down_revision: Union[str, None] = 'ce29e2d726fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('task', sa.Column('returned', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('task', 'returned')
    # ### end Alembic commands ###