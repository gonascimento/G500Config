"""Sobreposição dos pedais nos jogos: barras de embreagem, freio e acelerador.

Roda como processo separado (G500Config.exe --overlay PORTA). Recebe os valores do
programa principal por UDP local, fica sempre por cima, não rouba o foco do jogo e deixa
os cliques passarem. No modo "posicionar" pode ser arrastada com o mouse.
Funciona em jogos em janela ou "tela cheia sem bordas"; tela cheia exclusiva não mostra
janelas por cima.
"""
import ctypes
import json
import socket
import sys
import time
import tkinter as tk

KEY = "#010203"  # cor tratada como transparente
COLORS = {"clutch": "#3d9bff", "brake": "#ff4757", "throttle": "#2ed573"}
LABELS = {"clutch": "E", "brake": "F", "throttle": "A"}
ORDER = ("clutch", "brake", "throttle")

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x08000000


class Overlay:
    def __init__(self, port):
        self.server = ("127.0.0.1", port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=KEY)
        try:
            self.root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.cv = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)

        self.cfg = None
        self.values = {k: 0.0 for k in ORDER}
        self.connected = False
        self.last_rx = time.time()
        self.last_top = 0.0
        self.geom = None
        self.style_edit = None
        self.drag = None
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._move)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self._send({"hello": 1, "screen": [self.root.winfo_screenwidth(), self.root.winfo_screenheight()]})
        self.root.after(16, self._tick)

    # ------------------------------------------------------------ rede
    def _send(self, msg):
        try:
            self.sock.sendto(json.dumps(msg).encode(), self.server)
        except OSError:
            pass

    def _recv(self):
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
            except (BlockingIOError, OSError):
                return
            try:
                m = json.loads(data.decode())
            except ValueError:
                continue
            self.last_rx = time.time()
            if m.get("quit"):
                self.root.destroy()
                raise SystemExit
            if "cfg" in m:
                self.cfg = m["cfg"]
            if "v" in m:
                self.values.update(m["v"])
            self.connected = bool(m.get("on", True))

    # ------------------------------------------------------------ arrastar
    def _press(self, e):
        if self.cfg and self.cfg.get("edit"):
            self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _move(self, e):
        if self.drag:
            x, y = e.x_root - self.drag[0], e.y_root - self.drag[1]
            self.root.geometry(f"+{x}+{y}")

    def _release(self, _e):
        if self.drag:
            self.drag = None
            x, y = self.root.winfo_x(), self.root.winfo_y()
            self.cfg["x"], self.cfg["y"] = x, y
            self._send({"pos": [x, y]})

    # ------------------------------------------------------------ janela
    def _hwnd(self):
        # janela de nível superior (a que o Windows mostra), não o widget interno do Tk
        try:
            return int(self.root.wm_frame(), 16)
        except (tk.TclError, ValueError):
            return ctypes.windll.user32.GetParent(self.root.winfo_id())

    def _apply_style(self, edit):
        if edit == self.style_edit or not self.root.winfo_ismapped():
            return
        try:
            u = ctypes.windll.user32
            h = self._hwnd()
            if not h:
                return
            st = u.GetWindowLongW(h, GWL_EXSTYLE) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            st = st & ~WS_EX_TRANSPARENT if edit else st | WS_EX_TRANSPARENT
            u.SetWindowLongW(h, GWL_EXSTYLE, st)
            # SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            u.SetWindowPos(h, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
            self.style_edit = edit
        except (AttributeError, OSError):
            pass

    def _size(self, c):
        s = float(c.get("scale", 1.0))
        shown = [k for k in ORDER if c.get("show", {}).get(k, True)] or list(ORDER)
        pad = int(10 * s)
        if c.get("orientation") == "horizontal":
            bar_w, bar_h, gap = int(180 * s), int(16 * s), int(8 * s)
            lab = int(18 * s) if c.get("labels", True) else 0
            pct = int(40 * s) if c.get("percent", True) else 0
            w = pad * 2 + lab + bar_w + pct
            h = pad * 2 + len(shown) * bar_h + (len(shown) - 1) * gap
        else:
            bar_w, bar_h, gap = int(22 * s), int(120 * s), int(10 * s)
            top = int(16 * s) if c.get("percent", True) else 0
            bot = int(16 * s) if c.get("labels", True) else 0
            w = pad * 2 + len(shown) * bar_w + (len(shown) - 1) * gap
            h = pad * 2 + top + bar_h + bot
        return shown, s, pad, bar_w, bar_h, gap, max(w, 40), max(h, 30)

    def _draw(self):
        c = self.cfg
        shown, s, pad, bw, bh, gap, w, h = self._size(c)
        geom = (w, h, int(c.get("x", 40)), int(c.get("y", 40)))
        if geom != self.geom and not self.drag:
            self.root.geometry(f"{w}x{h}+{geom[2]}+{geom[3]}")
            self.geom = geom
        self.root.attributes("-alpha", max(0.15, min(1.0, float(c.get("opacity", 0.85)))))
        cv = self.cv
        cv.delete("all")
        cv.create_rectangle(0, 0, w, h, fill="#12151c", outline="")
        font = ("Segoe UI Semibold", max(7, int(8 * s)))
        if c.get("orientation") == "horizontal":
            lab = int(18 * s) if c.get("labels", True) else 0
            for i, k in enumerate(shown):
                y = pad + i * (bh + gap)
                x0 = pad + lab
                v = max(0.0, min(1.0, float(self.values.get(k, 0))))
                if lab:
                    cv.create_text(pad + lab / 2 - 2, y + bh / 2, text=LABELS[k], fill="#cbd5e1", font=font)
                cv.create_rectangle(x0, y, x0 + bw, y + bh, fill="#262b36", outline="")
                cv.create_rectangle(x0, y, x0 + bw * v, y + bh, fill=COLORS[k], outline="")
                if c.get("percent", True):
                    cv.create_text(x0 + bw + 6, y + bh / 2, anchor="w", text=f"{v * 100:.0f}%",
                                   fill="#f1f5f9", font=font)
        else:
            top = int(16 * s) if c.get("percent", True) else 0
            for i, k in enumerate(shown):
                x = pad + i * (bw + gap)
                y0 = pad + top
                v = max(0.0, min(1.0, float(self.values.get(k, 0))))
                cv.create_rectangle(x, y0, x + bw, y0 + bh, fill="#262b36", outline="")
                cv.create_rectangle(x, y0 + bh * (1 - v), x + bw, y0 + bh, fill=COLORS[k], outline="")
                if top:
                    cv.create_text(x + bw / 2, pad + top / 2 - 1, text=f"{v * 100:.0f}", fill="#f1f5f9", font=font)
                if c.get("labels", True):
                    cv.create_text(x + bw / 2, y0 + bh + int(8 * s), text=LABELS[k], fill="#cbd5e1", font=font)
        if not self.connected:
            cv.create_text(w / 2, h / 2, text="sem volante", fill="#ffb020", font=font)
        if c.get("edit"):
            cv.create_rectangle(1, 1, w - 2, h - 2, outline="#ffc400", width=2, dash=(4, 3))

    def _tick(self):
        self._recv()
        if time.time() - self.last_rx > 5:  # programa principal fechou
            self.root.destroy()
            return
        if self.cfg:
            self._draw()
            if self.root.state() == "withdrawn":
                self.root.deiconify()
                self.root.update_idletasks()
            self._apply_style(bool(self.cfg.get("edit")))
            if time.time() - self.last_top > 2:  # alguns jogos jogam a janela para trás
                self.last_top = time.time()
                self.root.attributes("-topmost", True)
                self.root.lift()
        self.root.after(16, self._tick)


def main(port):
    try:
        Overlay(int(port)).root.mainloop()
    except SystemExit:
        pass


if __name__ == "__main__":
    main(sys.argv[1])
