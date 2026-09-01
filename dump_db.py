import os
import django
from django.core.management import call_command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

with open("data.json", "w", encoding="utf-8") as f:
    call_command(
        "dumpdata",
        natural_foreign=True,
        natural_primary=True,
        exclude=["contenttypes", "auth.Permission"],
        indent=2,
        stdout=f,
    )

print("✅ Database exported successfully to data.json")