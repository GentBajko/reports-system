def populate_developer_fields(user_dict: dict) -> None:
    """
    Populate the developer fields with the user's email, full name, and project tasks.

    :param user_dict: The dictionary representation of the user.
    """
    for project in user_dict.get("projects", []):
        if isinstance(project, dict):
            for developer in project.get("developers", []):
                if isinstance(developer, dict):
                    developer.setdefault("email", user_dict.get("email"))
                    developer.setdefault(
                        "full_name", user_dict.get("full_name")
                    )
                    developer.setdefault("tasks", project.get("tasks", []))