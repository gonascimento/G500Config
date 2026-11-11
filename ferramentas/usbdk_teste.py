"""Envia o comando de leitura de estado (50 01) direto ao volante via UsbDk + libusb."""
import faulthandler, sys; faulthandler.dump_traceback_later(45, exit=True)
import ctypes
import time

import libusb_package
import usb.backend.libusb1 as lb
import usb.core
import usb.util

be = lb.get_backend(find_library=lambda _: libusb_package.get_library_path())
be.lib.libusb_set_option.argtypes = [ctypes.c_void_p, ctypes.c_int]
r = be.lib.libusb_set_option(be.ctx, 1)  # LIBUSB_OPTION_USE_USBDK
print("UsbDk ativado no libusb:", r == 0, r)

dev = usb.core.find(idVendor=0x11FF, idProduct=0x2355, backend=be)
print("aparelho:", dev is not None)
try:
    cfg = dev.get_active_configuration()
except usb.core.USBError:
    # aparelho redirecionado pelo UsbDk chega sem configuração ativa
    dev.set_configuration()
    cfg = dev.get_active_configuration()
eps = {}
for intf in cfg:
    for ep in intf:
        d = "IN" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
        eps.setdefault(intf.bInterfaceNumber, []).append((d, ep.bEndpointAddress, ep.wMaxPacketSize))
        print(f"  interface {intf.bInterfaceNumber}: endpoint {d} 0x{ep.bEndpointAddress:02X} max {ep.wMaxPacketSize}")
for i in eps:
    try:
        usb.util.claim_interface(dev, i)
    except usb.core.USBError as e:
        print("claim", i, e)


def drain(secs):
    out = []
    t = time.time()
    while time.time() - t < secs:
        for i, lst in eps.items():
            for d, addr, mx in lst:
                if d != "IN":
                    continue
                try:
                    data = bytes(dev.read(addr, mx, timeout=30))
                    if data and data[0] != 0x01:
                        out.append((f"0x{addr:02X}", data.hex(" ")))
                except usb.core.USBTimeoutError:
                    pass
                except usb.core.USBError as e:
                    out.append((f"0x{addr:02X}", f"erro {e}"))
    return out


drain(0.3)
CMD = [0x50, 0x01]
tests = []
for intf in eps:
    tests += [
        (f"SET_REPORT saída id=50 intf {intf}", lambda i=intf: dev.ctrl_transfer(0x21, 0x09, (2 << 8) | 0x50, i, bytes(CMD + [0] * 18), 500)),
        (f"SET_REPORT feature id=50 intf {intf}", lambda i=intf: dev.ctrl_transfer(0x21, 0x09, (3 << 8) | 0x50, i, bytes(CMD + [0] * 18), 500)),
        (f"SET_REPORT saída id=0 intf {intf}", lambda i=intf: dev.ctrl_transfer(0x21, 0x09, (2 << 8) | 0x00, i, bytes(CMD + [0] * 18), 500)),
    ]
    for d, addr, mx in eps[intf]:
        if d == "OUT":
            tests.append((f"interrupt OUT 0x{addr:02X} (20 B)", lambda a=addr: dev.write(a, bytes(CMD + [0] * 18), 500)))
            tests.append((f"interrupt OUT 0x{addr:02X} (2 B)", lambda a=addr: dev.write(a, bytes(CMD), 500)))

for name, fn in tests:
    try:
        n = fn()
        res = "enviado %s" % n
    except usb.core.USBError as e:
        res = f"erro {e}"
    got = drain(0.8)
    print(f"{name:42s} {res:18s} respostas={got[:3]}")
    for rid in (0xD0,):
        for typ, tn in ((1, "input"), (3, "feature")):
            try:
                data = bytes(dev.ctrl_transfer(0xA1, 0x01, (typ << 8) | rid, 0, 32, 300))
                print(f"    GET_REPORT {tn} id=D0 -> {data.hex(' ')}")
            except usb.core.USBError:
                pass

for i in eps:
    usb.util.release_interface(dev, i)
usb.util.dispose_resources(dev)
print("fim (o volante volta ao Windows)")
