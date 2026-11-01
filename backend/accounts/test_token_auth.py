# SPDX-License-Identifier: Apache-2.0
"""Bearer-token API authentication (quickpoll fork, accounts/token_auth.py)."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.token_auth import parse_tokens
from rooms.models import QuestionSet, Room

User = get_user_model()

WITH_TOKENS = {"API_TOKENS": {"secret-token": "lena", "ghost-token": "nobody"}}


def bearer(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class ParseTokensTests(TestCase):
    def test_pairs(self):
        self.assertEqual(parse_tokens(" a=alice, b = bob ,,broken, =x, y="), {"a": "alice", "b": "bob"})
        self.assertEqual(parse_tokens(""), {})


@override_settings(**WITH_TOKENS)
class ApiTokenAuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="lena")
        self.other = User.objects.create_user(username="tom")
        self.room = Room.objects.create(owner=self.user, title_en="Mine")
        self.room.owners.add(self.user)
        foreign = Room.objects.create(owner=self.other, title_en="Not mine")
        foreign.owners.add(self.other)

    def test_token_acts_as_its_user(self):
        response = self.client.get("/api/rooms/", **bearer("secret-token"))
        self.assertEqual(response.status_code, 200)
        titles = [r["title"]["en"] for r in response.json()["results"]]
        self.assertEqual(titles, ["Mine"])

    def test_unsafe_requests_need_no_csrf(self):
        client = self.client_class(enforce_csrf_checks=True)
        data = {"format": "abstimmbar-set-v2", "title": {"de": "Warm-up", "en": "Warm-up"}, "type": "live_poll",
                "questions": [{"kind": "word_cloud", "text": {"de": "Ein Wort?", "en": "One word?"}}]}
        response = client.post(f"/api/rooms/{self.room.pk}/import-set/", data,
                               content_type="application/json", **bearer("secret-token"))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(QuestionSet.objects.get(pk=response.json()["id"]).questions.count(), 1)

    def test_bad_or_orphan_tokens_are_rejected(self):
        # 403 like any unauthenticated request (SessionAuthentication comes first and sends no challenge).
        self.assertEqual(self.client.get("/api/rooms/", **bearer("wrong")).status_code, 403)
        self.assertEqual(self.client.get("/api/rooms/", **bearer("ghost-token")).status_code, 403)
        self.assertEqual(self.client.get("/api/rooms/").status_code, 403)

    @override_settings(API_TOKENS={})
    def test_off_without_tokens(self):
        self.assertEqual(self.client.get("/api/rooms/", **bearer("secret-token")).status_code, 403)
