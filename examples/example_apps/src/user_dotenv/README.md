# User dotenv example

This app declares `user_dotenv=rc.UserDotenv()` and no storage. Setup creates
`apprc.user.env` and `apprc.user.secret.env`. The terminal editor and
`config set --scope user` save ordinary fields in `apprc.user.env`.

```shell
apprc-examples-lab user-dotenv
```

The optional [desktop entry point](desktop.py) uses the same `MyRC` declaration
and the reusable `apprc-gui` view. Install a Toga backend for your platform and
`apprc-gui`, then run `apprc-user-dotenv-desktop`. The window creates the user
files, edits the profile and debug fields, and reads the resulting profile into
the example application.
