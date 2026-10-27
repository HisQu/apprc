"""Register reusable test sections through the supported AppRC declaration API."""

from apprc import AppRC, Config, UserDotenv
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.app_config.workspaces import Workspaces
from apprc.definition.env_config.schema import owner_for
from apprc.definition.paths import Layout, Paths


def app_from_envs(
    spec: AppConfigSpec | None = None,
    *,
    app_id: str = "test-app",
    display_name: str | None = None,
    config_package: str | None = None,
    envs: tuple[type[Config], ...] = (),
    paths: Paths = Paths(),
    layout: Layout | None = None,
    bootstrap_env_prefix: str | None = None,
    user_dotenv: UserDotenv | None = None,
    workspaces: Workspaces | None = None,
    setup_next_step: str | None = None,
    command_name: str | None = None,
) -> AppRC:
    """Build a test app and register existing section classes normally.

    :param spec: Optional declaration metadata used by specification tests.
    :param app_id: Test application identity.
    :param display_name: Human-readable identity.
    :param config_package: Optional test resource package.
    :param envs: Reusable registered test sections.
    :param paths: Explicit filesystem capabilities for the test application.
    :param layout: Optional isolated layout for managed paths.
    :param bootstrap_env_prefix: Prefix for layout and workspace selectors.
    :param user_dotenv: Optional saved user overrides.
    :param workspaces: Optional workspace registry or direct-path capability.
    :param setup_next_step: Optional instruction printed after CLI setup.
    :param command_name: Executable name used in rendered guidance.
    :return: An application using the same registration path as user code.
    """
    if spec is not None:
        app_id, display_name = spec.app_id, spec.display_name
        config_package = spec.config_package
        envs = tuple(
            section for section in spec.envs if issubclass(section, Config)
        )
        paths, layout = spec.paths, spec.layout
        bootstrap_env_prefix = spec.bootstrap_env_prefix
        user_dotenv, workspaces = spec.user_dotenv, spec.workspaces
        setup_next_step = spec.setup_next_step
        command_name = spec.command_name
    app = AppRC(
        app_id=app_id,
        display_name=display_name,
        config_package=config_package,
        paths=paths,
        layout=layout,
        bootstrap_env_prefix=bootstrap_env_prefix,
        user_dotenv=user_dotenv,
        workspaces=workspaces,
        setup_next_step=setup_next_step,
        command_name=command_name,
    )
    for section in envs:
        owner = owner_for(section)
        app.config(
            owner.key,
            prefix=owner.env_prefix,
            title=owner.title,
            rc_path=owner.rc_path,
        )(section)
    return app
