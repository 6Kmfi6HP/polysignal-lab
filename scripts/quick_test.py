"""快速测试：连接 Polymarket Gamma API 获取实时数据"""
import asyncio
import httpx
import json


async def test_gamma_api():
    url = "https://gamma-api.polymarket.com/events"
    params = {"active": "true", "closed": "false", "limit": "5"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params)
        print(f"Gamma API status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Events found: {len(data)}")
            for event in data[:3]:
                markets = event.get("markets", [])
                print(f"  Event: {event.get('title', 'N/A')[:60]}")
                print(f"  Markets: {len(markets)}")
                for m in markets[:2]:
                    tokens = m.get("clobTokenIds", [])
                    print(f"    Market: {m.get('question', '')[:50]} | tokens: {tokens}")


async def main():
    print("=== Gamma API Test ===")
    await test_gamma_api()


asyncio.run(main())
