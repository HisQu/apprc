"""Pass several settings sections to application code and reload one section."""

from dataclasses import dataclass, field

import apprc as rc

MyRC = rc.AppRC(app_id="section-demo")


@MyRC.config("client", prefix="DEMO_")
class ClientSettings(rc.Config):
    """Values used by an API client."""

    timeout: int = rc.field("DEMO_TIMEOUT", default=30)


@MyRC.config("output", prefix="DEMO_")
class OutputSettings(rc.Config):
    """Values used by a report writer."""

    format: str = rc.field(
        "DEMO_FORMAT", default="json", choices=("json", "csv")
    )


@MyRC.bundle
@dataclass(kw_only=True)
class ApplicationConfig:
    """Settings passed to the top-level application operation.

    :param client: API-client settings.
    :param output: Report-writer settings.
    """

    client: ClientSettings = field(default_factory=ClientSettings)
    output: OutputSettings = field(default_factory=OutputSettings)


def describe_run(config: ApplicationConfig) -> str:
    """Describe the values application code would use.

    :param config: Constructed application settings.
    :return: Output format and request timeout.
    """
    return f"{config.output.format}: timeout={config.client.timeout}"


def main() -> None:
    """Demonstrate construction, a scoped override, and a later reload."""
    resolved = MyRC.resolve(environment={"DEMO_TIMEOUT": "10"})
    config = resolved.build(ApplicationConfig)
    quick = config.client.scoped(timeout=5)
    assert config.client.timeout == 10
    assert quick.timeout == 5
    print(describe_run(config))
    print(f"one request: timeout={quick.timeout}")
    config.client.reload_from(MyRC.resolve(environment={"DEMO_TIMEOUT": "20"}))
    assert quick.timeout == 5
    assert resolved.build(ClientSettings).timeout == 10
    print(describe_run(config))


if __name__ == "__main__":
    main()
