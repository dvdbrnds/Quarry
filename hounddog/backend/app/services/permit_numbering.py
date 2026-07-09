"""QPS permit number generator.

New permits issued by Quarry get sequential numbers like QPS-00001.
Legacy permits imported from the old system keep their original numbers.
The sequence is driven by a Postgres sequence for gap-free, concurrent-safe numbering.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PREFIX = "QPS"
SEQUENCE_NAME = "qps_permit_number_seq"


async def next_permit_number(db: AsyncSession) -> str:
    result = await db.execute(text(f"SELECT nextval('{SEQUENCE_NAME}')"))
    seq_val = result.scalar()
    return f"{PREFIX}-{seq_val:05d}"
