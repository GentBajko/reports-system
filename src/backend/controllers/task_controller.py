from io import StringIO
import csv
from typing import Optional
from datetime import datetime

from loguru import logger
from fastapi import Form, Query, Depends, Request, APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from backend.models import TaskCreateModel, TaskResponseModel
from core.models.log import Log
from database.models import task_mapper  # noqa F401
from core.models.task import Task
from core.models.user import User
from backend.dependencies import get_session
from backend.utils.templates import templates
from backend.views.task_view import (
    get_task,
    create_task,
    update_task,
    upsert_task,
    get_all_tasks,
    get_task_logs,
    get_user_tasks,
    get_project_tasks,
)
from backend.dependencies.auth import (
    is_admin,
    validate_csrf,
    get_current_user,
)
from backend.models.pagination import Pagination
from database.interfaces.session import ISession
from backend.utils.filters_and_sort import get_filters, get_sorting

task_router = APIRouter(prefix="/task")


@task_router.get("/create")
def get_task_home(
    request: Request, current_user: User = Depends(get_current_user)
):
    """
    Endpoint to retrieve the task home page.
    """
    return templates.TemplateResponse("task/create.html", {"request": request})


@task_router.post("/", response_class=HTMLResponse)
async def create_task_endpoint(
    request: Request,
    project_id: str = Form(...),
    project_name: str = Form(...),
    title: str = Form(...),
    hours_required: float = Form(...),
    description: str = Form(...),
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    csrf_protect=Depends(validate_csrf),
):
    """
    Endpoint to create a new task.
    """

    task_data = TaskCreateModel(
        project_id=project_id,
        project_name=project_name,
        user_id=current_user.id,
        user_name=current_user.full_name,
        title=title,
        hours_required=hours_required,
        description=description,
    )
    try:
        task = create_task(task_data, session)
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(f"/task/{task.id}", status_code=303)


@task_router.get("/options", response_class=HTMLResponse)
def get_project_options(
    request: Request,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    pagination = Pagination(
        limit=300,
        current_page=1,
        order_by=[Task.timestamp],  # type: ignore
    )
    tasks = (
        get_all_tasks(session, pagination)[0]
        if is_admin(current_user)
        else [
            project
            for project in get_user_tasks(
                session, current_user.id, pagination
            )[0]
        ]
    )

    options_html = ""
    for task in tasks:
        options_html += f'<option value="{task.id}" status="{task.status}">{task.title}</option>'

    return HTMLResponse(content=options_html)


@task_router.get("/export", response_class=StreamingResponse)
def export_tasks_csv(
    request: Request,
    combined_filters: Optional[str] = Query(None),
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Export tasks between two dates as a CSV file.
    """
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")
    try:
        filter_mapping = {
            "Title": "title",
            "Project": "project_name",
            "Hours Required": "hours_required",
            "Hours Worked": "hours_worked",
            "Status": "status",
            "Date": "timestamp",
            "Last Updated": "last_updated",
            "User": "user_name",
        }
        pagination = Pagination(limit=None, current_page=1, order_by=[])
        filters = get_filters(
            combined_filters,
            filter_mapping,
            "Title",
            date_fields=["Date", "Last Updated"],
        )

        tasks, _ = get_all_tasks(session, pagination, **filters)
        csv_file = StringIO()
        writer = csv.writer(csv_file)
        writer.writerow(
            ["ID", "Title", "User", "Project", "Status", "Timestamp"]
        )
        for task in tasks:
            writer.writerow(
                [
                    task.id,
                    task.title,
                    task.user_name,
                    task.project_name,
                    task.status,
                    datetime.fromtimestamp(task.timestamp).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                ]
            )
        csv_file.seek(0)
        response = StreamingResponse(
            iter([csv_file.getvalue()]),
            media_type="text/csv",
        )
        response.headers["Content-Disposition"] = (
            "attachment; filename=tasks.csv"
        )
        return response
    except Exception as e:
        logger.error(f"Error exporting tasks: {e}")
        raise HTTPException(status_code=500, detail="Error exporting tasks")


@task_router.get("/{task_id}", response_class=HTMLResponse)
def get_task_endpoint(
    request: Request,
    task_id: str,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint to retrieve a specific task.
    """
    try:
        task = get_task(session, id=task_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    return templates.TemplateResponse(
        "task/detail.html", {"request": request, "task": task}
    )


@task_router.put("/{task_id}", response_model=TaskResponseModel)
def update_task_endpoint(
    task_id: str,
    task_update: TaskCreateModel,
    session: ISession = Depends(get_session),
):
    """
    Endpoint to update an existing task.
    """
    try:
        task = update_task(task_id, task_update, session)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


@task_router.post("/upsert", response_model=TaskResponseModel)
def upsert_task_endpoint(
    task: TaskResponseModel, session: ISession = Depends(get_session)
):
    """
    Endpoint to upsert a task.
    """
    try:
        task = upsert_task(task, session)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return task


@task_router.get("/", response_class=HTMLResponse)
def get_all_tasks_endpoint(
    request: Request,
    page: int = 1,
    sort: Optional[str] = "Date",
    order: Optional[str] = "desc",
    limit: int = 15,
    combined_filters: Optional[str] = Query(None),
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    sort_mapping = {
        "Title": Task.title,
        "Hours Required": Task.hours_required,
        "Hours Worked": Task.hours_worked,
        "Status": Task.status,
        "Date": Task.timestamp,
        "Last Updated": Task.last_updated,
    }

    order_by = get_sorting(sort, order, sort_mapping)
    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    filter_mapping = {
        "Title": "title",
        "Project": "project_name",
        "Hours Required": "hours_required",
        "Hours Worked": "hours_worked",
        "Status": "status",
        "Date": "timestamp",
        "Last Updated": "last_updated",
        "User": "user_name",
    }

    filters = get_filters(
        combined_filters,
        filter_mapping,
        "Title",
        date_fields=["Date", "Last Updated"],
    )

    if is_admin(current_user):
        tasks, pagination = get_all_tasks(session, pagination, **filters)
    else:
        tasks, pagination = get_user_tasks(
            session, current_user.id, pagination, **filters
        )

    table_headers = [
        "Title",
        "Project",
        "Hours Required",
        "Hours Worked",
        "Description",
        "Date",
        "Status",
        "Logs",
        "Last Updated",
        "Actions",
    ]

    return templates.TemplateResponse(
        "task/tasks.html",
        {
            "request": request,
            "headers": table_headers,
            "data": tasks,
            "pagination": pagination,
            "entity": "task",
            "current_sort": sort,
            "current_order": order,
            "allowed_filter_fields": [
                "Title",
                "Project",
                "Hours Required",
                "Hours Worked",
                "Status",
                "User",
            ],
        },
    )


@task_router.get("/project/{project_id}", response_class=HTMLResponse)
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
    sort_mapping = {
        "Title": Task.title,
        "Hours Required": Task.hours_required,
        "Hours Worked": Task.hours_worked,
        "Status": Task.status,
        "Date": Task.timestamp,
        "Last Updated": Task.last_updated,
    }

    order_by = get_sorting(sort, order, sort_mapping)
    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    tasks, pagination = get_project_tasks(session, project_id, pagination)

    context = {
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
    }
    return templates.TemplateResponse("task/tasks.html", context)


@task_router.get("/user/{user_id}", response_class=HTMLResponse)
def get_tasks_by_user_endpoint(
    request: Request,
    user_id: str,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    sort_mapping = {
        "Title": Task.title,
        "Hours Required": Task.hours_required,
        "Hours Worked": Task.hours_worked,
        "Status": Task.status,
        "Date": Task.timestamp,
        "Last Updated": Task.last_updated,
    }

    order_by = get_sorting(sort, order, sort_mapping)
    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    if current_user.id != user_id and not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Access forbidden")

    tasks, pagination = get_user_tasks(session, user_id, pagination)

    context = {
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
    }
    return templates.TemplateResponse("task/tasks.html", context)


@task_router.get("/{task_id}/logs", response_class=HTMLResponse)
def get_logs_by_task_endpoint(
    request: Request,
    task_id: str,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 15,
    session: ISession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    sort_mapping = {
        "ID": Log.id,
        "Task Name": Log.task_name,
        "Hours ": Log.hours_spent_today,
        "Task Status": Log.task_status,
        "Date": Log.timestamp,
    }

    order_by = get_sorting(sort, order, sort_mapping)

    pagination = Pagination(limit=limit, current_page=page, order_by=order_by)

    logs, pagination = get_task_logs(session, task_id, pagination)

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
