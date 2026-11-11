import os
import sys

if getattr(sys, "frozen", False):
    # dentro do .exe: aponta o pysdl2 para as DLLs do SDL empacotadas
    os.environ.setdefault("PYSDL2_DLL_PATH", os.path.join(sys._MEIPASS, "sdl2dll", "dll"))


def run():
    if "--overlay" in sys.argv:  # janela das barras dos pedais sobre os jogos
        from g500 import overlay
        overlay.main(sys.argv[sys.argv.index("--overlay") + 1])
        return
    if "--classico" not in sys.argv:
        try:
            from g500 import webapp
            webapp.main()
            return
        except Exception:  # noqa: BLE001  (sem WebView2: usa a interface antiga)
            import traceback
            traceback.print_exc()
    from g500.gui import main
    main()


if __name__ == "__main__":
    run()
