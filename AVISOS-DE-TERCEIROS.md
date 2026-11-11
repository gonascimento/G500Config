# Avisos de terceiros

O código deste projeto está sob a licença MIT (arquivo `LICENSE`). Os itens abaixo
pertencem a terceiros e seguem as licenças de cada um.

## Imagens e marcas
- **Fotos dos produtos** (`g500/webui/img/kalkam_g500.png` e `g500/webui/img/pcyes_w270.png`):
  imagens de divulgação dos fabricantes, usadas apenas para identificar os volantes.
  Kalkan/Kalkam, PCyes, LITE STAR, Logitech, G HUB e Xbox são marcas dos seus respectivos donos.
  Este projeto não tem ligação com nenhum desses fabricantes.
- **Desenhos** (`docs/*.svg`, `g500/webui/wheels.js`, `g500/webui/art.js`): feitos para este
  projeto (MIT). O desenho do Kalkam G500 segue a ilustração do manual do produto.

## Incluídos na interface (`g500/webui/vendor`)
| Item | Licença |
|---|---|
| Tailwind CSS (script "play" 3.4) | MIT |
| Font Awesome Free 6.4 | Ícones: CC BY 4.0 · Fontes: SIL OFL 1.1 · Código: MIT |
| Fontes Inter e Rajdhani (Google Fonts) | SIL Open Font License 1.1 |

## Bibliotecas Python (instaladas pelo `requirements.txt` e embutidas no `.exe`)
| Biblioteca | Licença |
|---|---|
| PySDL2 / SDL2 (pysdl2-dll) | Domínio público / zlib |
| psutil | BSD-3-Clause |
| vgamepad (inclui o instalador do ViGEmBus) | MIT (ViGEmBus: BSD-3-Clause) |
| bleak | MIT |
| pywebview | BSD-3-Clause |
| sv-ttk | MIT |
| PyInstaller (só para gerar o `.exe`) | GPL 2.0 com exceção para programas gerados |

## Protocolo Bluetooth
Os comandos em `g500/ble.py` foram descobertos para interoperabilidade, analisando o app
"Racing Wheel" (com.star.v10). O app e o código dele **não** fazem parte deste repositório.
