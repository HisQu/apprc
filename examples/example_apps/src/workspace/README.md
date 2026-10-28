# Workspace example

This app declares `workspaces=rc.Workspaces()` and no user dotenv. Add a named
workspace with `apprc-workspace workspace add NAME PATH`; its registry is stored
in `apprc.toml` and its values in the workspace-local `apprc.workspace.env`.

```shell
apprc-examples-lab workspace
```
