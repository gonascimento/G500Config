// Desenhos próprios dos conjuntos (volante + pedais + câmbio), em SVG.
// Usados no seletor de volante (opção "Desenho") e exportados para docs/ pelo
// script ferramentas/gerar_desenhos.js. Dependem de wheels.js (wheelGroup).

function pedalsArt(c) {
    // base de 3 pedais vista de frente (embreagem, freio, acelerador)
    const pedal = (x, w, h) => `
        <rect x="${x}" y="${160 - h}" width="${w}" height="${h}" rx="7" fill="#c7cfda" stroke="#e5e9f0" stroke-width="2" />
        ${[0.28, 0.72].map(fx => [0.22, 0.78].map(fy =>
            `<circle cx="${x + w * fx}" cy="${160 - h + h * fy}" r="4.5" fill="#1e2430" />`).join('')).join('')}`;
    return `
        <path d="M 8 70 L 22 46 L 238 46 L 252 70 L 252 168 L 8 168 Z" fill="#1d222d" stroke="#3a4357" stroke-width="2" />
        <rect x="16" y="56" width="228" height="10" rx="3" fill="#2a3245" />
        ${pedal(30, 52, 86)}${pedal(104, 52, 86)}${pedal(186, 40, 100)}
        <path d="M 0 168 L 260 168 L 248 226 L 12 226 Z" fill="#151922" stroke="#3a4357" stroke-width="2" />
        ${Array.from({ length: 9 }, (_, i) => `<rect x="${24 + i * 24}" y="180" width="16" height="36" rx="3" fill="#0d1016" />`).join('')}
        <rect x="104" y="174" width="52" height="12" rx="3" fill="${c}" opacity=".85" />`;
}

function shifterArt(c) {
    // câmbio H 6+1 com manopla, botão P (freio de mão) e LO/HI
    return `
        <path d="M 10 150 C 10 90 40 70 96 70 L 150 70 C 182 70 196 96 196 130 L 196 168 C 196 182 186 190 172 190 L 28 190 C 16 190 10 180 10 166 Z"
              fill="#1d222d" stroke="#3a4357" stroke-width="2" />
        <ellipse cx="96" cy="112" rx="58" ry="30" fill="#12151c" stroke="#475569" stroke-width="2" />
        <path d="M 62 102 H 130 M 62 122 H 130 M 70 98 V 126 M 96 98 V 126 M 122 98 V 126" stroke="#3a4357" stroke-width="5" stroke-linecap="round" />
        <rect x="91" y="40" width="10" height="72" rx="4" fill="#9aa4b5" />
        <circle cx="96" cy="34" r="27" fill="#2a3245" stroke="#cbd5e1" stroke-width="2.5" />
        <circle cx="88" cy="26" r="8" fill="#ffffff" opacity=".18" />
        <rect x="150" y="102" width="30" height="20" rx="5" fill="#12151c" stroke="${c}" stroke-width="2" />
        <text x="165" y="117" text-anchor="middle" fill="${c}" font-family="Inter, Arial" font-size="12" font-weight="800">P</text>
        <rect x="150" y="132" width="30" height="20" rx="5" fill="#12151c" stroke="#64748b" stroke-width="2" />
        <text x="165" y="146" text-anchor="middle" fill="#cbd5e1" font-family="Inter, Arial" font-size="8.5" font-weight="800">LO/HI</text>`;
}

// Conjunto completo: volante grande à esquerda, pedais embaixo à direita, câmbio ao lado.
function kitArt(dev, c, opts = {}) {
    const H = opts.title ? 480 : 420, top = opts.title ? 60 : 0;
    const bg = opts.background ? `<rect width="640" height="${H}" rx="28" fill="${opts.background}" />` : '';
    const title = opts.title ? `<text x="28" y="44" fill="#ffffff" font-family="Rajdhani, Inter, Arial" font-size="30" font-weight="700">${opts.title}</text>
        <rect x="28" y="54" width="56" height="4" rx="2" fill="${c}" />` : '';
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 ${H}">${bg}${title}
        <g transform="translate(0 ${top})">
        <ellipse cx="320" cy="400" rx="300" ry="16" fill="#000" opacity=".35" />
        <!-- base do volante -->
        <path d="M 110 392 L 150 300 L 330 300 L 370 392 Z" fill="#161a23" stroke="#3a4357" stroke-width="2" />
        <rect x="196" y="262" width="88" height="48" rx="10" fill="#1d222d" stroke="#3a4357" stroke-width="2" />
        ${wheelGroup(dev, c, 240, 170, 152)}
        <g transform="translate(386 186) scale(0.92)">${pedalsArt(c)}</g>
        <g transform="translate(432 0) scale(0.86)">${shifterArt(c)}</g>
        </g>
    </svg>`;
}
