// Interface do G500 Config. Conversa com o Python por window.pywebview.api.
const App = (() => {
    let api = null, init = null, st = null;
    let prof = null, glob = null, device = 'kalkam';
    let lastProfJson = '', lastGlobJson = '', editingUntil = 0;
    let selPin = null, polling = false, builtDevice = null;
    const $ = (s, r = document) => r.querySelector(s);
    const $$ = (s, r = document) => [...r.querySelectorAll(s)];
    const PEDALS = [['clutch', 'Embreagem', 'fa-gear', '#3d9bff'], ['brake', 'Freio', 'fa-stop', '#ff4757'],
                    ['throttle', 'Acelerador', 'fa-gauge', '#2ed573']];
    const FUNCS = [['wheel', 'Volante'], ['throttle', 'Acelerador'], ['brake', 'Freio'], ['clutch', 'Embreagem']];

    // ------------------------------------------------------------ utilidades
    const getPath = (o, p) => p.split('.').reduce((a, k) => (a == null ? a : a[k]), o);
    function toast(msg, error = false) {
        const t = $('#toast');
        $('#toast-text').textContent = msg;
        $('#toast-icon').className = error ? 'fa-solid fa-circle-xmark text-red-400 text-lg' : 'fa-solid fa-circle-check text-brand text-lg';
        t.classList.add('show');
        clearTimeout(t._h);
        t._h = setTimeout(() => t.classList.remove('show'), 2600);
    }
    async function call(name, ...args) {
        const r = await api[name](...args);
        if (r && r.ok === false) { toast(r.error, true); return undefined; }
        return r && typeof r === 'object' && 'ok' in r ? r.data : r;
    }
    const debouncers = {};
    function later(key, fn, ms = 120) { clearTimeout(debouncers[key]); debouncers[key] = setTimeout(fn, ms); }
    const fmt = (v, el) => {
        const scale = Number(el.dataset.scale || 1), fixed = el.dataset.fixed;
        const x = Number(v) * scale;
        return (fixed ? x.toFixed(Number(fixed)) : Math.round(x)) + (el.dataset.suffix || '');
    };

    // ------------------------------------------------------------ diálogos
    function modal(title, bodyHtml, { okText = 'OK', cancel = true } = {}) {
        return new Promise(resolve => {
            $('#modal-title').textContent = title;
            $('#modal-body').innerHTML = bodyHtml;
            $('#modal-ok').textContent = okText;
            $('#modal-cancel').style.display = cancel ? '' : 'none';
            $('#modal').classList.add('open');
            const done = v => { $('#modal').classList.remove('open'); resolve(v); };
            $('#modal-ok').onclick = () => done(true);
            $('#modal-cancel').onclick = () => done(false);
            const inp = $('#modal-body input');
            if (inp) { inp.focus(); inp.select(); inp.onkeydown = e => { if (e.key === 'Enter') done(true); if (e.key === 'Escape') done(false); }; }
        });
    }
    async function ask(title, label, value = '') {
        const esc = String(value).replace(/"/g, '&quot;');
        const ok = await modal(title, `<label class="text-xs text-gray-400 block mb-2">${label}</label><input class="field w-full !text-sm !py-2" id="modal-input" value="${esc}">`);
        return ok ? $('#modal-input').value.trim() : null;
    }
    const confirmBox = (title, text) => modal(title, `<p>${text}</p>`, { okText: 'Confirmar' });

    // ------------------------------------------------------------ ligação dos controles
    function onInput(el, global) {
        const path = global ? el.dataset.g : el.dataset.bind;
        let v;
        if (el.type === 'checkbox') v = el.checked;
        else if (el.type === 'range') v = Number(el.value) / Number(el.dataset.scale || 1);
        else v = el.value;
        editingUntil = Date.now() + 1500;
        const lbl = global ? $(`[data-glabel="${path}"]`) : $(`[data-label="${path}"]`);
        if (lbl) lbl.textContent = fmt(v, lbl);
        const target = global ? glob : prof;
        const keys = path.split('.');
        let o = target; keys.slice(0, -1).forEach(k => { o[k] = o[k] || {}; o = o[k]; }); o[keys.at(-1)] = v;
        renderDerived();
        later(path, () => call(global ? 'set_global' : 'set_value', keys, v), el.type === 'range' ? 120 : 0);
    }
    function wireInputs(root = document) {
        $$('[data-bind]', root).forEach(el => {
            if (el._wired) return; el._wired = true;
            el.addEventListener(el.type === 'range' ? 'input' : 'change', () => onInput(el, false));
        });
        $$('[data-g]', root).forEach(el => {
            if (el._wired) return; el._wired = true;
            el.addEventListener(el.type === 'range' ? 'input' : 'change', () => onInput(el, true));
        });
    }
    function renderBinds() {
        $$('[data-bind]').forEach(el => setInput(el, getPath(prof, el.dataset.bind)));
        $$('[data-g]').forEach(el => setInput(el, getPath(glob, el.dataset.g)));
        $$('[data-label]').forEach(el => { const v = getPath(prof, el.dataset.label); if (v != null) el.textContent = fmt(v, el); });
        $$('[data-glabel]').forEach(el => { const v = getPath(glob, el.dataset.glabel); if (v != null) el.textContent = fmt(v, el); });
        renderDerived();
        renderProfiles();
        renderAxisRows();
        renderPins();
    }
    function setInput(el, v) {
        if (v == null) return;
        if (el.type === 'checkbox') el.checked = !!v;
        else if (el.type === 'range') el.value = Number(v) * Number(el.dataset.scale || 1);
        else el.value = v;
    }

    // ------------------------------------------------------------ cor base da interface
    const COLORS = [['#ff2a4b', 'Vermelho (padrão)'], ['#00f0ff', 'Ciano'], ['#3d8bff', 'Azul'], ['#22e07a', 'Verde'],
                    ['#ff8a1f', 'Laranja'], ['#ffc400', 'Amarelo'], ['#a855f7', 'Roxo'], ['#ff4fa3', 'Rosa'], ['#e5e7eb', 'Branco']];
    let accent = '#ff2a4b';
    const hexRgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
    const shade = (h, f) => '#' + hexRgb(h).map(v => Math.round(v * f).toString(16).padStart(2, '0')).join('');
    function logoSvg(c) {
        return `<svg viewBox="0 0 100 100" class="w-full h-full">
            <defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c}"/><stop offset="1" stop-color="${shade(c, 0.55)}"/></linearGradient></defs>
            <rect x="3" y="3" width="94" height="94" rx="22" fill="url(#lg)"/>
            <circle cx="50" cy="50" r="30" fill="none" stroke="#fff" stroke-width="9"/>
            <path d="M50 50 L22 50 M50 50 L78 50 M50 50 L50 78" stroke="#fff" stroke-width="9" stroke-linecap="round"/>
            <circle cx="50" cy="50" r="12" fill="#fff"/><circle cx="50" cy="50" r="6" fill="${shade(c, 0.7)}"/>
            <rect x="46" y="14" width="8" height="12" rx="3" fill="#ffc400"/></svg>`;
    }
    function applyAccent(c, force = false) {
        if (!c || (c === accent && !force)) return;
        accent = c;
        const [r, g, b] = hexRgb(c);
        document.body.style.setProperty('--brand-primary', c);
        document.body.style.setProperty('--brand-glow', `rgba(${r}, ${g}, ${b}, 0.32)`);
        document.body.style.setProperty('--brand-dark', shade(c, 0.6));
        $('#logo').innerHTML = logoSvg(c);
        if (builtDevice) { const d = builtDevice; builtDevice = null; applyDevice(d); }
    }
    async function pickColor() {
        const before = accent;
        const sw = COLORS.map(([c, n]) => `<button class="swatch ${c === accent ? 'on' : ''}" data-c="${c}" title="${n}" style="background:${c}"></button>`).join('');
        const p = modal('Cor da interface', `<div class="grid grid-cols-9 gap-2 mb-4">${sw}</div>
            <label class="flex items-center justify-between text-xs text-gray-300">Outra cor<input type="color" id="color-free" value="${accent}" class="w-14 h-8 bg-transparent cursor-pointer"></label>
            <p class="hint mt-3">A cor vale para toda a janela e para o logotipo. O padrão é vermelho.</p>`, { okText: 'Usar esta cor' });
        $$('#modal .swatch').forEach(b => b.onclick = () => {
            $$('#modal .swatch').forEach(x => x.classList.toggle('on', x === b));
            $('#color-free').value = b.dataset.c; applyAccent(b.dataset.c);
        });
        $('#color-free').oninput = e => { $$('#modal .swatch').forEach(x => x.classList.remove('on')); applyAccent(e.target.value); };
        if (await p) { glob.accent = accent; await call('set_global', ['accent'], accent); toast('Cor da interface alterada'); }
        else applyAccent(before);
    }

    // ------------------------------------------------------------ proporção (zoom)
    // A interface foi desenhada para ~1600 px de largura; em telas menores reduz sozinha
    // para caber mais coisa. O usuário pode fixar outro valor (salvo nas configurações).
    const ZOOM_MIN = 0.6, ZOOM_MAX = 1.5, ZOOM_STEP = 0.05;
    let zoom = 1;
    const autoZoom = () => Math.max(0.7, Math.min(1, window.innerWidth / 1600));
    function applyZoom(z) {
        zoom = Math.round(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z)) * 100) / 100;
        document.documentElement.style.zoom = zoom;
        // com zoom, 100vh deixaria sobra/corte: a altura da página acompanha a janela
        document.body.style.height = (window.innerHeight / zoom) + 'px';
        // o mapa de botões cabe inteiro na altura da janela (sem precisar rolar)
        const avail = window.innerHeight / zoom - 470;  // cabeçalho, perfil, abas, título do cartão e rodapé
        $('#map-box').style.maxWidth = Math.max(560, avail * 1100 / 720) + 'px';
        $('#zoom-val').textContent = Math.round(zoom * 100) + '%';
        $('#zoom-auto').classList.toggle('on', glob && glob.zoom == null);
        drawCurves();
    }
    function setZoom(z) {
        applyZoom(z);
        glob.zoom = zoom;
        later('zoom', () => call('set_global', ['zoom'], zoom), 250);
    }
    const zoomStep = d => setZoom(zoom + d * ZOOM_STEP);
    function zoomAuto() {
        glob.zoom = null;
        call('set_global', ['zoom'], null);
        applyZoom(autoZoom());
        toast('Proporção automática');
    }
    window.addEventListener('resize', () => applyZoom(glob && glob.zoom != null ? glob.zoom : autoZoom()));
    window.addEventListener('keydown', e => {
        if (!e.ctrlKey) return;
        if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomStep(1); }
        else if (e.key === '-') { e.preventDefault(); zoomStep(-1); }
        else if (e.key === '0') { e.preventDefault(); zoomAuto(); }
    });
    window.addEventListener('wheel', e => {
        if (!e.ctrlKey) return;
        e.preventDefault();
        zoomStep(e.deltaY < 0 ? 1 : -1);
    }, { passive: false });

    // ------------------------------------------------------------ foto ou desenho no seletor de volante
    let artShown = null;
    function renderArt(force = false) {
        const mode = (glob && glob.device_art) || 'photo';
        const key = mode + accent;
        if (key === artShown && !force) return;
        artShown = key;
        $$('.dev-art').forEach(el => {
            const dev = el.dataset.art;
            el.innerHTML = mode === 'drawing'
                ? kitArt(dev, accent).replace('<svg ', '<svg class="art-svg" ')
                : `<img src="${init.devices[dev].photo}" alt="">`;
        });
        const b = $('#btn-art');
        b.querySelector('i').className = (mode === 'drawing' ? 'fa-solid fa-pen-ruler' : 'fa-solid fa-image') + ' text-brand';
        b.querySelector('span').textContent = mode === 'drawing' ? 'Desenho' : 'Foto';
    }
    function toggleArt() {
        glob.device_art = glob.device_art === 'drawing' ? 'photo' : 'drawing';
        call('set_global', ['device_art'], glob.device_art);
        renderArt(true);
    }

    // ------------------------------------------------------------ volante escolhido
    function applyDevice(dev) {
        if (dev === builtDevice) return;
        builtDevice = device = dev;
        $('#wheel-svg').innerHTML = wheelGroup(dev, accent, 200, 200, 196);
        $('#device-badge').textContent = init.devices[dev].badge;
        $$('.device-tab').forEach(b => b.classList.toggle('active', b.dataset.device === dev));
        if (!WHEELS[dev].hotspots.some(h => h.id === selPin)) selPin = WHEELS[dev].hotspots[0].id;
        renderPins();
        drawCurves();
    }

    // ------------------------------------------------------------ construção das partes fixas
    function buildPedals() {
        $('#pedal-bars').innerHTML = PEDALS.map(([k, n, ic, col]) => `
            <div>
                <div class="flex justify-between items-center text-xs font-bold mb-1.5">
                    <span style="color:${col}" class="flex items-center gap-2"><i class="fa-solid ${ic}"></i>${n.toUpperCase()}</span>
                    <span class="font-mono text-white" id="pv-${k}">0%</span>
                </div>
                <div class="pbar"><div class="fill" id="pf-${k}" style="background:linear-gradient(90deg, ${col}aa, ${col})"></div><div class="raw" id="pr-${k}"></div></div>
            </div>`).join('');
        $('#pedal-cards').innerHTML = PEDALS.map(([k, n, ic, col]) => `
            <div class="card !gap-2.5 !p-4">
                <h3 class="card-h" style="color:${col}"><i class="fa-solid ${ic}"></i>${n}</h3>
                <div class="slider-row"><span>Zona morta</span><b data-label="${k}.deadzone" data-scale="100" data-suffix="%"></b>
                    <input type="range" min="0" max="40" data-bind="${k}.deadzone" data-scale="100"></div>
                <div class="slider-row"><span>Saturação</span><b data-label="${k}.saturation" data-scale="100" data-suffix="%"></b>
                    <input type="range" min="50" max="100" data-bind="${k}.saturation" data-scale="100"></div>
                <div class="slider-row"><span>Curva</span><b data-label="${k}.gamma" data-fixed="2"></b>
                    <input type="range" min="0.4" max="3" step="0.05" data-bind="${k}.gamma"></div>
                <canvas id="pc-${k}" width="220" height="110" class="w-full h-24 bg-hub-bg rounded-lg border border-hub-border"></canvas>
            </div>`).join('');
        const order = ['1', '3', '5', 'R', '2', '4', '6', 'N'];
        $('#gear-grid').innerHTML = order.map(g => `<button class="gear-btn ${g === 'R' ? 'r' : ''}" data-gear="${g}">${g}<small></small></button>`).join('');
        $$('#gear-grid .gear-btn').forEach(b => b.onclick = () => learnGear(b.dataset.gear));
        $$('.gear-btn.extra').forEach(b => b.onclick = () => learnExtra(b.dataset.extra));
        $('#raw-buttons').innerHTML = Array.from({ length: 24 }, (_, i) => `<div class="rb" id="rb-${i}">${i}</div>`).join('');
        wireInputs();
    }

    function renderAxisRows() {
        const box = $('#axis-rows');
        if (!box.children.length) {
            box.innerHTML = FUNCS.map(([k, n]) => `
                <div class="flex items-center gap-2 text-xs">
                    <span class="w-24 text-gray-300">${n}</span>
                    <select class="field" data-axis="${k}">
                        <option value="-1">Nenhum</option>${[0, 1, 2, 3, 4, 5, 6, 7].map(i => `<option value="${i}">Eixo ${i}</option>`).join('')}
                    </select>
                    <label class="check !text-xs"><input type="checkbox" class="switch sm" data-invert="${k}">Inverter</label>
                    <button class="btn !py-1.5 ml-auto" onclick="App.detectAxis('${k}')"><i class="fa-solid fa-magnifying-glass"></i>Detectar</button>
                </div>`).join('');
            $$('[data-axis]').forEach(s => s.onchange = () => { prof.axes[s.dataset.axis] = Number(s.value); call('set_value', ['axes', s.dataset.axis], Number(s.value)); });
            $$('[data-invert]').forEach(c => c.onchange = () => { prof.invert[c.dataset.invert] = c.checked; call('set_value', ['invert', c.dataset.invert], c.checked); });
        }
        $$('[data-axis]').forEach(s => s.value = String(prof.axes[s.dataset.axis]));
        $$('[data-invert]').forEach(c => c.checked = !!prof.invert[c.dataset.invert]);
    }

    // ------------------------------------------------------------ perfis
    function renderProfiles() {
        const sel = $('#profile-select');
        const names = st ? st.profiles : init.profiles;
        if (sel._names !== names.join('|')) {
            sel.innerHTML = names.map(n => `<option>${n.replace(/</g, '&lt;')}</option>`).join('');
            sel._names = names.join('|');
        }
        sel.value = prof.name;
        $('#profile-list').innerHTML = names.map(n => {
            const q = n.replace(/"/g, '&quot;'), fixed = n === 'Padrão';
            return `<div class="p-row ${n === prof.name ? 'active' : ''}" data-name="${q}">
                <span class="font-bold ${n === prof.name ? 'text-brand' : 'text-gray-200'}">${n === prof.name ? '<i class="fa-solid fa-circle-check mr-2"></i>' : ''}${n.replace(/</g, '&lt;')}</span>
                <span class="flex items-center gap-1 ml-auto pl-3">
                    <span class="text-gray-500 mr-2">${n === prof.name ? 'ativo' : ''}</span>
                    ${fixed ? '<span class="text-[10px] text-gray-500">fixo</span>' : `
                    <button class="row-btn" data-act="rename" data-name="${q}" title="Renomear"><i class="fa-solid fa-pen"></i></button>
                    <button class="row-btn danger" data-act="delete" data-name="${q}" title="Excluir"><i class="fa-solid fa-trash"></i></button>`}
                </span>
            </div>`;
        }).join('');
        $$('#profile-list .p-row').forEach(it => it.onclick = () => activate(it.dataset.name));
        $$('#profile-list .row-btn').forEach(b => b.onclick = e => {
            e.stopPropagation();
            (b.dataset.act === 'rename' ? renameNamed : deleteNamed)(b.dataset.name);
        });
        $('#exes-profile').textContent = prof.name;
        $('#exe-list').innerHTML = prof.exes.length ? prof.exes.map(e => `<span class="chip">${e}<button data-exe="${e}" title="Remover"><i class="fa-solid fa-xmark"></i></button></span>`).join('')
            : '<span class="hint">Nenhum jogo ligado a este perfil.</span>';
        $$('#exe-list [data-exe]').forEach(b => b.onclick = async () => { await call('exe_remove', b.dataset.exe); });
    }
    async function activate(name) { await call('activate', name); toast(`Perfil "${name}" ativado`); }
    async function profileNew() { const n = await ask('Novo perfil', 'Nome do perfil:'); if (n) { const r = await call('profile_new', n); if (r) toast(`Perfil "${r}" criado`); } }
    async function profileDuplicate() { const n = await ask('Duplicar perfil', 'Nome da cópia:', prof.name + ' (cópia)'); if (n) { const r = await call('profile_duplicate', n); if (r) toast(`Perfil "${r}" criado`); } }
    async function renameNamed(old) {
        if (old === 'Padrão') { toast('O perfil Padrão não pode ser renomeado.', true); return; }
        const n = await ask('Renomear perfil', `Novo nome para "${old}":`, old);
        if (n && n !== old) { const r = await call('profile_rename', n, old); if (r) toast(`Renomeado para "${r}"`); }
    }
    async function deleteNamed(name) {
        if (name === 'Padrão') { toast('O perfil Padrão não pode ser excluído.', true); return; }
        if (await confirmBox('Excluir perfil', `Excluir o perfil "${name}"? Isso não pode ser desfeito (exporte antes, se quiser guardar uma cópia).`)) {
            if (await call('profile_delete', name)) toast(`Perfil "${name}" excluído`);
        }
    }
    const profileRename = () => renameNamed(prof.name);
    const profileDelete = () => deleteNamed(prof.name);
    async function importProfiles() {
        const r = await call('import_profiles'); if (!r) return;
        if (r.imported.length) toast(`${r.imported.length} perfil(is) importado(s)`);
        if (r.errors.length) await modal('Importar', r.errors.join('<br>'), { cancel: false });
    }
    async function exportProfiles(which) { const r = await call('export_profiles', which); if (r) toast(`${r.count} perfil(is) exportado(s)`); }
    async function pickRunning() {
        const list = await call('running_processes'); if (!list) return;
        const ok = await modal('Escolher jogo aberto', `<input class="field w-full mb-2" id="proc-filter" placeholder="Filtrar…">
            <select class="field w-full" size="12" id="proc-list">${list.map(n => `<option>${n}</option>`).join('')}</select>`, { okText: 'Adicionar' });
        if (ok && $('#proc-list').value) { await call('exe_add', $('#proc-list').value); toast('Jogo adicionado'); }
    }
    document.addEventListener('input', e => {
        if (e.target.id === 'proc-filter') { const f = e.target.value.toLowerCase(); $$('#proc-list option').forEach(o => o.hidden = !o.value.includes(f)); }
    });
    async function typeExe() { const n = await ask('Adicionar jogo', 'Nome do executável (ex.: dirt5.exe):'); if (n) { await call('exe_add', n); toast('Jogo adicionado'); } }

    // ------------------------------------------------------------ partes que dependem do perfil
    function renderDerived() {
        const a = Math.round(prof.hw.angle);
        $('#angle-badge').textContent = a + '°';
        $$('.preset[data-angle]').forEach(b => b.classList.toggle('active', Number(b.dataset.angle) === a));
        $('#pedals-on-wheel-note').textContent = prof.hw.pedals_on_wheel
            ? 'As curvas dos pedais estão gravadas no volante: as barras já mostram o resultado final.'
            : 'As curvas abaixo ainda não foram gravadas no volante (valem só no modo compatibilidade até enviar).';
        $$('#gear-grid .gear-btn').forEach(b => {
            const idx = glob.shifter[b.dataset.gear];
            b.querySelector('small').textContent = b.dataset.gear === 'N' ? '' : (idx == null ? '—' : 'B' + idx);
        });
        $$('.gear-btn.extra').forEach(b => {
            const idx = (glob.shifter_extra || {})[b.dataset.extra];
            b.querySelector('small').textContent = idx == null ? '—' : 'B' + idx;
        });
        drawCurves();
    }
    function setAngle(v) {
        prof.hw.angle = v;
        $(`[data-bind="hw.angle"]`).value = v;
        $(`[data-label="hw.angle"]`).textContent = v;
        renderDerived();
        call('set_value', ['hw', 'angle'], v);
    }

    // ------------------------------------------------------------ curvas
    function curvePedal(x, c) {
        const dz = c.deadzone, sat = Math.max(c.saturation, dz + 0.01);
        return Math.pow(Math.min(1, Math.max(0, (x - dz) / (sat - dz))), c.gamma);
    }
    function curveWheel(x, c) {
        const a = Math.abs(x); if (a <= c.deadzone) return 0;
        const y = Math.pow((a - c.deadzone) / (1 - c.deadzone), c.gamma); return x < 0 ? -y : y;
    }
    function plot(cv, fn, x0, color, dotX) {
        if (!cv) return;
        const ctx = cv.getContext('2d'), w = cv.width, h = cv.height, p = 8;
        ctx.clearRect(0, 0, w, h);
        ctx.strokeStyle = '#242b3b'; ctx.lineWidth = 1; ctx.beginPath();
        for (let i = 1; i < 4; i++) { ctx.moveTo(p + (w - 2 * p) * i / 4, p); ctx.lineTo(p + (w - 2 * p) * i / 4, h - p); ctx.moveTo(p, p + (h - 2 * p) * i / 4); ctx.lineTo(w - p, p + (h - 2 * p) * i / 4); }
        ctx.stroke();
        ctx.strokeStyle = '#3a4357'; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(p, h - p); ctx.lineTo(w - p, p); ctx.stroke(); ctx.setLineDash([]);
        const X = x => p + (x - x0) / (1 - x0) * (w - 2 * p), Y = y => h - p - (y - x0) / (1 - x0) * (h - 2 * p);
        ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.beginPath();
        for (let i = 0; i <= 100; i++) { const x = x0 + (1 - x0) * i / 100; i ? ctx.lineTo(X(x), Y(fn(x))) : ctx.moveTo(X(x), Y(fn(x))); }
        ctx.stroke();
        if (dotX != null) { ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(X(dotX), Y(fn(dotX)), 4, 0, 7); ctx.fill(); }
    }
    function drawCurves() {
        if (!prof) return;
        const color = getComputedStyle(document.body).getPropertyValue('--brand-primary').trim() || '#00f0ff';
        const half = (prof.wheel.hw_angle || 900) / 2;
        const wx = st ? Math.max(-1, Math.min(1, st.wheel_deg / half)) : null;
        plot($('#steer-curve'), x => curveWheel(x, prof.wheel), -1, color, wx);
        PEDALS.forEach(([k, , , col]) => plot($('#pc-' + k), x => curvePedal(x, prof[k]), 0, col, st ? st.raw_pedals[k] : null));
    }

    // ------------------------------------------------------------ botões / pinos
    // Mapa no estilo G HUB: desenho no centro, etiquetas nas laterais ligadas por linhas.
    const MAP = { w: 1100, h: 720, cx: 550, cy: 372, r: 285, colL: [0, 262], colR: [838, 1100] };
    function mapPoint(dev, x, y) {
        const n = WHEELS[dev].native, k = MAP.r / n.r;
        return [MAP.cx + (x - n.cx) * k, MAP.cy + (y - n.cy) * k, k];
    }
    function calloutLayout(dev) {
        const out = [];
        for (const side of ['L', 'R']) {
            const items = WHEELS[dev].hotspots.filter(h => h.side === side).sort((a, b) => a.y - b.y);
            const top = 48, bottom = MAP.h - 48, step = items.length > 1 ? (bottom - top) / (items.length - 1) : 0;
            items.forEach((h, i) => out.push({ h, side, y: items.length > 1 ? top + i * step : MAP.h / 2 }));
        }
        return out;
    }
    function renderPins() {
        if (!prof || !builtDevice) return;
        const spots = WHEELS[device].hotspots, map = (glob.hotspots[device] || {});
        const xboxOf = phys => Object.entries(prof.compat.buttons).find(([, v]) => v === phys && phys != null)?.[0];
        if (!spots.some(h => h.id === selPin)) selPin = spots[0].id;
        const lay = calloutLayout(device);
        // linhas e anéis (SVG) + desenho
        let lines = '', rings = '';
        lay.forEach(({ h, side, y }) => {
            const [bx, by, k] = mapPoint(device, h.x, h.y);
            const ax = side === 'L' ? MAP.colL[1] : MAP.colR[0], ex = side === 'L' ? ax + 40 : ax - 40;
            const sel = h.id === selPin ? ' sel' : '';
            lines += `<polyline class="lead${sel}" data-pin="${h.id}" points="${ax},${y} ${ex},${y} ${bx},${by}" />`;
            rings += `<circle class="ring${sel}" data-pin="${h.id}" cx="${bx}" cy="${by}" r="${h.r * k + 6}" />`;
        });
        $('#map-svg').innerHTML = `<g opacity="0.92">${wheelGroup(device, accent, MAP.cx, MAP.cy, MAP.r)}</g>${lines}${rings}`;
        // etiquetas (HTML)
        $('#pins').innerHTML = lay.map(({ h, side, y }) => {
            const phys = map[h.id], x0 = h.hat ? '' : xboxOf(phys), xb = x0 && x0 !== h.short ? x0 : '';
            const num = h.hat ? '✥' : (phys == null ? '?' : phys);
            const left = (side === 'L' ? MAP.colL[0] : MAP.colR[0]) / MAP.w * 100;
            const width = (MAP.colL[1] - MAP.colL[0]) / MAP.w * 100;
            return `<button class="callout ${side} ${h.id === selPin ? 'sel' : ''} ${phys == null && !h.hat ? 'unset' : ''}"
                data-pin="${h.id}" title="${h.label}" style="left:${left}%;width:${width}%;top:${y / MAP.h * 100}%">
                <span class="num">${num}</span><span class="lbl">${h.short}</span>${xb ? `<span class="xb" title="No modo compatibilidade vira Xbox ${xb}"><i class="fa-brands fa-xbox"></i>${xb}</span>` : ''}</button>`;
        }).join('');
        $$('#pins .callout, #map-svg .ring').forEach(el => el.onclick = () => { selPin = el.dataset.pin; renderPins(); });
        // painel do botão selecionado
        const sel = spots.find(h => h.id === selPin);
        const phys = map[sel.id];
        $('#pin-label').textContent = sel.label;
        $('#pin-phys').textContent = sel.hat ? 'direcional (vira o D-pad do Xbox)' : phys == null ? 'não definido' : 'Botão ' + phys;
        $('#pin-detect').disabled = !!sel.hat;
        const xs = $('#pin-xbox');
        if (!xs.children.length) xs.innerHTML = '<option value="">— nenhum —</option>' + init.xbox_buttons.map(b => `<option value="${b}">${b}</option>`).join('');
        xs.value = xboxOf(phys) || '';
        xs.disabled = !!sel.hat;
        $('#pin-list').innerHTML = spots.map(h => {
            const ph = map[h.id], xb = xboxOf(ph);
            return `<div class="p-row ${h.id === selPin ? 'active' : ''}" data-pin="${h.id}">
                <span class="font-bold text-gray-300">${h.label}</span>
                <span class="font-mono text-brand">${h.hat ? 'direcional' : (ph == null ? '—' : 'B' + ph)}${xb ? ' · Xbox ' + xb : ''}</span></div>`;
        }).join('');
        $$('#pin-list .p-row').forEach(r => r.onclick = () => { selPin = r.dataset.pin; renderPins(); });
        const ex = glob.shifter_extra || {};
        const chips = [['park', 'P · Freio de mão', ex.park], ...init.gears.map(g => ['g' + g, g === 'R' ? 'Ré' : g + 'ª', glob.shifter[g]]), ['range', 'LO / HI', ex.range]];
        $('#shifter-chips').innerHTML = chips.map(([k, n, idx]) =>
            `<span class="chip !pr-3" data-chip="${k}">${n}<b class="text-brand">${idx == null ? '—' : 'B' + idx}</b></span>`).join('');
    }
    function updatePins(s) {
        const map = glob.hotspots[device] || {};
        const pressed = id => {
            const h = WHEELS[device].hotspots.find(x => x.id === id);
            if (h && h.hat) return !!s.hat;
            const i = map[id];
            return i != null && !!s.buttons[i];
        };
        $$('#pins .callout, #map-svg .ring, #map-svg .lead').forEach(el => el.classList.toggle('pressed', pressed(el.dataset.pin)));
    }
    async function detectPin() { await call('start_detect', 'button', ['hotspot', device, selPin]); }
    async function setPinXbox(x) {
        const phys = (glob.hotspots[device] || {})[selPin];
        if (phys == null) { toast('Primeiro detecte qual botão físico é este.', true); renderPins(); return; }
        for (const [k, v] of Object.entries(prof.compat.buttons)) {
            if (v === phys && k !== x) { prof.compat.buttons[k] = null; await call('set_value', ['compat', 'buttons', k], null); }
        }
        if (x) { prof.compat.buttons[x] = phys; await call('set_value', ['compat', 'buttons', x], phys); }
        renderPins();
        toast(x ? `Botão ${phys} → Xbox ${x}` : 'Mapeamento removido');
    }
    async function learnExtra(k) {
        $$('.gear-btn').forEach(b => b.classList.toggle('learn', b.dataset.extra === k));
        toast(k === 'park' ? 'Aperte o botão P (freio de mão) no câmbio…' : 'Aperte o botão LO/HI no câmbio…');
        await call('start_detect', 'button', ['extra', k]);
    }
    async function resetMapping() {
        if (await confirmBox('Resetar mapeamento', 'Voltar ao padrão os botões do volante, as marchas (16–21, ré 22), o Park (15), a caixa alta/baixa (23) e os botões de Xbox do perfil ativo?')) {
            if (await call('reset_mapping', device)) toast('Mapeamento restaurado');
        }
    }
    async function learnGear(g) {
        if (g === 'N') return;
        $$('.gear-btn').forEach(b => b.classList.toggle('learn', b.dataset.gear === g));
        toast(`Engate a marcha ${g} no câmbio…`);
        await call('start_detect', 'button', ['gear', g]);
    }

    // ------------------------------------------------------------ overlay
    function overlaySize(o) {
        const n = Math.max(1, ['clutch', 'brake', 'throttle'].filter(k => o.show[k]).length), s = o.scale;
        return o.orientation === 'horizontal'
            ? [(20 + (o.labels ? 18 : 0) + 180 + (o.percent ? 40 : 0)) * s, (20 + n * 16 + (n - 1) * 8) * s]
            : [(20 + n * 22 + (n - 1) * 10) * s, (20 + (o.percent ? 16 : 0) + 120 + (o.labels ? 16 : 0)) * s];
    }
    function overlayCorner(c) {
        const o = glob.overlay, [w, h] = overlaySize(o), [sw, sh] = st ? st.screen : [1920, 1080], m = 24;
        o.x = Math.round(c[1] === 'l' ? m : sw - w - m);
        o.y = Math.round(c[0] === 't' ? m : sh - h - m - 40);
        call('set_global', ['overlay', 'x'], o.x); call('set_global', ['overlay', 'y'], o.y);
        renderBinds();
    }
    function renderOverlayPreview(v) {
        const o = glob.overlay, keys = ['clutch', 'brake', 'throttle'].filter(k => o.show[k]);
        const col = { clutch: '#3d9bff', brake: '#ff4757', throttle: '#2ed573' }, lab = { clutch: 'E', brake: 'F', throttle: 'A' };
        const s = o.scale;
        let html;
        if (o.orientation === 'horizontal') {
            html = keys.map(k => `<div style="display:flex;align-items:center;gap:${6 * s}px;margin:${4 * s}px 0">
                ${o.labels ? `<b style="width:${12 * s}px;color:#cbd5e1;font-size:${11 * s}px">${lab[k]}</b>` : ''}
                <div style="width:${180 * s}px;height:${16 * s}px;background:#262b36"><div style="height:100%;width:${v[k] * 100}%;background:${col[k]}"></div></div>
                ${o.percent ? `<span style="width:${36 * s}px;color:#f1f5f9;font-size:${11 * s}px">${Math.round(v[k] * 100)}%</span>` : ''}</div>`).join('');
        } else {
            html = `<div style="display:flex;gap:${10 * s}px">` + keys.map(k => `<div style="display:flex;flex-direction:column;align-items:center;gap:${3 * s}px">
                ${o.percent ? `<span style="color:#f1f5f9;font-size:${10 * s}px">${Math.round(v[k] * 100)}</span>` : ''}
                <div style="width:${22 * s}px;height:${120 * s}px;background:#262b36;display:flex;align-items:flex-end"><div style="width:100%;height:${v[k] * 100}%;background:${col[k]}"></div></div>
                ${o.labels ? `<b style="color:#cbd5e1;font-size:${10 * s}px">${lab[k]}</b>` : ''}</div>`).join('') + '</div>';
        }
        const box = $('#ov-preview');
        box.style.cssText = `background:#12151c;padding:${10 * s}px;opacity:${o.opacity};font-family:Inter;transform:scale(${Math.min(1, 200 / (overlaySize(o)[1] || 1))});transform-origin:center`;
        box.innerHTML = html;
    }

    // ------------------------------------------------------------ atualização ao vivo
    function setBadge(el, b) {
        el.className = 'badge ' + b.state;
        const ico = { ok: '<i class="fa-solid fa-check"></i>', fail: '<i class="fa-solid fa-xmark"></i>', dirty: '!', pending: '' }[b.state] || '';
        el.innerHTML = `<span class="ico">${ico}</span><span>${b.text}</span>`;
    }
    function update(s) {
        st = s;
        // perfil / configurações gerais mudaram no Python (troca de perfil, leitura do volante, detecção…)
        const pj = JSON.stringify(s.profile), gj = JSON.stringify(s.glob);
        if ((pj !== lastProfJson || gj !== lastGlobJson) && Date.now() > editingUntil) {
            const switched = !prof || prof.name !== s.profile.name;
            prof = s.profile; glob = s.glob; lastProfJson = pj; lastGlobJson = gj;
            renderBinds();
            if (switched && lastProfJson) $('#auto-tag').classList.toggle('hidden', !s.auto_active);
        } else if ($('#profile-select')._names !== s.profiles.join('|')) {
            renderProfiles();  // perfil criado, renomeado ou excluído sem trocar o ativo
        }
        $('#auto-tag').classList.toggle('hidden', !s.auto_active);
        if (!$('#modal').classList.contains('open')) applyAccent(glob.accent);  // não desfaz a prévia da escolha de cor
        renderArt();
        applyDevice(glob.device === 'auto' ? s.device : glob.device);
        $$('.device-tab').forEach(b => b.querySelector('.det').textContent = b.dataset.device === s.device_detected ? '● conectado' : '');
        $('#btn-auto').classList.toggle('auto-on', glob.device === 'auto');

        // conexões
        $('#usb-dot').className = 'dot ' + (s.usb.connected ? 'on' : 'off');
        $('#usb-text').textContent = s.usb.connected ? s.usb.name : 'Volante não conectado';
        const b = s.ble;
        $('#bt-dot').className = 'dot ' + (b.connected ? 'on' : b.busy ? 'busy' : 'off');
        $('#bt-text').textContent = b.connected ? 'Bluetooth conectado' : b.busy ? b.status : (b.status.startsWith('erro') || b.status.startsWith('volante não') ? b.status : 'Bluetooth desconectado');
        const btBtn = $('#bt-connect');
        btBtn.textContent = b.connected ? 'Desconectar' : 'Conectar';
        btBtn.disabled = b.busy && !b.connected;
        $('#fw-tag').textContent = b.info.version != null ? 'v' + b.info.version : '—';
        $('#mode-tag').textContent = b.info.mode_name || '—';
        $('#mode-now').textContent = b.info.mode_name || 'conecte o Bluetooth';
        $('#msg-line').textContent = s.detect || s.message || '';

        // sentir os ajustes
        $('#preview-status').textContent = !glob.preview ? 'desligado' : s.preview ? 'motor ligado agora'
            : s.preview_paused ? 'pausado (' + s.preview_paused + ')' : s.usb.connected ? 'aguardando…' : 'sem volante';

        Object.entries(s.badges).forEach(([k, v]) => $$(`[data-badge="${k}"]`).forEach(el => setBadge(el, v)));

        // volante
        const deg = s.wheel_deg;
        $('#wheel-wrap').style.transform = `rotate(${deg}deg)`;
        $('#angle-now').textContent = Math.round(deg) + '°';
        $('#steer-out').textContent = s.wheel.toFixed(2);
        const out = Math.max(-1, Math.min(1, s.wheel)), bar = $('#steer-bar');
        bar.style.left = out < 0 ? (50 + out * 50) + '%' : '50%';
        bar.style.width = Math.abs(out) * 50 + '%';

        // pedais
        PEDALS.forEach(([k]) => {
            const v = s.pedals[k] || 0;
            $('#pv-' + k).textContent = Math.round(v * 100) + '%';
            $('#pf-' + k).style.width = v * 100 + '%';
            $('#pr-' + k).style.left = `calc(3px + ${(s.raw_pedals[k] || 0) * 100}% - ${(s.raw_pedals[k] || 0) * 6}px)`;
        });
        $('#axes-raw').textContent = s.axes.length ? 'Eixos: ' + s.axes.join('  ') : '';
        $('#gear-now').textContent = 'MARCHA: ' + s.gear;
        $$('#gear-grid .gear-btn').forEach(g => g.classList.toggle('on', g.dataset.gear === s.gear));
        $$('.gear-btn.extra').forEach(b => b.classList.toggle('on', !!(s.shifter_extra || {})[b.dataset.extra]));
        $$('#shifter-chips [data-chip]').forEach(c => {
            const k = c.dataset.chip;
            const on = k === 'park' || k === 'range' ? !!(s.shifter_extra || {})[k] : s.gear === k.slice(1);
            c.classList.toggle('chip-on', on);
        });
        if (!s.detect) $$('.gear-btn.learn').forEach(g => g.classList.remove('learn'));
        drawCurves();

        // botões
        s.buttons.forEach((on, i) => { const el = $('#rb-' + i); if (el) el.classList.toggle('on', !!on); });
        const map = glob.hotspots[device] || {};
        updatePins(s);
        const hat = s.hat, dirs = [[1, 'cima'], [2, 'direita'], [4, 'baixo'], [8, 'esquerda']].filter(([bit]) => hat & bit).map(([, n]) => n);
        $('#hat-text').textContent = 'Direcional: ' + (dirs.join(' + ') || 'solto');

        // force feedback / compatibilidade
        $('#ffb-error').textContent = s.ffb_error ? 'Erro no force feedback: ' + s.ffb_error : '';
        $('#compat-error').textContent = s.compat_error ? 'Controle virtual: ' + s.compat_error : '';
        $('#vigem-text').innerHTML = s.svc.vigem ? '<i class="fa-solid fa-circle-check text-emerald-400 mr-2"></i>Driver do controle virtual (ViGEmBus) instalado'
            : '<i class="fa-solid fa-circle-exclamation text-amber-400 mr-2"></i>Driver do controle virtual (ViGEmBus) não instalado';
        $('#vigem-btn').style.display = s.svc.vigem ? 'none' : '';
        $('#hidhide-text').innerHTML = s.svc.hidhide ? '<i class="fa-solid fa-circle-check text-emerald-400 mr-2"></i>HidHide instalado (oculte o volante nele e libere o G500 Config)'
            : '<i class="fa-solid fa-circle-info text-gray-400 mr-2"></i>Recomendado: HidHide, para o jogo não ver o volante e o controle virtual juntos';

        // overlay
        $('#ov-x').max = s.screen[0]; $('#ov-y').max = s.screen[1];
        renderOverlayPreview(s.pedals);
        $('#ov-status').textContent = glob.overlay.enabled ? (s.overlay_running ? 'Overlay ativo na tela.' : 'Iniciando overlay…') : 'Overlay desligado.';
    }

    async function poll() {
        if (polling) return;
        polling = true;
        try { const s = await api.state(); if (s && !s.error) update(s); }
        catch (e) { /* janela fechando */ }
        finally { polling = false; }
    }

    // ------------------------------------------------------------ início
    async function start() {
        api = window.pywebview.api;
        init = await call('init');
        prof = init.profile; glob = init.glob;
        $('#app-version').textContent = 'v' + init.version;
        buildPedals();
        applyAccent(glob.accent || '#ff2a4b', true);
        applyZoom(glob.zoom != null ? glob.zoom : autoZoom());
        renderArt(true);
        applyDevice(glob.device === 'auto' ? 'kalkam' : glob.device);
        renderBinds();
        $$('.tab-btn').forEach(b => b.onclick = () => showTab(b.dataset.tab));
        showTab(localStorage.getItem('tab') || 'steering');
        setInterval(poll, 50);
        api.ui_ready();
    }
    function showTab(t) {
        $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
        $$('.tab-content').forEach(c => c.classList.toggle('hidden', c.dataset.tab !== t));
        try { localStorage.setItem('tab', t); } catch (e) { /* sem armazenamento */ }
    }
    window.addEventListener('pywebviewready', start);

    return {
        call, activate, profileNew, profileDuplicate, profileRename, profileDelete, importProfiles, exportProfiles,
        pickRunning, typeExe, setAngle, pickColor, resetMapping, zoomStep, zoomAuto, toggleArt, detectPin, setPinXbox, overlayCorner,
        setDevice: d => { glob.device = d; builtDevice = null; call('set_global', ['device'], d); applyDevice(d === 'auto' ? (st ? st.device : 'kalkam') : d); },
        bleConnect: () => (st && st.ble.connected ? call('ble_disconnect') : call('ble_connect')),
        bleRead: () => call('ble_read'),
        sendHw: () => call('send_hw'),
        sendPedals: linear => call('send_pedals', linear),
        detectAxis: k => call('start_detect', 'axis', [k]),
        calibrate: async () => { if (await confirmBox('Calibrar', 'Ao confirmar, durante 10 segundos: gire o volante até os dois batentes, pise fundo em cada pedal e termine com o volante no centro e os pedais soltos.')) call('calibrate'); },
        ffbTest: (k, d) => call('ffb_test', k, d || 0),
        switchMode: async m => { if (await confirmBox('Modo USB', `Mudar o volante para ${init.modes[m]}? Ele vai se reconectar no USB com outra identidade; dá para voltar por aqui.`)) { if (await call('switch_mode', m)) toast('Modo enviado ao volante'); } },
        factoryReset: async () => { if (await confirmBox('Padrão de fábrica', 'Restaurar todas as configurações do volante (ângulo, forças, botões e curvas) para o padrão de fábrica?')) { if (await call('factory_reset')) toast('Restaurando padrão de fábrica…'); } },
        installVigem: async () => { if (await confirmBox('Driver do controle virtual', 'Instalar o driver ViGEmBus? O Windows vai pedir permissão de administrador.')) { await call('install_vigem'); setTimeout(() => call('refresh_services'), 15000); } },
    };
})();
