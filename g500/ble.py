"""Configuração do volante pelo Bluetooth (BLE), com o mesmo protocolo do app
"Racing Wheel" (com.star.v10, classe Device_FFB).

Serviço FFE0: escreve em FFE1 e recebe respostas por notificação em FFE2.
Cada comando 0x5X recebe uma resposta que começa com 0xDX:
  50 01                 ler estado        -> D0 .. modo, versão(u16), pedal, câmbio, modo de ângulo
  51 <modo> <parte>     ler perfil 0..5   -> D1 .. (parte 2 = ângulo e forças; 3/4/5 = curvas)
  52 <modo> <parte> ..  gravar parte do perfil (20 bytes)
  53 01 <modo>          trocar modo (1 = PC DInput, 2 = PC XInput)
  53 03 <modo> <ffb> <reverso>
  53 04 01 01 <ângulo u16>
  53 08 <modo>          restaurar padrão de fábrica
  53 09 01 <mola> <amortecimento> <atrito> <inércia>
"""
import asyncio
import struct
import threading

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover
    BleakClient = BleakScanner = None

WRITE_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
NAME_TAG = "FFB WHEEL"
MODES = {1: "PC DInput", 2: "PC XInput"}
MODE_NAMES = {1: "PC DInput", 2: "PC XInput", 3: "PS3", 4: "PS3", 5: "PS4 volante", 6: "PS4 controle",
              7: "Xbox 360", 8: "Xbox One volante", 9: "Xbox One controle", 10: "Android", 11: "Switch"}
CURVE_PARTS = {"throttle": 3, "brake": 4, "clutch": 5}
# Curva linear usada pelo app quando o usuário redefine o gráfico.
LINEAR_CURVE = [(819, 13107), (1638, 26214), (2457, 39321), (3276, 52428)]


def curve_points(gamma):
    """4 pontos (entrada 0..4095, saída 0..65535) para uma curva y = x^gamma."""
    pts = []
    for k in range(1, 5):
        x = k / 5
        pts.append((round(4095 * x), round(65535 * x ** gamma)))
    return pts


def pedal_curve_points(deadzone, saturation, gamma):
    """Converte zona morta, saturação e curva de um pedal nos 4 pontos que o
    volante guarda. O volante liga (0,0) -> pontos -> (4095,65535) com retas."""
    dz = min(max(float(deadzone), 0.0), 0.9)
    sat = min(max(float(saturation), dz + 0.05), 1.0)
    start = [dz] if dz >= 0.02 else []
    end = [sat] if sat <= 0.98 else []
    n = 4 - len(start) - len(end)
    xs = start + [dz + (sat - dz) * k / (n + 1) for k in range(1, n + 1)] + end
    pts, last_x = [], 0
    for x in xs:
        y = min(max((x - dz) / (sat - dz), 0.0), 1.0) ** float(gamma)
        px = max(round(4095 * x), last_x + 1)  # x sempre crescente
        pts.append((min(px, 4095), round(65535 * y)))
        last_x = px
    return pts


class WheelBLE:
    """Roda um loop asyncio numa thread. Os métodos públicos podem ser chamados
    da interface; o resultado aparece em .info / .status."""

    def __init__(self, on_change=None):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.client = None
        self.queue = None
        self.lock = asyncio.Lock()
        self.status = "desconectado"
        self.busy = False
        self.info = {}
        self.on_change = on_change or (lambda: None)

    # ------------------------------------------------------------ util
    def _run(self, coro):
        fut = asyncio.run_coroutine_threadsafe(self._guard(coro), self.loop)
        return fut

    async def _guard(self, coro):
        self.busy = True
        self.on_change()
        try:
            return await coro
        except Exception as e:  # noqa: BLE001
            self.status = f"erro: {e}"
            if self.client and not self.client.is_connected:
                self.client = None
        finally:
            self.busy = False
            self.on_change()

    @property
    def connected(self):
        return bool(self.client and self.client.is_connected)

    async def _cmd(self, pkt, reply, timeout=1.0, retries=3):
        """Envia um pacote e espera a resposta 0xDX correspondente."""
        async with self.lock:
            for _ in range(retries):
                while not self.queue.empty():
                    self.queue.get_nowait()
                await self.client.write_gatt_char(WRITE_UUID, bytes(pkt), response=True)
                try:
                    while True:
                        d = await asyncio.wait_for(self.queue.get(), timeout)
                        if (d[0] | 0x80) == reply:
                            return d
                except asyncio.TimeoutError:
                    continue
            raise RuntimeError(f"o volante não respondeu ao comando {bytes(pkt[:2]).hex(' ')}")

    # ------------------------------------------------------- conexão
    def connect(self):
        return self._run(self._connect())

    async def _connect(self):
        if BleakScanner is None:
            raise RuntimeError("biblioteca bleak não instalada")
        if self.connected:
            return
        self.status = "procurando o volante…"
        self.on_change()
        dev = await BleakScanner.find_device_by_filter(
            lambda d, a: NAME_TAG in (d.name or a.local_name or "").upper(), timeout=12)
        if not dev:
            self.status = "volante não encontrado (ligue o Bluetooth do PC e do volante)"
            return
        self.status = "conectando…"
        self.on_change()
        self.queue = asyncio.Queue()
        self.client = BleakClient(dev, disconnected_callback=self._on_disconnect)
        await self.client.connect()
        await self.client.start_notify(NOTIFY_UUID, lambda _, d: self.queue.put_nowait(bytes(d)))
        self.info["name"] = dev.name
        self.status = "conectado"
        await self._read_all()

    def _on_disconnect(self, _client):
        self.status = "desconectado"
        self.client = None
        self.on_change()

    def disconnect(self):
        return self._run(self._disconnect())

    async def _disconnect(self):
        if self.client:
            await self.client.disconnect()
        self.client = None
        self.status = "desconectado"

    # --------------------------------------------------------- leitura
    def read_all(self):
        return self._run(self._read_all())

    async def _read_all(self):
        d = await self._cmd([0x50, 0x01], 0xD0)
        mode = d[2]
        self.info.update(mode=mode, version=struct.unpack_from("<H", d, 3)[0],
                         pedal=d[5], shifter=d[6], angle_mode=d[7])
        d = await self._cmd([0x51, mode, 2], 0xD1)
        self.info["raw_part2"] = bytearray(d)
        self.info.update(angle=struct.unpack_from("<H", d, 5)[0], ffb=d[7], spring=d[8], damper=d[9],
                         friction=d[10], inertia=d[11], reverse=bool(d[12]))
        for key, part in CURVE_PARTS.items():
            d = await self._cmd([0x51, mode, part], 0xD1)
            self.info["curve_" + key] = [struct.unpack_from("<HH", d, 3 + 4 * k) for k in range(4)]
        self.status = "conectado"

    # --------------------------------------------------------- escrita
    def apply(self, angle=None, ffb=None, reverse=None, spring=None, damper=None, friction=None, inertia=None):
        return self._run(self._apply(angle, ffb, reverse, spring, damper, friction, inertia))

    async def _apply(self, angle, ffb, reverse, spring, damper, friction, inertia):
        if not self.connected:
            raise RuntimeError("volante não conectado pelo Bluetooth")
        i = self.info
        mode = i.get("mode", 1)
        if angle is not None:
            angle = int(max(90, min(900, round(angle / 10) * 10)))
            await self._cmd([0x53, 0x04, 0x01, 0x01, angle & 0xFF, angle >> 8], 0xD3)
            i["angle"] = angle
        if ffb is not None or reverse is not None:
            ffb = i.get("ffb", 80) if ffb is None else int(ffb)
            reverse = i.get("reverse", False) if reverse is None else bool(reverse)
            await self._cmd([0x53, 0x03, mode, ffb, int(reverse)], 0xD3)
            i.update(ffb=ffb, reverse=reverse)
        if any(v is not None for v in (spring, damper, friction, inertia)):
            vals = [i.get(k, 80) if v is None else int(v) for k, v in
                    (("spring", spring), ("damper", damper), ("friction", friction), ("inertia", inertia))]
            await self._cmd([0x53, 0x09, 0x01] + vals, 0xD3)
            i.update(spring=vals[0], damper=vals[1], friction=vals[2], inertia=vals[3])
        self.status = "configuração enviada"

    def write_curve(self, pedal, points):
        return self._run(self._write_curve(pedal, points))

    async def _write_curve(self, pedal, points):
        if not self.connected:
            raise RuntimeError("volante não conectado pelo Bluetooth")
        mode, part = self.info.get("mode", 1), CURVE_PARTS[pedal]
        pkt = bytearray(20)
        pkt[0], pkt[1], pkt[2] = 0x52, mode, part
        for k, (x, y) in enumerate(points[:4]):
            struct.pack_into("<HH", pkt, 3 + 4 * k, int(x), int(y))
        await self._cmd(pkt, 0xD2)
        self.info["curve_" + pedal] = [tuple(p) for p in points[:4]]
        self.status = "curva enviada"

    # ------------------------------------------- envio com confirmação
    def send_verified(self, settings=None, curves=None):
        """Envia ajustes e confirma relendo o volante.
        settings: dict com angle/ffb/reverse/spring/damper/friction/inertia (os que quiser).
        curves:   dict pedal -> 4 pontos.
        O futuro devolve {"ok", "faltando", "tempo"} (ou None se deu erro de conexão)."""
        return self._run(self._send_verified(settings or {}, curves or {}))

    async def _send_verified(self, settings, curves):
        import time
        t0 = time.time()
        if not self.connected:
            await self._connect()
            if not self.connected:
                raise RuntimeError(self.status)
        expected = dict(settings)
        if "angle" in expected:
            expected["angle"] = int(max(90, min(900, round(expected["angle"] / 10) * 10)))
        for k in ("ffb", "spring", "damper", "friction", "inertia"):
            if k in expected:
                expected[k] = int(expected[k])
        if "reverse" in expected:
            expected["reverse"] = bool(expected["reverse"])
        if settings:
            await self._apply(*(settings.get(k) for k in
                                ("angle", "ffb", "reverse", "spring", "damper", "friction", "inertia")))
        for pedal, pts in curves.items():
            await self._write_curve(pedal, pts)
            expected["curve_" + pedal] = [tuple(int(v) for v in p) for p in pts[:4]]
        # relê o que o volante guardou e compara com o que foi pedido
        self.status = "confirmando…"
        await asyncio.sleep(0.2)
        await self._read_all()
        faltando = [k for k, v in expected.items() if self.info.get(k) != v]
        self.status = "confirmado pelo volante" if not faltando else "o volante não aceitou tudo"
        return {"ok": not faltando, "faltando": faltando, "tempo": time.time() - t0}

    def switch_mode(self, mode):
        return self._run(self._switch_mode(mode))

    async def _switch_mode(self, mode):
        if mode not in MODES:
            raise ValueError("modo inválido")
        await self._cmd([0x53, 0x01, mode], 0xD3)
        await asyncio.sleep(1.0)
        await self._read_all()
        self.status = f"modo trocado para {MODES[mode]}"

    def factory_reset(self):
        return self._run(self._factory_reset())

    async def _factory_reset(self):
        await self._cmd([0x53, 0x08, self.info.get("mode", 1)], 0xD3)
        await asyncio.sleep(0.5)
        await self._read_all()
        self.status = "padrão de fábrica restaurado"

    def close(self):
        try:
            asyncio.run_coroutine_threadsafe(self._disconnect(), self.loop).result(3)
        except Exception:  # noqa: BLE001
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
