from pydantic import BaseModel, Field
from typing import Optional


class ConversationTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$", description="Papel do turno: user ou assistant")
    content: str = Field("", description="Texto da pergunta ou da explicação do assistente")
    sql: Optional[str] = Field(None, description="SQL gerado pelo assistente naquele turno (apenas para role=assistant)")


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Pergunta em linguagem natural")
    analysis_type_id: Optional[int] = Field(None, description="ID do tipo de análise")
    conversation_context: Optional[str] = Field(None, description="[deprecated] Contexto da conversa em texto. Prefira conversation_history.")
    conversation_history: Optional[list[ConversationTurn]] = Field(
        None,
        description="Histórico estruturado de turnos anteriores (multi-turno real). Sobrepõe conversation_context se ambos vierem.",
    )
    result_limit: Optional[int] = Field(20, ge=0, le=1000, description="Limite de registros retornados (0 = sem limite)")
    datamart_ids: Optional[list[int]] = Field(None, description="IDs dos DataMarts para filtrar tabelas")
    diamond_layer_ids: Optional[list[int]] = Field(None, description="IDs das DiamondLayers para filtrar tabelas")
    skill_ids: Optional[list[int]] = Field(None, description="IDs das skills selecionadas manualmente pelo usuário")
    saved_sql: Optional[str] = Field(None, description="SQL salvo de pergunta anterior — executa direto sem passar pelo agente")


class QueryResponse(BaseModel):
    question: str
    sql_generated: str
    explanation: str
    data: dict
    insights: Optional[str] = None


class ExecHeroRequest(BaseModel):
    """Análise Executiva (P0) — uma pergunta de negócio → número-herói auditável."""
    question: str = Field(..., min_length=3, description="Pergunta de negócio em linguagem natural")
    datamart_ids: Optional[list[int]] = Field(None, description="IDs dos DataMarts para focar a análise")
    diamond_layer_ids: Optional[list[int]] = Field(None, description="IDs das DiamondLayers para focar a análise")


class ExecDeckRequest(BaseModel):
    """Análise Executiva (P1) — uma pergunta de negócio → deck executivo completo."""
    question: str = Field(..., min_length=3, description="Pergunta de negócio em linguagem natural")
    datamart_ids: Optional[list[int]] = Field(None, description="IDs dos DataMarts para focar a análise")
    diamond_layer_ids: Optional[list[int]] = Field(None, description="IDs das DiamondLayers para focar a análise")
    n_insights: Optional[int] = Field(4, ge=2, le=5, description="Quantidade de slides de insight (2 a 5)")


class ExecDeckSaveRequest(BaseModel):
    """Salva um deck executivo gerado (Deck vivo)."""
    name: str = Field(..., min_length=2, max_length=140)
    question: str = Field("", description="Pergunta de negócio que gerou o deck")
    datamart_ids: Optional[list[int]] = None
    diamond_layer_ids: Optional[list[int]] = None
    deck_spec: dict = Field(..., description="Deck completo gerado por /exec/deck")


class ExecDeckUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=140)
    deck_spec: Optional[dict] = None


class ExecDeckParamsRequest(BaseModel):
    """Analisa um deck_spec e devolve os 'botões' (janelas + dimensões de recorte)."""
    deck_spec: dict = Field(..., description="Deck a analisar")
    datamart_ids: Optional[list[int]] = None
    diamond_layer_ids: Optional[list[int]] = None


class ExecSegmentFilter(BaseModel):
    column: str = Field(..., max_length=120)
    values: list[str] = Field(default_factory=list)


class ExecReplayRequest(BaseModel):
    """Reexecuta determinístico um deck com recorte de segmento + janela."""
    deck_spec: dict = Field(..., description="Deck a reexecutar")
    segment_filters: list[ExecSegmentFilter] = Field(default_factory=list)
    window: Optional[str] = Field(None, pattern="^(3m|6m|12m)$")
    datamart_ids: Optional[list[int]] = None
    diamond_layer_ids: Optional[list[int]] = None


class ExecNarrateRequest(BaseModel):
    """Re-narra UM slide a partir dos números atuais (não toca SQL/herói)."""
    slide: dict = Field(..., description="Slide insight com hero/chart_data atuais")


class PlaybookCreate(BaseModel):
    """Cria um playbook (jogada curada) — coleção de perguntas de negócio."""
    title: str = Field(..., min_length=2, max_length=140)
    category: str = Field("", max_length=60)
    description: str = Field("", max_length=400)
    emoji: str = Field("📊", max_length=8)
    questions: list[str] = Field(default_factory=list)
    datamart_ids: Optional[list[int]] = None
    diamond_layer_ids: Optional[list[int]] = None
    visibility: str = Field("private", pattern="^(private|shared)$")


class PlaybookUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=140)
    category: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = Field(None, max_length=400)
    emoji: Optional[str] = Field(None, max_length=8)
    questions: Optional[list[str]] = None
    datamart_ids: Optional[list[int]] = None
    diamond_layer_ids: Optional[list[int]] = None
    visibility: Optional[str] = Field(None, pattern="^(private|shared)$")


class PlaybookCopyRequest(BaseModel):
    """Admin copia um playbook para um ou mais usuários (cópias privadas)."""
    target_user_ids: list[int] = Field(..., min_length=1)


class FailureCreate(BaseModel):
    """Falha originada no front (erro de conexão/JS) — registro para troubleshooting."""
    source: str = Field("frontend", max_length=40)
    question: str = Field("", max_length=2000)
    sql_generated: str = Field("", max_length=8000)
    error_message: str = Field("", max_length=4000)
    error_type: str = Field("", max_length=120)
    response_text: str = Field("", max_length=8000)
    snapshot_html: str = Field("", max_length=300000)
    screenshot: str = Field("", max_length=1400000)
    model: str = Field("", max_length=120)


class FailureArtifact(BaseModel):
    """Print (data URL JPEG) e snapshot HTML do bloco da resposta."""
    screenshot: str = ""
    snapshot_html: str = ""


class FailureStatusUpdate(BaseModel):
    status: str = Field("open", pattern="^(open|resolved)$")


class AnalysisTypeCreate(BaseModel):
    name: str = Field(..., min_length=2)
    system_prompt: str = ""
    guardrails_input: str = ""
    guardrails_output: str = ""


class AnalysisTypeUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    guardrails_input: Optional[str] = None
    guardrails_output: Optional[str] = None


class EmailRequest(BaseModel):
    to_email: str
    subject: str
    body_html: str
    excel_data: Optional[dict] = None


class ApiKeyCreate(BaseModel):
    label: str = Field(..., min_length=2)


class ApiQueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    analysis_type_id: Optional[int] = None


class GallerySaveRequest(BaseModel):
    title: str = Field(..., min_length=2)
    description: str = ""
    query_data: dict = Field(..., description="Dados da consulta {columns, rows}")
    chart_config: Optional[dict] = Field(None, description="Config do gráfico")
    page_html: str = Field("", description="HTML completo da página PyGWalker")
    local_storage: Optional[dict] = Field(None, description="Snapshot do localStorage do PyGWalker")
    category: str = Field("analysis", description="Categoria: 'analysis' (padrão) ou 'cockpit'")


class PredictionRequest(BaseModel):
    query_data: dict = Field(..., description="Dados da consulta {columns, rows}")
    target: str = Field("", description="Coluna alvo (Y) — vazio para clustering/pca")
    features: list[str] = Field(..., min_length=1, description="Colunas features (X)")
    model_type: str = Field(..., pattern="^(linear|logistic|clustering|automl|pca)$", description="Tipo de modelo")
    n_clusters: int = Field(0, description="Qtd clusters para K-Means (0 = automático)")
    task_type: str = Field("auto", pattern="^(auto|regression|classification)$", description="Tipo de tarefa para AutoML: auto, regression ou classification")


class CausalRequest(BaseModel):
    query_data: dict = Field(..., description="Dados da consulta {columns, rows}")
    method: str = Field(
        ...,
        pattern="^(dag|psm|mediation|synthetic_control|iv)$",
        description="Método de inferência causal",
    )
    config: dict = Field(
        default_factory=dict,
        description=(
            "Configuração específica do método:\n"
            "dag: {variables: [...], alpha: 0.05}\n"
            "psm: {treatment: col, outcome: col, covariates: [...]}\n"
            "mediation: {exposure: col, mediator: col, outcome: col, n_bootstrap: 500}\n"
            "synthetic_control: {unit_col, time_col, outcome_col, treated_unit, treatment_time}\n"
            "iv: {instrument: col, treatment: col, outcome: col, covariates: [...]}"
        ),
    )


# --- Auth ---

class LoginRequest(BaseModel):
    login: str = Field(..., min_length=2)
    password: str = Field(..., min_length=8)


class UserCreate(BaseModel):
    login: str = Field(..., min_length=2)
    password: str = Field(..., min_length=8)
    user_type: str = Field("user", pattern="^(root|superuser|admin|analista|engenheiro_dados|user)$")
    display_name: str = ""
    profile_description: str = ""
    datamart_ids: list[int] = Field(default_factory=list, description="IDs dos DataMarts atribuídos")
    diamond_layer_ids: list[int] = Field(default_factory=list, description="IDs das DiamondLayers atribuídas")


class UserUpdate(BaseModel):
    login: Optional[str] = None
    user_type: Optional[str] = Field(None, pattern="^(root|superuser|admin|analista|engenheiro_dados|user)$")
    display_name: Optional[str] = None
    profile_description: Optional[str] = None
    is_active: Optional[int] = None
    datamart_ids: Optional[list[int]] = None
    diamond_layer_ids: Optional[list[int]] = None


class PasswordChange(BaseModel):
    new_password: str = Field(..., min_length=8)


# --- Skills ---

class SkillCreate(BaseModel):
    name: str = Field(..., min_length=2)
    description: str = ""
    content: str = ""
    triggers: list[str] = Field(default_factory=list, description="Palavras-chave para auto-detecção da skill")


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[int] = None
    triggers: Optional[list[str]] = None


# --- DataMarts ---

class DataMartCreate(BaseModel):
    name: str = Field(..., min_length=2)
    description: str = ""


class DataMartUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class DataMartAssignTable(BaseModel):
    table_name: str = Field(..., min_length=1)


# --- DiamondLayers ---

class DiamondLayerCreate(BaseModel):
    name: str = Field(..., min_length=2)
    description: str = ""


class DiamondLayerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class DiamondLayerAssignTable(BaseModel):
    table_name: str = Field(..., min_length=1)


class DiamondLayerSetUsers(BaseModel):
    user_ids: list[int] = Field(default_factory=list)


# --- System Prompts (SKILL.md / AGENTS.md — root only) ---

class SystemPromptUpdate(BaseModel):
    content: str = ""


class SystemPromptCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=60, description="Nome do skill (slug)")
    content: str = ""


# --- Shares (compartilhamento interno) ---

# --- Reportes (módulo executivo banded) ---

class ReportColumn(BaseModel):
    key: str = Field(..., description="Nome da coluna no resultado SQL")
    label: str = Field("", description="Cabeçalho exibido na tabela")
    fmt: str = Field("", description="Formatador: text|number_0|number_2|number_k|currency_brl|date_br|percent_2|percent_0|percent_raw|percent_raw_sign")
    align: str = Field("", pattern="^(|left|center|right)$", description="Alinhamento da coluna")
    color_rule: str = Field("", pattern="^(|negative_red|sign_color)$", description="Regra de cor condicional")

class ReportAggregation(BaseModel):
    column: str = Field(..., description="Coluna numérica a agregar")
    fn: str = Field(..., pattern="^(sum|avg|count|min|max)$")
    label: str = Field("", description="Rótulo opcional para placeholders e exibição")

class ReportGroup(BaseModel):
    column: str = Field(..., description="Coluna pela qual agrupar")
    sort: str = Field("asc", pattern="^(asc|desc)$")
    header_template: str = Field("", description="Markdown — exibido antes do bloco de detalhe")
    footer_template: str = Field("", description="Markdown — exibido após o bloco. Aceita placeholders.")
    aggregations: list[ReportAggregation] = Field(default_factory=list)

class ReportLayout(BaseModel):
    report_header: str = Field("", description="Markdown no topo")
    report_footer: str = Field("", description="Markdown no fim")
    page_header: str = Field("", description="Aparece somente na impressão (CSS @page)")
    page_footer: str = Field("", description="Aparece somente na impressão")
    detail_columns: list[ReportColumn] = Field(default_factory=list, description="Colunas do detalhe")
    group: Optional[ReportGroup] = Field(None, description="Quebra principal (nível 1)")
    sub_group: Optional[ReportGroup] = Field(None, description="Sub-quebra (nível 2)")
    grand_aggregations: list[ReportAggregation] = Field(default_factory=list)
    show_detail: bool = Field(True, description="Quando False, esconde detail e mostra só headers/footers")

class ReportCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str = Field("", max_length=500)
    question: str = Field(..., min_length=3, description="Pergunta NL que alimenta o report")
    sql_generated: str = Field("", description="SQL congelado (preenchido na publicação)")
    datamart_ids: list[int] = Field(default_factory=list)
    diamond_layer_ids: list[int] = Field(default_factory=list)
    definition: ReportLayout = Field(default_factory=ReportLayout)

class ReportUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    description: Optional[str] = None
    question: Optional[str] = None
    sql_generated: Optional[str] = None
    datamart_ids: Optional[list[int]] = None
    diamond_layer_ids: Optional[list[int]] = None
    definition: Optional[ReportLayout] = None

class ReportPublish(BaseModel):
    sql_generated: str = Field(..., description="SQL definitivo capturado pelo designer")

class ShareCreate(BaseModel):
    recipient_id: int = Field(..., description="ID do usuário destinatário")
    question: str = Field(..., min_length=1, description="Pergunta original em linguagem natural")
    sql_generated: str = Field("", description="SQL gerado pelo agente para a consulta compartilhada")
    datamart_ids: list[int] = Field(
        default_factory=list,
        description="IDs dos DataMarts referenciados pela consulta — recipient precisa ter acesso a todos",
    )
    label: str = Field("", description="Rótulo curto exibido na inbox do destinatário")
    message: str = Field("", description="Mensagem opcional do remetente")

# --- Chart submenu ---

class ChartRequest(BaseModel):
    chart_type: str = Field(..., pattern="^(auto|bar|line|scatter|area|pie|doughnut|radar|polarArea)$")
    query_data: dict = Field(..., description="Dados da consulta {columns, rows}")

# --- Saved Questions ---

class SavedQuestionCreate(BaseModel):
    question: str = Field(..., min_length=3)
    label: str = Field("", description="Rótulo opcional para a pergunta")
    sql_generated: str = Field("", description="SQL gerado pelo agente para reuso futuro")

class SavedQuestionUpdate(BaseModel):
    label: str = Field("", description="Novo rótulo")

# --- Saved Visions ---

class VisionCreate(BaseModel):
    question: str = Field(..., min_length=3)
    sql_generated: str = Field("", description="SQL gerado pelo agente")
    label: str = Field("", description="Rótulo opcional")

class VisionUpdate(BaseModel):
    label: str = Field("", description="Novo rótulo")
    question: Optional[str] = Field(None, description="Nova pergunta (None = não altera)")

# --- Cockpit ---

class CockpitTileCreate(BaseModel):
    vision_id: int
    chart_type: str = Field("bar", pattern="^(bar|line|area|pie|doughnut|scatter|radar|polarArea)$")
    x_field: str = ""
    y_field: str = ""
    agg: str = Field("sum", pattern="^(sum|mean|count|none)$")

class CockpitTileUpdate(BaseModel):
    chart_type: Optional[str] = Field(None, pattern="^(bar|line|area|pie|doughnut|scatter|radar|polarArea)$")
    x_field: Optional[str] = None
    y_field: Optional[str] = None
    agg: Optional[str] = Field(None, pattern="^(sum|mean|count|none)$")

class CockpitReorder(BaseModel):
    tile_ids: list[int]

class DataProductCreate(BaseModel):
    name: str = Field(..., min_length=2)
    display_name: str = ""
    version: str = Field("1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    status: str = Field("draft", pattern="^(draft|active|deprecated|retired)$")
    domain: str = ""
    purpose: str = ""
    business_value: str = ""
    consumers: list = Field(default_factory=list)
    owner_team: str = ""
    owner_email: str = ""
    owner_role: str = "data product owner"
    classification: str = Field("internal", pattern="^(public|internal|restricted)$")
    compliance: list = Field(default_factory=list)
    tags: dict = Field(default_factory=dict)
    artifacts: list = Field(default_factory=list)
    input_ports: list = Field(default_factory=list)
    output_ports: list = Field(default_factory=list)
    quality_rules: list = Field(default_factory=list)
    sla_freshness: str = ""
    sla_availability: str = ""
    value_layer: str = Field("refined", pattern="^(raw|refined|insight)$")
    consumption_type: str = Field("analytical", pattern="^(analytical|operational|ml_ai)$")
 
 
class DataProductUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = None
    domain: Optional[str] = None
    purpose: Optional[str] = None
    business_value: Optional[str] = None
    consumers: Optional[list] = None
    owner_team: Optional[str] = None
    owner_email: Optional[str] = None
    owner_role: Optional[str] = None
    classification: Optional[str] = None
    compliance: Optional[list] = None
    tags: Optional[dict] = None
    artifacts: Optional[list] = None
    input_ports: Optional[list] = None
    output_ports: Optional[list] = None
    quality_rules: Optional[list] = None
    sla_freshness: Optional[str] = None
    sla_availability: Optional[str] = None
    value_layer: Optional[str] = None
    consumption_type: Optional[str] = None
 
 
class DataProductStatusTransition(BaseModel):
    new_status: str = Field(..., pattern="^(draft|active|deprecated|retired)$")
