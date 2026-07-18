from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import mimetypes
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from wca_competition_reminder.config import AppConfig
from wca_competition_reminder.events import OFFICIAL_EVENTS
from wca_competition_reminder.mailer import DeliverySendError, SmtpMailer
from wca_competition_reminder.state import StateStore
from wca_competition_reminder.subscriptions import (
    SubscriptionConflictError,
    SubscriptionNotFoundError,
    SubscriptionService,
    SubscriptionValidationError,
    SubscriptionView,
    normalize_email,
)
from wca_competition_reminder.utils import mask_email, utc_now
from wca_competition_reminder.wca import WcaApiError, WcaClient

LOGGER = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 64 * 1024
OPTIONS_CACHE_SECONDS = 6 * 60 * 60
VERIFICATION_CODE_SECONDS = 5 * 60
VERIFICATION_SEND_COOLDOWN_SECONDS = 50
ADMIN_SESSION_SECONDS = 8 * 60 * 60
ADMIN_LOGIN_ATTEMPTS = 5
ADMIN_LOGIN_WINDOW_SECONDS = 5 * 60
ADMIN_COOKIE_NAME = "wca_admin_session"
APPLICATION_BASE_PATH_PLACEHOLDER = "__WCA_APPLICATION_BASE_PATH__"
GOOGLE_MAPS_API_KEY_PLACEHOLDER = "__WCA_GOOGLE_MAPS_API_KEY__"
AMAP_API_KEY_PLACEHOLDER = "__WCA_AMAP_API_KEY__"
AMAP_SECURITY_JS_CODE_PLACEHOLDER = "__WCA_AMAP_SECURITY_JS_CODE__"
AMAP_SERVICE_HOST_PLACEHOLDER = "__WCA_AMAP_SERVICE_HOST__"
CSP_NONCE_PLACEHOLDER = "__WCA_CSP_NONCE__"
FORWARDED_PREFIX_PATTERN = re.compile(r"/(?:[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*)?")
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
    "/admin": "admin.html",
    "/admin/": "admin.html",
    "/admin.html": "admin.html",
    "/admin.js": "admin.js",
    "/admin.css": "admin.css",
}

VerificationSender = Callable[[str, str, datetime], None]
Clock = Callable[[], datetime]
CodeFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class WebSettings:
    config: AppConfig
    static_dir: Path


@dataclass(frozen=True, slots=True)
class VerificationChallenge:
    code_hash: bytes
    sent_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AdminSession:
    username: str
    expires_at: datetime


class VerificationRateLimitError(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("验证码发送过于频繁")
        self.retry_after_seconds = retry_after_seconds


class ReminderHttpServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        settings: WebSettings,
        *,
        verification_sender: VerificationSender,
        clock: Clock = utc_now,
        code_factory: CodeFactory | None = None,
    ) -> None:
        self.settings = settings
        self._options_lock = Lock()
        self._options_cache: dict[str, Any] | None = None
        self._options_cached_at = 0.0
        self._verification_lock = Lock()
        self._verification_challenges: dict[str, VerificationChallenge] = {}
        self._verification_sender = verification_sender
        self._clock = clock
        self._code_factory = code_factory or (lambda: f"{secrets.randbelow(1_000_000):06d}")
        self._admin_lock = Lock()
        self._admin_sessions: dict[str, AdminSession] = {}
        self._admin_login_failures: dict[str, list[datetime]] = {}
        super().__init__(address, ReminderRequestHandler)

    @staticmethod
    def _verification_hash(email: str, code: str) -> bytes:
        return hashlib.sha256(f"{email}\0{code}".encode()).digest()

    def issue_verification_code(self, email: str) -> None:
        now = self._clock()
        with self._verification_lock:
            current = self._verification_challenges.get(email)
            if current is not None:
                retry_after = (
                    current.sent_at + timedelta(seconds=VERIFICATION_SEND_COOLDOWN_SECONDS) - now
                ).total_seconds()
                if retry_after > 0:
                    raise VerificationRateLimitError(math.ceil(retry_after))
            code = self._code_factory()
            if len(code) != 6 or not code.isdigit():
                raise RuntimeError("verification code factory must return six digits")
            challenge = VerificationChallenge(
                code_hash=self._verification_hash(email, code),
                sent_at=now,
                expires_at=now + timedelta(seconds=VERIFICATION_CODE_SECONDS),
            )
            self._verification_challenges[email] = challenge
        try:
            self._verification_sender(email, code, now)
        except BaseException:
            with self._verification_lock:
                if self._verification_challenges.get(email) is challenge:
                    self._verification_challenges.pop(email, None)
            raise

    @contextmanager
    def verified_registration(self, email: str, code_value: object) -> Iterator[None]:
        if not isinstance(code_value, str) or len(code_value.strip()) != 6:
            raise SubscriptionValidationError("请输入 6 位邮箱验证码")
        code = code_value.strip()
        if not code.isdigit():
            raise SubscriptionValidationError("请输入 6 位邮箱验证码")
        with self._verification_lock:
            challenge = self._verification_challenges.get(email)
            if (
                challenge is None
                or self._clock() >= challenge.expires_at
                or not hmac.compare_digest(
                    challenge.code_hash,
                    self._verification_hash(email, code),
                )
            ):
                raise SubscriptionValidationError("邮箱验证码无效或已过期")
            try:
                yield
            except BaseException:
                raise
            else:
                self._verification_challenges.pop(email, None)

    def options_payload(self) -> dict[str, Any]:
        now = monotonic()
        if (
            self._options_cache is not None
            and now - self._options_cached_at < OPTIONS_CACHE_SECONDS
        ):
            return self._options_cache
        with self._options_lock:
            now = monotonic()
            if (
                self._options_cache is not None
                and now - self._options_cached_at < OPTIONS_CACHE_SECONDS
            ):
                return self._options_cache
            try:
                with WcaClient(self.settings.config.wca) as wca:
                    countries = wca.fetch_countries()
            except WcaApiError:
                if self._options_cache is not None:
                    return self._options_cache
                raise
            self._options_cache = {
                "events": [{"id": event_id, "name": name} for event_id, name in OFFICIAL_EVENTS],
                "continents": sorted({country.continent_name for country in countries.values()}),
                "countries": [
                    {
                        "name": country.name,
                        "iso2": country.iso2,
                        "continent": country.continent_name,
                    }
                    for country in sorted(countries.values(), key=lambda item: item.name.casefold())
                ],
            }
            self._options_cached_at = monotonic()
            return self._options_cache

    @staticmethod
    def _credential_matches(candidate: str, configured: str) -> bool:
        candidate_digest = hashlib.sha256(candidate.encode("utf-8")).digest()
        configured_digest = hashlib.sha256(configured.encode("utf-8")).digest()
        return hmac.compare_digest(candidate_digest, configured_digest)

    def create_admin_session(self, username: object, password: object) -> str | None:
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        authenticated_username: str | None = None
        for admin in self.settings.config.admins:
            username_matches = self._credential_matches(username, admin.username)
            password_matches = self._credential_matches(password, admin.password)
            if username_matches and password_matches:
                authenticated_username = admin.username
        if authenticated_username is None:
            return None

        token = secrets.token_urlsafe(32)
        now = self._clock()
        with self._admin_lock:
            self._prune_admin_sessions(now)
            self._admin_sessions[token] = AdminSession(
                username=authenticated_username,
                expires_at=now + timedelta(seconds=ADMIN_SESSION_SECONDS),
            )
        return token

    def admin_login_retry_after(self, client: str) -> int:
        now = self._clock()
        with self._admin_lock:
            failures = self._current_admin_login_failures(client, now)
            if len(failures) < ADMIN_LOGIN_ATTEMPTS:
                return 0
            retry_at = failures[0] + timedelta(seconds=ADMIN_LOGIN_WINDOW_SECONDS)
            return max(1, math.ceil((retry_at - now).total_seconds()))

    def record_admin_login_failure(self, client: str) -> None:
        now = self._clock()
        with self._admin_lock:
            failures = self._current_admin_login_failures(client, now)
            failures.append(now)
            self._admin_login_failures[client] = failures

    def clear_admin_login_failures(self, client: str) -> None:
        with self._admin_lock:
            self._admin_login_failures.pop(client, None)

    def admin_session(self, token: str | None) -> AdminSession | None:
        if not token:
            return None
        now = self._clock()
        with self._admin_lock:
            self._prune_admin_sessions(now)
            return self._admin_sessions.get(token)

    def revoke_admin_session(self, token: str | None) -> AdminSession | None:
        if not token:
            return None
        with self._admin_lock:
            return self._admin_sessions.pop(token, None)

    def _prune_admin_sessions(self, now: datetime) -> None:
        expired = [
            token for token, session in self._admin_sessions.items() if now >= session.expires_at
        ]
        for token in expired:
            self._admin_sessions.pop(token, None)

    def _current_admin_login_failures(self, client: str, now: datetime) -> list[datetime]:
        cutoff = now - timedelta(seconds=ADMIN_LOGIN_WINDOW_SECONDS)
        failures = [
            failed_at
            for failed_at in self._admin_login_failures.get(client, [])
            if failed_at > cutoff
        ]
        if failures:
            self._admin_login_failures[client] = failures
        else:
            self._admin_login_failures.pop(client, None)
        return failures


class ReminderRequestHandler(BaseHTTPRequestHandler):
    server_version = "WcaCompetitionReminderWeb/0.1"

    @property
    def _settings(self) -> WebSettings:
        return cast(ReminderHttpServer, self.server).settings

    @property
    def _reminder_server(self) -> ReminderHttpServer:
        return cast(ReminderHttpServer, self.server)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers()
        self.send_header("Allow", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/api/admin/session":
            session = self._admin_session()
            if session is None:
                self._audit("admin_session_check", "unauthorized", level=logging.WARNING)
                self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "管理员会话无效")
            else:
                self._audit(
                    "admin_session_check",
                    "success",
                    username=session.username,
                )
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "authenticated": True,
                        "username": session.username,
                        "expires_at": session.expires_at.isoformat(),
                    },
                )
            return
        if parsed.path == "/api/admin/activity-logs":
            self._admin_activity_logs(parsed.query)
            return
        if parsed.path == "/api/admin/snapshot":
            session = self._require_admin("admin_snapshot_view")
            if session is None:
                return
            try:
                with StateStore(self._settings.config.state_path) as state:
                    snapshot = state.admin_snapshot(now=self._reminder_server._clock())
                    managed_config_emails = {
                        recipient.email
                        for recipient in self._settings.config.recipients
                        if state.find_subscriber(recipient.email) is not None
                    }
                self._add_configured_recipients(snapshot, managed_config_emails)
            except Exception:
                LOGGER.exception("admin snapshot failed")
                self._audit(
                    "admin_snapshot_view",
                    "failed",
                    username=session.username,
                    level=logging.ERROR,
                )
                self._send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "snapshot_failed",
                    "管理数据读取失败",
                )
            else:
                snapshot.update(
                    {
                        "generated_at": self._reminder_server._clock().isoformat(),
                        "timezone": self._settings.config.timezone_name,
                        "admin": {"username": session.username},
                    }
                )
                self._audit(
                    "admin_snapshot_view",
                    "success",
                    username=session.username,
                )
                self._send_json(HTTPStatus.OK, snapshot)
            return
        if parsed.path == "/api/options":
            try:
                options = cast(ReminderHttpServer, self.server).options_payload()
            except WcaApiError:
                self._audit(
                    "subscription_options_view",
                    "failed",
                    level=logging.ERROR,
                )
                self._send_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "wca_unavailable",
                    "暂时无法读取 WCA 地区目录",
                )
            else:
                self._audit("subscription_options_view", "success")
                self._send_json(HTTPStatus.OK, options)
            return
        if parsed.path == "/api/health":
            with StateStore(self._settings.config.state_path) as state:
                self._send_json(
                    HTTPStatus.OK,
                    {"status": "ok", "active_subscribers": state.subscriber_count()},
                )
            return
        if parsed.path == "/api/subscriptions":
            query = parse_qs(parsed.query, keep_blank_values=True)
            payload = {"email": query.get("email", [""])[0]}
            try:
                with StateStore(self._settings.config.state_path) as state:
                    subscription = SubscriptionService(state).get(payload)
            except SubscriptionValidationError as exc:
                self._audit(
                    "subscription_lookup",
                    "rejected",
                    email=self._payload_email(payload),
                    reason=str(exc),
                    level=logging.WARNING,
                )
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
            except SubscriptionNotFoundError as exc:
                self._audit(
                    "subscription_lookup",
                    "not_found",
                    email=self._payload_email(payload),
                    reason=str(exc),
                    level=logging.WARNING,
                )
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", str(exc))
            else:
                self._audit(
                    "subscription_lookup",
                    "success",
                    email=subscription.email,
                )
                self._send_json(HTTPStatus.OK, {"subscription": subscription.to_dict()})
            return
        if parsed.path in STATIC_FILES:
            if parsed.path in {"/", "/index.html"}:
                self._audit("subscription_page_view", "success")
            elif parsed.path in {"/admin", "/admin/", "/admin.html"}:
                self._audit("admin_page_view", "success")
            self._send_static(STATIC_FILES[parsed.path])
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not_found", "资源不存在")

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/admin/login":
            self._admin_login()
            return
        if path == "/api/admin/logout":
            self._admin_logout()
            return
        if path == "/api/verification-codes":
            self._send_verification_code()
            return
        if path != "/api/subscriptions":
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "接口不存在")
            return
        payload: object = None
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise SubscriptionValidationError("请求内容必须是 JSON 对象")
            email = normalize_email(payload.get("email"))
            server = cast(ReminderHttpServer, self.server)
            with (
                server.verified_registration(email, payload.get("verification_code")),
                StateStore(self._settings.config.state_path) as state,
            ):
                subscription = SubscriptionService(state).register(payload)
        except SubscriptionValidationError as exc:
            self._audit(
                "subscription_register",
                "rejected",
                email=self._payload_email(payload),
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except SubscriptionConflictError as exc:
            self._audit(
                "subscription_register",
                "conflict",
                email=self._payload_email(payload),
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.CONFLICT, "already_subscribed", str(exc))
        else:
            self._audit(
                "subscription_register",
                "success",
                email=subscription.email,
                subscription=self._subscription_audit_details(subscription),
            )
            self._send_json(
                HTTPStatus.CREATED,
                {"subscription": subscription.to_dict()},
            )

    def _send_verification_code(self) -> None:
        email = ""
        payload: object = None
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise SubscriptionValidationError("请求内容必须是 JSON 对象")
            email = normalize_email(payload.get("email"))
            with StateStore(self._settings.config.state_path) as state:
                record = state.find_subscriber(email)
                if record is not None and record.active:
                    raise SubscriptionConflictError("该邮箱已经订阅，请直接修改订阅")
            cast(ReminderHttpServer, self.server).issue_verification_code(email)
        except SubscriptionValidationError as exc:
            self._audit(
                "verification_code_request",
                "rejected",
                email=self._payload_email(payload),
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except SubscriptionConflictError as exc:
            self._audit(
                "verification_code_request",
                "conflict",
                email=email,
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.CONFLICT, "already_subscribed", str(exc))
        except VerificationRateLimitError as exc:
            self._audit(
                "verification_code_request",
                "rate_limited",
                email=email,
                retry_after_seconds=exc.retry_after_seconds,
                level=logging.WARNING,
            )
            self._send_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {
                    "error": "rate_limited",
                    "message": f"请在 {exc.retry_after_seconds} 秒后重新获取验证码",
                    "retry_after_seconds": exc.retry_after_seconds,
                },
                extra_headers={"Retry-After": str(exc.retry_after_seconds)},
            )
        except DeliverySendError:
            LOGGER.error(
                "verification email failed recipient=%s",
                mask_email(email),
                exc_info=True,
            )
            self._audit(
                "verification_code_request",
                "delivery_failed",
                email=email,
                level=logging.ERROR,
            )
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "email_unavailable",
                "验证码邮件发送失败，请稍后重试",
            )
        else:
            self._audit(
                "verification_code_request",
                "success",
                email=email,
                expires_in_seconds=VERIFICATION_CODE_SECONDS,
            )
            self._send_json(
                HTTPStatus.OK,
                {
                    "message": "验证码已发送",
                    "expires_in_seconds": VERIFICATION_CODE_SECONDS,
                    "cooldown_seconds": VERIFICATION_SEND_COOLDOWN_SECONDS,
                },
            )

    def do_PUT(self) -> None:
        if urlsplit(self.path).path != "/api/subscriptions":
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "接口不存在")
            return
        payload: object = None
        try:
            payload = self._read_json()
            with StateStore(self._settings.config.state_path) as state:
                subscription = SubscriptionService(state).update(payload)
        except SubscriptionValidationError as exc:
            self._audit(
                "subscription_update",
                "rejected",
                email=self._payload_email(payload),
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except SubscriptionNotFoundError as exc:
            self._audit(
                "subscription_update",
                "not_found",
                email=self._payload_email(payload),
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", str(exc))
        else:
            self._audit(
                "subscription_update",
                "success",
                email=subscription.email,
                subscription=self._subscription_audit_details(subscription),
            )
            self._send_json(HTTPStatus.OK, {"subscription": subscription.to_dict()})

    def do_DELETE(self) -> None:
        if urlsplit(self.path).path != "/api/subscriptions":
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "接口不存在")
            return
        payload: object = None
        try:
            payload = self._read_json()
            with StateStore(self._settings.config.state_path) as state:
                subscription = SubscriptionService(state).cancel(payload)
        except SubscriptionValidationError as exc:
            self._audit(
                "subscription_cancel",
                "rejected",
                email=self._payload_email(payload),
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except SubscriptionNotFoundError as exc:
            self._audit(
                "subscription_cancel",
                "not_found",
                email=self._payload_email(payload),
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", str(exc))
        else:
            self._audit(
                "subscription_cancel",
                "success",
                email=subscription.email,
                subscription=self._subscription_audit_details(subscription),
            )
            self._send_json(HTTPStatus.OK, {"subscription": subscription.to_dict()})

    def _admin_activity_logs(self, query_string: str) -> None:
        session = self._require_admin("admin_activity_logs_view")
        if session is None:
            return

        query = parse_qs(query_string, keep_blank_values=True)

        def first(name: str) -> str:
            return query.get(name, [""])[0].strip()

        try:
            limit = int(first("limit") or "100")
            before_value = first("before_id")
            before_id = int(before_value) if before_value else None
            actor_value = first("actor_type")
            actor_type = actor_value if actor_value and actor_value != "all" else None
            action_value = first("action")
            action = action_value if action_value and action_value != "all" else None
            outcome_value = first("outcome")
            outcome = outcome_value if outcome_value and outcome_value != "all" else None
            search = first("search") or None
            with StateStore(self._settings.config.state_path) as state:
                result = state.activity_logs(
                    now=self._reminder_server._clock(),
                    limit=limit,
                    before_id=before_id,
                    actor_type=actor_type,
                    action=action,
                    outcome=outcome,
                    search=search,
                )
        except ValueError as exc:
            self._audit(
                "admin_activity_logs_view",
                "rejected",
                username=session.username,
                reason=str(exc),
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
            return
        except Exception:
            LOGGER.exception("admin activity log query failed")
            self._audit(
                "admin_activity_logs_view",
                "failed",
                username=session.username,
                level=logging.ERROR,
            )
            self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "activity_logs_failed",
                "行为日志读取失败",
            )
            return

        result.update(
            {
                "generated_at": self._reminder_server._clock().isoformat(),
                "timezone": self._settings.config.timezone_name,
            }
        )
        self._audit(
            "admin_activity_logs_view",
            "success",
            username=session.username,
            returned_count=len(cast(list[object], result["items"])),
            actor_filter=actor_type,
            action_filter=action,
            outcome_filter=outcome,
        )
        self._send_json(HTTPStatus.OK, cast(dict[str, Any], result))

    def _admin_login(self) -> None:
        if not self._settings.config.admins:
            self._audit("admin_login", "not_configured", level=logging.WARNING)
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "admin_not_configured",
                "尚未配置管理员账号",
            )
            return

        payload: object = None
        try:
            payload = self._read_json()
        except SubscriptionValidationError as exc:
            self._audit("admin_login", "rejected", level=logging.WARNING)
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
            return
        if not isinstance(payload, dict):
            self._audit("admin_login", "rejected", level=logging.WARNING)
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", "请求内容必须是 JSON 对象")
            return

        username = payload.get("username")
        password = payload.get("password")
        client = self.client_address[0]
        retry_after = self._reminder_server.admin_login_retry_after(client)
        if retry_after:
            self._audit(
                "admin_login",
                "rate_limited",
                username=username,
                level=logging.WARNING,
            )
            self._send_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {
                    "error": "rate_limited",
                    "message": "登录失败次数过多，请稍后重试",
                    "retry_after_seconds": retry_after,
                },
                extra_headers={"Retry-After": str(retry_after)},
            )
            return
        token = self._reminder_server.create_admin_session(username, password)
        if token is None:
            self._reminder_server.record_admin_login_failure(client)
            self._audit(
                "admin_login",
                "denied",
                username=username,
                level=logging.WARNING,
            )
            self._send_error(HTTPStatus.UNAUTHORIZED, "invalid_credentials", "用户名或密码错误")
            return

        self._reminder_server.clear_admin_login_failures(client)
        session = self._reminder_server.admin_session(token)
        if session is None:
            raise RuntimeError("new admin session could not be read")
        self._audit("admin_login", "success", username=session.username)
        self._send_json(
            HTTPStatus.OK,
            {
                "authenticated": True,
                "username": session.username,
                "expires_at": session.expires_at.isoformat(),
            },
            extra_headers={"Set-Cookie": self._admin_cookie(token, ADMIN_SESSION_SECONDS)},
        )

    def _admin_logout(self) -> None:
        token = self._admin_token()
        session = self._reminder_server.revoke_admin_session(token)
        if session is None:
            self._audit("admin_logout", "no_session", level=logging.WARNING)
        else:
            self._audit("admin_logout", "success", username=session.username)
        self._send_json(
            HTTPStatus.OK,
            {"authenticated": False},
            extra_headers={"Set-Cookie": self._admin_cookie("", 0)},
        )

    def _admin_token(self) -> str | None:
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
        except CookieError:
            return None
        morsel = cookie.get(ADMIN_COOKIE_NAME)
        return morsel.value if morsel is not None else None

    def _admin_session(self) -> AdminSession | None:
        return self._reminder_server.admin_session(self._admin_token())

    def _require_admin(self, action: str) -> AdminSession | None:
        session = self._admin_session()
        if session is not None:
            return session
        self._audit(action, "unauthorized", level=logging.WARNING)
        self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "请先登录管理员账号")
        return None

    def _admin_cookie(self, token: str, max_age: int) -> str:
        base_path = self._application_base_path()
        cookie_path = f"{base_path}/" if base_path else "/"
        cookie = (
            f"{ADMIN_COOKIE_NAME}={token}; Path={cookie_path}; Max-Age={max_age}; "
            "HttpOnly; SameSite=Strict"
        )
        if self.headers.get("X-Forwarded-Proto", "").casefold() == "https":
            cookie += "; Secure"
        return cookie

    def _application_base_path(self) -> str:
        forwarded_prefix = self.headers.get("X-Forwarded-Prefix", "").strip()
        if not forwarded_prefix or forwarded_prefix == "/":
            return ""
        if FORWARDED_PREFIX_PATTERN.fullmatch(forwarded_prefix) is None:
            LOGGER.warning(
                "ignored invalid forwarded prefix client=%s",
                self.address_string(),
            )
            return ""
        return forwarded_prefix

    def _add_configured_recipients(
        self,
        snapshot: dict[str, object],
        managed_emails: set[str],
    ) -> None:
        configured_recipients = []
        for recipient in self._settings.config.recipients:
            configured_recipients.append(
                {
                    "email": recipient.email,
                    "name": recipient.name,
                    "latitude": recipient.latitude,
                    "longitude": recipient.longitude,
                    "max_distance_km": recipient.max_distance_km,
                    "events": (
                        sorted(recipient.event_ids) if recipient.event_ids is not None else None
                    ),
                    "countries": (
                        sorted(recipient.country_names)
                        if recipient.country_names is not None
                        else None
                    ),
                    "continents": (
                        sorted(recipient.continent_names)
                        if recipient.continent_names is not None
                        else None
                    ),
                    "effective": recipient.email not in managed_emails,
                }
            )
        snapshot["configured_recipients"] = configured_recipients

        counts = snapshot.get("counts")
        subscriber_counts = counts.get("subscribers") if isinstance(counts, dict) else None
        if isinstance(subscriber_counts, dict):
            configured_effective = sum(
                bool(recipient["effective"]) for recipient in configured_recipients
            )
            subscriber_counts["configured"] = len(configured_recipients)
            subscriber_counts["effective"] = (
                int(subscriber_counts.get("active", 0)) + configured_effective
            )

    @staticmethod
    def _payload_email(payload: object) -> str | None:
        if not isinstance(payload, dict) or not isinstance(payload.get("email"), str):
            return None
        email = payload["email"].strip().lower()
        return email[:320] or None

    @staticmethod
    def _subscription_audit_details(subscription: SubscriptionView) -> dict[str, object]:
        return {
            "name": subscription.name,
            "latitude": subscription.latitude,
            "longitude": subscription.longitude,
            "max_distance_km": subscription.max_distance_km,
            "events": list(subscription.events) if subscription.events is not None else None,
            "countries": (
                list(subscription.countries) if subscription.countries is not None else None
            ),
            "continents": (
                list(subscription.continents) if subscription.continents is not None else None
            ),
            "active": subscription.active,
            "updated_at": subscription.updated_at.isoformat(),
            "cancelled_at": (
                subscription.cancelled_at.isoformat()
                if subscription.cancelled_at is not None
                else None
            ),
        }

    @classmethod
    def _audit_detail_value(cls, value: object, *, depth: int = 0) -> object:
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            return value[:500]
        if depth >= 3:
            return str(value)[:500]
        if isinstance(value, dict):
            return {
                str(key)[:80]: cls._audit_detail_value(item, depth=depth + 1)
                for key, item in list(value.items())[:40]
            }
        if isinstance(value, list | tuple | set | frozenset):
            return [
                cls._audit_detail_value(item, depth=depth + 1)
                for item in list(value)[:50]
            ]
        return str(value)[:500]

    def _audit(
        self,
        action: str,
        outcome: str,
        *,
        level: int = logging.INFO,
        **details: object,
    ) -> None:
        suffix = "".join(
            f" {key}={self._safe_log_value(mask_email(str(value)) if key == 'email' else value)}"
            for key, value in details.items()
            if value is not None
        )
        LOGGER.log(
            level,
            "audit action=%s outcome=%s client=%s%s",
            self._safe_log_value(action),
            self._safe_log_value(outcome),
            self._safe_log_value(self.client_address[0]),
            suffix,
        )
        email_value = details.get("email")
        email = str(email_value).strip()[:320] if email_value is not None else None
        persisted_details = {
            str(key)[:80]: self._audit_detail_value(value)
            for key, value in details.items()
            if key != "email" and value is not None
        }
        user_agent = self.headers.get("User-Agent", "").strip()[:512] or None
        try:
            with StateStore(self._settings.config.state_path) as state:
                state.record_activity_log(
                    created_at=self._reminder_server._clock(),
                    actor_type="admin" if action.startswith("admin_") else "user",
                    action=action,
                    outcome=outcome,
                    email=email or None,
                    client_ip=self.client_address[0],
                    method=self.command,
                    path=urlsplit(self.path).path,
                    user_agent=user_agent,
                    details=persisted_details,
                )
        except Exception:
            LOGGER.exception(
                "activity audit persistence failed action=%s",
                self._safe_log_value(action),
            )

    @staticmethod
    def _safe_log_value(value: object) -> str:
        text = str(value)[:160]
        return "".join(
            character if character.isalnum() or character in "@._:+/*-" else "_"
            for character in text
        )

    def _read_json(self) -> object:
        length_value = self.headers.get("Content-Length")
        try:
            length = int(length_value or "0")
        except ValueError as exc:
            raise SubscriptionValidationError("请求体长度无效") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise SubscriptionValidationError("请求体大小无效")
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SubscriptionValidationError("请求体必须是有效的 JSON") from exc

    def _send_static(self, filename: str) -> None:
        path = (self._settings.static_dir / filename).resolve()
        root = self._settings.static_dir.resolve()
        if root not in path.parents and path != root:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "资源不存在")
            return
        try:
            body = path.read_bytes()
        except OSError:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "资源不存在")
            return
        csp_nonce: str | None = None
        if path.suffix.casefold() == ".html":
            if path.name == "index.html" and (
                self._settings.config.google_maps_api_key or self._settings.config.amap_api_key
            ):
                csp_nonce = secrets.token_urlsafe(18)
            body = body.replace(
                APPLICATION_BASE_PATH_PLACEHOLDER.encode("ascii"),
                self._application_base_path().encode("ascii"),
            )
            body = body.replace(
                GOOGLE_MAPS_API_KEY_PLACEHOLDER.encode("ascii"),
                escape(self._settings.config.google_maps_api_key or "", quote=True).encode("utf-8"),
            )
            body = body.replace(
                AMAP_API_KEY_PLACEHOLDER.encode("ascii"),
                escape(self._settings.config.amap_api_key or "", quote=True).encode("utf-8"),
            )
            body = body.replace(
                AMAP_SECURITY_JS_CODE_PLACEHOLDER.encode("ascii"),
                escape(self._settings.config.amap_security_js_code or "", quote=True).encode(
                    "utf-8"
                ),
            )
            body = body.replace(
                AMAP_SERVICE_HOST_PLACEHOLDER.encode("ascii"),
                escape(self._settings.config.amap_service_host or "", quote=True).encode("utf-8"),
            )
            body = body.replace(
                CSP_NONCE_PLACEHOLDER.encode("ascii"),
                (csp_nonce or "").encode("ascii"),
            )
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._send_common_headers(csp_nonce=csp_nonce)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send_json(status, {"error": code, "message": message})

    def _send_common_headers(self, *, csp_nonce: str | None = None) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Referrer-Policy",
            "strict-origin-when-cross-origin" if csp_nonce else "same-origin",
        )
        if csp_nonce:
            style_sources = ["'self'", f"'nonce-{csp_nonce}'"]
            connect_sources = ["'self'"]
            image_sources = ["'self'"]
            frame_sources: list[str] = []
            font_sources = ["'self'"]
            if self._settings.config.google_maps_api_key:
                style_sources.append("https://fonts.googleapis.com")
                connect_sources.extend(
                    [
                        "https://*.googleapis.com",
                        "https://*.google.com",
                        "https://*.gstatic.com",
                    ]
                )
                image_sources.extend(
                    [
                        "https://*.googleapis.com",
                        "https://*.gstatic.com",
                        "https://*.google.com",
                        "https://*.googleusercontent.com",
                    ]
                )
                frame_sources.append("https://*.google.com")
                font_sources.append("https://fonts.gstatic.com")
            if self._settings.config.amap_api_key:
                amap_sources = ["https://*.amap.com", "https://*.autonavi.com"]
                style_sources.extend(amap_sources)
                connect_sources.extend(amap_sources)
                image_sources.extend(amap_sources)
                font_sources.extend(amap_sources)
            style_element_sources = [
                source for source in style_sources if not source.startswith("'nonce-")
            ]
            style_element_sources.append("'unsafe-inline'")
            connect_sources.extend(["data:", "blob:"])
            image_sources.extend(["data:", "blob:"])
            content_security_policy = (
                "default-src 'self'; "
                f"script-src 'nonce-{csp_nonce}' 'strict-dynamic' https: 'unsafe-eval' blob:; "
                f"style-src {' '.join(style_sources)}; "
                f"style-src-elem {' '.join(style_element_sources)}; "
                "style-src-attr 'unsafe-inline'; "
                f"connect-src {' '.join(connect_sources)}; "
                f"img-src {' '.join(image_sources)}; "
                f"frame-src {' '.join(frame_sources) or "'none'"}; "
                f"font-src {' '.join(font_sources)}; "
                "worker-src blob:; base-uri 'none'; form-action 'self'"
            )
        else:
            content_security_policy = (
                "default-src 'self'; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'"
            )
        self.send_header(
            "Content-Security-Policy",
            content_security_policy,
        )

    def log_message(self, format: str, *args: object) -> None:
        del format
        status = args[1] if len(args) > 1 else "-"
        LOGGER.info(
            "http client=%s method=%s path=%s status=%s",
            self.address_string(),
            self.command,
            urlsplit(self.path).path,
            status,
        )


def create_server(
    config: AppConfig,
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    static_dir: Path | None = None,
    smtp_password: str | None = None,
    verification_sender: VerificationSender | None = None,
    clock: Clock = utc_now,
    verification_code_factory: CodeFactory | None = None,
) -> ReminderHttpServer:
    if not 0 <= port <= 65535:
        raise ValueError("web port must be between 0 and 65535")
    root = static_dir or Path(__file__).with_name("web_assets")
    sender = verification_sender
    if sender is None:

        def smtp_sender(email: str, code: str, created_at: datetime) -> None:
            with SmtpMailer(config.smtp, smtp_password) as mailer:
                mailer.send_verification_code(email, code, created_at)

        sender = smtp_sender

    return ReminderHttpServer(
        (host, port),
        WebSettings(config=config, static_dir=root),
        verification_sender=sender,
        clock=clock,
        code_factory=verification_code_factory,
    )


def serve_web(
    config: AppConfig,
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    static_dir: Path | None = None,
    smtp_password: str | None = None,
) -> None:
    server = create_server(
        config,
        host,
        port,
        static_dir=static_dir,
        smtp_password=smtp_password,
    )
    LOGGER.info("web subscription service listening on http://%s:%d", host, server.server_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("web subscription service stopped")
    finally:
        server.server_close()
