# User dotenv example

This app declares `user_dotenv=rc.UserDotenv()` and no workspace. Setup creates
`apprc.user.env` and `apprc.user.secret.env`. The terminal editor and
`config set --scope user` save ordinary fields in `apprc.user.env`.

```shell
apprc-examples-lab user-dotenv
```

Inside the lab, open the single-event-loop launcher:

```shell
cd "$APPRC_EXAMPLE_LAB_ROOT"
apprc-user-dotenv launcher
```

The home screen opens the reusable config editor and can run **Print active
configuration** as an owned foreground child, suspending/resuming the terminal.
The child uses this Python environment's absolute entry point and the captured
root/environment-file selectors, not another installation found on PATH.
Management does not construct business settings merely to open the launcher.

The optional [browser entry point](desktop.py) uses the same `MyRC` declaration
and the reusable `apprc-gui` editor. Install the example's `desktop` extra,
then run `apprc-user-dotenv-desktop`. Its Gradio page creates the user files,
edits the profile and debug fields, and reads the resulting profile into the
example application.
