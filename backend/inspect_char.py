import asyncio
from bleak import BleakClient

async def main():
    try:
        async with BleakClient('CF:40:F9:D0:BD:0A') as client:
            for service in client.services:
                for char in service.characteristics:
                    if char.uuid.lower() == '00000009-0000-3512-2118-0009af100700':
                        print(f'Auth Char Properties: {char.properties}')
    except Exception as e:
        print(f"Erro: {e}")

asyncio.run(main())
