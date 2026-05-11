"""
Заполняет шаблоны в БД на основе реальных ботов Cryptorg.
python3 seed_templates.py
"""
import asyncio
from dotenv import load_dotenv
from db.database import init_db, get_session_factory
from db.models import Template

load_dotenv()

# Шаблоны — неактивные боты из Cryptorg (status=0)
# Взяты из /crazy/api/bots 07.05.2026
TEMPLATES = [
    {"name": "TP 2% Period 2",  "cryptorg_bot_id": 165709},
    {"name": "TP 2% Period 5",  "cryptorg_bot_id": 165711},
]


async def main():
    await init_db()
    factory = get_session_factory()
    async with factory() as session:
        for t in TEMPLATES:
            session.add(Template(**t))
        await session.commit()
    print(f"Inserted {len(TEMPLATES)} templates.")


asyncio.run(main())
