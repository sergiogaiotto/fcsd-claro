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
            resultBox.innerHTML = '<div class="text-red-400 text-sm py-4 font-mono">' + _cgEscape(data.error || 'Erro ao executar.') + '</div>';
            status.textContent = 'Erro • ' + ms + ' ms';
            return;
        }
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

// ---- P3: gerar código Python --------------------------------------------
async function cgGenPython() {
    const sql = cgEditor ? cgEditor.getValue().trim() : '';
    const pre = document.getElementById('cgPyCode');
    const bar = document.getElementById('cgPyBar');
    if (!sql) { pre.textContent = 'Escreva um SQL na aba "Editor SQL" primeiro.'; return; }
    const lib = (document.getElementById('cgPyLib') || {}).value || 'pandas';
    pre.textContent = 'Gerando…';
    if (bar) bar.style.display = 'none';
    try {
        const res = await fetch('/api/codegen/pycode', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sql, lib }),
        });
        const data = await res.json();
        if (!res.ok || data.error) { pre.textContent = data.error || 'Erro ao gerar.'; return; }
        cgPyCode = data.code || '';
        cgPyName = data.filename || 'tdia_codegen.py';
        pre.textContent = cgPyCode;        // textContent → sem risco de injeção
        if (bar) { bar.style.display = 'flex'; document.getElementById('cgPyName').textContent = cgPyName; }
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

// ---- Init ---------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    _cgApplyTheme(_cgIsDark());   // sincroniza ícone/rótulo do botão
    cgInitEditor();
    cgLoadScope();
    cgLoadSchema();
    cgLoadSnippets();
    cgShowSection('editor');
});
