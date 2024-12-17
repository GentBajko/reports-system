import re
from typing import Optional

from loguru import logger
from fastapi import Form, Query, Depends, Request, APIRouter, HTTPException
from sqlalchemy import asc, desc
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.models import (
    UserCreateModel,
    UserResponseModel,
)
from core.models.log import Log
from database.models import user_mapper  # noqa F401
from core.models.task import Task
from core.models.user import User
from core.models.project import Project
from backend.dependencies import get_session
from backend.utils.templates import templates
from backend.views.user_view import (
    get_user,
    create_user,
    update_user,
    upsert_user,
    get_all_users,
    get_user_logs,
    get_user_tasks,
    authenticate_user,
    get_project_by_user,
)
from backend.dependencies.auth import (
    is_admin,
    validate_csrf,
    get_current_user,
)
from backend.models.pagination import Pagination
from database.interfaces.session import ISession

user_router = APIRouter(prefix="/user")


@user_router.get("/create")
def get_user_home(
    request: Request, current_user: User = Depends(get_current_user)
):
    if not is_admin(current_user):
        raise HTTPException(status_code=401, detail="Access forbidden")
    return templates.TemplateResponse("user/create.html", {"request": request})


@user_router.get("/is_admin", response_model=bool)
def is_admin_endpoint(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return is_admin(current_user)


@user_router.post("/")
async def create_user_endpoint(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    permissions: int = Form(...),
    session: ISession = Depends(get_session),
    csrf_protect=Depends(validate_csrf),
):
    user = UserCreateModel(
        email=email,
        full_name=full_name,
        password=password,
        permissions=permissions,
    )
    return templates.TemplateResponse(
        "user/detail.html",
        {"request": request, "user": create_user(user, session)},
    )


@user_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("user/login.html", {"request": request})


@user_router.post("/login")
async def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: ISession = Depends(get_session),
    csrf_protect=Depends(validate_csrf),
):
    authenticated_user = authenticate_user(email, password, session)
    if not authenticated_user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    request.session["user_id"] = authenticated_user.id
    return RedirectResponse(url="/", status_code=302)


@user_router.post("/logout")
async def logout(
    request: Request,
    csrf_protect=Depends(validate_csrf),
):
    request.session.clear()
    return RedirectResponse(url="/user/login", status_code=302)


@user_router.get("/options", response_class=HTMLResponse)
def get_user_options(
    request: Request,
    page: int = 1,
    limit: int = 300,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    order_by = [User.full_name]  # type: ignore

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    users, pagination = get_all_users(session, pagination)

    html_options = [
        f'<option value="{user.id}">{user.full_name}</option>'
        for user in users
    ]
    return HTMLResponse("\n".join(html_options))


@user_router.get("/{user_id}", response_class=HTMLResponse)
def get_user_endpoint(
    request: Request, user_id: str, session: ISession = Depends(get_session)
):
    user = get_user(session, id=user_id)
    if not user:
        return RedirectResponse(url="/user/login", status_code=302)

    return templates.TemplateResponse(
        "user/detail.html", {"request": request, "user": user}
    )


@user_router.put("/{user_id}", response_model=UserResponseModel)
def update_user_endpoint(
    user_id: str,
    user_update: UserCreateModel,
    session: ISession = Depends(get_session),
):
    return update_user(user_id, user_update, session)


@user_router.post("/upsert", response_model=UserResponseModel)
def upsert_user_endpoint(
    user: UserCreateModel, session: ISession = Depends(get_session)
):
    return upsert_user(user, session)


@user_router.get("/", response_class=HTMLResponse)
def get_all_users_endpoint(
    request: Request,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    combined_filters: Optional[str] = Query(None),
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    order_by = []

    filter_mapping = {
        "Name": "full_name",
        "Email": "email",
    }

    if sort:
        sort_field = filter_mapping.get(sort)
        if sort_field:
            sort_column = getattr(User, sort_field, None)
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
        "has": "has",
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
                field_part = match.group("field").strip().title()
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
    users, pagination = get_all_users(session, pagination)

    return templates.TemplateResponse(
        "user/users.html",
        {
            "request": request,
            "headers": ["Name", "Email", "Projects", "Tasks"],
            "data": users,
            "pagination": pagination,
            "entity": "user",
            "current_sort": sort,
            "current_order": order,
            "allowed_filter_fields": filter_mapping.keys(),
        },
    )


@user_router.get("/{user_id}/projects", response_class=HTMLResponse)
def get_user_projects_endpoint(
    request: Request,
    user_id: str,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    order_by = []
    if sort:
        sort_column = getattr(Project, sort, None)
        if sort_column:
            if order and order.lower() == "desc":
                order_by.append(desc(sort_column))
            else:
                order_by.append(asc(sort_column))

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    projects, pagination = get_project_by_user(session, user_id, pagination)

    return templates.TemplateResponse(
        "project/projects.html",
        {
            "request": request,
            "headers": [
                "Name",
                "Email",
                "Send Email",
                "Archived",
                "Developers",
                "Tasks",
            ],
            "data": projects,
            "pagination": pagination,
            "entity": "project",
            "current_sort": sort,
            "current_order": order,
        },
    )


@user_router.get("/{user_id}/tasks", response_class=HTMLResponse)
def get_user_tasks_endpoint(
    request: Request,
    user_id: str,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    order_by = []
    if sort:
        sort_column = getattr(Task, sort, None)
        if sort_column:
            if order and order.lower() == "desc":
                order_by.append(desc(sort_column))
            else:
                order_by.append(asc(sort_column))

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    tasks, pagination = get_user_tasks(session, user_id, pagination)

    return templates.TemplateResponse(
        "task/tasks.html",
        {
            "request": request,
            "headers": [
                "Title",
                "Project",
                "Hours Required",
                "Hours Worked",
                "Description",
                "Date",
                "Status",
                "Logs",
                "Last Updated",
            ],
            "data": tasks,
            "pagination": pagination,
            "entity": "task",
            "current_sort": sort,
            "current_order": order,
        },
    )


@user_router.get("/{user_id}/logs", response_class=HTMLResponse)
def get_logs_by_user_endpoint(
    request: Request,
    user_id: str,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    order_by = []
    if sort:
        sort_column = getattr(Log, sort, None)
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

    if current_user.id != user_id and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")

    logs, pagination = get_user_logs(session, user_id, pagination)

    context = {
        "request": request,
        "headers": [
            "Task Name",
            "User",
            "Hours Worked",
            "Description",
            "Date",
            "Task Status",
            "Actions",
        ],
        "data": logs,
        "pagination": pagination,
        "entity": "log",
        "current_sort": sort,
        "current_order": order,
    }
    return templates.TemplateResponse("log/logs.html", context)
