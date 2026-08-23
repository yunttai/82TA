from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import check_password
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from journeys.abuse import reset_rate_limits
from journeys.models import AccountAuditEvent, AuthenticatedSession, ConsentRecord, ServiceUser


class EmailAuthApiTests(TestCase):
    def setUp(self) -> None:
        reset_rate_limits()
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/api/v1/health")

    def post(self, path: str, payload: dict):
        token = self.client.cookies["csrftoken"].value
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

    def registration(self, email: str, password: str = "correct-horse-battery-staple") -> dict:
        return {
            "email": email,
            "password": password,
            "nickname": "팔이타",
            "documentVersion": "local-development",
            "requiredPrivacyAccepted": True,
            "optionalConsents": {
                "SEARCH_HISTORY": True,
                "PRECISE_LOCATION": False,
                "PRODUCT_ANALYTICS": False,
                "ROUTING_FEEDBACK": True,
            },
        }

    def test_register_hashes_password_and_starts_user_session(self) -> None:
        csrf_before = self.client.cookies["csrftoken"].value
        response = self.post(
            "/api/v1/auth/register",
            self.registration("New.User@Example.com"),
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(self.client.cookies["csrftoken"].value, csrf_before)
        self.assertEqual(response.json()["subjectType"], "USER")
        self.assertEqual(response.json()["email"], "new.user@example.com")
        self.assertEqual(response.json()["nickname"], "팔이타")
        user = ServiceUser.objects.get(email="new.user@example.com")
        self.assertEqual(user.profile.nickname, "팔이타")
        self.assertEqual(ConsentRecord.objects.filter(user=user).count(), 5)
        self.assertTrue(ConsentRecord.objects.get(user=user, consent_type="SERVICE_PRIVACY").accepted)
        self.assertNotEqual(user.password_hash, "correct-horse-battery-staple")
        self.assertTrue(check_password("correct-horse-battery-staple", user.password_hash))
        self.assertEqual(AuthenticatedSession.objects.filter(user=user, revoked_at__isnull=True).count(), 1)
        self.assertTrue(AccountAuditEvent.objects.filter(user=user, event_type="ACCOUNT_REGISTERED").exists())
        self.assertEqual(self.client.get("/api/v1/route-searches").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/me/favorite-journeys").status_code, 200)
        self.assertEqual(
            self.client.delete(
                "/api/v1/session",
                HTTP_X_CSRFTOKEN=csrf_before,
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/api/v1/session").status_code, 200)
        self.assertEqual(
            self.client.delete(
                "/api/v1/session",
                HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
            ).status_code,
            204,
        )

    def test_login_failure_is_generic_and_logout_revokes_session(self) -> None:
        self.post(
            "/api/v1/auth/register",
            self.registration("owner@example.com"),
        )
        self.client.delete(
            "/api/v1/session",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )

        wrong = self.post(
            "/api/v1/auth/login",
            {"email": "missing@example.com", "password": "this-is-the-wrong-password"},
        )
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json()["code"], "INVALID_CREDENTIALS")
        self.assertNotIn("missing@example.com", wrong.content.decode())

        csrf_before_login = self.client.cookies["csrftoken"].value
        logged_in = self.post(
            "/api/v1/auth/login",
            {"email": "owner@example.com", "password": "correct-horse-battery-staple"},
        )
        self.assertEqual(logged_in.status_code, 200)
        self.assertNotEqual(self.client.cookies["csrftoken"].value, csrf_before_login)
        session_id = self.client.session["service_authenticated_session_id"]
        self.assertEqual(
            self.client.delete(
                "/api/v1/session",
                HTTP_X_CSRFTOKEN=csrf_before_login,
            ).status_code,
            403,
        )
        logged_out = self.client.delete(
            "/api/v1/session",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )
        self.assertEqual(logged_out.status_code, 204)
        self.assertIsNotNone(AuthenticatedSession.objects.get(id=session_id).revoked_at)
        self.assertEqual(self.client.get("/api/v1/session").status_code, 401)

    def test_duplicate_registration_and_short_password_are_rejected(self) -> None:
        payload = self.registration("same@example.com")
        self.assertEqual(self.post("/api/v1/auth/register", payload).status_code, 201)
        self.assertEqual(self.post("/api/v1/auth/register", payload).status_code, 409)
        short = self.post(
            "/api/v1/auth/register",
            self.registration("short@example.com", "too-short"),
        )
        self.assertEqual(short.status_code, 400)

    def test_registration_requires_privacy_acceptance_and_valid_nickname(self) -> None:
        missing = self.registration("missing-consent@example.com")
        missing["requiredPrivacyAccepted"] = False
        self.assertEqual(self.post("/api/v1/auth/register", missing).status_code, 400)
        nickname = self.registration("nickname@example.com")
        nickname["nickname"] = " "
        self.assertEqual(self.post("/api/v1/auth/register", nickname).status_code, 400)
        invisible = self.registration("invisible-nickname@example.com")
        invisible["nickname"] = "팔\u200b이타"
        self.assertEqual(self.post("/api/v1/auth/register", invisible).status_code, 400)

    def test_revoked_or_expired_authenticated_session_is_rejected(self) -> None:
        self.post(
            "/api/v1/auth/register",
            self.registration("revoked-session@example.com"),
        )
        session_id = self.client.session["service_authenticated_session_id"]
        AuthenticatedSession.objects.filter(id=session_id).update(revoked_at=timezone.now())
        self.assertEqual(self.client.get("/api/v1/session").status_code, 401)

        self.post(
            "/api/v1/auth/login",
            {
                "email": "revoked-session@example.com",
                "password": "correct-horse-battery-staple",
            },
        )
        session_id = self.client.session["service_authenticated_session_id"]
        AuthenticatedSession.objects.filter(id=session_id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.client.get("/api/v1/session").status_code, 401)

        self.post(
            "/api/v1/auth/login",
            {
                "email": "revoked-session@example.com",
                "password": "correct-horse-battery-staple",
            },
        )
        session_id = self.client.session["service_authenticated_session_id"]
        AuthenticatedSession.objects.filter(id=session_id).update(token_hash="0" * 64)
        self.assertEqual(self.client.get("/api/v1/session").status_code, 401)

    def test_registration_rolls_back_when_consent_recording_fails(self) -> None:
        with patch(
            "journeys.account_views.ConsentRepository.record",
            side_effect=[object(), RuntimeError("consent storage failed")],
        ):
            with self.assertRaises(RuntimeError):
                self.post(
                    "/api/v1/auth/register",
                    self.registration("rollback@example.com"),
                )
        self.assertFalse(ServiceUser.objects.filter(email="rollback@example.com").exists())

    @override_settings(DEBUG=False)
    def test_unexpected_registration_error_does_not_render_password(self) -> None:
        client = Client(enforce_csrf_checks=True, raise_request_exception=False)
        client.get("/api/v1/health")
        password = "never-render-this-password"
        payload = self.registration("traceback@example.com", password)
        with patch(
            "journeys.account_views.IdentityRepository.create_user",
            side_effect=RuntimeError("forced account failure"),
        ):
            response = client.post(
                "/api/v1/auth/register",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(password, response.content.decode(errors="replace"))

    @override_settings(AUTH_RATE_LIMIT_PER_MINUTE=1)
    def test_login_attempts_are_rate_limited(self) -> None:
        payload = {"email": "missing@example.com", "password": "this-is-the-wrong-password"}
        self.assertEqual(self.post("/api/v1/auth/login", payload).status_code, 401)
        limited = self.post("/api/v1/auth/login", payload)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["code"], "RATE_LIMITED")
