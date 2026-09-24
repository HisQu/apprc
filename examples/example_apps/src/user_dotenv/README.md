# User dotenv example

This app declares `user_dotenv=rc.UserDotenv()` and no storage. Setup creates
`apprc.user.env` and `apprc.user.secret.env`. The terminal editor and
`config set --scope user` save ordinary fields in `apprc.user.env`.

```shell
apprc-examples-lab user-dotenv
```

The optional [browser entry point](desktop.py) uses the same `MyRC` declaration
and the reusable `apprc-gui` editor. Install the example's `desktop` extra,
then run `apprc-user-dotenv-desktop`. Its Gradio page creates the user files,
edits the profile and debug fields, and reads the resulting profile into the
example application.
