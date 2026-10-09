"""Warcon's required reads, exercised through FastAPI without network or extra dependencies."""

import asyncio
import json
import unittest

from src.main import app, mock_state, reserved_slots_state


class WarconReadsTest(unittest.TestCase):
    def request(self, path, authorization="Bearer test"):
        messages = []
        headers = [] if authorization is None else [(b"authorization", authorization.encode())]
        scope = {
            "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers,
            "client": ("127.0.0.1", 10000), "server": ("mock", 7776),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        asyncio.run(app(scope, receive, send))
        status = next(message["status"] for message in messages if message["type"] == "http.response.start")
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return status, json.loads(body)

    def test_new_routes_require_existing_bearer_authentication(self):
        for path in [
            "/v1/catalog/maps", "/v1/catalog/lightings", "/v1/catalog/experiences",
            "/v1/capabilities", "/v1/health", "/v1/rotation", "/v1/sponsor", "/v1/config",
        ]:
            for authorization in [None, "Bearer incorrect"]:
                with self.subTest(path=path, authorization=authorization):
                    self.assertEqual(self.request(path, authorization)[0], 401)

    def test_catalogs_cover_the_live_status_values(self):
        status_code, status = self.request("/v1/status")
        self.assertEqual(status_code, 200)
        for key in ["maps", "lightings", "experiences"]:
            with self.subTest(catalog=key):
                code, catalog = self.request(f"/v1/catalog/{key}")
                self.assertEqual(code, 200)
                ids = {entry["id"] for entry in catalog[key]}
                self.assertTrue(all(entry["displayName"] for entry in catalog[key]))
                if key == "maps":
                    self.assertEqual(ids, set(mock_state["maps"]))
                    self.assertIn(status["map"], ids)
                elif key == "lightings":
                    self.assertIn(status["lighting"], ids)
                else:
                    self.assertTrue(set(status["experiences"]).issubset(ids))

    def test_capabilities_list_only_implemented_game_routes(self):
        code, capabilities = self.request("/v1/capabilities")
        self.assertEqual(code, 200)
        actual = {
            f"{method} {route.path}"
            for route in app.routes
            if route.path.startswith("/v1/") and not route.path.startswith("/v1/mock/")
            for method in route.methods
            if method not in {"HEAD", "OPTIONS"}
        }
        self.assertEqual(set(capabilities["routes"]), actual)
        self.assertIn("POST /v1/reserved-slots", actual)
        self.assertNotIn("POST /v1/rotation/entries", actual)
        self.assertNotIn("GET /v1/server-id", actual)
        self.assertFalse(capabilities["config"]["writable"])

    def test_health_reports_nonnegative_uptime(self):
        code, health = self.request("/v1/health")
        self.assertEqual(code, 200)
        self.assertEqual(health["status"], "ok")
        self.assertIsInstance(health["uptimeSeconds"], int)
        self.assertGreaterEqual(health["uptimeSeconds"], 0)

    def test_rotation_matches_status_and_advances_with_it(self):
        original = mock_state.copy()
        try:
            for current in range(len(mock_state["maps"])):
                with self.subTest(current=current):
                    mock_state["rotation"] = current
                    mock_state["score"] = 90
                    _, status = self.request("/v1/status")
                    code, rotation = self.request("/v1/rotation")
                    self.assertEqual(code, 200)
                    now = next(entry for entry in rotation["entries"] if entry["status"] == "now")
                    following = next(entry for entry in rotation["entries"] if entry["status"] == "next")
                    self.assertEqual(now["map"], status["map"])
                    self.assertEqual(now["index"], status["rotation"]["nowIndex"])
                    self.assertEqual(following["index"], status["rotation"]["nextIndex"])
                    self.assertEqual(now["experiences"], status["experiences"])
                    self.assertEqual(now["lighting"], status["lighting"])
        finally:
            mock_state.update(original)

    def test_config_is_a_read_only_document_that_reflects_native_slot_changes(self):
        original = reserved_slots_state[:]
        try:
            code, first = self.request("/v1/config")
            self.assertEqual(code, 200)
            self.assertFalse(first["writable"])
            self.assertEqual(first["sections"], [])
            self.assertEqual(first["warnings"], [])
            self.assertIn("[/Script/WDGame.WDGameSession]", first["text"])
            self.assertIn("!DefaultReservedPlayerIds=ClearArray", first["text"])
            for steam_id in original:
                self.assertIn(f".DefaultReservedPlayerIds={steam_id}\n", first["text"])
            reserved_slots_state.append("76561198000999999")
            _, updated = self.request("/v1/config")
            self.assertIn(".DefaultReservedPlayerIds=76561198000999999\n", updated["text"])
            self.assertNotEqual(first["revision"], updated["revision"])
            self.assertEqual(self.request("/v1/reserved-slots")[1]["reservedSlots"], reserved_slots_state)
        finally:
            reserved_slots_state[:] = original

    def test_sponsor_supports_a_server_without_banner(self):
        self.assertEqual(self.request("/v1/sponsor"), (200, {"imageUrl": ""}))


if __name__ == "__main__":
    unittest.main()
