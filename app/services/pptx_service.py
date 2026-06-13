"""
Análise Executiva — Export PPTX nativo (P1).

export_to_pptx_bytes(deck_spec) -> bytes  (assinatura espelha
email_service.export_to_excel_bytes: recebe dict, devolve bytes via BytesIO).

Princípios:
- Gráficos NATIVOS do PowerPoint (add_chart) alimentados pelo data{rows} — sem
  screenshot de Chart.js, sem matplotlib/kaleido. O .pptx sai editável.
- Marca Claro (vermelho #E30613), tag de seção, número-herói grande, caixa de
  "Ação recomendada", rodapé de fonte + nº do slide.
- O SQL de cada insight vai para as speaker notes (auditabilidade fora da app).
"""

from __future__ import annotations

import io
from typing import Any

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE

# ---- Marca -----------------------------------------------------------------
RED   = RGBColor(0xE3, 0x06, 0x13)
INK   = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x6B, 0x72, 0x80)
LIGHT = RGBColor(0xF4, 0xF5, 0xF7)
LINE  = RGBColor(0xE2, 0xE5, 0xEA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x16, 0xA3, 0x4A)
AMBER = RGBColor(0xD9, 0x77, 0x06)

SW, SH = 13.333, 7.5
M = 0.6
_ALIGN = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}


def _slide(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    try:
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = WHITE
    except Exception:
        pass
    return s


def _txt(slide, l, t, w, h, text, size=12, bold=False, color=INK, align="l",
         name="Calibri", italic=False, anchor=None):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Pt(0)
    tf.margin_top = tf.margin_bottom = Pt(0)
    if anchor is not None:
        tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = _ALIGN.get(align, PP_ALIGN.LEFT)
    r = p.add_run()
    r.text = str(text if text is not None else "")
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.name = name
    r.font.color.rgb = color
    return tb


def _bullets(slide, l, t, w, h, items, size=12, color=INK, name="Calibri",
             bullet="•  ", space_after=6):
    tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Pt(0)
    first = True
    for it in items or []:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(space_after)
        r = p.add_run()
        r.text = bullet + str(it)
        r.font.size = Pt(size)
        r.font.name = name
        r.font.color.rgb = color
    return tb


def _rect(slide, l, t, w, h, fill=LIGHT, line=None, rounded=True):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
        Inches(l), Inches(t), Inches(w), Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(0.75)
    shape.shadow.inherit = False
    return shape


def _section_tag(slide, text):
    _txt(slide, M, 0.36, 8, 0.3, (text or "").upper(), size=12, bold=True, color=RED)


def _footer(slide, text, page):
    _txt(slide, M, SH - 0.45, SW - 2 * M - 0.6, 0.3, text or "", size=8.5, color=MUTED)
    _txt(slide, SW - M - 0.6, SH - 0.45, 0.6, 0.3, str(page), size=8.5, color=MUTED, align="r")


def _conf_seal(slide, conf):
    if not conf or not conf.get("level"):
        return
    level = conf.get("level")
    col = GREEN if level == "Alta" else (RED if level == "Baixa" else AMBER)
    _txt(slide, SW - M - 2.6, 0.34, 2.6, 0.3, f"Confiança: {level}", size=10, bold=True, color=col, align="r")


# ---------------------------------------------------------------------------
# Builders por tipo de slide
# ---------------------------------------------------------------------------

def _cover(prs, slide_spec, deck):
    s = _slide(prs)
    _rect(s, 0, 0, 0.22, SH, fill=RED, rounded=False)
    _txt(s, 0.9, 2.3, 11.5, 2.0, slide_spec.get("title") or deck.get("title", ""),
         size=40, bold=True, color=INK)
    sub = slide_spec.get("subtitle") or deck.get("thesis", "")
    if sub:
        _txt(s, 0.9, 4.4, 10.8, 1.6, sub, size=18, color=MUTED)
    _txt(s, 0.9, 6.6, 9, 0.4, slide_spec.get("date_label") or deck.get("date_label", ""),
         size=11, bold=True, color=RED)


def _header(s, slide_spec):
    _section_tag(s, slide_spec.get("section", ""))
    _txt(s, M, 0.68, SW - 2 * M, 0.7, slide_spec.get("title", ""), size=26, bold=True, color=INK)


def _sintese(prs, sp, deck, page):
    s = _slide(prs)
    _header(s, sp)
    if sp.get("thesis"):
        _txt(s, M, 1.45, SW - 2 * M, 0.8, sp["thesis"], size=15, bold=True, color=INK)
    callouts = sp.get("callouts") or []
    if callouts:
        n = len(callouts)
        gap = 0.2
        cw = (SW - 2 * M - gap * (n - 1)) / n
        for i, c in enumerate(callouts):
            x = M + i * (cw + gap)
            _rect(s, x, 2.45, cw, 1.25, fill=LIGHT)
            _txt(s, x + 0.1, 2.58, cw - 0.2, 0.7, c.get("value", ""), size=30, bold=True, color=RED, align="c")
            _txt(s, x + 0.1, 3.28, cw - 0.2, 0.35, c.get("label", ""), size=10, color=MUTED, align="c")
    colw = (SW - 2 * M - 0.4) / 2
    y = 4.1
    _txt(s, M, y, colw, 0.35, "O que os dados mostram", size=13, bold=True, color=INK)
    _bullets(s, M, y + 0.45, colw, 2.2, sp.get("o_que_mostram") or [], size=12, color=INK)
    x2 = M + colw + 0.4
    _txt(s, x2, y, colw, 0.35, "Implicação estratégica", size=13, bold=True, color=RED)
    _bullets(s, x2, y + 0.45, colw, 2.2, sp.get("implicacao") or [], size=12, color=INK)
    _footer(s, deck.get("source_footer", ""), page)


def _sowhat(prs, sp, deck, page):
    s = _slide(prs)
    _header(s, sp)
    pilares = sp.get("pilares") or []
    n = max(1, len(pilares))
    gap = 0.3
    cw = (SW - 2 * M - gap * (n - 1)) / n
    for i, p in enumerate(pilares):
        x = M + i * (cw + gap)
        _rect(s, x, 1.7, cw, 2.7, fill=LIGHT)
        _txt(s, x + 0.25, 1.85, 0.8, 0.7, str(p.get("n", i + 1)), size=34, bold=True, color=RED)
        _txt(s, x + 0.25, 2.7, cw - 0.5, 0.5, p.get("title", ""), size=15, bold=True, color=INK)
        _txt(s, x + 0.25, 3.2, cw - 0.5, 1.1, p.get("text", ""), size=11.5, color=MUTED)
    if sp.get("thesis"):
        _rect(s, M, 4.8, SW - 2 * M, 1.0, fill=RGBColor(0xFC, 0xE9, 0xEA))
        _txt(s, M + 0.25, 5.0, SW - 2 * M - 0.5, 0.7, "Tese: " + sp["thesis"], size=13, bold=True, color=INK, anchor=MSO_ANCHOR.MIDDLE)
    _footer(s, deck.get("source_footer", ""), page)


def _add_chart(slide, chart, l, t, w, h):
    try:
        labels = [str(x) for x in (chart.get("labels") or [])]
        values = [float(v) if v is not None else 0.0 for v in (chart.get("values") or [])]
        if len(labels) < 2 or len(values) < 2:
            return False
        cd = CategoryChartData()
        cd.categories = labels
        cd.add_series(chart.get("y_field", "valor"), values)
        ctype = XL_CHART_TYPE.LINE_MARKERS if chart.get("type") == "line" else XL_CHART_TYPE.COLUMN_CLUSTERED
        gframe = slide.shapes.add_chart(ctype, Inches(l), Inches(t), Inches(w), Inches(h), cd)
        ch = gframe.chart
        ch.has_legend = False
        try:
            ch.has_title = False
            plot = ch.plots[0]
            plot.has_data_labels = False
            ser = plot.series[0]
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = RED
        except Exception:
            pass
        return True
    except Exception:
        return False


def _insight(prs, sp, deck, page):
    s = _slide(prs)
    _header(s, sp)
    _conf_seal(s, sp.get("confidence"))
    if sp.get("subtitle"):
        _txt(s, M, 1.32, SW - 2 * M, 0.4, sp["subtitle"], size=13, color=MUTED, italic=True)
    has_chart = bool(sp.get("chart"))
    left_w = 5.6 if has_chart else (SW - 2 * M)
    # narrativa
    if sp.get("narrative"):
        _txt(s, M, 1.85, left_w, 1.1, sp["narrative"], size=12, color=INK)
    # número-herói
    hero = sp.get("hero") or {}
    _txt(s, M, 3.0, left_w, 1.1, hero.get("value", "—"), size=52, bold=True, color=RED)
    _txt(s, M, 4.15, left_w, 0.35, hero.get("label", ""), size=13, bold=True, color=INK)
    if hero.get("caption"):
        _txt(s, M, 4.5, left_w, 0.35, hero["caption"], size=11, color=MUTED)
    # efeito causal (PSM) — só aparece quando o método rodou de verdade
    cz = sp.get("causal")
    if cz:
        ccol = GREEN if cz.get("significant") else AMBER
        _txt(s, M, 4.85, left_w, 0.5,
             f"Efeito causal (PSM): {cz.get('effect_label','')}  ·  {cz.get('caveat','')}",
             size=9.5, bold=True, color=ccol)
    # gráfico nativo
    if has_chart:
        _add_chart(s, sp["chart"], 6.5, 1.7, SW - M - 6.5, 3.4)
    # ação recomendada
    actions = sp.get("actions") or []
    if actions:
        ay = 5.5 if cz else 5.25
        _txt(s, M, ay, left_w, 0.3, "Ação recomendada", size=12, bold=True, color=RED)
        _bullets(s, M, ay + 0.35, left_w, 1.0, actions, size=11, color=INK, space_after=3)
    foot = _src_footer_for(sp) or deck.get("source_footer", "")
    _footer(s, foot, page)
    # SQL nas speaker notes (auditabilidade)
    if sp.get("sql"):
        try:
            s.notes_slide.notes_text_frame.text = "SQL do número-herói:\n" + sp["sql"]
        except Exception:
            pass


def _src_footer_for(sp):
    src = sp.get("source") or {}
    tables = ", ".join(src.get("tables", [])[:3]) if src else ""
    if not tables:
        return ""
    out = "Fonte: " + tables
    comp = src.get("min_completeness")
    if isinstance(comp, (int, float)):
        out += f" | completude {int(comp)}%"
    return out + " | Análise interna"


def _estrategia(prs, sp, deck, page):
    s = _slide(prs)
    _header(s, sp)
    frentes = sp.get("frentes") or []
    cols, gap = 2, 0.3
    cw = (SW - 2 * M - gap) / cols
    rh = 2.1
    for i, f in enumerate(frentes[:4]):
        row, col = divmod(i, cols)
        x = M + col * (cw + gap)
        y = 1.7 + row * (rh + 0.25)
        _rect(s, x, y, cw, rh, fill=LIGHT)
        _txt(s, x + 0.25, y + 0.18, 0.8, 0.6, str(f.get("n", i + 1)), size=30, bold=True, color=RED)
        _txt(s, x + 1.1, y + 0.22, cw - 1.3, 0.6, f.get("title", ""), size=15, bold=True, color=INK)
        _txt(s, x + 0.25, y + 0.95, cw - 0.5, 1.0, f.get("text", ""), size=11.5, color=MUTED)
    _footer(s, deck.get("source_footer", ""), page)


def _roadmap(prs, sp, deck, page):
    s = _slide(prs)
    _header(s, sp)
    sprints = sp.get("sprints") or []
    n = max(1, len(sprints))
    gap = 0.2
    cw = (SW - 2 * M - gap * (n - 1)) / n
    for i, sp_ in enumerate(sprints[:4]):
        x = M + i * (cw + gap)
        _rect(s, x, 1.7, cw, 0.55, fill=RED)
        _txt(s, x + 0.1, 1.78, cw - 0.2, 0.4, sp_.get("period", ""), size=12, bold=True, color=WHITE, align="c")
        _rect(s, x, 2.3, cw, 3.4, fill=LIGHT)
        _txt(s, x + 0.18, 2.45, cw - 0.36, 0.7, sp_.get("title", ""), size=13, bold=True, color=INK)
        _bullets(s, x + 0.18, 3.2, cw - 0.36, 2.4, sp_.get("bullets") or [], size=10.5, color=MUTED, space_after=4)
    _footer(s, deck.get("source_footer", ""), page)


def _kpis(prs, sp, deck, page):
    s = _slide(prs)
    _header(s, sp)
    metas = sp.get("metas") or []
    if metas:
        n = len(metas)
        gap = 0.2
        cw = (SW - 2 * M - gap * (n - 1)) / n
        for i, m in enumerate(metas):
            x = M + i * (cw + gap)
            _rect(s, x, 1.6, cw, 1.25, fill=LIGHT)
            _txt(s, x + 0.1, 1.72, cw - 0.2, 0.7, m.get("value", ""), size=28, bold=True, color=RED, align="c")
            _txt(s, x + 0.1, 2.42, cw - 0.2, 0.35, m.get("label", ""), size=10, color=MUTED, align="c")
    colw = (SW - 2 * M - 0.4) / 2
    y = 3.3
    _txt(s, M, y, colw, 0.35, "Ritual de gestão", size=13, bold=True, color=INK)
    _bullets(s, M, y + 0.45, colw, 2.2, sp.get("ritual") or [], size=12, color=INK)
    x2 = M + colw + 0.4
    _txt(s, x2, y, colw, 0.35, "Papéis recomendados", size=13, bold=True, color=RED)
    donos = []
    for d in sp.get("donos") or []:
        if isinstance(d, dict):
            donos.append(f"{d.get('role','')}: {d.get('scope','')}")
        else:
            donos.append(str(d))
    _bullets(s, x2, y + 0.45, colw, 2.2, donos, size=12, color=INK)
    _footer(s, deck.get("source_footer", ""), page)


_BUILDERS = {
    "sintese": _sintese, "sowhat": _sowhat, "insight": _insight,
    "estrategia": _estrategia, "roadmap": _roadmap, "kpis": _kpis,
}


def export_to_pptx_bytes(deck: dict) -> bytes:
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)
    page = 0
    for sp in deck.get("slides", []):
        page += 1
        stype = sp.get("type")
        try:
            if stype == "cover":
                _cover(prs, sp, deck)
            elif stype in _BUILDERS:
                _BUILDERS[stype](prs, sp, deck, page)
            else:
                # tipo desconhecido — slide de texto simples (não quebra o export)
                s = _slide(prs)
                _header(s, sp)
                _footer(s, deck.get("source_footer", ""), page)
        except Exception:
            # um slide problemático não pode derrubar o deck inteiro
            try:
                s = _slide(prs)
                _txt(s, M, 0.7, SW - 2 * M, 0.7, sp.get("title", "Slide"), size=24, bold=True, color=INK)
            except Exception:
                pass
    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf.getvalue()
