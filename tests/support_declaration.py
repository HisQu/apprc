"""Register reusable test sections through the supported AppRC declaration API."""

from pathlib import Path

from apprc import AppRC, Config, Storage, UserDotenv
from apprc.definition.app_config.spec import AppConfigSpec
from apprc.definition.env_config.schema import owner_for


def app_from_envs(
    spec: AppConfigSpec | None = None,
    *,
    app_id: str = "test-app",
    display_name: str | None = None,
    config_package: str | None = None,
    envs: tuple[type[Config], ...] = (),
    user_dotenv: UserDotenv | None = None,
    storage: Storage | None = None,
    command_name: str | None = None,
    apprc_dir: Path | None = None,
    apprc_dir_env_key: str | None = None,
    legacy_app_ids: tuple[str, ...] = (),
) -> AppRC:
    """Build a test app and register existing section classes normally.

    :param spec: Optional declaration metadata used by specification tests.
    :param app_id: Test application identity.
    :param display_name: Human-readable identity.
    :param config_package: Optional test resource package.
    :param envs: Reusable registered test sections.
    :param user_dotenv: Optional saved user overrides.
    :param storage: Optional named-storage capability.
    :param command_name: Command name used in rendered guidance.
    :param apprc_dir: Isolated managed-file directory.
    :param apprc_dir_env_key: Explicit directory selector key.
    :param legacy_app_ids: Identities used by migration tests.
    :return: An application using the same registration path as user code.
    """
    if spec is not None:
        app_id, display_name = spec.app_id, spec.display_name
        config_package = spec.config_package
        envs = tuple(
            section for section in spec.envs if issubclass(section, Config)
        )
        user_dotenv, storage = spec.user_dotenv, spec.storage
        command_name = spec.command_name
        apprc_dir = spec.declared_apprc_dir
        apprc_dir_env_key = (
            spec.apprc_dir_env_key if spec.uses_managed_files() else None
        )
        legacy_app_ids = spec.legacy_app_ids
    app = AppRC(
        app_id=app_id,
        display_name=display_name,
        config_package=config_package,
        user_dotenv=user_dotenv,
        storage=storage,
        command_name=command_name,
        apprc_dir=apprc_dir,
        apprc_dir_env_key=apprc_dir_env_key,
        legacy_app_ids=legacy_app_ids,
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
