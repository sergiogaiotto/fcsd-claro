// ============================
// DATA PRODUCTS (ODPS) — JavaScript Module
// ============================
// Inserir no bloco <script> do default.html, antes do fechamento </script>

let _dpAll = [];
let _dpSelectedId = null;

const _dpStatusConfig = {
    draft:      { color: '#8b949e', bg: 'rgba(139,148,158,0.12)', border: '#8b949e40', label: 'DRAFT' },
    active:     { color: '#39d353', bg: 'rgba(57,211,83,0.12)',   border: '#39d35340', label: 'ACTIVE' },
    deprecated: { color: '#f0883e', bg: 'rgba(240,136,62,0.12)',  border: '#f0883e40', label: 'DEPRECATED' },
    retired:    { color: '#ff6347', bg: 'rgba(255,99,71,0.12)',   border: '#ff634740', label: 'RETIRED' },
};

const _dpLayerLabels = { raw: 'Raw', refined: 'Refined', insight: 'Insight' };
const _dpConsumptionLabels = { analytical: 'Analytical', operational: 'Operational', ml_ai: 'ML/AI' };
const _dpClassLabels = { public: 'Public', internal: 'Internal', restricted: 'Restricted' };

// ── Load ─────────────────────────────────────────────────────────────────

async function loadDataProducts() {
    try {
        const res = await fetch('/api/data-products');
        if (!res.ok) return;
        _dpAll = await res.json();
        _renderDPDashboard();
    } catch(e) { console.error('DP load error:', e); }
}

function _renderDPDashboard() {
    const list  = document.getElementById('dpList');
    const empty = document.getElementById('dpEmpty');
    const count = document.getElementById('dpCount');

    if (!_dpAll.length) {
        list.classList.add('hidden');
        empty.classList.remove('hidden');
        count.textContent = '';
        document.getElementById('dpKPIs').innerHTML = '';
        return;
    }

    list.classList.remove('hidden');
    empty.classList.add('hidden');
    count.textContent = `${_dpAll.length} produto(s)`;

    // KPIs
    const byStatus = {};
    const byDomain = {};
    const byLayer  = {};
    _dpAll.forEach(p => {
        byStatus[p.status] = (byStatus[p.status] || 0) + 1;
        byDomain[p.domain || 'N/D'] = (byDomain[p.domain || 'N/D'] || 0) + 1;
        byLayer[p.value_layer || 'refined'] = (byLayer[p.value_layer || 'refined'] || 0) + 1;
    });

    document.getElementById('dpKPIs').innerHTML = `
        <div class="bg-fg-800 border border-fg-border rounded-xl p-3 text-center">
            <div class="text-lg font-bold font-mono text-fg-bright">${_dpAll.length}</div>
            <div class="text-[9px] text-fg-muted uppercase tracking-wider mt-1">Total</div>
        </div>
        <div class="bg-fg-800 border border-fg-border rounded-xl p-3 text-center">
            <div class="text-lg font-bold font-mono text-fg-green">${byStatus.active || 0}</div>
            <div class="text-[9px] text-fg-muted uppercase tracking-wider mt-1">Ativos</div>
        </div>
        <div class="bg-fg-800 border border-fg-border rounded-xl p-3 text-center">
            <div class="text-lg font-bold font-mono text-fg-muted">${byStatus.draft || 0}</div>
            <div class="text-[9px] text-fg-muted uppercase tracking-wider mt-1">Draft</div>
        </div>
        <div class="bg-fg-800 border border-fg-border rounded-xl p-3 text-center">
            <div class="text-lg font-bold font-mono text-fg-accent">${byStatus.deprecated || 0}</div>
            <div class="text-[9px] text-fg-muted uppercase tracking-wider mt-1">Deprecated</div>
        </div>
        <div class="bg-fg-800 border border-fg-border rounded-xl p-3 text-center">
            <div class="text-lg font-bold font-mono text-fg-blue">${Object.keys(byDomain).length}</div>
            <div class="text-[9px] text-fg-muted uppercase tracking-wider mt-1">Domínios</div>
        </div>
        <div class="bg-fg-800 border border-fg-border rounded-xl p-3 text-center">
            <div class="text-lg font-bold font-mono text-purple-400">${Object.keys(byLayer).length}</div>
            <div class="text-[9px] text-fg-muted uppercase tracking-wider mt-1">Camadas</div>
        </div>
    `;

    // Populate domain filter
    const domFilter = document.getElementById('dpFilterDomain');
    const currentDomVal = domFilter.value;
    const domains = [...new Set(_dpAll.map(p => p.domain || '').filter(Boolean))].sort();
    domFilter.innerHTML = '<option value="">Todos</option>' + domains.map(d => `<option value="${d}" ${d === currentDomVal ? 'selected' : ''}>${d}</option>`).join('');

    filterDataProducts();
}

function filterDataProducts() {
    const status      = document.getElementById('dpFilterStatus').value;
    const domain      = document.getElementById('dpFilterDomain').value;
    const layer       = document.getElementById('dpFilterLayer').value;
    const consumption = document.getElementById('dpFilterConsumption').value;
    const search      = (document.getElementById('dpSearch').value || '').toLowerCase();

    let filtered = _dpAll.filter(p => {
        if (status && p.status !== status) return false;
        if (domain && p.domain !== domain) return false;
        if (layer && p.value_layer !== layer) return false;
        if (consumption && p.consumption_type !== consumption) return false;
        if (search) {
            const haystack = [
                p.name, p.display_name, p.domain, p.purpose,
                p.nomenclature, p.owner_team,
            ].join(' ').toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });

    _renderDPList(filtered);
}

function _renderDPList(products) {
    const list = document.getElementById('dpList');

    if (!products.length) {
        list.innerHTML = '<div class="text-center py-8 text-fg-muted text-xs">Nenhum produto encontrado com os filtros selecionados.</div>';
        return;
    }

    list.innerHTML = products.map(p => {
        const sc = _dpStatusConfig[p.status] || _dpStatusConfig.draft;
        const layerLabel = _dpLayerLabels[p.value_layer] || p.value_layer;
        const consLabel  = _dpConsumptionLabels[p.consumption_type] || p.consumption_type;
        const classLabel = _dpClassLabels[p.classification] || p.classification;
        const consumers  = (p.consumers || []).slice(0, 3).join(', ');
        const artCount   = (p.artifacts || []).length;
        const outCount   = (p.output_ports || []).length;
        const hasOwner   = !!p.owner_team;
        const hasSLA     = !!(p.sla_freshness || p.sla_availability);

        return `
        <div class="bg-fg-900 rounded-xl border border-fg-border px-5 py-4 hover:border-emerald-500/30 transition-all cursor-pointer group"
             onclick="showDPDetail(${p.id})">
            <div class="flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1.5 flex-wrap">
                        <span class="text-sm font-bold text-emerald-400 font-mono">${escapeHtml(p.display_name || p.name)}</span>
                        <span class="text-[9px] px-2 py-0.5 rounded-full font-mono font-bold" style="color:${sc.color};background:${sc.bg};border:1px solid ${sc.border}">${sc.label}</span>
                        <span class="text-[9px] bg-fg-700 text-fg-muted px-1.5 py-0.5 rounded border border-fg-border font-mono">v${p.version}</span>
                        ${p.domain ? `<span class="text-[9px] bg-fg-blue/10 text-fg-blue px-1.5 py-0.5 rounded-full">${escapeHtml(p.domain)}</span>` : ''}
                        <span class="text-[9px] bg-purple-500/10 text-purple-400 px-1.5 py-0.5 rounded-full">${layerLabel}</span>
                        <span class="text-[9px] bg-fg-700 text-fg-muted px-1.5 py-0.5 rounded-full">${consLabel}</span>
                    </div>
                    <div class="text-[11px] text-fg-muted font-mono mb-1">${escapeHtml(p.nomenclature || '')}</div>
                    ${p.purpose ? `<p class="text-xs text-fg-text leading-relaxed line-clamp-2 mb-2">${escapeHtml(p.purpose)}</p>` : ''}
                    <div class="flex flex-wrap gap-3 text-[10px] text-fg-muted">
                        <span class="flex items-center gap-1">${hasOwner ? '<span class="text-fg-green">●</span>' : '<span class="text-red-400">●</span>'} Owner: ${hasOwner ? escapeHtml(p.owner_team) : 'N/D'}</span>
                        <span>${artCount} artefato(s)</span>
                        <span>${outCount} output port(s)</span>
                        ${hasSLA ? '<span class="text-fg-green">SLA ✓</span>' : '<span class="text-fg-muted/50">SLA —</span>'}
                        ${consumers ? `<span>Consumidores: ${escapeHtml(consumers)}</span>` : ''}
                    </div>
                </div>
                <div class="flex items-center gap-2 flex-shrink-0 opacity-0 group-hover:opacity-100 transition">
                    <button onclick="event.stopPropagation(); openDPModal(${p.id})" class="text-[10px] text-fg-muted hover:text-emerald-400 border border-fg-border px-2 py-1 rounded transition">Editar</button>
                    <button onclick="event.stopPropagation(); deleteDP(${p.id}, '${escapeHtml(p.name)}')" class="text-fg-muted hover:text-red-400 transition p-1">
                        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    </button>
                </div>
            </div>
        </div>`;
    }).join('');
}

// ── Detail ────────────────────────────────────────────────────────────────

function showDPDetail(productId) {
    _dpSelectedId = productId;
    const p = _dpAll.find(x => x.id === productId);
    if (!p) return;

    document.getElementById('dpDetail').classList.remove('hidden');
    document.getElementById('dpDetailName').textContent = p.display_name || p.name;

    const sc = _dpStatusConfig[p.status] || _dpStatusConfig.draft;
    const statusEl = document.getElementById('dpDetailStatus');
    statusEl.textContent = sc.label;
    statusEl.style.color = sc.color;
    statusEl.style.background = sc.bg;

    const domEl = document.getElementById('dpDetailDomain');
    domEl.textContent = p.domain || 'N/D';
    domEl.style.color = '#58a6ff';
    domEl.style.borderColor = 'rgba(88,166,255,0.3)';

    document.getElementById('dpDetailVersion').textContent = 'v' + p.version;
    document.getElementById('dpDetailNomenclature').textContent = p.nomenclature || '(nomenclatura será gerada ao salvar)';
    document.getElementById('dpDetailPurpose').textContent = p.purpose || '';

    document.getElementById('dpValidationBanner').classList.add('hidden');

    showDPDetailTab('overview');
    _renderDPOverview(p);
    _renderDPArtifacts(p);
    _renderDPQuality(p);
    _renderDPLifecycle(p);

    document.getElementById('dpDetail').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeDPDetail() {
    document.getElementById('dpDetail').classList.add('hidden');
    _dpSelectedId = null;
}

function showDPDetailTab(tab) {
    ['overview', 'artifacts', 'quality', 'lifecycle'].forEach(t => {
        document.getElementById('dppanel-' + t).classList.toggle('hidden', t !== tab);
        const btn = document.getElementById('dptab-' + t);
        if (t === tab) { btn.classList.add('border-emerald-400', 'text-emerald-400'); btn.classList.remove('border-transparent', 'text-fg-muted'); }
        else { btn.classList.remove('border-emerald-400', 'text-emerald-400'); btn.classList.add('border-transparent', 'text-fg-muted'); }
    });
}

function _renderDPOverview(p) {
    const el = document.getElementById('dppanel-overview');
    const consumers = (p.consumers || []).join(', ') || '—';
    const compliance = (p.compliance || []).join(', ') || '—';
    const tags = p.tags || {};

    el.innerHTML = `
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="bg-fg-900 rounded-lg p-4 border border-fg-border">
            <div class="text-[10px] text-emerald-400 uppercase tracking-wider font-mono font-bold mb-3">Valor de Negócio</div>
            <div class="space-y-2 text-xs">
                <div class="flex justify-between border-b border-fg-border/30 pb-1"><span class="text-fg-muted">Propósito</span><span class="text-fg-text text-right max-w-[60%]">${escapeHtml(p.purpose || '—')}</span></div>
                <div class="flex justify-between border-b border-fg-border/30 pb-1"><span class="text-fg-muted">Business Value</span><span class="text-fg-text text-right max-w-[60%]">${escapeHtml(p.business_value || '—')}</span></div>
                <div class="flex justify-between"><span class="text-fg-muted">Consumidores</span><span class="text-fg-text text-right max-w-[60%]">${escapeHtml(consumers)}</span></div>
            </div>
        </div>
        <div class="bg-fg-900 rounded-lg p-4 border border-fg-border">
            <div class="text-[10px] text-fg-blue uppercase tracking-wider font-mono font-bold mb-3">Ownership</div>
            <div class="space-y-2 text-xs">
                <div class="flex justify-between border-b border-fg-border/30 pb-1"><span class="text-fg-muted">Team</span><span class="text-fg-text font-mono">${escapeHtml(p.owner_team || '—')}</span></div>
                <div class="flex justify-between border-b border-fg-border/30 pb-1"><span class="text-fg-muted">Email</span><span class="text-fg-text">${escapeHtml(p.owner_email || '—')}</span></div>
                <div class="flex justify-between border-b border-fg-border/30 pb-1"><span class="text-fg-muted">Role</span><span class="text-fg-text">${escapeHtml(p.owner_role || '—')}</span></div>
                <div class="flex justify-between border-b border-fg-border/30 pb-1"><span class="text-fg-muted">Classificação</span><span class="text-fg-text">${_dpClassLabels[p.classification] || p.classification}</span></div>
                <div class="flex justify-between"><span class="text-fg-muted">Compliance</span><span class="text-fg-text">${escapeHtml(compliance)}</span></div>
            </div>
        </div>
        <div class="bg-fg-900 rounded-lg p-4 border border-fg-border sm:col-span-2">
            <div class="text-[10px] text-purple-400 uppercase tracking-wider font-mono font-bold mb-3">Classificação</div>
            <div class="flex flex-wrap gap-4 text-xs">
                <div><span class="text-fg-muted">Domínio:</span> <span class="text-fg-blue font-bold">${escapeHtml(p.domain || '—')}</span></div>
                <div><span class="text-fg-muted">Camada:</span> <span class="text-purple-400 font-bold">${_dpLayerLabels[p.value_layer] || '—'}</span></div>
                <div><span class="text-fg-muted">Consumo:</span> <span class="text-fg-text font-bold">${_dpConsumptionLabels[p.consumption_type] || '—'}</span></div>
                <div><span class="text-fg-muted">Criado por:</span> <span class="text-fg-text font-mono">${escapeHtml(p.created_by || '—')}</span></div>
                <div><span class="text-fg-muted">Criado em:</span> <span class="text-fg-text font-mono">${p.created_at ? p.created_at.slice(0,16).replace('T',' ') : '—'}</span></div>
            </div>
        </div>
    </div>`;
}

function _renderDPArtifacts(p) {
    const el = document.getElementById('dppanel-artifacts');
    const artifacts  = p.artifacts || [];
    const inputPorts = p.input_ports || [];
    const outputPorts = p.output_ports || [];

    let html = '<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">';

    // Artefatos
    html += '<div class="bg-fg-900 rounded-lg p-4 border border-fg-border"><div class="text-[10px] text-emerald-400 uppercase tracking-wider font-mono font-bold mb-3">Artefatos (' + artifacts.length + ')</div>';
    if (artifacts.length) {
        html += '<div class="space-y-2">';
        artifacts.forEach(a => {
            const aName = typeof a === 'object' ? (a.name || '?') : String(a);
            const aType = typeof a === 'object' ? (a.type || 'dataset') : 'dataset';
            const versions = typeof a === 'object' ? (a.versions || []) : [];
            html += `<div class="bg-fg-800 rounded-lg px-3 py-2 border border-fg-border/50">
                <div class="flex items-center gap-2">
                    <span class="text-xs text-fg-bright font-mono font-bold">${escapeHtml(aName)}</span>
                    <span class="text-[9px] bg-fg-blue/10 text-fg-blue px-1.5 py-0.5 rounded">${escapeHtml(aType)}</span>
                </div>
                ${versions.length ? '<div class="mt-1 text-[10px] text-fg-muted">' + versions.map(v => `v${v.version || '?'} (${v.status || '?'})`).join(', ') + '</div>' : ''}
            </div>`;
        });
        html += '</div>';
    } else {
        html += '<p class="text-[11px] text-fg-muted italic">Nenhum artefato definido.</p>';
    }
    html += '</div>';

    // Input Ports
    html += '<div class="bg-fg-900 rounded-lg p-4 border border-fg-border"><div class="text-[10px] text-fg-accent uppercase tracking-wider font-mono font-bold mb-3">Input Ports (' + inputPorts.length + ')</div>';
    if (inputPorts.length) {
        html += '<div class="space-y-2">';
        inputPorts.forEach(port => {
            const pName = typeof port === 'object' ? (port.name || '?') : String(port);
            const pContract = typeof port === 'object' ? (port.contractId || '') : '';
            const pType = typeof port === 'object' ? (port.dataType || '') : '';
            html += `<div class="bg-fg-800 rounded-lg px-3 py-2 border border-fg-border/50 text-xs">
                <span class="text-fg-bright font-mono">${escapeHtml(pName)}</span>
                ${pContract ? ` <span class="text-fg-muted">contract: ${escapeHtml(pContract)}</span>` : ''}
                ${pType ? ` <span class="text-fg-blue text-[9px]">${escapeHtml(pType)}</span>` : ''}
            </div>`;
        });
        html += '</div>';
    } else {
        html += '<p class="text-[11px] text-fg-muted italic">Nenhum input port.</p>';
    }
    html += '</div>';

    // Output Ports
    html += '<div class="bg-fg-900 rounded-lg p-4 border border-fg-border"><div class="text-[10px] text-fg-green uppercase tracking-wider font-mono font-bold mb-3">Output Ports (' + outputPorts.length + ')</div>';
    if (outputPorts.length) {
        html += '<div class="space-y-2">';
        outputPorts.forEach(port => {
            const pName = typeof port === 'object' ? (port.name || '?') : String(port);
            const pContract = typeof port === 'object' ? (port.contractId || '') : '';
            const pType = typeof port === 'object' ? (port.dataType || '') : '';
            html += `<div class="bg-fg-800 rounded-lg px-3 py-2 border border-fg-border/50 text-xs">
                <span class="text-fg-bright font-mono">${escapeHtml(pName)}</span>
                ${pContract ? ` <span class="text-fg-muted">contract: ${escapeHtml(pContract)}</span>` : ''}
                ${pType ? ` <span class="text-fg-green text-[9px]">${escapeHtml(pType)}</span>` : ''}
            </div>`;
        });
        html += '</div>';
    } else {
        html += '<p class="text-[11px] text-fg-muted italic">Nenhum output port.</p>';
    }
    html += '</div></div>';

    el.innerHTML = html;
}

function _renderDPQuality(p) {
    const el = document.getElementById('dppanel-quality');
    const rules = p.quality_rules || [];

    let html = '<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">';

    // SLA
    html += '<div class="bg-fg-900 rounded-lg p-4 border border-fg-border"><div class="text-[10px] text-fg-green uppercase tracking-wider font-mono font-bold mb-3">SLA</div>';
    html += `<div class="space-y-2 text-xs">
        <div class="flex justify-between border-b border-fg-border/30 pb-1"><span class="text-fg-muted">Freshness</span><span class="text-fg-text font-mono font-bold">${escapeHtml(p.sla_freshness || '—')}</span></div>
        <div class="flex justify-between"><span class="text-fg-muted">Availability</span><span class="text-fg-text font-mono font-bold">${escapeHtml(p.sla_availability || '—')}</span></div>
    </div>`;
    html += '</div>';

    // Quality Rules
    html += '<div class="bg-fg-900 rounded-lg p-4 border border-fg-border"><div class="text-[10px] text-fg-accent uppercase tracking-wider font-mono font-bold mb-3">Regras de Qualidade (' + rules.length + ')</div>';
    if (rules.length) {
        html += '<div class="space-y-1.5">';
        rules.forEach(r => {
            const rName = typeof r === 'object' ? (r.name || '?') : String(r);
            const rType = typeof r === 'object' ? (r.type || '') : '';
            const rThreshold = typeof r === 'object' ? (r.threshold || '') : '';
            html += `<div class="flex items-center gap-2 text-xs bg-fg-800 rounded-lg px-3 py-2 border border-fg-border/50">
                <span class="text-fg-bright font-mono">${escapeHtml(rName)}</span>
                ${rType ? `<span class="text-[9px] bg-fg-blue/10 text-fg-blue px-1.5 py-0.5 rounded">${escapeHtml(rType)}</span>` : ''}
                ${rThreshold ? `<span class="text-[9px] text-fg-green font-mono ml-auto">${escapeHtml(rThreshold)}</span>` : ''}
            </div>`;
        });
        html += '</div>';
    } else {
        html += '<p class="text-[11px] text-fg-muted italic">Nenhuma regra definida.</p>';
    }
    html += '</div></div>';

    el.innerHTML = html;
}

function _renderDPLifecycle(p) {
    const el = document.getElementById('dppanel-lifecycle');
    const stages = ['draft', 'active', 'deprecated', 'retired'];
    const currentIdx = stages.indexOf(p.status);

    const validTransitions = {
        draft: ['active'],
        active: ['deprecated'],
        deprecated: ['active', 'retired'],
        retired: [],
    };

    let html = '<div class="bg-fg-900 rounded-lg p-5 border border-fg-border">';
    html += '<div class="text-[10px] text-fg-muted uppercase tracking-wider font-mono font-bold mb-4">Ciclo de Vida</div>';

    // Visual pipeline
    html += '<div class="flex items-center justify-center gap-1 mb-6">';
    stages.forEach((s, i) => {
        const sc = _dpStatusConfig[s];
        const isCurrent = s === p.status;
        const isPast = i < currentIdx;
        html += `<div class="flex items-center gap-1">
            <div class="flex flex-col items-center">
                <div class="w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold font-mono transition-all
                    ${isCurrent ? 'ring-2 ring-offset-2 ring-offset-fg-900' : ''}"
                    style="background:${isCurrent ? sc.bg : (isPast ? 'rgba(57,211,83,0.1)' : '#21262d')};
                           color:${isCurrent ? sc.color : (isPast ? '#39d353' : '#484f58')};
                           ${isCurrent ? 'ring-color:' + sc.color : ''}">
                    ${isPast ? '✓' : (i + 1)}
                </div>
                <span class="text-[9px] mt-1.5 font-mono font-bold" style="color:${isCurrent ? sc.color : '#8b949e'}">${sc.label}</span>
            </div>
            ${i < stages.length - 1 ? '<div class="w-12 h-0.5 mx-1" style="background:' + (isPast ? '#39d353' : '#30363d') + '"></div>' : ''}
        </div>`;
    });
    html += '</div>';

    // Transition buttons
    const allowed = validTransitions[p.status] || [];
    if (allowed.length) {
        html += '<div class="flex justify-center gap-3 mt-4">';
        allowed.forEach(next => {
            const nsc = _dpStatusConfig[next];
            html += `<button onclick="transitionDPStatus(${p.id}, '${next}')"
                class="text-xs font-semibold px-4 py-2 rounded-lg transition flex items-center gap-1.5"
                style="background:${nsc.bg};color:${nsc.color};border:1px solid ${nsc.border}">
                Avançar para ${nsc.label} →
            </button>`;
        });
        html += '</div>';
    }

    // Versioning info
    html += `<div class="mt-5 bg-fg-800 rounded-lg p-3 border border-fg-border text-[11px] text-fg-muted leading-relaxed">
        <strong class="text-fg-text">Versionamento semver:</strong> MAJOR (quebra de contrato) · MINOR (incremento) · PATCH (correção)
        <br>Versão atual: <span class="text-emerald-400 font-mono font-bold">v${p.version}</span>
        ${p.updated_at ? ` · Última atualização: <span class="text-fg-text font-mono">${p.updated_at.slice(0,16).replace('T',' ')}</span>` : ''}
    </div>`;

    html += '</div>';
    el.innerHTML = html;
}

// ── Validation ────────────────────────────────────────────────────────────

async function validateDP() {
    if (!_dpSelectedId) return;
    try {
        const res = await fetch(`/api/data-products/${_dpSelectedId}/validate`);
        const data = await res.json();
        const banner = document.getElementById('dpValidationBanner');
        banner.classList.remove('hidden');

        if (data.valid) {
            banner.style.background = 'rgba(57,211,83,0.08)';
            banner.style.border = '1px solid rgba(57,211,83,0.25)';
            banner.style.color = '#39d353';
            banner.innerHTML = `<strong>✓ Produto válido</strong> — ${data.checks_passed}/${data.checks_total} critérios atendidos. Pronto para publicação.`;
        } else {
            banner.style.background = 'rgba(255,99,71,0.08)';
            banner.style.border = '1px solid rgba(255,99,71,0.25)';
            banner.style.color = '#ff6347';
            banner.innerHTML = `<strong>✗ Bloqueio de publicação</strong> — ${data.checks_passed}/${data.checks_total} critérios atendidos.<br>` +
                data.errors.map(e => `<span class="text-fg-muted">• ${escapeHtml(e)}</span>`).join('<br>');
        }
    } catch(e) { alert('Erro: ' + e.message); }
}

// ── Status Transition ─────────────────────────────────────────────────────

async function transitionDPStatus(productId, newStatus) {
    if (!confirm(`Alterar status para "${newStatus.toUpperCase()}"?`)) return;
    try {
        const res = await fetch(`/api/data-products/${productId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_status: newStatus }),
        });
        const data = await res.json();
        if (!res.ok) { alert(data.detail || data.error || 'Erro.'); return; }
        await loadDataProducts();
        showDPDetail(productId);
    } catch(e) { alert('Erro: ' + e.message); }
}

// ── Modal ─────────────────────────────────────────────────────────────────

async function openDPModal(productId) {
    const modal = document.getElementById('dpModal');
    document.getElementById('dpEditId').value = productId || '';
    document.getElementById('dpModalTitle').textContent = productId ? 'Editar Produto de Dados' : 'Novo Produto de Dados';

    if (productId) {
        const p = _dpAll.find(x => x.id === productId);
        if (p) {
            document.getElementById('dpName').value = p.name || '';
            document.getElementById('dpDisplayName').value = p.display_name || '';
            document.getElementById('dpVersion').value = p.version || '1.0.0';
            document.getElementById('dpStatus').value = p.status || 'draft';
            document.getElementById('dpDomain').value = p.domain || '';
            document.getElementById('dpPurpose').value = p.purpose || '';
            document.getElementById('dpBusinessValue').value = p.business_value || '';
            document.getElementById('dpConsumers').value = (p.consumers || []).join(', ');
            document.getElementById('dpOwnerTeam').value = p.owner_team || '';
            document.getElementById('dpOwnerEmail').value = p.owner_email || '';
            document.getElementById('dpOwnerRole').value = p.owner_role || 'data product owner';
            document.getElementById('dpClassification').value = p.classification || 'internal';
            document.getElementById('dpCompliance').value = (p.compliance || []).join(', ');
            document.getElementById('dpValueLayer').value = p.value_layer || 'refined';
            document.getElementById('dpConsumptionType').value = p.consumption_type || 'analytical';
            document.getElementById('dpSLAFreshness').value = p.sla_freshness || '';
            document.getElementById('dpSLAAvailability').value = p.sla_availability || '';
            document.getElementById('dpArtifacts').value = JSON.stringify(p.artifacts || [], null, 2);
            document.getElementById('dpInputPorts').value = JSON.stringify(p.input_ports || [], null, 2);
            document.getElementById('dpOutputPorts').value = JSON.stringify(p.output_ports || [], null, 2);
            document.getElementById('dpQualityRules').value = JSON.stringify(p.quality_rules || [], null, 2);
        }
    } else {
        // Reset all fields
        ['dpName','dpDisplayName','dpPurpose','dpBusinessValue','dpConsumers',
         'dpOwnerTeam','dpOwnerEmail','dpCompliance','dpSLAFreshness','dpSLAAvailability'].forEach(id => {
            document.getElementById(id).value = '';
        });
        document.getElementById('dpVersion').value = '1.0.0';
        document.getElementById('dpStatus').value = 'draft';
        document.getElementById('dpDomain').value = '';
        document.getElementById('dpOwnerRole').value = 'data product owner';
        document.getElementById('dpClassification').value = 'internal';
        document.getElementById('dpValueLayer').value = 'refined';
        document.getElementById('dpConsumptionType').value = 'analytical';
        document.getElementById('dpArtifacts').value = '[]';
        document.getElementById('dpInputPorts').value = '[]';
        document.getElementById('dpOutputPorts').value = '[]';
        document.getElementById('dpQualityRules').value = '[]';
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.getElementById('dpName').focus();
}

function closeDPModal() {
    document.getElementById('dpModal').classList.add('hidden');
    document.getElementById('dpModal').classList.remove('flex');
}

function _parseCSV(val) {
    return (val || '').split(',').map(s => s.trim()).filter(Boolean);
}

function _parseJSON(val, fallback) {
    try { return JSON.parse(val || JSON.stringify(fallback)); }
    catch(e) { return fallback; }
}

async function saveDataProduct() {
    const id   = document.getElementById('dpEditId').value;
    const name = document.getElementById('dpName').value.trim();
    if (!name || name.length < 2) { alert('Nome obrigatório (mínimo 2 caracteres).'); return; }

    const btn = document.getElementById('btnSaveDP');
    btn.disabled = true;
    btn.textContent = 'Salvando...';

    const payload = {
        name,
        display_name:     document.getElementById('dpDisplayName').value.trim() || name,
        version:          document.getElementById('dpVersion').value.trim() || '1.0.0',
        status:           document.getElementById('dpStatus').value,
        domain:           document.getElementById('dpDomain').value,
        purpose:          document.getElementById('dpPurpose').value.trim(),
        business_value:   document.getElementById('dpBusinessValue').value.trim(),
        consumers:        _parseCSV(document.getElementById('dpConsumers').value),
        owner_team:       document.getElementById('dpOwnerTeam').value.trim(),
        owner_email:      document.getElementById('dpOwnerEmail').value.trim(),
        owner_role:       document.getElementById('dpOwnerRole').value.trim(),
        classification:   document.getElementById('dpClassification').value,
        compliance:       _parseCSV(document.getElementById('dpCompliance').value),
        value_layer:      document.getElementById('dpValueLayer').value,
        consumption_type: document.getElementById('dpConsumptionType').value,
        sla_freshness:    document.getElementById('dpSLAFreshness').value.trim(),
        sla_availability: document.getElementById('dpSLAAvailability').value.trim(),
        artifacts:        _parseJSON(document.getElementById('dpArtifacts').value, []),
        input_ports:      _parseJSON(document.getElementById('dpInputPorts').value, []),
        output_ports:     _parseJSON(document.getElementById('dpOutputPorts').value, []),
        quality_rules:    _parseJSON(document.getElementById('dpQualityRules').value, []),
    };

    try {
        const url    = id ? `/api/data-products/${id}` : '/api/data-products';
        const method = id ? 'PUT' : 'POST';
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            const e = await res.json();
            alert(e.detail || 'Erro ao salvar.');
            btn.disabled = false;
            btn.textContent = 'Salvar Produto';
            return;
        }
        closeDPModal();
        await loadDataProducts();
        // Se editando, reabrir detalhe
        if (id) showDPDetail(parseInt(id));
    } catch(e) {
        alert('Erro: ' + e.message);
    }
    btn.disabled = false;
    btn.textContent = 'Salvar Produto';
}

// ── Delete ────────────────────────────────────────────────────────────────

async function deleteDP(id, name) {
    if (!confirm(`Excluir o produto "${name}"?`)) return;
    try {
        const res = await fetch(`/api/data-products/${id}`, { method: 'DELETE' });
        if (res.ok) {
            if (_dpSelectedId === id) closeDPDetail();
            await loadDataProducts();
        } else {
            const e = await res.json();
            alert(e.detail || 'Erro.');
        }
    } catch(e) { alert('Erro: ' + e.message); }
}

// ── Export / Import ───────────────────────────────────────────────────────

async function exportDataProducts() {
    try {
        const res = await fetch('/api/data-products/export/excel');
        if (!res.ok) { alert('Erro ao exportar.'); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = 'data_products_export.xlsx'; a.click();
        URL.revokeObjectURL(url);
    } catch(e) { alert('Erro: ' + e.message); }
}

async function importDataProducts() {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.xlsx,.xls';
    input.onchange = async () => {
        if (!input.files[0]) return;
        const fd = new FormData(); fd.append('file', input.files[0]);
        try {
            const res = await fetch('/api/data-products/import', { method: 'POST', body: fd });
            const d = await res.json();
            alert(`Importados: ${d.total}${d.errors.length ? '\nErros: ' + d.errors.join('; ') : ''}`);
            loadDataProducts();
        } catch(e) { alert('Erro: ' + e.message); }
    };
    input.click();
}


let _scanResults = [];
let _scanSelectedIdxs = new Set();
 
// ── Abrir modal do scanner ───────────────────────────────────────────────
 
async function openDPScanner() {
    const modal = document.getElementById('dpScannerModal');
    if (!modal) return;
 
    // Reset state
    _scanResults = [];
    _scanSelectedIdxs.clear();
    document.getElementById('dpScanStatus').textContent = '';
    document.getElementById('dpScanResults').classList.add('hidden');
    document.getElementById('dpScanResults').innerHTML = '';
    document.getElementById('dpScanEmpty').classList.add('hidden');
    document.getElementById('dpScanLoading').classList.add('hidden');
    document.getElementById('btnSaveScanResults').classList.add('hidden');
    document.getElementById('btnSaveScanResults').disabled = false;
 
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}
 
function closeDPScanner() {
    const modal = document.getElementById('dpScannerModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}
 
// ── Executar scanner ─────────────────────────────────────────────────────
 
async function runDPScanner() {
    const btn     = document.getElementById('btnRunDPScan');
    const status  = document.getElementById('dpScanStatus');
    const loading = document.getElementById('dpScanLoading');
    const results = document.getElementById('dpScanResults');
    const empty   = document.getElementById('dpScanEmpty');
    const saveBtn = document.getElementById('btnSaveScanResults');
    const includeCatalog = document.getElementById('dpScanIncludeCatalog')?.checked ?? true;
 
    btn.disabled = true;
    btn.innerHTML = '<span style="animation:spin 1s linear infinite;display:inline-block">⟳</span> Escaneando…';
    status.style.color = '#8b949e';
    status.textContent = 'Analisando tabelas e gerando sugestões ODPS com IA…';
    loading.classList.remove('hidden');
    results.classList.add('hidden');
    empty.classList.add('hidden');
    saveBtn.classList.add('hidden');
 
    try {
        const res = await fetch('/api/data-products/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ include_catalog: includeCatalog }),
        });
        const data = await res.json();
        loading.classList.add('hidden');
 
        if (data.error) {
            status.style.color = '#ff6347';
            status.textContent = '✗ ' + data.error;
            btn.disabled = false;
            btn.innerHTML = _scanBtnHtml();
            return;
        }
 
        _scanResults = data.suggestions || [];
 
        if (!_scanResults.length) {
            status.style.color = '#f0883e';
            status.textContent = data.message || 'Nenhuma sugestão gerada.';
            empty.classList.remove('hidden');
        } else {
            status.style.color = '#39d353';
            status.textContent = `✓ ${_scanResults.length} sugestão(ões) · ${data.tables_scanned} tabelas escaneadas` +
                (data.tables_skipped > 0 ? ` · ${data.tables_skipped} já com produto` : '');
 
            // Selecionar todas por padrão
            _scanSelectedIdxs.clear();
            _scanResults.forEach((_, i) => _scanSelectedIdxs.add(i));
 
            _renderScanResults();
            results.classList.remove('hidden');
            saveBtn.classList.remove('hidden');
            _updateSaveBtn();
        }
    } catch(e) {
        loading.classList.add('hidden');
        status.style.color = '#ff6347';
        status.textContent = '✗ Erro: ' + e.message;
    }
 
    btn.disabled = false;
    btn.innerHTML = _scanBtnHtml();
}
 
function _scanBtnHtml() {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg> Executar Scanner`;
}
 
// ── Renderizar resultados ────────────────────────────────────────────────
 
function _renderScanResults() {
    const container = document.getElementById('dpScanResults');
    if (!_scanResults.length) {
        container.innerHTML = '';
        return;
    }
 
    const statusColors = {
        draft:      { color: '#8b949e', bg: 'rgba(139,148,158,0.12)' },
        active:     { color: '#39d353', bg: 'rgba(57,211,83,0.12)' },
    };
    const layerLabels = { raw: 'Raw', refined: 'Refined', insight: 'Insight' };
    const consLabels  = { analytical: 'Analytical', operational: 'Operational', ml_ai: 'ML/AI' };
    const classLabels = { public: 'Public', internal: 'Internal', restricted: 'Restricted' };
 
    container.innerHTML = `
        <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
                <label class="flex items-center gap-1.5 text-xs cursor-pointer text-fg-muted hover:text-fg-text transition">
                    <input type="checkbox" id="dpScanSelectAll" onchange="_toggleAllScan(this.checked)"
                           class="accent-emerald-500 w-3.5 h-3.5" ${_scanSelectedIdxs.size === _scanResults.length ? 'checked' : ''}>
                    Selecionar todos
                </label>
                <span class="text-[10px] text-fg-muted font-mono" id="dpScanSelCount">${_scanSelectedIdxs.size}/${_scanResults.length} selecionados</span>
            </div>
            <div class="flex items-center gap-2">
                <span class="text-[10px] text-fg-muted">Ordenar:</span>
                <button onclick="_sortScanResults('confidence')" class="text-[10px] text-fg-muted hover:text-emerald-400 transition">Confiança</button>
                <button onclick="_sortScanResults('domain')" class="text-[10px] text-fg-muted hover:text-emerald-400 transition">Domínio</button>
                <button onclick="_sortScanResults('name')" class="text-[10px] text-fg-muted hover:text-emerald-400 transition">Nome</button>
            </div>
        </div>
    ` + _scanResults.map((s, idx) => {
        const isSelected  = _scanSelectedIdxs.has(idx);
        const conf        = Math.round((s.confidence || 0) * 100);
        const confColor   = conf >= 70 ? '#39d353' : (conf >= 40 ? '#f0883e' : '#8b949e');
        const layer       = layerLabels[s.value_layer] || s.value_layer || 'refined';
        const cons        = consLabels[s.consumption_type] || s.consumption_type || 'analytical';
        const cls         = classLabels[s.classification] || s.classification || 'internal';
        const domain      = s.domain || 'N/D';
        const meta        = s._meta || {};
        const artCount    = (s.artifacts || []).length;
        const outCount    = (s.output_ports || []).length;
        const qrCount     = (s.quality_rules || []).length;
        const consumers   = (s.consumers || []).slice(0, 3).join(', ');
        const alreadyExists = meta.already_has_product;
 
        return `
        <div class="rounded-xl border px-5 py-4 transition-all mb-2 ${isSelected ? 'bg-emerald-500/5 border-emerald-500/30' : 'bg-fg-900 border-fg-border'}"
             id="scan-card-${idx}">
            <div class="flex items-start gap-3">
 
                <!-- Checkbox -->
                <div class="pt-1 flex-shrink-0">
                    <input type="checkbox" class="accent-emerald-500 w-4 h-4 cursor-pointer dp-scan-check"
                           data-idx="${idx}" ${isSelected ? 'checked' : ''}
                           onchange="_toggleScanItem(${idx}, this.checked)">
                </div>
 
                <!-- Content -->
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1.5 flex-wrap">
                        <span class="text-sm font-bold text-emerald-400 font-mono">${escapeHtml(s.display_name || s.name)}</span>
                        <span class="text-[9px] bg-fg-700 text-fg-muted px-1.5 py-0.5 rounded border border-fg-border font-mono">${escapeHtml(s.name)}</span>
                        ${domain !== 'N/D' ? `<span class="text-[9px] bg-fg-blue/10 text-fg-blue px-1.5 py-0.5 rounded-full">${escapeHtml(domain)}</span>` : ''}
                        <span class="text-[9px] bg-purple-500/10 text-purple-400 px-1.5 py-0.5 rounded-full">${layer}</span>
                        <span class="text-[9px] bg-fg-700 text-fg-muted px-1.5 py-0.5 rounded-full">${cons}</span>
                        <span class="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded-full" style="color:${confColor};background:${confColor}15;border:1px solid ${confColor}30">${conf}% conf.</span>
                        ${alreadyExists ? '<span class="text-[9px] bg-fg-accent/10 text-fg-accent border border-fg-accent/20 px-1.5 py-0.5 rounded-full">⚠ já existe</span>' : ''}
                    </div>
 
                    <!-- Source table -->
                    <div class="text-[10px] text-fg-muted font-mono mb-1.5">
                        Tabela: <span class="text-fg-green font-bold">${escapeHtml(s.source_table || '—')}</span>
                        ${meta.row_count ? ` · ${meta.row_count.toLocaleString('pt-BR')} registros` : ''}
                        ${meta.col_count ? ` · ${meta.col_count} colunas` : ''}
                    </div>
 
                    ${s.purpose ? `<p class="text-xs text-fg-text leading-relaxed mb-2">${escapeHtml(s.purpose)}</p>` : ''}
 
                    ${s.rationale ? `<p class="text-[10px] text-fg-muted italic mb-2">💡 ${escapeHtml(s.rationale)}</p>` : ''}
 
                    <div class="flex flex-wrap gap-3 text-[10px] text-fg-muted">
                        ${s.owner_team ? `<span>Owner: <strong class="text-fg-text">${escapeHtml(s.owner_team)}</strong></span>` : ''}
                        <span>${artCount} artefato(s)</span>
                        <span>${outCount} output port(s)</span>
                        <span>${qrCount} regra(s) qualidade</span>
                        ${s.sla_freshness ? `<span class="text-fg-green">SLA: ${escapeHtml(s.sla_freshness)}</span>` : ''}
                        ${consumers ? `<span>Consumidores: ${escapeHtml(consumers)}</span>` : ''}
                    </div>
 
                    <!-- Expandable details -->
                    <details class="mt-2">
                        <summary class="text-[10px] text-fg-muted cursor-pointer hover:text-emerald-400 transition">
                            Ver detalhes ODPS completos
                        </summary>
                        <div class="mt-2 bg-fg-800 rounded-lg p-3 border border-fg-border text-[10px] font-mono text-fg-muted overflow-x-auto">
                            <pre style="white-space:pre-wrap;word-break:break-all;">${escapeHtml(JSON.stringify(s, null, 2))}</pre>
                        </div>
                    </details>
                </div>
 
                <!-- Edit button -->
                <div class="flex-shrink-0 pt-1">
                    <button onclick="_editScanItem(${idx})"
                        class="text-[10px] text-fg-muted hover:text-emerald-400 border border-fg-border px-2 py-1 rounded transition"
                        title="Editar antes de salvar">
                        Editar
                    </button>
                </div>
            </div>
        </div>`;
    }).join('');
}
 
// ── Seleção ──────────────────────────────────────────────────────────────
 
function _toggleScanItem(idx, checked) {
    if (checked) _scanSelectedIdxs.add(idx);
    else _scanSelectedIdxs.delete(idx);
 
    const card = document.getElementById(`scan-card-${idx}`);
    if (card) {
        card.className = checked
            ? 'rounded-xl border px-5 py-4 transition-all mb-2 bg-emerald-500/5 border-emerald-500/30'
            : 'rounded-xl border px-5 py-4 transition-all mb-2 bg-fg-900 border-fg-border';
    }
 
    _updateSaveBtn();
    _updateSelCount();
}
 
function _toggleAllScan(checked) {
    _scanSelectedIdxs.clear();
    if (checked) _scanResults.forEach((_, i) => _scanSelectedIdxs.add(i));
    document.querySelectorAll('.dp-scan-check').forEach(cb => cb.checked = checked);
    _renderScanResults(); // re-render with correct styles
    _updateSaveBtn();
}
 
function _updateSelCount() {
    const el = document.getElementById('dpScanSelCount');
    if (el) el.textContent = `${_scanSelectedIdxs.size}/${_scanResults.length} selecionados`;
    const allCb = document.getElementById('dpScanSelectAll');
    if (allCb) allCb.checked = _scanSelectedIdxs.size === _scanResults.length;
}
 
function _updateSaveBtn() {
    const btn = document.getElementById('btnSaveScanResults');
    if (!btn) return;
    const n = _scanSelectedIdxs.size;
    btn.disabled = n === 0;
    btn.textContent = n > 0 ? `Salvar ${n} Produto(s) Selecionado(s)` : 'Selecione ao menos 1 produto';
}
 
// ── Ordenação ────────────────────────────────────────────────────────────
 
function _sortScanResults(by) {
    if (by === 'confidence') {
        _scanResults.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    } else if (by === 'domain') {
        _scanResults.sort((a, b) => (a.domain || '').localeCompare(b.domain || ''));
    } else {
        _scanResults.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    }
    // Reset selection indexes (keep same items selected by name)
    const selectedNames = new Set(
        [..._scanSelectedIdxs].map(i => _scanResults[i]?.name).filter(Boolean)
    );
    _scanSelectedIdxs.clear();
    _scanResults.forEach((s, i) => {
        if (selectedNames.has(s.name)) _scanSelectedIdxs.add(i);
    });
    _renderScanResults();
    _updateSaveBtn();
}
 
// ── Editar item antes de salvar ──────────────────────────────────────────
 
function _editScanItem(idx) {
    const s = _scanResults[idx];
    if (!s) return;
 
    // Preencher o modal de edição padrão com os dados do scanner
    closeDPScanner();
    openDPModal(); // abre vazio
 
    // Delay para o DOM renderizar
    setTimeout(() => {
        document.getElementById('dpEditId').value = '';
        document.getElementById('dpName').value = s.name || '';
        document.getElementById('dpDisplayName').value = s.display_name || '';
        document.getElementById('dpVersion').value = s.version || '1.0.0';
        document.getElementById('dpStatus').value = s.status || 'draft';
        document.getElementById('dpDomain').value = s.domain || '';
        document.getElementById('dpPurpose').value = s.purpose || '';
        document.getElementById('dpBusinessValue').value = s.business_value || '';
        document.getElementById('dpConsumers').value = (s.consumers || []).join(', ');
        document.getElementById('dpOwnerTeam').value = s.owner_team || '';
        document.getElementById('dpOwnerEmail').value = s.owner_email || '';
        document.getElementById('dpOwnerRole').value = s.owner_role || 'data product owner';
        document.getElementById('dpClassification').value = s.classification || 'internal';
        document.getElementById('dpCompliance').value = (s.compliance || []).join(', ');
        document.getElementById('dpValueLayer').value = s.value_layer || 'refined';
        document.getElementById('dpConsumptionType').value = s.consumption_type || 'analytical';
        document.getElementById('dpSLAFreshness').value = s.sla_freshness || '';
        document.getElementById('dpSLAAvailability').value = s.sla_availability || '';
        document.getElementById('dpArtifacts').value = JSON.stringify(s.artifacts || [], null, 2);
        document.getElementById('dpInputPorts').value = JSON.stringify(s.input_ports || [], null, 2);
        document.getElementById('dpOutputPorts').value = JSON.stringify(s.output_ports || [], null, 2);
        document.getElementById('dpQualityRules').value = JSON.stringify(s.quality_rules || [], null, 2);
        document.getElementById('dpModalTitle').textContent = 'Produto de Dados (do Scanner)';
    }, 200);
}
 
// ── Salvar selecionados em batch ─────────────────────────────────────────
 
async function saveScanResults() {
    const btn    = document.getElementById('btnSaveScanResults');
    const status = document.getElementById('dpScanStatus');
    const selected = [..._scanSelectedIdxs].map(i => _scanResults[i]).filter(Boolean);
 
    if (!selected.length) {
        status.style.color = '#f0883e';
        status.textContent = 'Selecione ao menos um produto.';
        return;
    }
 
    btn.disabled = true;
    btn.textContent = 'Salvando…';
    status.style.color = '#8b949e';
    status.textContent = `Salvando ${selected.length} produto(s)…`;
 
    try {
        const res = await fetch('/api/data-products/scan/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ suggestions: selected }),
        });
        const data = await res.json();
 
        if (data.error) {
            status.style.color = '#ff6347';
            status.textContent = '✗ ' + data.error;
        } else {
            const errMsg = data.errors.length ? ` · ${data.errors.length} erro(s): ${data.errors.slice(0, 3).join('; ')}` : '';
            status.style.color = '#39d353';
            status.textContent = `✓ ${data.total} produto(s) criado(s)${errMsg}`;
 
            // Recarregar lista
            await loadDataProducts();
 
            // Fechar modal após 1.5s
            setTimeout(() => closeDPScanner(), 1800);
        }
    } catch(e) {
        status.style.color = '#ff6347';
        status.textContent = '✗ Erro: ' + e.message;
    }
 
    btn.disabled = false;
    _updateSaveBtn();
}
