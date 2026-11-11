// Gera docs/kalkam_g500.svg e docs/pcyes_w270.svg a partir dos desenhos da interface.
// Uso:  node ferramentas/gerar_desenhos.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const ctx = {};
vm.createContext(ctx);
for (const f of ['wheels.js', 'art.js']) {
    // "const" de nível superior não vira propriedade do contexto; expõe WHEELS manualmente
    const code = fs.readFileSync(path.join(root, 'g500', 'webui', f), 'utf8').replace(/^const WHEELS =/m, 'var WHEELS =');
    vm.runInContext(code, ctx, { filename: f });
}

const out = path.join(root, 'docs');
fs.mkdirSync(out, { recursive: true });
const RED = '#ff2a4b';
for (const [dev, title, file] of [['kalkam', 'Kalkam G500', 'kalkam_g500.svg'], ['pcyes', 'PCyes W270', 'pcyes_w270.svg']]) {
    const svg = ctx.kitArt(dev, RED, { background: '#0b0c10', title });
    fs.writeFileSync(path.join(out, file), svg.trim() + '\n');
    console.log('gerado', path.join('docs', file));
}
