"""
Тест логина и списка ботов.
python3 test_login.py

Если 2FA — введи код из письма в консоли.
"""
import asyncio
from dotenv import load_dotenv
from cryptorg.client import CryptorgClient, NeedsTwoFA

load_dotenv()


async def main():
    c = CryptorgClient()

    print("Step 1: email + password...")
    try:
        await c.login_step1()
        print("Logged in (no 2FA)\n")
    except NeedsTwoFA:
        code = input("Введи код из письма: ").strip()
        await c.login_step2(code)
        print("2FA OK\n")

    print("Getting bots...")
    bots = await c.get_bots()
    print(f"Total bots: {len(bots)}")
    for b in bots:
        print(f"  id={b.get('id')} symbol={b.get('symbol') or b.get('pair')} "
              f"strategy={b.get('strategy')} status={b.get('status')} "
              f"deal={b.get('deal')}")

    print("\nGetting active deals...")
    deals = await c.get_deals(active=True)
    print(f"Active deals: {len(deals)}")
    for d in deals:
        print(f"  id={d.get('id')} botId={d.get('botId')} pair={d.get('pair')} "
              f"pnl={d.get('pnl')} status={d.get('status')}")

    await c.close()


asyncio.run(main())
