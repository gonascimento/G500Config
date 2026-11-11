"""Interface gráfica (tkinter) do G500 Config."""
import copy
import json
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

import psutil
import sv_ttk

from . import profiles as P
from .ble import LINEAR_CURVE, MODE_NAMES, MODES, WheelBLE, pedal_curve_points
from .engine import Engine, vg

APP_NAME = "G500 Config"
APP_VERSION = "2.0"
FUNCS = [("wheel", "Volante"), ("throttle", "Acelerador"), ("brake", "Freio"), ("clutch", "Embreagem")]
AXIS_CHOICES = ["Nenhum"] + [f"Eixo {i}" for i in range(8)]
BTN_CHOICES = ["—"] + [f"Botão {i}" for i in range(32)]
HIDHIDE_URL = "https://github.com/nefarius/HidHide/releases"
EXPORT_FORMAT = "g500config-perfis"

# Cores dos desenhos (canvas) para cada tema; os widgets usam o tema Sun Valley.
PALETTES = {
    "dark": {"bg": "#1c1c1c", "card": "#2b2b2b", "fg": "#f3f3f3", "muted": "#a0a0a0", "line": "#4a4a4a",
             "off": "#3a3a3a", "accent": "#57c8ff", "on": "#4cd964", "rim": "#e8e8e8", "hub": "#57c8ff",
             "list_bg": "#2b2b2b", "list_sel": "#2f5a7a", "sidebar": "#202020"},
    "light": {"bg": "#fafafa", "card": "#ffffff", "fg": "#1b1b1b", "muted": "#5f5f5f", "line": "#d0d0d0",
              "off": "#e6e6e6", "accent": "#005fb8", "on": "#0f9d58", "rim": "#2b2b2b", "hub": "#005fb8",
              "list_bg": "#ffffff", "list_sel": "#cfe4f7", "sidebar": "#f0f0f0"},
}
PEDAL_COLORS = {"clutch": "#2ecc71", "brake": "#ff5f57", "throttle": "#3d9bff"}


def resource(*parts):
    """Caminho de um arquivo empacotado (funciona no .py e no .exe do PyInstaller)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def vigem_installer():
    if vg is not None:
        p = os.path.join(os.path.dirname(vg.__file__), "win", "vigem", "install", "x64", "ViGEmBusSetup_x64.msi")
        if os.path.exists(p):
            return p
    p = resource("vgamepad", "win", "vigem", "install", "x64", "ViGEmBusSetup_x64.msi")
    return p if os.path.exists(p) else None


def vigem_installed():
    try:
        r = subprocess.run(["sc", "query", "ViGEmBus"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except OSError:
        return False


def get_path(d, path):
    for k in path:
        d = d[k]
    return d


def set_path(d, path, v):
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = v


def hidhide_installed():
    try:
        r = subprocess.run(["sc", "query", "HidHide"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except OSError:
        return False


FIELD_NAMES = {"angle": "ângulo", "ffb": "force feedback", "spring": "mola", "damper": "amortecimento",
               "friction": "atrito", "inertia": "inércia", "reverse": "inversão",
               "curve_throttle": "curva do acelerador", "curve_brake": "curva do freio",
               "curve_clutch": "curva da embreagem"}


class StatusBadge(ttk.Frame):
    """Ícone + texto do estado de um envio ao volante: enviando (gira, com contador
    de segundos), confirmado (✔ verde), falhou (✖ vermelho) ou alterado sem enviar (! laranja)."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.cv = tk.Canvas(self, width=22, height=22, highlightthickness=0)
        self.cv.pack(side="left", padx=(0, 6))
        self.lbl = ttk.Label(self, text="")
        self.lbl.pack(side="left")
        self.state, self.angle = "idle", 90

    def set(self, state, text=""):
        self.state = state
        self.lbl.configure(text=text)
        self.draw()

    def spin(self, text):
        self.angle = (self.angle - 24) % 360
        self.lbl.configure(text=text)
        self.draw()

    def draw(self):
        p, c = self.app.pal, self.cv
        c.delete("all")
        c.configure(bg=p["bg"])
        if self.state == "pending":
            c.create_oval(3, 3, 19, 19, outline=p["off"], width=3)
            c.create_arc(3, 3, 19, 19, start=self.angle, extent=110, style="arc", outline=p["accent"], width=3)
        elif self.state == "ok":
            c.create_oval(2, 2, 20, 20, fill="#2ecc71", outline="")
            c.create_line(6, 11, 10, 15, 16, 7, fill="white", width=2.5, capstyle="round", joinstyle="round")
        elif self.state == "fail":
            c.create_oval(2, 2, 20, 20, fill="#ff5f57", outline="")
            c.create_line(7, 7, 15, 15, fill="white", width=2.5, capstyle="round")
            c.create_line(15, 7, 7, 15, fill="white", width=2.5, capstyle="round")
        elif self.state == "dirty":
            c.create_oval(2, 2, 20, 20, fill="#f5a623", outline="")
            c.create_text(11, 11, text="!", fill="white", font=("Segoe UI", 10, "bold"))


class PageHost(ttk.Frame):
    """Área de conteúdo com páginas trocadas pela barra lateral (substitui o Notebook)."""

    def __init__(self, master, on_add):
        super().__init__(master)
        self.on_add = on_add
        self.pages = {}

    def add(self, frame, text):
        self.pages[text] = frame
        self.on_add(text)

    def show(self, text):
        for name, fr in self.pages.items():
            if name == text:
                fr.pack(fill="both", expand=True)
            else:
                fr.pack_forget()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — Kalkam G500")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1080, sw - 40), min(720, sh - 80)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h - 40) // 2)}")
        self.minsize(min(940, w), min(600, h))
        try:
            self.iconbitmap(default=resource("assets", "icone.ico"))
            self._icon_png = tk.PhotoImage(file=resource("assets", "icone.png"))
            self.iconphoto(True, self._icon_png)
        except tk.TclError:
            pass

        self.profiles = P.load_profiles()
        self.glob = P.load_global()
        self.theme = self.glob.get("theme", "dark")
        self.pal = PALETTES[self.theme]
        sv_ttk.set_theme(self.theme)
        self._style()
        self.active = self.glob.get("active_profile")
        if self.active not in self.profiles:
            self.active = "Padrão"
        self.manual_profile = self.active
        self.auto_active = False

        self.bindings = []  # (path, var, to_ui, from_ui)
        self.loading = False
        self.save_job = None
        self.detect = None
        self.running_exes = set()
        self.last_match = None

        self.engine = Engine(self.profiles[self.active], self.glob.setdefault("calibration", {}))
        self.engine.start()
        self.ble = WheelBLE()
        self.ble_pull = False
        self.jobs = []  # envios ao volante aguardando confirmação
        self.badges = []

        nb = self._build_shell()
        self._build_test(nb)
        self._build_hw(nb)
        self._build_settings(nb)
        self._build_ffb(nb)
        self._build_compat(nb)
        self._build_profiles(nb)
        self._load_profile_into_ui()
        page = self.glob.get("page")
        self._show_page(page if page in self.host.pages else "Teste ao vivo")
        self._apply_canvas_colors()

        threading.Thread(target=self._watch_processes, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(33, self._tick)

    # ------------------------------------------------------------------ util
    @property
    def prof(self):
        return self.profiles[self.active]

    def bind(self, path, var, to_ui=lambda v: v, from_ui=lambda v: v):
        self.bindings.append((path, var, to_ui, from_ui))

        def on_write(*_):
            if self.loading:
                return
            try:
                set_path(self.prof, path, from_ui(var.get()))
            except (tk.TclError, ValueError):
                return
            self._mark_dirty(path)
            self._schedule_save()
        var.trace_add("write", on_write)
        return var

    def slider(self, parent, row, label, path, lo, hi, fmt="{:.0f}", to_ui=lambda v: v,
               from_ui=lambda v: v, hint=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        var = tk.DoubleVar()
        ttk.Scale(parent, from_=lo, to=hi, variable=var, length=190).grid(row=row, column=1, sticky="we", padx=4)
        lbl = ttk.Label(parent, width=8)
        lbl.grid(row=row, column=2, sticky="w")
        var.trace_add("write", lambda *_: lbl.configure(text=fmt.format(var.get())))
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(row=row, column=3, sticky="w", padx=4)
        return self.bind(path, var, to_ui, from_ui)

    def _schedule_save(self):
        if self.save_job:
            self.after_cancel(self.save_job)
        self.save_job = self.after(600, self._save_now)

    def _save_now(self):
        self.save_job = None
        P.save_profile(self.prof)
        self.glob["active_profile"] = self.manual_profile
        P.save_global(self.glob)

    def _load_profile_into_ui(self):
        self.loading = True
        try:
            for path, var, to_ui, _ in self.bindings:
                var.set(to_ui(get_path(self.prof, path)))
        finally:
            self.loading = False
        self.profile_var.set(self.active)
        self._refresh_profile_lists()

    def activate(self, name, manual=True):
        if name not in self.profiles:
            return
        if self.save_job:
            self.after_cancel(self.save_job)
            self._save_now()
        self.active = name
        if manual:
            self.manual_profile = name
            self.auto_active = False
        self.engine.set_profile(self.prof)
        self._load_profile_into_ui()
        self._schedule_save()
        if self.prof["hw"]["apply"] and self.ble.connected:
            self._hw_send()

    # ------------------------------------------------------------ estrutura
    NAV_ICONS = {"Teste ao vivo": "◎", "Volante (Bluetooth)": "⟲", "Ajustes": "☰",
                 "Force feedback": "≋", "Compatibilidade": "⇄", "Perfis": "★"}

    def _style(self):
        st = ttk.Style(self)
        st.configure("Title.TLabel", font=("Segoe UI Semibold", 12))
        st.configure("PageTitle.TLabel", font=("Segoe UI Semibold", 20))
        st.configure("Brand.TLabel", font=("Segoe UI Semibold", 15))
        st.configure("Hint.TLabel", foreground=self.pal["muted"], font=("Segoe UI", 9))
        st.configure("Status.TLabel", font=("Segoe UI", 10))
        st.configure("Nav.Toggle.TButton", anchor="w", padding=(14, 9), font=("Segoe UI", 10))
        st.configure("Sidebar.TFrame", background=self.pal["sidebar"])
        st.configure("Sidebar.TLabel", background=self.pal["sidebar"])
        st.configure("SidebarHint.TLabel", background=self.pal["sidebar"], foreground=self.pal["muted"],
                     font=("Segoe UI", 9))
        st.configure("SidebarBrand.TLabel", background=self.pal["sidebar"], font=("Segoe UI Semibold", 15))

    def _build_shell(self):
        side = ttk.Frame(self, style="Sidebar.TFrame", padding=(12, 16))
        side.pack(side="left", fill="y")
        brand = ttk.Frame(side, style="Sidebar.TFrame")
        brand.pack(fill="x", pady=(0, 18))
        try:
            self._icon_small = tk.PhotoImage(file=resource("assets", "icone.png")).subsample(6, 6)
            ttk.Label(brand, image=self._icon_small, style="Sidebar.TLabel").pack(side="left", padx=(2, 10))
        except tk.TclError:
            pass
        txt = ttk.Frame(brand, style="Sidebar.TFrame")
        txt.pack(side="left")
        ttk.Label(txt, text=APP_NAME, style="SidebarBrand.TLabel").pack(anchor="w")
        ttk.Label(txt, text="Kalkam G500", style="SidebarHint.TLabel").pack(anchor="w")

        self.page_var = tk.StringVar()
        self.nav = ttk.Frame(side, style="Sidebar.TFrame")
        self.nav.pack(fill="x")

        bottom = ttk.Frame(side, style="Sidebar.TFrame")
        bottom.pack(side="bottom", fill="x")
        self.theme_var = tk.BooleanVar(value=self.theme == "dark")
        ttk.Checkbutton(bottom, text="Tema escuro", style="Switch.TCheckbutton", variable=self.theme_var,
                        command=self._toggle_theme).pack(anchor="w", pady=(0, 6))
        ttk.Label(bottom, text=f"versão {APP_VERSION}", style="SidebarHint.TLabel").pack(anchor="w")

        main = ttk.Frame(self, padding=(20, 14, 20, 14))
        main.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(main)
        top.pack(fill="x", pady=(0, 10))
        self.page_title = ttk.Label(top, text="", style="PageTitle.TLabel")
        self.page_title.pack(side="left")
        pf = ttk.Frame(top)
        pf.pack(side="right")
        ttk.Label(pf, text="Perfil", style="Hint.TLabel").pack(side="left", padx=(0, 6))
        self.profile_var = tk.StringVar()
        self.profile_cb = ttk.Combobox(pf, textvariable=self.profile_var, state="readonly", width=24)
        self.profile_cb.pack(side="left")
        self.profile_cb.bind("<<ComboboxSelected>>", lambda e: self.activate(self.profile_var.get()))
        self.auto_lbl = ttk.Label(pf, text="", style="Hint.TLabel")
        self.auto_lbl.pack(side="left", padx=8)

        bar = ttk.Frame(main)
        bar.pack(fill="x", pady=(0, 12))
        self.status_dot = tk.Canvas(bar, width=12, height=12, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(2, 8))
        self.status_lbl = ttk.Label(bar, text="Procurando volante…", style="Status.TLabel")
        self.status_lbl.pack(side="left")
        self.preview_var = tk.BooleanVar(value=self.glob.get("preview", True))
        ttk.Checkbutton(bar, text="Sentir os ajustes", style="Switch.TCheckbutton", variable=self.preview_var,
                        command=self._preview_changed).pack(side="right")
        self.preview_lbl = ttk.Label(bar, text="", style="Hint.TLabel")
        self.preview_lbl.pack(side="right", padx=10)
        ttk.Separator(main).pack(fill="x", pady=(0, 12))

        self.host = PageHost(main, self._add_nav)
        self.host.pack(fill="both", expand=True)
        return self.host

    def _add_nav(self, text):
        ttk.Radiobutton(self.nav, text=f"  {self.NAV_ICONS.get(text, '•')}   {text}", value=text,
                        variable=self.page_var, style="Nav.Toggle.TButton",
                        command=lambda: self._show_page(text)).pack(fill="x", pady=2)

    def _show_page(self, text):
        self.page_var.set(text)
        self.page_title.configure(text=text)
        self.host.show(text)
        self.glob["page"] = text

    def _preview_changed(self):
        self.glob["preview"] = self.preview_var.get()
        self._schedule_save()
        if self.preview_var.get() and not self.glob.get("preview_explained"):
            self.glob["preview_explained"] = True
            messagebox.showinfo("Sentir os ajustes", (
                "Os ajustes gravados no volante (força, mola, amortecimento, atrito, inércia e ângulo) "
                "modificam as forças que o JOGO manda. Fora de um jogo o volante fica solto.\n\n"
                "Com esta opção ligada, enquanto a janela do G500 Config estiver em primeiro plano, o "
                "programa manda forças de referência, como um jogo, para você sentir o efeito dos ajustes.\n\n"
                "Ao trocar de janela ou abrir um jogo cadastrado, o programa solta o volante para o jogo usar."))

    def _preview_tick(self):
        focused = self.focus_displayof() is not None and self.state() != "iconic"
        on = bool(self.preview_var.get() and focused and not self.last_match)
        if on != self.engine.preview:
            self.engine.set_preview(on)
        s = self.engine.snapshot()
        if s.get("preview"):
            txt = "motor ligado: sentindo os ajustes do volante"
        elif self.preview_var.get() and not focused:
            txt = "pausado (janela em segundo plano)"
        elif self.preview_var.get() and self.last_match:
            txt = "pausado (jogo aberto)"
        else:
            txt = ""
        if self.preview_lbl.cget("text") != txt:
            self.preview_lbl.configure(text=txt)

    def _toggle_theme(self):
        self.theme = "dark" if self.theme_var.get() else "light"
        self.pal = PALETTES[self.theme]
        sv_ttk.set_theme(self.theme)
        self._style()
        self._apply_canvas_colors()
        self.glob["theme"] = self.theme
        self._schedule_save()

    def _apply_canvas_colors(self):
        p = self.pal
        for cv in (self.wheel_cv, self.pedal_cv, self.axes_cv, self.btn_cv, self.status_dot):
            cv.configure(bg=p["bg"])
        for lb in (self.prof_list, self.exe_list):
            lb.configure(bg=p["list_bg"], fg=p["fg"], selectbackground=p["list_sel"], selectforeground=p["fg"],
                         highlightthickness=1, highlightbackground=p["line"], highlightcolor=p["accent"],
                         relief="flat", borderwidth=0, font=("Segoe UI", 10), activestyle="none")
        self._draw_status_dot(getattr(self, "_status_color", p["muted"]))
        for b in self.badges:
            b.draw()

    def _draw_status_dot(self, color):
        self._status_color = color
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 11, 11, fill=color, outline="")

    # ------------------------------------------------------------- aba teste
    def _build_test(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Teste ao vivo")
        wf = ttk.LabelFrame(f, text="Volante", padding=8)
        wf.grid(row=0, column=0, rowspan=2, sticky="n", padx=6, pady=6)
        self.wheel_cv = tk.Canvas(wf, width=280, height=280, highlightthickness=0)
        self.wheel_cv.pack()
        self.wheel_deg = ttk.Label(wf, text="", style="Title.TLabel")
        self.wheel_deg.pack(pady=(6, 0))

        pf = ttk.LabelFrame(f, text="Pedais (valor final)", padding=8)
        pf.grid(row=0, column=1, sticky="n", padx=6, pady=6)
        self.pedal_cv = tk.Canvas(pf, width=230, height=200, highlightthickness=0)
        self.pedal_cv.pack()

        af = ttk.LabelFrame(f, text="Eixos brutos", padding=8)
        af.grid(row=0, column=2, sticky="n", padx=6, pady=6)
        self.axes_cv = tk.Canvas(af, width=250, height=200, highlightthickness=0)
        self.axes_cv.pack()

        bf = ttk.LabelFrame(f, text="Botões e direcional", padding=8)
        bf.grid(row=1, column=1, columnspan=2, sticky="we", padx=6, pady=6)
        self.btn_cv = tk.Canvas(bf, width=520, height=96, highlightthickness=0)
        self.btn_cv.pack()
        self.rumble_lbl = ttk.Label(f, text="", style="Hint.TLabel")
        self.rumble_lbl.grid(row=2, column=1, columnspan=2, sticky="w")

    def _draw_test(self, s):
        cv = self.wheel_cv
        cv.delete("all")
        cx, cy, r = 130, 130, 105
        hw = float(self.prof["wheel"]["hw_angle"])
        wi = int(self.prof["axes"]["wheel"])
        raw = 0.0
        if s["axes"] and 0 <= wi < len(s["axes"]):
            raw = self.engine._norm_axis(wi, s["axes"][wi], True)
            if self.prof["invert"]["wheel"]:
                raw = -raw
        deg = raw * hw / 2
        p = self.pal
        cv.create_arc(cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12, start=90, extent=-deg,
                      style="arc", outline=p["accent"], width=4)
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, width=16, outline=p["rim"])
        for base in (90, 210, 330):
            a = math.radians(base - deg)
            cv.create_line(cx, cy, cx + r * math.cos(a), cy - r * math.sin(a), width=10, fill=p["rim"],
                           capstyle="round")
        a = math.radians(90 - deg)
        cv.create_oval(cx + r * math.cos(a) - 8, cy - r * math.sin(a) - 8,
                       cx + r * math.cos(a) + 8, cy - r * math.sin(a) + 8, fill="#ffc400", outline="")
        cv.create_oval(cx - 26, cy - 26, cx + 26, cy + 26, fill=p["hub"], outline="")
        self.wheel_deg.configure(text=f"{deg:+.0f}°   ·   saída {s['wheel']:+.2f}")

        cv = self.pedal_cv
        cv.delete("all")
        for i, (key, name) in enumerate([("clutch", "Embreagem"), ("brake", "Freio"), ("throttle", "Acelerador")]):
            x = 22 + i * 72
            cv.create_rectangle(x, 24, x + 40, 170, fill=p["off"], outline="")
            h = 146 * s[key]
            cv.create_rectangle(x, 170 - h, x + 40, 170, fill=PEDAL_COLORS[key], outline="")
            cv.create_text(x + 20, 188, text=name, font=("Segoe UI", 8), fill=p["muted"])
            cv.create_text(x + 20, 11, text=f"{s[key] * 100:.0f}%", font=("Segoe UI Semibold", 9), fill=p["fg"])

        cv = self.axes_cv
        cv.delete("all")
        for i, a in enumerate(s["axes"]):
            y = 8 + i * 26
            cv.create_text(4, y + 8, text=f"Eixo {i}", anchor="w", font=("Segoe UI", 8), fill=p["muted"])
            cv.create_rectangle(52, y + 2, 242, y + 14, fill=p["off"], outline="")
            w = 190 * (a + 32768) / 65535
            cv.create_rectangle(52, y + 2, 52 + w, y + 14, fill=p["accent"], outline="")
            cv.create_text(147, y + 8, text=str(a), font=("Segoe UI", 7), fill=p["fg"])

        cv = self.btn_cv
        cv.delete("all")
        for i, b in enumerate(s["buttons"]):
            x, y = 16 + (i % 16) * 32, 18 + (i // 16) * 34
            cv.create_oval(x - 12, y - 12, x + 12, y + 12, fill=p["on"] if b else p["off"], outline="")
            cv.create_text(x, y, text=str(i), font=("Segoe UI", 8), fill="#ffffff" if b else p["fg"])
        hat = s["hat"]
        dirs = [n for bit, n in ((1, "cima"), (2, "direita"), (4, "baixo"), (8, "esquerda")) if hat & bit]
        cv.create_text(4, 84, anchor="w", text="Direcional: " + (" + ".join(dirs) or "solto"),
                       font=("Segoe UI", 9), fill=p["muted"])
        if s["compat"]:
            self.rumble_lbl.configure(text=f"Vibração vinda do jogo: {s['rumble'][0]} / {s['rumble'][1]}")
        else:
            self.rumble_lbl.configure(text="")

    # ------------------------------------------------- aba volante (bluetooth)
    def _build_hw(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Volante (Bluetooth)")
        top = ttk.Frame(f)
        top.grid(row=0, column=0, columnspan=2, sticky="we")
        ttk.Button(top, text="Conectar", command=self._hw_connect).pack(side="left", padx=2)
        ttk.Button(top, text="Ler do volante", command=self._hw_read).pack(side="left", padx=2)
        ttk.Button(top, text="Desconectar", command=self.ble.disconnect).pack(side="left", padx=2)
        self.hw_status = ttk.Label(top, text="", style="Title.TLabel")
        self.hw_status.pack(side="left", padx=12)
        self.hw_info = ttk.Label(f, text="", style="Hint.TLabel")
        self.hw_info.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 6))

        pf = ttk.LabelFrame(f, text="Ângulo e forças (gravados no volante)", padding=6)
        pf.grid(row=2, column=0, sticky="nwe", padx=4)
        self.slider(pf, 0, "Ângulo de rotação", ("hw", "angle"), 90, 900, "{:.0f}°", float,
                    lambda v: int(round(v / 10) * 10))
        for r, (key, name) in enumerate((("ffb", "Force feedback"), ("spring", "Mola (centralização)"),
                                         ("damper", "Amortecimento"), ("friction", "Atrito"),
                                         ("inertia", "Inércia")), start=1):
            self.slider(pf, r, name, ("hw", key), 0, 100, "{:.0f}", float, int)
        rv = tk.BooleanVar()
        ttk.Checkbutton(pf, text="Inverter force feedback", variable=rv).grid(row=6, column=0, sticky="w", pady=2)
        self.bind(("hw", "reverse"), rv)
        av = tk.BooleanVar()
        ttk.Checkbutton(pf, text="Enviar ao volante sempre que este perfil for ativado",
                        variable=av).grid(row=7, column=0, columnspan=3, sticky="w")
        self.bind(("hw", "apply"), av)
        sb = ttk.Frame(pf)
        sb.grid(row=8, column=0, columnspan=3, sticky="w", pady=6)
        ttk.Button(sb, text="Enviar ao volante", style="Accent.TButton", command=self._hw_send).pack(side="left")
        self.bt_badge = StatusBadge(sb, self)
        self.bt_badge.pack(side="left", padx=10)
        self.badges.append(self.bt_badge)

        cf = ttk.LabelFrame(f, text="Curva dos pedais", padding=6)
        cf.grid(row=2, column=1, sticky="nwe", padx=4)
        ttk.Label(cf, style="Hint.TLabel", wraplength=330, text=(
            "A zona morta, a saturação e a curva de cada pedal ficam na página Ajustes. "
            "O botão \"Enviar ao volante\" de lá grava tudo no próprio volante.")).pack(anchor="w")
        ttk.Button(cf, text="Ir para Ajustes", command=lambda: self._show_page("Ajustes")).pack(anchor="w", pady=6)

        mf = ttk.LabelFrame(f, text="Modo USB do volante", padding=6)
        mf.grid(row=3, column=1, sticky="nwe", padx=4, pady=6)
        ttk.Label(mf, style="Hint.TLabel", wraplength=380, text=(
            "PC DInput: volante de verdade, com force feedback (padrão). PC XInput: o volante se apresenta "
            "como controle de Xbox; pode ajudar em jogos como Dirt 5 e Forza, sem o controle virtual.")).pack(anchor="w")
        bb = ttk.Frame(mf)
        bb.pack(anchor="w", pady=4)
        for m, name in MODES.items():
            ttk.Button(bb, text=f"Mudar para {name}", command=lambda m=m: self._hw_mode(m)).pack(side="left", padx=2)

        rf = ttk.LabelFrame(f, text="Avançado", padding=6)
        rf.grid(row=3, column=0, sticky="nwe", padx=4, pady=6)
        ttk.Button(rf, text="Restaurar padrão de fábrica", command=self._hw_reset).pack(anchor="w")
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

    def _hw_connect(self):
        fut = self.ble.connect()
        fut.add_done_callback(lambda _f: setattr(self, "ble_pull", "connect"))

    def _hw_read(self):
        fut = self.ble.read_all()
        fut.add_done_callback(lambda _f: setattr(self, "ble_pull", "read"))

    def _hw_pull_into_profile(self):
        i = self.ble.info
        if "angle" not in i:
            return
        hw = self.prof["hw"]
        for k in ("angle", "ffb", "spring", "damper", "friction", "inertia", "reverse"):
            hw[k] = i[k]
        self._sync_hw_angle(i["angle"])
        self._load_profile_into_ui()
        self._schedule_save()

    def _sync_hw_angle(self, angle):
        w = self.prof["wheel"]
        w["hw_angle"] = int(angle)
        if w["angle"] > angle:
            w["angle"] = int(angle)

    # ------------------------------------- envio com confirmação (Bluetooth)
    def _start_verified(self, badge, settings, curves, on_ok, label):
        if any(j["badge"] is badge for j in self.jobs):
            return  # já tem um envio em andamento para este botão
        label = label if self.ble.connected else "Conectando e enviando…"
        fut = self.ble.send_verified(settings, curves)
        self.jobs.append({"badge": badge, "fut": fut, "t0": time.time(), "on_ok": on_ok, "label": label,
                          "profile": self.active})
        badge.set("pending", f"{label} 0,0 s")

    def _jobs_tick(self):
        for job in list(self.jobs):
            badge, fut = job["badge"], job["fut"]
            secs = f"{time.time() - job['t0']:.1f}".replace(".", ",")
            if not fut.done():
                txt = "Confirmando com o volante…" if self.ble.status.startswith("confirmando") else job["label"]
                badge.spin(f"{txt} {secs} s")
                continue
            self.jobs.remove(job)
            res = fut.result()
            if res and res["ok"]:
                badge.set("ok", f"Confirmado pelo volante em {res['tempo']:.1f} s".replace(".", ","))
                if job["profile"] in self.profiles:
                    job["on_ok"](self.profiles[job["profile"]])
            elif res:
                nomes = ", ".join(FIELD_NAMES.get(k, k) for k in res["faltando"])
                badge.set("fail", f"O volante não confirmou: {nomes}")
            else:
                badge.set("fail", f"Não enviado: {self.ble.status}")

    def _mark_dirty(self, path):
        if path[0] in ("throttle", "brake", "clutch") or tuple(path) == ("wheel", "angle"):
            badge = getattr(self, "adj_badge", None)
        elif path[0] == "hw" and path[1] != "apply":
            badge = getattr(self, "bt_badge", None)
        else:
            return
        if badge and not any(j["badge"] is badge for j in self.jobs):
            badge.set("dirty", "Alterado, ainda não enviado ao volante")

    def _hw_send(self):
        hw = self.prof["hw"]
        settings = {k: hw[k] for k in ("angle", "ffb", "reverse", "spring", "damper", "friction", "inertia")}

        def ok(prof):
            a = int(min(900, max(90, round(prof["hw"]["angle"] / 10) * 10)))
            prof["hw"]["angle"] = a
            prof["wheel"]["hw_angle"] = a
            prof["wheel"]["angle"] = a
            self._after_hw_change()
        self._start_verified(self.bt_badge, settings, {}, ok, "Enviando ao volante…")

    def _after_hw_change(self):
        self._load_profile_into_ui()
        self._schedule_save()

    def _adj_send(self, linear=False):
        p = self.prof
        angle = int(min(900, max(90, round(p["wheel"]["angle"] / 10) * 10)))
        if linear:
            curves = {k: list(LINEAR_CURVE) for k in ("throttle", "brake", "clutch")}
        else:
            curves = {k: pedal_curve_points(p[k]["deadzone"], p[k]["saturation"], p[k]["gamma"])
                      for k in ("throttle", "brake", "clutch")}

        def ok(prof):
            prof["hw"]["angle"] = angle
            prof["wheel"]["hw_angle"] = angle
            prof["wheel"]["angle"] = angle
            if linear:
                for k in ("throttle", "brake", "clutch"):
                    prof[k].update(deadzone=0.0, saturation=1.0, gamma=1.0)
            # as curvas agora estão no volante: o programa não aplica de novo por cima
            prof["hw"]["pedals_on_wheel"] = True
            self._after_hw_change()
        self._start_verified(self.adj_badge, {"angle": angle}, curves, ok, "Enviando ao volante…")

    def _hw_mode(self, mode):
        if not self.ble.connected:
            messagebox.showinfo("Volante", "Conecte o volante pelo Bluetooth primeiro (botão Conectar).")
            return
        if messagebox.askyesno("Modo USB", f"Mudar o volante para {MODES[mode]}?\n\n"
                               "O volante vai se reconectar no USB com outra identidade. "
                               "Dá para voltar a qualquer momento por aqui."):
            self.ble.switch_mode(mode)

    def _hw_reset(self):
        if not self.ble.connected:
            messagebox.showinfo("Volante", "Conecte o volante pelo Bluetooth primeiro (botão Conectar).")
            return
        if messagebox.askyesno("Padrão de fábrica", "Restaurar todas as configurações do volante para o "
                               "padrão de fábrica (ângulo, forças, botões e curvas)?"):
            fut = self.ble.factory_reset()
            fut.add_done_callback(lambda _f: setattr(self, "ble_pull", "read"))

    def _hw_tick(self):
        b = self.ble
        # o topo mostra só a conexão; o resultado de cada envio aparece no indicador ao lado do botão
        if b.connected:
            txt = "Bluetooth conectado"
        elif b.busy:
            txt = b.status if b.status.endswith("…") else "conectando…"
        else:
            txt = b.status if b.status.startswith(("erro", "volante não")) else "Bluetooth desconectado"
        if self.hw_status.cget("text") != txt:
            self.hw_status.configure(text=txt)
        i = b.info
        if b.connected and "mode" in i:
            self.hw_info.configure(text=f"{i.get('name', '')}  •  modo {MODE_NAMES.get(i['mode'], i['mode'])}  •  "
                                        f"firmware {i.get('version')}  •  ângulo atual {i.get('angle')}°")
        else:
            self.hw_info.configure(text="Ligue o Bluetooth do PC e clique em Conectar. "
                                        "Feche o app do celular antes (o volante aceita uma conexão por vez).")
        if self.ble_pull:
            kind, self.ble_pull = self.ble_pull, False
            if b.connected:
                if kind == "connect" and self.prof["hw"]["apply"]:
                    self._hw_send()
                else:
                    self._hw_pull_into_profile()

    # ---------------------------------------------------------- aba ajustes
    def _build_settings(self, nb):
        outer = ttk.Frame(nb, padding=10)
        nb.add(outer, text="Ajustes")

        ef = ttk.LabelFrame(outer, text="Eixos (qual peça do volante faz o quê)", padding=6)
        ef.grid(row=0, column=0, sticky="nwe", padx=4, pady=4)
        for r, (key, name) in enumerate(FUNCS):
            ttk.Label(ef, text=name).grid(row=r, column=0, sticky="w", padx=4, pady=2)
            v = tk.StringVar()
            ttk.Combobox(ef, textvariable=v, values=AXIS_CHOICES, state="readonly", width=9).grid(row=r, column=1)
            self.bind(("axes", key), v, lambda i: AXIS_CHOICES[int(i) + 1],
                      lambda s: AXIS_CHOICES.index(s) - 1)
            iv = tk.BooleanVar()
            ttk.Checkbutton(ef, text="Inverter", variable=iv).grid(row=r, column=2, padx=4)
            self.bind(("invert", key), iv)
            ttk.Button(ef, text="Detectar", width=9,
                       command=lambda k=key, n=name: self._start_detect_axis(k, n)).grid(row=r, column=3)
        ttk.Button(ef, text="Calibrar (10 s)", command=self._calibrate).grid(row=5, column=0, columnspan=2,
                                                                             sticky="w", pady=(8, 0))
        self.calib_lbl = ttk.Label(ef, text="", style="Hint.TLabel")
        self.calib_lbl.grid(row=6, column=0, columnspan=4, sticky="w")

        wf = ttk.LabelFrame(outer, text="Volante", padding=6)
        wf.grid(row=0, column=1, sticky="nwe", padx=4, pady=4)
        ttk.Label(wf, text="Ângulo físico").grid(row=0, column=0, sticky="w", padx=4)
        hv = tk.IntVar()
        ttk.Spinbox(wf, from_=90, to=1080, increment=90, textvariable=hv, width=7).grid(row=0, column=1, sticky="w")
        self.bind(("wheel", "hw_angle"), hv, int, int)
        self.slider(wf, 1, "Ângulo desejado", ("wheel", "angle"), 90, 900, "{:.0f}°", float, lambda v: round(v / 10) * 10)
        self.slider(wf, 2, "Zona morta", ("wheel", "deadzone"), 0, 30, "{:.0f}%", lambda v: v * 100, lambda v: v / 100)
        self.slider(wf, 3, "Curva", ("wheel", "gamma"), 0.4, 3.0, "{:.2f}")
        ttk.Label(wf, text="Curva < 1 = mais sensível no centro; > 1 = mais suave no centro.",
                  style="Hint.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", padx=4)

        for i, (key, name) in enumerate(FUNCS[1:]):
            pf = ttk.LabelFrame(outer, text=name, padding=6)
            pf.grid(row=1 + i // 2, column=i % 2, sticky="nwe", padx=4, pady=4)
            self.slider(pf, 0, "Zona morta", (key, "deadzone"), 0, 40, "{:.0f}%", lambda v: v * 100, lambda v: v / 100)
            self.slider(pf, 1, "Saturação", (key, "saturation"), 50, 100, "{:.0f}%", lambda v: v * 100, lambda v: v / 100)
            self.slider(pf, 2, "Curva", (key, "gamma"), 0.4, 3.0, "{:.2f}")

        sf = ttk.LabelFrame(outer, text="Gravar no volante (Bluetooth)", padding=8)
        sf.grid(row=2, column=1, sticky="nwe", padx=4, pady=4)
        ttk.Label(sf, style="Hint.TLabel", wraplength=360, text=(
            "Grava no próprio volante o ângulo desejado e a zona morta, a saturação e a curva dos três "
            "pedais. Assim valem em qualquer jogo, inclusive sem o modo compatibilidade.")).pack(anchor="w")
        bb = ttk.Frame(sf)
        bb.pack(anchor="w", pady=(8, 4))
        ttk.Button(bb, text="Enviar ao volante", style="Accent.TButton", command=self._adj_send).pack(side="left")
        ttk.Button(bb, text="Pedais lineares (padrão)",
                   command=lambda: self._adj_send(linear=True)).pack(side="left", padx=6)
        self.adj_badge = StatusBadge(sf, self)
        self.adj_badge.pack(anchor="w", pady=(4, 0))
        self.badges.append(self.adj_badge)

        note = ("Sem enviar ao volante, zona morta, curvas e ângulo desejado só valem no modo compatibilidade "
                "(controle virtual). A zona morta e a curva do volante (direção) só existem no programa.")
        ttk.Label(outer, text=note, style="Hint.TLabel", wraplength=760).grid(row=3, column=0, columnspan=2,
                                                                             sticky="w", pady=6)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)

    def _start_detect_axis(self, key, name):
        s = self.engine.snapshot()
        if not s["axes"]:
            return
        self.detect = ("axis", key, list(s["axes"]), time.time() + 6)
        self.calib_lbl.configure(text=f"Mexa o {name.lower()} até o fim agora…")

    def _calibrate(self):
        messagebox.showinfo("Calibrar", "Ao fechar esta janela, durante 10 segundos:\n\n"
                            "1. Gire o volante até os dois batentes.\n"
                            "2. Pise fundo em cada pedal.\n"
                            "3. Termine com o volante no centro e os pedais soltos.")
        self.engine.send("calibrate", 10)

    # -------------------------------------------------------------- aba ffb
    def _build_ffb(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Force feedback")
        v = tk.BooleanVar()
        ttk.Checkbutton(f, text="Programa controla o force feedback neste perfil", variable=v).grid(
            row=0, column=0, columnspan=4, sticky="w")
        self.bind(("ffb", "app_control"), v)
        ttk.Label(f, style="Hint.TLabel", wraplength=760, text=(
            "Desligado: o jogo usa o force feedback do volante normalmente (recomendado para jogos que "
            "reconhecem o volante). Ligado: o programa aplica a centralização e o peso abaixo, e o jogo não "
            "consegue mandar força. No modo de compatibilidade ele fica sempre ligado.")).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.slider(f, 2, "Força geral", ("ffb", "gain"), 0, 100, "{:.0f}%", float, int)
        self.slider(f, 3, "Centralização (mola)", ("ffb", "spring"), 0, 100, "{:.0f}%", float, int)
        self.slider(f, 4, "Peso (amortecimento)", ("ffb", "damper"), 0, 100, "{:.0f}%", float, int)
        self.slider(f, 5, "Vibração do jogo", ("ffb", "rumble"), 0, 100, "{:.0f}%", float, int,
                    hint="só no modo de compatibilidade")
        iv = tk.BooleanVar()
        ttk.Checkbutton(f, text="Inverter lado da força", variable=iv).grid(row=6, column=0, sticky="w", pady=4)
        self.bind(("ffb", "invert"), iv)

        tf = ttk.LabelFrame(f, text="Testes", padding=6)
        tf.grid(row=7, column=0, columnspan=4, sticky="we", pady=8)
        ttk.Button(tf, text="◀ Empurrar p/ esquerda", command=lambda: self.engine.send("test_push", -1)).pack(side="left", padx=4)
        ttk.Button(tf, text="Empurrar p/ direita ▶", command=lambda: self.engine.send("test_push", 1)).pack(side="left", padx=4)
        ttk.Button(tf, text="Vibrar", command=lambda: self.engine.send("test_vibrate")).pack(side="left", padx=4)
        ttk.Button(tf, text="Testar centralização (6 s)", command=lambda: self.engine.send("test_spring")).pack(side="left", padx=4)
        ttk.Button(tf, text="Parar", command=lambda: self.engine.send("stop_ffb")).pack(side="left", padx=4)
        self.ffb_lbl = ttk.Label(f, text="", style="Hint.TLabel")
        self.ffb_lbl.grid(row=8, column=0, columnspan=4, sticky="w")
        f.columnconfigure(1, weight=1)

    # ----------------------------------------------------------- aba compat
    def _build_compat(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Compatibilidade")
        v = tk.BooleanVar()
        ttk.Checkbutton(f, text="Modo compatibilidade: simular controle de Xbox 360", variable=v).grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.bind(("compat", "enabled"), v)
        ttk.Label(f, style="Hint.TLabel", wraplength=760, text=(
            "Para jogos que não aceitam este volante (ex.: Dirt 5, Forza Motorsport). O volante vira o "
            "analógico esquerdo, o acelerador o gatilho direito e o freio o gatilho esquerdo. A vibração do "
            "jogo é repassada ao motor do volante. No jogo, use o perfil de controle (gamepad) e reduza a "
            "zona morta e a assistência de direção ao mínimo.")).grid(row=1, column=0, columnspan=3, sticky="w")

        self.hid_lbl = ttk.Label(f, text="")
        self.hid_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(f, text="Baixar HidHide", command=lambda: webbrowser.open(HIDHIDE_URL)).grid(row=2, column=2, sticky="e")
        self.vigem_lbl = ttk.Label(f, text="")
        self.vigem_lbl.grid(row=6, column=0, columnspan=2, sticky="w", pady=6)
        self.vigem_btn = ttk.Button(f, text="Instalar driver do controle virtual", style="Accent.TButton",
                                    command=self._install_vigem)
        self.vigem_btn.grid(row=6, column=2, sticky="e")

        ttk.Label(f, text="Embreagem:").grid(row=3, column=0, sticky="w")
        cv = tk.StringVar()
        opts = {"none": "Não usar", "left_stick_y": "Analógico esquerdo (vertical)"}
        ttk.Combobox(f, textvariable=cv, values=list(opts.values()), state="readonly", width=30).grid(
            row=3, column=1, sticky="w")
        self.bind(("compat", "clutch_to"), cv, lambda k: opts.get(k, opts["none"]),
                  lambda s: next(k for k, t in opts.items() if t == s))

        bf = ttk.LabelFrame(f, text="Botões (Xbox ← volante)", padding=6)
        bf.grid(row=4, column=0, columnspan=3, sticky="we", pady=8)
        for i, xb in enumerate(P.XBOX_BUTTONS):
            r, c = i % 6, (i // 6) * 3
            ttk.Label(bf, text=xb, width=6).grid(row=r, column=c, sticky="w", padx=4, pady=2)
            bv = tk.StringVar()
            ttk.Combobox(bf, textvariable=bv, values=BTN_CHOICES, state="readonly", width=9).grid(row=r, column=c + 1)
            self.bind(("compat", "buttons", xb), bv,
                      lambda n: BTN_CHOICES[int(n) + 1] if n is not None else "—",
                      lambda s: None if s == "—" else BTN_CHOICES.index(s) - 1)
            ttk.Button(bf, text="Detectar", width=9,
                       command=lambda x=xb: self._start_detect_button(x)).grid(row=r, column=c + 2, padx=(2, 20))
        ttk.Label(bf, text="O direcional do volante vira o direcional do Xbox.", style="Hint.TLabel").grid(
            row=6, column=0, columnspan=6, sticky="w")
        self.compat_lbl = ttk.Label(f, text="", style="Hint.TLabel")
        self.compat_lbl.grid(row=5, column=0, columnspan=3, sticky="w")
        self.after(500, self._update_hidhide)

    def _install_vigem(self):
        msi = vigem_installer()
        if not msi:
            messagebox.showerror("Driver", "Instalador do ViGEmBus não encontrado neste pacote.")
            return
        if not messagebox.askyesno("Driver do controle virtual",
                                   "Instalar o driver ViGEmBus (necessário para o modo compatibilidade)?\n\n"
                                   "O Windows vai pedir permissão de administrador. Depois, reabra o programa."):
            return
        try:
            subprocess.Popen(["msiexec", "/i", msi])
        except OSError as e:
            messagebox.showerror("Driver", f"Não foi possível iniciar o instalador:\n{e}")

    def _update_hidhide(self):
        if vigem_installed():
            self.vigem_lbl.configure(text="Driver do controle virtual (ViGEmBus) instalado ✔")
            self.vigem_btn.grid_remove()
        else:
            self.vigem_lbl.configure(text="O modo compatibilidade precisa do driver ViGEmBus, que não está "
                                          "instalado neste PC.")
            self.vigem_btn.grid()
        if hidhide_installed():
            self.hid_lbl.configure(text="HidHide instalado ✔ (no HidHide, oculte o KalkanG500 e libere este programa)")
        else:
            self.hid_lbl.configure(text="Recomendado: instale o HidHide para o jogo não ver o volante e o controle "
                                        "virtual ao mesmo tempo.")

    def _start_detect_button(self, xb):
        s = self.engine.snapshot()
        self.detect = ("button", xb, list(s["buttons"]), time.time() + 6)
        self.compat_lbl.configure(text=f"Aperte no volante o botão que será o {xb}…")

    # ---------------------------------------------------------- aba perfis
    def _build_profiles(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Perfis")
        lf = ttk.LabelFrame(f, text="Perfis", padding=6)
        lf.grid(row=0, column=0, sticky="nswe", padx=4)
        self.prof_list = tk.Listbox(lf, height=14, exportselection=False)
        self.prof_list.pack(fill="both", expand=True)
        self.prof_list.bind("<Double-Button-1>", lambda e: self._activate_selected())
        bb = ttk.Frame(lf)
        bb.pack(fill="x", pady=4)
        for txt, cmd in (("Ativar", self._activate_selected), ("Novo", self._new_profile),
                         ("Duplicar", self._dup_profile), ("Renomear", self._rename_profile),
                         ("Excluir", self._del_profile)):
            ttk.Button(bb, text=txt, command=cmd, width=9).pack(side="left", padx=1)

        xf = ttk.LabelFrame(f, text="Jogos que ativam o perfil atual (.exe)", padding=6)
        xf.grid(row=0, column=1, sticky="nswe", padx=4)
        self.exe_list = tk.Listbox(xf, height=10, exportselection=False)
        self.exe_list.pack(fill="both", expand=True)
        xb = ttk.Frame(xf)
        xb.pack(fill="x", pady=4)
        ttk.Button(xb, text="Jogo aberto…", command=self._pick_running).pack(side="left", padx=2)
        ttk.Button(xb, text="Digitar…", command=self._add_exe).pack(side="left", padx=2)
        ttk.Button(xb, text="Remover", command=self._del_exe).pack(side="left", padx=2)
        av = tk.BooleanVar(value=self.glob.get("auto_switch", True))
        ttk.Checkbutton(xf, text="Trocar de perfil sozinho quando o jogo abrir", variable=av,
                        command=lambda: (self.glob.__setitem__("auto_switch", av.get()), self._schedule_save())
                        ).pack(anchor="w")
        ef = ttk.LabelFrame(f, text="Compartilhar perfis", padding=8)
        ef.grid(row=1, column=0, columnspan=2, sticky="we", padx=4, pady=(10, 0))
        ttk.Button(ef, text="Importar perfis…", style="Accent.TButton",
                   command=self._import_profiles).pack(side="left", padx=2)
        ttk.Button(ef, text="Exportar perfil selecionado…", command=self._export_selected).pack(side="left", padx=2)
        ttk.Button(ef, text="Exportar todos…", command=self._export_all).pack(side="left", padx=2)
        ttk.Label(ef, text="Arquivos .json — servem para levar seus perfis para outro PC ou compartilhar.",
                  style="Hint.TLabel").pack(side="left", padx=10)
        ttk.Label(f, style="Hint.TLabel", wraplength=760, text=(
            "Dica: abra o jogo, depois clique em \"Escolher jogo aberto\" para pegar o nome certo do .exe. "
            "Quando o jogo fecha, volta o último perfil escolhido à mão.")).grid(row=2, column=0, columnspan=2,
                                                                               sticky="w", pady=6)
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

    # --------------------------------------------------- exportar / importar
    def _export(self, names, default_name):
        path = filedialog.asksaveasfilename(
            parent=self, title="Exportar perfis", defaultextension=".json", initialfile=default_name,
            filetypes=[("Perfis do G500 Config", "*.json"), ("Todos os arquivos", "*.*")])
        if not path:
            return
        data = {"format": EXPORT_FORMAT, "version": 1, "app_version": APP_VERSION,
                "profiles": [self.profiles[n] for n in names]}
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except OSError as e:
            messagebox.showerror("Exportar", f"Não foi possível salvar o arquivo:\n{e}")
            return
        messagebox.showinfo("Exportar", f"{len(names)} perfil(is) exportado(s) para:\n{path}")

    def _export_selected(self):
        n = self._selected_profile() or self.active
        if self.save_job:
            self.after_cancel(self.save_job)
            self._save_now()
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in n).strip() or "perfil"
        self._export([n], f"{safe}.json")

    def _export_all(self):
        if self.save_job:
            self.after_cancel(self.save_job)
            self._save_now()
        self._export(sorted(self.profiles), "perfis_g500.json")

    def _import_profiles(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="Importar perfis",
            filetypes=[("Perfis do G500 Config", "*.json"), ("Todos os arquivos", "*.*")])
        if not paths:
            return
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
                prof = P._merge(P.DEFAULT_PROFILE, item)
                prof["exes"] = [str(x).strip().lower() for x in prof.get("exes", []) if str(x).strip()]
                name = prof["name"].strip()[:60]
                if name in self.profiles:
                    if not messagebox.askyesno("Importar", f"Já existe um perfil \"{name}\".\n\n"
                                               "Sim = substituir    Não = importar como cópia"):
                        base, k = name, 2
                        while f"{base} ({k})" in self.profiles:
                            k += 1
                        name = f"{base} ({k})"
                prof["name"] = name
                self.profiles[name] = prof
                P.save_profile(prof)
                imported.append(name)
        if imported:
            self.activate(imported[0])
        msg = f"{len(imported)} perfil(is) importado(s)." + (f"\n\n" + "\n".join(errors) if errors else "")
        (messagebox.showinfo if imported else messagebox.showwarning)("Importar", msg)

    def _refresh_profile_lists(self):
        names = sorted(self.profiles, key=lambda n: (n != "Padrão", n.lower()))
        self.profile_cb.configure(values=names)
        self.prof_list.delete(0, "end")
        for n in names:
            self.prof_list.insert("end", ("● " if n == self.active else "   ") + n)
        self.exe_list.delete(0, "end")
        for e in self.prof["exes"]:
            self.exe_list.insert("end", e)

    def _selected_profile(self):
        sel = self.prof_list.curselection()
        return self.prof_list.get(sel[0])[3:] if sel else None

    def _activate_selected(self):
        n = self._selected_profile()
        if n:
            self.activate(n)

    def _ask_name(self, title, initial=""):
        n = simpledialog.askstring(title, "Nome do perfil:", initialvalue=initial, parent=self)
        n = (n or "").strip()
        if not n:
            return None
        if n in self.profiles:
            messagebox.showerror(title, "Já existe um perfil com esse nome.")
            return None
        return n

    def _new_profile(self):
        n = self._ask_name("Novo perfil")
        if n:
            self.profiles[n] = P.new_profile(n)
            P.save_profile(self.profiles[n])
            self.activate(n)

    def _dup_profile(self):
        n = self._ask_name("Duplicar perfil", self.active + " (cópia)")
        if n:
            p = copy.deepcopy(self.prof)
            p["name"], p["exes"] = n, []
            self.profiles[n] = p
            P.save_profile(p)
            self.activate(n)

    def _rename_profile(self):
        if self.active == "Padrão":
            messagebox.showinfo("Renomear", "O perfil Padrão não pode ser renomeado.")
            return
        n = self._ask_name("Renomear perfil", self.active)
        if n:
            if self.save_job:
                self.after_cancel(self.save_job)
                self.save_job = None
            old = self.active
            p = self.profiles.pop(old)
            P.delete_profile(old)
            p["name"] = n
            self.profiles[n] = p
            P.save_profile(p)
            self.active = n
            self.activate(n)

    def _del_profile(self):
        n = self._selected_profile() or self.active
        if n == "Padrão":
            messagebox.showinfo("Excluir", "O perfil Padrão não pode ser excluído.")
            return
        if not messagebox.askyesno("Excluir", f"Excluir o perfil \"{n}\"?"):
            return
        self.profiles.pop(n, None)
        P.delete_profile(n)
        if self.active == n or self.active not in self.profiles:
            self.activate("Padrão")
        else:
            self._refresh_profile_lists()

    def _add_exe(self, name=None):
        name = name or simpledialog.askstring("Adicionar jogo", "Nome do executável (ex.: dirt5.exe):", parent=self)
        name = (name or "").strip().lower()
        if name and name not in self.prof["exes"]:
            self.prof["exes"].append(name)
            self._refresh_profile_lists()
            self._schedule_save()

    def _del_exe(self):
        sel = self.exe_list.curselection()
        if sel:
            self.prof["exes"].pop(sel[0])
            self._refresh_profile_lists()
            self._schedule_save()

    def _pick_running(self):
        win = tk.Toplevel(self)
        win.title("Escolher jogo aberto")
        win.geometry("360x420")
        lb = tk.Listbox(win)
        lb.pack(fill="both", expand=True, padx=6, pady=6)
        names = sorted({(pr.info["name"] or "").lower() for pr in psutil.process_iter(["name"])} - {""})
        for n in names:
            lb.insert("end", n)

        def ok():
            sel = lb.curselection()
            if sel:
                self._add_exe(lb.get(sel[0]))
            win.destroy()
        lb.bind("<Double-Button-1>", lambda e: ok())
        ttk.Button(win, text="Adicionar", command=ok).pack(pady=6)

    def _watch_processes(self):
        while True:
            try:
                self.running_exes = {(pr.info["name"] or "").lower() for pr in psutil.process_iter(["name"])}
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)

    def _auto_switch(self):
        if not self.glob.get("auto_switch", True):
            self.auto_lbl.configure(text="")
            return
        match = None
        for n, p in self.profiles.items():
            if n != "Padrão" and self.running_exes & set(p["exes"]):
                match = n
                break
        # só age quando o jogo detectado muda, para não brigar com uma troca manual
        if match == self.last_match:
            pass
        elif match:
            self.activate(match, manual=False)
            self.auto_active = True
        elif self.auto_active:
            self.auto_active = False
            self.activate(self.manual_profile if self.manual_profile in self.profiles else "Padrão", manual=False)
        self.last_match = match
        self.auto_lbl.configure(text="(ativado pelo jogo)" if self.auto_active else "")

    # ------------------------------------------------------------- loop
    def _tick(self):
        s = self.engine.snapshot()
        if s["connected"]:
            extra = []
            if s["compat"]:
                extra.append("Xbox virtual ligado")
            if s["ffb"] and not s.get("preview"):
                extra.append("force feedback pelo programa")
            if self.ble.connected:
                extra.append("Bluetooth conectado")
            text = f"{s['name']} conectado pelo USB" + (f"   ·   {'   ·   '.join(extra)}" if extra else "")
            color = "#2ecc71"
        else:
            text, color = "Volante não encontrado — conecte o cabo USB", "#ff5f57"
        if self.status_lbl.cget("text") != text:
            self.status_lbl.configure(text=text)
        if getattr(self, "_status_color", None) != color:
            self._draw_status_dot(color)

        if s["axes"]:
            self._draw_test(s)

        if self.detect:
            kind, key, base, deadline = self.detect
            if time.time() > deadline:
                self.detect = None
                self.calib_lbl.configure(text="Nada detectado.")
                self.compat_lbl.configure(text="Nada detectado.")
            elif kind == "axis" and s["axes"]:
                diffs = [abs(a - b) for a, b in zip(s["axes"], base)]
                i = max(range(len(diffs)), key=diffs.__getitem__)
                if diffs[i] > 12000:
                    self.prof["axes"][key] = i
                    self.detect = None
                    self.calib_lbl.configure(text=f"Detectado: Eixo {i}.")
                    self._load_profile_into_ui()
                    self._schedule_save()
            elif kind == "button":
                for i, b in enumerate(s["buttons"]):
                    if b and not (i < len(base) and base[i]):
                        self.prof["compat"]["buttons"][key] = i
                        self.detect = None
                        self.compat_lbl.configure(text=f"{key} = Botão {i}.")
                        self._load_profile_into_ui()
                        self._schedule_save()
                        break

        if s["calibrating"]:
            self.calib_lbl.configure(text="Calibrando… gire o volante e pise nos pedais.")
        elif self.calib_lbl.cget("text").startswith("Calibrando"):
            self.calib_lbl.configure(text="Calibração salva.")
            self._schedule_save()

        self.ffb_lbl.configure(text=("Erro no force feedback: " + s["ffb_error"]) if s["ffb_error"] else "")
        if s["compat_error"]:
            self.compat_lbl.configure(text="Erro no controle virtual: " + s["compat_error"])

        self._auto_switch()
        self._hw_tick()
        self._jobs_tick()
        self._preview_tick()
        self.after(33, self._tick)

    def _on_close(self):
        if self.save_job:
            self.after_cancel(self.save_job)
        self._save_now()
        self.engine.stop()
        self.engine.join(timeout=2)
        self.ble.close()
        self.destroy()


def _self_test(app, out_path):
    """Modo --autoteste: confere as peças principais e grava um relatório JSON."""
    rep = {"versao": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
           "tema": app.theme, "paginas": list(app.host.pages)}
    t0 = time.time()

    def finish():
        s = app.engine.snapshot()
        rep.update(usb_conectado=s["connected"], usb_nome=s["name"], eixos=s["axes"],
                   botoes=len(s["buttons"]), vgamepad_ok=vg is not None, vigem_instalado=vigem_installed(),
                   icone=os.path.exists(resource("assets", "icone.ico")),
                   ble_status=app.ble.status, ble_info={k: v for k, v in app.ble.info.items()
                                                        if k not in ("raw_part2",)})
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2, ensure_ascii=False, default=str)
        app._on_close()

    def wait_ble():
        if (app.ble.connected and not app.ble.busy and "angle" in app.ble.info) or time.time() - t0 > 30:
            finish()
        else:
            app.after(500, wait_ble)

    app._hw_connect()
    app.after(1500, wait_ble)


def main():
    app = App()
    if "--autoteste" in sys.argv:
        i = sys.argv.index("--autoteste")
        out = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(P.CONFIG_DIR, "autoteste.json")
        app.after(500, lambda: _self_test(app, out))
    app.mainloop()
