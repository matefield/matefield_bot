import re

with open('src/modules/v1/services/players_service.py', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Fix get_by_discord
c = c.replace(
    'return {\n            "steam_id": player.steam_id,\n            "in_game_name": player.in_game_name,\n            "custom_welcome_message": player.custom_welcome_message,\n            "observations": player.observations,\n        }',
    'return {\n            "steam_id": player.steam_id,\n            "in_game_name": player.in_game_name,\n            "discord_id": player.discord_id,\n            "role": "PLAYER",\n            "roles": [],\n            "active_memberships": [],\n            "is_banned": False,\n            "reward_points": player.reward_points,\n            "custom_welcome_message": player.custom_welcome_message,\n            "observations": player.observations,\n        }'
)

# 2. Fix get_by_steam
c = c.replace(
    'return {\n            "name": player.in_game_name,\n            "in_game_name": player.in_game_name,\n            "avatar_url": player.avatar_url,\n            "discord_id": player.discord_id, \n            "custom_welcome_message": player.custom_welcome_message,\n            "observations": player.observations,\n            "active_role": primary_role,\n            "is_banned": is_banned,\n            "memberships": active_memberships,\n            "active_memberships": active_memberships,\n            "special_roles": [r.name if (r.name and not r.name.isdigit()) else r.code for r in special_roles if r.role_type == "SPECIAL"]\n        }',
    'return {\n            "steam_id": player.steam_id,\n            "name": player.in_game_name,\n            "in_game_name": player.in_game_name,\n            "avatar_url": player.avatar_url,\n            "discord_id": player.discord_id, \n            "custom_welcome_message": player.custom_welcome_message,\n            "observations": player.observations,\n            "role": primary_role or "PLAYER",\n            "active_role": primary_role or "PLAYER",\n            "is_banned": is_banned,\n            "reward_points": player.reward_points,\n            "memberships": active_memberships,\n            "active_memberships": active_memberships,\n            "roles": [r.name if (r.name and not r.name.isdigit()) else r.code for r in special_roles if r.role_type == "SPECIAL"],\n            "special_roles": [r.name if (r.name and not r.name.isdigit()) else r.code for r in special_roles if r.role_type == "SPECIAL"]\n        }'
)

with open('src/modules/v1/services/players_service.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("done")
