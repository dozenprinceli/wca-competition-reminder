from pathlib import Path

import pytest

from wca_competition_reminder.config import ConfigurationError, load_config


def write_config(path: Path, recipients: str) -> None:
    path.write_text(
        f"""
timezone = "UTC"
state_path = "var/state.sqlite3"
lock_path = "var/runner.lock"

[wca]
base_url = "https://www.worldcubeassociation.org"

[smtp]
host = "smtp.example.com"
port = 587
security = "starttls"
username = "sender@example.com"
from_address = "sender@example.com"

{recipients}
""",
        encoding="utf-8",
    )


def test_load_config_resolves_paths_and_recipients(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        """
[[recipients]]
email = "ONE@example.com"
latitude = 31.2
longitude = 121.4
max_distance_km = 250
events = "333, minx,333oh"
countries = ["China", "Hong Kong, China", "Côte d'Ivoire"]
continents = ["Europe"]
""",
    )

    config = load_config(config_path)

    assert config.state_path == (tmp_path / "var/state.sqlite3").resolve()
    assert config.recipients[0].email == "one@example.com"
    assert config.recipients[0].max_distance_km == 250
    assert config.recipients[0].event_ids == frozenset({"333", "minx", "333oh"})
    assert config.recipients[0].country_names == frozenset(
        {"China", "Hong Kong, China", "Côte d'Ivoire"}
    )
    assert config.recipients[0].continent_names == frozenset({"Europe"})
    assert config.recipients[0].follows_region("China", "Asia")
    assert config.recipients[0].follows_region("France", "Europe")
    assert not config.recipients[0].follows_region("Japan", "Asia")
    assert config.wca.page_size == 100
    assert config.log_dir == (tmp_path / "logs").resolve()


def test_load_config_reads_admin_list(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        """
[[admins]]
username = "operator"
password = "first-secret"

[[admins]]
username = "auditor"
password = "second-secret"
""",
    )

    config = load_config(config_path)

    assert [(admin.username, admin.password) for admin in config.admins] == [
        ("operator", "first-secret"),
        ("auditor", "second-secret"),
    ]


def test_duplicate_admin_username_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        """
[[admins]]
username = "operator"
password = "first-secret"

[[admins]]
username = "operator"
password = "second-secret"
""",
    )

    with pytest.raises(ConfigurationError, match="duplicate admin username"):
        load_config(config_path)


@pytest.mark.parametrize(
    "admin_entry",
    (
        'username = "operator"',
        'password = "secret"',
        'username = ""\npassword = "secret"',
        'username = "operator"\npassword = ""',
    ),
)
def test_admin_username_and_password_are_required(tmp_path: Path, admin_entry: str) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path, f"[[admins]]\n{admin_entry}")

    with pytest.raises(ConfigurationError):
        load_config(config_path)


def test_recipients_can_be_managed_entirely_through_web_subscriptions(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(config_path, "")

    assert load_config(config_path).recipients == ()


def test_recipient_coordinates_can_be_omitted(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        """
[[recipients]]
email = "one@example.com"
""",
    )

    recipient = load_config(config_path).recipients[0]

    assert recipient.latitude is None
    assert recipient.longitude is None
    assert recipient.max_distance_km is None


@pytest.mark.parametrize("coordinate", ["latitude = 0", "longitude = 0"])
def test_recipient_coordinates_must_be_provided_together(
    tmp_path: Path,
    coordinate: str,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        f"""
[[recipients]]
email = "one@example.com"
{coordinate}
""",
    )

    with pytest.raises(ConfigurationError, match="must be provided together"):
        load_config(config_path)


def test_recipient_distance_requires_coordinates(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        """
[[recipients]]
email = "one@example.com"
max_distance_km = 100
""",
    )

    with pytest.raises(ConfigurationError, match="required when max_distance_km"):
        load_config(config_path)


@pytest.mark.parametrize("value", ["0", "-1", "true", "inf"])
def test_recipient_distance_must_be_a_positive_finite_number(
    tmp_path: Path,
    value: str,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        f"""
[[recipients]]
email = "one@example.com"
latitude = 0
longitude = 0
max_distance_km = {value}
""",
    )

    with pytest.raises(ConfigurationError, match="max_distance_km"):
        load_config(config_path)


@pytest.mark.parametrize("events_line", ["", 'events = ""', 'events = "   "'])
def test_missing_or_blank_events_follows_all(tmp_path: Path, events_line: str) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        f"""
[[recipients]]
email = "one@example.com"
latitude = 0
longitude = 0
{events_line}
""",
    )

    config = load_config(config_path)

    assert config.recipients[0].event_ids is None
    assert config.recipients[0].follows_any(["333"])


@pytest.mark.parametrize(
    ("countries_line", "continents_line"),
    [("", ""), ("countries = []", "continents = []")],
)
def test_missing_or_empty_region_filters_follow_all(
    tmp_path: Path,
    countries_line: str,
    continents_line: str,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        f"""
[[recipients]]
email = "one@example.com"
latitude = 0
longitude = 0
{countries_line}
{continents_line}
""",
    )

    recipient = load_config(config_path).recipients[0]

    assert recipient.country_names is None
    assert recipient.continent_names is None
    assert not recipient.has_region_filter
    assert recipient.follows_region("Any country", "Any continent")


@pytest.mark.parametrize(
    ("events_value", "message"),
    [
        ('"333,unknown"', "unknown WCA event IDs"),
        ('"333,,minx"', "empty event ID"),
        ('["333", "minx"]', "comma-separated string"),
    ],
)
def test_invalid_recipient_events_are_rejected(
    tmp_path: Path, events_value: str, message: str
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        f"""
[[recipients]]
email = "one@example.com"
latitude = 0
longitude = 0
events = {events_value}
""",
    )

    with pytest.raises(ConfigurationError, match=message):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("countries", '"China"', "array of strings"),
        ("countries", '["China", ""]', "non-empty strings"),
        ("continents", '["Asia", 1]', "non-empty strings"),
    ],
)
def test_invalid_recipient_region_filters_are_rejected(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        f"""
[[recipients]]
email = "one@example.com"
latitude = 0
longitude = 0
{field} = {value}
""",
    )

    with pytest.raises(ConfigurationError, match=message):
        load_config(config_path)


def test_duplicate_recipient_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        """
[[recipients]]
email = "one@example.com"
latitude = 0
longitude = 0

[[recipients]]
email = "ONE@example.com"
latitude = 1
longitude = 1
""",
    )

    with pytest.raises(ConfigurationError, match="duplicate recipient"):
        load_config(config_path)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91, 0), (-91, 0), (0, 181), (0, -181)],
)
def test_invalid_recipient_coordinates_are_rejected(
    tmp_path: Path, latitude: float, longitude: float
) -> None:
    config_path = tmp_path / "config.toml"
    write_config(
        config_path,
        f"""
[[recipients]]
email = "one@example.com"
latitude = {latitude}
longitude = {longitude}
""",
    )

    with pytest.raises(ConfigurationError):
        load_config(config_path)
