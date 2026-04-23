import requests
from django.core.management.base import BaseCommand
from vehicles.models import Livery


class Command(BaseCommand):
    help = 'Import liveries from bustimes.org API'

    def handle(self, *args, **options):
        url = 'https://bustimes.org/api/liveries/?limit=100'
        imported = 0
        skipped = 0
        page = 1

        while url:
            self.stdout.write(f'Fetching page {page}...')
            response = requests.get(url, timeout=30)
            data = response.json()

            for item in data['results']:
                if Livery.objects.filter(id=item['id']).exists():
                    skipped += 1
                    continue

                Livery.objects.create(
                    id=item['id'],
                    name=item.get('name', ''),
                    colour='',
                    colours='',
                    left_css=item.get('left_css', ''),
                    right_css=item.get('right_css', ''),
                    white_text=item.get('white_text', False),
                    text_colour=item.get('text_colour', ''),
                    stroke_colour=item.get('stroke_colour', ''),
                    horizontal=False,
                    published=True,
                    show_name=True,
                    image_url='',
                )
                imported += 1

            url = data.get('next')
            page += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done! Imported: {imported}, Skipped (already exist): {skipped}'
        ))
