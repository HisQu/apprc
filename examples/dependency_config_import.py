"""Give a dependency client fields owned by a parent AppRC."""

from dataclasses import dataclass, field

import apprc as rc

DependencyRC = rc.AppRC(app_id="dependency")


@DependencyRC.config("client", prefix="DEP_")
class DependencyClient(rc.Config):
    """Settings accepted by the dependency when used on its own."""

    api_key: str = rc.field("DEP_API_KEY", secret=True)
    base_url: str = rc.field(
        "DEP_BASE_URL", default="https://dependency.example"
    )
    model_llm: str = rc.field("DEP_MODEL_LLM", default="dependency-model")
    model_fast: str = rc.field("DEP_MODEL_FAST", default="dependency-model")


HostRC = rc.AppRC(app_id="host")
host_client = HostRC.import_dependency_config(
    DependencyRC,
    DependencyClient,
    key="client",
    prefix="HOST_LLM_",
    title="Host language model",
    fields={
        "api_key": rc.field("HOST_LLM_API_KEY", secret=True),
        "endpoint": rc.field(
            "HOST_LLM_ENDPOINT", default="https://host.example"
        ),
        "model": rc.field("HOST_LLM_MODEL", default="host-model"),
    },
    field_targets={
        "api_key": "api_key",
        "base_url": "endpoint",
        "model_llm": "model",
        "model_fast": "model",
    },
)


@HostRC.bundle
@dataclass(kw_only=True)
class HostSettings:
    """Parent settings passed to application code."""

    client: DependencyClient = field(default_factory=DependencyClient)


def main() -> None:
    """Build the dependency config without reading its environment."""
    resolved = HostRC.resolve(
        environment={
            "HOST_LLM_API_KEY": "example-placeholder",
            "HOST_LLM_MODEL": "host-model-v2",
            "DEP_BASE_URL": "https://ignored.example",
        }
    )
    bundle = resolved.build(HostSettings)
    client = resolved.build(host_client)

    assert bundle.client.base_url == "https://host.example"
    assert (
        bundle.client.model_llm == bundle.client.model_fast == "host-model-v2"
    )
    assert client.provenance_of("api_key").env_key == "HOST_LLM_API_KEY"
    assert "example-placeholder" not in repr(client)
    print(f"{bundle.client.base_url}: {bundle.client.model_llm}")


if __name__ == "__main__":
    main()
