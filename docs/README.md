# Documentation

- [Find the right page](#find-the-right-page)
  - [Start here](#start-here)
  - [Choose a document](#choose-a-document)
- [Documentation conventions](#documentation-conventions)
  - [Component names](#component-names)
  - [Documentation rules](#documentation-rules)

<br>

# Find the right page

## Start here

AppRC lets a Python application declare typed settings and independently opt in
to configuration, application data, cache, and state paths. Start with the
[working example](../README.md#load-settings), then read how
[`AppRC`](Explanations.md#apprc) connects these features.

Learn the components in this order:

1. Define a [config section](Explanations.md#config-sections-and-fields) and build
   settings from a [`ResolvedConfig`](Explanations.md#resolvedconfig).
2. Understand [configuration layers](Explanations.md#configuration-layers) and
   [provenance](Explanations.md#provenance).
3. Declare independent [application paths](Explanations.md#application-paths)
   with `Paths` and choose a [layout](Explanations.md#layouts). A cache-only
   application does not need config files.
4. Add [user preferences](Explanations.md#user-dotenv), or selectable
   [workspaces](Explanations.md#workspaces) when the application needs named
   working directories. A direct workspace does not require a registry.
5. Use [`ConfigManager`](Explanations.md#configmanager) for settings and
   [`WorkspaceManager`](Explanations.md#workspaces) for workspace operations.
   Add the grouped [application CLI](Explanations.md#application-cli) or a
   [Textual](Explanations.md#config-editor)/[Gradio](Explanations.md#gradio-editor)
   editor when users need those interfaces.
6. Use a [config bundle](Explanations.md#config-bundles) for related settings
   sections and an [imported config binding](Explanations.md#imported-dependency-settings)
   when the parent application owns dependency settings.

The [complete setups](EXAMPLES.md#choose-a-setup) show when to use each option.
Guides in [How-to user guides](How-To-User-Guides.md) are independent. Existing
applications can follow the explicit [breaking-change upgrade guide](How-To-User-Guides.md#migrate-existing-applications);
AppRC never moves old files or upgrades the old schema automatically.

## Choose a document

| Document | What it answers |
| --- | --- |
| [Explanations](Explanations.md) | What is each component, why does it exist, and how does it connect to the others? |
| [How-to user guides](How-To-User-Guides.md) | How do I complete a particular task? |
| [References](References.md) | What is the exact API, command, filename, priority, or failure behavior? |
| [Examples](EXAMPLES.md) | Which complete setup fits my application, and how can I run it? |
| [Development](Development.md) | Where does implementation belong, and how do I test, build, and release changes? |

<br>

# Documentation conventions

## Component names

Use these names consistently. The linked explanation defines each component;
the Python name identifies its implementation.

| Name | Python name or file | Meaning |
| --- | --- | --- |
| [`AppRC`](Explanations.md#apprc) | `rc.AppRC` | Application declaration for settings and optional capabilities. |
| [Config section](Explanations.md#config-sections-and-fields) | Subclass of `rc.Config` or `rc.ConfigBase` | A group of related typed settings. |
| [Config field](Explanations.md#config-sections-and-fields) | `rc.field(...)` | One setting's environment key, default, and documentation. |
| [`ResolvedConfig`](Explanations.md#resolvedconfig) | `rc.ResolvedConfig` | Settings-source snapshot for one application run; it always carries `AppPaths`. |
| [Paths](Explanations.md#application-paths) | `rc.Paths` | Declaration enabling config, appdata, cache, and state independently. |
| [Layout](Explanations.md#layouts) | `rc.Layout` | Native or single-root mapping for enabled path components. |
| [AppPaths](Explanations.md#application-paths) | `rc.AppPaths` | Read-only resolved locations; disabled components are `None`. |
| [Workspace](Explanations.md#workspaces) | `rc.Workspaces` | Optional named or direct working-directory selection, separate from `AppPaths`. |
| [User dotenv](Explanations.md#user-dotenv) | `apprc.user.env` | Saved overrides enabled by `rc.UserDotenv()` with config enabled. |
| [Secret companion](Explanations.md#secret-companions) | `apprc.user.secret.env` or `apprc.workspace.secret.env` | Private file for saved `secret=True` fields in that layer. |
| [`ConfigManager`](Explanations.md#configmanager) | Returned by `MyRC.manage()` | Settings setup, inspection, editing, and secret repair. |
| [`WorkspaceManager`](Explanations.md#workspaces) | Returned by `MyRC.workspaces()` | Workspace registry, selection, and archive operations. |
| [Maintenance](Explanations.md#maintenance) | `rc.MaintenanceHandlers` | Explicit application operations for supported resource categories. |
| [Application CLI](Explanations.md#application-cli) | `rc.cli.mount_app_cli(...)` | Grouped paths, doctor, config, workspace, category, and purge commands. |
| [Config editor](Explanations.md#config-editor) | `rc.tui.ConfigEditorApp` | Terminal interface for inspecting and editing saved settings. |
| [Gradio editor](Explanations.md#gradio-editor) | `apprc_gui.ConfigEditor` | Settings controls in application-owned Gradio `Blocks`. |
| [Config bundle](Explanations.md#config-bundles) | Dataclass registered with `@MyRC.bundle` | An object containing several config sections. |

## Documentation rules

These rules apply to the root README, this directory, example READMEs, and
generated package descriptions. Contributors and coding agents must read them
before changing documentation.

### Names and learning order

- Use the document labels in [Choose a document](#choose-a-document) verbatim.
- Use the [component names](#component-names) consistently. Define a component
  before relying on it in instructions.
- Call the Windows `Setup.exe` an **installer** and the process of creating it an
  **installer build**.
- Introduce basic settings before files, optional features, and integrations.
- Start Explanations sections with what a component is and why an application
  needs it. Describe concrete inputs, outputs, and connections.
- Use task headings in How-to user guides and define unfamiliar terms when first
  used.
- Describe current behavior. Keep upgrade instructions in clearly labeled
  migration guidance and breaking changes in the changelog.

### Links and examples

- Link the relevant phrase in its paragraph or table cell. Link a component to
  Explanations, an operation to How-to user guides, an exact API to References,
  and a complete setup to Examples.
- Give each independent guide all imports, declarations, filenames, commands,
  and expected results needed to reproduce it. State when a block is an excerpt.
- Keep complete application sources in the existing examples tree. Examples
  explains the setup and links to sources rather than becoming only a link list.
- Explain why a setting wins, which file an edit changes, and whether an
  operation writes application data.

### Review and maintenance

- In the six pages in `docs/`, keep the document-title H1 above the table of
  contents. List each topical H1 and every H2 exactly once in document order.
- Put a standalone `<br>` before the first topical H1 and between later H1
  sections. Do not add spacers between H2 sections.
- Check links and anchors after renaming headings. Preserve existing anchors
  where practical and update internal links to current headings.
- Review prose for undefined terms, synonym drift, vague claims, and unexplained
  component relationships.
- Follow the [generated-file procedure](Development.md#generated-files) for
  package descriptions. Diagram source scripts are canonical; do not hand-edit
  generated SVG files.
- Run the [documentation checks](Development.md#documentation-checks) alongside
  checks required for any accompanying code changes.
