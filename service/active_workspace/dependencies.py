from service.active_workspace.service import ActiveWorkspaceService


def configure_active_workspaces(app) -> None:
    app.state.active_workspaces = ActiveWorkspaceService()


def active_workspaces_for(request):
    return request.app.state.active_workspaces
