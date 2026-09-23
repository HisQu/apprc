# AppRC GUI

`apprc-gui` provides a Toga configuration view for applications using
`apprc-core`. The host application creates one `ConfigManager` from its `AppRC`
declaration and places `apprc_gui.ConfigView` in its own Toga window.

```python
import toga
from apprc_gui import ConfigView

from my_app.config import MyRC


class MyDesktopApp(toga.App):
    def startup(self):
        window = toga.MainWindow(title="My App")
        self.main_window = window
        window.content = ConfigView(MyRC.manage(), window).widget
        window.show()
```

Import the config sections registered on `MyRC` before creating the view.
The view can open before required settings or storage are ready. It uses
AppRC's manager to set up files, select storage, and edit saved fields. The
application retains ownership of the window and decides when to start its own
work. See the [GUI guide](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#add-a-native-settings-window)
for an application callback and installer instructions.

On Windows, installation includes the WinForms backend. On other platforms,
install a supported Toga backend separately before opening the window.
