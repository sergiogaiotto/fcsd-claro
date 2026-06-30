"""
Fale com Seus Dados — Data Catalog Service

Módulo de Catálogo de Dados com:
- Profiling automático (estatísticas descritivas por coluna)
- Enriquecimento semântico via LLM (descrições, domínio, entidades)
- Inferência de relacionamentos (FK-like)
- Motor de qualidade de dados (completeness, consistency, validity)
- Detecção de PII / dados sensíveis
- Busca inteligente
"""

import json
import math
import re
from app.core.db_engine import DialectConnection
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.database import (
    get_sync_connection,
    get_all_tables,
    INTERNAL_TABLES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(v):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return round(float(v), 4)
    return v


# ---------------------------------------------------------------------------
# PII / Sensitive Data Detection
# ---------------------------------------------------------------------------

_PII_PATTERNS = {
    "cpf": r"\b\d{3}\.?\d{3}\.?\d{3}[-.]?\d{2}\b",
    "cnpj": r"\b\d{2}\.?\d{3}\.?\d{3}[/]?\d{4}[-.]?\d{2}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "telefone": r"\b\(?\d{2}\)?\s?\d{4,5}[-.]?\d{4}\b",
    "cep": r"\b\d{5}[-]?\d{3}\b",
    "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
}

_PII_NAME_HINTS = {
    "cpf", "cnpj", "rg", "passport", "passaporte", "ssn", "social_security",
    "email", "e_mail", "telefone", "phone", "celular", "mobile",
    "endereco", "address", "cep", "zip", "zip_code",
    "senha", "password", "token", "secret", "api_key",
    "cartao", "card_number", "credit_card", "conta", "account",
    "nome_completo", "full_name", "nome_mae", "mother_name",
    "data_nascimento", "birth_date", "dob",
    "salario", "salary", "wage", "remuneracao",
    "ip_address", "ip", "mac_address",
}

_SENSITIVITY_LEVELS = {
    "cpf": "alto", "cnpj": "medio", "email": "medio", "telefone": "medio",
    "cep": "baixo", "credit_card": "alto", "name_hint": "medio",
}


def _detect_pii(col_name: str, sample_values: list) -> dict:
    """Detect PII in column by name patterns and value regex."""
    result = {"is_sensitive": False, "pii_type": None, "sensitivity": None, "confidence": 0.0}

    col_lower = col_name.lower().replace(" ", "_")
    for hint in _PII_NAME_HINTS:
        if hint in col_lower or col_lower in hint:
            result.update({
                "is_sensitive": True, "pii_type": f"name_match:{hint}",
                "sensitivity": "medio", "confidence": 0.7,
            })
            break

    sample_str = [str(v) for v in sample_values if v is not None and str(v).strip()][:100]
    if not sample_str:
        return result

    for pii_type, pattern in _PII_PATTERNS.items():
        matches = sum(1 for v in sample_str if re.search(pattern, v))
        ratio = matches / len(sample_str) if sample_str else 0
        if ratio >= 0.3:
            confidence = min(ratio + 0.2, 1.0)
            if confidence > result["confidence"]:
                result.update({
                    "is_sensitive": True, "pii_type": pii_type,
                    "sensitivity": _SENSITIVITY_LEVELS.get(pii_type, "medio"),
                    "confidence": round(confidence, 2),
                })

    return result


# ---------------------------------------------------------------------------
# Semantic Type Detection
# ---------------------------------------------------------------------------

def _infer_semantic_type(col_name: str, dtype: str, sample_values: list, stats: dict) -> str:
    """Infer semantic type from column name, data type, and sample values."""
    name = col_name.lower().replace(" ", "_")

    date_hints = {"data", "date", "dt", "created", "updated", "timestamp", "time", "hora",
                  "ano", "year", "mes", "month", "dia", "day", "periodo", "semestre", "trimestre"}
    id_hints = {"id", "cod", "codigo", "code", "key", "chave", "pk", "fk", "seq", "num", "numero"}
    money_hints = {"valor", "value", "preco", "price", "custo", "cost", "total", "subtotal",
                   "receita", "revenue", "faturamento", "salario", "salary", "desconto", "discount",
                   "imposto", "tax", "margem", "margin", "lucro", "profit"}
    pct_hints = {"pct", "percent", "percentual", "taxa", "rate", "ratio", "proporcao"}
    qty_hints = {"qtd", "qty", "quantidade", "quantity", "count", "contagem", "volume", "estoque", "stock"}
    geo_hints = {"cidade", "city", "estado", "state", "uf", "pais", "country", "regiao", "region",
                 "bairro", "cep", "zip", "lat", "lng", "longitude", "latitude"}
    cat_hints = {"tipo", "type", "categoria", "category", "status", "grupo", "group", "classe",
                 "segmento", "segment", "canal", "channel", "marca", "brand"}
    bool_hints = {"ativo", "active", "flag", "bool", "sim_nao", "yes_no", "is_", "has_", "pode", "tem"}
    name_hints = {"nome", "name", "descricao", "description", "titulo", "title", "label", "rotulo"}

    for hint in date_hints:
        if hint in name or name.startswith(hint) or name.endswith(hint):
            return "data/tempo"
    for hint in id_hints:
        if hint == name or name.endswith("_" + hint) or name.startswith(hint + "_"):
            return "identificador"
    for hint in money_hints:
        if hint in name:
            return "monetário"
    for hint in pct_hints:
        if hint in name:
            return "percentual"
    for hint in qty_hints:
        if hint in name:
            return "quantidade"
    for hint in geo_hints:
        if hint in name:
            return "geográfico"
    for hint in bool_hints:
        if hint in name or name.startswith("is_") or name.startswith("has_"):
            return "booleano"
    for hint in cat_hints:
        if hint in name:
            return "categórico"
    for hint in name_hints:
        if hint in name:
            return "texto descritivo"

    if "int" in dtype.lower() or "real" in dtype.lower() or "float" in dtype.lower() or "numeric" in dtype.lower():
        cardinality = stats.get("cardinality", 0)
        total = stats.get("count", 1)
        if cardinality and total and cardinality <= 2:
            return "booleano"
        if cardinality and total and cardinality / max(total, 1) < 0.05:
            return "categórico"
        return "numérico"

    if "text" in dtype.lower() or "varchar" in dtype.lower() or "char" in dtype.lower():
        cardinality = stats.get("cardinality", 0)
        total = stats.get("count", 1)
        if cardinality and total and cardinality / max(total, 1) < 0.1:
            return "categórico"
        sample_str = [str(v) for v in sample_values if v is not None][:20]
        if sample_str:
            date_pattern = r"\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4}"
            date_matches = sum(1 for v in sample_str if re.match(date_pattern, v))
            if date_matches / len(sample_str) > 0.5:
                return "data/tempo"
        return "texto"

    return "desconhecido"


# ---------------------------------------------------------------------------
# Domain Classification
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS = {
    "Financeiro": {"receita", "despesa", "faturamento", "lucro", "margem", "dre", "balanco",
                   "custo", "imposto", "tax", "orcamento", "budget", "fluxo_caixa", "ebitda",
                   "investimento", "conta", "contabil", "debito", "credito", "valor"},
    "Vendas": {"venda", "pedido", "order", "cliente", "customer", "produto", "product",
               "faturamento", "revenue", "pipeline", "lead", "conversao", "ticket", "comissao",
               "vendedor", "seller", "quota", "meta", "negocio", "deal"},
    "Marketing": {"campanha", "campaign", "lead", "cac", "roi", "impressao", "clique", "click",
                  "conversao", "conversion", "canal", "channel", "midia", "media", "engagement",
                  "bounce", "utm", "session", "pageview"},
    "RH": {"funcionario", "employee", "salario", "salary", "cargo", "position", "departamento",
            "department", "admissao", "demissao", "turnover", "headcount", "beneficio",
            "ferias", "folha", "payroll", "avaliacao", "performance"},
    "Operações": {"estoque", "stock", "inventory", "logistica", "entrega", "delivery", "sla",
                  "fornecedor", "supplier", "compra", "purchase", "armazem", "warehouse",
                  "producao", "production", "defeito", "quality"},
    "Produto": {"usuario", "user", "churn", "retencao", "retention", "nps", "feature",
                "engagement", "session", "ativo", "active", "signup", "onboarding",
                "feedback", "rating", "review"},
    "Saúde": {"paciente", "patient", "leito", "bed", "atendimento", "consulta", "diagnostico",
              "cid", "medicamento", "prescricao", "exame", "internacao", "alta", "obito"},
    "Educação": {"aluno", "student", "matricula", "enrollment", "turma", "class", "nota",
                 "grade", "disciplina", "course", "evasao", "dropout", "professor", "teacher",
                 "frequencia", "attendance"},
}


def _classify_domain(table_name: str, column_names: list) -> dict:
    """Classify table domain based on table name and column names."""
    all_tokens = set()
    for name in [table_name] + column_names:
        tokens = re.findall(r'\b\w{3,}\b', name.lower())
        all_tokens.update(tokens)

    scores = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = len(all_tokens & keywords)
        if score > 0:
            scores[domain] = score

    if not scores:
        return {"domain": "N/D", "confidence": 0.0, "scores": {}}

    total = sum(scores.values())
    best_domain = max(scores, key=scores.get)
    confidence = round(scores[best_domain] / max(total, 1), 2)

    return {
        "domain": best_domain,
        "confidence": confidence,
        "scores": {k: round(v / max(total, 1), 2) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
    }


# ---------------------------------------------------------------------------
# Entity Detection
# ---------------------------------------------------------------------------

_ENTITY_PATTERNS = {
    "cliente": {"cliente", "customer", "comprador", "buyer", "consumidor"},
    "produto": {"produto", "product", "item", "sku", "mercadoria", "artigo"},
    "pedido": {"pedido", "order", "compra", "purchase", "venda", "sale", "transacao"},
    "funcionário": {"funcionario", "employee", "colaborador", "worker", "empregado"},
    "fornecedor": {"fornecedor", "supplier", "vendor", "parceiro"},
    "loja": {"loja", "store", "filial", "branch", "unidade", "ponto_venda"},
    "região": {"regiao", "region", "estado", "state", "cidade", "city", "pais", "country"},
    "período": {"data", "date", "mes", "month", "ano", "year", "periodo", "semestre", "trimestre"},
    "financeiro": {"receita", "revenue", "custo", "cost", "lucro", "profit", "valor", "preco"},
    "campanha": {"campanha", "campaign", "midia", "media", "canal", "channel"},
}


def _detect_entities(table_name: str, column_names: list) -> list:
    """Detect business entities present in the table."""
    all_tokens = set()
    for name in [table_name] + column_names:
        tokens = re.findall(r'\b\w{3,}\b', name.lower())
        all_tokens.update(tokens)

    entities = []
    for entity, keywords in _ENTITY_PATTERNS.items():
        matches = all_tokens & keywords
        if matches:
            entities.append({
                "entity": entity,
                "matched_terms": sorted(matches),
                "confidence": round(min(len(matches) * 0.3 + 0.4, 1.0), 2),
            })

    return sorted(entities, key=lambda e: -e["confidence"])


# ---------------------------------------------------------------------------
# Column Profiling
# ---------------------------------------------------------------------------

def _profile_column(conn: DialectConnection, table_name: str, col_name: str, col_type: str) -> dict:
    """Profile a single column: stats, distribution, PII, semantic type."""
    profile = {
        "column": col_name,
        "technical_type": col_type,
        "semantic_type": None,
        "count": 0, "nulls": 0, "blanks": 0, "cardinality": 0,
        "completeness": 0.0,
        "pii": {"is_sensitive": False},
    }

    try:
        # Basic counts
        total = conn.execute(f'SELECT COUNT(*) AS n FROM "{table_name}"').fetchone()[0]
        nulls = conn.execute(f'SELECT COUNT(*) AS n FROM "{table_name}" WHERE "{col_name}" IS NULL').fetchone()[0]
        blanks = conn.execute(
            f'SELECT COUNT(*) AS n FROM "{table_name}" WHERE "{col_name}" IS NOT NULL AND TRIM(CAST("{col_name}" AS TEXT)) = \'\''
        ).fetchone()[0]
        cardinality = conn.execute(f'SELECT COUNT(DISTINCT "{col_name}") AS n FROM "{table_name}" WHERE "{col_name}" IS NOT NULL').fetchone()[0]

        profile["count"] = total
        profile["nulls"] = nulls
        profile["blanks"] = blanks
        profile["cardinality"] = cardinality
        profile["completeness"] = round((total - nulls) / max(total, 1) * 100, 1)

        # Sample values
        sample_rows = conn.execute(
            f'SELECT "{col_name}" FROM "{table_name}" WHERE "{col_name}" IS NOT NULL LIMIT 100'
        ).fetchall()
        sample_values = [r[0] for r in sample_rows]
        profile["sample_values"] = [str(v) for v in sample_values[:5]]

        # Top values (frequency)
        top_rows = conn.execute(
            f'SELECT "{col_name}" AS value, COUNT(*) as cnt FROM "{table_name}" WHERE "{col_name}" IS NOT NULL '
            f'GROUP BY "{col_name}" ORDER BY cnt DESC LIMIT 10'
        ).fetchall()
        profile["top_values"] = [{"value": str(r[0]), "count": r[1]} for r in top_rows]

        # Numeric stats — Postgres is strongly typed, so col_type tells us straight up
        numeric_types = {
            "smallint", "integer", "bigint", "decimal", "numeric",
            "real", "double precision", "money",
        }
        is_numeric = col_type.lower() in numeric_types or col_type.upper() in (
            "INTEGER", "REAL", "NUMERIC", "FLOAT", "DOUBLE", "DECIMAL", "BIGINT", "SMALLINT"
        )

        if is_numeric:
            try:
                stats_row = conn.execute(
                    f'SELECT MIN("{col_name}"::double precision) AS mn, '
                    f'MAX("{col_name}"::double precision) AS mx, '
                    f'AVG("{col_name}"::double precision) AS av '
                    f'FROM "{table_name}" WHERE "{col_name}" IS NOT NULL'
                ).fetchone()
                if stats_row:
                    profile["min"] = _safe(stats_row[0])
                    profile["max"] = _safe(stats_row[1])
                    profile["mean"] = _safe(stats_row[2])
                    profile["range"] = _safe((stats_row[1] or 0) - (stats_row[0] or 0))

                    # Std dev / median via numpy (works on either backend)
                    try:
                        vals = [float(r[0]) for r in conn.execute(
                            f'SELECT "{col_name}"::double precision FROM "{table_name}" WHERE "{col_name}" IS NOT NULL LIMIT 10000'
                        ).fetchall()]
                        if vals:
                            profile["std"] = _safe(float(np.std(vals)))
                            profile["median"] = _safe(float(np.median(vals)))
                    except Exception:
                        pass
            except Exception:
                pass

        # String length stats for text columns
        if not is_numeric and sample_values:
            lengths = [len(str(v)) for v in sample_values if v is not None]
            if lengths:
                profile["avg_length"] = _safe(round(np.mean(lengths), 1))
                profile["max_length"] = max(lengths)
                profile["min_length"] = min(lengths)

        # PII detection
        profile["pii"] = _detect_pii(col_name, sample_values)

        # Semantic type
        profile["semantic_type"] = _infer_semantic_type(
            col_name, col_type, sample_values,
            {"cardinality": cardinality, "count": total},
        )

    except Exception as e:
        profile["error"] = str(e)[:100]

    return profile


# ---------------------------------------------------------------------------
# Relationship Inference
# ---------------------------------------------------------------------------

def _infer_relationships(conn: DialectConnection, tables: list[dict]) -> list:
    """Infer FK-like relationships between tables via name matching and value overlap."""
    relationships = []
    seen = set()

    # Build column index: {col_name_normalized: [(table, col, cardinality), ...]}
    col_index = {}
    for t in tables:
        for c in t["columns"]:
            key = c["name"].lower().replace("_id", "").replace("id_", "").rstrip("_")
            if key not in col_index:
                col_index[key] = []
            # Get cardinality
            try:
                card = conn.execute(
                    f'SELECT COUNT(DISTINCT "{c["name"]}") FROM "{t["name"]}" WHERE "{c["name"]}" IS NOT NULL'
                ).fetchone()[0]
            except Exception:
                card = 0
            col_index[key].append({"table": t["name"], "column": c["name"], "cardinality": card})

    # Check pairs with similar names
    for key, entries in col_index.items():
        if len(entries) < 2 or len(key) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                if a["table"] == b["table"]:
                    continue
                pair_key = tuple(sorted([(a["table"], a["column"]), (b["table"], b["column"])]))
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                # Calculate confidence
                confidence = 0.0

                # Name similarity
                a_norm = a["column"].lower().replace("_", "")
                b_norm = b["column"].lower().replace("_", "")
                if a_norm == b_norm:
                    confidence += 0.4
                elif a_norm.endswith("id") and b_norm == "id":
                    confidence += 0.5
                elif b_norm.endswith("id") and a_norm == "id":
                    confidence += 0.5
                else:
                    confidence += 0.2

                # Value overlap (sample-based)
                try:
                    a_vals = set(r[0] for r in conn.execute(
                        f'SELECT DISTINCT "{a["column"]}" FROM "{a["table"]}" WHERE "{a["column"]}" IS NOT NULL LIMIT 500'
                    ).fetchall())
                    b_vals = set(r[0] for r in conn.execute(
                        f'SELECT DISTINCT "{b["column"]}" FROM "{b["table"]}" WHERE "{b["column"]}" IS NOT NULL LIMIT 500'
                    ).fetchall())
                    if a_vals and b_vals:
                        overlap = len(a_vals & b_vals) / max(min(len(a_vals), len(b_vals)), 1)
                        confidence += overlap * 0.4
                except Exception:
                    pass

                # Cardinality ratio (one side should be higher)
                if a["cardinality"] > 0 and b["cardinality"] > 0:
                    ratio = min(a["cardinality"], b["cardinality"]) / max(a["cardinality"], b["cardinality"])
                    if ratio < 0.3:
                        confidence += 0.1

                if confidence >= 0.3:
                    # Determine direction (lower cardinality = likely PK side)
                    if a["cardinality"] <= b["cardinality"]:
                        source, target = a, b
                    else:
                        source, target = b, a

                    rel_type = "1:N" if source["cardinality"] < target["cardinality"] * 0.5 else "N:N"

                    relationships.append({
                        "source_table": source["table"],
                        "source_column": source["column"],
                        "target_table": target["table"],
                        "target_column": target["column"],
                        "confidence": round(min(confidence, 1.0), 2),
                        "type": rel_type,
                    })

    return sorted(relationships, key=lambda r: -r["confidence"])


# ---------------------------------------------------------------------------
# Data Quality Scoring
# ---------------------------------------------------------------------------

def _compute_quality(table_name: str, profiles: list[dict]) -> dict:
    """Compute data quality score for a table based on column profiles."""
    if not profiles:
        return {"overall": 0, "completeness": 0, "consistency": 0, "validity": 0}

    # Completeness: avg percentage of non-null values
    completeness_scores = [p.get("completeness", 0) for p in profiles]
    completeness = round(np.mean(completeness_scores), 1) if completeness_scores else 0

    # Consistency: penalize columns with mixed types or high blank ratio
    consistency_scores = []
    for p in profiles:
        total = p.get("count", 0)
        blanks = p.get("blanks", 0)
        blank_ratio = blanks / max(total, 1)
        consistency_scores.append(round((1 - blank_ratio) * 100, 1))
    consistency = round(np.mean(consistency_scores), 1) if consistency_scores else 0

    # Validity: based on cardinality ratio (not all same value, not all unique for categoricals)
    validity_scores = []
    for p in profiles:
        total = p.get("count", 0)
        card = p.get("cardinality", 0)
        nulls = p.get("nulls", 0)
        non_null = total - nulls
        if non_null <= 0:
            validity_scores.append(0)
            continue
        ratio = card / non_null
        if ratio == 0:
            validity_scores.append(0)
        elif ratio <= 0.001 and non_null > 100:
            validity_scores.append(50)  # Suspiciously low cardinality
        else:
            validity_scores.append(100)
    validity = round(np.mean(validity_scores), 1) if validity_scores else 0

    overall = round((completeness * 0.4 + consistency * 0.3 + validity * 0.3), 1)

    return {
        "overall": overall,
        "completeness": completeness,
        "consistency": consistency,
        "validity": validity,
        "issues": _detect_quality_issues(profiles),
    }


def _detect_quality_issues(profiles: list[dict]) -> list:
    """Detect specific quality issues from column profiles."""
    issues = []
    for p in profiles:
        col = p.get("column", "?")
        total = p.get("count", 0)
        nulls = p.get("nulls", 0)
        blanks = p.get("blanks", 0)
        card = p.get("cardinality", 0)

        null_pct = nulls / max(total, 1) * 100
        if null_pct > 50:
            issues.append({"column": col, "type": "high_nulls",
                           "severity": "alto", "detail": f"{null_pct:.0f}% de valores nulos"})
        elif null_pct > 20:
            issues.append({"column": col, "type": "moderate_nulls",
                           "severity": "medio", "detail": f"{null_pct:.0f}% de valores nulos"})

        blank_pct = blanks / max(total, 1) * 100
        if blank_pct > 10:
            issues.append({"column": col, "type": "blanks",
                           "severity": "medio", "detail": f"{blank_pct:.0f}% de valores em branco"})

        if card == 1 and total > 10:
            issues.append({"column": col, "type": "constant",
                           "severity": "alto", "detail": "Coluna com valor constante (cardinalidade = 1)"})

        if card == total and total > 10:
            issues.append({"column": col, "type": "all_unique",
                           "severity": "info", "detail": "Todos os valores são únicos (possível identificador)"})

        if p.get("pii", {}).get("is_sensitive"):
            pii_type = p["pii"].get("pii_type", "desconhecido")
            issues.append({"column": col, "type": "pii_detected",
                           "severity": "alto", "detail": f"PII detectado: {pii_type}"})

    return sorted(issues, key=lambda i: {"alto": 0, "medio": 1, "baixo": 2, "info": 3}.get(i["severity"], 9))


# ---------------------------------------------------------------------------
# LLM Enrichment
# ---------------------------------------------------------------------------

_ENRICH_PROMPT = """Você é um especialista em Data Catalog. Analise a tabela e colunas abaixo e gere descrições semânticas.

## Tabela: {table_name}
Registros: {row_count}
Domínio detectado: {domain}

## Colunas:
{columns_info}

## Tarefa
Para cada coluna e para a tabela, gere:
1. Descrição da tabela (1-2 frases)
2. Para cada coluna: descrição semântica (1 frase), classificação (dimensão, métrica, identificador, atributo)

Retorne APENAS JSON válido:
{{
  "table_description": "...",
  "columns": {{
    "nome_coluna": {{"description": "...", "classification": "dimensão|métrica|identificador|atributo"}},
    ...
  }},
  "suggested_kpis": ["KPI 1", "KPI 2", "KPI 3"],
  "suggested_joins": ["Sugestão de join 1", "Sugestão de join 2"]
}}
"""


async def enrich_table_with_llm(table_name: str) -> dict:
    """Use LLM to generate semantic descriptions for a table and its columns."""
    if not (settings.oss120b_url or settings.azure_openai_api_key or settings.openai_api_key):
        return {"error": "Nenhum LLM configurado."}

    
    conn = get_sync_connection()
    try:
        # Get table info
        row_count = conn.execute(f'SELECT COUNT(*) AS n FROM "{table_name}"').fetchone()[0]
        cols_info = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ? "
            "ORDER BY ordinal_position",
            (table_name,),
        ).fetchall()
        col_names = [c["column_name"] for c in cols_info]

        domain_info = _classify_domain(table_name, col_names)

        # Build column descriptions
        cols_text = []
        for c in cols_info:
            col_name, col_type = c["column_name"], c["data_type"]
            sample = conn.execute(
                f'SELECT DISTINCT "{col_name}" FROM "{table_name}" WHERE "{col_name}" IS NOT NULL LIMIT 5'
            ).fetchall()
            sample_vals = [str(r[0]) for r in sample]
            card = conn.execute(
                f'SELECT COUNT(DISTINCT "{col_name}") AS n FROM "{table_name}" WHERE "{col_name}" IS NOT NULL'
            ).fetchone()[0]
            cols_text.append(f"  - {col_name} ({col_type}, {card} valores únicos, ex: {sample_vals[:3]})")

        prompt = _ENRICH_PROMPT.format(
            table_name=table_name,
            row_count=row_count,
            domain=domain_info["domain"],
            columns_info="\n".join(cols_text),
        )

        # from langchain_openai import ChatOpenAI
        # llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.2)
        from app.services.llm_factory import make_chat_llm
        llm = make_chat_llm(temperature=0.2, role="catalog_enrich")
        response = llm.invoke(prompt)
        content = response.content.strip()

        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()

        result = json.loads(content)
        result["table_name"] = table_name
        result["enriched_at"] = datetime.utcnow().isoformat()

        # Save enrichment to catalog
        _save_enrichment(table_name, result)

        return result

    except json.JSONDecodeError:
        return {"error": "Resposta inválida da IA."}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        conn.close()


def _save_enrichment(table_name: str, enrichment: dict):
    """Persist LLM enrichment to catalog tables."""
    conn = get_sync_connection()
    try:
        # Update dataset description
        conn.execute(
            """INSERT INTO catalog_datasets (table_name, description, domain, enriched_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(table_name) DO UPDATE SET
               description=excluded.description, domain=excluded.domain, enriched_at=excluded.enriched_at""",
            (table_name, enrichment.get("table_description", ""),
             enrichment.get("domain", ""), enrichment.get("enriched_at", "")),
        )

        # Update column descriptions
        for col_name, col_info in enrichment.get("columns", {}).items():
            conn.execute(
                """UPDATE catalog_columns SET description=?, classification=?, enriched_at=?
                   WHERE table_name=? AND column_name=?""",
                (col_info.get("description", ""), col_info.get("classification", ""),
                 enrichment.get("enriched_at", ""), table_name, col_name),
            )

        # Save KPIs and joins
        extras = json.dumps({
            "suggested_kpis": enrichment.get("suggested_kpis", []),
            "suggested_joins": enrichment.get("suggested_joins", []),
        }, ensure_ascii=False)
        conn.execute(
            "UPDATE catalog_datasets SET extras=? WHERE table_name=?",
            (extras, table_name),
        )

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Full Scan — Main Entry Point
# ---------------------------------------------------------------------------

def scan_catalog_iter(table_names: list[str] | None = None):
    """Gerador do scan de catálogo: roda tabela-a-tabela e emite eventos de progresso
    (dicts com 'phase': start / table_start / table_done / relationships / done). O evento
    'done' carrega o resumo completo. Alimenta a rota de streaming (/catalog/scan/stream);
    run_catalog_scan() consome este gerador e devolve só o resumo (assinatura preservada)."""
    conn = get_sync_connection()
    try:
        all_tables = get_all_tables()
        if table_names:
            all_tables = [t for t in all_tables if t["name"] in set(table_names)]

        if not all_tables:
            yield {"phase": "done", "result": {"error": "Nenhuma tabela encontrada."}}
            return

        total = len(all_tables)
        yield {"phase": "start", "total": total, "tables": [t["name"] for t in all_tables]}

        scanned = 0
        total_cols = 0
        total_rows = 0

        for i, table in enumerate(all_tables):
            t_name = table["name"]
            col_names = [c["name"] for c in table["columns"]]
            yield {"phase": "table_start", "table": t_name, "index": i, "total": total,
                   "columns": len(col_names), "rows": table.get("row_count", 0)}

            # Profile each column
            profiles = []
            for col in table["columns"]:
                profiles.append(_profile_column(conn, t_name, col["name"], col["type"]))

            domain_info = _classify_domain(t_name, col_names)
            entities = _detect_entities(t_name, col_names)
            quality = _compute_quality(t_name, profiles)
            sensitive_count = sum(1 for p in profiles if p.get("pii", {}).get("is_sensitive"))

            entry = {
                "table_name": t_name,
                "row_count": table["row_count"],
                "col_count": len(table["columns"]),
                "domain": domain_info,
                "entities": entities,
                "quality": quality,
                "profiles": profiles,
                "sensitive_columns": sensitive_count,
                "scanned_at": datetime.utcnow().isoformat(),
            }
            _persist_scan(t_name, entry)
            scanned += 1
            total_cols += entry["col_count"]
            total_rows += entry["row_count"]

            yield {"phase": "table_done", "table": t_name, "index": i, "total": total,
                   "quality": (quality or {}).get("overall"),
                   "domain": (domain_info or {}).get("domain"),
                   "sensitive": sensitive_count}

        # Infer relationships (fase final, cross-table)
        yield {"phase": "relationships", "total": total}
        relationships = _infer_relationships(conn, all_tables)
        _persist_relationships(relationships)

        yield {"phase": "done", "result": {
            "tables_scanned": scanned,
            "total_columns": total_cols,
            "total_rows": total_rows,
            "relationships": relationships,
            "scanned_at": datetime.utcnow().isoformat(),
        }}
    finally:
        conn.close()


def run_catalog_scan(table_names: list[str] | None = None) -> dict:
    """Run full catalog scan: profile all columns, detect relationships, score quality.
    Consome scan_catalog_iter() e devolve só o resumo final (compat. com chamadores legados)."""
    result = {"error": "Scan não retornou resultado."}
    for ev in scan_catalog_iter(table_names):
        if ev.get("phase") == "done":
            result = ev.get("result", result)
    return result


def _persist_scan(table_name: str, entry: dict):
    """Save scan results to catalog tables."""
    conn = get_sync_connection()
    try:
        # Upsert dataset
        domain = entry.get("domain", {}).get("domain", "Geral")
        quality_json = json.dumps(entry.get("quality", {}), ensure_ascii=False)
        entities_json = json.dumps(entry.get("entities", []), ensure_ascii=False)

        conn.execute(
            """INSERT INTO catalog_datasets (table_name, domain, quality_score, quality_detail, entities, row_count, col_count, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(table_name) DO UPDATE SET
               domain=excluded.domain, quality_score=excluded.quality_score,
               quality_detail=excluded.quality_detail, entities=excluded.entities,
               row_count=excluded.row_count, col_count=excluded.col_count,
               scanned_at=excluded.scanned_at""",
            (table_name, domain, entry["quality"]["overall"], quality_json,
             entities_json, entry["row_count"], entry["col_count"], entry["scanned_at"]),
        )

        # Upsert columns
        for p in entry.get("profiles", []):
            profile_json = json.dumps({
                k: v for k, v in p.items()
                if k not in ("column", "technical_type", "semantic_type", "pii")
            }, ensure_ascii=False, default=str)
            pii_json = json.dumps(p.get("pii", {}), ensure_ascii=False)

            conn.execute(
                """INSERT INTO catalog_columns
                   (table_name, column_name, technical_type, semantic_type, profile_data, pii_data, scanned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(table_name, column_name) DO UPDATE SET
                   technical_type=excluded.technical_type, semantic_type=excluded.semantic_type,
                   profile_data=excluded.profile_data, pii_data=excluded.pii_data,
                   scanned_at=excluded.scanned_at""",
                (table_name, p["column"], p.get("technical_type", ""),
                 p.get("semantic_type", ""), profile_json, pii_json, entry["scanned_at"]),
            )

        conn.commit()
    finally:
        conn.close()


def _persist_relationships(relationships: list):
    """Save inferred relationships to catalog tables."""
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM catalog_relationships")
        for r in relationships:
            conn.execute(
                """INSERT INTO catalog_relationships
                   (source_table, source_column, target_table, target_column, confidence, rel_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (r["source_table"], r["source_column"], r["target_table"],
                 r["target_column"], r["confidence"], r["type"]),
            )
        conn.commit()
    finally:
        conn.close()


def recompute_dataset_quality(table_name: str) -> dict:
    """Recomputa e persiste quality_detail/entities/quality_score de um dataset a
    partir do estado ATUAL de catalog_columns (após edição manual de coluna).

    Reusa as mesmas funções do scan (_compute_quality/_detect_quality_issues/
    _detect_entities), mas SEM re-profilar os dados — aproveita o profile_data já
    gravado (nulls/blanks/cardinalidade/completude) combinado com o pii_data e o
    semantic_type EDITADOS. Assim, desmarcar um PII remove o "PII detectado",
    definir um tipo semântico atualiza a validade, etc. Retorna {} se a tabela
    não estiver catalogada."""
    conn = get_sync_connection()
    try:
        from app.core.db_engine import table_exists as _table_exists
        if not _table_exists(conn, "catalog_columns") or not _table_exists(conn, "catalog_datasets"):
            return {}
        rows = conn.execute(
            "SELECT column_name, semantic_type, profile_data, pii_data "
            "FROM catalog_columns WHERE table_name=? ORDER BY column_name",
            (table_name,),
        ).fetchall()
        if not rows:
            return {}
        profiles: list[dict] = []
        col_names: list[str] = []
        for r in rows:
            d = dict(r)
            col_names.append(d["column_name"])
            try:
                prof = json.loads(d.get("profile_data") or "{}")
            except (ValueError, TypeError):
                prof = {}
            if not isinstance(prof, dict):
                prof = {}
            try:
                pii = json.loads(d.get("pii_data") or "{}")
            except (ValueError, TypeError):
                pii = {}
            prof["column"] = d["column_name"]
            prof["semantic_type"] = d.get("semantic_type") or ""
            prof["pii"] = pii if isinstance(pii, dict) else {}
            profiles.append(prof)

        quality = _compute_quality(table_name, profiles)
        entities = _detect_entities(table_name, col_names)

        conn.execute(
            "UPDATE catalog_datasets SET quality_score=?, quality_detail=?, entities=? "
            "WHERE table_name=?",
            (
                quality.get("overall", 0),
                json.dumps(quality, ensure_ascii=False),
                json.dumps(entities, ensure_ascii=False),
                table_name,
            ),
        )
        conn.commit()
        return {"quality": quality, "entities": entities}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read Catalog (for API)
# ---------------------------------------------------------------------------

def get_catalog_summary() -> dict:
    """Get catalog overview for the dashboard."""
    from app.core.db_engine import table_exists as _table_exists
    conn = get_sync_connection()
    try:
        # Check if catalog has been scanned
        if not _table_exists(conn, "catalog_datasets"):
            return {"scanned": False, "tables": []}
        datasets = conn.execute(
            "SELECT * FROM catalog_datasets ORDER BY table_name"
        ).fetchall()

        if not datasets:
            return {"scanned": False, "tables": []}

        # Maps de table_name -> [{id, name}, ...] para enriquecer cada tabela
        # com seus DataMarts e DiamondLayers em uma unica query cada (evita N+1).
        dm_map: dict[str, list] = {}
        if _table_exists(conn, "datamart_tables") and _table_exists(conn, "datamarts"):
            for r in conn.execute(
                "SELECT dt.table_name, d.id, d.name "
                "FROM datamart_tables dt JOIN datamarts d ON d.id = dt.datamart_id "
                "ORDER BY d.name"
            ).fetchall():
                rd = dict(r)
                dm_map.setdefault(rd["table_name"], []).append(
                    {"id": rd["id"], "name": rd["name"]}
                )

        dl_map: dict[str, list] = {}
        if _table_exists(conn, "diamond_layer_tables") and _table_exists(conn, "diamond_layers"):
            for r in conn.execute(
                "SELECT dlt.table_name, l.id, l.name "
                "FROM diamond_layer_tables dlt JOIN diamond_layers l ON l.id = dlt.layer_id "
                "ORDER BY l.name"
            ).fetchall():
                rd = dict(r)
                dl_map.setdefault(rd["table_name"], []).append(
                    {"id": rd["id"], "name": rd["name"]}
                )

        tables = []
        for ds in datasets:
            d = dict(ds)
            # Get column count
            cols = conn.execute(
                "SELECT * FROM catalog_columns WHERE table_name=? ORDER BY column_name",
                (d["table_name"],),
            ).fetchall()
            d["columns"] = [dict(c) for c in cols]
            d["col_count"] = len(cols)

            # Parse JSON fields
            for field in ("quality_detail", "entities", "extras"):
                try:
                    d[field] = json.loads(d.get(field) or "{}")
                except (json.JSONDecodeError, TypeError):
                    d[field] = {}

            # Parse column profile/pii data
            for col in d["columns"]:
                for field in ("profile_data", "pii_data"):
                    try:
                        col[field] = json.loads(col.get(field) or "{}")
                    except (json.JSONDecodeError, TypeError):
                        col[field] = {}

            d["datamarts"] = dm_map.get(d["table_name"], [])
            d["diamond_layers"] = dl_map.get(d["table_name"], [])

            tables.append(d)

        # Get relationships
        if _table_exists(conn, "catalog_relationships"):
            rels = conn.execute("SELECT * FROM catalog_relationships ORDER BY confidence DESC").fetchall()
            relationships = [dict(r) for r in rels]
        else:
            relationships = []

        # Global stats
        total_cols = sum(t["col_count"] for t in tables)
        total_rows = sum(t.get("row_count", 0) or 0 for t in tables)
        avg_quality = round(np.mean([
            t.get("quality_score", 0) or 0 for t in tables
        ]), 1) if tables else 0
        sensitive_cols = sum(
            1 for t in tables for c in t["columns"]
            if c.get("pii_data", {}).get("is_sensitive")
        )
        domains = Counter(t.get("domain", "Geral") for t in tables)

        return {
            "scanned": True,
            "stats": {
                "total_tables": len(tables),
                "total_columns": total_cols,
                "total_rows": total_rows,
                "avg_quality": avg_quality,
                "sensitive_columns": sensitive_cols,
                "total_relationships": len(relationships),
                "domains": dict(domains.most_common()),
            },
            "tables": tables,
            "relationships": relationships,
        }

    finally:
        conn.close()


def search_catalog(query: str) -> list:
    """Search catalog by name, description, or content."""
    from app.core.db_engine import table_exists as _table_exists
    conn = get_sync_connection()
    try:
        results = []
        if not _table_exists(conn, "catalog_datasets"):
            return results
        query_lower = f"%{query.lower()}%"

        # Search datasets
        datasets = conn.execute(
            """SELECT table_name, description, domain FROM catalog_datasets
               WHERE LOWER(table_name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(domain) LIKE ?""",
            (query_lower, query_lower, query_lower),
        ).fetchall()
        for d in datasets:
            results.append({"type": "table", "name": d[0], "description": d[1], "domain": d[2]})

        # Search columns
        if _table_exists(conn, "catalog_columns"):
            columns = conn.execute(
                """SELECT table_name, column_name, description, semantic_type FROM catalog_columns
                   WHERE LOWER(column_name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(semantic_type) LIKE ?""",
                (query_lower, query_lower, query_lower),
            ).fetchall()
            for c in columns:
                results.append({"type": "column", "table": c[0], "name": c[1], "description": c[2], "semantic_type": c[3]})

        return results
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Agent Enrichment — inject catalog business context into NL→SQL prompt
# ---------------------------------------------------------------------------

def _truncate(s: str, n: int) -> str:
    """Trim a string to ``n`` chars with an ellipsis, collapsing surrounding space."""
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def get_catalog_context(table_names: list[str] | None = None) -> dict:
    """Focused catalog read used to enrich the NL→SQL agent context.

    Returns ``{table_name: {description, domain, columns, suggested_joins,
    suggested_kpis}}`` ONLY for tables that have an entry in ``catalog_datasets``.
    Tables without a catalog entry are simply omitted — the caller falls back to
    the raw structural schema for those.

    ``table_names=None`` → all cataloged tables (root without DataMart filter).
    Returns ``{}`` when the catalog has not been built yet, so callers can treat
    an empty result as "no enrichment, behave exactly as before".
    """
    from app.core.db_engine import table_exists as _table_exists
    conn = get_sync_connection()
    try:
        if not _table_exists(conn, "catalog_datasets"):
            return {}

        if table_names:
            names = list({n for n in table_names if n})
            if not names:
                return {}
            ph = ",".join(["?"] * len(names))
            ds_rows = conn.execute(
                f"SELECT table_name, description, domain, quality_score, extras "
                f"FROM catalog_datasets WHERE table_name IN ({ph})",
                tuple(names),
            ).fetchall()
        else:
            ds_rows = conn.execute(
                "SELECT table_name, description, domain, quality_score, extras "
                "FROM catalog_datasets"
            ).fetchall()

        if not ds_rows:
            return {}

        out: dict = {}
        for r in ds_rows:
            d = dict(r)
            try:
                extras = json.loads(d.get("extras") or "{}")
            except (ValueError, TypeError):
                extras = {}
            if not isinstance(extras, dict):
                extras = {}
            out[d["table_name"]] = {
                "description": (d.get("description") or "").strip(),
                "domain": (d.get("domain") or "").strip(),
                "quality_score": d.get("quality_score"),
                "columns": [],
                "suggested_joins": extras.get("suggested_joins") or [],
                "suggested_kpis": extras.get("suggested_kpis") or [],
            }

        # Columns for the cataloged tables (single IN query — no N+1).
        if _table_exists(conn, "catalog_columns") and out:
            names = list(out.keys())
            ph = ",".join(["?"] * len(names))
            col_rows = conn.execute(
                f"SELECT table_name, column_name, semantic_type, description, pii_data, profile_data "
                f"FROM catalog_columns WHERE table_name IN ({ph}) "
                f"ORDER BY table_name, column_name",
                tuple(names),
            ).fetchall()
            for c in col_rows:
                cd = dict(c)
                t = cd["table_name"]
                if t not in out:
                    continue
                try:
                    pii = json.loads(cd.get("pii_data") or "{}")
                except (ValueError, TypeError):
                    pii = {}
                try:
                    prof = json.loads(cd.get("profile_data") or "{}")
                except (ValueError, TypeError):
                    prof = {}
                out[t]["columns"].append({
                    "name": cd["column_name"],
                    "semantic_type": (cd.get("semantic_type") or "").strip(),
                    "description": (cd.get("description") or "").strip(),
                    "pii": bool(pii.get("is_sensitive")),
                    "pii_type": (pii.get("pii_type") or "").strip(),
                    "completeness": prof.get("completeness"),
                })

        return out
    finally:
        conn.close()


def build_catalog_context_text(table_names: list[str] | None = None, max_tables: int = 25) -> str:
    """Format the catalog of the given tables as a compact Markdown block for the
    agent system prompt. Returns ``""`` when no table is cataloged — in that case
    the agent runs with the raw structural schema only (identical to legacy
    behavior). Only columns carrying business meaning (a description OR a known
    semantic type) are included, to keep the prompt lean.
    """
    ctx = get_catalog_context(table_names)
    if not ctx:
        return ""

    names = sorted(ctx.keys())
    omitted = 0
    if len(names) > max_tables:
        omitted = len(names) - max_tables
        names = names[:max_tables]

    blocks = []
    for tname in names:
        info = ctx[tname]
        lines = []
        header = f"### {tname}"
        if info.get("domain"):
            header += f" — Domínio: {info['domain']}"
        lines.append(header)
        if info.get("description"):
            lines.append(f"Descrição: {_truncate(info['description'], 280)}")

        meaningful = [
            c for c in info.get("columns", [])
            if c.get("description")
            or (c.get("semantic_type") and c["semantic_type"] != "desconhecido")
        ]
        if meaningful:
            lines.append("Colunas (significado de negócio):")
            for c in meaningful:
                sem = (
                    f" [{c['semantic_type']}]"
                    if c.get("semantic_type") and c["semantic_type"] != "desconhecido"
                    else ""
                )
                pii = " ⚠PII" if c.get("pii") else ""
                desc = f": {_truncate(c['description'], 160)}" if c.get("description") else ""
                lines.append(f"  - {c['name']}{sem}{pii}{desc}")

        joins = info.get("suggested_joins") or []
        if joins:
            lines.append("Joins sugeridos:")
            for j in joins:
                lines.append(f"  - {_truncate(str(j), 240)}")

        kpis = info.get("suggested_kpis") or []
        if kpis:
            lines.append("KPIs sugeridos: " + "; ".join(_truncate(str(k), 120) for k in kpis))

        blocks.append("\n".join(lines))

    text = "\n\n".join(blocks)
    if omitted:
        text += f"\n\n_({omitted} tabela(s) catalogada(s) omitida(s) por limite de contexto.)_"
    return text


def tables_in_sql(sql: str, known_tables: list[str] | None = None) -> list[str]:
    """Return the cataloged tables referenced by a SQL string.

    Matches known/cataloged table names against the SQL text by word boundary —
    avoids a fragile SQL parser. ``known_tables=None`` → all cataloged tables.
    """
    if not sql:
        return []
    names = known_tables if known_tables is not None else list(get_catalog_context(None).keys())
    if not names:
        return []
    low = sql.lower()
    hits = []
    for n in names:
        if not n:
            continue
        if re.search(r"(?<![\w.])" + re.escape(n.lower()) + r"(?![\w])", low):
            hits.append(n)
    return hits


def build_cockpit_catalog_context(table_names: list[str]) -> str:
    """Like ``build_catalog_context_text`` but tuned for the Cockpit insights
    prompt: adds data-quality (table score + per-column completeness) and PII
    type annotations so the LLM can produce quality/LGPD caveats. Returns ``""``
    when no table is cataloged.
    """
    ctx = get_catalog_context(table_names)
    if not ctx:
        return ""
    blocks = []
    for tname in sorted(ctx.keys()):
        info = ctx[tname]
        lines = []
        header = f"### {tname}"
        if info.get("domain"):
            header += f" — Domínio: {info['domain']}"
        if info.get("quality_score") is not None:
            header += f" — Qualidade: {info['quality_score']}%"
        lines.append(header)
        if info.get("description"):
            lines.append(f"Descrição: {_truncate(info['description'], 280)}")

        cols = info.get("columns", [])
        if cols:
            lines.append("Colunas:")
            for c in cols:
                sem = (
                    f" [{c['semantic_type']}]"
                    if c.get("semantic_type") and c["semantic_type"] != "desconhecido"
                    else ""
                )
                comp = c.get("completeness")
                compflag = (
                    f" ⚠completude {int(comp)}%"
                    if isinstance(comp, (int, float)) and comp < 80
                    else ""
                )
                pii = f" ⚠PII({c['pii_type']})" if c.get("pii") else ""
                desc = f": {_truncate(c['description'], 140)}" if c.get("description") else ""
                lines.append(f"  - {c['name']}{sem}{pii}{compflag}{desc}")

        joins = info.get("suggested_joins") or []
        if joins:
            lines.append("Joins sugeridos:")
            for j in joins:
                lines.append(f"  - {_truncate(str(j), 240)}")

        kpis = info.get("suggested_kpis") or []
        if kpis:
            lines.append("KPIs canônicos: " + "; ".join(_truncate(str(k), 120) for k in kpis))

        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
