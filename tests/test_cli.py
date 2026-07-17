import io
import logging
import signal
from dataclasses import replace
from pathlib import Path
from threading import Event, Timer

import pytest

from tests.conftest import make_config
from wca_competition_reminder import cli
from wca_competition_reminder.config import ConfigurationError, RecipientConfig
from wca_competition_reminder.locking import AlreadyRunningError, ProcessLock
from wca_competition_reminder.mailer import DeliverySendError
from wca_competition_reminder.wca import WcaApiError


class MonotonicClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current


def test_send_test_uses_dash_when_recipient_coordinates_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = []

    class RecordingMailer:
        def __init__(self, *_args: object) -> None:
            pass

        def __enter__(self) -> "RecordingMailer":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def send(self, delivery) -> None:
            sent.append(delivery)

    config = replace(
        make_config(tmp_path),
        recipients=(RecipientConfig("one@example.com", None, None, "One"),),
    )
    monkeypatch.setattr(cli, "load_smtp_password", lambda *_args, **_kwargs: "secret")
    monkeypatch.setattr(cli, "SmtpMailer", RecordingMailer)

    assert cli._send_test(config, None) == 0
    assert "已配置位置：-" in sent[0].text_body
    assert "已配置位置：-" in sent[0].html_body


def test_parser_accepts_run_command() -> None:
    assert cli.build_parser().parse_args(["run"]).command == "run"


def test_logging_routes_levels_and_keeps_seven_daily_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    root_logger = logging.getLogger()
    previous_handlers = root_logger.handlers
    previous_level = root_logger.level
    root_logger.handlers = []
    try:
        cli._configure_logging("INFO", log_dir=tmp_path, process_name="web")
        logger = logging.getLogger("routing-test")
        logger.info("info-output")
        logger.warning("warning-output")
        logger.error("error-output")
        for handler in root_logger.handlers:
            handler.flush()

        assert "info-output" in stdout.getvalue()
        assert "warning-output" in stdout.getvalue()
        assert "error-output" not in stdout.getvalue()
        assert "error-output" in stderr.getvalue()
        assert "warning-output" not in stderr.getvalue()
        assert "warning-output" in (tmp_path / "web.out.log").read_text(encoding="utf-8")
        assert "error-output" in (tmp_path / "web.err.log").read_text(encoding="utf-8")
        rotating_handlers = [
            handler
            for handler in root_logger.handlers
            if isinstance(handler, cli.TimedRotatingFileHandler)
        ]
        assert len(rotating_handlers) == 2
        assert cli.LOG_RETENTION_DAYS == 7
        assert all(handler.backupCount == 6 for handler in rotating_handlers)
    finally:
        for handler in root_logger.handlers:
            handler.close()
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)


def test_run_loop_starts_immediately_and_stays_on_minute_boundaries() -> None:
    clock = MonotonicClock()
    stop_event = Event()
    starts: list[float] = []
    waits: list[float] = []

    def poll_once() -> int:
        starts.append(clock.current)
        if len(starts) == 3:
            stop_event.set()
        return 0

    def wait(delay: float) -> bool:
        waits.append(delay)
        clock.current += delay
        return False

    assert (
        cli._run_poll_loop(
            poll_once,
            stop_event,
            monotonic=clock,
            waiter=wait,
        )
        == 0
    )
    assert starts == [0.0, 60.0, 120.0]
    assert waits == [60.0, 60.0]


def test_run_loop_skips_missed_ticks_without_drifting() -> None:
    clock = MonotonicClock()
    stop_event = Event()
    starts: list[float] = []
    waits: list[float] = []
    durations = iter((5.0, 70.0, 0.0))

    def poll_once() -> int:
        starts.append(clock.current)
        clock.current += next(durations)
        if len(starts) == 3:
            stop_event.set()
        return 0

    def wait(delay: float) -> bool:
        waits.append(delay)
        clock.current += delay
        return False

    cli._run_poll_loop(
        poll_once,
        stop_event,
        monotonic=clock,
        waiter=wait,
    )

    assert starts == [0.0, 60.0, 180.0]
    assert waits == [55.0, 50.0]


def test_run_loop_continues_after_failed_result_and_expected_error(
    caplog,
) -> None:
    clock = MonotonicClock()
    stop_event = Event()
    outcomes = iter((1, WcaApiError("temporary failure"), 0))

    def poll_once() -> int:
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == 0:
            stop_event.set()
        return outcome

    def wait(delay: float) -> bool:
        clock.current += delay
        return False

    with caplog.at_level(logging.ERROR):
        assert (
            cli._run_poll_loop(
                poll_once,
                stop_event,
                monotonic=clock,
                waiter=wait,
            )
            == 0
        )

    assert "poll cycle returned exit_code=1; continuing" in caplog.text
    assert "poll cycle failed; continuing error=temporary failure" in caplog.text


def test_run_loop_wait_is_interrupted_by_shutdown() -> None:
    stop_event = Event()
    timer: Timer | None = None

    def poll_once() -> int:
        nonlocal timer
        timer = Timer(0.01, stop_event.set)
        timer.start()
        return 0

    assert cli._run_poll_loop(poll_once, stop_event) == 0
    assert timer is not None
    timer.join(timeout=1)
    assert not timer.is_alive()


@pytest.mark.parametrize(
    "error",
    (
        ConfigurationError("missing password file"),
        DeliverySendError(
            "SMTP authentication failed",
            permanent=True,
            stop_run=True,
        ),
    ),
)
def test_run_loop_does_not_hide_permanent_configuration_errors(error: Exception) -> None:
    def poll_once() -> int:
        raise error

    with pytest.raises(type(error), match=str(error)):
        cli._run_poll_loop(poll_once, Event())


@pytest.mark.parametrize("shutdown_signal", (signal.SIGINT, signal.SIGTERM))
def test_run_uses_supplied_paths_and_stops_on_signals(
    tmp_path: Path,
    monkeypatch,
    shutdown_signal: signal.Signals,
) -> None:
    config = make_config(tmp_path)
    password_file = tmp_path / "smtp-password"
    handlers: dict[signal.Signals, object] = {}
    cycle_arguments: list[tuple[object, object, object]] = []

    def fake_signal(signal_number, handler):
        previous = handlers.get(signal_number, signal.SIG_DFL)
        handlers[signal_number] = handler
        return previous

    def fake_cycle(received_config, received_password_file, *, stop_event) -> int:
        cycle_arguments.append((received_config, received_password_file, stop_event))
        return 0

    def fake_loop(poll_once, stop_event, **_kwargs) -> int:
        with pytest.raises(AlreadyRunningError), ProcessLock(config.lock_path):
            pass
        assert poll_once() == 0
        handler = handlers[shutdown_signal]
        assert callable(handler)
        handler(shutdown_signal, None)
        assert stop_event.is_set()
        return 0

    monkeypatch.setattr(cli.signal, "signal", fake_signal)
    monkeypatch.setattr(cli, "_poll_cycle", fake_cycle)
    monkeypatch.setattr(cli, "_run_poll_loop", fake_loop)

    assert cli._run(config, password_file) == 0
    assert len(cycle_arguments) == 1
    received_config, received_password_file, received_stop_event = cycle_arguments[0]
    assert (received_config, received_password_file) == (config, password_file)
    assert received_stop_event.is_set()
    assert handlers[signal.SIGINT] == signal.SIG_DFL
    assert handlers[signal.SIGTERM] == signal.SIG_DFL
