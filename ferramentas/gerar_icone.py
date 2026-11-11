"""Gera o ícone do programa (assets/icone.ico e assets/icone.png)."""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

S = 1024  # desenha grande e reduz, para bordas suaves
OUT = os.path.join(os.path.dirname(__file__), "..", "assets")


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # fundo: quadrado arredondado com gradiente vermelho
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    c1, c2 = (255, 42, 75), (140, 10, 35)  # vermelho (cor padrão da interface)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(c1, c2)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)

    # sombra suave do volante
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    cx, cy, r = S // 2, S // 2 + 18, 330
    sd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 0, 0, 110), width=110)
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    img.alpha_composite(shadow)

    d = ImageDraw.Draw(img)
    cx, cy = S // 2, S // 2
    white = (255, 255, 255, 255)
    # aro
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=white, width=96)
    # raios (esquerda, direita e baixo)
    for ang in (180, 0, 270):
        a = math.radians(ang)
        x2, y2 = cx + (r - 40) * math.cos(a), cy - (r - 40) * math.sin(a)
        d.line([(cx, cy), (x2, y2)], fill=white, width=92)
    # cubo central
    d.ellipse([cx - 120, cy - 120, cx + 120, cy + 120], fill=white)
    d.ellipse([cx - 62, cy - 62, cx + 62, cy + 62], fill=(178, 20, 50, 255))
    # marcador de centro (topo do aro)
    d.rounded_rectangle([cx - 34, cy - r - 52, cx + 34, cy - r + 52], radius=20, fill=(255, 196, 0, 255))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icone.png"))
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(os.path.join(OUT, "icone.ico"), sizes=sizes)
    print("ícone gerado em", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
