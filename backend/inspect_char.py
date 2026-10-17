import asyncio
from bleak import BleakClient

async def main():
    mac = 'CF:40:F9:D0:BD:0A'
    print(f"Conectando a {mac} para inspecionar serviços...")
    try:
        async with BleakClient(mac, timeout=12.0) as client:
            print("Conectado com sucesso!\n")
            for service in client.services:
                print(f"SERVIÇO: {service.uuid} ({service.description})")
                for char in service.characteristics:
                    print(f"   -> Característica: {char.uuid} | Props: {char.properties} ({char.description})")
                print()
    except Exception as e:
        print(f"Erro ao inspecionar: {e}")

if __name__ == '__main__':
    asyncio.run(main())
