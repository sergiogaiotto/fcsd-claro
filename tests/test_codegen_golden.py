"""Golden-tests do gerador TDIA-CodeGen M2.3 — padrões tipados (schema-aware).

Determinístico e SEM banco: injeta um schema sintético fixo e renderiza cada
(técnica × padrão) compatível direto pelos templates de fábrica (`_compose`),
conferindo:

  - o resultado é Python VÁLIDO (`ast.parse`);
  - os MARCADORES tipados esperados aparecem (classe, imports condicionais,
    StructType, dtypes, literais de nomes "difíceis" via `pyrepr`…);
  - DEGRADAÇÃO: com schema vazio (tabela inexistente) ainda gera Python válido.

Roda em qualquer ambiente com jinja2 (host ou container), sem pytest::

    python tests/test_codegen_golden.py

e também é descoberto por `pytest` (funções `test_*`).
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.codegen_pycodegen import _compose, _SEED_TECHNIQUES, _SEED_PATTERNS

# Schema sintético cobrindo o leque de tipos (incl. os que exigem import
# condicional) + nomes de coluna "difíceis" p/ exercitar o `pyrepr`.
FIXED_SCHEMA = [
    {"name": "id",        "ident": "id",        "py": "int",               "pd": "Int64",          "spark": "IntegerType"},
    {"name": "nome",      "ident": "nome",      "py": "str",               "pd": "string",         "spark": "StringType"},
    {"name": "valor",     "ident": "valor",     "py": "decimal.Decimal",   "pd": "object",         "spark": "DecimalType"},
    {"name": "criado_em", "ident": "criado_em", "py": "datetime.datetime", "pd": "datetime64[ns]", "spark": "TimestampType"},
    {"name": "data_ref",  "ident": "data_ref",  "py": "datetime.date",     "pd": "object",         "spark": "DateType"},
    {"name": "ativo",     "ident": "ativo",     "py": "bool",              "pd": "boolean",        "spark": "BooleanType"},
    {"name": "score",     "ident": "score",     "py": "float",             "pd": "float64",        "spark": "DoubleType"},
    {"name": "tot$al",    "ident": "tot_al",    "py": "int",               "pd": "Int64",          "spark": "IntegerType"},
    {"name": 'qt"d',      "ident": "qt_d",      "py": "int",               "pd": "Int64",          "spark": "IntegerType"},
]

SQL = "SELECT * FROM vendas WHERE valor > 0"


def _tech(key):
    return next(t for t in _SEED_TECHNIQUES if t["key"] == key)


def _pat(key):
    return next(p for p in _SEED_PATTERNS if p["key"] == key)


def _render(tech_key, pat_key, schema):
    """Compõe e garante que é Python válido — devolve o código gerado."""
    code = _compose(_tech(tech_key), _pat(pat_key), schema, SQL, {})
    ast.parse(code)  # levanta SyntaxError se o código gerado for inválido
    assert "TODO" not in code  # nada de placeholder esquecido nos templates
    return code


# --- baseline (não-tipado, M2.0) ------------------------------------------

def test_script_baseline():
    code = _render("pandas", "script", FIXED_SCHEMA)
    assert "def main():" in code
    assert 'SQL = """' in code
    assert "SELECT * FROM vendas" in code


# --- dataclass (compat pandas; usa c.py) ----------------------------------

def test_dataclass_typed():
    code = _render("pandas", "dataclass", FIXED_SCHEMA)
    assert "@dataclass" in code
    assert "class ResultRow:" in code
    # GOTCHA: imports condicionais p/ os tipos dotted.
    assert "import decimal" in code
    assert "import datetime" in code
    # campos tipados a partir do schema.
    assert "valor: decimal.Decimal" in code
    assert "criado_em: datetime.datetime" in code
    assert "data_ref: datetime.date" in code
    assert "id: int" in code
    assert 'to_dict("records")' in code


def test_dataclass_degraded():
    code = _render("pandas", "dataclass", [])
    assert "class ResultRow:" in code
    assert "pass" in code                  # corpo da classe não fica vazio
    assert "import decimal" not in code    # sem schema → sem import condicional
    assert "import datetime" not in code


# --- pydantic (compat pandas; usa c.py) -----------------------------------

def test_pydantic_typed():
    code = _render("pandas", "pydantic", FIXED_SCHEMA)
    assert "from pydantic import BaseModel" in code
    assert "class ResultRow(BaseModel):" in code
    assert "class ResultRepository:" in code
    assert "def fetch(self) -> list[ResultRow]:" in code
    assert "import decimal" in code
    assert "import datetime" in code
    assert "valor: decimal.Decimal" in code


def test_pydantic_degraded():
    code = _render("pandas", "pydantic", [])
    assert "class ResultRow(BaseModel):" in code
    assert "model_config" in code          # aceita campos livres sem schema
    assert "class ResultRepository:" in code


# --- typed_dataframe (compat pandas; usa c.pd + pyrepr) -------------------

def test_typed_dataframe_typed():
    code = _render("pandas", "typed_dataframe", FIXED_SCHEMA)
    assert "DTYPES = {" in code
    assert ".astype(DTYPES" in code
    assert "'Int64'" in code               # dtype pandas vindo do schema
    assert "'datetime64[ns]'" in code
    assert "'tot$al'" in code              # nome difícil via pyrepr
    assert "'qt\"d'" in code               # nome com aspas via pyrepr


def test_typed_dataframe_degraded():
    code = _render("pandas", "typed_dataframe", [])
    assert "DTYPES = {}" in code
    assert ".astype(" not in code          # sem schema → não força dtypes


# --- spark_schema (compat pyspark; usa c.spark + c.name + pyrepr) ---------

def test_spark_schema_typed():
    code = _render("pyspark", "spark_schema", FIXED_SCHEMA)
    assert "from pyspark.sql.types import StructType, StructField," in code
    assert "RESULT_SCHEMA = StructType([" in code
    assert "StructField('id', IntegerType(), True)" in code
    assert "StructField('valor', DecimalType(), True)" in code
    assert "StructField('tot$al', IntegerType(), True)" in code   # pyrepr
    assert "result.printSchema()" in code


def test_spark_schema_degraded():
    code = _render("pyspark", "spark_schema", [])
    assert "RESULT_SCHEMA = StructType([])" in code
    # sem schema o import não lista tipos concretos.
    assert "from pyspark.sql.types import StructType, StructField\n" in code


# --- matriz de compatibilidade declarada ----------------------------------

def test_typed_patterns_declare_compat():
    """Padrões tipados de linha são pandas-only; o StructType é pyspark-only —
    é isso que torna a suposição de formato de `result` segura."""
    compat = {p["key"]: p["compatible"] for p in _SEED_PATTERNS}
    assert compat["dataclass"] == ["pandas"]
    assert compat["pydantic"] == ["pandas"]
    assert compat["typed_dataframe"] == ["pandas"]
    assert compat["spark_schema"] == ["pyspark"]
    assert compat["script"] == "*"


def _run():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:  # noqa: BLE001 - golden runner reporta tudo
            failed.append(name)
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} golden-tests passaram.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
