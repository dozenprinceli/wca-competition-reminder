import argparse
import html
import logging
import math
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from email.utils import make_msgid
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from threading import Event

from wca_competition_reminder import __version__
from wca_competition_reminder.config import (
    AppConfig,
    ConfigurationError,
    load_config,
    load_smtp_password,
)
from wca_competition_reminder.distance import coordinates_are_valid
from wca_competition_reminder.events import OFFICIAL_EVENT_IDS, format_event_ids
from wca_competition_reminder.locking import AlreadyRunningError, ProcessLock
from wca_competition_reminder.mailer import DeliverySendError, SmtpMailer
from wca_competition_reminder.models import Delivery
from wca_competition_reminder.service import ReminderService
from wca_competition_reminder.state import StateError, StateStore
from wca_competition_reminder.utils import mask_email, utc_now
from wca_competition_reminder.wca import WcaApiError, WcaClient

LOGGER = logging.getLogger(__name__)
LOG_RETENTION_DAYS = 7


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wca-competition-reminder",
        description="Poll WCA competitions and email personalized event reminders.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="TOML configuration path (default: ./config.toml)",
    )
    parser.add_argument("--state", type=Path, help="override the SQLite state path")
    parser.add_argument("--lock", type=Path, help="override the process lock path")
    parser.add_argument(
        "--smtp-password-file",
        type=Path,
        help="read the SMTP password from this file",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("poll", help="run one polling and delivery cycle")
    commands.add_parser("run", help="poll continuously at one-minute intervals")
    commands.add_parser("check-config", help="validate configuration without sending email")
    commands.add_parser("send-test", help="send one test email to each configured recipient")
    commands.add_parser("status", help="show state and delivery counts")
    web_command = commands.add_parser("web", help="serve the subscription form and JSON API")
    web_command.add_argument(
        "--host",
        default="127.0.0.1",
        help="web bind address (default: 127.0.0.1)",
    )
    web_command.add_argument(
        "--port",
        type=int,
        default=8080,
        help="web bind port (default: 8080)",
    )
    commands.add_parser(
        "retry-blocked",
        help="move permanently blocked deliveries back to the pending queue",
    )
    return parser


class _BelowErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < logging.ERROR


def _configure_logging(
    level: str,
    *,
    log_dir: Path | None = None,
    process_name: str = "application",
) -> None:
    numeric_level = getattr(logging, level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    below_error = _BelowErrorFilter()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(numeric_level)
    stdout_handler.addFilter(below_error)
    stdout_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(max(numeric_level, logging.ERROR))
    stderr_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [stdout_handler, stderr_handler]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        out_file_handler = TimedRotatingFileHandler(
            log_dir / f"{process_name}.out.log",
            when="midnight",
            interval=1,
            backupCount=LOG_RETENTION_DAYS - 1,
            encoding="utf-8",
            delay=True,
        )
        out_file_handler.setLevel(numeric_level)
        out_file_handler.addFilter(below_error)
        out_file_handler.setFormatter(formatter)
        handlers.append(out_file_handler)

        error_file_handler = TimedRotatingFileHandler(
            log_dir / f"{process_name}.err.log",
            when="midnight",
            interval=1,
            backupCount=LOG_RETENTION_DAYS - 1,
            encoding="utf-8",
            delay=True,
        )
        error_file_handler.setLevel(max(numeric_level, logging.ERROR))
        error_file_handler.setFormatter(formatter)
        handlers.append(error_file_handler)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.close()
    root_logger.handlers = handlers
    root_logger.setLevel(numeric_level)


def _with_path_overrides(config: AppConfig, arguments: argparse.Namespace) -> AppConfig:
    return replace(
        config,
        state_path=(arguments.state.resolve() if arguments.state else config.state_path),
        lock_path=(arguments.lock.resolve() if arguments.lock else config.lock_path),
    )


def _poll_cycle(
    config: AppConfig,
    password_file: Path | None,
    *,
    stop_event: Event | None = None,
) -> int:
    def wait_for_retry(delay: float) -> None:
        if stop_event is None:
            time.sleep(delay)
        else:
            stop_event.wait(delay)

    stop_requested = stop_event.is_set if stop_event is not None else lambda: False
    password = load_smtp_password(config.smtp, password_file=password_file)
    with (
        StateStore(config.state_path) as state,
        WcaClient(
            config.wca,
            sleeper=wait_for_retry,
            stop_requested=stop_requested,
        ) as wca,
        SmtpMailer(config.smtp, password) as mailer,
    ):
        succeeded = ReminderService(
            config,
            state,
            wca,
            mailer,
            stop_requested=stop_requested,
        ).run_once()
    return 0 if succeeded else 1


def _poll(config: AppConfig, password_file: Path | None) -> int:
    with ProcessLock(config.lock_path):
        return _poll_cycle(config, password_file)


def _run_poll_loop(
    poll_once: Callable[[], int],
    stop_event: Event,
    *,
    interval_seconds: float = 60.0,
    monotonic: Callable[[], float] = time.monotonic,
    waiter: Callable[[float], bool] | None = None,
) -> int:
    if interval_seconds <= 0:
        raise ValueError("poll interval must be positive")

    wait = waiter or stop_event.wait
    next_run_at = monotonic()
    while not stop_event.is_set():
        LOGGER.info("poll cycle starting")
        try:
            exit_code = poll_once()
        except WcaApiError as exc:
            if stop_event.is_set():
                LOGGER.info("poll cycle interrupted for shutdown")
            else:
                LOGGER.exception("poll cycle failed; continuing error=%s", exc)
        else:
            if exit_code != 0:
                LOGGER.error("poll cycle returned exit_code=%d; continuing", exit_code)
            else:
                LOGGER.info("poll cycle completed")

        if stop_event.is_set():
            break

        next_run_at += interval_seconds
        now = monotonic()
        if now > next_run_at:
            skipped_intervals = math.ceil((now - next_run_at) / interval_seconds)
            next_run_at += skipped_intervals * interval_seconds
            LOGGER.warning(
                "poll cycle overran schedule skipped_intervals=%d",
                skipped_intervals,
            )
        if wait(max(0.0, next_run_at - now)):
            break

    LOGGER.info("polling loop stopped")
    return 0


def _run(config: AppConfig, password_file: Path | None) -> int:
    stop_event = Event()

    def request_stop(signal_number: int, _: object) -> None:
        LOGGER.info("shutdown requested signal=%s", signal.Signals(signal_number).name)
        stop_event.set()

    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    try:
        with ProcessLock(config.lock_path):
            return _run_poll_loop(
                lambda: _poll_cycle(config, password_file, stop_event=stop_event),
                stop_event,
            )
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)


def _send_test(config: AppConfig, password_file: Path | None) -> int:
    password = load_smtp_password(config.smtp, password_file=password_file)
    now = utc_now()
    domain = config.smtp.from_address.rpartition("@")[2] or "wca-reminder.local"
    with SmtpMailer(config.smtp, password) as mailer:
        for recipient in config.recipients:
            condition_lines: list[str] = []
            for index, condition in enumerate(recipient.conditions, start=1):
                followed_events = (
                    f"全部 {len(OFFICIAL_EVENT_IDS)} 个 WCA 官方项目"
                    if condition.event_ids is None
                    else format_event_ids(condition.event_ids)
                )
                configured_location = (
                    f"{condition.latitude:.6f}, {condition.longitude:.6f}"
                    if coordinates_are_valid(condition.latitude, condition.longitude)
                    else "-"
                )
                regions = sorted(
                    (condition.country_names or frozenset())
                    | (condition.continent_names or frozenset())
                )
                radius = (
                    f"{condition.max_distance_km:g} km"
                    if condition.max_distance_km
                    else "不限"
                )
                condition_lines.append(
                    f"条件 {index:02d}：位置 {configured_location}；"
                    f"半径 {radius}；"
                    f"项目 {followed_events}；地区 {', '.join(regions) if regions else '全球'}"
                )
            text_conditions = "\n".join(condition_lines)
            html_conditions = "".join(
                f"<li>{html.escape(line)}</li>" for line in condition_lines
            )
            delivery = Delivery(
                delivery_id=0,
                claim_token="configuration-test",
                competition_id="configuration-test",
                recipient_email=recipient.email,
                recipient_name=recipient.name,
                message_id=make_msgid(domain=domain),
                subject="[WCA 比赛提醒] 配置测试",
                text_body=(
                    "这是一封配置测试邮件。\n\n"
                    f"已配置 {len(condition_lines)} 条关注条件：\n{text_conditions}\n"
                    "收到此邮件表示 SMTP 与该收件人配置可用。"
                ),
                html_body=(
                    "<p>这是一封配置测试邮件。</p>"
                    f"<p>已配置 {len(condition_lines)} 条关注条件：</p>"
                    f"<ol>{html_conditions}</ol>"
                    "<p>收到此邮件表示 SMTP 与该收件人配置可用。</p>"
                ),
                created_at=now,
                attempts=1,
            )
            mailer.send(delivery)
            LOGGER.info("test email sent recipient=%s", mask_email(recipient.email))
    return 0


def _status(config: AppConfig) -> int:
    with StateStore(config.state_path) as state:
        counts = state.counts()
        baseline = state.is_baseline_initialized()
    print(f"baseline_initialized={str(baseline).lower()}")
    for key, value in sorted(counts.items()):
        print(f"{key}={value}")
    return 0


def _retry_blocked(config: AppConfig) -> int:
    with ProcessLock(config.lock_path), StateStore(config.state_path) as state:
        count = state.retry_blocked_deliveries(datetime.now(UTC))
    print(f"retried_blocked_deliveries={count}")
    return 0


def _web(
    config: AppConfig,
    host: str,
    port: int,
    password_file: Path | None,
) -> int:
    from wca_competition_reminder.web import serve_web

    password = load_smtp_password(config.smtp, password_file=password_file)
    serve_web(config, host, port, smtp_password=password)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    _configure_logging(arguments.log_level)

    try:
        config = _with_path_overrides(load_config(arguments.config), arguments)
        _configure_logging(
            arguments.log_level,
            log_dir=config.log_dir,
            process_name=arguments.command,
        )
        if arguments.command == "check-config":
            print(
                "configuration_valid=true "
                f"python={sys.version_info.major}.{sys.version_info.minor} "
                f"timezone={config.timezone_name} recipients={len(config.recipients)} "
                f"admins={len(config.admins)}"
            )
            return 0
        if arguments.command == "poll":
            return _poll(config, arguments.smtp_password_file)
        if arguments.command == "run":
            return _run(config, arguments.smtp_password_file)
        if arguments.command == "send-test":
            return _send_test(config, arguments.smtp_password_file)
        if arguments.command == "status":
            return _status(config)
        if arguments.command == "retry-blocked":
            return _retry_blocked(config)
        if arguments.command == "web":
            return _web(
                config,
                arguments.host,
                arguments.port,
                arguments.smtp_password_file,
            )
        parser.error(f"unknown command: {arguments.command}")
    except AlreadyRunningError as exc:
        LOGGER.warning("%s", exc)
        return 0
    except (ConfigurationError, DeliverySendError, StateError, WcaApiError) as exc:
        LOGGER.error("%s", exc)
        return 1
    except Exception:
        LOGGER.exception("unexpected fatal error")
        return 1
    return 2
