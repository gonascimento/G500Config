"""Segunda tentativa de enviar o comando de leitura (50 01) pelo USB.
Somente comandos de leitura; nada de force feedback é disparado."""
import ctypes
import ctypes.wintypes as W
import threading
import time

import hid

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
hidd = ctypes.WinDLL("hid", use_last_error=True)
k32.CreateFileW.restype = W.HANDLE
k32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
for fn in ("HidD_SetOutputReport", "HidD_SetFeature", "HidD_GetFeature", "HidD_GetInputReport"):
    getattr(hidd, fn).argtypes = [W.HANDLE, ctypes.c_void_p, W.ULONG]
    getattr(hidd, fn).restype = W.BOOLEAN

GAME = [d for d in hid.enumerate(0x11FF, 0x2355) if d["usage"] == 4][0]["path"]
MOUSE = [d for d in hid.enumerate(0x11FF, 0x2355) if d["usage"] == 2][0]["path"]

# ---- leitor contínuo de relatórios de entrada (procura respostas 0xD?) ----
seen, stop = [], threading.Event()


def reader(path):
    h = hid.device()
    h.open_path(path)
    h.set_nonblocking(True)
    while not stop.is_set():
        r = h.read(64)
        if r:
            seen.append((path, bytes(r)))
        else:
            time.sleep(0.002)
    h.close()


threads = [threading.Thread(target=reader, args=(p,), daemon=True) for p in (GAME, MOUSE)]
for t in threads:
    t.start()
time.sleep(0.5)
base = len(seen)
kinds = {r[0] for _, r in seen}
print(f"leitura OK: {len(seen)} relatórios em 0,5 s, IDs vistos: {sorted(kinds)}")


def raw_open(path):
    h = k32.CreateFileW(path.decode(), 0xC0000000, 3, None, 3, 0, None)
    if h in (None, W.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error())
    return h


def try_(label, fn, buf):
    b = (ctypes.c_ubyte * len(buf))(*buf)
    ok = fn(b, len(buf))
    err = ctypes.get_last_error()
    mark = len(seen)
    time.sleep(0.6)
    new = [r for _, r in seen[mark:] if r[0] not in (0x01,)]
    print(f"{label:52s} ok={bool(ok)} erro={0 if ok else err} respostas={[r[:12].hex(' ') for r in new[:3]]}")


hg = raw_open(GAME)
cmd = [0x50, 0x01]
# A) canal de controle (SET_REPORT) com ID 0x50, tamanho de saída (18) e de feature (5)
try_("SetOutputReport id=50 (18 B)", lambda b, n: hidd.HidD_SetOutputReport(hg, b, n), cmd + [0] * 16)
try_("SetFeature id=50 (5 B)", lambda b, n: hidd.HidD_SetFeature(hg, b, n), cmd + [0] * 3)
# B) WriteFile com ID 0 e o comando logo depois
wr = W.DWORD()
try_("WriteFile id=00 + 50 01 (18 B)",
     lambda b, n: k32.WriteFile(W.HANDLE(hg), b, n, ctypes.byref(wr), None), [0x00] + cmd + [0] * 15)
# C) comando escondido dentro do feature declarado 5 (Create New Effect: não inicia efeito)
try_("SetFeature id=05 + 50 01", lambda b, n: hidd.HidD_SetFeature(hg, b, n), [0x05] + cmd + [0, 0])
# D) GetInputReport / GetFeature pedindo IDs de resposta
for rid in (0xD0, 0x50):
    buf = (ctypes.c_ubyte * 21)(rid)
    ok = hidd.HidD_GetInputReport(hg, buf, 21)
    print(f"GetInputReport id={rid:02X}: ok={bool(ok)} erro={0 if ok else ctypes.get_last_error()} "
          f"dados={bytes(buf).hex(' ') if ok else ''}")
k32.CloseHandle(W.HANDLE(hg))

# E) interface do mouse (MI_01): não tem saída declarada, mas testa o canal de controle
try:
    hm = raw_open(MOUSE)
    try_("mouse SetOutputReport id=50", lambda b, n: hidd.HidD_SetOutputReport(hm, b, n), cmd + [0] * 7)
    try_("mouse SetFeature id=50", lambda b, n: hidd.HidD_SetFeature(hm, b, n), cmd + [0] * 7)
    k32.CloseHandle(W.HANDLE(hm))
except OSError as e:
    print("mouse não abriu:", e)

stop.set()
time.sleep(0.1)
odd = [(p[-60:], r.hex(" ")) for p, r in seen[base:] if r[0] not in (0x01,)]
print("relatórios diferentes do normal durante o teste:", odd[:10])
