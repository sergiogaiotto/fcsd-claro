import json
import re
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Header, Query, Request, Response, Depends
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
import io
import base64 as _base64_mod
# from fastapi import APIRouter  # já existe
from datetime import date as _date
from datetime import date as _date

from app.models.schemas import (
    QueryRequest, AnalysisTypeCreate, AnalysisTypeUpdate,
    EmailRequest, ApiKeyCreate, ApiQueryRequest, GallerySaveRequest, PredictionRequest,
    CausalRequest,
    LoginRequest, UserCreate, UserUpdate, PasswordChange,
    SkillCreate, SkillUpdate,
    DataMartCreate, DataMartUpdate, DataMartAssignTable, ChartRequest,
    DiamondLayerCreate, DiamondLayerUpdate, DiamondLayerAssignTable, DiamondLayerSetUsers,
    SystemPromptUpdate, SystemPromptCreate,
    SavedQuestionCreate, SavedQuestionUpdate,
    VisionCreate, VisionUpdate,
    ShareCreate,
    ReportCreate, ReportUpdate, ReportPublish,
)
from app.core.database import (
    get_sync_connection, get_all_tables, execute_readonly_sql,
    get_all_skills, get_active_skills, get_skill_by_id,
    create_skill as db_create_skill, update_skill as db_update_skill, delete_skill as db_delete_skill,
    get_all_datamarts, get_datamart_by_id, get_datamart_by_name,
    create_datamart as db_create_datamart, update_datamart as db_update_datamart,
    delete_datamart as db_delete_datamart,
    assign_table_to_datamart, remove_table_from_datamart,
    get_user_datamarts, set_user_datamarts, get_tables_for_datamarts,
    get_users_with_access_to_datamarts,
    get_all_diamond_layers, get_diamond_layer_by_id, get_diamond_layer_by_name,
    create_diamond_layer as db_create_diamond_layer,
    update_diamond_layer as db_update_diamond_layer,
    delete_diamond_layer as db_delete_diamond_layer,
    assign_table_to_diamond_layer, remove_table_from_diamond_layer,
    get_user_diamond_layers, set_user_diamond_layers,
    get_tables_for_diamond_layers,
    get_users_with_access_to_diamond_layers,
    get_users_with_diamond_layer, set_diamond_layer_users,
    create_shared_result, list_incoming_shares, get_shared_result,
    mark_shared_result_read, delete_shared_result,
    create_report, update_report, get_report, list_reports,
    list_published_reports, delete_report,
    get_saved_questions, create_saved_question,
    delete_saved_question, update_saved_question_label,
    get_all_saved_questions_with_user, get_saved_questions_with_user,
    import_saved_questions,
    INTERNAL_TABLES,
    get_visions, get_all_visions_with_user, get_visions_with_user,
    create_vision, delete_vision, update_vision_label, update_vision_meta,
    import_visions as import_visions_db,
    set_favorite_question, unset_favorite_question, get_favorite_question,
)
from app.core.security import (
    validate_api_key, create_api_key,
    authenticate_user, create_session, validate_session, destroy_session,
    get_user_count, create_user, list_users, get_user_by_id, update_user,
    change_password, delete_user,
    is_admin, is_root, hash_password,
)
from app.core.config import settings
from app.services.excel_service import import_excel
from app.services.agent_service import run_query, reset_agent
from app.services.email_service import build_eml, export_to_excel_bytes
from app.services.viz_service import (
    generate_explore_html, generate_chart_html, generate_gallery_view_html,
    generate_typed_chart_html, get_chart_options_for_data,
    ask_visualization_ai,
)
from app.services.analytics_service import generate_analytics_html, run_prediction, run_causal_analysis
from app.services.catalog_service import (
    run_catalog_scan, get_catalog_summary, enrich_table_with_llm, search_catalog,
    tables_in_sql, build_cockpit_catalog_context,
)
from app.core.database import (
    get_cockpit_tiles, add_cockpit_tile, update_cockpit_tile,
    delete_cockpit_tile, reorder_cockpit_tiles,
)
from app.models.schemas import (
    CockpitTileCreate, CockpitTileUpdate, CockpitReorder,
)
from app.core.database import (
    get_all_json_sources, get_json_source_by_id,
    create_json_source as db_create_json_source,
    update_json_source as db_update_json_source,
    delete_json_source as db_delete_json_source,
)
from app.services.json_import_service import (
    fetch_and_import_json, preview_json_url,
    resolve_url, format_date,
) 
from app.core.database import (
    get_all_data_products, get_data_product_by_id,
    create_data_product as db_create_data_product,
    update_data_product as db_update_data_product,
    delete_data_product as db_delete_data_product,
    transition_data_product_status, validate_data_product,
)
from app.models.schemas import (
    DataProductCreate, DataProductUpdate,
    DataProductStatusTransition,
)

router = APIRouter(prefix="/api")

COOKIE_NAME = "qi_session"
MAX_UPLOAD_SIZE = 20 * 1024 * 1024
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]+$")

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def get_current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    user = validate_session(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return user


async def require_root(user: dict = Depends(get_current_user)) -> dict:
    if not is_root(user):
        raise HTTPException(status_code=403, detail="Acesso restrito ao Root")
    return user

async def require_upload_access(user: dict = Depends(get_current_user)) -> dict:
    """Permite admin OU analista."""
    from app.core.security import can_upload
    if not can_upload(user):
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores e analistas")
    return user


async def require_codegen(user: dict = Depends(get_current_user)) -> dict:
    """Acesso ao módulo TDIA-CodeGen: Root, Admin/Superuser e Engenheiro de Dados."""
    from app.core.security import can_codegen
    if not can_codegen(user):
        raise HTTPException(status_code=403, detail="Acesso restrito ao TDIA-CodeGen")
    return user

# ---------------------------------------------------------------------------
# Auth routes (public)
# ---------------------------------------------------------------------------

@router.post("/auth/login")
async def login(req: LoginRequest, response: Response):
    user = authenticate_user(req.login, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Login ou senha inválidos")
    token = create_session(user["id"])
    response = JSONResponse(content={
        "success": True,
        "user": {
            "id": user["id"], "login": user["login"],
            "user_type": user["user_type"], "display_name": user["display_name"],
        },
    })
    response.set_cookie(
        key=COOKIE_NAME, value=token, httponly=True,
        samesite="lax", secure=settings.cookie_secure, max_age=86400,
    )
    return response


@router.post("/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        destroy_session(token)
    response = JSONResponse(content={"success": True})
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    dm_list = get_user_datamarts(user["id"]) if not is_root(user) else get_all_datamarts()
    return {
        "id": user["id"], "login": user["login"],
        "user_type": user["user_type"], "display_name": user["display_name"],
        "profile_description": user.get("profile_description", ""),
        "datamarts": dm_list,
        "is_root": is_root(user),
    }


@router.get("/auth/check")
async def auth_check(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    user = validate_session(token) if token else None
    if user is None:
        return JSONResponse(status_code=401, content={"authenticated": False, "has_users": get_user_count() > 0})
    return {"authenticated": True, "user": {
        "id": user["id"], "login": user["login"],
        "user_type": user["user_type"], "display_name": user["display_name"],
    }}


# ---------------------------------------------------------------------------
# User Management (admin only)
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users_route(user: dict = Depends(require_admin)):
    return list_users()


@router.post("/users")
async def create_user_route(req: UserCreate, user: dict = Depends(require_admin)):
    if req.user_type == "root" and not is_root(user):
        raise HTTPException(403, "Apenas Root pode criar usuários Root")
    try:
        new_user = create_user(
            login=req.login, password=req.password, user_type=req.user_type,
            display_name=req.display_name, profile_description=req.profile_description,
            datamart_ids=req.datamart_ids,
            diamond_layer_ids=req.diamond_layer_ids,
        )
        return new_user
    except Exception as e:
        raise HTTPException(400, str(e))


@router.put("/users/{user_id}")
async def update_user_route(user_id: int, req: UserUpdate, user: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    if target["user_type"] == "root" and not is_root(user):
        raise HTTPException(403, "Apenas Root pode editar outros Root")
    if req.user_type == "root" and not is_root(user):
        raise HTTPException(403, "Apenas Root pode promover a Root")
    data = req.model_dump(exclude_none=True)
    update_user(user_id, **data)
    return {"success": True}


@router.put("/users/{user_id}/password")
async def change_password_route(user_id: int, req: PasswordChange, user: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    if target["user_type"] == "root" and not is_root(user):
        raise HTTPException(403, "Apenas Root pode alterar senha de Root")
    change_password(user_id, req.new_password)
    return {"success": True}


@router.delete("/users/{user_id}")
async def delete_user_route(user_id: int, user: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    if target["user_type"] == "root":
        raise HTTPException(403, "Root não pode ser excluído")
    if target["id"] == user["id"]:
        raise HTTPException(400, "Você não pode excluir a si mesmo")
    delete_user(user_id)
    return {"success": True}


# --- User Export/Import ---

@router.get("/users/export")
async def export_users(user: dict = Depends(require_admin)):
    import pandas as pd
    users = list_users()
    dms = get_all_datamarts()
    dm_map = {d["id"]: d["name"] for d in dms}
    rows = []
    for u in users:
        dm_names = ", ".join(dm_map.get(did, str(did)) for did in u.get("datamart_ids", []))
        rows.append({
            "login": u["login"], "user_type": u["user_type"],
            "display_name": u.get("display_name", ""),
            "profile_description": u.get("profile_description", ""),
            "is_active": u.get("is_active", 1), "datamarts": dm_names,
            "created_at": u.get("created_at", ""),
        })
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=users_export.xlsx"},
    )


@router.post("/users/import")
async def import_users(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    import pandas as pd
    data = await file.read()
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    default_dm = get_datamart_by_name("default")
    default_dm_id = default_dm["id"] if default_dm else None
    created, errors = [], []
    for _, row in df.iterrows():
        login = str(row.get("login", "")).strip()
        if not login or len(login) < 2:
            errors.append(f"Login vazio ou inválido: '{login}'")
            continue
        display_name = str(row.get("display_name", login)).strip()
        profile_desc = str(row.get("profile_description", "")).strip()
        if profile_desc == "nan":
            profile_desc = ""
        dm_ids = [default_dm_id] if default_dm_id else []
        try:
            create_user(login=login, password="minhasenha01", user_type="admin",
                        display_name=display_name, profile_description=profile_desc, datamart_ids=dm_ids)
            created.append(login)
        except Exception as e:
            errors.append(f"{login}: {str(e)}")
    return {"created": created, "errors": errors, "total": len(created)}


# ---------------------------------------------------------------------------
# DataMart Management
# ---------------------------------------------------------------------------

@router.get("/datamarts")
async def list_datamarts(user: dict = Depends(get_current_user)):
    return get_all_datamarts()


@router.post("/datamarts")
async def create_datamart_route(req: DataMartCreate, user: dict = Depends(require_admin)):
    existing = get_datamart_by_name(req.name)
    if existing:
        raise HTTPException(400, f"DataMart '{req.name}' já existe")
    return db_create_datamart(req.name, req.description)


@router.put("/datamarts/{dm_id}")
async def update_datamart_route(dm_id: int, req: DataMartUpdate, user: dict = Depends(require_admin)):
    dm = get_datamart_by_id(dm_id)
    if not dm:
        raise HTTPException(404, "DataMart não encontrado")
    db_update_datamart(dm_id, **req.model_dump(exclude_none=True))
    return {"success": True}


@router.delete("/datamarts/{dm_id}")
async def delete_datamart_route(dm_id: int, user: dict = Depends(require_admin)):
    dm = get_datamart_by_id(dm_id)
    if not dm:
        raise HTTPException(404, "DataMart não encontrado")
    if dm["name"] == "default":
        raise HTTPException(400, "O DataMart 'default' não pode ser excluído")
    if not db_delete_datamart(dm_id):
        raise HTTPException(400, "Erro ao excluir DataMart")
    return {"success": True}


@router.post("/datamarts/{dm_id}/tables")
async def add_table_to_datamart(dm_id: int, req: DataMartAssignTable, user: dict = Depends(require_admin)):
    dm = get_datamart_by_id(dm_id)
    if not dm:
        raise HTTPException(404, "DataMart não encontrado")
    assign_table_to_datamart(dm_id, req.table_name)
    return {"success": True}


@router.delete("/datamarts/{dm_id}/tables/{table_name}")
async def remove_table_from_dm(dm_id: int, table_name: str, user: dict = Depends(require_admin)):
    remove_table_from_datamart(dm_id, table_name)
    return {"success": True}


@router.get("/datamarts/user")
async def get_my_datamarts(user: dict = Depends(get_current_user)):
    if is_root(user):
        return get_all_datamarts()
    return get_user_datamarts(user["id"])


@router.get("/datamarts/users-with-access")
async def get_users_with_access(
    ids: str = Query("", description="IDs dos DataMarts separados por vírgula"),
    q: str = Query("", description="Filtro por login ou display_name"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Lista usuários ativos que têm acesso a TODOS os datamart_ids fornecidos
    (acesso estrito, igualando a regra do compartilhamento). Usado pelo
    autocomplete de "Compartilhar — Por aqui"."""
    try:
        dm_ids = [int(x) for x in (ids or "").split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids inválido — use lista de inteiros separados por vírgula.")
    if not dm_ids:
        return []
    return get_users_with_access_to_datamarts(
        datamart_ids=dm_ids,
        exclude_user_id=user["id"],
        query=q,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# DiamondLayer Management (mirror of DataMart, with table ownership)
# ---------------------------------------------------------------------------

@router.get("/diamond-layers")
async def list_diamond_layers(user: dict = Depends(get_current_user)):
    return get_all_diamond_layers()


@router.get("/diamond-layers/user")
async def get_my_diamond_layers(user: dict = Depends(get_current_user)):
    if is_root(user):
        return get_all_diamond_layers()
    return get_user_diamond_layers(user["id"])


@router.get("/diamond-layers/users-with-access")
async def get_users_with_access_layers(
    ids: str = Query("", description="IDs das DiamondLayers separados por vírgula"),
    q: str = Query("", description="Filtro por login ou display_name"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    try:
        layer_ids = [int(x) for x in (ids or "").split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids inválido — use lista de inteiros separados por vírgula.")
    if not layer_ids:
        return []
    return get_users_with_access_to_diamond_layers(
        layer_ids=layer_ids,
        exclude_user_id=user["id"],
        query=q,
        limit=limit,
    )


@router.post("/diamond-layers")
async def create_diamond_layer_route(req: DiamondLayerCreate, user: dict = Depends(require_admin)):
    existing = get_diamond_layer_by_name(req.name)
    if existing:
        raise HTTPException(400, f"DiamondLayer '{req.name}' já existe")
    return db_create_diamond_layer(req.name, req.description)


@router.put("/diamond-layers/{layer_id}")
async def update_diamond_layer_route(layer_id: int, req: DiamondLayerUpdate, user: dict = Depends(require_admin)):
    layer = get_diamond_layer_by_id(layer_id)
    if not layer:
        raise HTTPException(404, "DiamondLayer não encontrada")
    db_update_diamond_layer(layer_id, **req.model_dump(exclude_none=True))
    return {"success": True}


@router.delete("/diamond-layers/{layer_id}")
async def delete_diamond_layer_route(layer_id: int, user: dict = Depends(require_admin)):
    layer = get_diamond_layer_by_id(layer_id)
    if not layer:
        raise HTTPException(404, "DiamondLayer não encontrada")
    if not db_delete_diamond_layer(layer_id):
        raise HTTPException(400, "Erro ao excluir DiamondLayer")
    return {"success": True}


@router.post("/diamond-layers/{layer_id}/tables")
async def add_table_to_diamond_layer(
    layer_id: int,
    req: DiamondLayerAssignTable,
    user: dict = Depends(require_admin),
):
    """Atribui uma tabela à DiamondLayer e renomeia a tabela física para
    ``{layer_name}_{table_name}``. O admin que faz a atribuição se torna o
    owner da tabela na camada."""
    layer = get_diamond_layer_by_id(layer_id)
    if not layer:
        raise HTTPException(404, "DiamondLayer não encontrada")

    from app.services.excel_service import sanitize_table_name
    from app.core.database import rename_user_table

    layer_part = sanitize_table_name(layer["name"])
    current_name = req.table_name
    target_name = f"{layer_part}_{current_name}"

    final_name = current_name
    if target_name != current_name:
        result = rename_user_table(current_name, target_name)
        if "error" in result:
            raise HTTPException(400, result["error"])
        final_name = target_name

    assign_table_to_diamond_layer(layer_id, final_name, owner_id=user["id"])
    return {"success": True, "table_name": final_name}


@router.delete("/diamond-layers/{layer_id}/tables/{table_name}")
async def remove_table_from_layer(layer_id: int, table_name: str, user: dict = Depends(require_admin)):
    remove_table_from_diamond_layer(layer_id, table_name)
    return {"success": True}


@router.get("/diamond-layers/{layer_id}/users")
async def list_diamond_layer_users(layer_id: int, user: dict = Depends(require_admin)):
    layer = get_diamond_layer_by_id(layer_id)
    if not layer:
        raise HTTPException(404, "DiamondLayer não encontrada")
    return get_users_with_diamond_layer(layer_id)


@router.post("/diamond-layers/{layer_id}/users")
async def set_diamond_layer_users_route(
    layer_id: int,
    req: DiamondLayerSetUsers,
    user: dict = Depends(require_admin),
):
    layer = get_diamond_layer_by_id(layer_id)
    if not layer:
        raise HTTPException(404, "DiamondLayer não encontrada")
    set_diamond_layer_users(layer_id, req.user_ids)
    return {"success": True}


# ---------------------------------------------------------------------------
# System Prompts (SKILL.md / AGENTS.md) — root only
# ---------------------------------------------------------------------------

_SYS_PROMPT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")


def _sys_prompt_sanitize_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-_")
    return s


def _sys_prompt_list() -> list[dict]:
    items: list[dict] = []
    if settings.agents_md.exists():
        items.append({
            "id": "agents",
            "label": "AGENTS.md",
            "path": "AGENTS.md",
            "kind": "agents",
            "deletable": False,
        })
    if settings.skills_dir.exists():
        for child in sorted(settings.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if skill_md.exists():
                items.append({
                    "id": f"skill:{child.name}",
                    "label": f"skills/{child.name}/SKILL.md",
                    "path": f"skills/{child.name}/SKILL.md",
                    "kind": "skill",
                    "deletable": True,
                })
    return items


def _sys_prompt_resolve(prompt_id: str):
    """Resolve a stable prompt id to the file Path on disk, or return None.
    Defends against directory-traversal by re-validating the resolved path."""
    if prompt_id == "agents":
        return settings.agents_md
    if prompt_id.startswith("skill:"):
        slug = prompt_id[len("skill:"):]
        if not _SYS_PROMPT_SLUG_RE.match(slug):
            return None
        path = settings.skills_dir / slug / "SKILL.md"
        try:
            path.resolve().relative_to(settings.skills_dir.resolve())
        except Exception:
            return None
        return path
    return None


@router.get("/system-prompts")
async def list_system_prompts(user: dict = Depends(require_root)):
    return _sys_prompt_list()


@router.get("/system-prompts/{prompt_id}")
async def get_system_prompt(prompt_id: str, user: dict = Depends(require_root)):
    path = _sys_prompt_resolve(prompt_id)
    if not path or not path.exists():
        raise HTTPException(404, "Arquivo não encontrado.")
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        raise HTTPException(500, "Erro ao ler arquivo.")
    return {"id": prompt_id, "path": str(path.relative_to(settings.project_dir)), "content": content}


@router.put("/system-prompts/{prompt_id}")
async def update_system_prompt(
    prompt_id: str,
    req: SystemPromptUpdate,
    user: dict = Depends(require_root),
):
    path = _sys_prompt_resolve(prompt_id)
    if not path:
        raise HTTPException(404, "Arquivo não encontrado.")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(req.content, encoding="utf-8")
    except Exception:
        raise HTTPException(500, "Erro ao salvar arquivo.")
    return {"success": True}


@router.post("/system-prompts")
async def create_skill_prompt(req: SystemPromptCreate, user: dict = Depends(require_root)):
    slug = _sys_prompt_sanitize_slug(req.name)
    if not slug or not _SYS_PROMPT_SLUG_RE.match(slug):
        raise HTTPException(400, "Nome inválido. Use letras minúsculas, dígitos, '-' ou '_'.")
    target_dir = settings.skills_dir / slug
    if target_dir.exists():
        raise HTTPException(400, f"Skill '{slug}' já existe.")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "SKILL.md").write_text(req.content or f"# {slug}\n", encoding="utf-8")
    except Exception:
        raise HTTPException(500, "Erro ao criar skill.")
    return {
        "id": f"skill:{slug}",
        "label": f"skills/{slug}/SKILL.md",
        "path": f"skills/{slug}/SKILL.md",
        "kind": "skill",
        "deletable": True,
    }


@router.delete("/system-prompts/{prompt_id}")
async def delete_system_prompt(prompt_id: str, user: dict = Depends(require_root)):
    if not prompt_id.startswith("skill:"):
        raise HTTPException(400, "AGENTS.md não pode ser excluído.")
    path = _sys_prompt_resolve(prompt_id)
    if not path:
        raise HTTPException(404, "Arquivo não encontrado.")
    folder = path.parent
    try:
        folder.resolve().relative_to(settings.skills_dir.resolve())
    except Exception:
        raise HTTPException(400, "Caminho inválido.")
    import shutil
    try:
        shutil.rmtree(folder, ignore_errors=False)
    except Exception:
        raise HTTPException(500, "Erro ao excluir skill.")
    return {"success": True}


# --- Shares (compartilhamento interno) ---

@router.post("/shares")
async def create_share(req: ShareCreate, user: dict = Depends(get_current_user)):
    """Cria um compartilhamento interno. Valida estritamente que o destinatário
    tem acesso a TODOS os datamart_ids da consulta."""
    if req.recipient_id == user["id"]:
        raise HTTPException(status_code=400, detail="Não é possível compartilhar consigo mesmo.")
    recipient = get_user_by_id(req.recipient_id)
    if not recipient or not recipient.get("is_active", 1):
        raise HTTPException(status_code=404, detail="Destinatário não encontrado ou inativo.")
    if req.datamart_ids:
        allowed_users = get_users_with_access_to_datamarts(
            datamart_ids=req.datamart_ids,
            limit=10000,
        )
        allowed_ids = {u["id"] for u in allowed_users}
        if req.recipient_id not in allowed_ids:
            raise HTTPException(
                status_code=403,
                detail="Destinatário não tem acesso a todos os DataMarts desta consulta.",
            )
    created = create_shared_result(
        sender_id=user["id"],
        recipient_id=req.recipient_id,
        question=req.question,
        sql_generated=req.sql_generated,
        datamart_ids=req.datamart_ids,
        label=req.label,
        message=req.message,
    )
    return {"id": created["id"], "recipient_id": created["recipient_id"]}


@router.get("/shares/incoming")
async def get_incoming_shares(
    unread: bool = Query(False, description="Se true, retorna apenas não lidos"),
    user: dict = Depends(get_current_user),
):
    return list_incoming_shares(recipient_id=user["id"], unread_only=unread)


@router.get("/shares/{share_id}")
async def get_share(share_id: int, user: dict = Depends(get_current_user)):
    share = get_shared_result(share_id)
    if not share or share["recipient_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Compartilhamento não encontrado.")
    return share


@router.post("/shares/{share_id}/read")
async def mark_share_read(share_id: int, user: dict = Depends(get_current_user)):
    ok = mark_shared_result_read(share_id, recipient_id=user["id"])
    if not ok:
        # Pode estar já lido ou não pertencer ao usuário — retorna estado idempotente
        share = get_shared_result(share_id)
        if not share or share["recipient_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Compartilhamento não encontrado.")
    return {"ok": True}


@router.delete("/shares/{share_id}")
async def delete_share(share_id: int, user: dict = Depends(get_current_user)):
    ok = delete_shared_result(share_id, recipient_id=user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Compartilhamento não encontrado.")
    return {"ok": True}


# --- Reportes (executive reports) ---

def _accessible_tables_for(
    user: dict,
    datamart_ids: list[int] | None,
    diamond_layer_ids: list[int] | None = None,
) -> list[str] | None:
    """Mirrors the /api/query authorization logic for report execution."""
    any_filter = bool(datamart_ids) or bool(diamond_layer_ids)
    if user and is_root(user):
        if any_filter:
            tables: set[str] = set()
            if datamart_ids:
                tables.update(get_tables_for_datamarts(datamart_ids))
            if diamond_layer_ids:
                tables.update(get_tables_for_diamond_layers(diamond_layer_ids))
            return sorted(tables)
        return None
    if not user:
        return None
    user_dm_ids = {d["id"] for d in get_user_datamarts(user["id"])}
    user_layer_ids = {l["id"] for l in get_user_diamond_layers(user["id"])}
    if any_filter:
        allowed_dm = [d for d in (datamart_ids or []) if d in user_dm_ids]
        allowed_layers = [l for l in (diamond_layer_ids or []) if l in user_layer_ids]
        if datamart_ids and not allowed_dm and not allowed_layers:
            raise HTTPException(
                status_code=403,
                detail="Nenhum DataMart do report está autorizado para este usuário.",
            )
        if diamond_layer_ids and not allowed_layers and not allowed_dm:
            raise HTTPException(
                status_code=403,
                detail="Nenhuma DiamondLayer do report está autorizada para este usuário.",
            )
        tables = set()
        if allowed_dm:
            tables.update(get_tables_for_datamarts(allowed_dm))
        if allowed_layers:
            tables.update(get_tables_for_diamond_layers(allowed_layers))
        return sorted(tables)
    # No filter: union of everything the user can reach
    tables = set()
    if user_dm_ids:
        tables.update(get_tables_for_datamarts(list(user_dm_ids)))
    if user_layer_ids:
        tables.update(get_tables_for_diamond_layers(list(user_layer_ids)))
    return sorted(tables) if tables else None


def _can_edit_report(user: dict, rep: dict) -> bool:
    return is_admin(user) or rep.get("owner_id") == user.get("id")


@router.get("/reports")
async def reports_list(user: dict = Depends(get_current_user)):
    """Reports the user can see: own (any status) + published from others."""
    return list_reports(owner_id=user["id"], include_published=True)


@router.get("/reports/published")
async def reports_published(user: dict = Depends(get_current_user)):
    """Published reports the user can actually run (datamart + diamond layer access)."""
    pub = list_published_reports()
    if is_admin(user):
        return pub
    user_dms = {d["id"] for d in get_user_datamarts(user["id"])}
    user_layers = {l["id"] for l in get_user_diamond_layers(user["id"])}
    out = []
    for r in pub:
        rep_dms = set(r.get("datamart_ids") or [])
        rep_layers = set(r.get("diamond_layer_ids") or [])
        # Without any binding, the report is unrestricted; otherwise the user
        # needs access to every selected datamart AND every selected layer.
        if (not rep_dms and not rep_layers) or (rep_dms.issubset(user_dms) and rep_layers.issubset(user_layers)):
            out.append(r)
    return out


@router.post("/reports")
async def reports_create(req: ReportCreate, user: dict = Depends(get_current_user)):
    rep = create_report(
        owner_id=user["id"],
        name=req.name,
        description=req.description,
        question=req.question,
        sql_generated=req.sql_generated,
        datamart_ids=req.datamart_ids,
        diamond_layer_ids=req.diamond_layer_ids,
        definition=req.definition.model_dump() if req.definition else {},
    )
    return rep


@router.get("/reports/{report_id}")
async def reports_get(report_id: int, user: dict = Depends(get_current_user)):
    rep = get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Report não encontrado.")
    if rep["status"] != "published" and not _can_edit_report(user, rep):
        raise HTTPException(status_code=404, detail="Report não encontrado.")
    return rep


@router.put("/reports/{report_id}")
async def reports_update(report_id: int, req: ReportUpdate, user: dict = Depends(get_current_user)):
    rep = get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Report não encontrado.")
    if not _can_edit_report(user, rep):
        raise HTTPException(status_code=403, detail="Sem permissão para editar este report.")
    fields = req.model_dump(exclude_unset=True)
    if "definition" in fields and fields["definition"] is not None:
        fields["definition"] = req.definition.model_dump() if req.definition else {}
    return update_report(report_id, fields)


@router.post("/reports/{report_id}/publish")
async def reports_publish(report_id: int, req: ReportPublish, user: dict = Depends(get_current_user)):
    rep = get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Report não encontrado.")
    if not _can_edit_report(user, rep):
        raise HTTPException(status_code=403, detail="Sem permissão para publicar este report.")
    return update_report(report_id, {"sql_generated": req.sql_generated, "status": "published"})


@router.post("/reports/{report_id}/unpublish")
async def reports_unpublish(report_id: int, user: dict = Depends(get_current_user)):
    rep = get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Report não encontrado.")
    if not _can_edit_report(user, rep):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    return update_report(report_id, {"status": "draft"})


@router.delete("/reports/{report_id}")
async def reports_delete(report_id: int, user: dict = Depends(get_current_user)):
    rep = get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Report não encontrado.")
    if not _can_edit_report(user, rep):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    delete_report(report_id)
    return {"ok": True}


@router.post("/reports/{report_id}/run")
async def reports_run(report_id: int, user: dict = Depends(get_current_user)):
    """Executa o report com a versão atualmente salva (draft ou published)."""
    from app.services.report_service import render_report
    rep = get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail="Report não encontrado.")
    if rep["status"] != "published" and not _can_edit_report(user, rep):
        raise HTTPException(status_code=404, detail="Report não encontrado.")
    accessible = _accessible_tables_for(user, rep.get("datamart_ids"), rep.get("diamond_layer_ids"))
    apply_login_filter = not is_root(user) if user else False
    try:
        return await render_report(rep, user, accessible, apply_login_filter)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao executar report: {e}")


@router.post("/reports/preview")
async def reports_preview(req: ReportCreate, user: dict = Depends(get_current_user)):
    """Pré-visualiza um report sem persistir. Útil para o designer."""
    from app.services.report_service import render_report
    rep = {
        "id": 0,
        "owner_id": user["id"],
        "name": req.name,
        "description": req.description,
        "status": "draft",
        "question": req.question,
        "sql_generated": req.sql_generated,
        "datamart_ids": req.datamart_ids,
        "diamond_layer_ids": req.diamond_layer_ids,
        "definition": req.definition.model_dump() if req.definition else {},
        "version": 1,
    }
    accessible = _accessible_tables_for(user, req.datamart_ids, req.diamond_layer_ids)
    apply_login_filter = not is_root(user) if user else False
    try:
        return await render_report(rep, user, accessible, apply_login_filter)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao pré-visualizar: {e}")


# --- Tables ---

@router.get("/tables")
async def list_tables(request: Request):
    user = getattr(request.state, "user", None)
    all_tables = get_all_tables()
    if user and is_admin(user):
        # root / superuser / admin sempre veem tudo (a UI oferece o filtro
        # "Apenas os meus" para refinar do lado cliente).
        return all_tables
    if user:
        # user / analista: estritamente limitado às tabelas acessíveis via
        # DataMarts OU DiamondLayers autorizadas. Sem nenhuma atribuição
        # → lista vazia (regra de segurança).
        dm_list = get_user_datamarts(user["id"])
        layer_list = get_user_diamond_layers(user["id"])
        if not dm_list and not layer_list:
            return []
        allowed_set: set[str] = set()
        if dm_list:
            allowed_set.update(get_tables_for_datamarts([d["id"] for d in dm_list]))
        if layer_list:
            allowed_set.update(get_tables_for_diamond_layers([l["id"] for l in layer_list]))
        return [t for t in all_tables if t["name"] in allowed_set]
    return all_tables


@router.get("/tables/{table_name}/preview")
async def preview_table(table_name: str, limit: int = Query(20, ge=1, le=100)):
    safe_name = _safe_table_name(table_name)
    result = execute_readonly_sql(f'SELECT * FROM "{safe_name}" LIMIT {limit}')
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.delete("/tables/{table_name}")
async def drop_table(table_name: str, user: dict = Depends(get_current_user)):
    from app.core.database import drop_user_table
    from app.core.security import is_admin

    safe_name = _safe_table_name(table_name)

    # Admin/Root: pode excluir qualquer tabela
    if is_admin(user):
        result = drop_user_table(safe_name)
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result

    # Analista: só tabelas do seu DataMart dm-{login}
    if user.get("user_type") == "analista":
        dm_name = f"dm-{user['login']}"
        dm = get_datamart_by_name(dm_name)
        if not dm:
            raise HTTPException(403, "Você não possui DataMart próprio.")
        dm_tables = set(get_tables_for_datamarts([dm["id"]]))
        if safe_name not in dm_tables:
            raise HTTPException(403, f"Tabela '{safe_name}' não pertence ao seu DataMart ({dm_name}).")
        result = drop_user_table(safe_name)
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result

    raise HTTPException(403, "Sem permissão para excluir tabelas.")


# --- Excel Upload ---

@router.post("/upload")
async def upload_excel(
    file: UploadFile = File(...),
    datamart_name: str = Query("", description="Nome do DataMart"),
    conflict_strategy: str | None = Query(
        None,
        description="Como tratar tabelas já existentes: 'replace' ou 'append'.",
    ),
    user: dict = Depends(require_upload_access),
):
    filename = _sanitize_filename(file.filename or "")
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext != "xlsx":
        raise HTTPException(400, "Apenas arquivos Excel (.xlsx) são aceitos.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, "Arquivo excede o tamanho máximo permitido (10MB).")

    # Analista: forçar DataMart "dm-{login}" e auto-atribuir
    if user.get("user_type") == "analista":
        datamart_name = f"dm-{user['login']}"

    if not datamart_name or not datamart_name.strip():
        raise HTTPException(400, "Escolha um DataMart ou crie um novo antes de enviar.")

    if conflict_strategy is not None and conflict_strategy not in ("replace", "append"):
        raise HTTPException(400, "conflict_strategy inválido. Use 'replace' ou 'append'.")

    dest = settings.upload_dir / filename
    with open(dest, "wb") as f:
        f.write(data)

    dm = get_datamart_by_name(datamart_name)
    if not dm:
        dm = db_create_datamart(datamart_name)
    dm_id = dm["id"]

    # Auto-atribuir DataMart ao analista
    if user.get("user_type") == "analista":
        current_dms = get_user_datamarts(user["id"])
        current_dm_ids = [d["id"] for d in current_dms]
        if dm_id not in current_dm_ids:
            current_dm_ids.append(dm_id)
            set_user_datamarts(user["id"], current_dm_ids)

    try:
        report = import_excel(dest, datamart_name=dm["name"], conflict_strategy=conflict_strategy)
        conflicts = [r for r in report if r.get("action") == "conflict"]
        if conflicts and conflict_strategy is None:
            return JSONResponse(
                status_code=409,
                content={
                    "filename": filename,
                    "datamart": dm["name"],
                    "conflicts": conflicts,
                    "detail": "Tabelas existentes encontradas no DataMart.",
                },
            )
        for sheet_info in report:
            if sheet_info.get("table") and sheet_info.get("action") in ("created", "replaced", "appended"):
                assign_table_to_datamart(dm_id, sheet_info["table"])
        reset_agent()
        return {"filename": filename, "sheets": report, "datamart": dm["name"]}
    except Exception:
        raise HTTPException(500, "Erro ao processar arquivo.")


# --- Query (Natural Language via Deep Agent) ---

@router.post("/query")
async def query_nl(req: QueryRequest, request: Request):
    user = getattr(request.state, "user", None)
    user_login = user["login"] if user else ""

    # Compatibilidade: alguns conectores enviam o payload inteiro serializado
    # dentro de "question". Quando detectado, extraímos os campos esperados.
    question = req.question
    analysis_type_id = req.analysis_type_id
    conversation_context = req.conversation_context
    conversation_history = (
        [t.model_dump() for t in req.conversation_history]
        if req.conversation_history else None
    )
    result_limit = req.result_limit
    datamart_ids = req.datamart_ids
    diamond_layer_ids = req.diamond_layer_ids
    skill_ids = req.skill_ids
    saved_sql = req.saved_sql

    try:
        parsed_question = json.loads(req.question)
        if isinstance(parsed_question, dict) and "question" in parsed_question:
            question = str(parsed_question.get("question") or req.question)
            analysis_type_id = parsed_question.get("analysis_type_id", analysis_type_id)
            conversation_context = parsed_question.get("conversation_context", conversation_context)
            conversation_history = parsed_question.get("conversation_history", conversation_history)
            result_limit = parsed_question.get("result_limit", result_limit)
            datamart_ids = parsed_question.get("datamart_ids", datamart_ids)
            diamond_layer_ids = parsed_question.get("diamond_layer_ids", diamond_layer_ids)
            skill_ids = parsed_question.get("skill_ids", skill_ids)
            saved_sql = parsed_question.get("saved_sql", saved_sql)
    except Exception:
        pass

    accessible_tables: set[str] | None = None
    any_filter = bool(datamart_ids) or bool(diamond_layer_ids)

    if user and not is_root(user):
        # Authorize DataMart selection
        user_dms = get_user_datamarts(user["id"])
        user_dm_ids = {d["id"] for d in user_dms}
        allowed_dm_ids: list[int] = []
        if datamart_ids:
            allowed_dm_ids = [did for did in datamart_ids if did in user_dm_ids]
            if datamart_ids and not allowed_dm_ids:
                raise HTTPException(
                    status_code=403,
                    detail="Nenhum DataMart informado está autorizado para este usuário.",
                )

        # Authorize DiamondLayer selection
        user_layers = get_user_diamond_layers(user["id"])
        user_layer_ids = {l["id"] for l in user_layers}
        allowed_layer_ids: list[int] = []
        if diamond_layer_ids:
            allowed_layer_ids = [lid for lid in diamond_layer_ids if lid in user_layer_ids]
            if diamond_layer_ids and not allowed_layer_ids:
                raise HTTPException(
                    status_code=403,
                    detail="Nenhuma DiamondLayer informada está autorizada para este usuário.",
                )

        if any_filter:
            accessible_tables = set()
            if allowed_dm_ids:
                accessible_tables.update(get_tables_for_datamarts(allowed_dm_ids))
            if allowed_layer_ids:
                accessible_tables.update(get_tables_for_diamond_layers(allowed_layer_ids))
        else:
            # No filter selected: union of everything the user can reach
            accessible_tables = set()
            if user_dms:
                accessible_tables.update(get_tables_for_datamarts([d["id"] for d in user_dms]))
            if user_layers:
                accessible_tables.update(get_tables_for_diamond_layers([l["id"] for l in user_layers]))
            if not accessible_tables:
                accessible_tables = None  # no permissions configured at all
    elif user and is_root(user) and any_filter:
        accessible_tables = set()
        if datamart_ids:
            accessible_tables.update(get_tables_for_datamarts(datamart_ids))
        if diamond_layer_ids:
            accessible_tables.update(get_tables_for_diamond_layers(diamond_layer_ids))

    if accessible_tables is not None and not accessible_tables:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma tabela foi encontrada nos DataMarts/DiamondLayers selecionados.",
        )

    # run_query expects a list (or None)
    accessible_tables_list = sorted(accessible_tables) if accessible_tables is not None else None

    try:
        result = await run_query(
            question=question,
            analysis_type_id=analysis_type_id,
            context=conversation_context,
            history=conversation_history,
            result_limit=result_limit,
            user_login=user_login,
            skill_ids=skill_ids,
            accessible_tables=accessible_tables_list,
            saved_sql=saved_sql,
            apply_login_filter=not is_root(user) if user else False,
        )
        return result
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Erro na consulta.")


# --- Analysis Types ---

@router.get("/analysis-types")
async def list_analysis_types():
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM analysis_types ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


@router.get("/analysis-types/{type_id}")
async def get_analysis_type(type_id: int):
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM analysis_types WHERE id = ?", (type_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Tipo de análise não encontrado.")
        return dict(row)
    finally:
        conn.close()


def _can_edit_analysis_type(user: dict, row: dict) -> bool:
    if is_admin(user):
        return True
    owner = row.get("owner_id")
    return owner is not None and owner == user.get("id")


@router.post("/analysis-types")
async def create_analysis_type(data: AnalysisTypeCreate, user: dict = Depends(get_current_user)):
    conn = get_sync_connection()
    try:
        owner_id = user.get("id") if user else None
        conn.execute(
            "INSERT INTO analysis_types (name, system_prompt, guardrails_input, guardrails_output, owner_id) VALUES (?, ?, ?, ?, ?)",
            (data.name, data.system_prompt, data.guardrails_input, data.guardrails_output, owner_id),
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@router.put("/analysis-types/{type_id}")
async def update_analysis_type(type_id: int, data: AnalysisTypeUpdate, user: dict = Depends(get_current_user)):
    conn = get_sync_connection()
    try:
        existing = conn.execute("SELECT * FROM analysis_types WHERE id = ?", (type_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Prompt não encontrado.")
        if not _can_edit_analysis_type(user, dict(existing)):
            raise HTTPException(403, "Apenas o autor do prompt ou um administrador pode editá-lo.")
        fields, values = [], []
        for field_name in ("name", "system_prompt", "guardrails_input", "guardrails_output"):
            val = getattr(data, field_name)
            if val is not None:
                fields.append(f"{field_name} = ?")
                values.append(val)
        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar.")
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(type_id)
        conn.execute(f"UPDATE analysis_types SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.delete("/analysis-types/{type_id}")
async def delete_analysis_type(type_id: int, user: dict = Depends(get_current_user)):
    conn = get_sync_connection()
    try:
        existing = conn.execute("SELECT * FROM analysis_types WHERE id = ?", (type_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Prompt não encontrado.")
        if not _can_edit_analysis_type(user, dict(existing)):
            raise HTTPException(403, "Apenas o autor do prompt ou um administrador pode excluí-lo.")
        conn.execute("DELETE FROM analysis_types WHERE id = ?", (type_id,))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


# --- Export Excel ---

@router.post("/export/excel")
async def export_excel(data: dict):
    excel_bytes = export_to_excel_bytes(data)
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=falecomseusdados_export.xlsx"},
    )


# --- Visualization (PyGWalker) ---

@router.post("/explore", response_class=HTMLResponse)
async def explore_data(data: dict):
    try:
        return HTMLResponse(content=generate_explore_html(data))
    except Exception as e:
        raise HTTPException(500, f"Erro ao abrir explorador: {str(e)}")


@router.post("/explore/open", response_class=HTMLResponse)
async def explore_data_open(json_data: str = Form(...)):
    try:
        return HTMLResponse(content=generate_explore_html(json.loads(json_data)))
    except Exception as e:
        raise HTTPException(500, f"Erro ao abrir explorador: {str(e)}")


@router.post("/explore/ask")
async def explore_ask_ai(data: dict, user: dict = Depends(get_current_user)):
    prompt = data.get("prompt", "").strip()
    json_data = data.get("json_data", {})
    if not prompt:
        raise HTTPException(400, "Prompt vazio.")
    if not json_data or not json_data.get("rows"):
        raise HTTPException(400, "Dataset vazio.")
    try:
        result = ask_visualization_ai(json_data, prompt)
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


@router.post("/chart", response_class=HTMLResponse)
async def chart_data(data: dict):
    try:
        return HTMLResponse(content=generate_chart_html(data))
    except Exception as e:
        raise HTTPException(500, f"Erro ao gerar gráfico: {str(e)}")


@router.post("/chart/open", response_class=HTMLResponse)
async def chart_data_open(json_data: str = Form(...), chart_type: str = Form("auto"), sql_no_limit: str = Form("")):
    try:
        data = json.loads(json_data)
        html = generate_chart_html(data) if chart_type == "auto" else generate_typed_chart_html(data, chart_type, sql_no_limit=sql_no_limit)
        return HTMLResponse(content=html)
    except Exception as e:
        raise HTTPException(500, f"Erro ao gerar gráfico: {str(e)}")


@router.post("/chart/typed", response_class=HTMLResponse)
async def chart_data_typed(req: ChartRequest):
    try:
        return HTMLResponse(content=generate_typed_chart_html(req.query_data, req.chart_type))
    except Exception as e:
        raise HTTPException(500, f"Erro ao gerar gráfico: {str(e)}")


@router.post("/chart/options")
async def chart_options(data: dict):
    try:
        return get_chart_options_for_data(data)
    except Exception as e:
        raise HTTPException(500, f"Erro ao analisar opções: {str(e)}")


# --- Analytics (Análise Avançada) ---

def _analytics_error_html(message: str, traceback_text: str = "") -> str:
    """Render a friendly error page for the analytics endpoints. Avoids the
    generic 'Internal Server Error' plaintext that Starlette returns when an
    HTMLResponse handler raises HTTPException — the user's browser cannot
    distinguish the cause without the message."""
    import html as _html
    safe_msg = _html.escape(message or "Erro desconhecido")
    safe_tb = _html.escape(traceback_text) if traceback_text else ""
    tb_block = f'<details style="margin-top:12px"><summary style="cursor:pointer;color:#7d8590">Detalhes técnicos</summary><pre style="white-space:pre-wrap;word-break:break-word;background:#0d1117;padding:12px;border-radius:6px;border:1px solid #30363d;color:#c9d1d9;font-size:11px;line-height:1.5">{safe_tb}</pre></details>' if safe_tb else ""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><title>Erro — Análise Avançada</title>
<style>body{{background:#0a0c10;color:#c9d1d9;font-family:system-ui,sans-serif;margin:0;padding:40px;max-width:800px;margin:auto}}
h1{{color:#f85149;font-size:18px;margin:0 0 8px}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px}}
p{{line-height:1.6;color:#c9d1d9}}
.muted{{color:#7d8590;font-size:12px}}</style></head>
<body><div class="box">
<h1>Falha ao gerar a Análise Avançada</h1>
<p>{safe_msg}</p>
<p class="muted">Volte à aba anterior, refaça a consulta e tente novamente. Se o erro persistir, envie a mensagem acima ao administrador.</p>
{tb_block}
</div></body></html>"""


def _analytics_log_error(label: str, exc: BaseException) -> str:
    """Log full traceback to stderr (visible in Render/uvicorn logs) and
    return a short technical traceback for the user-facing details panel."""
    import sys
    import traceback as _tb
    print(f"[ANALYTICS] {label}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    tb_full = _tb.format_exc()
    print(tb_full, file=sys.stderr, flush=True)
    return tb_full


@router.post("/analytics", response_class=HTMLResponse)
async def analytics_page(data: dict):
    try:
        return HTMLResponse(content=generate_analytics_html(data))
    except BaseException as e:
        tb = _analytics_log_error("/api/analytics", e)
        return HTMLResponse(content=_analytics_error_html(str(e), tb), status_code=500)


@router.post("/analytics/open", response_class=HTMLResponse)
async def analytics_page_open(json_data: str = Form(...)):
    # Parse + render are wrapped in a single broad except so that
    # malformed JSON, missing form fields, or downstream exceptions
    # all produce the friendly HTML page instead of Starlette's
    # plaintext "Internal Server Error" (which gives the user nothing).
    try:
        try:
            payload = json.loads(json_data)
        except json.JSONDecodeError as je:
            return HTMLResponse(
                content=_analytics_error_html(
                    f"JSON inválido recebido: {je.msg} (linha {je.lineno}, col {je.colno})."
                ),
                status_code=400,
            )
        return HTMLResponse(content=generate_analytics_html(payload))
    except BaseException as e:
        tb = _analytics_log_error("/api/analytics/open", e)
        return HTMLResponse(content=_analytics_error_html(str(e), tb), status_code=500)


@router.post("/analytics/predict")
async def analytics_predict(req: PredictionRequest):
    try:
        if req.model_type == "automl":
            try:
                from app.core.ag_utils import suppress_stderr
                with suppress_stderr():
                    return run_prediction(req.query_data, req.target, req.features, req.model_type, n_clusters=req.n_clusters, task_type=req.task_type)
            except ImportError:
                return run_prediction(req.query_data, req.target, req.features, req.model_type, n_clusters=req.n_clusters, task_type=req.task_type)
        return run_prediction(req.query_data, req.target, req.features, req.model_type, n_clusters=req.n_clusters, task_type=req.task_type)
    except Exception as e:
        return {"error": str(e)}


@router.post("/analytics/causal")
async def analytics_causal(req: CausalRequest):
    try:
        return run_causal_analysis(req.query_data, req.method, req.config)
    except Exception as e:
        return {"error": str(e)[:300]}


# --- Email ---

@router.post("/email")
async def send_email(req: EmailRequest):
    try:
        eml_bytes = build_eml(to_email=req.to_email, subject=req.subject, body_html=req.body_html, data=req.excel_data)
        return StreamingResponse(
            io.BytesIO(eml_bytes), media_type="message/rfc822",
            headers={"Content-Disposition": f'attachment; filename="{req.subject}.eml"'},
        )
    except Exception as e:
        raise HTTPException(500, f"Erro ao gerar email: {str(e)}")


# --- API Keys ---

@router.post("/keys")
async def create_key(data: ApiKeyCreate, user: dict = Depends(require_admin)):
    return create_api_key(data.label)


@router.get("/keys")
async def list_keys(user: dict = Depends(require_admin)):
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT id, label, is_active, created_at FROM api_keys ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# --- Custom Skills ---

@router.get("/skills")
async def list_skills():
    return get_all_skills()


@router.get("/skills/active")
async def list_active_skills():
    return get_active_skills()


def _can_edit_skill(user: dict, skill: dict) -> bool:
    if is_admin(user):
        return True
    owner = skill.get("owner_id")
    return owner is not None and owner == user.get("id")


@router.post("/skills")
async def create_skill_route(req: SkillCreate, user: dict = Depends(get_current_user)):
    created_by = user.get("login", "") if user else ""
    owner_id = user.get("id") if user else None
    try:
        return db_create_skill(
            name=req.name, description=req.description, content=req.content,
            created_by=created_by, triggers=req.triggers or None, owner_id=owner_id,
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/skills/{skill_id}")
async def get_skill_route(skill_id: int):
    skill = get_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(404, "Skill não encontrada")
    return skill


@router.put("/skills/{skill_id}")
async def update_skill_route(skill_id: int, req: SkillUpdate, user: dict = Depends(get_current_user)):
    skill = get_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(404, "Skill não encontrada")
    if not _can_edit_skill(user, skill):
        raise HTTPException(403, "Apenas o autor da skill ou um administrador pode editá-la.")
    db_update_skill(skill_id, **req.model_dump(exclude_none=True))
    return {"success": True}


@router.put("/skills/{skill_id}/toggle")
async def toggle_skill(skill_id: int, user: dict = Depends(get_current_user)):
    skill = get_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(404, "Skill não encontrada")
    if not _can_edit_skill(user, skill):
        raise HTTPException(403, "Apenas o autor da skill ou um administrador pode ativar/desativar.")
    new_state = 0 if skill["is_active"] else 1
    db_update_skill(skill_id, is_active=new_state)
    return {"success": True, "is_active": new_state}


@router.delete("/skills/{skill_id}")
async def delete_skill_route(skill_id: int, user: dict = Depends(get_current_user)):
    skill = get_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(404, "Skill não encontrada")
    if not _can_edit_skill(user, skill):
        raise HTTPException(403, "Apenas o autor da skill ou um administrador pode excluí-la.")
    db_delete_skill(skill_id)
    return {"success": True}


# --- Skill AI Generator ---

_SKILL_GEN_PROMPT = """Você é um engenheiro de Agent Skills especialista. Gere um SKILL.md completo para um agente de análise de dados (SQL sobre SQLite).

## Informações fornecidas pelo usuário

Domínio: {domain}
Objetivo: {objective}
Métricas/KPIs: {metrics}
Contexto dos dados: {data_context}
Regras de negócio: {rules}
Formato de resposta: {format}

## Sua tarefa

Gere o conteúdo completo de um SKILL.md com:

1. YAML frontmatter com: name (slug kebab-case), description (1 linha), triggers (lista de 5-10 palavras-chave em português), trust_level: 1, priority: 10

2. Seção "## Quando Usar" — condições que ativam esta skill

3. Seção "## Métricas e Indicadores" — lista de KPIs com fórmula SQL quando relevante

4. Seção "## Padrões de Query" — exemplos de SQL para consultas típicas do domínio (compatível com SQLite)

5. Seção "## Regras de Negócio" — restrições, filtros obrigatórios, formatação

6. Seção "## Formato de Resposta" — como estruturar a resposta ao usuário

7. Seção "## Propostas de Análise" — 5 exemplos de perguntas que o usuário pode fazer

## Regras de geração
- SQL compatível com SQLite (sem funções MySQL/PostgreSQL)
- Sempre em português do Brasil
- Nomes de tabelas e colunas genéricos (o agente resolve os reais)
- Gere conteúdo prático e diretamente utilizável
- Retorne APENAS o conteúdo do SKILL.md, sem explicação adicional
- Comece com --- (YAML frontmatter)
"""


@router.post("/skills/generate")
async def generate_skill_ai(data: dict, user: dict = Depends(get_current_user)):
    # from langchain_openai import ChatOpenAI as _ChatOpenAI
    from app.services.llm_factory import make_chat_llm

    domain = data.get("domain", "Geral")
    objective = data.get("objective", "").strip()
    if not objective or len(objective) < 10:
        return {"error": "Descreva o objetivo da skill (mínimo 10 caracteres)."}

    metrics = data.get("metrics", "") or "Definir automaticamente pelo domínio"
    data_ctx = data.get("data_context", "") or "Tabelas genéricas — o agente descobre dinamicamente"
    rules = data.get("rules", "") or "Nenhuma restrição específica"
    fmt = data.get("format", "auto")
    fmt_labels = {
        "auto": "Automático — a IA decide o melhor formato",
        "detailed": "Detalhado com insights e recomendações",
        "concise": "Conciso e direto ao ponto",
        "executive": "Executivo — resumo + números-chave",
        "technical": "Técnico — SQL explícito + métricas detalhadas",
    }

    prompt = _SKILL_GEN_PROMPT.format(
        domain=domain, objective=objective, metrics=metrics,
        data_context=data_ctx, rules=rules, format=fmt_labels.get(fmt, fmt),
    )

    try:
        # llm = _ChatOpenAI(model=settings.openai_model,api_key=settings.openai_api_key,temperature=0.3,)
        llm = make_chat_llm(temperature=0.3, role="api_ai")
        response = llm.invoke(prompt)
        content = response.content.strip()

        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()

        from app.core.database import _parse_skill_frontmatter
        parsed = _parse_skill_frontmatter(content)
        fm = parsed["frontmatter"]

        name = fm.get("name", "").strip() or domain.lower().replace(" ", "-")
        description = fm.get("description", "").strip() or objective[:80]
        triggers = fm.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [t.strip() for t in triggers.split(",")]

        return {
            "name": name,
            "description": description,
            "triggers": triggers,
            "content": content,
        }
    except Exception as e:
        return {"error": f"Erro ao gerar skill: {str(e)[:150]}"}


# --- Skills Export/Import ---

@router.get("/skills/export/excel")
async def export_skills(user: dict = Depends(require_admin)):
    import pandas as pd
    skills = get_all_skills()
    rows = [{"name": s["name"], "description": s.get("description", ""), "content": s.get("content", ""),
             "is_active": s.get("is_active", 1), "created_by": s.get("created_by", ""),
             "created_at": s.get("created_at", "")} for s in skills]
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=skills_export.xlsx"},
    )


@router.post("/skills/import")
async def import_skills(file: UploadFile = File(...), request: Request = None, user: dict = Depends(require_admin)):
    import pandas as pd
    data = await file.read()
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    current_user = getattr(request.state, "user", None) if request else None
    created_by = current_user["login"] if current_user else ""
    created, errors = [], []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        if not name or len(name) < 2:
            errors.append(f"Nome vazio ou inválido: '{name}'")
            continue
        description = str(row.get("description", "")).strip()
        content = str(row.get("content", "")).strip()
        if description == "nan": description = ""
        if content == "nan": content = ""
        try:
            db_create_skill(name=name, description=description, content=content, created_by=created_by)
            created.append(name)
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
    return {"created": created, "errors": errors, "total": len(created)}


# --- Data Catalog ---

@router.get("/catalog")
async def catalog_summary(user: dict = Depends(get_current_user)):
    return get_catalog_summary()


@router.post("/catalog/scan")
async def catalog_scan(data: dict = None, user: dict = Depends(require_admin)):
    table_names = None
    if data and data.get("tables"):
        table_names = data["tables"]
    return run_catalog_scan(table_names)


@router.get("/catalog/search")
async def catalog_search(q: str = Query("", min_length=1), user: dict = Depends(get_current_user)):
    return search_catalog(q)


@router.post("/catalog/enrich/{table_name}")
async def catalog_enrich(table_name: str, user: dict = Depends(require_admin)):
    safe_name = _safe_table_name(table_name)
    return await enrich_table_with_llm(safe_name)


@router.put("/catalog/{table_name}/tags")
async def catalog_update_tags(table_name: str, data: dict, user: dict = Depends(require_admin)):
    import json as _json
    tags = data.get("tags", [])
    conn = get_sync_connection()
    try:
        conn.execute("UPDATE catalog_datasets SET tags=?, updated_at=CURRENT_TIMESTAMP WHERE table_name=?",
                     (_json.dumps(tags, ensure_ascii=False), table_name))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.put("/catalog/{table_name}/owner")
async def catalog_update_owner(table_name: str, data: dict, user: dict = Depends(require_admin)):
    owner = data.get("owner", "")
    conn = get_sync_connection()
    try:
        conn.execute("UPDATE catalog_datasets SET owner=?, updated_at=CURRENT_TIMESTAMP WHERE table_name=?",
                     (owner, table_name))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.put("/catalog/{table_name}/domain")
async def catalog_update_domain(table_name: str, data: dict, user: dict = Depends(require_admin)):
    domain = data.get("domain", "Geral")
    conn = get_sync_connection()
    try:
        conn.execute(
            "UPDATE catalog_datasets SET domain=?, updated_at=CURRENT_TIMESTAMP WHERE table_name=?",
            (domain, table_name),
        )
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.put("/catalog/{table_name}/description")
async def catalog_update_description(table_name: str, data: dict, user: dict = Depends(require_admin)):
    description = (data.get("description") or "").strip()
    conn = get_sync_connection()
    try:
        cur = conn.execute("SELECT 1 FROM catalog_datasets WHERE table_name=?", (table_name,))
        if not cur.fetchone():
            raise HTTPException(404, "Tabela nao esta no catalogo.")
        conn.execute(
            "UPDATE catalog_datasets SET description=?, updated_at=CURRENT_TIMESTAMP WHERE table_name=?",
            (description, table_name),
        )
        conn.commit()
        return {"success": True, "description": description}
    finally:
        conn.close()


@router.put("/catalog/{table_name}/columns/{column_name}")
async def catalog_update_column(
    table_name: str, column_name: str, data: dict,
    user: dict = Depends(require_admin),
):
    """Edita description, technical_type, semantic_type e pii_data de uma coluna.

    Apenas campos presentes no payload sao atualizados. pii_data e mesclado
    com o JSON existente (nao substitui campos ausentes).
    """
    import json as _json
    desc = data.get("description")
    tech = data.get("technical_type")
    sem = data.get("semantic_type")
    pii_patch = data.get("pii_data")

    conn = get_sync_connection()
    try:
        row = conn.execute(
            "SELECT pii_data FROM catalog_columns WHERE table_name=? AND column_name=?",
            (table_name, column_name),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Coluna nao encontrada no catalogo.")

        sets = []
        params: list = []
        if desc is not None:
            sets.append("description=?"); params.append(str(desc))
        if tech is not None:
            sets.append("technical_type=?"); params.append(str(tech))
        if sem is not None:
            sets.append("semantic_type=?"); params.append(str(sem))
        if isinstance(pii_patch, dict):
            try:
                current = _json.loads(dict(row).get("pii_data") or "{}")
            except (ValueError, TypeError):
                current = {}
            current.update(pii_patch)
            sets.append("pii_data=?"); params.append(_json.dumps(current, ensure_ascii=False))

        if not sets:
            return {"success": True, "updated": []}

        params.extend([table_name, column_name])
        conn.execute(
            f"UPDATE catalog_columns SET {', '.join(sets)} WHERE table_name=? AND column_name=?",
            tuple(params),
        )
        conn.commit()
        return {"success": True, "updated": [s.split("=")[0] for s in sets]}
    finally:
        conn.close()


@router.put("/catalog/{table_name}/joins")
async def catalog_update_joins(table_name: str, data: dict, user: dict = Depends(require_admin)):
    """Substitui a lista de joins sugeridos (campo extras.suggested_joins)."""
    import json as _json
    joins = data.get("joins")
    if not isinstance(joins, list):
        raise HTTPException(400, "Payload deve conter 'joins' como lista de strings.")
    joins = [str(j).strip() for j in joins if str(j).strip()]

    conn = get_sync_connection()
    try:
        row = conn.execute(
            "SELECT extras FROM catalog_datasets WHERE table_name=?", (table_name,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Tabela nao esta no catalogo.")
        try:
            extras = _json.loads(dict(row).get("extras") or "{}")
        except (ValueError, TypeError):
            extras = {}
        if not isinstance(extras, dict):
            extras = {}
        extras["suggested_joins"] = joins
        conn.execute(
            "UPDATE catalog_datasets SET extras=?, updated_at=CURRENT_TIMESTAMP WHERE table_name=?",
            (_json.dumps(extras, ensure_ascii=False), table_name),
        )
        conn.commit()
        return {"success": True, "joins": joins}
    finally:
        conn.close()


# --- External API (with API Key auth) ---

@router.post("/v1/query")
async def external_query(req: ApiQueryRequest, x_api_key: str = Header(...)):
    if not validate_api_key(x_api_key):
        raise HTTPException(401, "API key inválida ou inativa.")
    try:
        result = await run_query(question=req.question, analysis_type_id=req.analysis_type_id,
                                  user_login=f"api-key:{x_api_key[:8]}")
        return result
    except Exception:
        raise HTTPException(500, "Erro na consulta.")


# --- Gallery ---

@router.get("/gallery")
async def list_gallery():
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT id, title, description, share_token, category, created_at FROM analysis_gallery ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


@router.post("/gallery")
async def save_to_gallery(req: GallerySaveRequest, user: dict = Depends(get_current_user)):
    token = uuid.uuid4().hex[:12]
    conn = get_sync_connection()
    try:
        category = (req.category or "analysis").strip() or "analysis"
        conn.execute(
            "INSERT INTO analysis_gallery (title, description, query_data, chart_config, page_html, share_token, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (req.title, req.description, json.dumps(req.query_data),
             json.dumps(req.local_storage) if req.local_storage else "", req.page_html, token, category),
        )
        conn.commit()
        return {"success": True, "share_token": token}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@router.delete("/gallery/{gallery_id}")
async def delete_gallery_item(gallery_id: int, user: dict = Depends(require_admin)):
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM analysis_gallery WHERE id = ?", (gallery_id,))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.get("/gallery/{token}/view", response_class=HTMLResponse)
async def view_gallery_item(token: str):
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM analysis_gallery WHERE share_token = ?", (token,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Análise não encontrada.")
        item = dict(row)
        page_html = item.get("page_html", "")
        if page_html:
            ls_data = item.get("chart_config", "")
            if ls_data:
                try:
                    ls_obj = json.loads(ls_data)
                    ls_json = json.dumps(ls_obj)
                    restore_script = f"""<script>(function(){{var d={ls_json};Object.keys(d).forEach(function(k){{try{{localStorage.setItem(k,d[k])}}catch(e){{}}}})}})()</script>"""
                    if "<head>" in page_html:
                        page_html = page_html.replace("<head>", "<head>" + restore_script, 1)
                    else:
                        page_html = restore_script + page_html
                except (json.JSONDecodeError, TypeError):
                    pass
            return HTMLResponse(content=page_html)
        query_data = json.loads(item["query_data"])
        chart_config = None
        try:
            chart_config = json.loads(item["chart_config"]) if item["chart_config"] else None
        except (json.JSONDecodeError, TypeError):
            pass
        return HTMLResponse(content=generate_gallery_view_html(query_data, chart_config, item["title"]))
    finally:
        conn.close()


# --- Query History ---

@router.get("/history")
async def query_history(limit: int = Query(20, le=100)):
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM query_history ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# --- Saved Questions ---

@router.get("/saved-questions")
async def list_saved_questions(user: dict = Depends(get_current_user)):
    return get_saved_questions(user["id"])


@router.post("/saved-questions")
async def save_question(req: SavedQuestionCreate, user: dict = Depends(get_current_user)):
    return create_saved_question(
        user_id=user["id"],
        question=req.question,
        label=req.label,
        sql_generated=req.sql_generated,
    )


@router.put("/saved-questions/{question_id}")
async def update_saved_question(question_id: int, req: SavedQuestionUpdate, user: dict = Depends(get_current_user)):
    update_saved_question_label(question_id, user["id"], req.label)
    return {"success": True}


@router.delete("/saved-questions/{question_id}")
async def remove_saved_question(question_id: int, user: dict = Depends(get_current_user)):
    delete_saved_question(question_id, user["id"])
    return {"success": True}


@router.get("/saved-questions/all")
async def list_all_saved_questions(user: dict = Depends(get_current_user)):
    if is_admin(user):
        return get_all_saved_questions_with_user()
    return get_saved_questions_with_user(user["id"])


@router.get("/saved-questions/export")
async def export_saved_questions(user: dict = Depends(get_current_user)):
    import pandas as pd
    if is_admin(user):
        questions = get_all_saved_questions_with_user()
    else:
        questions = get_saved_questions_with_user(user["id"])
    rows = [{"label": q.get("label", ""), "question": q["question"],
             "sql_generated": q.get("sql_generated", ""),
             "user": q.get("display_name") or q.get("login", ""),
             "created_at": q.get("created_at", "")} for q in questions]
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=perguntas_salvas.xlsx"},
    )


@router.post("/saved-questions/import")
async def import_saved_questions_route(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    import pandas as pd
    data = await file.read()
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "question": str(row.get("question", row.get("pergunta", ""))).strip(),
            "label": str(row.get("label", row.get("rótulo", row.get("rotulo", "")))).strip(),
            "sql_generated": str(row.get("sql_generated", row.get("sql", ""))).strip(),
        })
    return import_saved_questions(user["id"], rows)


@router.post("/query/full-data")
async def query_full_data(data: dict, user: dict = Depends(get_current_user)):
    sql = (data.get("sql") or "").strip()
    if not sql:
        raise HTTPException(400, "SQL vazio.")
    result = execute_readonly_sql(sql)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.put("/saved-questions/{question_id}/favorite")
async def toggle_favorite(question_id: int, data: dict, user: dict = Depends(get_current_user)):
    if data.get("is_favorite"):
        param_config = json.dumps(data.get("param_config", {}), ensure_ascii=False)
        return set_favorite_question(user["id"], question_id, param_config)
    else:
        return unset_favorite_question(user["id"])


@router.get("/saved-questions/favorite")
async def get_my_favorite(user: dict = Depends(get_current_user)):
    fav = get_favorite_question(user["id"])
    if not fav:
        return {"has_favorite": False}
    try:
        fav["param_config"] = json.loads(fav.get("param_config") or "{}")
    except (json.JSONDecodeError, TypeError):
        fav["param_config"] = {}
    return {"has_favorite": True, "question": fav}


# ---------------------------------------------------------------------------
# Saved Visions
# ---------------------------------------------------------------------------

@router.get("/visions")
async def list_visions(user: dict = Depends(get_current_user)):
    """Visions for current user (simple list)."""
    return get_visions(user["id"])


@router.get("/visions/all")
async def list_all_visions(user: dict = Depends(get_current_user)):
    """All visions with user info — admins see everyone, users see own."""
    if is_admin(user):
        return get_all_visions_with_user()
    return get_visions_with_user(user["id"])


@router.post("/visions")
async def save_vision(req: VisionCreate, user: dict = Depends(get_current_user)):
    return create_vision(
        user_id=user["id"],
        question=req.question,
        sql_generated=req.sql_generated,
        label=req.label,
    )


@router.put("/visions/{vision_id}")
async def update_vision(vision_id: int, req: VisionUpdate, user: dict = Depends(get_current_user)):
    uid = 0 if is_admin(user) else user["id"]
    question = req.question.strip() if isinstance(req.question, str) else None
    update_vision_meta(vision_id, uid, req.label, question)
    return {"success": True}


@router.delete("/visions/{vision_id}")
async def remove_vision(vision_id: int, user: dict = Depends(get_current_user)):
    uid = 0 if is_admin(user) else user["id"]
    delete_vision(vision_id, uid)
    return {"success": True}

@router.put("/visions/{vision_id}/sql")
async def update_vision_sql(vision_id: int, data: dict, user: dict = Depends(get_current_user)):
    """Atualiza o SQL salvo de uma visão. Remove LIMIT automaticamente."""
    import re as _re
    sql = (data.get("sql_generated") or "").strip()
    if not sql:
        raise HTTPException(400, "SQL não pode ser vazio.")
 
    # Remove LIMIT ao salvar (visões devem retornar dados completos)
    sql_clean = _re.sub(r'\s+LIMIT\s+\d+\s*;?\s*$', '', sql, flags=_re.IGNORECASE).strip()
 
    conn = get_sync_connection()
    try:
        # Só o dono (ou admin) pode editar
        row = conn.execute(
            "SELECT user_id FROM saved_visions WHERE id = ?", (vision_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Visão não encontrada.")
        if not is_admin(user) and row[0] != user["id"]:
            raise HTTPException(403, "Sem permissão para editar esta visão.")
 
        conn.execute(
            "UPDATE saved_visions SET sql_generated = ? WHERE id = ?",
            (sql_clean, vision_id)
        )
        conn.commit()
        return {"success": True, "sql_generated": sql_clean}
    finally:
        conn.close()
 

@router.get("/visions/export")
async def export_visions(user: dict = Depends(get_current_user)):
    import pandas as pd
    if is_admin(user):
        visions = get_all_visions_with_user()
    else:
        visions = get_visions_with_user(user["id"])
    rows = [
        {
            "label":         v.get("label", ""),
            "question":      v["question"],
            "sql_generated": v.get("sql_generated", ""),
            "user":          v.get("display_name") or v.get("login", ""),
            "created_at":    v.get("created_at", ""),
        }
        for v in visions
    ]
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=visoes_salvas.xlsx"},
    )


@router.post("/visions/import")
async def import_visions_route(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    import pandas as pd
    data = await file.read()
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "question":      str(row.get("question", row.get("pergunta", ""))).strip(),
            "label":         str(row.get("label",    row.get("rótulo", row.get("rotulo", "")))).strip(),
            "sql_generated": str(row.get("sql_generated", row.get("sql", ""))).strip(),
        })
    return import_visions_db(user["id"], rows)

# ---------------------------------------------------------------------------
# Cockpit
# ---------------------------------------------------------------------------

@router.get("/cockpit")
async def get_cockpit(user: dict = Depends(get_current_user)):
    return get_cockpit_tiles(user["id"])


@router.post("/cockpit")
async def create_cockpit_tile(req: CockpitTileCreate, user: dict = Depends(get_current_user)):
    try:
        return add_cockpit_tile(
            user_id=user["id"],
            vision_id=req.vision_id,
            chart_type=req.chart_type,
            x_field=req.x_field,
            y_field=req.y_field,
            agg=req.agg,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/cockpit/reorder")
async def reorder_tiles(req: CockpitReorder, user: dict = Depends(get_current_user)):
    reorder_cockpit_tiles(user["id"], req.tile_ids)
    return {"success": True}


@router.put("/cockpit/{tile_id}")
async def update_tile(tile_id: int, req: CockpitTileUpdate, user: dict = Depends(get_current_user)):
    update_cockpit_tile(tile_id, user["id"], **req.model_dump(exclude_none=True))
    return {"success": True}


@router.delete("/cockpit/{tile_id}")
async def remove_cockpit_tile(tile_id: int, user: dict = Depends(get_current_user)):
    delete_cockpit_tile(tile_id, user["id"])
    return {"success": True}


@router.post("/cockpit/insights")
async def cockpit_insights(data: dict, user: dict = Depends(get_current_user)):
    """Generate AI insights for cockpit tiles: individual + combined + recommendations."""
    import json as _json
    import pandas as _pd
    import numpy as _np
    # from langchain_openai import ChatOpenAI as _ChatOpenAI
    from app.services.llm_factory import make_chat_llm

    tiles_raw = data.get("tiles", [])
    if not tiles_raw:
        return {"error": "Nenhum dado de tile disponível."}

    # Build concise context for each tile
    tiles_context = []
    for t in tiles_raw:
        rows    = t.get("rows", [])
        columns = t.get("columns", [])
        label   = t.get("label") or t.get("question", "Sem título")
        ct      = t.get("chart_type", "bar")
        xf      = t.get("x_field", "")
        yf      = t.get("y_field", "")
        sql     = t.get("sql", "") or ""
        if not rows:
            continue

        # Numeric summary (com dispersão + outliers de Tukey)
        num_stats = {}
        for col in columns:
            try:
                vals = [float(r[col]) for r in rows if r[col] not in (None, "")]
            except (ValueError, TypeError):
                continue
            if not vals:
                continue
            arr = _np.array(vals, dtype=float)
            total = float(arr.sum())
            mean  = float(arr.mean())
            std   = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
            cv    = round(std / mean * 100, 2) if mean else None
            q1    = float(_np.percentile(arr, 25))
            q3    = float(_np.percentile(arr, 75))
            iqr   = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = int(((arr < lo) | (arr > hi)).sum())
            num_stats[col] = {
                "total":      round(total, 4),
                "mean":       round(mean, 4),
                "min":        round(float(arr.min()), 4),
                "max":        round(float(arr.max()), 4),
                "std":        round(std, 4),
                "cv_percent": cv,
                "outliers":   outliers,
            }

        # Top-5 category frequencies (first non-numeric col)
        cat_freq = {}
        cat_cols = [c for c in columns if c not in num_stats]
        if cat_cols:
            from collections import Counter
            freq = Counter(str(r.get(cat_cols[0], "")) for r in rows)
            cat_freq = dict(freq.most_common(5))

        tiles_context.append({
            "label":       label,
            "chart_type":  ct,
            "x_field":     xf,
            "y_field":     yf,
            "n_rows":      len(rows),
            "columns":     columns,
            "numeric":     num_stats,
            "top_categories": cat_freq,
            "source_tables": tables_in_sql(sql),
            "sample":      rows[:8],
        })

    if not tiles_context:
        return {"error": "Nenhum dado válido para análise."}

    # ── Enriquecimento por Catálogo de Dados ──────────────────────────────
    # Tabelas por trás dos tiles → contexto de negócio + relacionamentos.
    involved_tables = sorted({tb for t in tiles_context for tb in t.get("source_tables", [])})
    catalog_block = build_cockpit_catalog_context(involved_tables) if involved_tables else ""
    catalog_section = (
        "\n## Contexto de Negócio (Catálogo de Dados)\n"
        "Fonte de verdade sobre o significado das colunas, qualidade, PII e "
        "métricas canônicas (KPIs). Prefira estes termos a inferir pelo nome.\n"
        f"{catalog_block}\n"
    ) if catalog_block else ""

    rel_section = ""
    if len(involved_tables) >= 2:
        try:
            _summary = get_catalog_summary()
            _rels = [
                r for r in (_summary.get("relationships") or [])
                if r.get("source_table") in involved_tables
                and r.get("target_table") in involved_tables
            ]
            if _rels:
                _lines = [
                    f"- {r['source_table']}.{r['source_column']} ↔ "
                    f"{r['target_table']}.{r['target_column']} "
                    f"(confiança {round((r.get('confidence') or 0) * 100)}%)"
                    for r in _rels
                ]
                rel_section = (
                    "\n## Relacionamentos entre Tabelas\n"
                    "Quando ≥2 tiles usam tabelas relacionadas abaixo, proponha ao "
                    "menos UMA análise combinada que cruze (JOIN) essas tabelas.\n"
                    + "\n".join(_lines) + "\n"
                )
        except Exception:
            rel_section = ""

    prompt = f"""Você é um analista de dados sênior. Analise os dados do Cockpit abaixo e gere insights precisos em português brasileiro.

## Dados do Cockpit ({len(tiles_context)} tiles)

{_json.dumps(tiles_context, ensure_ascii=False, default=str, indent=2)}
{catalog_section}{rel_section}
## Tarefa

Retorne SOMENTE JSON válido (sem markdown, sem texto extra) com EXATAMENTE esta estrutura:

{{
  "individual_insights": [
    {{
      "label": "nome exato do tile (igual ao campo label acima)",
      "insight": "insight analítico específico em 2-3 frases com números reais dos dados",
      "status": "positive|negative|neutral|alert",
      "key_metric": "valor ou variação principal — ex: R$ 1,2M total, crescimento 18%"
    }}
  ],
  "combined_analysis": {{
    "summary": "análise integrada de 3-4 frases conectando os indicadores e o que eles revelam juntos",
    "correlations": [
      "descrição de correlação observada entre tiles, com dados"
    ],
    "patterns": [
      "padrão de comportamento identificado"
    ],
    "risks": [
      "risco potencial identificado com base nos dados"
    ],
    "opportunities": [
      "oportunidade identificada"
    ]
  }},
  "data_caveats": [
    "ressalva de qualidade/completude ou conformidade PII/LGPD baseada no Catálogo — ex: 'vr_salario é PII sensível: evite expor valores individuais (LGPD)' ou 'coluna X com 62% de completude: interprete agregações com cautela'. Use [] se não houver."
  ],
  "recommendations": [
    {{
      "title": "título curto (máx 6 palavras)",
      "description": "o que esta análise revelará (1 frase)",
      "query": "pergunta completa em linguagem natural para o agente SQL executar"
    }}
  ]
}}

Regras críticas:
- individual_insights: um objeto por tile, na mesma ordem dos tiles
- status: positive=bom resultado, negative=resultado ruim/queda, alert=atenção necessária, neutral=informativo
- correlations, patterns, risks, opportunities: entre 1 e 3 itens cada
- recommendations: entre 3 e 5 itens, queries específicas e acionáveis baseadas nos dados reais
- Insights com números reais extraídos dos dados — use também desvio-padrão, coeficiente de variação (cv_percent) e nº de outliers quando relevante
- Se houver "Contexto de Negócio (Catálogo)": use as descrições e ancore as recomendações nos KPIs canônicos listados; nomeie as colunas pelo significado de negócio, não pelo código
- Se houver "Relacionamentos entre Tabelas": inclua em recommendations ao menos UMA análise que cruze (JOIN) as tabelas relacionadas, com a pergunta NL correspondente
- data_caveats: liste ressalvas de qualidade (completude baixa) e de PII/LGPD com base no Catálogo; [] se não houver
- Retorne APENAS o JSON, sem nenhum texto antes ou depois
"""

    try:
        # llm = _ChatOpenAI(model=settings.openai_model,api_key=settings.openai_api_key,temperature=0.3,)
        llm = make_chat_llm(temperature=0.3, role="api_ai")
        response = llm.invoke(prompt)
        content  = response.content.strip()

        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
            content = content.strip()

        result = _json.loads(content)
        return result

    except _json.JSONDecodeError as e:
        return {"error": f"JSON inválido gerado pela IA: {str(e)[:100]}"}
    except Exception as e:
        return {"error": f"Erro ao gerar insights: {str(e)[:200]}"}

@router.get("/json-sources")
async def list_json_sources(user: dict = Depends(get_current_user)):
    return get_all_json_sources()
 
 
@router.post("/json-sources")
async def create_json_source_route(data: dict, user: dict = Depends(require_admin)):
    name = (data.get("name") or "").strip()
    url_template = (data.get("url_template") or "").strip()
    table_name_raw = (data.get("table_name") or "").strip()
    if not name or not url_template or not table_name_raw:
        raise HTTPException(400, "name, url_template e table_name são obrigatórios.")
    # Sanitize table name
    import re as _re
    table_name = _re.sub(r"[^\w]", "_", table_name_raw).strip("_").lower()
    if not table_name or table_name[0].isdigit():
        table_name = f"json_{table_name}"
    try:
        return db_create_json_source(
            name=name,
            url_template=url_template,
            table_name=table_name,
            json_path=data.get("json_path", ""),
            date_format=data.get("date_format", "yyyy-MM-dd"),
            http_headers=json.dumps(data.get("http_headers") or {}),
            append_mode=1 if data.get("append_mode") else 0,
            datamart_id=data.get("datamart_id") or None,
            description=data.get("description", ""),
        )
    except Exception as e:
        raise HTTPException(400, str(e))
 
 
@router.put("/json-sources/{source_id}")
async def update_json_source_route(source_id: int, data: dict, user: dict = Depends(require_admin)):
    src = get_json_source_by_id(source_id)
    if not src:
        raise HTTPException(404, "Fonte JSON não encontrada.")
    import re as _re
    updates = {}
    for field in ("name", "url_template", "json_path", "date_format", "description"):
        if field in data:
            updates[field] = data[field]
    if "table_name" in data and data["table_name"]:
        tn = _re.sub(r"[^\w]", "_", data["table_name"]).strip("_").lower()
        updates["table_name"] = tn
    if "http_headers" in data:
        updates["http_headers"] = json.dumps(data["http_headers"] or {})
    if "append_mode" in data:
        updates["append_mode"] = 1 if data["append_mode"] else 0
    if "datamart_id" in data:
        updates["datamart_id"] = data["datamart_id"] or None
    db_update_json_source(source_id, **updates)
    return {"success": True}
 
 
@router.delete("/json-sources/{source_id}")
async def delete_json_source_route(source_id: int, user: dict = Depends(require_admin)):
    src = get_json_source_by_id(source_id)
    if not src:
        raise HTTPException(404, "Fonte JSON não encontrada.")
    db_delete_json_source(source_id)
    return {"success": True}
 
 
@router.post("/json-sources/{source_id}/execute")
async def execute_json_source(source_id: int, data: dict = {}, user: dict = Depends(require_admin)):
    src = get_json_source_by_id(source_id)
    if not src:
        raise HTTPException(404, "Fonte JSON não encontrada.")
 
    # Resolve dates
    date_start_raw = data.get("date_start") or _date.today().isoformat()
    date_end_raw   = data.get("date_end")   or _date.today().isoformat()
    fmt = src.get("date_format", "yyyy-MM-dd")
 
    try:
        ds = _date.fromisoformat(date_start_raw)
        de = _date.fromisoformat(date_end_raw)
    except ValueError:
        raise HTTPException(400, "Formato de data inválido. Use yyyy-MM-dd.")
 
    date_start_str = format_date(ds, fmt)
    date_end_str   = format_date(de, fmt)
 
    url = resolve_url(src["url_template"], date_start_str, date_end_str)
 
    try:
        headers = json.loads(src.get("http_headers") or "{}")
    except (json.JSONDecodeError, TypeError):
        headers = {}
 
    result = fetch_and_import_json(
        url=url,
        table_name=src["table_name"],
        json_path=src.get("json_path", ""),
        append=bool(src.get("append_mode")),
        http_headers=headers,
        datamart_id=src.get("datamart_id"),
    )
 
    if "error" not in result:
        from datetime import datetime as _dt
        db_update_json_source(
            source_id,
            last_imported_at=_dt.utcnow().isoformat(),
            last_rows_imported=result.get("rows_imported", 0),
        )
 
    return {**result, "url_resolved": url}
 
 
@router.post("/json-sources/preview")
async def preview_json_source_route(data: dict, user: dict = Depends(require_admin)):
    url_template = (data.get("url_template") or "").strip()
    if not url_template:
        raise HTTPException(400, "url_template obrigatório.")
 
    fmt = data.get("date_format", "yyyy-MM-dd")
    date_start_raw = data.get("date_start") or _date.today().isoformat()
    date_end_raw   = data.get("date_end")   or _date.today().isoformat()
 
    try:
        ds = _date.fromisoformat(date_start_raw)
        de = _date.fromisoformat(date_end_raw)
    except ValueError:
        raise HTTPException(400, "Formato de data inválido.")
 
    url = resolve_url(url_template, format_date(ds, fmt), format_date(de, fmt))
 
    try:
        headers = json.loads(data.get("http_headers") or "{}")
    except (json.JSONDecodeError, TypeError):
        headers = {}
 
    result = preview_json_url(
        url=url,
        json_path=data.get("json_path", ""),
        http_headers=headers,
        max_rows=5,
    )
    return {**result, "url_resolved": url}
 
 
@router.get("/json-sources/date-formats")
async def get_date_formats(user: dict = Depends(get_current_user)):
    from app.services.json_import_service import DATE_FORMATS
    return list(DATE_FORMATS.keys())
 
 
# ── Export / Import das fontes ────────────────────────────────────────────
 
@router.get("/json-sources/export")
async def export_json_sources(user: dict = Depends(require_admin)):
    import pandas as pd
    sources = get_all_json_sources()
    rows = [
        {
            "name":          s["name"],
            "url_template":  s["url_template"],
            "table_name":    s["table_name"],
            "json_path":     s.get("json_path", ""),
            "date_format":   s.get("date_format", "yyyy-MM-dd"),
            "http_headers":  s.get("http_headers", "{}"),
            "append_mode":   s.get("append_mode", 0),
            "description":   s.get("description", ""),
        }
        for s in sources
    ]
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=json_sources_export.xlsx"},
    )
 
@router.post("/json-sources/import")
async def import_json_sources(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    import pandas as pd
    data = await file.read()
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    created, errors = [], []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        url_template = str(row.get("url_template", "")).strip()
        table_name = str(row.get("table_name", "")).strip()
        if not name or not url_template or not table_name:
            errors.append(f"Linha inválida: name/url_template/table_name obrigatórios")
            continue
        try:
            db_create_json_source(
                name=name,
                url_template=url_template,
                table_name=table_name,
                json_path=str(row.get("json_path", "") or "").strip(),
                date_format=str(row.get("date_format", "yyyy-MM-dd") or "yyyy-MM-dd"),
                http_headers=str(row.get("http_headers", "{}") or "{}"),
                append_mode=int(row.get("append_mode", 0) or 0),
                description=str(row.get("description", "") or "").strip(),
            )
            created.append(name)
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
    return {"created": created, "errors": errors, "total": len(created)}

# ---------------------------------------------------------------------------
# Data Products (ODPS)
# ---------------------------------------------------------------------------
 
@router.get("/data-products")
async def list_data_products(user: dict = Depends(get_current_user)):
    return get_all_data_products()
 
 
@router.get("/data-products/export/excel")
async def export_data_products(user: dict = Depends(require_admin)):
    import pandas as pd
    products = get_all_data_products()
    rows = []
    for p in products:
        rows.append({
            "name": p["name"],
            "display_name": p.get("display_name", ""),
            "version": p.get("version", ""),
            "status": p.get("status", ""),
            "domain": p.get("domain", ""),
            "purpose": p.get("purpose", ""),
            "business_value": p.get("business_value", ""),
            "consumers": json.dumps(p.get("consumers", []), ensure_ascii=False),
            "owner_team": p.get("owner_team", ""),
            "owner_email": p.get("owner_email", ""),
            "classification": p.get("classification", ""),
            "compliance": json.dumps(p.get("compliance", []), ensure_ascii=False),
            "value_layer": p.get("value_layer", ""),
            "consumption_type": p.get("consumption_type", ""),
            "sla_freshness": p.get("sla_freshness", ""),
            "sla_availability": p.get("sla_availability", ""),
            "nomenclature": p.get("nomenclature", ""),
            "created_by": p.get("created_by", ""),
            "created_at": p.get("created_at", ""),
        })
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=data_products_export.xlsx"},
    )
 
 
@router.post("/data-products/import")
async def import_data_products(file: UploadFile = File(...), request: Request = None, user: dict = Depends(require_admin)):
    import pandas as pd
    data = await file.read()
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    current_user = getattr(request.state, "user", None) if request else None
    created_by = current_user["login"] if current_user else ""
    created, errors = [], []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        if not name or len(name) < 2:
            errors.append(f"Nome inválido: '{name}'")
            continue
        product_data = {
            "name": name,
            "display_name": str(row.get("display_name", name)).strip(),
            "version": str(row.get("version", "1.0.0")).strip(),
            "status": str(row.get("status", "draft")).strip(),
            "domain": str(row.get("domain", "")).strip(),
            "purpose": str(row.get("purpose", "")).strip(),
            "business_value": str(row.get("business_value", "")).strip(),
            "owner_team": str(row.get("owner_team", "")).strip(),
            "owner_email": str(row.get("owner_email", "")).strip(),
            "classification": str(row.get("classification", "internal")).strip(),
            "value_layer": str(row.get("value_layer", "refined")).strip(),
            "consumption_type": str(row.get("consumption_type", "analytical")).strip(),
            "sla_freshness": str(row.get("sla_freshness", "")).strip(),
            "sla_availability": str(row.get("sla_availability", "")).strip(),
            "created_by": created_by,
        }
        for k, v in product_data.items():
            if v == "nan":
                product_data[k] = ""
        for jf in ("consumers", "compliance"):
            raw = str(row.get(jf, "[]")).strip()
            if raw == "nan":
                raw = "[]"
            try:
                product_data[jf] = json.loads(raw)
            except Exception:
                product_data[jf] = []
        try:
            db_create_data_product(product_data)
            created.append(name)
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
    return {"created": created, "errors": errors, "total": len(created)}
 
 
@router.get("/data-products/{product_id}")
async def get_data_product(product_id: int, user: dict = Depends(get_current_user)):
    p = get_data_product_by_id(product_id)
    if not p:
        raise HTTPException(404, "Produto de dados não encontrado.")
    return p
 
 
@router.post("/data-products")
async def create_data_product_route(req: DataProductCreate, request: Request, user: dict = Depends(require_admin)):
    current_user = getattr(request.state, "user", None)
    data = req.model_dump()
    data["created_by"] = current_user["login"] if current_user else ""
    try:
        return db_create_data_product(data)
    except Exception as e:
        raise HTTPException(400, str(e))
 
 
@router.put("/data-products/{product_id}")
async def update_data_product_route(product_id: int, req: DataProductUpdate, user: dict = Depends(require_admin)):
    p = get_data_product_by_id(product_id)
    if not p:
        raise HTTPException(404, "Produto de dados não encontrado.")
    data = req.model_dump(exclude_none=True)
    db_update_data_product(product_id, data)
    return {"success": True}
 
 
@router.delete("/data-products/{product_id}")
async def delete_data_product_route(product_id: int, user: dict = Depends(require_admin)):
    p = get_data_product_by_id(product_id)
    if not p:
        raise HTTPException(404, "Produto de dados não encontrado.")
    db_delete_data_product(product_id)
    return {"success": True}
 
 
@router.put("/data-products/{product_id}/status")
async def transition_status_route(product_id: int, req: DataProductStatusTransition, user: dict = Depends(require_admin)):
    result = transition_data_product_status(product_id, req.new_status)
    if result is None:
        raise HTTPException(404, "Produto de dados não encontrado.")
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result
 
 
@router.get("/data-products/{product_id}/validate")
async def validate_product_route(product_id: int, user: dict = Depends(get_current_user)):
    return validate_data_product(product_id)


@router.post("/data-products/scan")
async def scan_data_products(data: dict = {}, request: Request = None, user: dict = Depends(require_admin)):
    """
    Escaneia tabelas do banco e gera sugestões de Produtos de Dados (ODPS).
    Usa LLM para inferir: nome, domínio, propósito, valor de negócio,
    classificação, camada, artefatos, output ports, regras de qualidade e SLA.
    
    Body opcional:
        tables: list[str]  — filtrar por nomes de tabelas (vazio = todas)
        include_catalog: bool — usar dados do catálogo se disponível (default: true)
    """
    import json as _json
    # from langchain_openai import ChatOpenAI as _ChatOpenAI
    from app.services.llm_factory import make_chat_llm
    from app.core.database import get_all_tables, get_sync_connection, INTERNAL_TABLES
 
    table_filter = data.get("tables", [])
    include_catalog = data.get("include_catalog", True)
 
    # ── Coletar informações das tabelas ───────────────────────────────────
    all_tables = get_all_tables()
    if table_filter:
        filter_set = set(table_filter)
        all_tables = [t for t in all_tables if t["name"] in filter_set]
 
    if not all_tables:
        return {"error": "Nenhuma tabela encontrada para escanear."}
 
    # Já existem produtos? Filtrar tabelas que já têm produto
    existing_products = get_all_data_products()
    existing_names = set()
    for p in existing_products:
        for art in (p.get("artifacts") or []):
            if isinstance(art, dict) and art.get("name"):
                existing_names.add(art["name"].lower())
            elif isinstance(art, str):
                existing_names.add(art.lower())
        # Também checar pelo nome do produto
        existing_names.add(p["name"].lower())
 
    conn = get_sync_connection()
    tables_context = []
    try:
        for table in all_tables:
            t_name = table["name"]
 
            # Coletar schema
            cols_info = []
            for col in table["columns"]:
                col_detail = {
                    "name": col["name"],
                    "type": col["type"],
                }
                cols_info.append(col_detail)
 
            # Amostra de dados (3 linhas)
            try:
                sample_rows = conn.execute(
                    f'SELECT * FROM "{t_name}" LIMIT 3'
                ).fetchall()
                sample_cols = [desc[0] for desc in conn.execute(f'SELECT * FROM "{t_name}" LIMIT 1').description or []]
                sample = [dict(zip(sample_cols, row)) for row in sample_rows]
            except Exception:
                sample = []
 
            # Cardinalidade por coluna
            col_cards = {}
            for col in table["columns"]:
                try:
                    card = conn.execute(
                        f'SELECT COUNT(DISTINCT "{col["name"]}") FROM "{t_name}" WHERE "{col["name"]}" IS NOT NULL'
                    ).fetchone()[0]
                    col_cards[col["name"]] = card
                except Exception:
                    col_cards[col["name"]] = 0
 
            # Catálogo (se disponível)
            catalog_info = None
            if include_catalog:
                try:
                    cat_row = conn.execute(
                        "SELECT description, domain, quality_score, entities, extras "
                        "FROM catalog_datasets WHERE table_name = ?",
                        (t_name,),
                    ).fetchone()
                    if cat_row:
                        catalog_info = {
                            "description": cat_row[0] or "",
                            "domain": cat_row[1] or "",
                            "quality_score": cat_row[2] or 0,
                            "entities": cat_row[3] or "[]",
                            "extras": cat_row[4] or "{}",
                        }
                except Exception:
                    pass
 
            # DataMarts associados
            dm_names = [d["name"] for d in table.get("datamarts", [])]
 
            already_exists = t_name.lower() in existing_names
 
            tables_context.append({
                "table_name": t_name,
                "row_count": table["row_count"],
                "columns": cols_info,
                "cardinality": col_cards,
                "sample": sample[:2],  # limitar para não estourar contexto
                "datamarts": dm_names,
                "catalog": catalog_info,
                "already_has_product": already_exists,
            })
    finally:
        conn.close()
 
    # Filtrar tabelas que já têm produto (mas incluir flag)
    new_tables = [t for t in tables_context if not t["already_has_product"]]
    if not new_tables and not table_filter:
        return {
            "suggestions": [],
            "skipped": len(tables_context),
            "message": "Todas as tabelas já possuem Produto de Dados associado.",
        }
 
    # Usar todas se filtro explícito, senão apenas novas
    scan_tables = tables_context if table_filter else (new_tables if new_tables else tables_context)
 
    # ── Prompt LLM ────────────────────────────────────────────────────────
    # Processar em batches de até 5 tabelas por chamada
    BATCH_SIZE = 5
    all_suggestions = []
 
    for i in range(0, len(scan_tables), BATCH_SIZE):
        batch = scan_tables[i:i + BATCH_SIZE]
        batch_context = _json.dumps(batch, ensure_ascii=False, default=str, indent=2)
 
        prompt = f"""Você é um Data Product Manager especialista em ODPS (Open Data Product Specification).
Analise as tabelas abaixo e gere sugestões de Produtos de Dados para cada uma.
 
## Tabelas para análise
 
{batch_context}
 
## Tarefa
 
Para CADA tabela, gere um objeto JSON com os campos ODPS:
 
{{
  "source_table": "nome_da_tabela_original",
  "name": "slug_kebab_case (ex: daily_revenue)",
  "display_name": "Nome de Negócio legível (ex: Faturamento Diário)",
  "domain": "domínio de negócio (billing, crm, network, finance, marketing, rh, operations, product)",
  "purpose": "2-3 frases explicando que problema resolve e para quem",
  "business_value": "impacto mensurável (ex: Redução de 40% no tempo de análise)",
  "consumers": ["time ou sistema consumidor 1", "time ou sistema 2"],
  "owner_team": "squad ou time responsável sugerido",
  "classification": "public|internal|restricted",
  "value_layer": "raw|refined|insight",
  "consumption_type": "analytical|operational|ml_ai",
  "artifacts": [
    {{"name": "nome_artefato", "type": "dataset|table|view|model", "versions": [{{"version": "1.0.0", "status": "prod"}}]}}
  ],
  "output_ports": [
    {{"name": "nome_porta", "dataType": "table|api|file", "contractId": "contract_001"}}
  ],
  "quality_rules": [
    {{"name": "regra_nome", "type": "completeness|uniqueness|freshness|validity", "threshold": "99%"}}
  ],
  "sla_freshness": "frequência sugerida (ex: 24h, 1h, diário)",
  "sla_availability": "percentual (ex: 99.9%)",
  "confidence": 0.85,
  "rationale": "1 frase explicando por que este produto foi sugerido"
}}
 
## Regras
- Analise os nomes de colunas, tipos, cardinalidade e amostras para inferir o domínio e propósito
- Se houver dados do catálogo (campo "catalog"), use a descrição e domínio já detectados
- Gere quality_rules baseadas nas colunas reais (ex: completeness para colunas obrigatórias)
- O campo "artifacts" deve referenciar a tabela original
- Sugira consumers realistas baseados no domínio
- confidence: 0.0 a 1.0 baseado na qualidade da inferência
- Retorne APENAS um JSON array válido, sem markdown, sem texto extra
- Se a tabela já tem produto (already_has_product=true), inclua com confidence 0.3 e note no rationale
 
## Output
JSON array com um objeto por tabela. Nada mais."""
 
        try:
            # llm = _ChatOpenAI(model=settings.openai_model,api_key=settings.openai_api_key,temperature=0.2,)
            llm = make_chat_llm(temperature=0.2, role="data_product_scan")
            response = llm.invoke(prompt)
            content = response.content.strip()
 
            # Limpar markdown fences
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content.rsplit("```", 1)[0]
                content = content.strip()
 
            batch_suggestions = _json.loads(content)
            if isinstance(batch_suggestions, dict):
                batch_suggestions = [batch_suggestions]
            all_suggestions.extend(batch_suggestions)
 
        except _json.JSONDecodeError as e:
            return {"error": f"JSON inválido gerado pela IA: {str(e)[:100]}"}
        except Exception as e:
            # Surface enough context that ops can diagnose without reading logs.
            etype = type(e).__name__
            msg = str(e).strip() or "(sem mensagem)"
            provider_hint = (settings.llm_general_provider or "?").lower()
            fallback_hint = (settings.llm_fallback_provider or "").lower()
            chain = provider_hint if not fallback_hint or fallback_hint == provider_hint else f"{provider_hint} → {fallback_hint}"
            return {"error": f"Erro ao gerar sugestões ({etype} via {chain}): {msg[:200]}"}
 
    # ── Enriquecer sugestões com metadados ────────────────────────────────
    for s in all_suggestions:
        # Garantir campos obrigatórios com defaults
        s.setdefault("version", "1.0.0")
        s.setdefault("status", "draft")
        s.setdefault("owner_email", "")
        s.setdefault("owner_role", "data product owner")
        s.setdefault("compliance", [])
        s.setdefault("input_ports", [])
        s.setdefault("tags", {})
 
        # Encontrar tabela original para dados extras
        src = s.get("source_table", "")
        table_info = next((t for t in tables_context if t["table_name"] == src), None)
        if table_info:
            s["_meta"] = {
                "row_count": table_info["row_count"],
                "col_count": len(table_info["columns"]),
                "columns": [c["name"] for c in table_info["columns"]],
                "datamarts": table_info["datamarts"],
                "already_has_product": table_info.get("already_has_product", False),
            }
 
    return {
        "suggestions": all_suggestions,
        "tables_scanned": len(scan_tables),
        "tables_skipped": len(tables_context) - len(scan_tables),
        "total_tables": len(tables_context),
    }
 
 
@router.post("/data-products/scan/save")
async def save_scanned_products(data: dict, request: Request = None, user: dict = Depends(require_admin)):
    """
    Salva múltiplas sugestões do scanner como Produtos de Dados.
    Body: { suggestions: [...] } — array de objetos ODPS do scanner.
    """
    suggestions = data.get("suggestions", [])
    if not suggestions:
        return {"error": "Nenhuma sugestão para salvar."}
 
    current_user = getattr(request.state, "user", None) if request else None
    created_by = current_user["login"] if current_user else ""
 
    created, errors = [], []
    for s in suggestions:
        name = (s.get("name") or "").strip()
        if not name or len(name) < 2:
            errors.append(f"Nome inválido: '{name}'")
            continue
 
        # Remover campos internos do scanner
        for key in ("source_table", "confidence", "rationale", "_meta"):
            s.pop(key, None)
 
        s["created_by"] = created_by
        s.setdefault("version", "1.0.0")
        s.setdefault("status", "draft")
 
        try:
            db_create_data_product(s)
            created.append(name)
        except Exception as e:
            errors.append(f"{name}: {str(e)}")
 
    return {
        "created": created,
        "errors": errors,
        "total": len(created),
    }


def _sanitize_filename(filename: str) -> str:
    base_name = Path(filename or "").name
    if not base_name or not SAFE_FILENAME.fullmatch(base_name):
        raise HTTPException(400, "Nome de arquivo inválido.")
    return base_name


def _safe_table_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise HTTPException(400, "Nome de tabela inválido")
    return name


# ---------------------------------------------------------------------------
# TDIA-CodeGen — módulo de Engenharia de Dados (Root/Admin/Engenheiro de Dados)
# P1a: leitura (SELECT/WITH) + export. Escrita/DDL e autorizador ficam na P1b.
# ---------------------------------------------------------------------------

@router.get("/codegen/scope")
async def codegen_scope(user: dict = Depends(require_codegen)):
    """DataMarts e DiamondLayers autorizados ao usuário (contexto do editor)."""
    if is_root(user):
        return {"datamarts": get_all_datamarts(), "diamond_layers": get_all_diamond_layers()}
    return {
        "datamarts": get_user_datamarts(user["id"]),
        "diamond_layers": get_user_diamond_layers(user["id"]),
    }


@router.post("/codegen/run")
async def codegen_run(req: dict, user: dict = Depends(require_codegen)):
    """Executa um script SQL do editor através do autorizador do módulo (P1b):
    leitura e escrita escopadas aos DataMarts/DiamondLayers do usuário; DROP/ALTER
    só em tabelas de posse; CREATE associa ao DataMart escolhido. Execução atômica;
    operações destrutivas exigem `confirm: true`."""
    from app.services.codegen_service import execute_script
    sql = (req.get("sql") or "").strip()
    if not sql:
        raise HTTPException(400, "Consulta vazia.")
    try:
        limit = int(req.get("result_limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    dm = req.get("target_datamart_id") or req.get("datamart_id")
    try:
        dm = int(dm) if dm not in (None, "", []) else None
    except (TypeError, ValueError):
        dm = None

    result = execute_script(
        sql, user, target_datamart_id=dm,
        confirm=bool(req.get("confirm")), result_limit=limit,
    )
    if "error" in result:
        return JSONResponse(status_code=400, content={"error": result["error"]})
    return result


@router.post("/codegen/export")
async def codegen_export(req: dict, user: dict = Depends(require_codegen)):
    """Exporta o resultado atual (linhas enviadas pelo cliente) em CSV/Excel/JSON."""
    import csv as _csv
    fmt = (req.get("format") or "csv").lower()
    columns = req.get("columns") or []
    rows = req.get("rows") or []
    fname = re.sub(r"[^A-Za-z0-9_.-]", "_", str(req.get("filename") or "tdia_codegen"))[:60] or "tdia_codegen"

    if fmt == "xlsx":
        content = export_to_excel_bytes({"rows": rows})
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    elif fmt == "json":
        content = json.dumps(rows, ensure_ascii=False, default=str, indent=2).encode("utf-8")
        media, ext = "application/json", "json"
    else:
        buf = io.StringIO()
        writer = _csv.DictWriter(
            buf,
            fieldnames=columns or (list(rows[0].keys()) if rows else []),
            extrasaction="ignore",
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        content = buf.getvalue().encode("utf-8-sig")  # BOM → Excel abre acentos corretamente
        media, ext = "text/csv", "csv"

    return StreamingResponse(
        io.BytesIO(content),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{fname}.{ext}"'},
    )


@router.get("/codegen/tables")
async def codegen_tables(user: dict = Depends(require_codegen)):
    """Tabelas criadas pelo usuário no módulo (lista 'Minhas Tabelas'). Root vê
    todas, com o login do dono."""
    conn = get_sync_connection()
    try:
        if is_root(user):
            cur = conn.execute(
                "SELECT ct.table_name, ct.datamart_id, d.name AS datamart_name, "
                "ct.created_at, u.login AS owner_login "
                "FROM codegen_tables ct "
                "LEFT JOIN datamarts d ON d.id = ct.datamart_id "
                "LEFT JOIN users u ON u.id = ct.owner_id "
                "ORDER BY ct.created_at DESC"
            )
        else:
            cur = conn.execute(
                "SELECT ct.table_name, ct.datamart_id, d.name AS datamart_name, ct.created_at "
                "FROM codegen_tables ct LEFT JOIN datamarts d ON d.id = ct.datamart_id "
                "WHERE ct.owner_id = ? ORDER BY ct.created_at DESC",
                (user["id"],),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# --- P2: Snippets (salvar/carregar) ---
@router.get("/codegen/snippets")
async def codegen_snippets_list(user: dict = Depends(require_codegen)):
    conn = get_sync_connection()
    try:
        cur = conn.execute(
            "SELECT id, name, sql, updated_at FROM codegen_snippets WHERE user_id = ? ORDER BY name",
            (user["id"],),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@router.post("/codegen/snippets")
async def codegen_snippets_save(req: dict, user: dict = Depends(require_codegen)):
    name = (req.get("name") or "").strip()
    sql = (req.get("sql") or "").strip()
    if not name or not sql:
        raise HTTPException(400, "Nome e SQL são obrigatórios.")
    conn = get_sync_connection()
    try:
        conn.execute(
            "INSERT INTO codegen_snippets (user_id, name, sql) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, name) DO UPDATE SET sql = EXCLUDED.sql, updated_at = CURRENT_TIMESTAMP",
            (user["id"], name[:120], sql),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.delete("/codegen/snippets/{snippet_id}")
async def codegen_snippets_delete(snippet_id: int, user: dict = Depends(require_codegen)):
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM codegen_snippets WHERE id = ? AND user_id = ?", (snippet_id, user["id"]))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# --- P2: Histórico de execuções (isolado do módulo) ---
@router.get("/codegen/runs")
async def codegen_runs_list(user: dict = Depends(require_codegen)):
    conn = get_sync_connection()
    try:
        cur = conn.execute(
            "SELECT id, sql, kind, row_count, created_at FROM codegen_runs "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user["id"],),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# --- P2: Schema para autocomplete (tabelas+colunas no escopo do usuário) ---
@router.get("/codegen/schema")
async def codegen_schema(user: dict = Depends(require_codegen)):
    from app.services.codegen_service import get_user_scope
    scope = get_user_scope(user)
    allowed = scope["allowed"]
    out: dict = {}
    for t in get_all_tables():
        if scope["root"] or (allowed is not None and t["name"].lower() in allowed):
            out[t["name"]] = [c["name"] for c in (t.get("columns") or [])]
    return {"tables": out}


# --- M2: Gerar código Python via motor Spec-Driven (técnica × padrão) ---
@router.post("/codegen/pycode")
async def codegen_pycode(req: dict, user: dict = Depends(require_codegen)):
    from app.services.codegen_pycodegen import render_spec
    sql = (req.get("sql") or "").strip()
    if not sql:
        raise HTTPException(400, "Escreva uma consulta no editor antes de gerar o código.")
    technique = (req.get("technique") or req.get("lib") or "pandas").lower()
    pattern = (req.get("pattern") or "script").lower()
    result = render_spec(sql, technique, pattern, req.get("options") or {})
    if "error" in result:
        return JSONResponse(status_code=400, content={"error": result["error"]})
    return {
        "code": result["code"],
        "filename": f"tdia_codegen_{result['technique']}_{result['pattern']}.py",
        "lib": result["technique"],
        "technique": result["technique"],
        "pattern": result["pattern"],
        "schema": result.get("schema", []),
    }


@router.get("/codegen/techniques")
async def codegen_techniques_inventory(user: dict = Depends(require_codegen)):
    """Inventário de técnicas e padrões disponíveis (para o seletor do editor)."""
    from app.services.codegen_pycodegen import list_inventory
    return list_inventory()


# --- M2.1: CRUD de Técnicas (autoria só Root/Admin) ---
@router.get("/codegen/admin/techniques")
async def codegen_admin_techniques_list(user: dict = Depends(require_admin)):
    from app.services.codegen_pycodegen import list_techniques_full
    return list_techniques_full()


@router.post("/codegen/admin/techniques")
async def codegen_admin_techniques_create(req: dict, user: dict = Depends(require_admin)):
    from app.services.codegen_pycodegen import create_technique
    r = create_technique(req, created_by=user.get("login", ""))
    if "error" in r:
        return JSONResponse(status_code=400, content={"error": r["error"]})
    return r


@router.put("/codegen/admin/techniques/{tid}")
async def codegen_admin_techniques_update(tid: int, req: dict, user: dict = Depends(require_admin)):
    from app.services.codegen_pycodegen import update_technique
    r = update_technique(tid, req)
    if "error" in r:
        return JSONResponse(status_code=400, content={"error": r["error"]})
    return r


@router.delete("/codegen/admin/techniques/{tid}")
async def codegen_admin_techniques_delete(tid: int, user: dict = Depends(require_admin)):
    from app.services.codegen_pycodegen import delete_technique
    return delete_technique(tid)
