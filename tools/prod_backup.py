import os
import subprocess
import urllib.parse
from datetime import datetime

from dotenv import dotenv_values


def make_prod_backup():
    cfg = dotenv_values(".env.prod")
    db_url = cfg.get("DATABASE_URL", "")
    if not db_url:
        raise ValueError("DATABASE_URL not found in .env.prod")
        
    parsed = urllib.parse.urlparse(db_url)
    user = parsed.username or "postgres"
    password = urllib.parse.unquote(parsed.password) if parsed.password else ""
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    db_name = parsed.path.lstrip("/")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("backups/sql", exist_ok=True)
    out_file = os.path.abspath(f"backups/sql/prod_pre_migration_{timestamp}.sql")
    
    print(f"Creating backup from {host}:{port}/{db_name}...")
    cmd = [
        "docker", "run", "--rm",
        "-e", f"PGPASSWORD={password}",
        "postgres:alpine",
        "pg_dump",
        "-h", host,
        "-p", str(port),
        "-U", user,
        "-d", db_name
    ]
    
    with open(out_file, "wb") as f:
        res = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=False)
        if res.returncode != 0:
            err_msg = res.stderr.decode("utf-8", errors="replace") if res.stderr else "Unknown error"
            print("pg_dump ERROR:", err_msg)
            raise RuntimeError(f"pg_dump failed with return code {res.returncode}")

    size_mb = os.path.getsize(out_file) / (1024 * 1024)
    print(f"Backup SUCCESS: {out_file} ({size_mb:.2f} MB)")
    return out_file

if __name__ == "__main__":
    make_prod_backup()
