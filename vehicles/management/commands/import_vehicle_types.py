import requests
from django.core.management.base import BaseCommand
from vehicles.models import VehicleType


class Command(BaseCommand):
    help = 'Import vehicle types from bustimes.org API'

    def handle(self, *args, **options):
        url = 'https://bustimes.org/api/vehicletypes/?limit=100'
        imported = 0
        skipped = 0
        page = 1

        while url:
            self.stdout.write(f'Fetching page {page}...')
            response = requests.get(url, timeout=30)
            data = response.json()

            for item in data['results']:
                if VehicleType.objects.filter(id=item['id']).exists():
                    skipped += 1
                    continue

                VehicleType.objects.create(
                    id=item['id'],
                    name=item.get('name', ''),
                    style=item.get('style', ''),
                    fuel=item.get('fuel', ''),
                )
                imported += 1

            url = data.get('next')
            page += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done! Imported: {imported}, Skipped (already exist): {skipped}'
        ))
