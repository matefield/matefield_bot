import asyncio

from dotenv import dotenv_values

from tools.clone_prod_to_env import clone_data


async def main():
    prod_env = dotenv_values(".env.prod")
    dev_env = dotenv_values(".env.dev")
    
    prod_url = prod_env.get("DATABASE_URL")
    dev_url = dev_env.get("DATABASE_URL")
    
    if not prod_url or not dev_url:
        print("Missing DATABASE_URL in .env.prod or .env.dev")
        return

    await clone_data("dev", dev_url, prod_url)

if __name__ == "__main__":
    asyncio.run(main())
