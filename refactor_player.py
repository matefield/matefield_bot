import os
import re

d = r'd:\proyectos_dev\matefield_bot\apps\discord_bot\src\plugins'

for f in os.listdir(d):
    if not f.endswith('.py'):
        continue
    filepath = os.path.join(d, f)
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Replace common player.get(...) with player.attr
    new_content = content
    # For player objects (player, db_player, target_player, player_info, user_data)
    vars = ['player', 'db_player', 'target_player', 'player_info', 'user_data', 'db_check', 'u']
    attrs = ['steam_id', 'discord_id', 'in_game_name', 'role', 'is_banned', 'reward_points', 'custom_welcome_message', 'active_role', 'active_memberships', 'special_roles']
    
    for v in vars:
        for attr in attrs:
            new_content = re.sub(fr'{v}\.get\("{attr}"\)', f'{v}.{attr}', new_content)
            new_content = re.sub(fr"{v}\.get\('{attr}'\)", f'{v}.{attr}', new_content)
            # also handle get("attr", default)
            # but default for those might be different. Let's just catch the ones with no default first.
            new_content = re.sub(fr'{v}\.get\("{attr}",\s*\[\]\)', f'{v}.{attr}', new_content)
            new_content = re.sub(fr"{v}\.get\('{attr}',\s*\[\]\)", f'{v}.{attr}', new_content)
            new_content = re.sub(fr'{v}\.get\("{attr}",\s*""\)', f'{v}.{attr}', new_content)
            new_content = re.sub(fr"{v}\.get\('{attr}',\s*''\)", f'{v}.{attr}', new_content)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(new_content)
        print(f"Updated {f}")
