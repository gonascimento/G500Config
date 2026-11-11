"""Janela principal em HTML (WebView2 via pywebview) ligada ao Controller."""
import json
import os
import sys
import threading
import time
import traceback
import webbrowser

import webview

from .controller import APP_VERSION, Controller, resource

HIDHIDE_URL = "https://github.com/nefarius/HidHide/releases"
WINDOW_TITLE = "G500 Config — Kalkam G500 / PCyes W270"


def _colorref(hex_color):
    """'#RRGGBB' -> COLORREF (0x00BBGGRR) usado pelo Windows."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def style_title_bar(window, caption="#12151c", text="#e1e7f0", border="#242b3b"):
    """Pinta a barra de título nativa do Windows com as cores do programa (Windows 11;
    no Windows 10 fica só o modo escuro). Mantém arrastar, encaixar e redimensionar."""
    import ctypes
    import ctypes.wintypes as W
    try:
        hwnd = 0
        try:
            hwnd = int(window.native.Handle.ToInt64())
        except Exception:  # noqa: BLE001
            hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            return False
        dwm = ctypes.windll.dwmapi

        def setattr_(attr, value):
            v = W.DWORD(value)
            return dwm.DwmSetWindowAttribute(W.HWND(hwnd), W.DWORD(attr), ctypes.byref(v), ctypes.sizeof(v))
        if setattr_(20, 1) != 0:   # DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 2004+)
            setattr_(19, 1)        # versões antigas do Windows 10
        setattr_(35, _colorref(caption))  # DWMWA_CAPTION_COLOR (Windows 11)
        setattr_(36, _colorref(text))     # DWMWA_TEXT_COLOR
        setattr_(34, _colorref(border))   # DWMWA_BORDER_COLOR
        return True
    except (AttributeError, OSError):
        return False


def _wrap(fn):
    """Toda chamada da interface devolve {ok, data} ou {ok: False, error}."""
    def call(*args):
        try:
            return {"ok": True, "data": fn(*args)}
        except Exception as e:  # noqa: BLE001
            if not isinstance(e, ValueError):
                traceback.print_exc()
            return {"ok": False, "error": str(e)}
    call.__name__ = fn.__name__
    return call


class Api:
    def __init__(self, ctl):
        self._ctl = ctl
        self._window = None
        self.ready = False
        c = ctl
        # métodos expostos ao JavaScript (window.pywebview.api.<nome>)
        for name, fn in {
            "init": c.init_data, "set_value": c.set_value, "set_global": c.set_global,
            "activate": c.activate, "profile_new": c.profile_new, "profile_duplicate": c.profile_duplicate,
            "profile_rename": c.profile_rename, "profile_delete": c.profile_delete,
            "exe_add": c.exe_add, "exe_remove": c.exe_remove, "running_processes": c.running_processes,
            "ble_connect": c.ble_connect, "ble_read": c.ble_read, "ble_disconnect": c.ble_disconnect,
            "send_hw": c.send_hw, "send_pedals": c.send_pedals, "switch_mode": c.switch_mode,
            "factory_reset": c.factory_reset, "ffb_test": c.ffb_test, "start_detect": c.start_detect,
            "cancel_detect": c.cancel_detect, "calibrate": c.calibrate, "install_vigem": c.install_vigem,
            "reset_mapping": c.reset_mapping,
            "refresh_services": c.refresh_services,
        }.items():
            setattr(self, name, _wrap(fn))

    def state(self):
        try:
            return self._ctl.state()
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def profile(self):
        return self._ctl.prof

    def ui_ready(self):
        self.ready = True
        return True

    def clear_message(self):
        self._ctl.message = ""
        return True

    def open_hidhide(self):
        webbrowser.open(HIDHIDE_URL)
        return True

    def export_profiles(self, which):
        names = sorted(self._ctl.profiles) if which == "all" else [self._ctl.active]
        default = "perfis_g500.json" if which == "all" else (
            "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in self._ctl.active).strip() + ".json")
        path = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=default,
                                               file_types=("Perfis do G500 Config (*.json)",))
        if not path:
            return {"ok": True, "data": None}
        path = path if isinstance(path, str) else path[0]
        try:
            n = self._ctl.export_to(path, names)
            return {"ok": True, "data": {"count": n, "path": path}}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def import_profiles(self):
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                                file_types=("Perfis do G500 Config (*.json)",))
        if not paths:
            return {"ok": True, "data": None}
        return {"ok": True, "data": self._ctl.import_from(list(paths))}


def _self_test(api, ctl, out_path, window):
    """--autoteste: espera a interface carregar e o Bluetooth conectar, grava um relatório e fecha."""
    t0 = time.time()
    ctl.ble_connect()
    while time.time() - t0 < 45:
        if api.ready and ctl.ble.connected and not ctl.ble.busy and "angle" in ctl.ble.info:
            break
        time.sleep(0.5)
    time.sleep(1.5)
    s = ctl.state()
    rep = {"versao": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)), "interface_carregou": api.ready,
           "usb_conectado": s["usb"]["connected"], "usb_nome": s["usb"]["name"], "eixos": s["axes"],
           "botoes": len(s["buttons"]), "volante_detectado": s["device_detected"],
           "ble": s["ble"]["status"], "ble_info": s["ble"]["info"], "vigem": s["svc"]["vigem"],
           "overlay_rodando": s["overlay_running"]}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2, ensure_ascii=False, default=str)
    window.destroy()


def main():
    ctl = Controller()
    api = Api(ctl)
    window = webview.create_window(
        WINDOW_TITLE, url=resource("g500", "webui", "index.html"), js_api=api,
        width=1320, height=860, min_size=(980, 640), maximized=True, background_color="#0b0c10")
    api._window = window
    window.events.closed += lambda: ctl.close()
    window.events.shown += lambda: style_title_bar(window)
    window.events.loaded += lambda: style_title_bar(window)
    func, args = None, ()
    if "--autoteste" in sys.argv:
        i = sys.argv.index("--autoteste")
        out = sys.argv[i + 1] if len(sys.argv) > i + 1 else "autoteste.json"
        func, args = (lambda: threading.Thread(target=_self_test, args=(api, ctl, out, window), daemon=True).start()), ()
    icon = resource("assets", "icone.ico")
    try:
        _start(func, args, icon)
    except Exception:
        ctl.close()  # libera o volante antes de cair para a interface antiga
        raise


def _start(func, args, icon):
    webview.start(func, args, gui="edgechromium", http_server=True, icon=icon if os.path.exists(icon) else None,
                  storage_path=os.path.join(os.environ.get("LOCALAPPDATA", "."), "G500Config", "webview"),
                  private_mode=False)
