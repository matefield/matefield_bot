"""Guild configuration and inline delivery are isolated, audited and network-free."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import socket
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import UniqueConstraint
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from src.connections.apis.warcon import WarconClient
from src.connections.databases.db import Membership, MembershipType, Player, PlayerRole, Role, RoleDiscordBinding
from src.main import app
from src.modules.v1.services.membership_roles_service import MembershipRolesService
from src.security.guard import verify_api_key_guard
from wardogs_config import ENVIRONMENT_SETTINGS
from wardogs_config.security import SecuritySettings
from wardogs_schemas.dtos import (
    AddMembershipRequest, MembershipWarconDelivery, MembershipRoleUnassignment,
)

GUILD_A = "111111111111111111"
GUILD_B = "222222222222222222"
ROLE_A = "333333333333333333"
ROLE_B = "444444444444444444"
ACTOR = "555555555555555555"
STEAM = "76561198000000001"


def url(guild_id=GUILD_A, code="regular"):
    return f"/api/v1/discord/guilds/{guild_id}/membership-types/{code}/role"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    security = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS
    monkeypatch.setattr(security, "DISCORD_GUILD_IDS", f" {GUILD_A}, {GUILD_B} ")
    monkeypatch.setattr(security, "DISCORD_GUILD_ID", None)
    def block_network(*args, **kwargs):
        raise AssertionError("Role binding tests must not contact Discord or Warcon")
    monkeypatch.setattr(socket.socket, "connect", block_network)


@pytest_asyncio.fixture
async def catalog(session):
    role = Role(code="VIP", name="VIP", role_type="VIP", discord_role_id="999999999999999999")
    player = Player(steam_id=STEAM, discord_id="666666666666666666")
    session.add_all([role, player])
    await session.flush()
    m_type = MembershipType(code="regular", name="VIP Normal", default_days=30, role_id=role.id)
    session.add(m_type)
    await session.commit()
    return role, m_type, player


@pytest.fixture
def game_delivery(monkeypatch):
    settings = ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS
    for key, value in {"WARCON_URL": "http://warcon.test", "WARCON_ORG_ID": "test-org",
                       "WARCON_SERVER_ID": "test-server", "WARCON_API_TOKEN": "test-only"}.items():
        monkeypatch.setattr(settings, key, value)
    mock = AsyncMock(return_value=MembershipWarconDelivery(status="SUCCESS", server_id="test-server", entry_id="test-entry"))
    monkeypatch.setattr(WarconClient, "upsert_reserved_slot", mock)
    return mock


def create_payload(guild_id=GUILD_A, **overrides):
    return {"steam_id": STEAM, "membership_type": "regular", "source": "DISCORD",
            "operation_id": "op-guild-one", "guild_id": guild_id, **overrides}


@pytest.mark.asyncio
async def test_put_and_get_are_audited_without_mutating_domain_role(client, session, catalog):
    role, m_type, _ = catalog
    response = await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    assert response.status_code == 200
    assert response.json() == {"guild_id": GUILD_A, "membership_type": "regular",
        "membership_type_name": "VIP Normal", "role_id": role.id,
        "discord_role_id": ROLE_A, "configured_by": ACTOR, "changed": True}
    assert (await client.get(url(code="REGULAR"))).json() == {**response.json(), "changed": False}
    binding = (await session.exec(select(RoleDiscordBinding))).one()
    assert binding.created_at is not None and binding.updated_at is not None
    assert m_type.role_id == role.id and role.discord_role_id == "999999999999999999"
    assert (await session.exec(select(Membership))).all() == []
    assert (await session.exec(select(PlayerRole))).all() == []


@pytest.mark.asyncio
async def test_repeat_keeps_original_audit_and_timestamp(client, session, catalog):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    binding = (await session.exec(select(RoleDiscordBinding))).one()
    timestamp = binding.updated_at
    repeated = await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": "777777777777777777"})
    assert repeated.json()["changed"] is False
    assert repeated.json()["configured_by"] == ACTOR
    assert binding.updated_at == timestamp
    assert len((await session.exec(select(RoleDiscordBinding))).all()) == 1


@pytest.mark.asyncio
async def test_two_guilds_have_independent_representations(client, session, catalog):
    first = await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    second = await client.put(url(GUILD_B), json={"discord_role_id": ROLE_B, "actor_id": ACTOR})
    assert first.status_code == second.status_code == 200
    assert (await client.get(url())).json()["discord_role_id"] == ROLE_A
    assert (await client.get(url(GUILD_B))).json()["discord_role_id"] == ROLE_B
    assert len((await session.exec(select(RoleDiscordBinding))).all()) == 2


@pytest.mark.asyncio
async def test_api_key_guard_applies_to_all_configuration_operations(client, catalog):
    saved_guard = app.dependency_overrides.pop(verify_api_key_guard)
    try:
        assert (await client.get(url())).status_code == 403
        assert (await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).status_code == 403
        assert (await client.request("DELETE", url(), json={"actor_id": ACTOR})).status_code == 403
    finally:
        app.dependency_overrides[verify_api_key_guard] = saved_guard


@pytest.mark.asyncio
@pytest.mark.parametrize("configured,fallback,expected", [(None, None, 403), ("", GUILD_A, 200), (None, GUILD_A, 200), (GUILD_B, GUILD_A, 403)])
async def test_allowlist_fails_closed_and_explicit_list_takes_precedence(client, catalog, monkeypatch, configured, fallback, expected):
    security = ENVIRONMENT_SETTINGS.SECURITY_SETTINGS
    monkeypatch.setattr(security, "DISCORD_GUILD_IDS", configured)
    monkeypatch.setattr(security, "DISCORD_GUILD_ID", fallback)
    assert (await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).status_code == expected


@pytest.mark.asyncio
async def test_unknown_guild_cannot_read_or_write(client, catalog):
    assert (await client.get(url("888888888888888888"))).status_code == 403
    assert (await client.put(url("888888888888888888"), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).status_code == 403
    assert (await client.request("DELETE", url("888888888888888888"), json={"actor_id": ACTOR})).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["0", "-1", "001", "abc", "١٢٣", "18446744073709551616", 123, None])
@pytest.mark.parametrize("field", ["discord_role_id", "actor_id"])
async def test_body_requires_valid_string_discord_ids(client, catalog, invalid, field):
    body = {"discord_role_id": ROLE_A, "actor_id": ACTOR, field: invalid}
    assert (await client.put(url(), json=body)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("guild_id", ["0", "-1", "001", "abc", "18446744073709551616"])
async def test_path_requires_valid_discord_guild_id(client, catalog, guild_id):
    assert (await client.put(url(guild_id), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).status_code == 422


@pytest.mark.asyncio
async def test_unknown_inactive_or_roleless_types_do_not_create_binding(client, session, catalog):
    assert (await client.put(url(code="unknown"), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).status_code == 404
    session.add(MembershipType(code="roleless", name="Roleless"))
    session.add(MembershipType(code="inactive", name="Inactive", is_active=False, role_id=catalog[0].id))
    await session.commit()
    assert (await client.put(url(code="roleless"), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).status_code == 400
    assert (await client.put(url(code="inactive"), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).status_code == 400
    assert (await session.exec(select(RoleDiscordBinding))).all() == []
    assert (await client.get(url())).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role_field", ["role_granted_id", "special_role_id", "legacy_type"])
async def test_replacing_a_role_with_active_memberships_is_rejected(client, session, catalog, role_field):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    membership = Membership(steam_id=STEAM, membership_type="regular", end_time=datetime.now(timezone.utc) + timedelta(days=3))
    if role_field != "legacy_type":
        setattr(membership, role_field, catalog[0].id)
    session.add(membership)
    await session.commit()
    rejected = await client.put(url(), json={"discord_role_id": ROLE_B, "actor_id": ACTOR})
    assert rejected.status_code == 409
    assert (await client.get(url())).json()["discord_role_id"] == ROLE_A
    assert (await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).json()["changed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("inactive,expiry", [(True, None), (False, -1)])
async def test_replacement_is_allowed_after_entitlement_ends(client, session, catalog, inactive, expiry):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    session.add(Membership(steam_id=STEAM, membership_type="regular", role_granted_id=catalog[0].id,
        is_active=not inactive, end_time=datetime.now(timezone.utc) + timedelta(days=expiry) if expiry else None))
    await session.commit()
    response = await client.put(url(), json={"discord_role_id": ROLE_B, "actor_id": ACTOR})
    assert response.status_code == 200 and response.json()["changed"] is True


@pytest.mark.asyncio
async def test_initial_legacy_guild_binding_cannot_silently_replace_active_role(client, session, catalog, monkeypatch):
    monkeypatch.setattr(ENVIRONMENT_SETTINGS.SECURITY_SETTINGS, "DISCORD_GUILD_ID", GUILD_A)
    session.add(Membership(steam_id=STEAM, membership_type="regular", role_granted_id=catalog[0].id))
    await session.commit()
    assert (await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})).status_code == 409
    response = await client.put(url(), json={"discord_role_id": catalog[0].discord_role_id, "actor_id": ACTOR})
    assert response.status_code == 200
    assert (await client.put(url(GUILD_B), json={"discord_role_id": ROLE_B, "actor_id": ACTOR})).status_code == 200


def test_binding_metadata_has_dependency_and_unique_guild_role():
    table = RoleDiscordBinding.__table__
    assert {tuple(column.name for column in constraint.columns) for constraint in table.constraints if isinstance(constraint, UniqueConstraint)} == {("guild_id", "role_id")}
    assert {foreign_key.target_fullname for foreign_key in table.foreign_keys} == {"roles.id"}


def test_allowlist_setting_is_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("DISCORD_GUILD_IDS", f"{GUILD_A},{GUILD_B}")
    assert SecuritySettings(_env_file=None).DISCORD_GUILD_IDS == f"{GUILD_A},{GUILD_B}"


@pytest.mark.asyncio
async def test_creation_without_binding_fails_before_membership_and_warcon(client, session, catalog, game_delivery):
    response = await client.post("/api/v1/db/players/membership", json=create_payload())
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "membership_role_configuration_missing"}
    assert (await session.exec(select(Membership))).all() == []
    assert (await session.exec(select(PlayerRole))).all() == []
    game_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_creation_returns_target_guild_role_and_cross_guild_replay_is_rejected(client, session, catalog, game_delivery):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    await client.put(url(GUILD_B), json={"discord_role_id": ROLE_B, "actor_id": ACTOR})
    first = await client.post("/api/v1/db/players/membership", json=create_payload())
    assert first.status_code == 200
    assert first.json()["discord"] == {"guild_id": GUILD_A, "user_id": catalog[2].discord_id, "role_ids": [ROLE_A]}
    repeated = await client.post("/api/v1/db/players/membership", json=create_payload())
    assert repeated.status_code == 200 and repeated.json()["replayed"] is True
    other = await client.post("/api/v1/db/players/membership", json=create_payload(GUILD_B))
    assert other.status_code == 409
    assert len((await session.exec(select(Membership))).all()) == 1
    assert game_delivery.await_count == 2


@pytest.mark.asyncio
async def test_creation_requires_enabled_guild(client, session, catalog, game_delivery):
    response = await client.post("/api/v1/db/players/membership", json=create_payload("888888888888888888"))
    assert response.status_code == 403
    assert (await session.exec(select(Membership))).all() == []
    game_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_special_role_selection_is_resolved_only_in_current_guild(client, session, catalog, game_delivery):
    special = Role(code="FOUNDER", name="Founder", role_type="SPECIAL", discord_role_id="777777777777777777")
    session.add(special)
    await session.flush()
    session.add_all([RoleDiscordBinding(guild_id=GUILD_A, role_id=special.id, discord_role_id="888888888888888888", configured_by=ACTOR),
                     RoleDiscordBinding(guild_id=GUILD_B, role_id=special.id, discord_role_id="777777777777777777", configured_by=ACTOR)])
    await session.commit()
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    wrong = await client.post("/api/v1/db/players/membership", json=create_payload(special_role="777777777777777777"))
    assert wrong.status_code == 409
    assert (await session.exec(select(Membership))).all() == []
    game_delivery.assert_not_awaited()
    good = await client.post("/api/v1/db/players/membership", json=create_payload(special_role="888888888888888888"))
    assert good.status_code == 200
    assert good.json()["discord"]["role_ids"] == [ROLE_A, "888888888888888888"]
    assert (await session.exec(select(Membership))).one().special_role_id == special.id
    assert len((await session.exec(select(Role))).all()) == 2


@pytest.mark.asyncio
async def test_renewal_preserves_existing_membership_if_inherited_special_role_has_no_binding(client, session, catalog, game_delivery):
    special = Role(code="STAFF", name="Staff", role_type="SPECIAL")
    session.add(special)
    await session.flush()
    old = Membership(steam_id=STEAM, membership_type="regular", role_granted_id=catalog[0].id,
                     special_role_id=special.id, end_time=datetime.now(timezone.utc) + timedelta(days=2))
    session.add(old)
    await session.commit()
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    response = await client.post("/api/v1/db/players/membership", json=create_payload())
    assert response.status_code == 409
    await session.refresh(old)
    assert old.is_active is True
    assert len((await session.exec(select(Membership))).all()) == 1
    game_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_replay_keeps_the_hash_and_response_from_before_guild_support(client, session, catalog, game_delivery):
    payload = create_payload()
    payload.pop("guild_id")
    req = AddMembershipRequest(**payload)
    historical_hash = hashlib.sha256(json.dumps(req.model_dump(exclude={"operation_id", "guild_id", "actor_id"}), sort_keys=True).encode()).hexdigest()
    existing = Membership(steam_id=STEAM, membership_type="regular", role_granted_id=catalog[0].id,
        creation_operation_id=payload["operation_id"], creation_request_hash=historical_hash,
        end_time=datetime.now(timezone.utc) + timedelta(days=30))
    session.add(existing)
    await session.commit()
    response = await client.post("/api/v1/db/players/membership", json=payload)
    assert response.status_code == 200 and response.json()["replayed"] is True
    assert response.json()["discord"] == {"user_id": catalog[2].discord_id, "role_ids": [catalog[0].discord_role_id]}
    assert len((await session.exec(select(Membership))).all()) == 1
    game_delivery.assert_awaited_once()


@pytest.mark.asyncio
async def test_role_resolution_refreshes_binding_loaded_before_another_configuration(session, test_engine, catalog):
    binding = RoleDiscordBinding(role_id=catalog[0].id, guild_id=GUILD_A,
                                 discord_role_id=ROLE_A, configured_by=ACTOR)
    session.add(binding)
    await session.commit()
    async with AsyncSession(test_engine, expire_on_commit=False) as other:
        saved = await other.get(RoleDiscordBinding, binding.id)
        saved.discord_role_id = ROLE_B
        other.add(saved)
        await other.commit()
    # The initial object is deliberately kept alive in this session's identity map.
    assert binding.discord_role_id == ROLE_A
    resolved = await MembershipRolesService.resolve_roles(GUILD_A, [catalog[0].id], session)
    assert resolved == [ROLE_B]
    assert binding.discord_role_id == ROLE_B


@pytest.mark.asyncio
async def test_list_requires_enabled_guild_without_changing_legacy_access(client, session, catalog):
    session.add(Membership(steam_id=STEAM, membership_type="regular"))
    await session.commit()
    assert (await client.get("/api/v1/db/memberships?guild_id=888888888888888888")).status_code == 403
    assert (await client.get(f"/api/v1/db/memberships?guild_id={GUILD_A}")).json()["total"] == 1
    assert (await client.get("/api/v1/db/memberships")).json()["total"] == 1


@pytest.mark.asyncio
async def test_list_role_mentions_use_the_requested_guild_without_global_fallback(client, session, catalog):
    role = catalog[0]
    special = Role(code="FOUNDER", name="Founder", role_type="SPECIAL", discord_role_id="777777777777777777")
    session.add(special)
    await session.flush()
    session.add_all([
        RoleDiscordBinding(guild_id=GUILD_A, role_id=role.id, discord_role_id=ROLE_A, configured_by=ACTOR),
        RoleDiscordBinding(guild_id=GUILD_B, role_id=role.id, discord_role_id=ROLE_B, configured_by=ACTOR),
        RoleDiscordBinding(guild_id=GUILD_A, role_id=special.id, discord_role_id="888888888888888888", configured_by=ACTOR),
        Membership(steam_id=STEAM, membership_type="regular", role_granted_id=role.id, special_role_id=special.id),
    ])
    await session.commit()
    first = (await client.get(f"/api/v1/db/memberships?guild_id={GUILD_A}")).json()["memberships"][0]
    second = (await client.get(f"/api/v1/db/memberships?guild_id={GUILD_B}")).json()["memberships"][0]
    legacy = (await client.get("/api/v1/db/memberships")).json()["memberships"][0]
    assert (first["role_granted_discord_id"], first["special_discord_role_id"]) == (ROLE_A, "888888888888888888")
    assert (second["role_granted_discord_id"], second["special_discord_role_id"]) == (ROLE_B, None)
    assert (legacy["role_granted_discord_id"], legacy["special_discord_role_id"]) == (role.discord_role_id, special.discord_role_id)


@pytest.mark.asyncio
async def test_list_pagination_is_stable_for_identical_membership_dates(client, session, catalog):
    timestamp = datetime.now(timezone.utc)
    rows = [Membership(steam_id=STEAM, membership_type="regular", start_time=timestamp) for _ in range(3)]
    session.add_all(rows)
    await session.commit()
    ids = []
    for page in range(1, 4):
        listing = (await client.get(f"/api/v1/db/memberships?guild_id={GUILD_A}&page={page}&limit=1")).json()
        ids.append(listing["memberships"][0]["id"])
    assert ids == sorted((row.id for row in rows), reverse=True)


@pytest.mark.asyncio
async def test_unassignment_is_guild_scoped_idempotent_and_audited(client, session, catalog, caplog, game_delivery):
    role, m_type, _ = catalog
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    await client.put(url(GUILD_B), json={"discord_role_id": ROLE_B, "actor_id": ACTOR})
    ended = Membership(steam_id=STEAM, membership_type="regular", is_active=False,
                       role_granted_id=role.id)
    player_role = PlayerRole(steam_id=STEAM, role_id=role.id)
    session.add_all([ended, player_role])
    await session.commit()

    with caplog.at_level(logging.INFO, logger="wardogs.memberships"):
        removed = await client.request("DELETE", url(code="%20rEgUlAr%20"), json={"actor_id": ACTOR})
        repeated = await client.request("DELETE", url(), json={"actor_id": ACTOR})

    expected = {"guild_id": GUILD_A, "membership_type": "regular", "membership_type_name": "VIP Normal",
                "role_id": role.id, "discord_role_id": ROLE_A, "actor_id": ACTOR, "changed": True}
    assert removed.status_code == repeated.status_code == 200
    assert removed.json() == expected
    assert repeated.json() == {**expected, "discord_role_id": None, "changed": False}
    assert (await client.get(url())).status_code == 404
    other = (await session.exec(select(RoleDiscordBinding))).one()
    assert (other.guild_id, other.discord_role_id) == (GUILD_B, ROLE_B)
    await session.refresh(role)
    await session.refresh(m_type)
    assert role.discord_role_id == "999999999999999999"
    assert m_type.role_id == role.id
    assert (await session.exec(select(Membership))).one().id == ended.id
    assert (await session.exec(select(PlayerRole))).one() == player_role
    audits = [record for record in caplog.records if record.getMessage().startswith("membership_role_unassignment ")]
    assert [(record.actor_id, record.guild_id, record.membership_type, record.role_id,
             record.previous_discord_role_id, record.changed) for record in audits] == [
        (ACTOR, GUILD_A, "regular", role.id, ROLE_A, True),
        (ACTOR, GUILD_A, "regular", role.id, None, False),
    ]
    assert f"actor_id={ACTOR}" in audits[0].getMessage()
    assert f"guild_id={GUILD_A}" in audits[0].getMessage()
    assert f"role_id={role.id}" in audits[0].getMessage()
    assert f"previous_discord_role_id={ROLE_A}" in audits[0].getMessage()
    assert "changed=True" in audits[0].getMessage()
    assert "previous_discord_role_id=None changed=False" in audits[1].getMessage()
    game_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_absent_binding_is_unchanged_even_when_role_is_shared_and_in_use(client, session, catalog):
    role = catalog[0]
    session.add_all([
        MembershipType(code="express", name="VIP Express", role_id=role.id, is_active=False),
        Membership(steam_id=STEAM, membership_type="regular", role_granted_id=role.id),
        RoleDiscordBinding(role_id=role.id, guild_id=GUILD_B, discord_role_id=ROLE_B, configured_by=ACTOR),
    ])
    await session.commit()
    response = await client.request("DELETE", url(), json={"actor_id": ACTOR})
    assert response.status_code == 200
    assert response.json()["changed"] is False
    assert response.json()["discord_role_id"] is None
    assert (await session.exec(select(RoleDiscordBinding))).one().guild_id == GUILD_B


@pytest.mark.asyncio
@pytest.mark.parametrize("role_field", ["role_granted_id", "special_role_id", "legacy_type"])
@pytest.mark.parametrize("permanent", [False, True])
async def test_unassignment_rejects_every_active_role_source(client, session, catalog, role_field, permanent):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    membership = Membership(steam_id=STEAM, membership_type="REGULAR",
                            end_time=None if permanent else datetime.now(timezone.utc) + timedelta(days=3))
    if role_field != "legacy_type":
        setattr(membership, role_field, catalog[0].id)
    session.add(membership)
    await session.commit()
    response = await client.request("DELETE", url(), json={"actor_id": ACTOR})
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "membership_role_in_use"}}
    assert (await session.exec(select(RoleDiscordBinding))).one().discord_role_id == ROLE_A
    await session.refresh(membership)
    assert membership.is_active is True


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["inactive", "expired", "future"])
async def test_unassignment_ignores_memberships_without_current_entitlement(client, session, catalog, state):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    now = datetime.now(timezone.utc)
    membership = Membership(steam_id=STEAM, membership_type="regular", role_granted_id=catalog[0].id,
                            is_active=state != "inactive", start_time=now + timedelta(days=1) if state == "future" else now,
                            end_time=now - timedelta(days=1) if state == "expired" else None)
    session.add(membership)
    await session.commit()
    original = membership.model_dump()
    response = await client.request("DELETE", url(), json={"actor_id": ACTOR})
    assert response.status_code == 200 and response.json()["changed"] is True
    assert (await session.exec(select(RoleDiscordBinding))).all() == []
    assert membership.model_dump() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_active", [False, True])
async def test_unassignment_rejects_other_membership_types_sharing_logical_role(client, session, catalog, shared_active):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    await client.put(url(GUILD_B), json={"discord_role_id": ROLE_B, "actor_id": ACTOR})
    session.add(MembershipType(code="express", name="VIP Express", role_id=catalog[0].id, is_active=shared_active))
    await session.commit()
    response = await client.request("DELETE", url(), json={"actor_id": ACTOR})
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "membership_role_shared"}}
    assert {(binding.guild_id, binding.discord_role_id) for binding in (await session.exec(select(RoleDiscordBinding))).all()} == {
        (GUILD_A, ROLE_A), (GUILD_B, ROLE_B),
    }


@pytest.mark.asyncio
async def test_inactive_type_can_remove_configuration_without_changing_get_or_put(client, session, catalog):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    m_type = catalog[1]
    m_type.is_active = False
    session.add(m_type)
    await session.commit()
    assert (await client.get(url())).status_code == 400
    assert (await client.put(url(), json={"discord_role_id": ROLE_B, "actor_id": ACTOR})).status_code == 400
    response = await client.request("DELETE", url(), json={"actor_id": ACTOR})
    assert response.status_code == 200 and response.json()["changed"] is True
    assert m_type.is_active is False and m_type.role_id == catalog[0].id


@pytest.mark.asyncio
async def test_removal_stops_guild_resolution_and_creation_before_domain_or_external_effects(client, session, catalog, game_delivery):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    assert (await client.request("DELETE", url(), json={"actor_id": ACTOR})).status_code == 200
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await MembershipRolesService.resolve_roles(GUILD_A, [catalog[0].id], session)
    assert error.value.status_code == 409
    response = await client.post("/api/v1/db/players/membership", json=create_payload())
    assert response.status_code == 409
    assert (await session.exec(select(Membership))).all() == []
    assert (await session.exec(select(PlayerRole))).all() == []
    game_delivery.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["0", "-1", "001", "abc", "١٢٣", "18446744073709551616", 123, None])
async def test_unassignment_requires_valid_actor_id(client, session, catalog, invalid):
    await client.put(url(), json={"discord_role_id": ROLE_A, "actor_id": ACTOR})
    response = await client.request("DELETE", url(), json={"actor_id": invalid})
    assert response.status_code == 422
    assert (await session.exec(select(RoleDiscordBinding))).one().discord_role_id == ROLE_A


@pytest.mark.asyncio
@pytest.mark.parametrize("guild_id", ["0", "-1", "001", "abc", "18446744073709551616"])
async def test_unassignment_requires_valid_guild_path(client, catalog, guild_id):
    assert (await client.request("DELETE", url(guild_id), json={"actor_id": ACTOR})).status_code == 422


@pytest.mark.asyncio
async def test_unassignment_requires_actor_body_and_existing_type_with_logical_role(client, session, catalog):
    assert (await client.request("DELETE", url(), json={})).status_code == 422
    assert (await client.request("DELETE", url())).status_code == 422
    assert (await client.request("DELETE", url(code="unknown"), json={"actor_id": ACTOR})).status_code == 404
    session.add(MembershipType(code="roleless", name="Roleless"))
    await session.commit()
    assert (await client.request("DELETE", url(code="roleless"), json={"actor_id": ACTOR})).status_code == 400
    assert (await session.exec(select(RoleDiscordBinding))).all() == []


def test_unassignment_response_requires_previous_role_when_changed():
    from pydantic import ValidationError
    response = {"guild_id": GUILD_A, "membership_type": "regular", "membership_type_name": "VIP Normal",
                "role_id": 1, "actor_id": ACTOR, "changed": True}
    with pytest.raises(ValidationError):
        MembershipRoleUnassignment(**response)
    assert MembershipRoleUnassignment(**response, discord_role_id=ROLE_A).discord_role_id == ROLE_A
    assert MembershipRoleUnassignment(**{**response, "changed": False}).discord_role_id is None
    with pytest.raises(ValidationError):
        MembershipRoleUnassignment(**{**response, "changed": False}, discord_role_id=ROLE_A)
