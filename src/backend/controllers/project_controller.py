from typing import Optional

from fastapi import Form, Depends, Request, APIRouter, HTTPException
from sqlalchemy import asc, desc
from fastapi.responses import HTMLResponse

from backend.models import (
    ProjectCreateModel,
    ProjectResponseModel,
)
from database.models import project_mapper  # noqa F401
from core.models.task import Task
from core.models.user import User
from core.models.project import Project
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
    pagination = calculate_pagination(total=0, page=1, per_page=15)
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


@project_router.put("/{project_id}", response_model=ProjectResponseModel)
def update_project_endpoint(
    project_id: str,
    project_update: ProjectCreateModel,
    session: ISession = Depends(get_session),
):
    return update_project(project_id, project_update, session)


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
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint to retrieve all projects with pagination.

    - If the current user is an admin, retrieves all projects.
    - Otherwise, retrieves projects associated with the current user.
    """
    order_by = []
    if sort:
        sort_column = getattr(Project, sort, None)
        if sort_column:
            if order and order.lower() == "desc":
                order_by.append(desc(sort_column))
            else:
                order_by.append(asc(sort_column))

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    if is_admin(current_user):
        projects, pagination = get_all_projects(session, pagination)
    else:
        projects, pagination = get_users_projects(
            current_user.id, session, pagination
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
