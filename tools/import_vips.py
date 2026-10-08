import csv
import sys
import argparse
from datetime import datetime, timezone
from sqlmodel import Session, create_engine, select
import os

# We will run this inside the api_rcon container
from src.connections.databases.db import Player, Membership, Role, PlayerRole
from src.config import ENVIRONMENT_SETTINGS

# DB URL
engine = create_engine(ENVIRONMENT_SETTINGS.CONNECTIONS_SETTINGS.DATABASE_URL.replace("+asyncpg", ""))

FUNDADOR_ROLE_ID = 1546690312762564648

def parse_date(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        print(f"Error parsing date {date_str}: {e}")
        return None

def calculate_end_date_from_obs(start_date, obs):
    obs_lower = obs.lower() if obs else ""
    # "compro 5 meses" -> add 5 months
    if "compro 5 meses" in obs_lower or "compró 5 meses" in obs_lower:
        # crude add months
        month = start_date.month - 1 + 5
        year = start_date.year + month // 12
        month = month % 12 + 1
        return start_date.replace(year=year, month=month)
    if "vip seed (3 dias)" in obs_lower:
        import datetime
        return start_date + datetime.timedelta(days=3)
    return None

def main(csv_path, dry_run=True):
    print(f"Running import from {csv_path} (Dry Run: {dry_run})")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
    valid_rows = [r for r in rows if r.get('ID STEAM') and r.get('ID DISCORD')]
    print(f"Found {len(valid_rows)} valid rows with both Steam and Discord IDs.")
    
    with Session(engine) as session:
        # Ensure founder role exists
        if not dry_run:
            founder_role = session.exec(select(Role).where(Role.id == FUNDADOR_ROLE_ID)).first()
            if not founder_role:
                founder_role = Role(id=FUNDADOR_ROLE_ID, name="Fundador", code="FUNDADOR", role_type="SPECIAL")
                session.add(founder_role)
                session.commit()
        
        for row in valid_rows:
            steam_id = row['ID STEAM'].strip()
            discord_id = row['ID DISCORD'].strip()
            es_fundador = row.get('ES FUNDADOR', '').strip().upper() == 'SI'
            tipo_vip = row.get('TIPO VIP', '').strip().upper()
            start_date_str = row.get('Fecha inicio', '').strip()
            end_date_str = row.get('Fecha fin', '').strip()
            obs = row.get('OBSERVACIONES', '').strip()
            
            print(f"\n--- Processing {row.get('USUARIO', steam_id)} ({steam_id}) ---")
            
            # 1. Upsert Player
            player = session.exec(select(Player).where(Player.steam_id == steam_id)).first()
            if not player:
                print(f"[Player] Creating new player: {steam_id} with discord {discord_id}")
                player = Player(steam_id=steam_id, discord_id=discord_id, observations=obs or None)
                if not dry_run:
                    session.add(player)
            else:
                print(f"[Player] Found existing player {steam_id}. Updating discord and obs.")
                player.discord_id = discord_id
                if obs:
                    if player.observations:
                        player.observations += f" | {obs}"
                    else:
                        player.observations = obs
                if not dry_run:
                    session.add(player)
                    
            if not dry_run:
                session.flush() # flush to get player in session
                
            # 2. Membership
            membership_type = None
            end_date = None
            start_date = parse_date(start_date_str) or datetime.now(timezone.utc)
            
            if "vip seed" in obs.lower():
                membership_type = "VIP_SEED"
                end_date = parse_date(end_date_str) or calculate_end_date_from_obs(start_date, obs)
            elif tipo_vip == "MENSUAL":
                membership_type = "VIP_COMUN"
                end_date = parse_date(end_date_str) or calculate_end_date_from_obs(start_date, obs)
            elif tipo_vip == "PERMANENTE":
                membership_type = "VIP_PERMANENTE"
                end_date = None
                
            if membership_type:
                # Check if they already have an active membership of this type
                existing_mem = session.exec(
                    select(Membership).where(
                        Membership.steam_id == steam_id,
                        Membership.membership_type == membership_type,
                        Membership.is_active == True
                    )
                ).first()
                
                if existing_mem:
                    print(f"[Membership] ALREADY EXISTS: {membership_type} for {steam_id}")
                else:
                    print(f"[Membership] CREATING: {membership_type} | Start: {start_date} | End: {end_date}")
                    if not dry_run:
                        mem = Membership(
                            steam_id=steam_id,
                            membership_type=membership_type,
                            start_time=start_date,
                            end_time=end_date,
                            is_active=True,
                            rcon_sync_status="SUCCESS" if str(row.get("status_rcon", row.get("status rcon", ""))).strip().upper() in ["YES", "SI", "TRUE"] else "PENDING"
                        )
                        session.add(mem)
            else:
                print(f"[Membership] No standard membership determined (Tipo VIP: {tipo_vip})")
                
            # 3. Founder Role
            if es_fundador:
                print(f"[Roles] Granting FUNDADOR special role ({FUNDADOR_ROLE_ID})")
                # Check existing
                existing_role = session.exec(
                    select(PlayerRole).where(
                        PlayerRole.steam_id == steam_id,
                        PlayerRole.role_id == FUNDADOR_ROLE_ID
                    )
                ).first()
                if existing_role:
                    print(f"[Roles] ALREADY HAS FUNDADOR ROLE")
                else:
                    if not dry_run:
                        pr = PlayerRole(steam_id=steam_id, role_id=FUNDADOR_ROLE_ID)
                        session.add(pr)
                        
        if not dry_run:
            print("\n[Commit] Committing all changes to database...")
            session.commit()
            print("[Commit] Done.")
        else:
            print("\n[Dry Run] Changes were NOT saved to the database.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import VIPs from CSV")
    parser.add_argument("csv_path", help="Path to the CSV file")
    parser.add_argument("--execute", action="store_true", help="Actually commit to the database")
    args = parser.parse_args()
    
    main(args.csv_path, dry_run=not args.execute)
