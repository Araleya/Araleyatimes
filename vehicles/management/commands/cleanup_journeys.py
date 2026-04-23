from django.core.management.base import BaseCommand
from vehicles.models import VehicleJourney


class Command(BaseCommand):
    help = "Delete all VehicleJourney records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many would be deleted without deleting anything",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        count = VehicleJourney.objects.count()

        if dry_run:
            self.stdout.write(f"[dry-run] Would delete {count:,} journeys")
            return

        if count == 0:
            self.stdout.write("No journeys to delete.")
            return

        deleted = 0
        while True:
            batch = list(VehicleJourney.objects.order_by("id")[:1000].values_list("id", flat=True))
            if not batch:
                break
            VehicleJourney.objects.filter(id__in=batch).delete()
            deleted += len(batch)
            self.stdout.write(f"Deleted {deleted:,} / {count:,}...")

        self.stdout.write(f"Done. Deleted {deleted:,} journeys.")
