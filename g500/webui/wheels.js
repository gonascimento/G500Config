// Desenhos (SVG) dos volantes e posição dos botões.
// Kalkam G500: desenho e numeração tirados do manual oficial (KLK00032, "Layout dos botões frontais"
// e "Lista de correspondência de teclas"). Cada desenho usa as próprias coordenadas ("native");
// a interface encaixa no espaço que precisar.
//
// hotspot: id, label (nome), short (nome curto da etiqueta), x/y/r (posição no desenho),
//          side ('L' ou 'R' = coluna de etiquetas), hat (true = direcional, não é botão).

const WHEELS = {
    kalkam: {
        native: { cx: 615, cy: 510, r: 445 },
        hotspots: [
            { id: 'paddle-l', label: 'Borboleta esquerda', short: 'L-Paddle', x: 372, y: 405, r: 34, side: 'L' },
            { id: 'dpad', label: 'Direcional (D-pad)', short: 'D-pad', x: 378, y: 548, r: 46, side: 'L', hat: true },
            { id: 'share', label: 'SHARE / Voltar', short: 'SHARE', x: 582, y: 625, r: 15, side: 'L' },
            { id: 'mode', label: 'MODE / Home', short: 'MODE', x: 615, y: 632, r: 15, side: 'L' },
            { id: 'l1', label: 'L1 / LB', short: 'L1', x: 388, y: 640, r: 17, side: 'L' },
            { id: 'l2', label: 'L2 / LT', short: 'L2', x: 420, y: 662, r: 17, side: 'L' },
            { id: 'l3', label: 'L3 / SL', short: 'L3', x: 434, y: 694, r: 17, side: 'L' },
            { id: 'paddle-r', label: 'Borboleta direita', short: 'R-Paddle', x: 858, y: 405, r: 34, side: 'R' },
            { id: 'btn-y', label: 'Y', short: 'Y', x: 848, y: 513, r: 16, side: 'R' },
            { id: 'btn-x', label: 'X', short: 'X', x: 819, y: 540, r: 16, side: 'R' },
            { id: 'btn-b', label: 'B', short: 'B', x: 877, y: 540, r: 16, side: 'R' },
            { id: 'btn-a', label: 'A', short: 'A', x: 848, y: 567, r: 16, side: 'R' },
            { id: 'capture', label: 'Compartilhar (ícone)', short: 'Captura', x: 685, y: 604, r: 15, side: 'R' },
            { id: 'options', label: 'OPTIONS / Start', short: 'OPTIONS', x: 650, y: 624, r: 15, side: 'R' },
            { id: 'r1', label: 'R1 / RB', short: 'R1', x: 842, y: 640, r: 17, side: 'R' },
            { id: 'r2', label: 'R2 / RT', short: 'R2', x: 810, y: 662, r: 17, side: 'R' },
            { id: 'r3', label: 'R3 / SR', short: 'R3', x: 796, y: 694, r: 17, side: 'R' },
        ],
        svg: (c) => {
            const m = x => 1230 - x;  // espelho em torno do centro (x = 615)
            const wingL = 'M 262 548 C 262 505 280 494 304 489 L 506 438 L 498 612 L 302 606 C 278 604 262 592 262 548 Z';
            const wingR = 'M 968 548 C 968 505 950 494 926 489 L 724 438 L 732 612 L 928 606 C 952 604 968 592 968 548 Z';
            const paddleL = 'M 338 472 C 328 420 342 352 372 338 C 394 330 412 344 406 380 L 398 472 Z';
            const paddleR = `M ${m(338)} 472 C ${m(328)} 420 ${m(342)} 352 ${m(372)} 338 C ${m(394)} 330 ${m(412)} 344 ${m(406)} 380 L ${m(398)} 472 Z`;
            const btn = (x, y, r, fill = '#1e2430', stroke = '#64748b') =>
                `<circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="3" />`;
            return `
            <!-- aro -->
            <circle cx="615" cy="510" r="402" fill="none" stroke="#12151c" stroke-width="82" />
            <circle cx="615" cy="510" r="402" fill="none" stroke="#232a39" stroke-width="70" stroke-dasharray="26 9" />
            <circle cx="615" cy="510" r="361" fill="none" stroke="#2f384b" stroke-width="3" />
            <rect x="603" y="68" width="24" height="88" rx="4" fill="#ff2a4b" />
            <!-- borboletas (atrás) -->
            <path d="${paddleL}" fill="#2a3245" stroke="${c}" stroke-width="3" />
            <path d="${paddleR}" fill="#2a3245" stroke="${c}" stroke-width="3" />
            <!-- raio inferior em V (vazado) -->
            <path d="M 438 610 L 545 868 L 685 868 L 792 610 Z" fill="#8b97a8" stroke="#cbd5e1" stroke-width="3" />
            <path d="M 492 636 L 573 832 L 657 832 L 738 636 Z" fill="#0d0f14" stroke="#475569" stroke-width="3" />
            <!-- asas prateadas -->
            <path d="${wingL}" fill="#94a3b8" stroke="#cbd5e1" stroke-width="3" />
            <path d="${wingR}" fill="#94a3b8" stroke="#cbd5e1" stroke-width="3" />
            <!-- apoios dos botões de baixo -->
            <ellipse cx="412" cy="664" rx="62" ry="44" transform="rotate(38 412 664)" fill="#7c8899" stroke="#cbd5e1" stroke-width="3" />
            <ellipse cx="818" cy="664" rx="62" ry="44" transform="rotate(-38 818 664)" fill="#7c8899" stroke="#cbd5e1" stroke-width="3" />
            <!-- centro com visor -->
            <circle cx="615" cy="510" r="128" fill="#12151c" stroke="#64748b" stroke-width="5" />
            <circle cx="615" cy="510" r="114" fill="none" stroke="${c}" stroke-width="3" />
            <rect x="548" y="428" width="134" height="132" rx="44" fill="#0b0c10" stroke="#334155" stroke-width="4" />
            <path d="M 597 476 L 633 512 M 633 476 L 597 512" stroke="${c}" stroke-width="9" stroke-linecap="round" />
            <circle cx="615" cy="586" r="6" fill="${c}" />
            <text x="548" y="611" text-anchor="middle" fill="#64748b" font-size="13" font-family="Inter" font-weight="700">PROG</text>
            <!-- direcional -->
            <circle cx="378" cy="548" r="46" fill="#1e2430" stroke="#475569" stroke-width="3" />
            <path d="M 354 541 H 371 V 524 H 385 V 541 H 402 V 555 H 385 V 572 H 371 V 555 H 354 Z" fill="${c}" />
            <!-- A B X Y -->
            ${btn(848, 513, 16, '#eab308', '#fff')}${btn(819, 540, 16, '#3b82f6', '#fff')}
            ${btn(877, 540, 16, '#ef4444', '#fff')}${btn(848, 567, 16, '#22c55e', '#fff')}
            <!-- L1 L2 L3 / R1 R2 R3 -->
            ${btn(388, 640, 17)}${btn(420, 662, 17)}${btn(434, 694, 17)}
            ${btn(842, 640, 17)}${btn(810, 662, 17)}${btn(796, 694, 17)}
            <!-- fileira de baixo do centro: SHARE, MODE, OPTIONS, compartilhar -->
            ${btn(582, 625, 15)}${btn(615, 632, 15)}${btn(650, 624, 15)}${btn(685, 604, 15)}`;
        },
    },
    pcyes: {
        native: { cx: 200, cy: 200, r: 192 },
        hotspots: [
            { id: 'paddle-l', label: 'Borboleta esquerda', short: 'L-Paddle', x: 52, y: 156, r: 14, side: 'L' },
            { id: 'dpad', label: 'Direcional (D-pad)', short: 'D-pad', x: 110, y: 185, r: 18, side: 'L', hat: true },
            { id: 'l-1', label: 'Fileira esquerda 1', short: 'Esq. 1', x: 141, y: 218, r: 7, side: 'L' },
            { id: 'l-2', label: 'Fileira esquerda 2', short: 'Esq. 2', x: 156, y: 218, r: 7, side: 'L' },
            { id: 'l-3', label: 'Fileira esquerda 3', short: 'Esq. 3', x: 171, y: 218, r: 7, side: 'L' },
            { id: 'c-1', label: 'Central 1', short: 'Centro 1', x: 170, y: 250, r: 6, side: 'L' },
            { id: 'c-2', label: 'Central 2', short: 'Centro 2', x: 190, y: 250, r: 6, side: 'L' },
            { id: 'paddle-r', label: 'Borboleta direita', short: 'R-Paddle', x: 348, y: 156, r: 14, side: 'R' },
            { id: 'btn-1', label: 'Botão superior esq.', short: 'Sup. esq.', x: 280, y: 175, r: 8, side: 'R' },
            { id: 'btn-2', label: 'Botão superior dir.', short: 'Sup. dir.', x: 300, y: 175, r: 8, side: 'R' },
            { id: 'btn-3', label: 'Botão inferior esq.', short: 'Inf. esq.', x: 280, y: 195, r: 8, side: 'R' },
            { id: 'btn-4', label: 'Botão inferior dir.', short: 'Inf. dir.', x: 300, y: 195, r: 8, side: 'R' },
            { id: 'r-1', label: 'Fileira direita 1', short: 'Dir. 1', x: 229, y: 218, r: 7, side: 'R' },
            { id: 'r-2', label: 'Fileira direita 2', short: 'Dir. 2', x: 244, y: 218, r: 7, side: 'R' },
            { id: 'r-3', label: 'Fileira direita 3', short: 'Dir. 3', x: 259, y: 218, r: 7, side: 'R' },
            { id: 'c-3', label: 'Central 3', short: 'Centro 3', x: 210, y: 250, r: 6, side: 'R' },
            { id: 'c-4', label: 'Central 4', short: 'Centro 4', x: 230, y: 250, r: 6, side: 'R' },
        ],
        svg: (c) => `
            <circle cx="200" cy="200" r="175" fill="none" stroke="#12151c" stroke-width="32" />
            <circle cx="200" cy="200" r="175" fill="none" stroke="#252c3d" stroke-width="26" stroke-dasharray="12 4" />
            <path d="M 191 26 A 175 175 0 0 1 209 26" fill="none" stroke="#ff2a4b" stroke-width="28" />
            <path d="M 65 170 L 150 185 L 145 220 L 175 240 L 175 325 L 225 325 L 225 240 L 255 220 L 250 185 L 335 170 L 325 210 L 240 240 L 215 335 L 185 335 L 160 240 L 75 210 Z" fill="#cbd5e1" stroke="#ffffff" stroke-width="1.5" />
            <path d="M 140 150 L 260 150 L 245 240 L 155 240 Z" fill="#181c26" stroke="${c}" stroke-width="2" />
            <path d="M 150 160 L 250 160 L 238 230 L 162 230 Z" fill="#0b0c10" />
            <rect x="165" y="180" width="70" height="28" rx="6" fill="#ff2a4b" stroke="#ffffff" stroke-width="1" />
            <text x="200" y="199" text-anchor="middle" fill="#ffffff" font-family="Rajdhani" font-size="14" font-weight="700" letter-spacing="1">PCyes</text>
            <g transform="translate(110, 185)">
                <rect x="-18" y="-18" width="36" height="36" rx="8" fill="#1e2430" stroke="${c}" stroke-width="1" />
                <path d="M -10 -3 H -3 V -10 H 3 V -3 H 10 V 3 H 3 V 10 H -3 V 3 H -10 Z" fill="#ffffff" />
            </g>
            <rect x="135" y="215" width="12" height="7" rx="2" fill="${c}" />
            <rect x="150" y="215" width="12" height="7" rx="2" fill="${c}" />
            <rect x="165" y="215" width="12" height="7" rx="2" fill="${c}" />
            <g transform="translate(290, 185)">
                <circle cx="-10" cy="-10" r="7" fill="#252c3d" stroke="${c}" stroke-width="1.5" />
                <circle cx="10" cy="-10" r="7" fill="#252c3d" stroke="${c}" stroke-width="1.5" />
                <circle cx="-10" cy="10" r="7" fill="#252c3d" stroke="${c}" stroke-width="1.5" />
                <circle cx="10" cy="10" r="7" fill="#252c3d" stroke="${c}" stroke-width="1.5" />
            </g>
            <rect x="223" y="215" width="12" height="7" rx="2" fill="${c}" />
            <rect x="238" y="215" width="12" height="7" rx="2" fill="${c}" />
            <rect x="253" y="215" width="12" height="7" rx="2" fill="${c}" />
            <circle cx="170" cy="250" r="5" fill="#ffffff" />
            <circle cx="190" cy="250" r="5" fill="#ffffff" />
            <circle cx="210" cy="250" r="5" fill="#ffffff" />
            <circle cx="230" cy="250" r="5" fill="#ffffff" />
            <path d="M 45 130 L 65 120 L 60 190 L 40 180 Z" fill="#334155" stroke="${c}" stroke-width="1" />
            <path d="M 355 130 L 335 120 L 340 190 L 360 180 Z" fill="#334155" stroke="${c}" stroke-width="1" />`,
    },
};

// Encaixa o desenho de um volante num espaço: centro (cx, cy) e raio desejado.
function wheelGroup(dev, color, cx, cy, radius) {
    const n = WHEELS[dev].native, k = radius / n.r;
    return `<g transform="translate(${cx} ${cy}) scale(${k}) translate(${-n.cx} ${-n.cy})">${WHEELS[dev].svg(color)}</g>`;
}
