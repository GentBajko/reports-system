from datetime import datetime

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="src/backend/templates")


def date_to_string(timestamp):
    dt_object = datetime.fromtimestamp(timestamp) if timestamp else None
    return dt_object.strftime("%d-%m-%Y @ %H:%M:%S") if dt_object else ""


templates.env.filters["date_to_string"] = date_to_string


def is_old(timestamp):
    dt_object = datetime.fromtimestamp(timestamp)
    return (datetime.now() - dt_object).days > 7


templates.env.filters["is_old"] = is_old
