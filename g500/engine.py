"""Leitura do volante, processamento (zona morta/curvas/ângulo), force feedback
e controle de Xbox virtual. Tudo roda numa thread própria que é dona do SDL."""
import ctypes
import os
import queue
import threading
import time

import warnings
warnings.filterwarnings("ignore", message="Using SDL2 binaries")
import sdl2  # noqa: E402

G500_VID, G500_PID = 0x11FF, 0x2355
XBOX_VID = 0x045E
NUM_AXES_MAX = 8
HAPTIC_INF = sdl2.SDL_HAPTIC_INFINITY

try:
    import vgamepad as vg
except Exception:  # driver ViGEmBus ausente ou lib não instalada
    vg = None


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def process_wheel(v, cfg):
    """v em -1..1 -> -1..1 aplicando ângulo por software, zona morta e curva."""
    hw, ang = float(cfg["hw_angle"]), float(cfg["angle"])
    if 0 < ang < hw:
        v = v * hw / ang
    v = clamp(v, -1.0, 1.0)
    dz = float(cfg["deadzone"])
    a = abs(v)
    if a <= dz:
        return 0.0
    a = (a - dz) / (1.0 - dz) if dz < 1 else 0.0
    a = a ** float(cfg["gamma"])
    return a if v > 0 else -a


def process_pedal(v, cfg):
    """v em 0..1 -> 0..1 aplicando zona morta inicial, saturação e curva."""
    dz, sat = float(cfg["deadzone"]), float(cfg["saturation"])
    if sat <= dz:
        sat = dz + 0.01
    v = clamp((v - dz) / (sat - dz), 0.0, 1.0)
    return v ** float(cfg["gamma"])


class FFB:
    """Efeitos de force feedback via SDL Haptic (DirectInput por baixo)."""

    def __init__(self, joy):
        self.h = sdl2.SDL_HapticOpenFromJoystick(joy)
        if not self.h:
            raise RuntimeError(sdl2.SDL_GetError().decode(errors="ignore"))
        self.caps = sdl2.SDL_HapticQuery(self.h)
        self.ids = {}
        self.params = {}
        self.timed = {}  # efeito -> instante de parar

    def close(self):
        if self.h:
            sdl2.SDL_HapticStopAll(self.h)
            sdl2.SDL_HapticClose(self.h)
            self.h = None

    def set_gain(self, g):
        if self.caps & sdl2.SDL_HAPTIC_GAIN:
            sdl2.SDL_HapticSetGain(self.h, int(clamp(g, 0, 100)))

    def _upload(self, name, eff, run=True):
        if name in self.ids:
            sdl2.SDL_HapticUpdateEffect(self.h, self.ids[name], ctypes.byref(eff))
        else:
            eid = sdl2.SDL_HapticNewEffect(self.h, ctypes.byref(eff))
            if eid < 0:
                return
            self.ids[name] = eid
        if run:
            sdl2.SDL_HapticRunEffect(self.h, self.ids[name], 1)

    def _stop(self, name):
        if name in self.ids:
            sdl2.SDL_HapticStopEffect(self.h, self.ids[name])

    CONDITION_TYPES = {"spring": sdl2.SDL_HAPTIC_SPRING, "damper": sdl2.SDL_HAPTIC_DAMPER,
                       "friction": sdl2.SDL_HAPTIC_FRICTION, "inertia": sdl2.SDL_HAPTIC_INERTIA}

    def condition(self, kind, strength):
        """kind: spring (centralização), damper (peso), friction (atrito) ou inertia (inércia). 0..100."""
        key = (kind, int(strength))
        if self.params.get(kind) == key:
            return
        self.params[kind] = key
        if strength <= 0:
            self._stop(kind)
            return
        etype = self.CONDITION_TYPES[kind]
        if not self.caps & etype:
            return
        e = sdl2.SDL_HapticEffect()
        e.type = etype
        c = e.condition
        c.type = etype
        c.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
        c.direction.dir[0] = 1
        c.length = HAPTIC_INF
        coeff = int(32767 * strength / 100)
        c.right_sat[0] = c.left_sat[0] = 0xFFFF
        c.right_coeff[0] = c.left_coeff[0] = coeff
        c.deadband[0] = 0
        c.center[0] = 0
        self._upload(kind, e)

    def constant(self, level, ms):
        """level -1..1 (sinal = lado). ms = duração."""
        e = sdl2.SDL_HapticEffect()
        e.type = sdl2.SDL_HAPTIC_CONSTANT
        c = e.constant
        c.type = sdl2.SDL_HAPTIC_CONSTANT
        c.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
        c.direction.dir[0] = 1
        c.length = int(ms)
        c.level = int(clamp(level, -1, 1) * 32767)
        self._upload("constant", e)

    def vibrate(self, mag):
        """Vibração contínua 0..1 (0 = para)."""
        key = round(mag, 2)
        if self.params.get("sine") == key:
            return
        self.params["sine"] = key
        if mag <= 0.01:
            self._stop("sine")
            return
        e = sdl2.SDL_HapticEffect()
        e.type = sdl2.SDL_HAPTIC_SINE
        p = e.periodic
        p.type = sdl2.SDL_HAPTIC_SINE
        p.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
        p.direction.dir[0] = 1
        p.length = HAPTIC_INF
        p.period = 45
        p.magnitude = int(clamp(mag, 0, 1) * 32767)
        self._upload("sine", e)

    def stop_all(self):
        sdl2.SDL_HapticStopAll(self.h)
        self.params.clear()


class Engine(threading.Thread):
    def __init__(self, profile, calibration):
        super().__init__(daemon=True)
        self.profile = profile
        self.calibration = calibration  # {str(eixo): {"min":..,"max":..,"center":..}}
        self.cmds = queue.Queue()
        self.lock = threading.Lock()
        self.running = True
        self.state = {"connected": False, "name": "", "axes": [], "buttons": [], "hat": 0,
                      "wheel": 0.0, "throttle": 0.0, "brake": 0.0, "clutch": 0.0,
                      "ffb": False, "compat": False, "compat_error": "", "ffb_error": "",
                      "rumble": (0, 0), "calibrating": False, "preview": False}
        self.joy = None
        self.opened_at = 0.0
        self.ffb = None
        self.pad = None
        self.rumble = (0, 0)
        self.ffb_test_until = 0.0
        self.calib_until = 0.0
        self.calib_acc = None
        # "Sentir os ajustes": forças de referência, como um jogo mandaria. O volante as
        # modifica com o que foi gravado pelo Bluetooth (força, mola, amortecimento, ...).
        self.preview = False

    # Forças de referência do modo "Sentir os ajustes" (0..100), escaladas pelo volante.
    PREVIEW_FORCES = {"spring": 60, "damper": 45, "friction": 35, "inertia": 35}

    # ---------- API para a interface (thread-safe) ----------
    def set_profile(self, profile):
        self.profile = profile

    def set_preview(self, on):
        self.preview = bool(on)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def send(self, *cmd):
        self.cmds.put(cmd)

    def stop(self):
        self.running = False

    # ---------- dispositivo ----------
    def _open_joystick(self):
        best = None
        for i in range(sdl2.SDL_NumJoysticks()):
            vid = sdl2.SDL_JoystickGetDeviceVendor(i)
            pid = sdl2.SDL_JoystickGetDeviceProduct(i)
            if (vid, pid) == (G500_VID, G500_PID):
                best = i
                break
            name = (sdl2.SDL_JoystickNameForIndex(i) or b"").decode(errors="ignore").lower()
            if best is None and vid != XBOX_VID and "xbox" not in name:
                best = i
        if best is None:
            return
        self.joy = sdl2.SDL_JoystickOpen(best)
        self.opened_at = time.time()
        name = (sdl2.SDL_JoystickName(self.joy) or b"").decode(errors="ignore")
        with self.lock:
            self.state.update(connected=True, name=name)

    def _close_joystick(self):
        self._close_ffb()
        if self.joy:
            sdl2.SDL_JoystickClose(self.joy)
        self.joy = None
        with self.lock:
            self.state.update(connected=False, name="", axes=[], buttons=[])

    def _open_ffb(self):
        if self.ffb or not self.joy:
            return
        try:
            self.ffb = FFB(self.joy)
            err = ""
        except RuntimeError as e:
            self.ffb, err = None, str(e)
        with self.lock:
            self.state.update(ffb=self.ffb is not None, ffb_error=err)

    def _close_ffb(self):
        if self.ffb:
            self.ffb.close()
            self.ffb = None
        with self.lock:
            self.state["ffb"] = False

    # ---------- controle virtual ----------
    def _on_rumble(self, client, target, large_motor, small_motor, led_number, user_data):
        self.rumble = (large_motor, small_motor)

    def _open_pad(self):
        if self.pad:
            return
        if vg is None:
            with self.lock:
                self.state["compat_error"] = "Driver ViGEmBus/vgamepad não encontrado."
            return
        try:
            self.pad = vg.VX360Gamepad()
            self.pad.register_notification(callback_function=self._on_rumble)
            err = ""
        except Exception as e:  # noqa: BLE001
            self.pad, err = None, str(e)
        with self.lock:
            self.state.update(compat=self.pad is not None, compat_error=err)

    def _close_pad(self):
        if self.pad:
            try:
                self.pad.reset()
                self.pad.update()
            except Exception:  # noqa: BLE001
                pass
            del self.pad
            self.pad = None
            self.rumble = (0, 0)
        with self.lock:
            self.state["compat"] = False

    # ---------- processamento ----------
    def _norm_axis(self, idx, raw, centered):
        cal = self.calibration.get(str(idx))
        if centered:
            c = cal["center"] if cal else 0
            lo = cal["min"] if cal else -32768
            hi = cal["max"] if cal else 32767
            if raw >= c:
                return clamp((raw - c) / max(1, hi - c), 0, 1)
            return -clamp((c - raw) / max(1, c - lo), 0, 1)
        lo = cal["min"] if cal else -32768
        hi = cal["max"] if cal else 32767
        return clamp((raw - lo) / max(1, hi - lo), 0, 1)

    def _value(self, p, func, axes):
        idx = int(p["axes"].get(func, -1))
        if idx < 0 or idx >= len(axes):
            return 0.0
        if func == "wheel":
            v = self._norm_axis(idx, axes[idx], True)
            if p["invert"]["wheel"]:
                v = -v
            return process_wheel(v, p["wheel"])
        v = self._norm_axis(idx, axes[idx], False)
        if p["invert"][func]:
            v = 1 - v
        if p.get("hw", {}).get("pedals_on_wheel"):
            return v  # a curva já foi gravada no volante; não aplicar duas vezes
        return process_pedal(v, p[func])

    def _feed_pad(self, p, vals, buttons, hat):
        y = -vals["clutch"] if p["compat"]["clutch_to"] == "left_stick_y" else 0.0
        self.pad.left_joystick_float(x_value_float=clamp(vals["wheel"], -1, 1), y_value_float=y)
        self.pad.right_trigger_float(value_float=vals["throttle"])
        self.pad.left_trigger_float(value_float=vals["brake"])
        B = vg.XUSB_BUTTON
        names = {"A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B, "X": B.XUSB_GAMEPAD_X,
                 "Y": B.XUSB_GAMEPAD_Y, "LB": B.XUSB_GAMEPAD_LEFT_SHOULDER,
                 "RB": B.XUSB_GAMEPAD_RIGHT_SHOULDER, "BACK": B.XUSB_GAMEPAD_BACK,
                 "START": B.XUSB_GAMEPAD_START, "LS": B.XUSB_GAMEPAD_LEFT_THUMB,
                 "RS": B.XUSB_GAMEPAD_RIGHT_THUMB, "GUIDE": B.XUSB_GAMEPAD_GUIDE}
        mask = 0
        for xb, wb in p["compat"]["buttons"].items():
            if wb is not None and 0 <= int(wb) < len(buttons) and buttons[int(wb)]:
                mask |= int(names[xb])
        if hat & sdl2.SDL_HAT_UP:
            mask |= int(B.XUSB_GAMEPAD_DPAD_UP)
        if hat & sdl2.SDL_HAT_DOWN:
            mask |= int(B.XUSB_GAMEPAD_DPAD_DOWN)
        if hat & sdl2.SDL_HAT_LEFT:
            mask |= int(B.XUSB_GAMEPAD_DPAD_LEFT)
        if hat & sdl2.SDL_HAT_RIGHT:
            mask |= int(B.XUSB_GAMEPAD_DPAD_RIGHT)
        self.pad.report.wButtons = mask
        self.pad.update()

    def _handle_cmd(self, cmd):
        name = cmd[0]
        if name == "test_push":
            self.ffb_test_until = time.time() + 3
            self._open_ffb()
            if self.ffb:
                lvl = cmd[1] * (-1 if self.profile["ffb"]["invert"] else 1)
                self.ffb.constant(lvl * 0.6, 400)
        elif name == "test_vibrate":
            self.ffb_test_until = time.time() + 3
            self._open_ffb()
            if self.ffb:
                self.ffb.vibrate(0.6)
                self.ffb.timed["sine"] = time.time() + 1.0
        elif name == "test_spring":
            self.ffb_test_until = time.time() + 6
            self._open_ffb()
        elif name == "stop_ffb":
            if self.ffb:
                self.ffb.stop_all()
        elif name == "calibrate":
            self.calib_until = time.time() + cmd[1]
            self.calib_acc = None
            with self.lock:
                self.state["calibrating"] = True

    def run(self):
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_HAPTIC)
        ev = sdl2.SDL_Event()
        last_scan = 0.0
        while self.running:
            t = time.time()
            while sdl2.SDL_PollEvent(ctypes.byref(ev)):
                if ev.type == sdl2.SDL_JOYDEVICEREMOVED and self.joy and \
                        ev.jdevice.which == sdl2.SDL_JoystickInstanceID(self.joy):
                    self._close_joystick()
            if not self.joy and t - last_scan > 1.0:
                last_scan = t
                self._open_joystick()
            try:
                while True:
                    self._handle_cmd(self.cmds.get_nowait())
            except queue.Empty:
                pass

            p = self.profile
            # o volante só manda o primeiro relatório real um instante depois de aberto;
            # até lá o SDL devolve zeros, que pareceriam pedais pela metade
            if self.joy and t - self.opened_at < 1.0:
                time.sleep(0.01)
                continue
            if self.joy:
                sdl2.SDL_JoystickUpdate()
                na = min(sdl2.SDL_JoystickNumAxes(self.joy), NUM_AXES_MAX)
                axes = [sdl2.SDL_JoystickGetAxis(self.joy, i) for i in range(na)]
                buttons = [sdl2.SDL_JoystickGetButton(self.joy, i)
                           for i in range(sdl2.SDL_JoystickNumButtons(self.joy))]
                hat = sdl2.SDL_JoystickGetHat(self.joy, 0) if sdl2.SDL_JoystickNumHats(self.joy) else 0

                # calibração: registra mín/máx de cada eixo
                if self.calib_until:
                    if self.calib_acc is None:
                        self.calib_acc = [[a, a] for a in axes]
                    for i, a in enumerate(axes):
                        self.calib_acc[i][0] = min(self.calib_acc[i][0], a)
                        self.calib_acc[i][1] = max(self.calib_acc[i][1], a)
                    if t > self.calib_until:
                        wi = int(p["axes"].get("wheel", -1))
                        for i, (lo, hi) in enumerate(self.calib_acc):
                            if hi - lo > 2000:
                                center = axes[i] if i == wi else (lo + hi) // 2
                                self.calibration[str(i)] = {"min": lo, "max": hi, "center": center}
                        self.calib_until = 0.0
                        with self.lock:
                            self.state["calibrating"] = False

                vals = {f: self._value(p, f, axes) for f in ("wheel", "throttle", "brake", "clutch")}

                # controle virtual
                if p["compat"]["enabled"]:
                    self._open_pad()
                    if self.pad:
                        self._feed_pad(p, vals, buttons, hat)
                else:
                    self._close_pad()

                # force feedback
                program_ffb = p["ffb"]["app_control"] or p["compat"]["enabled"]
                preview = self.preview and not program_ffb
                want_ffb = program_ffb or preview or t < self.ffb_test_until
                if want_ffb:
                    self._open_ffb()
                elif self.ffb:
                    self._close_ffb()
                if self.ffb:
                    f = p["ffb"]
                    if preview:
                        # mesmo tipo de força que um jogo manda; o volante aplica os ajustes gravados
                        self.ffb.set_gain(100)
                        for kind, val in self.PREVIEW_FORCES.items():
                            self.ffb.condition(kind, val)
                    else:
                        self.ffb.set_gain(f["gain"])
                        self.ffb.condition("spring", f["spring"])
                        self.ffb.condition("damper", f["damper"])
                        self.ffb.condition("friction", 0)
                        self.ffb.condition("inertia", 0)
                    if self.pad:
                        large, small = self.rumble
                        mag = max(large, small * 0.6) / 255.0 * f["rumble"] / 100.0
                        self.ffb.vibrate(mag)
                    elif self.ffb.timed.get("sine", 0) and t > self.ffb.timed["sine"]:
                        self.ffb.timed.pop("sine")
                        self.ffb.vibrate(0)

                with self.lock:
                    self.state.update(axes=axes, buttons=buttons, hat=hat, rumble=self.rumble,
                                      preview=preview and self.ffb is not None, **vals)
            time.sleep(0.004)

        self._close_pad()
        self._close_joystick()
        sdl2.SDL_Quit()
