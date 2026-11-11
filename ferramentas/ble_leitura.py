import asyncio, struct
from bleak import BleakScanner, BleakClient

SVC = "0000ffe0-0000-1000-8000-00805f9b34fb"
WR = "0000ffe1-0000-1000-8000-00805f9b34fb"
NT = "0000ffe2-0000-1000-8000-00805f9b34fb"


async def main():
    dev = await BleakScanner.find_device_by_filter(
        lambda d, a: "FFB WHEEL" in (d.name or a.local_name or "").upper(), timeout=10)
    print("dispositivo:", dev)
    q = asyncio.Queue()
    async with BleakClient(dev) as c:
        for s in c.services:
            print("serviço", s.uuid)
            for ch in s.characteristics:
                print("   ", ch.uuid, ch.properties)
        wr = c.services.get_characteristic(WR)
        resp = "write" in wr.properties
        await c.start_notify(NT, lambda _, d: q.put_nowait(bytes(d)))

        async def cmd(pkt, wait=1.0):
            await c.write_gatt_char(WR, bytes(pkt), response=resp)
            out = []
            try:
                while True:
                    out.append(await asyncio.wait_for(q.get(), wait))
                    wait = 0.3
            except asyncio.TimeoutError:
                pass
            for d in out:
                print(f"  -> {d.hex(' ')}")
            return out

        print("readState 50 01")
        st = await cmd([0x50, 0x01])
        mode = 1
        for d in st:
            if d[0] | 0x80 == 0xD0:
                mode = d[2]
                ver = struct.unpack_from("<H", d, 3)[0]
                print(f"  modo={mode} versao={ver} pedal={d[5]} cambio={d[6]} angleMode={d[7]}")
        for i in range(6):
            print(f"readProfile 51 {mode:02x} {i:02x}")
            for d in await cmd([0x51, mode, i]):
                if d[0] | 0x80 == 0xD1 and d[2] == 2:
                    ang = struct.unpack_from("<H", d, 5)[0]
                    print(f"  ANGULO={ang}  FFB={d[7]} mola={d[8]} amortec={d[9]} atrito={d[10]} inercia={d[11]} reverso={d[12]}")
                if d[0] | 0x80 == 0xD1 and d[2] in (3, 4, 5):
                    pts = [struct.unpack_from("<HH", d, 3 + 4 * k) for k in range(4)]
                    print("  curva", {3: "acelerador", 4: "freio", 5: "embreagem"}[d[2]], pts)
        await c.stop_notify(NT)

asyncio.run(main())
