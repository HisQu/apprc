# User dotenv with workspace example

This app declares a user dotenv and named workspaces. Run `config setup` to
create `apprc.user.env`; adding a named workspace creates its local
`apprc.workspace.env` and the central `apprc.toml` registry.

```shell
apprc-examples-lab user-dotenv-with-workspace
```

Inside the lab, run `apprc-user-dotenv-with-workspace config setup --yes` to
initialize the user dotenv. The lab prints the workspace registration and
selection commands.
