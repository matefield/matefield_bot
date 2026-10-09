


class MockPlayer:
    def __init__(self, steam_id, name="Player", kills=0, deaths=0, cash=0, faction="Lonestar"):
        self.steamId = steam_id
        self.name = name
        self.kills = kills
        self.deaths = deaths
        self.cash = cash
        self.faction = faction


class MockFactionScore:
    def __init__(self, name, score):
        self.name = name
        self.score = score


class MockRotation:
    def __init__(self, now_index=0):
        self.nowIndex = now_index


class MockPlayersStatus:
    def __init__(self, current=0, max_players=100):
        self.current = current
        self.max = max_players


class MockScoreTick:
    def __init__(self, current=0):
        self.current = current


class MockGameStatus:
    def __init__(self, map_name="Bakurani", rotation_index=0, match_seconds=0, current_players=0, faction_scores=None, score_cap=100, score_tick=0):
        self.map = map_name
        self.rotation = MockRotation(rotation_index)
        self.matchSeconds = match_seconds
        self.players = MockPlayersStatus(current=current_players)
        self.factionScores = faction_scores or []
        self.scoreCap = score_cap
        self.scoreTick = MockScoreTick(score_tick)


class MockPlayersList:
    def __init__(self, players=None):
        self.players = players or []


