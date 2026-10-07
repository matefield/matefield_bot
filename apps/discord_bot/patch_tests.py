import re
from pathlib import Path

def process_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # We need to make sure we import schemas
    if "from wardogs_schemas import v1 as schemas" not in content and "PlayerResponse" not in content:
        content = "from wardogs_schemas import v1 as schemas\n" + content

    # Replace specific mocked dictionaries with schemas.PlayerResponse
    # test_steam_link_interaction.py
    content = re.sub(
        r'return_value = \{"steam_id": "([^"]+)", "in_game_name": name\}',
        r'return_value = schemas.PlayerResponse(steam_id="\1", in_game_name=name, roles=[])',
        content
    )

    # test_commands.py player_profile
    content = re.sub(
        r'return_value=\{"steam_id": "76561198058686447"\}',
        r'return_value=schemas.PlayerResponse(steam_id="76561198058686447", in_game_name="Player", roles=[])',
        content
    )
    
    # test_commands.py rewards
    content = re.sub(
        r'get_player_by_discord = AsyncMock\(return_value=\{\n\s*"steam_id": "76561198000000001",\n\s*"discord_id": "123456789",\n\s*"in_game_name": "RewardsTest"\n\s*\}\)',
        r'get_player_by_discord = AsyncMock(return_value=schemas.PlayerResponse(steam_id="76561198000000001", discord_id="123456789", in_game_name="RewardsTest", roles=[]))',
        content
    )

    content = re.sub(
        r'get_player_rewards_balance = AsyncMock\(return_value=\{\n\s*"steam_id": "76561198000000001",\n\s*"reward_points": 100\n\s*\}\)',
        r'get_player_rewards_balance = AsyncMock(return_value=schemas.PlayerRewardBalanceResponse(steam_id="76561198000000001", reward_points=100))',
        content
    )

    # test_integration_tasks.py sync_single_user_roles_linked
    content = re.sub(
        r'res\["success"\] is True',
        r'res.get("success", False) is True',
        content
    )

    # For api_client tests: test_api_client.py
    # RewardItemResponse**i => It failed because res was a string? No, because it was mock data.
    # In test_api_client.py:
    # "id": 1, "code": "VIP", ...
    # We should fix it there too.

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

test_files = [
    'tests/test_commands.py',
    'tests/test_steam_link_interaction.py',
    'tests/test_integration_tasks.py',
    'tests/test_api_client.py'
]

for tf in test_files:
    process_file(tf)
print("Patcher executed successfully.")
