import datetime
import hashlib
import random
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from wardogs_schemas import v1 as schemas

app = FastAPI(title="Wardogs RCON Mock")
started_at = time.monotonic()
mock_experiences = ["Rush", "Conquest"]
mock_lighting = "Day"

audit_logs = []

def add_audit_log(event: str, detail: str):
    audit_logs.insert(0, {
        "timestampUtc": datetime.datetime.now(datetime.UTC).isoformat(),
        "peer": "127.0.0.1",
        "sessionId": "mock-session",
        "event": event,
        "detail": detail
    })

def verify_auth(authorization: str | None = Header(None)):
    if authorization != "Bearer test":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return authorization

from typing import Any

mock_state: dict[str, Any] = {
    "score": 50,
    "rotation": 0,
    "maps": ["Bakurani", "Desert Strike", "Urban Combat", "Jungle Ops"],
    "match_seconds": 600,
    "lonestar_score": 100,
    "manticore_score": 150,
    "valkyre_score": 200
}

@app.get("/v1/status", response_model=schemas.Status)
async def get_status(auth: str = Depends(verify_auth)):
    # Simulate time passing/points
    mock_state["score"] += 15
    mock_state["match_seconds"] += 10
    mock_state["lonestar_score"] += random.randint(1, 5)
    mock_state["manticore_score"] += random.randint(1, 5)
    mock_state["valkyre_score"] += random.randint(1, 5)
    
    if mock_state["score"] >= 100:
        mock_state["score"] = 0
        mock_state["rotation"] = (mock_state["rotation"] + 1) % len(mock_state["maps"])
        mock_state["match_seconds"] = 0
        mock_state["lonestar_score"] = 0
        mock_state["manticore_score"] = 0
        mock_state["valkyre_score"] = 0
        
    current_map = mock_state["maps"][mock_state["rotation"]]
    
    return {
        "serverName": "Wardogs Mock Server",
        "map": current_map,
        "experiences": mock_experiences,
        "lighting": mock_lighting,
        "alternator": "Random",
        "scoreTick": {"current": mock_state["score"], "min": 0, "max": 100},
        "scoreCap": 100,
        "matchSeconds": mock_state["match_seconds"],
        "players": {"current": len(mock_players), "max": 100},
        "factionScores": [
            {"name": "Lonestar", "colorHex": "#0000FF", "score": mock_state["lonestar_score"]},
            {"name": "Manticore", "colorHex": "#00FF00", "score": mock_state["manticore_score"]},
            {"name": "Valkyre", "colorHex": "#FF0000", "score": mock_state["valkyre_score"]}
        ],
        "rotation": {"nowIndex": mock_state["rotation"], "nextIndex": (mock_state["rotation"] + 1) % len(mock_state["maps"])}
    }


@app.get("/v1/catalog/maps")
async def get_maps(auth: str = Depends(verify_auth)):
    return {"maps": [{"id": name, "displayName": name} for name in mock_state["maps"]]}


@app.get("/v1/catalog/lightings")
async def get_lightings(auth: str = Depends(verify_auth)):
    return {"lightings": [{"id": mock_lighting, "displayName": mock_lighting}]}


@app.get("/v1/catalog/experiences")
async def get_experiences(auth: str = Depends(verify_auth)):
    return {
        "experiences": [{"id": name, "displayName": name} for name in mock_experiences]
    }


@app.get("/v1/capabilities")
async def get_capabilities(auth: str = Depends(verify_auth)):
    # Report only implemented game routes; debug helpers are not game capabilities.
    routes = sorted(
        f"{method} {route.path}"
        for route in app.routes
        if route.path.startswith("/v1/") and not route.path.startswith("/v1/mock/")
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    )
    return {
        "apiVersion": 1,
        "build": "matefield-python-mock",
        "auth": {"scheme": "bearer", "header": "Authorization"},
        # The legacy JSON config endpoint does not implement Warcon's INI editor.
        "config": {"writable": False, "document": "/v1/config"},
        "routes": routes,
    }


@app.get("/v1/health")
async def get_health(auth: str = Depends(verify_auth)):
    return {
        "status": "ok",
        "uptimeSeconds": int(time.monotonic() - started_at),
        "connections": {"active": 0},
        "gameThreadQueue": {"inFlight": 0, "depth": 0, "rejectedTotal": 0},
    }


@app.get("/v1/rotation")
async def get_rotation(auth: str = Depends(verify_auth)):
    current = mock_state["rotation"]
    next_index = (current + 1) % len(mock_state["maps"])
    return {
        "enabled": True,
        "mode": "ordered",
        "entries": [
            {
                "index": index,
                "map": name,
                "experiences": mock_experiences,
                "lighting": mock_lighting,
                "status": "now" if index == current else "next" if index == next_index else None,
                "denied": False,
            }
            for index, name in enumerate(mock_state["maps"])
        ],
    }


@app.get("/v1/sponsor")
async def get_sponsor(auth: str = Depends(verify_auth)):
    return {"imageUrl": ""}


mock_players: list[dict[str, Any]] = []
def populate_mock_players(count: int = 80):
    global mock_players
    factions = ['Lonestar', 'Manticore', 'Valkyre']
    mock_players = []
    for i in range(1, count + 1):
        mock_players.append({
            'name': f'Soldier_{i:03d}',
            'steamId': f'7656119800000{i:04d}',
            'faction': factions[i % len(factions)],
            'kills': random.randint(0, 30),
            'deaths': random.randint(0, 18),
            'cash': random.randint(200, 4500),
            'pingMs': random.randint(15, 85)
        })
populate_mock_players(80)

@app.get("/v1/players", response_model=schemas.Players1)
async def get_players(auth: str = Depends(verify_auth)):
    # Si acaba de cambiar el mapa (score es bajo), quizas podriamos reiniciar los stats, 
    # pero para simular basta con subirlos aleatoriamente.
    for p in mock_players:
        if random.random() > 0.5:
            p["kills"] += random.randint(1, 3)
            p["cash"] += random.randint(50, 200)
        if random.random() > 0.7:
            p["deaths"] += 1
        p["pingMs"] = random.randint(20, 100)
        
    return {
        "players": mock_players
    }

@app.get("/v1/audit", response_model=schemas.Audit)
async def get_audit(limit: int = 50, auth: str = Depends(verify_auth)):
    return {
        "entries": audit_logs[:limit]
    }

reserved_slots_state = ["76561198000000001"]
banned_players_state = []

@app.get("/v1/bans")
async def get_bans(auth: str = Depends(verify_auth)):
    return {"bans": banned_players_state}

@app.post("/v1/bans")
async def ban_player(req: Request, auth: str = Depends(verify_auth)):
    data = await req.json()
    steam_id = data.get("steamId")
    add_audit_log("Ban", f"Banned {steam_id}")
    if steam_id not in [b.get("steamId") for b in banned_players_state]:
        banned_players_state.append({"steamId": steam_id, "reason": data.get("reason", "")})
    global mock_players
    mock_players = [p for p in mock_players if p["steamId"] != steam_id]
    return {"ok": True}

@app.delete("/v1/bans/{steam_id}")
async def unban_player(steam_id: str, auth: str = Depends(verify_auth)):
    add_audit_log("Unban", f"Unbanned {steam_id}")
    global banned_players_state
    original_len = len(banned_players_state)
    banned_players_state = [b for b in banned_players_state if b.get("steamId") != steam_id]
    if len(banned_players_state) == original_len:
        raise HTTPException(status_code=404, detail="Ban not found")
    return {"ok": True}

@app.get("/v1/reserved-slots", response_model=schemas.ReservedSlots)
async def get_reserved_slots(auth: str = Depends(verify_auth)):
    return {
        "reservedSlots": reserved_slots_state
    }

@app.post("/v1/reserved-slots")
async def add_reserved_slot(req: schemas.SteamIdRequest, auth: str = Depends(verify_auth)):
    add_audit_log("ReservedSlotAdded", f"Added steamId: {req.steamId}")
    if req.steamId not in reserved_slots_state:
        reserved_slots_state.append(req.steamId)
    return {"message": "Success"}

@app.delete("/v1/reserved-slots/{steam_id}")
async def remove_reserved_slot(steam_id: str, auth: str = Depends(verify_auth)):
    add_audit_log("ReservedSlotRemoved", f"Removed steamId: {steam_id}")
    if steam_id in reserved_slots_state:
        reserved_slots_state.remove(steam_id)
    return {"message": "Success"}

@app.post("/v1/broadcast")
async def broadcast(req: schemas.MessageRequest, auth: str = Depends(verify_auth)):
    add_audit_log("Broadcast", f"Message: {req.message}")
    return {"message": "Broadcast sent"}

@app.post("/v1/players/{steam_id}/message")
async def send_player_message(steam_id: str, req: schemas.MessageRequest, auth: str = Depends(verify_auth)):
    add_audit_log("PlayerMessage", f"Message to {steam_id}: {req.message}")
    return {"ok": True}

@app.post("/v1/players/{steam_id}/kick")
async def kick_player(steam_id: str, req: schemas.ReasonRequest, auth: str = Depends(verify_auth)):
    add_audit_log("Kick", f"Kicked {steam_id}. Reason: {req.reason}")
    global mock_players
    mock_players = [p for p in mock_players if p["steamId"] != steam_id]
    return {"ok": True}


@app.post("/v1/players/{steam_id}/faction")
async def switch_faction(steam_id: str, req: schemas.FactionRequest, auth: str = Depends(verify_auth)):
    add_audit_log("SwitchFaction", f"Switched {steam_id} to faction {req.faction}")
    for p in mock_players:
        if p["steamId"] == steam_id:
            p["faction"] = req.faction
    return {"ok": True}

@app.get("/v1/config")
async def get_config(auth: str = Depends(verify_auth)):
    """Expose the live slots as the read-only INI document Warcon also inspects."""
    text = "[/Script/WDGame.WDGameSession]\n!DefaultReservedPlayerIds=ClearArray\n"
    text += "".join(f".DefaultReservedPlayerIds={steam_id}\n" for steam_id in reserved_slots_state)
    return {
        "text": text,
        "revision": hashlib.sha256(text.encode()).hexdigest(),
        "writable": False,
        "sections": [],
        "warnings": [],
    }

@app.put("/v1/config", response_model=schemas.ConfigResult)
async def update_config(req: Request, force: bool = False, fullApply: bool = False, auth: str = Depends(verify_auth)):
    # Simular 412 ocasionalmente (Chaos Engineering para el retry de concurrencia)
    if random.random() < 0.2:
        raise HTTPException(status_code=412, detail="Precondition Failed: Revision mismatch")
        
    add_audit_log("ConfigUpdate", "Configuration was updated")
    return {
        "success": True,
        "newRevision": f"rev{random.randint(1000, 9999)}"
    }

@app.post("/v1/mock/populate")
async def populate(count: int = 80):
    populate_mock_players(count)
    return {"ok": True, "count": len(mock_players)}
