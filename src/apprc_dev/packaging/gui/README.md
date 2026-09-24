# AppRC GUI

`apprc-gui` adds a Gradio settings editor to an application that uses
`apprc-core`. The application owns the Gradio `Blocks`, server, and launch
decision. `ConfigEditor` reads and writes through the application's
`ConfigManager`.

```python
import gradio as gr
from apprc_gui import ConfigEditor

from my_app.config import MyRC

with gr.Blocks() as page:
    gr.Markdown("# My App settings")
    ConfigEditor(MyRC.manage()).render()

page.launch(server_name="127.0.0.1", share=False)
```

Import all config sections registered on `MyRC` before creating the editor.
It works before storage or required fields are ready. The editor can create
declared files, select storage, save user or storage overrides, and show the
effective source of each setting. Secret values use password inputs and the
private companion files. The [Gradio settings guide](https://github.com/HisQu/apprc/blob/main/docs/How-To-User-Guides.md#add-a-gradio-settings-page)
shows how to include the editor in an existing application.
