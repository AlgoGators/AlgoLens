"""Turn a copy of trade-ngin's config_template into the simulator's /app/config.

* defaults.json: the database block points at the sim postgres (the C++ engine reads its
  database settings only from here; the Python desk service reads DB_* first).
* portfolios/*/email.json: SMTP is Mailpit. The C++ mailer always uses STARTTLS and logs in,
  so use_tls stays true and a dummy login is set; Mailpit accepts any login.
"""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])

defaults_path = root / "defaults.json"
defaults = json.loads(defaults_path.read_text(encoding="utf-8"))
defaults["database"] = {
    "host": "postgres",
    "port": "5432",
    "username": "postgres",
    "password": "sim",
    "name": "new_algo_data",
    "num_connections": 5,
}
defaults_path.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")

email = {
    "_description": "Simulator: every e-mail goes to Mailpit (http://localhost:8025)",
    "smtp_host": "mailpit",
    "smtp_port": 1025,
    "username": "sim",
    "password": "sim",
    "from_email": "qt-engine@sim.local",
    "to_emails": ["desk@sim.local"],
    "to_emails_production": ["desk@sim.local"],
    "use_tls": True,
}
for portfolio in sorted(p for p in (root / "portfolios").iterdir() if p.is_dir()):
    (portfolio / "email.json").write_text(json.dumps(email, indent=2) + "\n", encoding="utf-8")
    print(f"sim config: {portfolio.name}")
