# Documentation

- [Start here](#start-here)
- [Choose a document](#choose-a-document)
- [Component names](#component-names)
- [Documentation rules](#documentation-rules)

## Start here

AppRC lets a Python application declare its settings once and use that declaration
to load values, explain their sources, and provide configuration tools to users.
Start with the [working example](../README.md#load-settings), then read how
[`AppRC`](Explanations.md#apprc) connects the settings to those tools.

Learn the components in this order:

1. Define a [config section](Explanations.md#config-sections-and-fields) and build
   settings from a [`ResolvedConfig`](Explanations.md#resolvedconfig).
2. Understand [configuration layers](Explanations.md#configuration-layers) and
   [provenance](Explanations.md#provenance) before adding files.
3. Add a [user dotenv](Explanations.md#user-dotenv-and-the-apprc-directory) when
   users need saved preferences, or [storage](Explanations.md#storage) when the
   application needs a persistent data directory.
   An [importable client](How-To-User-Guides.md#use-apprc-inside-an-importable-client)
   can load those layers inside its own constructor.
4. Use [`ConfigManager`](Explanations.md#configmanager) to initialize and edit
   those files. Add the [config CLI](Explanations.md#config-cli) and
   [config editor](Explanations.md#config-editor) for terminal use, or the
   [GUI view](Explanations.md#gui-view) in a desktop application.
5. Use a [config bundle](Explanations.md#config-bundles) when several parts of
   the application need their own config sections.

The [complete setups](EXAMPLES.md#choose-a-setup) show when to use each option.
Sections in [How-to user guides](How-To-User-Guides.md) are independent; you do not
have to run every earlier guide. Existing applications can use the
[migration instructions](How-To-User-Guides.md#migrate-existing-applications).

## Choose a document

| Document | What it answers |
| --- | --- |
| [Explanations](Explanations.md) | What is each component, why does it exist, and how does it connect to the others? |
| [How-to user guides](How-To-User-Guides.md) | How do I complete a particular task? |
| [References](References.md) | What is the exact API, command, filename, priority, or failure behavior? |
| [Examples](EXAMPLES.md) | Which complete setup fits my application, and how can I run it? |
| [Development](Development.md) | Where does implementation belong, and how do I test, build, and release changes? |

## Component names

Use these names in every document. The linked explanation defines each term;
the Python name identifies its implementation.

| Name | Python name or file | Meaning |
| --- | --- | --- |
| [`AppRC`](Explanations.md#apprc) | `rc.AppRC` | Application declaration that registers config sections and enables optional features. |
| [Config section](Explanations.md#config-sections-and-fields) | Subclass of `rc.Config` or `rc.ConfigBase` | A group of related typed settings. |
| [Config field](Explanations.md#config-sections-and-fields) | `rc.field(...)` | One setting's environment key, default, and documentation. |
| [`ResolvedConfig`](Explanations.md#resolvedconfig) | `rc.ResolvedConfig` | The result of reading configuration sources for one application run. |
| [Configuration layer](Explanations.md#configuration-layers) | One file or the process environment | A source of values with a defined priority. |
| [Provenance](Explanations.md#provenance) | `settings.provenance_of(...)` | The record of where a field's current value came from. |
| [AppRC directory](Explanations.md#user-dotenv-and-the-apprc-directory) | `~/.local/share/<app_id>` by default | Directory containing the user dotenv and storage registry when enabled. |
| [User dotenv](Explanations.md#user-dotenv-and-the-apprc-directory) | `apprc.user.env` | Saved user overrides enabled by `rc.UserDotenv()`. |
| [Secret companion](Explanations.md#secret-companions) | `apprc.user.secret.env` or `apprc.storage.secret.env` | Private file for saved `secret=True` fields in the same layer. |
| [Storage](Explanations.md#storage) | `rc.Storage()` enables it | A persistent data directory with its own `apprc.storage.env`. |
| [Storage registry](Explanations.md#storage-registry) | `apprc.toml` | Storage names, directory paths, and the saved default storage. |
| [`ConfigManager`](Explanations.md#configmanager) | Returned by `MyRC.manage()` | Application-specific setup, inspection, editing, and storage operations. |
| [Config CLI](Explanations.md#config-cli) | `rc.cli.mount_config_cli(...)` | Configuration commands added to a Typer application. |
| [Config editor](Explanations.md#config-editor) | `rc.tui.ConfigEditorApp` | Terminal interface for inspecting layers and editing saved overrides. |
| [GUI view](Explanations.md#gui-view) | `apprc_gui.ConfigView` | Toga settings view embedded in an application-owned window. |
| [Config bundle](Explanations.md#config-bundles) | Dataclass registered with `@MyRC.bundle` | An object containing several config sections. |

## Documentation rules

These rules apply to the root README, this directory, example READMEs, and
generated package descriptions. Contributors and coding agents must read them
before changing documentation.

### Names and learning order

- Use the document labels in [Choose a document](#choose-a-document) verbatim.
  Do not relabel Explanations as Architecture or How-to user guides as Recipes.
- Use the [component names](#component-names) consistently. Add a definition
  before introducing a new component. Do not invent synonyms for variation.
- Call the Windows `.msi` file an **installer**. Call cx_Freeze's process of
  creating that file an **installer build**. Do not call the installed app or
  its executable a "single file"; the installer contains multiple files.
- Introduce basic settings before files, optional features, and integrations.
  Explain an unfamiliar term before relying on it in instructions.
- Start Explanations sections with what the named component is and why the
  application needs it. Describe its inputs, outputs, and connections through
  concrete actions. A list of technical nouns is not an explanation.
- Use task headings in How-to user guides. For example, use "Pass several
  settings sections together" and define "config bundle" in the opening text.
- Describe current behavior. Keep previous implementations and upgrade details
  in migration instructions and the changelog.

### Links and examples

- Link the relevant word or phrase within its paragraph or table cell, as in
  "The [storage registry](Explanations.md#storage-registry) remembers the path."
- Link a component to Explanations, an operation to its How-to user guide, an
  exact API to References, and a complete setup to Examples. Use section anchors.
- Make these connections in both directions where they help the reader. Link
  the first useful occurrence in a section; do not link every repetition.
- Do not collect ordinary cross-links into "Related links" callouts or generic
  further-reading paragraphs. Use GitHub callouts for prerequisites, context,
  warnings, or optional advice that actually needs emphasis.
- Give each independent guide all imports, declarations, filenames, commands,
  and expected results needed to reproduce it. State when a block is an excerpt.
- Keep complete application sources in the existing examples tree. Examples
  explains their setup and links to specific files; it must not be only a link list.
- Exercise documented code against the current API. Explain why a setting wins,
  which file an edit changes, and whether an operation writes application data.

### Review and maintenance

- Keep a table of contents at the top of each major document.
- Check links and anchors after renaming headings. Preserve existing published
  anchors when practical, while updating internal links to current headings.
- Check prose manually for undefined terms, synonym drift, vague claims, and
  sentences that enumerate components without explaining their relationship.
- Follow the [generated-file procedure](Development.md#generated-files) for
  package descriptions. Edit diagram source scripts before regenerating assets;
  Graphigs remains the source of figure styling.
- Run the [documentation checks](Development.md#documentation-checks) alongside
  the checks required for any accompanying code changes.
