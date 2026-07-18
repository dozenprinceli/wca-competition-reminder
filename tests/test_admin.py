import json
import logging
import re
from dataclasses import replace
from datetime import timedelta
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path
from threading import Thread

from tests.conftest import MutableClock, make_config
from wca_competition_reminder import web
from wca_competition_reminder.config import AdminConfig, RecipientConfig
from wca_competition_reminder.state import StateStore


def request_json(
    connection: HTTPConnection,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[HTTPResponse, dict[str, object]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        request_headers.update(
            {"Content-Type": "application/json", "Content-Length": str(len(body))}
        )
    connection.request(method, path, body=body, headers=request_headers)
    response = connection.getresponse()
    response_body = json.loads(response.read().decode("utf-8"))
    return response, response_body


def start_admin_server(tmp_path: Path):
    config = replace(
        make_config(tmp_path),
        admins=(AdminConfig(username="operator", password="admin-secret"),),
    )
    clock = MutableClock()
    server = web.create_server(
        config,
        port=0,
        verification_sender=lambda *_args: None,
        clock=clock,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, clock


def test_admin_page_authentication_snapshot_and_logout(
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger=web.__name__)
    server, thread, clock = start_admin_server(tmp_path)
    with StateStore(server.settings.config.state_path) as state:
        state.register_subscriber(
            RecipientConfig("one@example.com", None, None, "Web override"),
            clock.current,
        )
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/admin")
        page_response = connection.getresponse()
        page = page_response.read().decode("utf-8")
        assert page_response.status == 200
        assert "管理员验证" in page
        assert 'name="application-base-path" content=""' in page
        assert 'href="/admin.css"' in page
        assert 'src="/admin.js"' in page
        assert 'data-view="activity"' in page
        assert 'id="activity-rows"' in page

        response, body = request_json(connection, "GET", "/api/admin/snapshot")
        assert response.status == 401
        assert body["error"] == "unauthorized"

        response, body = request_json(connection, "GET", "/api/admin/activity-logs")
        assert response.status == 401
        assert body["error"] == "unauthorized"

        response, body = request_json(
            connection,
            "POST",
            "/api/admin/login",
            {"username": "operator", "password": "wrong-secret"},
        )
        assert response.status == 401
        assert body["error"] == "invalid_credentials"

        response, body = request_json(
            connection,
            "POST",
            "/api/admin/login",
            {"username": "operator", "password": "admin-secret"},
        )
        assert response.status == 200
        assert body["username"] == "operator"
        cookie_header = response.getheader("Set-Cookie")
        assert cookie_header is not None
        assert "HttpOnly" in cookie_header
        assert "SameSite=Strict" in cookie_header
        assert "Path=/;" in cookie_header
        cookie = cookie_header.split(";", 1)[0]

        response, body = request_json(
            connection,
            "GET",
            "/api/admin/snapshot",
            headers={"Cookie": cookie},
        )
        assert response.status == 200
        assert body["admin"] == {"username": "operator"}
        assert body["counts"]["subscribers"]["configured"] == 2
        assert body["counts"]["subscribers"]["effective"] == 2
        assert len(body["configured_recipients"]) == 2
        assert body["configured_recipients"][0]["effective"] is False
        assert body["counts"]["activity_logs"]["retention_days"] == 7

        response, body = request_json(
            connection,
            "GET",
            "/api/admin/activity-logs?actor_type=admin&limit=2",
            headers={"Cookie": cookie},
        )
        assert response.status == 200
        assert body["retention_days"] == 7
        assert body["total"] >= 2
        assert len(body["items"]) == 2
        assert body["has_more"] is True
        assert any(
            item["action"] == "admin_snapshot_view" and item["outcome"] == "success"
            for item in body["items"]
        )
        assert all(item["actor_type"] == "admin" for item in body["items"])

        response, body = request_json(
            connection,
            "POST",
            "/api/admin/logout",
            {},
            headers={"Cookie": cookie},
        )
        assert response.status == 200
        assert body == {"authenticated": False}
        assert "Max-Age=0" in str(response.getheader("Set-Cookie"))

        response, _ = request_json(
            connection,
            "GET",
            "/api/admin/snapshot",
            headers={"Cookie": cookie},
        )
        assert response.status == 401

        assert "audit action=admin_login outcome=denied" in caplog.text
        assert "audit action=admin_login outcome=success" in caplog.text
        assert "audit action=admin_snapshot_view outcome=success" in caplog.text
        assert "audit action=admin_logout outcome=success" in caplog.text
        assert "admin-secret" not in caplog.text
        assert "wrong-secret" not in caplog.text
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_forwarded_prefix_scopes_pages_and_admin_cookie(tmp_path: Path) -> None:
    server, thread, _ = start_admin_server(tmp_path)
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    proxy_headers = {
        "X-Forwarded-Prefix": "/wca-competition-reminder",
        "X-Forwarded-Proto": "https",
    }
    try:
        connection.request("GET", "/", headers=proxy_headers)
        page_response = connection.getresponse()
        page = page_response.read().decode("utf-8")
        assert page_response.status == 200
        assert 'name="application-base-path" content="/wca-competition-reminder"' in page
        assert 'name="google-maps-api-key" content=""' in page
        assert 'name="amap-api-key" content=""' in page
        assert 'name="amap-security-js-code" content=""' in page
        assert 'name="amap-service-host" content=""' in page
        assert "__WCA_GOOGLE_MAPS_API_KEY__" not in page
        assert "__WCA_AMAP_API_KEY__" not in page
        assert "__WCA_AMAP_SECURITY_JS_CODE__" not in page
        assert "__WCA_AMAP_SERVICE_HOST__" not in page
        assert "__WCA_CSP_NONCE__" not in page
        assert page_response.getheader("Referrer-Policy") == "same-origin"
        content_security_policy = str(page_response.getheader("Content-Security-Policy"))
        assert "googleapis.com" not in content_security_policy
        assert "amap.com" not in content_security_policy
        assert "style-src-elem" not in content_security_policy
        assert 'href="/wca-competition-reminder/styles.css"' in page
        assert 'src="/wca-competition-reminder/app.js"' in page

        connection.request("GET", "/admin/", headers=proxy_headers)
        admin_response = connection.getresponse()
        admin_page = admin_response.read().decode("utf-8")
        assert admin_response.status == 200
        assert 'href="/wca-competition-reminder/admin.css"' in admin_page
        assert 'src="/wca-competition-reminder/admin.js"' in admin_page
        assert 'href="/wca-competition-reminder/"' in admin_page

        response, body = request_json(
            connection,
            "POST",
            "/api/admin/login",
            {"username": "operator", "password": "admin-secret"},
            headers=proxy_headers,
        )
        assert response.status == 200
        assert body["authenticated"] is True
        cookie_header = str(response.getheader("Set-Cookie"))
        assert "Path=/wca-competition-reminder/;" in cookie_header
        assert "Secure" in cookie_header
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_index_injects_escaped_google_maps_key_and_picker_markup(tmp_path: Path) -> None:
    config = replace(make_config(tmp_path), google_maps_api_key='maps-key&"<')
    server = web.create_server(config, port=0, verification_sender=lambda *_args: None)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        page = response.read().decode("utf-8")

        assert response.status == 200
        assert 'name="google-maps-api-key" content="maps-key&amp;&quot;&lt;"' in page
        assert 'name="amap-api-key" content=""' in page
        assert 'name="amap-service-host" content=""' in page
        assert 'id="location-picker-button"' in page
        assert 'id="location-dialog"' in page
        nonces = re.findall(r'nonce="([^"]+)"', page)
        assert len(nonces) == 3
        assert len(set(nonces)) == 1
        content_security_policy = str(response.getheader("Content-Security-Policy"))
        assert f"'nonce-{nonces[0]}'" in content_security_policy
        assert "'strict-dynamic'" in content_security_policy
        assert "style-src-elem 'self' https://fonts.googleapis.com 'unsafe-inline'" in (
            content_security_policy
        )
        assert "https://*.googleapis.com" in content_security_policy
        assert "amap.com" not in content_security_policy
        assert response.getheader("Referrer-Policy") == "strict-origin-when-cross-origin"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_index_injects_escaped_amap_credentials_and_csp_sources(tmp_path: Path) -> None:
    config = replace(
        make_config(tmp_path),
        amap_api_key='amap-key&"<',
        amap_security_js_code='security-code&"<',
    )
    server = web.create_server(config, port=0, verification_sender=lambda *_args: None)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        page = response.read().decode("utf-8")

        assert response.status == 200
        assert 'name="google-maps-api-key" content=""' in page
        assert 'name="amap-api-key" content="amap-key&amp;&quot;&lt;"' in page
        assert 'name="amap-security-js-code" content="security-code&amp;&quot;&lt;"' in page
        assert 'name="amap-service-host" content=""' in page
        nonces = re.findall(r'nonce="([^"]+)"', page)
        assert len(nonces) == 3
        assert len(set(nonces)) == 1
        content_security_policy = str(response.getheader("Content-Security-Policy"))
        assert f"'nonce-{nonces[0]}'" in content_security_policy
        assert "'strict-dynamic'" in content_security_policy
        assert (
            "style-src-elem 'self' https://*.amap.com https://*.autonavi.com 'unsafe-inline'"
            in content_security_policy
        )
        assert "https://*.amap.com" in content_security_policy
        assert "https://*.autonavi.com" in content_security_policy
        assert "googleapis.com" not in content_security_policy
        assert response.getheader("Referrer-Policy") == "strict-origin-when-cross-origin"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_index_injects_amap_service_host_without_security_code(tmp_path: Path) -> None:
    config = replace(
        make_config(tmp_path),
        amap_api_key="amap-key",
        amap_service_host="/_AMapService",
    )
    server = web.create_server(config, port=0, verification_sender=lambda *_args: None)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        page = response.read().decode("utf-8")

        assert response.status == 200
        assert 'name="amap-api-key" content="amap-key"' in page
        assert 'name="amap-security-js-code" content=""' in page
        assert 'name="amap-service-host" content="/_AMapService"' in page
        assert "https://*.amap.com" in str(response.getheader("Content-Security-Policy"))
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_invalid_forwarded_prefix_is_ignored(tmp_path: Path) -> None:
    server, thread, _ = start_admin_server(tmp_path)
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(
            "GET",
            "/admin",
            headers={"X-Forwarded-Prefix": "/invalid/"},
        )
        response = connection.getresponse()
        page = response.read().decode("utf-8")
        assert response.status == 200
        assert 'name="application-base-path" content=""' in page
        assert 'href="/admin.css"' in page
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_admin_login_is_disabled_without_configured_accounts(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    server = web.create_server(config, port=0, verification_sender=lambda *_args: None)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        response, body = request_json(
            connection,
            "POST",
            "/api/admin/login",
            {"username": "operator", "password": "admin-secret"},
        )
        assert response.status == 503
        assert body["error"] == "admin_not_configured"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_admin_login_is_rate_limited_after_five_failures(tmp_path: Path) -> None:
    server, thread, clock = start_admin_server(tmp_path)
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        for _ in range(web.ADMIN_LOGIN_ATTEMPTS):
            response, _ = request_json(
                connection,
                "POST",
                "/api/admin/login",
                {"username": "operator", "password": "wrong-secret"},
            )
            assert response.status == 401

        response, body = request_json(
            connection,
            "POST",
            "/api/admin/login",
            {"username": "operator", "password": "admin-secret"},
        )
        assert response.status == 429
        assert response.getheader("Retry-After") == str(web.ADMIN_LOGIN_WINDOW_SECONDS)
        assert body["retry_after_seconds"] == web.ADMIN_LOGIN_WINDOW_SECONDS

        clock.current += timedelta(seconds=web.ADMIN_LOGIN_WINDOW_SECONDS)
        response, body = request_json(
            connection,
            "POST",
            "/api/admin/login",
            {"username": "operator", "password": "admin-secret"},
        )
        assert response.status == 200
        assert body["authenticated"] is True
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
