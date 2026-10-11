from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.connections.databases.db import Player, PlayerSession, RewardItem, RewardClaim, Membership
from src.modules.v1.services.rewards_service import RewardsService


@pytest.mark.asyncio
async def test_process_session_seeding_points_accumulation(session: AsyncSession):
    player = Player(steam_id="76561198000000001", discord_id="discord_seed_01", reward_points=0)
    sess = PlayerSession(steam_id=player.steam_id, start_time=datetime.now(timezone.utc))
    session.add(player)
    session.add(sess)
    await session.commit()

    # 1. Non-seeding tick (delta = 600s, is_seeding = False)
    awarded = RewardsService.process_session_seeding(
        session_obj=sess,
        player_obj=player,
        delta_seconds=600,
        is_seeding=False,
        minutes_per_point=30, # 1800s required
    )
    assert awarded == 0
    assert sess.total_seconds == 600
    assert sess.seeding_seconds == 0
    assert player.reward_points == 0

    # 2. Seeding tick with 900s (15 min) -> under 1800s threshold
    awarded = RewardsService.process_session_seeding(
        session_obj=sess,
        player_obj=player,
        delta_seconds=900,
        is_seeding=True,
        minutes_per_point=30,
    )
    assert awarded == 0
    assert sess.seeding_seconds == 900
    assert sess.rewarded_seeding_seconds == 0
    assert player.reward_points == 0

    # 3. Next seeding tick with 900s (Total = 1800s = 30 min) -> exactly 1 point awarded
    awarded = RewardsService.process_session_seeding(
        session_obj=sess,
        player_obj=player,
        delta_seconds=900,
        is_seeding=True,
        minutes_per_point=30,
    )
    session.add(player)
    await session.flush()
    await session.refresh(player)

    assert awarded == 1
    assert sess.seeding_seconds == 1800
    assert sess.rewarded_seeding_seconds == 1800
    assert player.reward_points == 1

    # 4. Long seeding tick with 3600s (60 min) -> 2 additional points awarded
    awarded = RewardsService.process_session_seeding(
        session_obj=sess,
        player_obj=player,
        delta_seconds=3600,
        is_seeding=True,
        minutes_per_point=30,
    )
    session.add(player)
    await session.flush()
    await session.refresh(player)

    assert awarded == 2
    assert sess.seeding_seconds == 5400
    assert sess.rewarded_seeding_seconds == 5400
    assert player.reward_points == 3


@pytest.mark.asyncio
async def test_get_catalog_and_create_item(client: AsyncClient, session: AsyncSession):
    # 1. Fetch catalog initially -> ensure defaults exist
    resp = await client.get("/api/v1/rewards/catalog")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 2
    codes = [item["code"] for item in items]
    assert "VIP_MONTH" in codes
    assert "STEAM_GAME_KEY" in codes

    # 2. Admin creates a new item
    new_item_payload = {
        "code": "CUSTOM_ROLE_VIP",
        "name": "Rol VIP Veterano",
        "description": "Rol especial en Discord y servidor",
        "cost_points": 50,
        "delivery_type": "AUTOMATIC",
        "reward_type": "ROLE",
        "reward_value": "VIP",
        "is_active": True,
    }
    resp_create = await client.post("/api/v1/rewards/admin/create", json=new_item_payload)
    assert resp_create.status_code == 200
    assert resp_create.json()["ok"] is True

    # 3. Fetch catalog again -> new item is included
    resp_after = await client.get("/api/v1/rewards/catalog")
    assert resp_after.status_code == 200
    codes_after = [item["code"] for item in resp_after.json()]
    assert "CUSTOM_ROLE_VIP" in codes_after


@pytest.mark.asyncio
async def test_claim_automatic_vip_reward(client: AsyncClient, session: AsyncSession):
    player = Player(steam_id="76561198000000002", discord_id="discord_user_02", reward_points=100)
    session.add(player)
    await session.commit()

    # Ensure catalog exists
    await RewardsService._ensure_defaults(session)

    # Claim VIP_MONTH (costs 60 pts) using discord_id
    claim_payload = {
        "player_identifier": "discord_user_02",
        "reward_code": "VIP_MONTH",
    }
    resp = await client.post("/api/v1/rewards/claim", json=claim_payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert data["reward_code"] == "VIP_MONTH"
    assert data["cost_points"] == 60
    assert data["remaining_points"] == 40
    assert data["status"] == "DELIVERED"
    assert data["claim_code"].startswith("MF-")

    # Verify membership created in DB
    membership = (
        await session.exec(
            select(Membership).where(Membership.steam_id == "76561198000000002", Membership.is_active == True)
        )
    ).first()
    assert membership is not None
    assert membership.membership_type == "VIP"
    assert membership.payment_source == "REWARDS"


@pytest.mark.asyncio
async def test_claim_insufficient_points(client: AsyncClient, session: AsyncSession):
    player = Player(steam_id="76561198000000003", discord_id="discord_user_03", reward_points=20)
    session.add(player)
    await session.commit()

    await RewardsService._ensure_defaults(session)

    # Claim VIP_MONTH (costs 60 pts, player has 20)
    claim_payload = {
        "player_identifier": "76561198000000003",
        "reward_code": "VIP_MONTH",
    }
    resp = await client.post("/api/v1/rewards/claim", json=claim_payload)
    assert resp.status_code == 400
    assert "insuficientes" in resp.json()["detail"].lower()

    # Verify no points deducted
    await session.refresh(player)
    assert player.reward_points == 20


@pytest.mark.asyncio
async def test_manual_ticket_claim_and_admin_delivery_workflow(client: AsyncClient, session: AsyncSession):
    player = Player(steam_id="76561198000000004", discord_id="discord_user_04", reward_points=150)
    session.add(player)
    await session.commit()

    await RewardsService._ensure_defaults(session)

    # 1. Claim STEAM_GAME_KEY (costs 120 points, manual ticket)
    claim_payload = {
        "player_identifier": "76561198000000004",
        "reward_code": "STEAM_GAME_KEY",
    }
    resp_claim = await client.post("/api/v1/rewards/claim", json=claim_payload)
    assert resp_claim.status_code == 200
    claim_data = resp_claim.json()

    assert claim_data["status"] == "PENDING"
    assert claim_data["remaining_points"] == 30
    voucher_code = claim_data["claim_code"]
    assert voucher_code.startswith("MF-")

    # 2. Staff verifies the voucher code
    resp_verify = await client.get(f"/api/v1/rewards/admin/verify/{voucher_code}")
    assert resp_verify.status_code == 200
    verify_data = resp_verify.json()
    assert verify_data["claim_code"] == voucher_code
    assert verify_data["status"] == "PENDING"
    assert verify_data["points_spent"] == 120
    assert verify_data["steam_id"] == "76561198000000004"

    # 3. Staff delivers the key in ticket
    deliver_payload = {
        "delivered_by": "StaffAdmin#1234",
        "notes": "Steam Key: ABCD-1234-EFGH enviada por DM",
    }
    resp_deliver = await client.post(f"/api/v1/rewards/admin/deliver/{voucher_code}", json=deliver_payload)
    assert resp_deliver.status_code == 200
    assert resp_deliver.json()["ok"] is True

    # 4. Verify status is now DELIVERED
    resp_verify2 = await client.get(f"/api/v1/rewards/admin/verify/{voucher_code}")
    assert resp_verify2.status_code == 200
    assert resp_verify2.json()["status"] == "DELIVERED"
    assert resp_verify2.json()["delivered_by"] == "StaffAdmin#1234"

    # 5. Cannot deliver already delivered voucher
    resp_redeliver = await client.post(f"/api/v1/rewards/admin/deliver/{voucher_code}", json=deliver_payload)
    assert resp_redeliver.status_code == 400


@pytest.mark.asyncio
async def test_manual_ticket_refund_workflow(client: AsyncClient, session: AsyncSession):
    player = Player(steam_id="76561198000000005", discord_id="discord_user_05", reward_points=120)
    session.add(player)
    await session.commit()

    await RewardsService._ensure_defaults(session)

    # Claim STEAM_GAME_KEY
    claim_payload = {
        "player_identifier": "76561198000000005",
        "reward_code": "STEAM_GAME_KEY",
    }
    resp_claim = await client.post("/api/v1/rewards/claim", json=claim_payload)
    assert resp_claim.status_code == 200
    voucher_code = resp_claim.json()["claim_code"]

    await session.refresh(player)
    assert player.reward_points == 0

    # Staff refunds voucher
    refund_payload = {
        "refunded_by": "SupportStaff",
        "reason": "Stock agotado temporalmente",
    }
    resp_refund = await client.post(f"/api/v1/rewards/admin/refund/{voucher_code}", json=refund_payload)
    assert resp_refund.status_code == 200
    data = resp_refund.json()
    assert data["ok"] is True
    assert data["refunded_points"] == 120
    assert data["new_balance"] == 120

    # Points restored in DB
    await session.refresh(player)
    assert player.reward_points == 120

    # Cannot refund again
    resp_re_refund = await client.post(f"/api/v1/rewards/admin/refund/{voucher_code}", json=refund_payload)
    assert resp_re_refund.status_code == 400


@pytest.mark.asyncio
async def test_give_points_and_balance_endpoints(client: AsyncClient, session: AsyncSession):
    player = Player(steam_id="76561198000000006", discord_id="discord_user_06", reward_points=10)
    # Add a session with 1800s seeding (30 min)
    sess = PlayerSession(
        steam_id="76561198000000006",
        start_time=datetime.now(timezone.utc),
        total_seconds=2000,
        seeding_seconds=1800,
        rewarded_seeding_seconds=1800,
    )
    session.add(player)
    session.add(sess)
    await session.commit()

    # 1. Admin gives 25 points
    give_payload = {
        "player_identifier": "discord_user_06",
        "points": 25,
        "reason": "Premio evento mensual",
    }
    resp_give = await client.post("/api/v1/rewards/admin/give_points", json=give_payload)
    assert resp_give.status_code == 200
    assert resp_give.json()["new_balance"] == 35

    # 2. Check balance endpoint via discord_id
    resp_bal = await client.get("/api/v1/rewards/balance/discord_user_06")
    assert resp_bal.status_code == 200
    bal_data = resp_bal.json()
    assert bal_data["steam_id"] == "76561198000000006"
    assert bal_data["discord_id"] == "discord_user_06"
    assert bal_data["reward_points"] == 35
    assert bal_data["total_seeding_minutes"] == 30

    # 3. Check balance endpoint via steam_id
    resp_bal_steam = await client.get("/api/v1/rewards/balance/76561198000000006")
    assert resp_bal_steam.status_code == 200
    assert resp_bal_steam.json()["reward_points"] == 35


@pytest.mark.asyncio
async def test_rewards_requires_linked_account(client: AsyncClient, session: AsyncSession):
    # Player exists in game DB from Steam, but has NOT linked Discord (discord_id is None)
    unlinked_player = Player(steam_id="76561198000099999", discord_id=None, reward_points=100)
    sess = PlayerSession(steam_id=unlinked_player.steam_id, start_time=datetime.now(timezone.utc))
    session.add(unlinked_player)
    session.add(sess)
    await session.commit()

    await RewardsService._ensure_defaults(session)

    # 1. Seeding tick does NOT award points to unlinked player
    awarded = RewardsService.process_session_seeding(
        session_obj=sess,
        player_obj=unlinked_player,
        delta_seconds=3600,
        is_seeding=True,
        minutes_per_point=30,
        require_linked=True,
    )
    assert awarded == 0
    assert unlinked_player.reward_points == 100

    # 2. Querying balance for unlinked player fails with 400
    resp_bal = await client.get(f"/api/v1/rewards/balance/{unlinked_player.steam_id}")
    assert resp_bal.status_code == 400
    assert "obligatorio vincularla" in resp_bal.json()["detail"].lower()

    # 3. Attempting to claim rewards for unlinked player fails with 400
    claim_payload = {
        "player_identifier": unlinked_player.steam_id,
        "reward_code": "VIP_MONTH",
    }
    resp_claim = await client.post("/api/v1/rewards/claim", json=claim_payload)
    assert resp_claim.status_code == 400
    assert "obligatorio tener tu cuenta" in resp_claim.json()["detail"].lower()

    # 4. Once linked, claim succeeds
    unlinked_player.discord_id = "discord_user_99999"
    session.add(unlinked_player)
    await session.commit()

    resp_claim_after = await client.post("/api/v1/rewards/claim", json=claim_payload)
    assert resp_claim_after.status_code == 200
    assert resp_claim_after.json()["ok"] is True



@pytest.mark.asyncio
async def test_membership_reward_handover_rejects_before_spending_points(client, session, monkeypatch):
    from wardogs_config import BOT_SETTINGS
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    player = Player(steam_id="76561198000009001", discord_id="reward-owner-test", reward_points=100)
    session.add(player)
    await session.commit()
    await RewardsService._ensure_defaults(session)

    response = await client.post("/api/v1/rewards/claim", json={
        "player_identifier": player.discord_id, "reward_code": "VIP_MONTH",
    })
    assert response.status_code == 409
    await session.refresh(player)
    assert player.reward_points == 100
    assert not (await session.exec(select(RewardClaim))).all()
    assert not (await session.exec(select(Membership))).all()


@pytest.mark.asyncio
async def test_non_membership_reward_remains_available_during_handover(client, session, monkeypatch):
    from wardogs_config import BOT_SETTINGS
    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    player = Player(steam_id="76561198000009002", discord_id="manual-reward-test", reward_points=500)
    reward = RewardItem(code="MANUAL_TEST", name="Manual test", cost_points=25,
                        delivery_type="MANUAL", reward_type="GAME_KEY", reward_value="KEY")
    session.add_all([player, reward])
    await session.commit()

    response = await client.post("/api/v1/rewards/claim", json={
        "player_identifier": player.discord_id, "reward_code": reward.code,
    })
    assert response.status_code == 200
    await session.refresh(player)
    assert player.reward_points == 475
    assert len((await session.exec(select(RewardClaim))).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("role_type,attached_to_membership", [("VIP", False), ("SPECIAL", True)])
async def test_protected_role_reward_rejects_before_points_voucher_or_role_mutations(client, session, monkeypatch, mocker, role_type, attached_to_membership):
    from wardogs_config import BOT_SETTINGS
    from src.connections.databases.db import Role, PlayerRole

    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    player = Player(steam_id="protected-role-reward", discord_id="protected-reward-user", reward_points=100)
    role = Role(code="PROTECTED_REWARD", name="Protected reward", role_type=role_type)
    reward = RewardItem(code="PROTECTED_ROLE", name="Protected role", cost_points=25,
                        delivery_type="AUTOMATIC", reward_type="ROLE", reward_value=role.code)
    session.add_all([player, role, reward])
    await session.flush()
    session.add(PlayerRole(steam_id=player.steam_id, role_id=role.id))
    if attached_to_membership:
        session.add(Membership(steam_id=player.steam_id, membership_type="historical", is_active=False,
                               special_role_id=role.id))
    await session.commit()
    add = mocker.spy(session, "add")
    flush = mocker.spy(session, "flush")
    commit = mocker.spy(session, "commit")
    voucher = mocker.spy(RewardsService, "generate_voucher_code")

    response = await client.post("/api/v1/rewards/claim", json={
        "player_identifier": player.discord_id, "reward_code": reward.code,
    })

    assert response.status_code == 409 and "Laracord" in response.json()["detail"]
    assert player.reward_points == 100  # No rollback or refresh is needed to restore it.
    add.assert_not_called()
    flush.assert_not_called()
    commit.assert_not_called()
    voucher.assert_not_called()
    assert not (await session.exec(select(RewardClaim))).all()
    assert await session.get(PlayerRole, (player.steam_id, role.id)) is not None
    await session.refresh(player)
    assert player.reward_points == 100


@pytest.mark.asyncio
async def test_automatic_unrelated_role_reward_remains_available(client, session, monkeypatch):
    from wardogs_config import BOT_SETTINGS
    from src.connections.databases.db import Role, PlayerRole

    monkeypatch.setattr(BOT_SETTINGS, "DISCORD_MEMBERSHIP_MANAGEMENT_ENABLED", False)
    player = Player(steam_id="ordinary-role-reward", discord_id="ordinary-reward-user", reward_points=100)
    role = Role(code="COACH", name="Coach", role_type="SPECIAL")
    reward = RewardItem(code="COACH_ROLE", name="Coach role", cost_points=25,
                        delivery_type="AUTOMATIC", reward_type="ROLE", reward_value=role.code)
    session.add_all([player, role, reward])
    await session.commit()

    response = await client.post("/api/v1/rewards/claim", json={
        "player_identifier": player.discord_id, "reward_code": reward.code,
    })

    assert response.status_code == 200 and response.json()["status"] == "DELIVERED"
    assert player.reward_points == 75
    assert await session.get(PlayerRole, (player.steam_id, role.id)) is not None
    claims = (await session.exec(select(RewardClaim))).all()
    assert len(claims) == 1 and claims[0].status == "DELIVERED"
