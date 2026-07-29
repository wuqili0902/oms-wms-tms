import math

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int


async def paginate(
    db_stmt,
    db_session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedResponse:
    count_stmt = select(func.count()).select_from(db_stmt.subquery())
    total_result = await db_session.execute(count_stmt)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    stmt = db_stmt.offset(offset).limit(page_size)
    result = await db_session.execute(stmt)
    items = list(result.scalars().all())

    total_pages = math.ceil(total / page_size) if page_size > 0 and total > 0 else 0

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
