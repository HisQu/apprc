# AppRC manual

- [Choose a document](#choose-a-document)
- [Start with one declaration](#start-with-one-declaration)

## Choose a document

| Need | Read |
| --- | --- |
| First working example | [Root README](../README.md#load-settings) |
| Integrate, set up, or upgrade an application | [How-to guides](How-To-User-Guides.md) |
| Exact APIs, filenames, precedence, and commands | [Reference](References.md) |
| Understand responsibility boundaries | [Explanations](Explanations.md) |
| Develop, test, build, or release AppRC | [Development](Development.md) |
| Run real CLIs | [Examples](../examples/example_apps/README.md) |

![Documentation map](assets/docs-reading-map.svg)

## Start with one declaration

`AppRC` owns the application identity and registered settings. Its `schema`
contains metadata. `resolve()` captures source values; the returned snapshot
builds runtime settings. `manage()` provides setup, inspection, editing, and
storage operations. Terminal interfaces call those same operations.

Persistence is optional. Add `UserDotenv()` for saved user overrides and
`Storage()` for named data directories. Require storage per invocation, not on
the declaration. Choose `apprc-core` or `apprc` according to whether terminal
libraries are needed.

Existing users should begin with the
[migration table](How-To-User-Guides.md#migrate-existing-applications).
