"""
Показывает список exchange-аккаунтов (accessId) из Cryptorg.
Запускай один раз чтобы узнать свой ACCESS_ID для seed_templates.py.

python get_access_list.py
"""
import asyncio
import json
from dotenv import load_dotenv
from cryptorg.client import CryptorgClient

load_dotenv()


async def main():
    client = CryptorgClient()
    result = await client.get_access_list()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    await client.close()


asyncio.run(main())
