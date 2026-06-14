"""
Fale com Seus Dados — Visualization Service

- Explorar: PyGWalker (drag-and-drop) + AI Ask bar (OpenAI → Chart.js inline)
- Gráfico: Chart.js interativo com seletores de campo X, Y, agregação e tipo
- Galeria: Chart.js com config salva
"""

import json
import pandas as pd
import pygwalker as pyg
from langchain_openai import ChatOpenAI
from app.core.config import settings
from app.services.llm_factory import make_chat_llm

# ---------------------------------------------------------------------------
# LLM chart recommendation (used by Chart page)
# ---------------------------------------------------------------------------

_SPEC_PROMPT = """You are a data visualization expert. Analyze the data below and recommend the best chart.

## Data
Columns: {columns}
Types: {dtypes}
Sample (first 5 rows):
{sample}

## Rules
1. Identify which columns are metrics (numeric) and which are dimensions (categorical/text)
2. Choose the most appropriate chart type:
   - 1 dimension + 1 metric -> bar
   - temporal dimension + metric -> line
   - 2 metrics -> scatter
   - only metrics -> bar with first column as axis
3. Return ONLY valid JSON, no markdown, no explanation

## Output format (pure JSON)
{{
  "chart_type": "bar|line|scatter|area|pie|doughnut",
  "x_field": "column_name_for_x_axis",
  "y_field": "column_name_for_y_axis",
  "agg": "sum|mean|count|none"
}}
"""


# ---------------------------------------------------------------------------
# AI Visualization Ask (Explore page — powered by OpenAI)
# ---------------------------------------------------------------------------

_VIZ_ASK_PROMPT = """You are a data visualization expert. The user wants to create a visualization from their dataset.

## Dataset
Columns and types:
{columns_info}

Sample values (first 3 rows):
{sample}

Row count: {row_count}

## User request
"{prompt}"

## Rules
1. Choose the BEST chart type for the user's request.
2. Pick the most appropriate columns for X axis, Y axis, and optionally Color grouping.
3. Choose the right aggregation when grouping makes sense.
4. If the user asks for something vague, pick what's most insightful.
5. Write a brief explanation (1-2 sentences, in Portuguese do Brasil) of what the chart shows.
6. Return ONLY valid JSON — no markdown fences, no extra text.

## Valid chart types
bar, line, scatter, area, pie, doughnut, radar, polarArea

## Valid aggregations
sum, mean, count, min, max, none

## Output format (pure JSON)
{{
  "chart_type": "bar",
  "x": "column_name",
  "y": "column_name",
  "color": "",
  "agg": "sum",
  "explanation": "Explicação breve em português"
}}
"""


def ask_visualization_ai(data: dict, prompt: str) -> dict:
    """Use OpenAI to interpret a natural-language visualization request.
    Returns {chart_type, x, y, color, agg, explanation} or {error}."""
    if not (settings.oss120b_url or settings.azure_openai_api_key or settings.openai_api_key):
        return {"error": "Nenhum LLM configurado."}
   
    rows = data.get("rows", [])
    columns = data.get("columns", list(rows[0].keys()) if rows else [])
    if not rows:
        return {"error": "Dataset vazio."}

    df = pd.DataFrame(rows)

    col_info = []
    for col in columns:
        dtype = "numérico" if pd.api.types.is_numeric_dtype(df[col]) else "texto"
        nunique = df[col].nunique()
        sample_vals = df[col].dropna().head(3).tolist()
        col_info.append(f"- {col} ({dtype}, {nunique} valores únicos, ex: {sample_vals})")

    full_prompt = _VIZ_ASK_PROMPT.format(
        columns_info="\n".join(col_info),
        sample=df.head(3).to_string(index=False),
        row_count=len(df),
        prompt=prompt,
    )

    try:
       # llm = ChatOpenAI(model=settings.openai_model,api_key=settings.openai_api_key,temperature=0,)
        llm = make_chat_llm(temperature=0, role="viz_ask")
        response = llm.invoke(full_prompt)
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()
        result = json.loads(content)

        # Validate fields exist
        valid_cols = set(columns)
        if result.get("x") not in valid_cols:
            result["x"] = columns[0]
        if result.get("y") not in valid_cols:
            numeric = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]
            result["y"] = numeric[0] if numeric else columns[-1]
        if result.get("color") and result["color"] not in valid_cols:
            result["color"] = ""

        return result
    except json.JSONDecodeError:
        return {"error": "Resposta inválida da IA. Tente reformular."}
    except Exception as e:
        return {"error": f"Erro ao consultar IA: {str(e)[:120]}"}


def _ask_llm_for_chart_config(df: pd.DataFrame) -> dict | None:
    if not (settings.oss120b_url or settings.azure_openai_api_key or settings.openai_api_key):
        return None
    try:
        # llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0)
        llm = make_chat_llm(temperature=0, role="viz_ask")
        dtypes_info = {col: str(dtype) for col, dtype in df.dtypes.items()}
        sample = df.head(5).to_string(index=False)
        prompt = _SPEC_PROMPT.format(columns=list(df.columns), dtypes=json.dumps(dtypes_info), sample=sample)
        response = llm.invoke(prompt)
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()
        return json.loads(content)
    except Exception:
        return None


def _fallback_chart_config(df: pd.DataFrame, chart_type: str = "bar") -> dict:
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    non_numeric = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    return {
        "chart_type": chart_type,
        "x_field": non_numeric[0] if non_numeric else df.columns[0],
        "y_field": numeric[0] if numeric else df.columns[-1],
        "agg": "sum",
    }


def get_chart_options_for_data(data: dict) -> dict:
    df = _data_to_df(data)
    if df is None:
        return {"options": []}
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    non_numeric = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    n_rows = len(df)
    options = [
        {"type": "auto", "label": "Auto (LLM)", "icon": "*", "suitable": True},
        {"type": "bar", "label": "Barras", "icon": "||", "suitable": True},
        {"type": "line", "label": "Linhas", "icon": "/\\", "suitable": len(numeric) > 0 and n_rows > 2},
        {"type": "scatter", "label": "Dispersao", "icon": ".:", "suitable": len(numeric) >= 2},
        {"type": "area", "label": "Area", "icon": "~", "suitable": len(numeric) > 0 and n_rows > 2},
        {"type": "pie", "label": "Pizza", "icon": "O", "suitable": len(numeric) > 0 and n_rows <= 20},
        {"type": "doughnut", "label": "Rosca", "icon": "()", "suitable": len(numeric) > 0 and n_rows <= 20},
        {"type": "radar", "label": "Radar", "icon": "<>", "suitable": len(numeric) >= 3 and n_rows <= 15},
        {"type": "polarArea", "label": "Polar", "icon": "+", "suitable": len(numeric) > 0 and n_rows <= 12},
    ]
    return {"options": options, "numeric_cols": numeric, "categorical_cols": non_numeric, "row_count": n_rows}


def _data_to_df(data: dict) -> pd.DataFrame | None:
    rows = data.get("rows", [])
    if not rows:
        return None
    df = pd.DataFrame(rows)
    return df if not df.empty else None


# ---------------------------------------------------------------------------
# Interactive Chart Page (standalone) — FIXED rebuild() function
# ---------------------------------------------------------------------------

def _render_interactive_chart_html(data: dict, initial_config: dict | None = None, sql_no_limit: str = "") -> str:
    df = _data_to_df(data)
    if df is None:
        return _empty_html()

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    all_cols = list(df.columns)

    if not initial_config:
        initial_config = _fallback_chart_config(df)
    if initial_config.get("x_field") not in all_cols:
        initial_config["x_field"] = all_cols[0]
    if initial_config.get("y_field") not in all_cols:
        initial_config["y_field"] = numeric_cols[0] if numeric_cols else all_cols[-1]

    data_json = json.dumps(data.get("rows", []), default=str, ensure_ascii=False)
    sql_no_limit_json = json.dumps(sql_no_limit or "")
    cols_json = json.dumps(all_cols)
    num_cols_json = json.dumps(numeric_cols)
    config_json = json.dumps(initial_config)
    row_count = len(data.get("rows", []))
    x_options = "".join(f'<option value="{c}">{c}</option>' for c in all_cols)
    y_options = "".join(f'<option value="{c}">{c}</option>' for c in all_cols)

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Fale com Seus Dados — Gráfico</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Space+Grotesk:wght@400;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#c9d1d9;font-family:'Space Grotesk',sans-serif;height:100vh;display:flex;flex-direction:column}}
.qi-hdr{{background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}}
.qi-logo{{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600}}
.qi-logo span{{color:#ff6347}}
.qi-bar{{background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;flex-shrink:0}}
.qi-g{{display:flex;align-items:center;gap:6px}}
.qi-lbl{{font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:.05em;font-family:'JetBrains Mono',monospace;white-space:nowrap}}
.qi-sel{{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:5px 10px;border-radius:6px;font-size:12px;font-family:'Space Grotesk',sans-serif;cursor:pointer}}
.qi-sel:focus{{border-color:#ff6347;outline:none}}
.qi-sel option{{background:#0d1117}}
.qi-wrap{{flex:1;padding:20px;display:flex;align-items:center;justify-content:center;min-height:0;overflow:hidden}}
.qi-inner{{width:100%;max-width:1400px;height:100%;position:relative}}
.qi-nfo{{font-size:11px;color:#8b949e;font-family:'JetBrains Mono',monospace}}
.qi-status{{font-size:10px;color:#58a6ff;padding:4px 12px;font-family:'JetBrains Mono',monospace}}
</style>
</head><body>
<div class="qi-hdr">
  <div class="qi-logo">FALE COM <span>SEUS DADOS</span> — Gráfico Interativo</div>
  <div class="qi-nfo" id="rowInfo">{row_count} registros · {len(all_cols)} colunas</div>
</div>
<div class="qi-bar">
  <div class="qi-g"><span class="qi-lbl">Tipo</span>
    <select id="ctrlType" class="qi-sel" onchange="rebuild()">
      <option value="bar">Barras</option>
      <option value="line">Linhas</option>
      <option value="scatter">Dispersão</option>
      <option value="area">Área</option>
      <option value="pie">Pizza</option>
      <option value="doughnut">Rosca</option>
      <option value="radar">Radar</option>
      <option value="polarArea">Polar</option>
    </select>
  </div>
  <div class="qi-g"><span class="qi-lbl">Eixo X</span>
    <select id="ctrlX" class="qi-sel" onchange="rebuild()">{x_options}</select>
  </div>
  <div class="qi-g"><span class="qi-lbl">Eixo Y</span>
    <select id="ctrlY" class="qi-sel" onchange="rebuild()">{y_options}</select>
  </div>
  <div class="qi-g"><span class="qi-lbl">Agregação</span>
    <select id="ctrlAgg" class="qi-sel" onchange="rebuild()">
      <option value="sum">Soma</option>
      <option value="mean">Média</option>
      <option value="count">Contagem</option>
      <option value="none">Nenhuma</option>
    </select>
  </div>
  <div class="qi-g"><span class="qi-lbl">Limite</span>
    <select id="ctrlLimit" class="qi-sel" onchange="rebuild()">
      <option value="20" selected>20</option>
      <option value="50">50</option>
      <option value="100">100</option>
      <option value="500">500</option>
      <option value="1000">1.000</option>
      <option value="0">Todos</option>
    </select>
  </div>
  <div class="qi-g"><span class="qi-lbl">Ordem</span>
    <select id="ctrlSort" class="qi-sel" onchange="rebuild()">
      <option value="asc" selected>Ascendente</option>
      <option value="desc">Descendente</option>
    </select>
  </div>
  <span class="qi-status" id="statusBar"></span>
</div>
<div class="qi-wrap"><div class="qi-inner"><canvas id="mainChart"></canvas></div></div>

<script>
const RAW          = {data_json};
const COLS         = {cols_json};
const NUM_COLS     = new Set({num_cols_json});
const SQL_NO_LIMIT = {sql_no_limit_json};
const INI          = {config_json};

const PAL = [
  'rgba(255,99,71,.75)','rgba(88,166,255,.75)','rgba(57,211,83,.75)',
  'rgba(240,136,62,.75)','rgba(163,113,247,.75)','rgba(63,185,80,.75)',
  'rgba(210,168,255,.75)','rgba(121,192,255,.75)','rgba(255,166,87,.75)','rgba(255,123,114,.75)'
];

Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#21262d';
Chart.defaults.font.family = "'Space Grotesk', sans-serif";

let chart = null;
const _dataCache = Object.create(null);

// Aggregate rows into {{l: labels[], v: values[]}}
function aggRows(rows, xF, yF, fn, lim, sort) {{
  if (fn === 'none') {{
    let r = rows.map(d => ({{ x: String(d[xF] ?? ''), y: Number(d[yF]) || 0 }}));
    r.sort((a, b) => {{
      const c = a.x.localeCompare(b.x, undefined, {{ numeric: true, sensitivity: 'base' }});
      return sort === 'desc' ? -c : c;
    }});
    if (lim > 0) r = r.slice(0, lim);
    return {{ l: r.map(d => d.x), v: r.map(d => d.y) }};
  }}
  const g = {{}};
  rows.forEach(d => {{
    const k = String(d[xF] ?? '');
    if (!g[k]) g[k] = [];
    const n = Number(d[yF]);
    if (!isNaN(n)) g[k].push(n);
  }});
  let e = Object.entries(g).map(([k, vs]) => {{
    let v = 0;
    if (fn === 'sum')        v = vs.reduce((a, b) => a + b, 0);
    else if (fn === 'mean')  v = vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : 0;
    else if (fn === 'count') v = vs.length;
    return {{ l: k, v }};
  }});
  e.sort((a, b) => {{
    const c = a.l.localeCompare(b.l, undefined, {{ numeric: true, sensitivity: 'base' }});
    return sort === 'desc' ? -c : c;
  }});
  if (lim > 0) e = e.slice(0, lim);
  return {{ l: e.map(d => d.l), v: e.map(d => d.v) }};
}}

async function rebuild() {{
  // Read controls
  const tp   = document.getElementById('ctrlType').value;
  const xF   = document.getElementById('ctrlX').value;
  const yF   = document.getElementById('ctrlY').value;
  const ag   = document.getElementById('ctrlAgg').value;
  const lm   = parseInt(document.getElementById('ctrlLimit').value, 10);  // 0 = Todos
  const sort = document.getElementById('ctrlSort').value;

  const status  = document.getElementById('statusBar');
  const rowInfo = document.getElementById('rowInfo');

  // Resolve dataset — re-execute query with selected LIMIT
  let rows = RAW;
  let _serverFetched = false;
 
  if (SQL_NO_LIMIT) {{
    const cacheKey = String(lm);
    if (_dataCache[cacheKey]) {{
      rows = _dataCache[cacheKey];
      _serverFetched = true;
    }} else {{
      const sqlBase = SQL_NO_LIMIT.trim().replace(/;$/, '');
      const sqlToRun = lm > 0 ? sqlBase + ' LIMIT ' + lm : sqlBase;
      status.textContent = lm === 0
        ? 'Carregando todos os registros…'
        : 'Reexecutando query com LIMIT ' + lm + '…';
      try {{
        const res = await fetch('/api/query/full-data', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ sql: sqlToRun }}),
        }});
        if (res.ok) {{
          const rd = await res.json();
          if (rd.rows && rd.rows.length) {{
            _dataCache[cacheKey] = rd.rows;
            rows = rd.rows;
            _serverFetched = true;
          }}
        }}
      }} catch (err) {{
        console.error('full-data fetch error', err);
      }}
      status.textContent = '';
    }}
  }}
           
  rowInfo.textContent = rows.length.toLocaleString('pt-BR') + ' registros · {len(all_cols)} colunas';

  // Aggregate
  // When data came from server with LIMIT, skip client-side slice in aggRows
  const aggLim = _serverFetched ? 0 : lm;
  const d = aggRows(rows, xF, yF, ag, aggLim, sort);

  // Destroy previous chart
  if (chart) {{ chart.destroy(); chart = null; }}

  // Map type
  const typeMap = {{
    bar: 'bar', line: 'line', scatter: 'scatter',
    area: 'line', pie: 'pie', doughnut: 'doughnut',
    radar: 'radar', polarArea: 'polarArea',
  }};
  const ct   = typeMap[tp] || 'bar';
  const circ = ['pie', 'doughnut', 'polarArea'].includes(tp);
  const rad  = tp === 'radar';
  const fill = tp === 'area';

  // Build dataset
  let ds;
  if (ct === 'scatter') {{
    ds = {{
      label: yF,
      data: d.l.map((x, i) => ({{ x, y: d.v[i] }})),
      backgroundColor: 'rgba(255,99,71,.7)',
      borderColor: '#ff6347',
      pointRadius: 5,
      pointHoverRadius: 7,
    }};
  }} else if (circ) {{
    ds = {{
      label: yF,
      data: d.v,
      backgroundColor: d.l.map((_, i) => PAL[i % PAL.length]),
      borderColor: '#0d1117',
      borderWidth: 2,
    }};
  }} else if (rad) {{
    ds = {{
      label: yF,
      data: d.v,
      backgroundColor: 'rgba(255,99,71,.2)',
      borderColor: '#ff6347',
      borderWidth: 2,
      pointBackgroundColor: '#ff6347',
    }};
  }} else {{
    ds = {{
      label: yF,
      data: d.v,
      backgroundColor: 'rgba(255,99,71,.35)',
      borderColor: '#ff6347',
      borderWidth: 2,
      fill: fill,
      tension: 0.3,
      borderRadius: ct === 'bar' ? 4 : 0,
    }};
  }}

  // Build scales
  const sc = {{}};
  if (!circ && !rad) {{
    sc.x = {{
      ticks: {{ color: '#8b949e', maxRotation: 45, font: {{ size: 11 }} }},
      grid:  {{ color: '#21262d' }},
      title: {{ display: true, text: xF, color: '#c9d1d9', font: {{ size: 12, weight: 600 }} }},
    }};
    sc.y = {{
      ticks: {{ color: '#8b949e', font: {{ size: 11 }} }},
      grid:  {{ color: '#21262d' }},
      title: {{
        display: true,
        text: yF + (ag !== 'none' ? ' (' + ag + ')' : ''),
        color: '#c9d1d9',
        font: {{ size: 12, weight: 600 }},
      }},
      beginAtZero: true,
    }};
  }}

  // Render
  chart = new Chart(document.getElementById('mainChart'), {{
    type: ct,
    data: {{ labels: d.l, datasets: [ds] }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: true, labels: {{ color: '#c9d1d9', font: {{ size: 12 }} }} }},
        tooltip: {{
          backgroundColor: '#161b22',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#ff6347',
          bodyColor: '#c9d1d9',
          padding: 10,
          cornerRadius: 8,
        }},
      }},
      scales: sc,
      animation: {{ duration: 400, easing: 'easeOutQuart' }},
    }},
  }});
}}

// Initialise controls from LLM recommendation, then render
document.getElementById('ctrlType').value = INI.chart_type || 'bar';
document.getElementById('ctrlX').value    = INI.x_field   || COLS[0];
document.getElementById('ctrlY').value    = INI.y_field   || (COLS.length > 1 ? COLS[1] : COLS[0]);
document.getElementById('ctrlAgg').value  = INI.agg       || 'sum';
rebuild();
</script>
</body></html>"""


# ---------------------------------------------------------------------------
# Explore page (PyGWalker + AI Ask bar powered by OpenAI)
# ---------------------------------------------------------------------------

def generate_explore_html(data: dict) -> str:
    df = _data_to_df(data)
    if df is None:
        return _empty_html()

    try:
        walker_html = pyg.to_html(df, appearance="dark", default_tab="data")
    except Exception:
        walker_html = pyg.to_html(df, appearance="dark")

    data_json = json.dumps(data)
    row_count = len(data.get("rows", []))
    col_count = len(df.columns)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fale com Seus Dados — Explorar</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Space+Grotesk:wght@400;600&display=swap" rel="stylesheet">
    <style>
        body{{margin:0;padding:0;background:#0d1117;color:#c9d1d9;font-family:'Space Grotesk',sans-serif}}
        .qi-hdr{{background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;align-items:center;justify-content:space-between}}
        .qi-logo{{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600}}
        .qi-logo span{{color:#ff6347}}
        .qi-tb{{background:#161b22;border-bottom:1px solid #30363d;padding:8px 20px;display:flex;align-items:center;justify-content:flex-end;gap:8px}}
        .qi-btn{{padding:5px 14px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;border:1px solid;transition:all .15s;font-family:'Space Grotesk',sans-serif}}
        .qi-btn-s{{background:rgba(255,99,71,.15);color:#ff6347;border-color:rgba(255,99,71,.3)}}
        .qi-btn-s:hover{{background:rgba(255,99,71,.25)}}
        .qi-btn-a{{background:rgba(88,166,255,.15);color:#58a6ff;border-color:rgba(88,166,255,.3)}}
        .qi-btn-a:hover{{background:rgba(88,166,255,.25)}}
        .qi-btn-c{{background:#ff6347;color:#fff;border-color:#ff6347}}
        .qi-btn-c:hover{{background:#ff4500}}
        .qi-btn-x{{background:#21262d;color:#8b949e;border-color:#30363d}}
        .qi-btn-x:hover{{color:#c9d1d9}}
        .qi-m{{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center}}
        .qi-mc{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;width:100%;max-width:400px}}
        .qi-mc h3{{font-size:13px;font-weight:700;color:#ff6347;text-transform:uppercase;letter-spacing:.05em;margin:0 0 16px 0;font-family:'JetBrains Mono',monospace}}
        .qi-f{{margin-bottom:12px}}
        .qi-f label{{display:block;font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}}
        .qi-f input{{width:100%;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px 12px;border-radius:8px;font-size:13px;box-sizing:border-box}}
        .qi-f input:focus{{border-color:#ff6347;outline:none}}
        .qi-ma{{display:flex;gap:8px}}
        .qi-attach-drop{{border:2px dashed #30363d;border-radius:10px;padding:24px;text-align:center;cursor:pointer;transition:all .2s}}
        .qi-attach-drop:hover,.qi-attach-drop.active{{border-color:#58a6ff;background:rgba(88,166,255,.04)}}
        .qi-attach-status{{margin-top:10px;font-size:11px;min-height:18px}}
        .qi-ask-bar{{background:#161b22;border-bottom:1px solid #30363d;padding:10px 20px;display:flex;align-items:center;gap:10px}}
        .qi-ask-input{{flex:1;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:9px 14px;border-radius:8px;font-size:13px;font-family:'Space Grotesk',sans-serif;outline:none;transition:border-color .2s}}
        .qi-ask-input:focus{{border-color:#a371f7}}
        .qi-ask-input::placeholder{{color:#484f58}}
        .qi-ask-btn{{background:linear-gradient(135deg,#a371f7,#8b5cf6);color:#fff;border:none;padding:9px 20px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;font-family:'Space Grotesk',sans-serif;display:flex;align-items:center;gap:6px;transition:opacity .15s;white-space:nowrap}}
        .qi-ask-btn:hover{{opacity:.9}}
        .qi-ask-btn:disabled{{opacity:.5;cursor:wait}}
        .qi-ai-panel{{background:#0d1117;border-bottom:1px solid #30363d;overflow:hidden;transition:max-height .35s ease,padding .35s ease;max-height:0;padding:0 20px}}
        .qi-ai-panel.open{{max-height:520px;padding:16px 20px}}
        .qi-ai-chart-wrap{{height:300px;position:relative;margin-bottom:10px}}
        .qi-ai-explain{{font-size:12px;color:#c9d1d9;line-height:1.6;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:8px}}
        .qi-ai-meta{{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-size:10px;color:#8b949e;font-family:'JetBrains Mono',monospace}}
        .qi-ai-close{{position:absolute;top:8px;right:8px;background:none;border:none;color:#8b949e;cursor:pointer;font-size:16px;line-height:1;padding:4px}}
        .qi-ai-close:hover{{color:#ff6347}}
        @keyframes spin{{from{{transform:rotate(0deg)}}to{{transform:rotate(360deg)}}}}
    </style>
</head>
<body>
    <div class="qi-hdr">
        <div class="qi-logo">FALE COM <span>SEUS DADOS</span> — Exploração de Dados</div>
        <div style="font-size:11px;color:#8b949e">PyGWalker · {row_count} registros · {col_count} colunas</div>
    </div>

    <!-- AI Ask Bar -->
    <div class="qi-ask-bar">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#a371f7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <input type="text" id="aiAskInput" class="qi-ask-input"
               placeholder="Que visualização deseja gerar a partir do dataset?"
               onkeydown="if(event.key==='Enter')askAI()">
        <button id="aiAskBtn" class="qi-ask-btn" onclick="askAI()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            Ask
        </button>
    </div>

    <!-- AI Result Panel -->
    <div id="aiPanel" class="qi-ai-panel" style="position:relative">
        <button class="qi-ai-close" onclick="closeAiPanel()" title="Fechar">&#x2715;</button>
        <div class="qi-ai-chart-wrap"><canvas id="aiChart"></canvas></div>
        <div id="aiExplain" class="qi-ai-explain"></div>
        <div id="aiMeta" class="qi-ai-meta"></div>
    </div>

    <!-- Toolbar -->
    <div class="qi-tb">
        <button onclick="openAttachModal()" class="qi-btn qi-btn-a" title="Anexar arquivo Excel/CSV">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>Anexar Arquivo
        </button>
        <button onclick="saveToGallery()" class="qi-btn qi-btn-s">Salvar na Galeria</button>
    </div>

    <!-- Attach Modal -->
    <div id="attachModal" class="qi-m" style="display:none">
        <div class="qi-mc" style="max-width:460px">
            <h3 style="color:#58a6ff">Anexar Arquivo</h3>
            <p style="font-size:10px;color:#8b949e;margin-bottom:12px">Carregue <strong>.xlsx</strong> ou <strong>.csv</strong></p>
            <div class="qi-f"><label>Modo</label>
                <select id="attachMode" style="width:100%;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:8px 12px;border-radius:8px;font-size:12px">
                    <option value="replace">Substituir dados atuais</option><option value="append">Adicionar (merge)</option>
                </select>
            </div>
            <div id="attachDropZone" class="qi-attach-drop" onclick="document.getElementById('attachFileInput').click()"
                 ondragover="event.preventDefault();this.classList.add('active')" ondragleave="this.classList.remove('active')" ondrop="handleAttachDrop(event)">
                <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#58a6ff" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                <div style="font-size:12px;color:#c9d1d9;margin-top:8px">Arraste ou clique</div>
                <div style="font-size:10px;color:#8b949e;margin-top:4px">.xlsx &middot; .csv</div>
                <input type="file" id="attachFileInput" accept=".xlsx,.xls,.csv" style="display:none" onchange="handleAttachFile(this.files[0])">
            </div>
            <div id="attachStatus" class="qi-attach-status"></div>
            <div class="qi-ma" style="margin-top:12px"><button onclick="closeAttachModal()" class="qi-btn qi-btn-x" style="flex:1">Cancelar</button></div>
        </div>
    </div>

    <!-- Save Modal -->
    <div id="saveModal" class="qi-m" style="display:none">
        <div class="qi-mc"><h3>Salvar na Galeria</h3>
            <div class="qi-f"><label>Título</label><input type="text" id="saveTitle" placeholder="Nome da análise"></div>
            <div class="qi-f"><label>Descrição</label><input type="text" id="saveDesc" placeholder="Descrição opcional"></div>
            <div class="qi-ma"><button onclick="confirmSave()" class="qi-btn qi-btn-c">Salvar</button><button onclick="closeSaveModal()" class="qi-btn qi-btn-x">Cancelar</button></div>
            <div id="saveStatus" style="margin-top:8px;font-size:11px"></div>
        </div>
    </div>

    {walker_html}

    <script>
        const _qd={data_json};
        const PAL=['rgba(255,99,71,.7)','rgba(88,166,255,.7)','rgba(57,211,83,.7)','rgba(240,136,62,.7)','rgba(163,113,247,.7)','rgba(63,185,80,.7)','rgba(210,168,255,.7)','rgba(121,192,255,.7)','rgba(255,166,87,.7)','rgba(255,123,114,.7)'];
        Chart.defaults.color='#8b949e';Chart.defaults.borderColor='#21262d';Chart.defaults.font.family="'Space Grotesk',sans-serif";
        let _aiChart=null;

        // ── AI Ask (OpenAI) ─────────────────────────────────────
        async function askAI(){{
            const input=document.getElementById('aiAskInput');
            const btn=document.getElementById('aiAskBtn');
            const prompt=input.value.trim();
            if(!prompt){{input.focus();return}}
            btn.disabled=true;
            btn.innerHTML='<span style="animation:spin 1s linear infinite;display:inline-block">&#x27F3;</span> Pensando…';
            try{{
                const res=await fetch('/api/explore/ask',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{prompt:prompt,json_data:_qd}})}});
                const r=await res.json();
                if(r.error){{alert(r.error);resetAskBtn();return}}
                renderAiChart(r);
                document.getElementById('aiPanel').classList.add('open');
            }}catch(e){{alert('Erro: '+e.message)}}
            resetAskBtn();
        }}
        function resetAskBtn(){{const b=document.getElementById('aiAskBtn');b.disabled=false;b.innerHTML='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Ask'}}
        function closeAiPanel(){{document.getElementById('aiPanel').classList.remove('open')}}

        function renderAiChart(r){{
            if(_aiChart)_aiChart.destroy();
            const rows=_qd.rows||[];
            const xF=r.x,yF=r.y,colorF=r.color,ag=r.agg||'sum',ct=r.chart_type||'bar';
            let labels,datasets;
            function doAgg(vs,fn){{if(!vs.length)return 0;if(fn==='sum')return vs.reduce((a,b)=>a+b,0);if(fn==='mean')return vs.reduce((a,b)=>a+b,0)/vs.length;if(fn==='count')return vs.length;if(fn==='min')return Math.min(...vs);if(fn==='max')return Math.max(...vs);return vs.reduce((a,b)=>a+b,0)}}
            if(colorF&&colorF!==xF&&colorF!==yF){{
                const groups={{}};
                rows.forEach(d=>{{const g=String(d[colorF]??''),k=String(d[xF]??'');if(!groups[g])groups[g]={{}};if(!groups[g][k])groups[g][k]=[];const n=Number(d[yF]);if(!isNaN(n))groups[g][k].push(n)}});
                const allKeys=[...new Set(rows.map(d=>String(d[xF]??'')))].sort((a,b)=>a.localeCompare(b,undefined,{{numeric:true}}));
                labels=allKeys;
                datasets=Object.keys(groups).sort().map((g,i)=>({{label:g,data:allKeys.map(k=>doAgg(groups[g][k]||[],ag)),backgroundColor:PAL[i%PAL.length],borderColor:PAL[i%PAL.length].replace('.7','.9'),borderWidth:1.5,borderRadius:ct==='bar'?4:0,fill:ct==='area',tension:.3}}));
            }}else{{
                if(ag==='none'){{labels=rows.map(d=>String(d[xF]??''));const vals=rows.map(d=>Number(d[yF])||0);datasets=[{{label:yF,data:vals}}]}}
                else{{const g={{}};rows.forEach(d=>{{const k=String(d[xF]??'');if(!g[k])g[k]=[];const n=Number(d[yF]);if(!isNaN(n))g[k].push(n)}});const e=Object.entries(g).map(([k,vs])=>({{l:k,v:doAgg(vs,ag)}})).sort((a,b)=>a.l.localeCompare(b.l,undefined,{{numeric:true}}));labels=e.map(x=>x.l);datasets=[{{label:yF+(ag!=='none'?' ('+ag+')':''),data:e.map(x=>x.v)}}]}}
                const circ=['pie','doughnut','polarArea'].includes(ct);
                datasets[0].backgroundColor=circ?labels.map((_,i)=>PAL[i%PAL.length]):'rgba(163,113,247,.45)';
                datasets[0].borderColor=circ?'#0d1117':'#a371f7';
                datasets[0].borderWidth=circ?2:2;
                datasets[0].borderRadius=ct==='bar'?4:0;
                datasets[0].fill=ct==='area';
                datasets[0].tension=.3;
                if(ct==='scatter')datasets[0].pointRadius=4;
            }}
            const tm={{bar:'bar',line:'line',scatter:'scatter',area:'line',pie:'pie',doughnut:'doughnut',radar:'radar',polarArea:'polarArea'}};
            const cType=tm[ct]||'bar';const circ=['pie','doughnut','polarArea'].includes(ct);const rad=ct==='radar';
            const sc={{}};
            if(!circ&&!rad){{sc.x={{ticks:{{maxRotation:45,font:{{size:10}}}},title:{{display:true,text:xF,color:'#c9d1d9',font:{{size:11,weight:600}}}}}};sc.y={{title:{{display:true,text:yF+(ag!=='none'?' ('+ag+')':''),color:'#c9d1d9',font:{{size:11,weight:600}}}},beginAtZero:true}}}}
            _aiChart=new Chart(document.getElementById('aiChart'),{{type:cType,data:{{labels,datasets}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:datasets.length>1||circ,labels:{{color:'#c9d1d9',font:{{size:11}}}}}},tooltip:{{backgroundColor:'#161b22',borderColor:'#30363d',borderWidth:1,titleColor:'#a371f7',bodyColor:'#c9d1d9',padding:10,cornerRadius:8}}}},scales:sc,animation:{{duration:500,easing:'easeOutQuart'}}}}}});
            document.getElementById('aiExplain').innerHTML=r.explanation||'';
            const aL={{sum:'Soma',mean:'Média',count:'Contagem',min:'Mínimo',max:'Máximo',none:'Sem agregação'}};
            document.getElementById('aiMeta').innerHTML='<span>Tipo: <strong>'+ct+'</strong></span><span>X: <strong>'+xF+'</strong></span><span>Y: <strong>'+yF+'</strong></span>'+(colorF?'<span>Cor: <strong>'+colorF+'</strong></span>':'')+'<span>Agregação: <strong>'+(aL[ag]||ag)+'</strong></span>';
        }}

        // ── Attach ──────────────────────────────────────────────
        function openAttachModal(){{document.getElementById('attachModal').style.display='flex';document.getElementById('attachStatus').innerHTML='';document.getElementById('attachFileInput').value=''}}
        function closeAttachModal(){{document.getElementById('attachModal').style.display='none'}}
        function handleAttachDrop(e){{e.preventDefault();e.currentTarget.classList.remove('active');if(e.dataTransfer.files[0])handleAttachFile(e.dataTransfer.files[0])}}
        function handleAttachFile(file){{
            if(!file)return;const status=document.getElementById('attachStatus');const name=file.name.toLowerCase();
            if(!name.endsWith('.xlsx')&&!name.endsWith('.xls')&&!name.endsWith('.csv')){{status.innerHTML='<span style="color:#f85149">Formato inválido.</span>';return}}
            status.innerHTML='<span style="color:#58a6ff">Lendo…</span>';
            const reader=new FileReader();
            reader.onload=function(e){{try{{let nR,nC;
                if(name.endsWith('.csv')){{const t=e.target.result,lines=t.split(/\\r?\\n/).filter(l=>l.trim());if(lines.length<2){{status.innerHTML='<span style="color:#f85149">Vazio.</span>';return}}nC=lines[0].split(',').map(c=>c.trim().replace(/^["']|["']$/g,''));nR=[];for(let i=1;i<lines.length;i++){{const vs=lines[i].split(',').map(v=>v.trim().replace(/^["']|["']$/g,''));const row={{}};nC.forEach((c,j)=>{{let v=vs[j]||'';const n=Number(v);row[c]=v!==''&&!isNaN(n)?n:v}});nR.push(row)}}}}
                else{{const d=new Uint8Array(e.target.result),wb=XLSX.read(d,{{type:'array'}}),json=XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]],{{defval:''}});if(!json.length){{status.innerHTML='<span style="color:#f85149">Vazio.</span>';return}}nC=Object.keys(json[0]);nR=json}}
                const mode=document.getElementById('attachMode').value;let fd;
                if(mode==='append'&&_qd&&_qd.rows&&_qd.rows.length){{const ec=_qd.columns||Object.keys(_qd.rows[0]);fd={{columns:[...new Set([...ec,...nC])],rows:[..._qd.rows,...nR]}};status.innerHTML='<span style="color:#39d353">+'+nR.length+' registros. Abrindo…</span>'}}
                else{{fd={{columns:nC,rows:nR}};status.innerHTML='<span style="color:#39d353">'+nR.length+' registros. Abrindo…</span>'}}
                setTimeout(function(){{const f=document.createElement('form');f.method='POST';f.action='/api/explore/open';f.target='_self';const inp=document.createElement('input');inp.type='hidden';inp.name='json_data';inp.value=JSON.stringify(fd);f.appendChild(inp);document.body.appendChild(f);f.submit()}},600);
            }}catch(err){{status.innerHTML='<span style="color:#f85149">Erro: '+err.message+'</span>'}}}};
            if(name.endsWith('.csv'))reader.readAsText(file);else reader.readAsArrayBuffer(file);
        }}

        // ── Gallery ─────────────────────────────────────────────
        function saveToGallery(){{document.getElementById('saveModal').style.display='flex';document.getElementById('saveTitle').focus()}}
        function closeSaveModal(){{document.getElementById('saveModal').style.display='none';document.getElementById('saveStatus').textContent=''}}
        async function confirmSave(){{
            const t=document.getElementById('saveTitle').value.trim();if(t.length<2){{alert('O título precisa ter ao menos 2 caracteres.');return}}
            const d=document.getElementById('saveDesc').value.trim(),s=document.getElementById('saveStatus');
            s.style.color='#8b949e';s.textContent='Capturando…';
            const tb=document.querySelector('.qi-tb'),md=document.getElementById('saveModal'),am=document.getElementById('attachModal');
            const td=tb?tb.style.display:'';if(tb)tb.style.display='none';if(md)md.style.display='none';if(am)am.style.display='none';
            const ph='<!DOCTYPE html>'+document.documentElement.outerHTML;
            if(tb)tb.style.display=td;if(md)md.style.display='flex';
            const ls={{}};for(let i=0;i<localStorage.length;i++){{const k=localStorage.key(i);ls[k]=localStorage.getItem(k)}}
            s.textContent='Salvando…';
            try{{const r=await fetch('/api/gallery',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{title:t,description:d,query_data:_qd,page_html:ph,local_storage:ls}})}});
                if(r.ok){{s.style.color='#39d353';s.textContent='Salvo.';setTimeout(closeSaveModal,1500)}}else{{s.style.color='#ff6347';let m='Erro ao salvar.';try{{const e=await r.json();const d=e&&e.detail;if(typeof d==='string')m=d;else if(Array.isArray(d)&&d[0])m=(d[0].loc?d[0].loc.slice(-1)[0]+': ':'')+(d[0].msg||'inválido');}}catch(_e){{}}s.textContent=m}}
            }}catch(e){{s.style.color='#ff6347';s.textContent='Erro: '+e.message}}
        }}
    </script>
</body>
</html>"""


def generate_chart_html(data: dict) -> str:
    df = _data_to_df(data)
    if df is None:
        return _empty_html()
    config = _ask_llm_for_chart_config(df) or _fallback_chart_config(df)
    return _render_interactive_chart_html(data, config)


def generate_typed_chart_html(data: dict, chart_type: str, sql_no_limit: str = "") -> str:
    if chart_type == "auto":
        return generate_chart_html(data)
    df = _data_to_df(data)
    if df is None:
        return _empty_html()
    config = _ask_llm_for_chart_config(df) or _fallback_chart_config(df, chart_type)
    config["chart_type"] = chart_type
    return _render_interactive_chart_html(data, config, sql_no_limit=sql_no_limit)


def generate_gallery_view_html(data: dict, chart_config: dict | None, title: str) -> str:
    df = _data_to_df(data)
    if df is None:
        return _empty_html()
    config = chart_config or _fallback_chart_config(df)
    return _render_interactive_chart_html(data, config)


def _empty_html() -> str:
    return """<!DOCTYPE html>
<html><head><title>Fale com Seus Dados</title></head>
<body style="background:#0d1117;color:#8b949e;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center">
<h2 style="color:#ff6347">Sem dados para visualizar</h2>
<p>Execute uma consulta que retorne resultados tabulares.</p>
</div></body></html>"""
