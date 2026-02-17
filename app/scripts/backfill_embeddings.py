"""Backfill embeddings for MemoryFacts that have embedding IS NULL.

Usage:
    cd /Users/i3dlab/Documents/NUS/bakchodi/aura/app
    python -m scripts.backfill_embeddings
"""

import asyncio
import logging

from sqlalchemy import select

from db.models import MemoryFact
from db.session import async_session
from donna.memory.embeddings import embed_texts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BATCH_SIZE = 50


async def backfill():
    async with async_session() as session:
        result = await session.execute(
            select(MemoryFact)
            .where(MemoryFact.embedding.is_(None))
            .order_by(MemoryFact.created_at.asc())
        )
        facts = result.scalars().all()

    if not facts:
        logger.info("No facts need embedding backfill.")
        return

    logger.info("Found %d facts without embeddings. Backfilling in batches of %d...", len(facts), BATCH_SIZE)

    for i in range(0, len(facts), BATCH_SIZE):
        batch = facts[i : i + BATCH_SIZE]
        texts = [f.fact for f in batch]

        try:
            vectors = await embed_texts(texts)
        except Exception:
            logger.exception("Batch %d failed, skipping %d facts", i // BATCH_SIZE, len(batch))
            continue

        async with async_session() as session:
            for fact, vector in zip(batch, vectors):
                fact_obj = await session.get(MemoryFact, fact.id)
                if fact_obj:
                    fact_obj.embedding = vector
            await session.commit()

        logger.info("Embedded batch %d/%d (%d facts)", i // BATCH_SIZE + 1,
                     (len(facts) + BATCH_SIZE - 1) // BATCH_SIZE, len(batch))

    logger.info("Backfill complete.")


if __name__ == "__main__":
    asyncio.run(backfill())
