"""Browser settings page using the reusable AppRC editor."""

import gradio as gr
from apprc_gui import ConfigEditor

from user_dotenv.config.app import MyRC
from user_dotenv.config.sections.app import AppSettings


def build_page() -> gr.Blocks:
    """Show AppRC settings next to a small application action."""
    manager = MyRC.manage()
    with gr.Blocks(title="User dotenv example") as page:
        gr.Markdown("# User dotenv example")
        profile = gr.Textbox(label="Active profile", interactive=False)

        def read_profile() -> str:
            """Read current files after the editor saves a setting."""
            return manager.resolve().build(AppSettings).profile

        gr.Button("Read active profile").click(read_profile, outputs=profile)
        with gr.Accordion("Settings", open=True):
            ConfigEditor(manager).render()
    return page


def main() -> None:
    """Open the local settings page without requiring a native backend."""
    build_page().launch(server_name="127.0.0.1", inbrowser=True, share=False)


if __name__ == "__main__":
    main()
