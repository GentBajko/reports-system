import re
from typing import Optional

from loguru import logger
from fastapi import (
    Form,
    Query,
    Depends,
    Request,
    Response,
    APIRouter,
    HTTPException,
)
from sqlalchemy import asc, desc
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.models import (
    ProjectCreateModel,
    ProjectResponseModel,
)
from database.models import project_mapper  # noqa F401
from core.models.task import Task
from core.models.user import User
from backend.dependencies import get_session
from backend.utils.templates import templates
from backend.utils.pagination import calculate_pagination
from backend.dependencies.auth import (
    is_admin,
    validate_csrf,
    get_current_user,
)
from backend.models.pagination import Pagination
from backend.views.project_view import (
    get_project,
    create_project,
    update_project,
    upsert_project,
    get_all_projects,
    get_project_tasks,
    get_users_projects,
    get_user_by_project,
    assign_project_to_user,
    remove_user_from_project,
)
from database.interfaces.session import ISession

project_router = APIRouter(prefix="/project")


@project_router.get("/create", response_class=HTMLResponse)
def create_project_page(
    request: Request, current_user: User = Depends(get_current_user)
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")
    return templates.TemplateResponse(
        "project/create.html", {"request": request}
    )


@project_router.post("/")
async def create_project_endpoint(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    send_email: bool = Form(...),
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    csrf_protect=Depends(validate_csrf),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")
    project = ProjectCreateModel(
        name=name,
        email=email,
        send_email=send_email,
    )
    project = create_project(project, session)
    return templates.TemplateResponse(
        "project/detail.html", {"request": request, "project": project}
    )


@project_router.get("/options", response_class=HTMLResponse)
def get_project_options(
    request: Request,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    pagination = calculate_pagination(total=0, page=1, per_page=300)
    projects = (
        get_all_projects(session, pagination)[0]
        if is_admin(current_user)
        else [
            project
            for project in get_users_projects(
                current_user.id, session, pagination
            )[0]
        ]
    )

    options_html = ""
    for project in projects:
        options_html += f'<option value="{project.id}">{project.name}</option>'

    return HTMLResponse(content=options_html)


@project_router.get("/{project_id}", response_class=HTMLResponse)
def get_project_endpoint(
    request: Request,
    project_id: str,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    project = get_project(session, id=project_id)
    pagination = calculate_pagination(total=0, page=1, per_page=15)
    user_projects = get_users_projects(current_user.id, session, pagination)
    project_ids = [project.id for project in user_projects[0]]

    if not is_admin(current_user) and project_id not in project_ids:
        raise HTTPException(status_code=403, detail="Access forbidden")
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return templates.TemplateResponse(
        "project/detail.html", {"request": request, "project": project}
    )


@project_router.get("/{project_id}/edit", response_model=ProjectResponseModel)
def update_project_page(
    Request: Request,
    project_id: str,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")

    project = get_project(session, id=project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return templates.TemplateResponse(
        "project/edit.html", {"project": project, "request": Request}
    )


@project_router.put("/{project_id}", response_class=HTMLResponse)
async def update_project_endpoint(
    request: Request,
    project_id: str,
    name: str = Form(...),
    send_email: bool = Form(False),
    archived: bool = Form(False),
    email: str = Form(""),
    csrftoken: str = Form(""),
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")

    project_update = ProjectCreateModel(
        name=name, send_email=send_email, archived=archived, email=email
    )

    update_project(project_id, project_update, session)

    headers = {"HX-Redirect": f"/project/{project_id}"}
    return Response(status_code=200, headers=headers)


@project_router.post("/upsert", response_model=ProjectResponseModel)
def upsert_project_endpoint(
    project: ProjectCreateModel, session: ISession = Depends(get_session)
):
    return upsert_project(project, session)


@project_router.get("/", response_class=HTMLResponse)
def get_all_projects_endpoint(
    request: Request,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    combined_filters: Optional[str] = Query(None),
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint to retrieve all projects with pagination.

    - If the current user is an admin, retrieves all projects.
    - Otherwise, retrieves projects associated with the current user.
    """
    filter_mapping = {
        "Name": "name",
        "Email": "email",
        "Send Email": "send_email",
        "Archived": "archived",
    }
    order_by = []
    if sort:
        sort_column = filter_mapping.get(sort)
        if sort_column:
            if order and order.lower() == "desc":
                order_by.append(desc(sort_column))
            else:
                order_by.append(asc(sort_column))

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    filters = {}


    operator_map = {
        ">": "gt",
        "<": "lt",
        ">=": "gte",
        "<=": "lte",
        "=": "eq",
        "contains": "contains",
    }

    if combined_filters:
        mini_filters = [
            f.strip() for f in combined_filters.split(",") if f.strip()
        ]
        for mf in mini_filters:
            if " contains " in mf.lower():
                parts = re.split(r"\s+contains\s+", mf, flags=re.IGNORECASE)
                if len(parts) == 2:
                    field_part = parts[0].strip().title()
                    value_part = parts[1].strip()
                    db_field = filter_mapping.get(field_part)
                    if db_field:
                        filters[f"{db_field}__contains"] = value_part
                continue

            pattern = r"^(?P<field>.*?)\s*(?P<op>>=|<=|>|<|=)\s*(?P<value>.*)$"
            match = re.match(pattern, mf)
            if match:
                field_part = match.group("field").strip()
                op_part = match.group("op").strip()
                value_part = match.group("value").strip()
                # Convert True/False to 1/0
                if value_part.lower() == "yes":
                    value_part = 1
                elif value_part.lower() == "no":
                    value_part = 0
                db_field = filter_mapping.get(field_part)
                if db_field and op_part in operator_map:
                    op_key = operator_map[op_part]
                    filters[f"{db_field}__{op_key}"] = value_part
            else:
                if search_field := filter_mapping.get("Task Name"):
                    filters[search_field + "__contains"] = mf
                else:
                    logger.warning(
                        f"Could not find field for search term: {mf}"
                    )

    if is_admin(current_user):
        projects, pagination = get_all_projects(session, pagination, **filters)
    else:
        projects, pagination = get_users_projects(
            current_user.id, session, pagination, **filters
        )

    table_headers = [
        "Name",
        "Email",
        "Send Email",
        "Archived",
        "Developers",
        "Tasks",
    ]

    return templates.TemplateResponse(
        "project/projects.html",
        {
            "request": request,
            "headers": table_headers,
            "data": projects,
            "pagination": pagination,
            "entity": "project",
            "current_sort": sort,
            "current_order": order,
            "allowed_filter_fields": [
                "Name",
                "Email",
                "Send Email",
                "Archived",
            ],
        },
    )


@project_router.get("/{project_id}/assign", response_class=HTMLResponse)
def assign_project_to_user_page(
    request: Request,
    project_id: str,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")
    project = get_project(session, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        "project/assign.html", {"request": request, "project": project}
    )


@project_router.post(
    "/{project_id}/assign", response_model=ProjectResponseModel
)
def assign_project_to_user_endpoint(
    request: Request,
    project_id: str,
    user_id: str = Form(...),
    session: ISession = Depends(get_session),
):
    assignment = assign_project_to_user(project_id, user_id, session)
    return templates.TemplateResponse(
        "project/detail.html", {"project": assignment, "request": request}
    )


@project_router.get("/{project_id}/remove_user", response_class=HTMLResponse)
def remove_user_from_project_page(
    request: Request,
    project_id: str,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 50,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint to retrieve users associated with a specific project with pagination.
    """
    order_by = []
    if sort:
        sort_column = getattr(User, sort, None)
        if sort_column:
            if order and order.lower() == "desc":
                order_by.append(desc(sort_column))
            else:
                order_by.append(asc(sort_column))
        else:
            raise HTTPException(
                status_code=400, detail=f"Invalid sort field: {sort}"
            )

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    users, pagination = get_user_by_project(session, project_id, pagination)

    options_html = "".join(
        f'<option value="{user.id}">{user.full_name} ({user.email})</option>'
        for user in users
    )

    context = {
        "request": request,
        "project": {"id": project_id},
        "options": options_html,
        "pagination": pagination,
        "entity": "user",
        "current_sort": sort,
        "current_order": order,
    }
    return templates.TemplateResponse("project/remove_user.html", context)


@project_router.post(
    "/{project_id}/remove_user", response_model=ProjectResponseModel
)
def remove_user_from_project_endpoint(
    request: Request,
    project_id: str,
    user_id: str = Form(...),
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")
    remove_user_from_project(project_id, user_id, session)
    return RedirectResponse(url=f"/project/{project_id}", status_code=303)


@project_router.get("/{project_id}/users", response_class=HTMLResponse)
def get_user_by_project_endpoint(
    request: Request,
    project_id: str,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint to retrieve users associated with a specific project with pagination.
    """
    order_by = []
    if sort:
        sort_column = getattr(User, sort, None)
        if sort_column:
            if order and order.lower() == "desc":
                order_by.append(desc(sort_column))
            else:
                order_by.append(asc(sort_column))
        else:
            raise HTTPException(
                status_code=400, detail=f"Invalid sort field: {sort}"
            )

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    users, pagination = get_user_by_project(session, project_id, pagination)

    context = {
        "request": request,
        "headers": ["Full Name", "Email", "Projects", "Tasks"],
        "data": users,
        "pagination": pagination,
        "entity": "user",
        "current_sort": sort,
        "current_order": order,
    }
    return templates.TemplateResponse("user/users.html", context)


@project_router.get("/{project_id}/tasks", response_class=HTMLResponse)
def get_tasks_by_project_endpoint(
    request: Request,
    project_id: str,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint to retrieve tasks associated with a specific project with pagination.
    """
    order_by = []
    if sort:
        sort_column = getattr(Task, sort, None)
        if sort_column:
            if order and order.lower() == "desc":
                order_by.append(desc(sort_column))
            else:
                order_by.append(asc(sort_column))
        else:
            raise HTTPException(
                status_code=400, detail=f"Invalid sort field: {sort}"
            )

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    tasks, pagination = get_project_tasks(session, project_id, pagination)

    context = {
        "request": request,
        "headers": ["Title", "Hours Required", "Description", "Status"],
        "data": tasks,
        "pagination": pagination,
        "entity": "task",
        "current_sort": sort,
        "current_order": order,
    }
    return templates.TemplateResponse("task/tasks.html", context)
