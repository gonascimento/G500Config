"""Lógica do G500 Config sem interface gráfica.

Junta o leitor do volante (Engine), o Bluetooth (WheelBLE), os perfis por jogo, a troca
automática de perfil, os envios com confirmação, o modo "Sentir os ajustes" e a
sobreposição dos pedais nos jogos. A interface (HTML ou tkinter) só chama estes métodos.
"""
import copy
import ctypes
import ctypes.wintypes as W
import json
import os
import socket
import subprocess
import sys
import threading
import time

import psutil

from . import profiles as P
from .ble import LINEAR_CURVE, MODE_NAMES, MODES, WheelBLE, pedal_curve_points
from .engine import Engine, vg

APP_VERSION = "2.0"
EXPORT_FORMAT = "g500config-perfis"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Volantes suportados. Os dois usam o mesmo protocolo da LITE STAR.
DEVICES = {
    "kalkam": {"name": "Kalkam G500", "match": ("G500", "KALKAN", "KALKAM"), "color": "#00f0ff",
               "badge": "FFB · LITE STAR", "photo": "img/kalkam_g500.png"},
    "pcyes": {"name": "PCyes W270", "match": ("W270", "PCYES"), "color": "#ff2a4b",
              "badge": "FFB · LITE STAR", "photo": "img/pcyes_w270.png"},
}

OVERLAY_DEFAULT = {"enabled": False, "edit": False, "x": 40, "y": 40, "opacity": 0.85, "scale": 1.0,
                   "orientation": "vertical", "labels": True, "percent": True,
                   "show": {"clutch": True, "brake": True, "throttle": True}}

FIELD_NAMES = {"angle": "ângulo", "ffb": "force feedback", "spring": "mola", "damper": "amortecimento",
               "friction": "atrito", "inertia": "inércia", "reverse": "inversão",
               "curve_throttle": "curva do acelerador", "curve_brake": "curva do freio",
               "curve_clutch": "curva da embreagem"}
GEARS = ["1", "2", "3", "4", "5", "6", "R"]

# Mapeamento padrão dos botões físicos (contados a partir de 0) do Kalkam G500, conforme a
# "Lista de correspondência de teclas" do manual (KLK00032), coluna PC (D-INPUT) menos 1.
# As borboletas repetem L1/R1 (manual: L-paddle = 5, R-paddle = 6).
DEFAULT_HOTSPOTS = {
    "kalkam": {"btn-a": 0, "btn-b": 1, "btn-x": 2, "btn-y": 3,
               "l1": 4, "paddle-l": 4, "r1": 5, "paddle-r": 5, "l2": 6, "r2": 7,
               "share": 8, "options": 9, "l3": 10, "r3": 11, "mode": 12, "capture": 13},
    "pcyes": {},
}
# Câmbio do Kalkam G500: 16..21 = marchas 1..6, 22 = ré, 15 = Park, 23 = caixa alta/baixa.
DEFAULT_SHIFTER = {"1": 16, "2": 17, "3": 18, "4": 19, "5": 20, "6": 21, "R": 22}
DEFAULT_SHIFTER_EXTRA = {"park": 15, "range": 23}


def resource(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def _service_installed(name):
    try:
        return subprocess.run(["sc", "query", name], capture_output=True, creationflags=NO_WINDOW).returncode == 0
    except OSError:
        return False


def vigem_installer():
    if vg is not None:
        p = os.path.join(os.path.dirname(vg.__file__), "win", "vigem", "install", "x64", "ViGEmBusSetup_x64.msi")
        if os.path.exists(p):
            return p
    p = resource("vgamepad", "win", "vigem", "install", "x64", "ViGEmBusSetup_x64.msi")
    return p if os.path.exists(p) else None


def app_in_foreground():
    """True se a janela em primeiro plano é deste processo."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()
    except (AttributeError, OSError):
        return True


def _get(d, path):
    for k in path:
        d = d[k]
    return d


def _set(d, path, v):
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = v


class OverlayLink:
    """Processo separado com a janela das barras dos pedais (sempre por cima)."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.peer = None
        self.proc = None

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running():
            return
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--overlay", str(self.port)]
        else:
            exe = sys.executable
            w = os.path.join(os.path.dirname(exe), "pythonw.exe")
            cmd = [w if os.path.exists(w) else exe, resource("main.py"), "--overlay", str(self.port)]
        self.peer = None
        self.proc = subprocess.Popen(cmd, creationflags=NO_WINDOW)

    def stop(self):
        if self.running():
            self.send({"quit": 1})
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.peer = None

    def send(self, msg):
        if self.peer:
            try:
                self.sock.sendto(json.dumps(msg).encode(), self.peer)
            except OSError:
                pass

    def poll(self):
        msgs = []
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                break
            try:
                m = json.loads(data.decode())
            except ValueError:
                continue
            if m.get("hello"):
                self.peer = addr
            msgs.append(m)
        return msgs


class Controller:
    def __init__(self):
        self.lock = threading.RLock()
        self.profiles = P.load_profiles()
        self.glob = P.load_global()
        g = self.glob
        g.setdefault("calibration", {})
        g.setdefault("device", "auto")
        g.setdefault("preview", True)
        g.setdefault("auto_switch", True)
        g.setdefault("hotspots", {"kalkam": {}, "pcyes": {}})
        for dev, defaults in DEFAULT_HOTSPOTS.items():  # completa com o padrão o que ainda não foi definido
            hs = g["hotspots"].setdefault(dev, {})
            for k, v in defaults.items():
                hs.setdefault(k, v)
        g.setdefault("shifter", {})
        for k, v in DEFAULT_SHIFTER.items():
            if g["shifter"].get(k) is None:
                g["shifter"][k] = v
        g.setdefault("shifter_extra", {})
        for k, v in DEFAULT_SHIFTER_EXTRA.items():
            g["shifter_extra"].setdefault(k, v)
        g.setdefault("accent", "#ff2a4b")  # cor base da interface (vermelho)
        g.setdefault("zoom", None)  # proporção da interface (None = automática)
        g.setdefault("device_art", "photo")  # seletor de volante: "photo" ou "drawing"
        ov = copy.deepcopy(OVERLAY_DEFAULT)
        ov.update({k: v for k, v in g.get("overlay", {}).items() if k in ov})
        ov["show"] = {**OVERLAY_DEFAULT["show"], **g.get("overlay", {}).get("show", {})}
        ov["edit"] = False
        g["overlay"] = ov

        self.active = g.get("active_profile") if g.get("active_profile") in self.profiles else "Padrão"
        self.manual_profile = self.active
        self.auto_active = False
        self.last_match = None
        self.running_exes = set()

        self.engine = Engine(self.prof, g["calibration"])
        self.engine.start()
        self.ble = WheelBLE()
        self.badges = {"bt": {"state": "idle", "text": ""}, "adj": {"state": "idle", "text": ""}}
        self.jobs = []
        self.detect = None
        self.message = ""
        self.save_at = 0.0
        self.overlay = OverlayLink()
        self.overlay_screen = [1920, 1080]
        self.svc = {"vigem": _service_installed("ViGEmBus"), "hidhide": _service_installed("HidHide")}
        self.ble_after_connect = None
        self.alive = True
        threading.Thread(target=self._watch_processes, daemon=True).start()
        threading.Thread(target=self._loop, daemon=True).start()

    # ------------------------------------------------------------ básico
    @property
    def prof(self):
        return self.profiles[self.active]

    def _save_soon(self):
        self.save_at = time.time() + 0.6

    def save_now(self):
        with self.lock:
            self.save_at = 0.0
            P.save_profile(self.prof)
            self.glob["active_profile"] = self.manual_profile
            P.save_global(self.glob)

    def close(self):
        self.alive = False
        self.save_now()
        self.overlay.stop()
        self.engine.stop()
        self.engine.join(2)
        self.ble.close()

    # ------------------------------------------------------------ dados para a interface
    def init_data(self):
        with self.lock:
            return {"version": APP_VERSION, "devices": DEVICES, "profiles": self.profile_names(),
                    "active": self.active, "profile": self.prof, "glob": self._glob_public(),
                    "xbox_buttons": P.XBOX_BUTTONS, "gears": GEARS, "modes": MODES}

    def _glob_public(self):
        g = self.glob
        return {k: g[k] for k in ("device", "preview", "auto_switch", "hotspots", "shifter", "shifter_extra", "overlay", "accent", "zoom", "device_art")}

    def profile_names(self):
        return sorted(self.profiles, key=lambda n: (n != "Padrão", n.lower()))

    def detected_device(self, s=None):
        s = s or self.engine.snapshot()
        names = (s.get("name") or "") + " " + (self.ble.info.get("name") or "")
        names = names.upper()
        for key, d in DEVICES.items():
            if any(m in names for m in d["match"]):
                return key
        return None

    def current_device(self, s=None):
        if self.glob["device"] in DEVICES:
            return self.glob["device"]
        return self.detected_device(s) or "kalkam"

    def state(self):
        s = self.engine.snapshot()
        with self.lock:
            p = self.prof
            wi = int(p["axes"]["wheel"])
            raw = 0.0
            if s["axes"] and 0 <= wi < len(s["axes"]):
                raw = self.engine._norm_axis(wi, s["axes"][wi], True)
                if p["invert"]["wheel"]:
                    raw = -raw
            hw_angle = float(p["wheel"]["hw_angle"])
            buttons = s["buttons"]
            gear = "N"
            for gname, idx in self.glob["shifter"].items():
                if idx is not None and 0 <= int(idx) < len(buttons) and buttons[int(idx)]:
                    gear = gname
                    break
            raw_pedals = {}
            for f in ("throttle", "brake", "clutch"):
                i = int(p["axes"].get(f, -1))
                if s["axes"] and 0 <= i < len(s["axes"]):
                    v = self.engine._norm_axis(i, s["axes"][i], False)
                    raw_pedals[f] = 1 - v if p["invert"][f] else v
                else:
                    raw_pedals[f] = 0.0
            b = self.ble
            info = {k: v for k, v in b.info.items() if k != "raw_part2"}
            if "mode" in info:
                info["mode_name"] = MODE_NAMES.get(info["mode"], str(info["mode"]))
            return {
                "usb": {"connected": s["connected"], "name": s["name"]},
                "axes": s["axes"], "buttons": buttons, "hat": s["hat"],
                "wheel_deg": raw * hw_angle / 2, "wheel": s["wheel"],
                "pedals": {f: s[f] for f in ("throttle", "brake", "clutch")}, "raw_pedals": raw_pedals,
                "ffb": s["ffb"], "compat": s["compat"], "preview": s.get("preview", False),
                "compat_error": s["compat_error"], "ffb_error": s["ffb_error"], "rumble": s["rumble"],
                "calibrating": s["calibrating"], "gear": gear,
                "shifter_extra": {k: (idx is not None and 0 <= int(idx) < len(buttons) and bool(buttons[int(idx)]))
                                  for k, idx in self.glob["shifter_extra"].items()},
                "ble": {"connected": b.connected, "busy": b.busy, "status": b.status, "info": info},
                "badges": self.badges, "detect": self._detect_text(), "message": self.message,
                "active": self.active, "auto_active": self.auto_active, "game": self.last_match,
                "device": self.current_device(s), "device_detected": self.detected_device(s),
                "svc": self.svc, "overlay_running": self.overlay.running(), "screen": self.overlay_screen,
                "preview_paused": self._preview_pause_reason(),
                "profile": self.prof, "glob": self._glob_public(), "profiles": self.profile_names(),
            }

    # ------------------------------------------------------------ alterar valores
    def set_value(self, path, value):
        """Altera um valor do perfil ativo (caminho como lista, ex.: ["hw", "angle"])."""
        with self.lock:
            path = list(path)
            _get(self.prof, path[:-1])  # valida o caminho
            _set(self.prof, path, value)
            if path[0] == "hw" and path[-1] not in ("apply", "pedals_on_wheel"):
                self._dirty("bt")
            elif path[0] in ("throttle", "brake", "clutch"):
                self._dirty("adj")
            self.engine.set_profile(self.prof)
            self._save_soon()
            return True

    def set_global(self, path, value):
        with self.lock:
            path = list(path)
            if path[0] not in ("device", "preview", "auto_switch", "hotspots", "shifter", "shifter_extra", "overlay", "accent", "zoom", "device_art"):
                raise ValueError("campo não permitido")
            if path[0] == "accent" and not (isinstance(value, str) and len(value) == 7 and value.startswith("#")
                                            and all(ch in "0123456789abcdefABCDEF" for ch in value[1:])):
                raise ValueError("Cor inválida.")
            node = self.glob
            for k in path[:-1]:
                node = node.setdefault(k, {})
            node[path[-1]] = value
            self._save_soon()
            return True

    def _dirty(self, key):
        if not any(j["badge"] == key for j in self.jobs):
            self.badges[key] = {"state": "dirty", "text": "Alterado, ainda não enviado ao volante"}

    # ------------------------------------------------------------ perfis
    def activate(self, name, manual=True):
        with self.lock:
            if name not in self.profiles:
                return False
            P.save_profile(self.prof)
            self.active = name
            if manual:
                self.manual_profile = name
                self.auto_active = False
            self.engine.set_profile(self.prof)
            self._save_soon()
            if self.prof["hw"]["apply"] and self.ble.connected:
                self.send_hw()
            return True

    def _unique(self, name):
        name = (name or "").strip()[:60]
        if not name:
            raise ValueError("Digite um nome.")
        base, k = name, 2
        while name in self.profiles:
            name = f"{base} ({k})"
            k += 1
        return name

    def profile_new(self, name):
        with self.lock:
            name = self._unique(name)
            self.profiles[name] = P.new_profile(name)
            P.save_profile(self.profiles[name])
            self.activate(name)
            return name

    def profile_duplicate(self, name):
        with self.lock:
            name = self._unique(name or self.active + " (cópia)")
            p = copy.deepcopy(self.prof)
            p["name"], p["exes"] = name, []
            self.profiles[name] = p
            P.save_profile(p)
            self.activate(name)
            return name

    def profile_rename(self, new, old=None):
        """Renomeia o perfil `old` (padrão: o ativo)."""
        with self.lock:
            old = old or self.active
            if old not in self.profiles:
                raise ValueError("Perfil não encontrado.")
            if old == "Padrão":
                raise ValueError("O perfil Padrão não pode ser renomeado.")
            if (new or "").strip() == old:
                return old
            new = self._unique(new)
            p = self.profiles.pop(old)
            P.delete_profile(old)
            p["name"] = new
            self.profiles[new] = p
            P.save_profile(p)
            if self.active == old:
                self.active = new
            if self.manual_profile == old:
                self.manual_profile = new
            if self.last_match == old:
                self.last_match = new
            self._save_soon()
            return new

    def profile_delete(self, name):
        with self.lock:
            if name == "Padrão":
                raise ValueError("O perfil Padrão não pode ser excluído.")
            self.profiles.pop(name, None)
            P.delete_profile(name)
            if self.active == name or self.active not in self.profiles:
                self.activate("Padrão")
            return True

    def exe_add(self, exe):
        with self.lock:
            exe = (exe or "").strip().lower()
            if exe and exe not in self.prof["exes"]:
                self.prof["exes"].append(exe)
                self._save_soon()
            return self.prof["exes"]

    def exe_remove(self, exe):
        with self.lock:
            if exe in self.prof["exes"]:
                self.prof["exes"].remove(exe)
                self._save_soon()
            return self.prof["exes"]

    def running_processes(self):
        names = set()
        for pr in psutil.process_iter(["name"]):
            n = (pr.info.get("name") or "").lower()
            if n.endswith(".exe"):
                names.add(n)
        return sorted(names)

    def export_to(self, path, names):
        with self.lock:
            self.save_now()
            names = [n for n in names if n in self.profiles] or [self.active]
            data = {"format": EXPORT_FORMAT, "version": 1, "app_version": APP_VERSION,
                    "profiles": [self.profiles[n] for n in names]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        return len(names)

    def import_from(self, paths):
        imported, errors = [], []
        for path in paths:
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as e:
                errors.append(f"{os.path.basename(path)}: arquivo inválido ({e})")
                continue
            items = data.get("profiles") if isinstance(data, dict) and "profiles" in data else [data]
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
                    errors.append(f"{os.path.basename(path)}: perfil sem nome ignorado")
                    continue
                with self.lock:
                    prof = P._merge(P.DEFAULT_PROFILE, item)
                    prof["exes"] = [str(x).strip().lower() for x in prof.get("exes", []) if str(x).strip()]
                    name = self._unique(prof["name"])
                    prof["name"] = name
                    self.profiles[name] = prof
                    P.save_profile(prof)
                    imported.append(name)
        if imported:
            self.activate(imported[0])
        return {"imported": imported, "errors": errors}

    # ------------------------------------------------------------ Bluetooth
    def ble_connect(self):
        fut = self.ble.connect()
        self.ble_after_connect = fut
        return True

    def ble_read(self):
        fut = self.ble.read_all()
        fut.add_done_callback(lambda f: self._pull_from_wheel())
        return True

    def ble_disconnect(self):
        self.ble.disconnect()
        return True

    def _pull_from_wheel(self):
        i = self.ble.info
        if "angle" not in i:
            return
        with self.lock:
            hw = self.prof["hw"]
            for k in ("angle", "ffb", "spring", "damper", "friction", "inertia", "reverse"):
                hw[k] = i[k]
            self.prof["wheel"]["hw_angle"] = int(i["angle"])
            self.prof["wheel"]["angle"] = int(i["angle"])
            self.badges["bt"] = {"state": "ok", "text": "Valores lidos do volante"}
            self.engine.set_profile(self.prof)
            self._save_soon()

    def _start_job(self, key, settings, curves, on_ok, label):
        with self.lock:
            if any(j["badge"] == key for j in self.jobs):
                return False
            label = label if self.ble.connected else "Conectando e enviando…"
            fut = self.ble.send_verified(settings, curves)
            self.jobs.append({"badge": key, "fut": fut, "t0": time.time(), "on_ok": on_ok,
                              "label": label, "profile": self.active})
            self.badges[key] = {"state": "pending", "text": f"{label} 0,0 s"}
            return True

    def send_hw(self):
        hw = self.prof["hw"]
        settings = {k: hw[k] for k in ("angle", "ffb", "reverse", "spring", "damper", "friction", "inertia")}

        def ok(prof):
            a = int(min(900, max(90, round(prof["hw"]["angle"] / 10) * 10)))
            prof["hw"]["angle"] = a
            prof["wheel"]["hw_angle"] = a
            prof["wheel"]["angle"] = a
        return self._start_job("bt", settings, {}, ok, "Enviando ao volante…")

    def send_pedals(self, linear=False):
        p = self.prof
        if linear:
            curves = {k: list(LINEAR_CURVE) for k in ("throttle", "brake", "clutch")}
        else:
            curves = {k: pedal_curve_points(p[k]["deadzone"], p[k]["saturation"], p[k]["gamma"])
                      for k in ("throttle", "brake", "clutch")}

        def ok(prof):
            if linear:
                for k in ("throttle", "brake", "clutch"):
                    prof[k].update(deadzone=0.0, saturation=1.0, gamma=1.0)
            prof["hw"]["pedals_on_wheel"] = True
        return self._start_job("adj", {}, curves, ok, "Enviando curvas ao volante…")

    def switch_mode(self, mode):
        if not self.ble.connected:
            raise ValueError("Conecte o volante pelo Bluetooth primeiro.")
        self.ble.switch_mode(int(mode))
        return True

    def factory_reset(self):
        if not self.ble.connected:
            raise ValueError("Conecte o volante pelo Bluetooth primeiro.")
        fut = self.ble.factory_reset()
        fut.add_done_callback(lambda f: self._pull_from_wheel())
        return True

    # ------------------------------------------------------------ testes, detecção, calibração
    def ffb_test(self, kind, direction=0):
        if kind == "push":
            self.engine.send("test_push", 1 if direction > 0 else -1)
        elif kind == "vibrate":
            self.engine.send("test_vibrate")
        elif kind == "spring":
            self.engine.send("test_spring")
        else:
            self.engine.send("stop_ffb")
        return True

    def start_detect(self, kind, target):
        s = self.engine.snapshot()
        if not s["connected"]:
            raise ValueError("Volante não conectado no USB.")
        base = list(s["axes"]) if kind == "axis" else list(s["buttons"])
        with self.lock:
            self.detect = {"kind": kind, "target": list(target), "base": base, "until": time.time() + 8}
        return True

    def cancel_detect(self):
        self.detect = None
        return True

    def _detect_text(self):
        d = self.detect
        if not d:
            return None
        left = max(0, d["until"] - time.time())
        if d["kind"] == "axis":
            return f"Mexa o pedal/volante até o fim… ({left:.0f} s)"
        return f"Aperte o botão no volante… ({left:.0f} s)"

    def _detect_tick(self, s):
        d = self.detect
        if not d:
            return
        if time.time() > d["until"]:
            self.detect = None
            self.message = "Nada detectado."
            return
        if d["kind"] == "axis" and s["axes"]:
            diffs = [abs(a - b) for a, b in zip(s["axes"], d["base"])]
            i = max(range(len(diffs)), key=diffs.__getitem__)
            if diffs[i] > 12000:
                self.prof["axes"][d["target"][0]] = i
                self.engine.set_profile(self.prof)
                self.message = f"Detectado: Eixo {i}."
                self.detect = None
                self._save_soon()
        elif d["kind"] == "button":
            for i, b in enumerate(s["buttons"]):
                if b and not (i < len(d["base"]) and d["base"][i]):
                    t = d["target"]
                    if t[0] == "xbox":
                        btns = self.prof["compat"]["buttons"]
                        for k, v in list(btns.items()):
                            if v == i:
                                btns[k] = None
                        btns[t[1]] = i
                    elif t[0] == "hotspot":
                        self.glob["hotspots"].setdefault(t[1], {})[t[2]] = i
                    elif t[0] == "extra":
                        self.glob["shifter_extra"][t[1]] = i
                    elif t[0] == "gear":
                        for k, v in list(self.glob["shifter"].items()):
                            if v == i:
                                self.glob["shifter"][k] = None
                        self.glob["shifter"][t[1]] = i
                    self.message = f"Detectado: Botão {i}."
                    self.detect = None
                    self._save_soon()
                    break

    def reset_mapping(self, device):
        """Volta os botões do volante, as marchas, o Park, a caixa alta/baixa e os botões de Xbox
        do perfil ativo ao padrão."""
        with self.lock:
            if device not in DEVICES:
                raise ValueError("Volante desconhecido.")
            self.glob["hotspots"][device] = dict(DEFAULT_HOTSPOTS.get(device, {}))
            self.glob["shifter"] = dict(DEFAULT_SHIFTER)
            self.glob["shifter_extra"] = dict(DEFAULT_SHIFTER_EXTRA)
            self.prof["compat"]["buttons"] = dict(P.DEFAULT_PROFILE["compat"]["buttons"])
            self.engine.set_profile(self.prof)
            self.detect = None
            self.message = "Mapeamento restaurado para o padrão."
            self._save_soon()
            return True

    def calibrate(self):
        self.engine.send("calibrate", 10)
        self.message = "Calibrando: gire o volante até os batentes e pise fundo nos pedais (10 s)."
        return True

    def install_vigem(self):
        msi = vigem_installer()
        if not msi:
            raise ValueError("Instalador do ViGEmBus não encontrado neste pacote.")
        subprocess.Popen(["msiexec", "/i", msi])
        return True

    def refresh_services(self):
        self.svc = {"vigem": _service_installed("ViGEmBus"), "hidhide": _service_installed("HidHide")}
        return self.svc

    # ------------------------------------------------------------ laço de fundo
    def _preview_pause_reason(self):
        if not self.glob["preview"]:
            return None
        if self.last_match:
            return "jogo aberto"
        if not getattr(self, "_fg", True):
            return "janela em segundo plano"
        return None

    def _watch_processes(self):
        while self.alive:
            try:
                self.running_exes = {(pr.info["name"] or "").lower() for pr in psutil.process_iter(["name"])}
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)

    def _auto_switch(self):
        if not self.glob.get("auto_switch", True):
            return
        match = None
        for n, p in self.profiles.items():
            if n != "Padrão" and self.running_exes & set(p["exes"]):
                match = n
                break
        if match == self.last_match:
            return
        if match:
            self.activate(match, manual=False)
            self.auto_active = True
        elif self.auto_active:
            self.auto_active = False
            self.activate(self.manual_profile if self.manual_profile in self.profiles else "Padrão", manual=False)
        self.last_match = match

    def _jobs_tick(self):
        for job in list(self.jobs):
            key, fut = job["badge"], job["fut"]
            secs = f"{time.time() - job['t0']:.1f}".replace(".", ",")
            if not fut.done():
                txt = "Confirmando com o volante…" if self.ble.status.startswith("confirmando") else job["label"]
                self.badges[key] = {"state": "pending", "text": f"{txt} {secs} s"}
                continue
            self.jobs.remove(job)
            res = fut.result()
            if res and res["ok"]:
                self.badges[key] = {"state": "ok",
                                    "text": f"Confirmado pelo volante em {res['tempo']:.1f} s".replace(".", ",")}
                if job["profile"] in self.profiles:
                    job["on_ok"](self.profiles[job["profile"]])
                    self.engine.set_profile(self.prof)
                    self._save_soon()
            elif res:
                nomes = ", ".join(FIELD_NAMES.get(k, k) for k in res["faltando"])
                self.badges[key] = {"state": "fail", "text": f"O volante não confirmou: {nomes}"}
            else:
                self.badges[key] = {"state": "fail", "text": f"Não enviado: {self.ble.status}"}

    def _overlay_tick(self, s):
        ov = self.glob["overlay"]
        if ov["enabled"]:
            if not self.overlay.running():
                self.overlay.start()
            for m in self.overlay.poll():
                if "screen" in m:
                    self.overlay_screen = m["screen"]
                if "pos" in m:
                    ov["x"], ov["y"] = int(m["pos"][0]), int(m["pos"][1])
                    self._save_soon()
            self.overlay.send({"v": {f: round(s[f], 4) for f in ("clutch", "brake", "throttle")},
                               "cfg": ov, "on": s["connected"]})
        elif self.overlay.running():
            self.overlay.stop()

    def _loop(self):
        last_overlay = 0.0
        while self.alive:
            try:
                s = self.engine.snapshot()
                with self.lock:
                    self._auto_switch()
                    self._jobs_tick()
                    self._detect_tick(s)
                    if self.ble_after_connect is not None and self.ble_after_connect.done():
                        self.ble_after_connect = None
                        if self.ble.connected:
                            if self.prof["hw"]["apply"]:
                                self.send_hw()
                            else:
                                self._pull_from_wheel()
                    self._fg = app_in_foreground()
                    on = bool(self.glob["preview"] and self._fg and not self.last_match)
                    if on != self.engine.preview:
                        self.engine.set_preview(on)
                    if self.save_at and time.time() > self.save_at:
                        self.save_now()
                    if not s["calibrating"] and self.message.startswith("Calibrando"):
                        self.message = "Calibração salva."
                        self._save_soon()
                t = time.time()
                if t - last_overlay > 1 / 30:
                    last_overlay = t
                    self._overlay_tick(s)
            except Exception as e:  # noqa: BLE001
                self.message = f"Erro interno: {e}"
            time.sleep(0.03)
