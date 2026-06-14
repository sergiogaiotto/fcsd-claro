// ============================
// Fale com Seus Dados v2.1 — New Features
// ============================

// --- DataMart state ---
let userDatamarts = [];
let allDatamarts = [];

// --- DiamondLayer state (mirror of DataMart) ---
let userDiamondLayers = [];
let allDiamondLayers = [];
// Expose so non-module code (default.html) can read for inline rendering
window.userDiamondLayers = userDiamondLayers;
window.allDiamondLayers = allDiamondLayers;

async function loadDatamarts() {
    try {
        const res = await fetch('/api/datamarts');
        if (res.ok) allDatamarts = await res.json();
        populateUploadDatamart();
    } catch(e) {}
}

async function loadUserDatamarts() {
    try {
        const res = await fetch('/api/datamarts/user');
        if (res.ok) userDatamarts = await res.json();
        renderDatamartSelector();
    } catch(e) {}
}

async function loadDiamondLayers() {
    try {
        const res = await fetch('/api/diamond-layers');
        if (res.ok) {
            allDiamondLayers = await res.json();
            window.allDiamondLayers = allDiamondLayers;
        }
    } catch(e) {}
}

async function loadUserDiamondLayers() {
    try {
        const res = await fetch('/api/diamond-layers/user');
        if (res.ok) {
            userDiamondLayers = await res.json();
            window.userDiamondLayers = userDiamondLayers;
        }
        renderDiamondLayerSelector();
    } catch(e) {}
}

function renderDiamondLayerSelector() {
    const container = document.getElementById('diamondLayerSelector');
    if (!container || !userDiamondLayers.length) return;
    let html = '<span class="text-[10px] text-fg-muted uppercase tracking-wider mr-1">DiamondLayers</span>';
    html += userDiamondLayers.map(dl =>
        `<label class="inline-flex items-center gap-1.5 text-xs bg-fg-700 border border-fg-border rounded-full px-2.5 py-1 cursor-pointer hover:border-fg-blue transition">
            <input type="checkbox" value="${dl.id}" class="dl-check accent-[#58a6ff] w-3 h-3" checked>
            <span class="text-fg-text">${escapeHtml(dl.name)}</span>
        </label>`
    ).join('');
    container.innerHTML = html;
    container.classList.remove('hidden');
}

function getSelectedDiamondLayerIds() {
    return Array.from(document.querySelectorAll('.dl-check:checked')).map(c => parseInt(c.value));
}

function populateUploadDatamart() {
    const sel = document.getElementById('uploadDatamart');
    if (!sel) return;
    sel.innerHTML = '<option value="">Escolha o DataMart</option>'
        + allDatamarts.map(dm => `<option value="${dm.name}">${escapeHtml(dm.name)}</option>`).join('');
}

function renderDatamartSelector() {
    const container = document.getElementById('datamartSelector');
    if (!container || !userDatamarts.length) return;
    let html = '<span class="text-[10px] text-fg-muted uppercase tracking-wider mr-1">DataMarts</span>';
    html += userDatamarts.map(dm =>
        `<label class="inline-flex items-center gap-1.5 text-xs bg-fg-700 border border-fg-border rounded-full px-2.5 py-1 cursor-pointer hover:border-fg-blue transition">
            <input type="checkbox" value="${dm.id}" class="dm-check accent-[#58a6ff] w-3 h-3" checked>
            <span class="text-fg-text">${escapeHtml(dm.name)}</span>
        </label>`
    ).join('');
    container.innerHTML = html;
    container.classList.remove('hidden');
}

function getSelectedDatamartIds() {
    return Array.from(document.querySelectorAll('.dm-check:checked')).map(c => parseInt(c.value));
}

// --- Chart submenu ---
let chartMenuOpen = false;

async function openChartMenu(btn) {
    if (chartMenuOpen) { closeChartMenu(); return; }
    if (!lastQueryData || !lastQueryData.rows || !lastQueryData.rows.length) {
        alert('Sem dados para gráfico.'); return;
    }
    let options;
    try {
        const res = await fetch('/api/chart/options', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(lastQueryData),
        });
        const data = await res.json();
        options = data.options || [];
    } catch(e) {
        options = [
            {type:'auto',label:'Auto (LLM)',icon:'*',suitable:true},
            {type:'bar',label:'Barras',icon:'||',suitable:true},
            {type:'line',label:'Linhas',icon:'/\\',suitable:true},
            {type:'scatter',label:'Dispersao',icon:'.:',suitable:true},
            {type:'area',label:'Area',icon:'~',suitable:true},
            {type:'pie',label:'Pizza',icon:'O',suitable:true},
            {type:'doughnut',label:'Rosca',icon:'()',suitable:true},
            {type:'radar',label:'Radar',icon:'<>',suitable:true},
            {type:'polarArea',label:'Polar',icon:'+',suitable:true},
        ];
    }
    showChartPopup(btn, options);
}

function showChartPopup(btn, options) {
    closeChartMenu();
    const menu = document.createElement('div');
    menu.id = 'chartSubmenu';
    menu.className = 'fixed z-50 bg-[#161b22] border border-[#30363d] rounded-xl shadow-2xl p-1.5 min-w-[170px]';
    menu.style.animation = 'fadeIn 0.2s';
    const rect = btn.getBoundingClientRect();
    menu.style.left = rect.left + 'px';
    menu.style.bottom = (window.innerHeight - rect.top + 4) + 'px';
    menu.innerHTML = options.map(o => {
        const cls = o.suitable
            ? 'text-[#c9d1d9] hover:bg-[rgba(255,99,71,0.15)] hover:text-[#ff6347] cursor-pointer'
            : 'text-[#484f58] cursor-not-allowed';
        return `<div onclick="${o.suitable ? "openTypedChart('" + o.type + "')" : ''}"
            class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition ${cls}">
            <span class="w-4 text-center">${o.icon}</span><span>${o.label}</span>
        </div>`;
    }).join('');
    document.body.appendChild(menu);
    chartMenuOpen = true;
    setTimeout(() => document.addEventListener('click', _closeChartClick), 10);
}

function closeChartMenu() {
    const m = document.getElementById('chartSubmenu');
    if (m) m.remove();
    chartMenuOpen = false;
    document.removeEventListener('click', _closeChartClick);
}

function _closeChartClick(e) {
    if (!e.target.closest('#chartSubmenu') && !e.target.closest('.chart-menu-btn')) closeChartMenu();
}

// ──────────────────────────────────────────────────────────────────────────
// FIX: openTypedChart agora passa sql_no_limit e usa getFullData()
// para que o combobox LIMITE na página do gráfico funcione corretamente.
// ──────────────────────────────────────────────────────────────────────────
async function openTypedChart(type) {
    closeChartMenu();
    const data = await getFullData();
    if (!data || !data.rows || !data.rows.length) { alert('Sem dados.'); return; }
    postToNewTab('/api/chart/open', {
        json_data: JSON.stringify(data),
        chart_type: type,
        sql_no_limit: lastSqlNoLimit || '',
    });
    appendMessage('assistant',
        '<div class="flex items-center gap-2 text-sm"><span class="text-[#39d353]">&#x2713;</span> Gráfico <strong>' + type + '</strong> — <strong>' + data.rows.length.toLocaleString('pt-BR') + '</strong> registros.</div>', true);
}

// --- User Export/Import ---
async function exportUsers() {
    const res = await fetch('/api/users/export');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'users_export.xlsx'; a.click();
    URL.revokeObjectURL(url);
}

async function importUsers() {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.xlsx,.xls';
    input.onchange = async () => {
        const fd = new FormData(); fd.append('file', input.files[0]);
        try {
            const res = await fetch('/api/users/import', { method: 'POST', body: fd });
            const d = await res.json();
            alert('Importados: ' + d.total + (d.errors.length ? '\nErros: ' + d.errors.join('; ') : ''));
            loadUsers();
        } catch(e) { alert('Erro: ' + e.message); }
    };
    input.click();
}

// --- Skill Export/Import ---
async function exportSkills() {
    const res = await fetch('/api/skills/export/excel');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'skills_export.xlsx'; a.click();
    URL.revokeObjectURL(url);
}

async function importSkills() {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.xlsx,.xls';
    input.onchange = async () => {
        const fd = new FormData(); fd.append('file', input.files[0]);
        try {
            const res = await fetch('/api/skills/import', { method: 'POST', body: fd });
            const d = await res.json();
            alert('Importados: ' + d.total + (d.errors.length ? '\nErros: ' + d.errors.join('; ') : ''));
            loadSkills();
        } catch(e) { alert('Erro: ' + e.message); }
    };
    input.click();
}

// --- DataMart Admin ---
async function loadDatamartsAdmin() {
    await loadDatamarts();
    const el = document.getElementById('datamartAdminList');
    if (!el) return;
    if (!allDatamarts.length) { el.innerHTML = '<p class="text-xs text-[#8b949e]">Nenhum DataMart.</p>'; return; }
    el.innerHTML = allDatamarts.map(dm => {
        const tbl = (dm.tables || []).join(', ') || 'nenhuma';
        return `<div class="bg-[#0a0c10] rounded-lg px-3 py-2.5 border border-[#30363d] group hover:border-[rgba(88,166,255,0.3)] transition">
            <div class="flex items-center justify-between">
                <span class="text-sm text-[#58a6ff] font-mono font-bold">${escapeHtml(dm.name)}</span>
                <div class="flex items-center gap-2">
                    <span class="text-[10px] text-[#8b949e]">${(dm.tables||[]).length} tabelas</span>
                    ${dm.name !== 'default' ? '<button onclick="deleteDatamart(' + dm.id + ')" class="text-[#8b949e] hover:text-red-400 opacity-0 group-hover:opacity-100 transition text-[10px]">excluir</button>' : ''}
                </div>
            </div>
            <p class="text-[10px] text-[#8b949e] mt-1 font-mono truncate">${escapeHtml(tbl)}</p>
        </div>`;
    }).join('');
}

async function createDatamart() {
    const name = prompt('Nome do novo DataMart:');
    if (!name || name.length < 2) return;
    try {
        const res = await fetch('/api/datamarts', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ name, description: '' }),
        });
        if (!res.ok) { const e = await res.json(); alert(e.detail || 'Erro'); return; }
        loadDatamartsAdmin(); loadUserDatamarts();
    } catch(e) { alert('Erro: ' + e.message); }
}

async function deleteDatamart(id) {
    if (!confirm('Excluir este DataMart?')) return;
    try { await fetch('/api/datamarts/' + id, { method: 'DELETE' }); loadDatamartsAdmin(); loadUserDatamarts(); }
    catch(e) { alert('Erro: ' + e.message); }
}

// --- User form DataMart checkboxes ---
function renderUserFormDatamarts(selectedIds) {
    const el = document.getElementById('userFormDatamarts');
    if (!el) return;
    const ids = new Set(selectedIds || []);
    el.innerHTML = allDatamarts.map(dm =>
        `<label class="inline-flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="checkbox" value="${dm.id}" class="uf-dm-check accent-[#58a6ff] w-3 h-3" ${ids.has(dm.id) ? 'checked' : ''}>
            <span>${escapeHtml(dm.name)}</span>
        </label>`
    ).join('');
}

function getUserFormDatamartIds() {
    return Array.from(document.querySelectorAll('.uf-dm-check:checked')).map(c => parseInt(c.value));
}

// --- DiamondLayer Admin (mirror of DataMart Admin) ---
async function loadDiamondLayersAdmin() {
    await loadDiamondLayers();
    const el = document.getElementById('diamondLayerAdminList');
    if (!el) return;
    if (!allDiamondLayers.length) { el.innerHTML = '<p class="text-xs text-[#8b949e]">Nenhuma DiamondLayer.</p>'; return; }
    el.innerHTML = allDiamondLayers.map(dl => {
        const tables = (dl.tables || []);
        const tblNames = tables.map(t => t.name).join(', ') || 'nenhuma';
        return `<div class="bg-[#0a0c10] rounded-lg px-3 py-2.5 border border-[#30363d] group hover:border-[rgba(88,166,255,0.3)] transition">
            <div class="flex items-center justify-between">
                <span class="text-sm text-[#58a6ff] font-mono font-bold">${escapeHtml(dl.name)}</span>
                <div class="flex items-center gap-2">
                    <span class="text-[10px] text-[#8b949e]">${tables.length} tabelas</span>
                    <button onclick="deleteDiamondLayer(${dl.id})" class="text-[#8b949e] hover:text-red-400 opacity-0 group-hover:opacity-100 transition text-[10px]">excluir</button>
                </div>
            </div>
            <p class="text-[10px] text-[#8b949e] mt-1 font-mono truncate">${escapeHtml(tblNames)}</p>
        </div>`;
    }).join('');
}

async function createDiamondLayer() {
    const name = prompt('Nome da nova DiamondLayer:');
    if (!name || name.length < 2) return null;
    try {
        const res = await fetch('/api/diamond-layers', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ name: name.trim(), description: '' }),
        });
        if (!res.ok) { const e = await res.json(); alert(e.detail || 'Erro'); return null; }
        const created = await res.json();
        await loadDiamondLayers();
        loadDiamondLayersAdmin(); loadUserDiamondLayers();
        return created;
    } catch(e) { alert('Erro: ' + e.message); return null; }
}

async function deleteDiamondLayer(id) {
    if (!confirm('Excluir esta DiamondLayer?')) return;
    try { await fetch('/api/diamond-layers/' + id, { method: 'DELETE' }); loadDiamondLayersAdmin(); loadUserDiamondLayers(); if (typeof loadTables === 'function') loadTables(); }
    catch(e) { alert('Erro: ' + e.message); }
}

// Called from a per-row <select> in the "Tabelas Diamante" panel.
// On selection: assigns the table to the chosen layer (creating one if "__new__").
// The current admin user becomes the owner via the backend (owner_id = caller).
async function assignDiamondLayer(tableName, selectEl) {
    const value = selectEl.value;
    if (!value) return;
    let layerId = null;
    if (value === '__new__') {
        const created = await createDiamondLayer();
        selectEl.value = '';
        if (!created) return;
        layerId = created.id;
    } else {
        layerId = parseInt(value);
    }
    try {
        const res = await fetch('/api/diamond-layers/' + layerId + '/tables', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ table_name: tableName }),
        });
        if (!res.ok) { const e = await res.json(); alert(e.detail || 'Erro ao atribuir'); selectEl.value = ''; return; }
        // Refresh tables list (the row will move out of "Tabelas Diamante")
        if (typeof loadTables === 'function') loadTables();
        loadDiamondLayersAdmin();
    } catch(e) { alert('Erro: ' + e.message); selectEl.value = ''; }
}

// --- User form DiamondLayer checkboxes ---
function renderUserFormDiamondLayers(selectedIds) {
    const el = document.getElementById('userFormDiamondLayers');
    if (!el) return;
    const ids = new Set(selectedIds || []);
    if (!allDiamondLayers.length) {
        el.innerHTML = '<p class="text-[10px] text-[#8b949e]">Nenhuma DiamondLayer cadastrada.</p>';
        return;
    }
    el.innerHTML = allDiamondLayers.map(dl =>
        `<label class="inline-flex items-center gap-1.5 text-xs cursor-pointer">
            <input type="checkbox" value="${dl.id}" class="uf-dl-check accent-[#58a6ff] w-3 h-3" ${ids.has(dl.id) ? 'checked' : ''}>
            <span>${escapeHtml(dl.name)}</span>
        </label>`
    ).join('');
}

function getUserFormDiamondLayerIds() {
    return Array.from(document.querySelectorAll('.uf-dl-check:checked')).map(c => parseInt(c.value));
}
