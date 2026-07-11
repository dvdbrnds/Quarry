"""Citation number generator.

Tickets get sequential numbers like CIT-00001.
The sequence is driven by a Postgres sequence for gap-free, concurrent-safe numbering.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PREFIX = "CIT"
SEQUENCE_NAME = "quarry_ticket_number_seq"


async def next_ticket_number(db: AsyncSession) -> str:
    result = await db.execute(text(f"SELECT nextval('{SEQUENCE_NAME}')"))
    seq_val = result.scalar()
    return f"{PREFIX}-{seq_val:05d}"
