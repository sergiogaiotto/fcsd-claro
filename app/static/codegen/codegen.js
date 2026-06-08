/* ===========================================================================
 * TDIA-CodeGen — comportamento do módulo (página própria /codegen).
 * Arquivo estático: NÃO passa pelo Jinja, então usa `${...}` e chaves livremente
 * sem o risco do gotcha {{ }} que afeta os templates.
 *   P0  — tema + navegação de seções.
 *   P1a — editor SQL (CodeMirror) + execução de leitura + export CSV/Excel/JSON.
 * ========================================================================= */

// ---- Tema (compartilha a chave qi_theme_v2 com o app principal) -----------
const _CG_MOON = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
const _CG_SUN  = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';

let cgEditor = null;       // instância do CodeMirror
let cgLastResult = null;   // último {columns, rows, row_count} para export
let cgSchemaTables = {};   // {tabela: [colunas]} p/ autocomplete (escopo do usuário)
let cgSnippets = {};       // id -> snippet salvo
let cgHistoryRows = [];    // últimas execuções (codegen_runs)
let cgPyCode = '';         // último código Python gerado
let cgPyName = 'tdia_codegen.py';

function _cgIsDark() { return document.getElementById('html-root').classList.contains('dark'); }

function _cgApplyTheme(isDark) {
    const root  = document.getElementById('html-root');
    const icon  = document.getElementById('themeIcon');
    const label = document.getElementById('themeLabel');
    if (isDark) {
        root.classList.remove('light'); root.classList.add('dark');
        if (icon)  icon.innerHTML = _CG_MOON;
        if (label) label.textContent = 'Claro';
    } else {
        root.classList.remove('dark'); root.classList.add('light');
        if (icon)  icon.innerHTML = _CG_SUN;
        if (label) label.textContent = 'Escuro';
    }
    if (cgEditor) cgEditor.setOption('theme', isDark ? 'material-darker' : 'default');
}

function toggleCgTheme() {
    const next = !_cgIsDark();
    _cgApplyTheme(next);
    try { localStorage.setItem('qi_theme_v2', next ? 'dark' : 'light'); } catch (e) {}
}

// ---- Navegação entre seções internas -------------------------------------
function cgShowSection(name) {
    document.querySelectorAll('.cg-section').forEach(s => s.classList.add('hidden'));
    const sec = document.getElementById('cg-section-' + name);
    if (sec) sec.classList.remove('hidden');

    document.querySelectorAll('.cg-subtab').forEach(b => b.classList.remove('cg-subtab-active'));
    const btn = document.getElementById('cg-subtab-' + name);
    if (btn) btn.classList.add('cg-subtab-active');

    // CodeMirror não calcula altura quando inicia escondido — refresca ao exibir.
    if (name === 'editor' && cgEditor) setTimeout(() => cgEditor.refresh(), 0);
    if (name === 'tables') loadCgTables();
    if (name === 'historico') loadCgHistory();
    if (name === 'python') cgLoadInventory();
    if (name === 'techniques') loadCgTechniques();
    if (name === 'patterns') loadCgPatterns();
}

// ---- Editor SQL (P1a) ----------------------------------------------------
function cgInitEditor() {
    const ta = document.getElementById('cgSqlEditor');
    if (!ta || typeof CodeMirror === 'undefined') return;
    cgEditor = CodeMirror.fromTextArea(ta, {
        mode: 'text/x-sql',
        lineNumbers: true,
        lineWrapping: true,
        theme: _cgIsDark() ? 'material-darker' : 'default',
        hintOptions: { tables: {}, completeSingle: false },
        extraKeys: {
            'Ctrl-Enter': () => cgRun(),
            'Cmd-Enter': () => cgRun(),
            'Ctrl-Space': 'autocomplete',
        },
    });
    // Autocomplete automático ao digitar uma palavra/coluna.
    cgEditor.on('inputRead', function (cm, change) {
        if (!cm.state.completionActive && change.text && /^[\w.]$/.test(change.text.join(''))) {
            cm.execCommand('autocomplete');
        }
    });
}

async function cgLoadScope() {
    try {
        const res = await fetch('/api/codegen/scope');
        if (!res.ok) return;
        const data = await res.json();
        const fill = (sel, items) => {
            if (!sel) return;
            (items || []).forEach(it => {
                const o = document.createElement('option');
                o.value = it.id; o.textContent = it.name;
                sel.appendChild(o);
            });
        };
        fill(document.getElementById('cgDatamart'), data.datamarts);
        fill(document.getElementById('cgLayer'), data.diamond_layers);
    } catch (e) { /* contexto opcional na P1a */ }
}

function _cgEscape(v) {
    if (v === null || v === undefined) return '<span class="text-fg-muted">∅</span>';
    return String(v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function _cgSelVal(id) {
    const el = document.getElementById(id);
    if (!el || !el.value) return [];
    const n = parseInt(el.value, 10);
    return isNaN(n) ? [] : [n];
}

function cgRenderTable(result) {
    const box = document.getElementById('cgResult');
    if (!result.rows || !result.rows.length) {
        box.innerHTML = '<div class="text-fg-muted text-sm py-6 text-center">Nenhuma linha retornada.</div>';
        return;
    }
    const cols = (result.columns && result.columns.length) ? result.columns : Object.keys(result.rows[0]);
    let html = '<table class="cg-table"><thead><tr><th>#</th>';
    cols.forEach(c => { html += '<th>' + _cgEscape(c) + '</th>'; });
    html += '</tr></thead><tbody>';
    result.rows.forEach((row, i) => {
        html += '<tr><td class="text-fg-muted">' + (i + 1) + '</td>';
        cols.forEach(c => { html += '<td>' + _cgEscape(row[c]) + '</td>'; });
        html += '</tr>';
    });
    html += '</tbody></table>';
    box.innerHTML = html;
}

async function cgRun(confirmed) {
    const sql = cgEditor ? cgEditor.getValue().trim() : '';
    const status = document.getElementById('cgStatus');
    const exportBar = document.getElementById('cgExportBar');
    const runBtn = document.getElementById('cgRunBtn');
    const resultBox = document.getElementById('cgResult');
    if (!sql) { status.textContent = 'Escreva uma consulta.'; return; }

    status.textContent = 'Executando…';
    if (exportBar) exportBar.style.display = 'none';
    if (runBtn) runBtn.disabled = true;
    const t0 = performance.now();
    try {
        const dmEl = document.getElementById('cgDatamart');
        const res = await fetch('/api/codegen/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sql,
                result_limit: parseInt(document.getElementById('cgLimit').value, 10) || 100,
                target_datamart_id: (dmEl && dmEl.value) ? parseInt(dmEl.value, 10) : null,
                confirm: !!confirmed,
            }),
        });
        const data = await res.json();
        const ms = Math.round(performance.now() - t0);

        // Operação destrutiva → confirmar e reenviar com confirm:true.
        if (data.needs_confirm) {
            if (runBtn) runBtn.disabled = false;
            status.textContent = 'Confirmação necessária.';
            const ops = (data.destructive_ops || []).join(', ');
            if (window.confirm('⚠ Operação destrutiva detectada: ' + ops + '.\n\nIsso pode apagar dados ou tabelas. Executar mesmo assim?')) {
                return cgRun(true);
            }
            status.textContent = 'Cancelado.';
            return;
        }
        if (!res.ok || data.error) {
            window.cgLastError = data.error || 'Erro ao executar.';   // o Copiloto usa p/ "corrigir erro"
            resultBox.innerHTML = '<div class="text-red-400 text-sm py-4 font-mono">' + _cgEscape(data.error || 'Erro ao executar.') + '</div>';
            status.textContent = 'Erro • ' + ms + ' ms';
            return;
        }
        window.cgLastError = '';            // execução ok → limpa o último erro
        if (data.columns) {                 // resultado de leitura (ou SELECT final de um script)
            cgLastResult = data;
            cgRenderTable(data);
            status.textContent = data.row_count + ' linha(s)'
                + (data.limited ? ' · limite atingido' : '')
                + (data.writes ? ' · com escrita' : '') + ' • ' + ms + ' ms';
            if (exportBar) exportBar.style.display = 'flex';
        } else {                            // escrita sem retorno
            cgLastResult = null;
            resultBox.innerHTML = '<div class="text-fg-green text-sm py-4">✓ ' + _cgEscape(data.message || 'Executado.') + '</div>';
            status.textContent = (data.message || 'Executado.') + ' • ' + ms + ' ms';
        }
    } catch (e) {
        resultBox.innerHTML = '<div class="text-red-400 text-sm py-4">Falha: ' + _cgEscape(e.message) + '</div>';
        status.textContent = 'Erro';
    } finally {
        if (runBtn) runBtn.disabled = false;
    }
}

async function cgExport(fmt) {
    if (!cgLastResult || !cgLastResult.rows || !cgLastResult.rows.length) return;
    try {
        const res = await fetch('/api/codegen/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ format: fmt, columns: cgLastResult.columns, rows: cgLastResult.rows, filename: 'tdia_codegen' }),
        });
        if (!res.ok) { alert('Erro ao exportar.'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'tdia_codegen.' + fmt;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
    } catch (e) { alert('Erro ao exportar: ' + e.message); }
}

// ---- Minhas Tabelas (P1b-2) ---------------------------------------------
async function loadCgTables() {
    const box = document.getElementById('cgTablesList');
    if (!box) return;
    box.innerHTML = '<div class="text-fg-muted text-sm py-4 text-center">Carregando…</div>';
    try {
        const res = await fetch('/api/codegen/tables');
        if (!res.ok) { box.innerHTML = '<div class="text-red-400 text-sm py-4">Erro ao carregar.</div>'; return; }
        const rows = await res.json();
        if (!rows.length) {
            box.innerHTML = '<div class="text-fg-muted text-sm py-6 text-center">Você ainda não criou tabelas no módulo. Use <code>CREATE TABLE</code> no editor (selecionando o DataMart de destino).</div>';
            return;
        }
        box.innerHTML = rows.map(r => {
            const dm = r.datamart_name
                ? '<span class="text-[9px] bg-fg-accent/10 text-fg-accent px-1.5 py-0.5 rounded-full ml-2">' + _cgEscape(r.datamart_name) + '</span>' : '';
            const owner = r.owner_login ? '<span class="text-[10px] text-fg-muted ml-2">por ' + _cgEscape(r.owner_login) + '</span>' : '';
            const when = r.created_at ? String(r.created_at).slice(0, 16).replace('T', ' ') : '';
            return '<div class="flex items-center justify-between bg-fg-900 rounded-lg px-3 py-2.5 border border-fg-accent/20">'
                + '<div><span class="text-[9px] bg-fg-accent/15 text-fg-accent px-1.5 py-0.5 rounded font-bold uppercase tracking-wider mr-2">tech</span>'
                + '<span class="text-sm text-fg-green font-mono font-bold">' + _cgEscape(r.table_name) + '</span>' + dm + owner + '</div>'
                + '<span class="text-[10px] text-fg-muted font-mono">' + when + '</span></div>';
        }).join('');
    } catch (e) {
        box.innerHTML = '<div class="text-red-400 text-sm py-4">Falha: ' + _cgEscape(e.message) + '</div>';
    }
}

// ---- P2: autocomplete / snippets / histórico / exemplos -----------------
async function cgLoadSchema() {
    try {
        const res = await fetch('/api/codegen/schema');
        if (!res.ok) return;
        const data = await res.json();
        cgSchemaTables = data.tables || {};
        if (cgEditor) cgEditor.setOption('hintOptions', { tables: cgSchemaTables, completeSingle: false });
    } catch (e) { /* autocomplete é opcional */ }
}
function cgAutocomplete() { if (cgEditor) cgEditor.execCommand('autocomplete'); }

async function cgLoadSnippets() {
    const sel = document.getElementById('cgSnippetSel');
    if (!sel) return;
    try {
        const res = await fetch('/api/codegen/snippets');
        const rows = res.ok ? await res.json() : [];
        cgSnippets = {};
        sel.innerHTML = '<option value="">— salvos —</option>' + rows.map(r => {
            cgSnippets[r.id] = r;
            return '<option value="' + r.id + '">' + _cgEscape(r.name) + '</option>';
        }).join('');
    } catch (e) { /* ignore */ }
}
function cgLoadSnippet() {
    const sel = document.getElementById('cgSnippetSel');
    const r = sel && cgSnippets[sel.value];
    if (r && cgEditor) cgEditor.setValue(r.sql);
}
async function cgSaveSnippet() {
    if (!cgEditor) return;
    const sql = cgEditor.getValue().trim();
    if (!sql) { alert('Editor vazio.'); return; }
    const name = prompt('Nome do snippet:');
    if (!name || !name.trim()) return;
    const res = await fetch('/api/codegen/snippets', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), sql }),
    });
    if (res.ok) cgLoadSnippets(); else alert('Erro ao salvar o snippet.');
}
async function cgDeleteSnippet() {
    const sel = document.getElementById('cgSnippetSel');
    if (!sel || !sel.value) { alert('Selecione um snippet salvo.'); return; }
    const r = cgSnippets[sel.value];
    if (!confirm('Excluir o snippet "' + (r ? r.name : '') + '"?')) return;
    const res = await fetch('/api/codegen/snippets/' + sel.value, { method: 'DELETE' });
    if (res.ok) cgLoadSnippets();
}

async function loadCgHistory() {
    const box = document.getElementById('cgHistoryList');
    if (!box) return;
    box.innerHTML = '<div class="text-fg-muted text-sm py-4 text-center">Carregando…</div>';
    try {
        const res = await fetch('/api/codegen/runs');
        cgHistoryRows = res.ok ? await res.json() : [];
        if (!cgHistoryRows.length) {
            box.innerHTML = '<div class="text-fg-muted text-sm py-6 text-center">Sem execuções ainda.</div>';
            return;
        }
        box.innerHTML = cgHistoryRows.map((r, i) => {
            const when = r.created_at ? String(r.created_at).slice(0, 16).replace('T', ' ') : '';
            const kind = r.kind === 'write'
                ? '<span class="text-[9px] bg-fg-accent/15 text-fg-accent px-1.5 py-0.5 rounded uppercase">write</span>'
                : '<span class="text-[9px] bg-fg-blue/15 text-fg-blue px-1.5 py-0.5 rounded uppercase">read</span>';
            const sql1 = (r.sql || '').replace(/\s+/g, ' ').slice(0, 100);
            return '<div class="bg-fg-900 rounded-lg px-3 py-2 border border-fg-border hover:border-fg-accent/30 cursor-pointer transition" onclick="cgUseHistoryItem(' + i + ')">'
                + '<div class="flex items-center justify-between gap-2"><div class="font-mono text-xs text-fg-text truncate flex-1">' + _cgEscape(sql1) + '</div>' + kind + '</div>'
                + '<div class="text-[10px] text-fg-muted mt-1">' + when + ' · ' + r.row_count + ' linha(s)</div></div>';
        }).join('');
    } catch (e) {
        box.innerHTML = '<div class="text-red-400 text-sm py-4">Falha ao carregar o histórico.</div>';
    }
}
function cgUseHistoryItem(i) {
    const r = cgHistoryRows[i];
    if (r && cgEditor) { cgEditor.setValue(r.sql); cgShowSection('editor'); }
}

function cgUseExampleEl(btn) {
    const code = btn.parentElement.querySelector('code');
    if (code && cgEditor) { cgEditor.setValue(code.textContent.trim()); cgShowSection('editor'); }
}

// ---- P3 / M2.4: gerar código Python (Técnica × Padrão, schema-aware) ------
let cgInventory = { techniques: [], patterns: [] };

async function cgLoadInventory() {
    try {
        const res = await fetch('/api/codegen/techniques');
        if (!res.ok) return;
        cgInventory = await res.json();
    } catch (e) { return; }
    const tsel = document.getElementById('cgPyTechnique');
    if (tsel) {
        const cur = tsel.value;
        tsel.innerHTML = (cgInventory.techniques || []).map(t =>
            '<option value="' + _cgEscape(t.key) + '">' + _cgEscape(t.label || t.key) + '</option>').join('');
        if (cur && (cgInventory.techniques || []).some(t => t.key === cur)) tsel.value = cur;
    }
    cgFilterPatterns();
}

function cgFilterPatterns() {
    const tsel = document.getElementById('cgPyTechnique');
    const psel = document.getElementById('cgPyPattern');
    if (!psel) return;
    const tech = tsel ? tsel.value : 'pandas';
    const cur = psel.value;
    const compat = (cgInventory.patterns || []).filter(p => _cgPatCompatible(p, tech));
    psel.innerHTML = compat.map(p =>
        '<option value="' + _cgEscape(p.key) + '">' + _cgEscape(p.label || p.key) + '</option>').join('');
    if (cur && compat.some(p => p.key === cur)) psel.value = cur;
    else if (!compat.length) psel.innerHTML = '<option value="script">script</option>';
}

// Mostra o schema resolvido (dry-run) como chips name: <tipo py> (P3 já vinha no /pycode).
function cgRenderPySchema(schema) {
    const box = document.getElementById('cgPySchemaBox');
    const list = document.getElementById('cgPySchema');
    if (!box || !list) return;
    if (!schema || !schema.length) { box.style.display = 'none'; return; }
    list.innerHTML = schema.map(c =>
        '<span class="cg-chip" title="pandas: ' + _cgEscape(c.pd) + ' · spark: ' + _cgEscape(c.spark) + '">'
        + _cgEscape(c.name) + ': <strong>' + _cgEscape(c.py) + '</strong></span>').join('');
    box.style.display = 'block';
}

async function cgGenPython() {
    const sql = cgEditor ? cgEditor.getValue().trim() : '';
    const pre = document.getElementById('cgPyCode');
    const bar = document.getElementById('cgPyBar');
    const schemaBox = document.getElementById('cgPySchemaBox');
    if (!sql) { pre.textContent = 'Escreva um SQL na aba "Editor SQL" primeiro.'; return; }
    const technique = (document.getElementById('cgPyTechnique') || {}).value || 'pandas';
    const pattern = (document.getElementById('cgPyPattern') || {}).value || 'script';
    pre.textContent = 'Gerando…';
    if (bar) bar.style.display = 'none';
    if (schemaBox) schemaBox.style.display = 'none';
    try {
        const res = await fetch('/api/codegen/pycode', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sql, technique, pattern }),
        });
        const data = await res.json();
        if (!res.ok || data.error) { pre.textContent = data.error || 'Erro ao gerar.'; return; }
        cgPyCode = data.code || '';
        cgPyName = data.filename || 'tdia_codegen.py';
        pre.textContent = cgPyCode;        // textContent → sem risco de injeção
        if (bar) { bar.style.display = 'flex'; document.getElementById('cgPyName').textContent = cgPyName; }
        cgRenderPySchema(data.schema || []);
    } catch (e) { pre.textContent = 'Falha: ' + e.message; }
}
function cgCopyPython() {
    if (!cgPyCode) return;
    if (navigator.clipboard) navigator.clipboard.writeText(cgPyCode).catch(() => {});
}
function cgDownloadPython() {
    if (!cgPyCode) return;
    const blob = new Blob([cgPyCode], { type: 'text/x-python' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = cgPyName;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
}

// ---- M2.1: CRUD de Técnicas (admin) -------------------------------------
let cgTechniques = [];

async function loadCgTechniques() {
    const box = document.getElementById('cgTechList');
    if (!box) return;
    box.innerHTML = '<div class="text-fg-muted text-sm py-4 text-center">Carregando…</div>';
    try {
        const res = await fetch('/api/codegen/admin/techniques');
        if (!res.ok) { box.innerHTML = '<div class="text-red-400 text-sm py-3">Sem permissão ou erro.</div>'; return; }
        cgTechniques = await res.json();
        if (!cgTechniques.length) { box.innerHTML = '<div class="text-fg-muted text-sm py-4 text-center">Nenhuma técnica cadastrada.</div>'; return; }
        box.innerHTML = cgTechniques.map((t, i) => {
            const inactive = t.is_active ? '' : '<span class="text-[10px] text-fg-muted ml-2">(inativa)</span>';
            return '<div class="flex items-center justify-between bg-fg-900 rounded-lg px-3 py-2.5 border border-fg-border">'
                + '<div><span class="text-sm text-fg-green font-mono font-bold">' + _cgEscape(t.key) + '</span>'
                + '<span class="text-fg-muted text-sm ml-2">' + _cgEscape(t.label || '') + '</span>'
                + '<span class="text-[10px] bg-fg-blue/15 text-fg-blue px-1.5 py-0.5 rounded ml-2 uppercase">' + _cgEscape(t.runtime) + '</span>' + inactive + '</div>'
                + '<div class="flex items-center gap-2">'
                + '<button class="cg-btn-mini" onclick="cgEditTechnique(' + i + ')">Editar</button>'
                + '<button class="cg-btn-mini" onclick="cgDeleteTechnique(' + i + ')">Excluir</button></div></div>';
        }).join('');
    } catch (e) { box.innerHTML = '<div class="text-red-400 text-sm py-3">Falha: ' + _cgEscape(e.message) + '</div>'; }
}

function _cgTechSetForm(t) {
    const g = (id) => document.getElementById(id);
    g('cgTechId').value = t.id || '';
    g('cgTechKey').value = t.key || '';
    g('cgTechKey').disabled = !!t.id;   // chave imutável na edição
    g('cgTechLabel').value = t.label || '';
    g('cgTechRuntime').value = t.runtime || 'python';
    g('cgTechDesc').value = t.description || '';
    g('cgTechImports').value = t.frag_imports || '';
    g('cgTechSetup').value = t.frag_setup || '';
    g('cgTechRead').value = t.frag_read || '';
    g('cgTechShow').value = t.frag_show || '';
    g('cgTechTeardown').value = t.frag_teardown || '';
    g('cgTechActive').checked = (t.is_active === undefined) ? true : !!t.is_active;
    g('cgTechMsg').textContent = '';
    g('cgTechFormTitle').textContent = t.id ? ('Editar — ' + t.key) : 'Nova técnica';
    g('cgTechForm').style.display = 'block';
}

function cgNewTechnique() { _cgTechSetForm({}); }
function cgEditTechnique(i) { if (cgTechniques[i]) _cgTechSetForm(cgTechniques[i]); }
function cgCancelTechnique() { document.getElementById('cgTechForm').style.display = 'none'; }

async function cgSaveTechnique() {
    const g = (id) => document.getElementById(id);
    const id = g('cgTechId').value;
    const body = {
        key: g('cgTechKey').value.trim(),
        label: g('cgTechLabel').value.trim(),
        runtime: g('cgTechRuntime').value,
        description: g('cgTechDesc').value.trim(),
        frag_imports: g('cgTechImports').value,
        frag_setup: g('cgTechSetup').value,
        frag_read: g('cgTechRead').value,
        frag_show: g('cgTechShow').value,
        frag_teardown: g('cgTechTeardown').value,
        is_active: g('cgTechActive').checked ? 1 : 0,
    };
    const msg = g('cgTechMsg');
    msg.textContent = 'Validando e salvando…'; msg.className = 'text-xs ml-2 text-fg-muted';
    try {
        const url = id ? '/api/codegen/admin/techniques/' + id : '/api/codegen/admin/techniques';
        const res = await fetch(url, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await res.json();
        if (!res.ok || data.error) { msg.textContent = data.error || 'Erro ao salvar.'; msg.className = 'text-xs ml-2 text-red-400'; return; }
        cgCancelTechnique(); loadCgTechniques();
    } catch (e) { msg.textContent = 'Falha: ' + e.message; msg.className = 'text-xs ml-2 text-red-400'; }
}

async function cgDeleteTechnique(i) {
    const t = cgTechniques[i];
    if (!t || !confirm('Excluir a técnica "' + t.key + '"?')) return;
    const res = await fetch('/api/codegen/admin/techniques/' + t.id, { method: 'DELETE' });
    if (res.ok) loadCgTechniques(); else alert('Erro ao excluir.');
}

// ---- M2.2: CRUD de Padrões + matriz (admin) ----------------------------
let cgPatterns = [];
let cgPatTechKeys = [];

function _cgParseCompat(c) {
    if (!c || c === '*') return [];
    try { return JSON.parse(c); } catch (e) { return String(c).split(',').map(s => s.trim()).filter(Boolean); }
}
function _cgPatCompatible(p, techKey) {
    return (p.compatible === '*' || !p.compatible) || _cgParseCompat(p.compatible).includes(techKey);
}

async function loadCgPatterns() {
    const box = document.getElementById('cgPatList');
    if (!box) return;
    box.innerHTML = '<div class="text-fg-muted text-sm py-4 text-center">Carregando…</div>';
    try {
        const [pr, ir] = await Promise.all([fetch('/api/codegen/admin/patterns'), fetch('/api/codegen/techniques')]);
        if (!pr.ok) { box.innerHTML = '<div class="text-red-400 text-sm py-3">Sem permissão ou erro.</div>'; return; }
        cgPatterns = await pr.json();
        const inv = ir.ok ? await ir.json() : { techniques: [] };
        cgPatTechKeys = (inv.techniques || []).map(t => t.key);
        if (!cgPatterns.length) {
            box.innerHTML = '<div class="text-fg-muted text-sm py-4 text-center">Nenhum padrão.</div>';
        } else {
            box.innerHTML = cgPatterns.map((p, i) => {
                const compat = (p.compatible === '*' || !p.compatible) ? 'todas' : _cgParseCompat(p.compatible).join(', ');
                const inactive = p.is_active ? '' : '<span class="text-[10px] text-fg-muted ml-2">(inativo)</span>';
                const base = p.key === 'script' ? '<span class="text-[9px] text-fg-muted ml-2 uppercase">base</span>' : '';
                return '<div class="flex items-center justify-between bg-fg-900 rounded-lg px-3 py-2.5 border border-fg-border">'
                    + '<div><span class="text-sm text-fg-green font-mono font-bold">' + _cgEscape(p.key) + '</span>'
                    + '<span class="text-fg-muted text-sm ml-2">' + _cgEscape(p.label || '') + '</span>' + base + inactive
                    + '<div class="text-[10px] text-fg-muted mt-0.5">compat: ' + _cgEscape(compat) + '</div></div>'
                    + '<div class="flex items-center gap-2">'
                    + '<button class="cg-btn-mini" onclick="cgEditPattern(' + i + ')">Editar</button>'
                    + (p.key === 'script' ? '' : '<button class="cg-btn-mini" onclick="cgDeletePattern(' + i + ')">Excluir</button>') + '</div></div>';
            }).join('');
        }
        cgRenderMatrix();
    } catch (e) { box.innerHTML = '<div class="text-red-400 text-sm py-3">Falha: ' + _cgEscape(e.message) + '</div>'; }
}

function cgRenderMatrix() {
    const box = document.getElementById('cgMatrix');
    if (!box) return;
    if (!cgPatterns.length || !cgPatTechKeys.length) { box.innerHTML = '<div class="text-fg-muted text-sm">—</div>'; return; }
    let h = '<table class="cg-table"><thead><tr><th>Padrão \\ Técnica</th>';
    cgPatTechKeys.forEach(k => { h += '<th class="text-center">' + _cgEscape(k) + '</th>'; });
    h += '</tr></thead><tbody>';
    cgPatterns.forEach(p => {
        h += '<tr><td class="font-mono text-fg-green">' + _cgEscape(p.key) + '</td>';
        cgPatTechKeys.forEach(k => { h += '<td class="text-center">' + (_cgPatCompatible(p, k) ? '<span class="text-fg-green">✓</span>' : '<span class="text-fg-muted">·</span>') + '</td>'; });
        h += '</tr>';
    });
    h += '</tbody></table>';
    box.innerHTML = h;
}

// Abre/recolhe o painel da matriz de compatibilidade (recolhido por padrão).
function cgToggleMatrix() {
    const wrap = document.getElementById('cgMatrixWrap');
    const btn = document.getElementById('cgMatrixToggleBtn');
    if (!wrap) return;
    const open = wrap.style.display === 'none';   // estava recolhido → abre
    wrap.style.display = open ? 'block' : 'none';
    if (btn) {
        btn.textContent = open ? 'Recolher ▴' : 'Expandir ▾';
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
}

function _cgRenderCompatBoxes(selected, all) {
    const wrap = document.getElementById('cgPatCompat');
    wrap.innerHTML = cgPatTechKeys.map(k =>
        '<label class="flex items-center gap-1.5 text-xs text-fg-muted cursor-pointer"><input type="checkbox" class="cg-pat-compat accent-fg-accent" value="' + k + '"'
        + (selected.includes(k) ? ' checked' : '') + (all ? ' disabled' : '') + '> ' + _cgEscape(k) + '</label>'
    ).join('');
}
function cgPatToggleAll() {
    const all = document.getElementById('cgPatAll').checked;
    document.querySelectorAll('.cg-pat-compat').forEach(cb => { cb.disabled = all; });
}

function _cgPatSetForm(p) {
    const g = (id) => document.getElementById(id);
    g('cgPatId').value = p.id || '';
    g('cgPatKey').value = p.key || '';
    g('cgPatKey').disabled = !!p.id;
    g('cgPatLabel').value = p.label || '';
    g('cgPatDesc').value = p.description || '';
    g('cgPatTemplate').value = p.template || '';
    const isAll = (p.compatible === '*' || p.compatible === undefined || !p.compatible);
    g('cgPatAll').checked = isAll;
    _cgRenderCompatBoxes(isAll ? [] : _cgParseCompat(p.compatible), isAll);
    g('cgPatActive').checked = (p.is_active === undefined) ? true : !!p.is_active;
    g('cgPatMsg').textContent = '';
    g('cgPatFormTitle').textContent = p.id ? ('Editar — ' + p.key) : 'Novo padrão';
    g('cgPatForm').style.display = 'block';
}
function cgNewPattern() { _cgPatSetForm({}); }
function cgEditPattern(i) { if (cgPatterns[i]) _cgPatSetForm(cgPatterns[i]); }
function cgCancelPattern() { document.getElementById('cgPatForm').style.display = 'none'; }

async function cgSavePattern() {
    const g = (id) => document.getElementById(id);
    const id = g('cgPatId').value;
    let compatible = '*';
    if (!g('cgPatAll').checked) {
        compatible = Array.from(document.querySelectorAll('.cg-pat-compat:checked')).map(cb => cb.value);
    }
    const body = {
        key: g('cgPatKey').value.trim(), label: g('cgPatLabel').value.trim(),
        description: g('cgPatDesc').value.trim(), template: g('cgPatTemplate').value,
        compatible: compatible, is_active: g('cgPatActive').checked ? 1 : 0,
    };
    const msg = g('cgPatMsg'); msg.textContent = 'Validando e salvando…'; msg.className = 'text-xs ml-2 text-fg-muted';
    try {
        const url = id ? '/api/codegen/admin/patterns/' + id : '/api/codegen/admin/patterns';
        const res = await fetch(url, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await res.json();
        if (!res.ok || data.error) { msg.textContent = data.error || 'Erro ao salvar.'; msg.className = 'text-xs ml-2 text-red-400'; return; }
        cgCancelPattern(); loadCgPatterns();
    } catch (e) { msg.textContent = 'Falha: ' + e.message; msg.className = 'text-xs ml-2 text-red-400'; }
}
async function cgDeletePattern(i) {
    const p = cgPatterns[i];
    if (!p || !confirm('Excluir o padrão "' + p.key + '"?')) return;
    const res = await fetch('/api/codegen/admin/patterns/' + p.id, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (res.ok && !data.error) loadCgPatterns(); else alert(data.error || 'Erro ao excluir.');
}

// ---- Init ---------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    _cgApplyTheme(_cgIsDark());   // sincroniza ícone/rótulo do botão
    cgInitEditor();
    cgLoadScope();
    cgLoadSchema();
    cgLoadSnippets();
    cgShowSection('editor');
    cgCopInit();
});


/* ===========================================================================
 * Copiloto de Dados (programação em linguagem natural) — painel lateral
 * onipresente. O backend (/api/codegen/assist) PROPÕE; a execução de SQL
 * continua via cgRun()/api/codegen/run (autorizador). As "actions" devolvidas
 * pilotam o módulo: inserir no editor, executar, gerar Python tipado, salvar
 * snippet. Memória de conversa em /api/codegen/chats.
 * ========================================================================= */
let cgCopOpen = false;
let cgCopHistory = [];   // [{role:'user'|'assistant', content, sql?, actions?, _pending?}]
let cgCopChatId = null;
let cgCopBusy = false;

function cgCopInit() {
    cgCopRefreshChats();
    cgCopRenderThread();
    const inp = document.getElementById('cgCopInput');
    if (inp) inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); cgCopSend(); }
    });
    document.addEventListener('keydown', (e) => {
        if (e.altKey && (e.key === 'c' || e.key === 'C')) { e.preventDefault(); cgCopToggle(); }
    });
}

function cgCopToggle(force) {
    cgCopOpen = (typeof force === 'boolean') ? force : !cgCopOpen;
    const panel = document.getElementById('cgCopilotPanel');
    const fab = document.getElementById('cgCopilotFab');
    if (panel) { panel.classList.toggle('cg-copilot-open', cgCopOpen); panel.setAttribute('aria-hidden', cgCopOpen ? 'false' : 'true'); }
    if (fab) fab.classList.toggle('cg-fab-hidden', cgCopOpen);
    if (cgCopOpen) { cgCopRenderChips(); setTimeout(() => { const i = document.getElementById('cgCopInput'); if (i) i.focus(); }, 60); }
}

// Contexto vivo da IDE que viaja em cada mensagem (grounding do copiloto).
function cgCopContext() {
    const dm = document.getElementById('cgDatamart');
    const dl = document.getElementById('cgLayer');
    return {
        sql: cgEditor ? cgEditor.getValue().trim() : '',
        last_error: window.cgLastError || '',
        datamart: (dm && dm.value) ? dm.options[dm.selectedIndex].text : '',
        diamond: (dl && dl.value) ? dl.options[dl.selectedIndex].text : '',
    };
}

function cgCopRenderChips() {
    const box = document.getElementById('cgCopChips');
    if (!box) return;
    const ctx = cgCopContext();
    const chips = [];
    const nTables = Object.keys(cgSchemaTables || {}).length;
    chips.push('<span class="cg-chip" title="Tabelas no seu escopo">⛁ ' + nTables + ' tabela(s)</span>');
    if (ctx.datamart) chips.push('<span class="cg-chip">DataMart: ' + _cgEscape(ctx.datamart) + '</span>');
    if (ctx.diamond) chips.push('<span class="cg-chip">Layer: ' + _cgEscape(ctx.diamond) + '</span>');
    if (ctx.sql) chips.push('<span class="cg-chip" title="O copiloto vê o SQL atual do editor">✎ SQL atual (' + ctx.sql.length + ' ch)</span>');
    if (ctx.last_error) chips.push('<span class="cg-chip cg-chip-err" title="' + _cgEscape(ctx.last_error) + '">⚠ último erro</span>');
    box.innerHTML = chips.join('');
}

// Markdown mínimo e SEGURO (escapa antes; protege blocos de código do <br>).
function cgCopMd(t) {
    let s = _cgEscape(t || '');
    const blocks = [];
    s = s.replace(/```(?:[a-zA-Z]*)\n?([\s\S]*?)```/g, (m, code) => {
        blocks.push(code.replace(/\n+$/, ''));
        return '\uE000B' + (blocks.length - 1) + '\uE000';
    });
    s = s.replace(/`([^`]+)`/g, '<code class="cg-cop-ic">$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\n/g, '<br>');
    s = s.replace(/\uE000B(\d+)\uE000/g, (m, i) => '<pre class="cg-cop-code">' + blocks[+i] + '</pre>');
    return s;
}

function cgCopRenderThread() {
    const thread = document.getElementById('cgCopThread');
    if (!thread) return;
    if (!cgCopHistory.length) {
        thread.innerHTML = '<div class="cg-cop-empty">'
            + '<div class="cg-cop-empty-title">✦ Copiloto de Dados</div>'
            + '<p>Peça em linguagem natural — eu vejo seu escopo, esquema e o SQL atual.</p>'
            + '<button class="cg-cop-suggest" onclick="cgCopQuick(this)">Gere um SELECT dos 10 maiores registros</button>'
            + '<button class="cg-cop-suggest" onclick="cgCopQuick(this)">Explique o SQL atual do editor</button>'
            + '<button class="cg-cop-suggest" onclick="cgCopQuick(this)">Por que minha última consulta deu erro?</button>'
            + '<button class="cg-cop-suggest" onclick="cgCopQuick(this)">Transforme isso num job PySpark tipado</button>'
            + '</div>';
        return;
    }
    thread.innerHTML = cgCopHistory.map((m, i) => cgCopMsgHtml(m, i)).join('');
    thread.scrollTop = thread.scrollHeight;
}

function cgCopMsgHtml(m, idx) {
    if (m.role === 'user') {
        return '<div class="cg-msg cg-msg-user"><div class="cg-bubble">' + _cgEscape(m.content) + '</div></div>';
    }
    let html = '<div class="cg-msg cg-msg-bot"><div class="cg-bubble">' + cgCopMd(m.content || '');
    if (m.actions && m.actions.length) {
        html += '<div class="cg-cop-acts">';
        m.actions.forEach((a, ai) => {
            html += '<button class="cg-cop-act" onclick="cgCopAct(' + idx + ',' + ai + ')">' + _cgEscape(a.label || a.type) + '</button>';
        });
        html += '</div>';
    }
    return html + '</div></div>';
}

function cgCopQuick(btn) { const inp = document.getElementById('cgCopInput'); if (inp) { inp.value = btn.textContent; inp.focus(); } }

async function cgCopAct(mi, ai) {
    const m = cgCopHistory[mi]; if (!m || !m.actions) return;
    const a = m.actions[ai]; if (!a) return;
    if (a.type === 'insert_sql') {
        if (cgEditor) cgEditor.setValue(a.sql);
        cgShowSection('editor'); cgCopToast('SQL inserido no editor.');
    } else if (a.type === 'run_sql') {
        if (cgEditor) cgEditor.setValue(a.sql);
        cgShowSection('editor'); cgCopToast('Executando…'); cgRun();
    } else if (a.type === 'python') {
        cgCopShowPython(a);
    } else if (a.type === 'save_snippet') {
        try {
            const res = await fetch('/api/codegen/snippets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: a.name, sql: a.sql }) });
            if (res.ok) { cgLoadSnippets(); cgCopToast('Snippet salvo.'); } else cgCopToast('Erro ao salvar snippet.');
        } catch (e) { cgCopToast('Falha: ' + e.message); }
    } else if (a.type === 'copy_python') {
        if (navigator.clipboard) navigator.clipboard.writeText(a.code || '').catch(() => {});
        cgCopToast('Código copiado.');
    } else if (a.type === 'download_python') {
        const blob = new Blob([a.code || ''], { type: 'text/x-python' });
        const url = URL.createObjectURL(blob);
        const el = document.createElement('a'); el.href = url; el.download = a.filename || 'consulta.py';
        document.body.appendChild(el); el.click(); el.remove(); URL.revokeObjectURL(url);
    } else if (a.type === 'open_python_tab') {
        const pre = document.getElementById('cgPyCode'); if (pre) pre.textContent = cgPyCode;
        const bar = document.getElementById('cgPyBar'); if (bar) { bar.style.display = 'flex'; const nm = document.getElementById('cgPyName'); if (nm) nm.textContent = cgPyName; }
        cgShowSection('python'); cgCopToast('Aberto na aba Gerar Python.');
    }
}

// Mostra o Python gerado (já veio pronto do servidor) como uma mensagem com
// copiar / baixar / abrir na aba dedicada.
function cgCopShowPython(a) {
    cgPyCode = a.code || ''; cgPyName = a.filename || 'consulta.py';
    cgCopHistory.push({
        role: 'assistant',
        content: 'Código **' + (a.technique || '') + '·' + (a.pattern || '') + '** gerado:\n```python\n' + (a.code || '') + '\n```',
        actions: [
            { type: 'copy_python', label: '⧉ Copiar', code: a.code },
            { type: 'download_python', label: '⤓ Baixar .py', code: a.code, filename: cgPyName },
            { type: 'open_python_tab', label: 'Abrir na aba Gerar Python' },
        ],
    });
    cgCopRenderThread();
}

function cgCopSetBusy(b) {
    cgCopBusy = b;
    const btn = document.getElementById('cgCopSend');
    if (btn) { btn.disabled = b; btn.textContent = b ? '…' : 'Enviar'; }
}

async function cgCopSend() {
    if (cgCopBusy) return;
    const inp = document.getElementById('cgCopInput');
    const msg = (inp ? inp.value : '').trim();
    if (!msg) return;
    inp.value = '';
    cgCopHistory.push({ role: 'user', content: msg });
    cgCopHistory.push({ role: 'assistant', content: '…', _pending: true });
    cgCopRenderThread();
    cgCopSetBusy(true);
    try {
        const prior = cgCopHistory.filter(m => !m._pending);
        const histForApi = prior.slice(0, -1).map(m => ({ role: m.role, content: m.content }));
        const res = await fetch('/api/codegen/assist', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg, history: histForApi, context: cgCopContext() }),
        });
        const data = await res.json().catch(() => ({ error: 'resposta inválida' }));
        cgCopHistory = cgCopHistory.filter(m => !m._pending);
        if (!res.ok || data.error) {
            cgCopHistory.push({ role: 'assistant', content: '⚠ ' + (data.error || 'Erro ao falar com o copiloto.') });
        } else {
            cgCopHistory.push({ role: 'assistant', content: data.reply || 'Ok.', sql: data.sql || '', actions: data.actions || [] });
        }
    } catch (e) {
        cgCopHistory = cgCopHistory.filter(m => !m._pending);
        cgCopHistory.push({ role: 'assistant', content: '⚠ Falha de rede: ' + e.message });
    } finally {
        cgCopSetBusy(false);
        cgCopRenderThread();
        cgCopRenderChips();
    }
}

function cgCopToast(msg) {
    let t = document.getElementById('cgCopToast');
    if (!t) { t = document.createElement('div'); t.id = 'cgCopToast'; t.className = 'cg-cop-toast'; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add('cg-cop-toast-on');
    clearTimeout(window._cgCopToastT); window._cgCopToastT = setTimeout(() => t.classList.remove('cg-cop-toast-on'), 2200);
}

// ---- Memória de conversa (codegen_chats) --------------------------------
async function cgCopRefreshChats() {
    const sel = document.getElementById('cgCopChatSel'); if (!sel) return;
    try {
        const res = await fetch('/api/codegen/chats');
        const rows = res.ok ? await res.json() : [];
        sel.innerHTML = '<option value="">— conversas —</option>'
            + rows.map(r => '<option value="' + r.id + '">' + _cgEscape(r.title) + '</option>').join('');
        if (cgCopChatId) sel.value = String(cgCopChatId);
    } catch (e) { /* opcional */ }
}

async function cgCopLoadChat(id) {
    if (!id) return;
    try {
        const res = await fetch('/api/codegen/chats/' + id);
        if (!res.ok) return;
        const c = await res.json();
        cgCopChatId = c.id;
        cgCopHistory = (c.messages || []).map(m => ({ role: m.role, content: m.content, sql: m.sql, actions: m.actions }));
        cgCopRenderThread();
    } catch (e) { /* opcional */ }
}

function cgCopNewChat() {
    cgCopChatId = null; cgCopHistory = [];
    const s = document.getElementById('cgCopChatSel'); if (s) s.value = '';
    cgCopRenderThread();
}

async function cgCopSaveChat() {
    const msgs = cgCopHistory.filter(m => !m._pending).map(m => ({ role: m.role, content: m.content, sql: m.sql || '', actions: m.actions || [] }));
    if (!msgs.length) { cgCopToast('Nada para salvar.'); return; }
    const firstUser = cgCopHistory.find(m => m.role === 'user');
    const title = (firstUser ? firstUser.content : 'Conversa').slice(0, 60);
    try {
        const res = await fetch('/api/codegen/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: cgCopChatId, title, messages: msgs }) });
        const data = await res.json();
        if (data.id) { cgCopChatId = data.id; cgCopRefreshChats(); cgCopToast('Conversa salva.'); } else cgCopToast('Erro ao salvar.');
    } catch (e) { cgCopToast('Falha: ' + e.message); }
}

async function cgCopDeleteChat() {
    if (!cgCopChatId) { cgCopToast('Nenhuma conversa carregada.'); return; }
    if (!confirm('Excluir esta conversa?')) return;
    try { await fetch('/api/codegen/chats/' + cgCopChatId, { method: 'DELETE' }); } catch (e) {}
    cgCopNewChat(); cgCopRefreshChats(); cgCopToast('Conversa excluída.');
}
