"""Small application-owned Toga window using the reusable AppRC view."""

import toga
from apprc_gui import ConfigView

from user_dotenv.config.app import MyRC
from user_dotenv.config.sections.app import AppSettings


class UserDotenvDesktop(toga.App):
    """Show how one AppRC declaration serves an app and a settings window."""

    def startup(self) -> None:
        """Offer setup and editing before reading the current profile."""
        self.manager = MyRC.manage()
        self.profile = toga.Label("Read the active profile after setup.")
        window = toga.MainWindow(title="User dotenv example")
        self.main_window = window
        self.settings = ConfigView(self.manager, window)
        window.content = toga.Column(
            children=[
                self.profile,
                toga.Button("Read active profile", on_press=self._read_profile),
                self.settings.widget,
            ]
        )
        window.show()

    def _read_profile(self, _widget: toga.Widget) -> None:
        """Build application settings from the declaration edited above."""
        settings = self.manager.resolve().build(AppSettings)
        self.profile.text = f"Active profile: {settings.profile}"


def main() -> None:
    """Run the example with the installed native backend."""
    UserDotenvDesktop(
        "User dotenv example", "org.example.apprc-user-dotenv"
    ).main_loop()


if __name__ == "__main__":
    main()
