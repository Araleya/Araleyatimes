from django.db import connection, connections
import time
import re
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from vehicles.models import Vehicle


def format_reg(reg):
    reg = reg.strip().upper()
    match = re.match(r'^([A-Z]{2}\d{2}[A-Z]{3})$', reg)
    if match:
        return reg[:4] + ' ' + reg[4:]
    match = re.match(r'^([A-Z]{1,3})(\d{1,4})([A-Z]{1,3})$', reg)
    if match:
        return match.group(1) + match.group(2) + ' ' + match.group(3)
    return reg


def get_embed(slug):
    try:
        vehicle = Vehicle.objects.using('default').select_related('operator').get(slug=slug)
        operator_name = vehicle.operator.name if vehicle.operator else "Unknown Operator"
        parts = []
        if vehicle.fleet_number:
            parts.append(str(vehicle.fleet_number))
        if vehicle.reg:
            parts.append(format_reg(vehicle.reg))
        title = ' - '.join(parts) if parts else slug.upper()
    except Exception:
        operator_name = "Unknown"
        title = slug.upper()

    return {
        "title": title,
        "url": f"https://araleyatimes.net/vehicles/{slug}",
        "description": operator_name,
        "color": 0xFF69B4,
    }


def get_content(slug):
    return f"[{slug}](https://araleyatimes.net/vehicles/{slug})"


class Command(BaseCommand):
    def handle(self, *args, **options):
        assert settings.NEW_VEHICLE_WEBHOOK_URL, "NEW_VEHICLE_WEBHOOK_URL is not set"
        session = requests.Session()

        listen_conn = connections.create_connection('default')

        with listen_conn.cursor() as cursor:
            cursor.execute("""CREATE OR REPLACE FUNCTION notify_new_vehicle()
                           RETURNS trigger AS $$
                           BEGIN
                           PERFORM pg_notify('new_vehicle', NEW.slug);
                           RETURN NEW;
                           END;
                           $$ LANGUAGE plpgsql;""")
            cursor.execute("""CREATE OR REPLACE TRIGGER notify_new_vehicle
                           AFTER INSERT ON vehicles_vehicle
                           FOR EACH ROW
                           EXECUTE PROCEDURE notify_new_vehicle();""")
            cursor.execute("LISTEN new_vehicle")
            gen = cursor.connection.notifies()
            for notify in gen:
                print(notify)
                try:
                    embed = get_embed(notify.payload)
                    response = session.post(
                        settings.NEW_VEHICLE_WEBHOOK_URL,
                        json={
                            "content": get_content(notify.payload),
                            "embeds": [embed],
                        },
                        timeout=10,
                    )
                    print(f"Status: {response.status_code}")
                    print(f"Response: {response.text}")
                except Exception as e:
                    print(f"Error: {e}")
                time.sleep(5)
