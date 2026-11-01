"""Import iBus1 Static Data from TfL S3 bucket to populate Trip.block fields.

Downloads schedule data from s3-eu-west-1.amazonaws.com/ibus.data.tfl.gov.uk
and matches iBus journeys to existing Trip objects by route + direction + start time,
setting the block field to the iBus Running_No (running card number).

Data is cached locally in /tmp/ibus/{base_version}/ and only re-downloaded
when a new base version is available (~every 2 weeks).
"""

import io
import logging
import os
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from django.core.management.base import BaseCommand

from bustimes.models import Route, Trip

logger = logging.getLogger(__name__)

S3_BASE = "https://s3-eu-west-1.amazonaws.com/ibus.data.tfl.gov.uk"
CACHE_DIR = Path("/tmp/ibus")


class Command(BaseCommand):
    help = "Import iBus1 block/running card data into Trip.block for London buses"

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-version",
            help="Base version date string e.g. 20261024. If not given, fetches latest.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without saving.",
        )
        parser.add_argument(
            "--garage",
            help="Only process a single garage code (e.g. ML, HY).",
        )
        parser.add_argument(
            "--route",
            help="Only process a single route (e.g. 24, N29).",
        )
        parser.add_argument(
            "--redownload",
            action="store_true",
            help="Force re-download even if cached.",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.single_garage = options.get("garage")
        self.single_route = options.get("route")
        self.redownload = options.get("redownload", False)

        base_version = options.get("base_version")
        if not base_version:
            base_version = self.get_latest_base_version()
        self.base_version = base_version
        self.stdout.write(f"Using base version: {base_version}")

        # Set up cache directory
        self.cache_path = CACHE_DIR / base_version
        self.cache_path.mkdir(parents=True, exist_ok=True)

        # Step 1: Build line lookup (Contract_Line_No -> Service_Line_No)
        self.stdout.write("Loading Line data...")
        self.line_lookup = self.load_lines()
        self.stdout.write(f"  {len(self.line_lookup)} lines loaded")

        # Step 2: Load all pattern data (pattern_idx -> route info)
        self.stdout.write("Loading Pattern data...")
        self.pattern_lookup = self.load_patterns()
        self.stdout.write(f"  {len(self.pattern_lookup)} patterns loaded")

        # Step 3: Get garage list
        garages = self.get_garages()
        if self.single_garage:
            garages = [g for g in garages if g == self.single_garage]
        self.stdout.write(f"Processing {len(garages)} garages: {', '.join(garages)}")

        # Step 4: Process each garage
        total_matched = 0
        total_unmatched = 0
        total_updated = 0
        for garage_code in garages:
            matched, unmatched, updated = self.process_garage(garage_code)
            total_matched += matched
            total_unmatched += unmatched
            total_updated += updated

        action = "Would update" if self.dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{action} {total_updated} trips with block data. "
                f"{total_matched} journeys matched, "
                f"{total_unmatched} could not be matched."
            )
        )

    def get_latest_base_version(self):
        """Fetch Base_Version.xml to get the current base version."""
        url = f"{S3_BASE}/Base_Version.xml"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        bv = root.find("Base_Version")
        if bv is None:
            bv = root
        return bv.text.strip()

    def cached_download(self, url, filename):
        """Download a file, caching it locally."""
        cache_file = self.cache_path / filename
        if cache_file.exists() and not self.redownload:
            return cache_file.read_bytes()

        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        cache_file.write_bytes(resp.content)
        return resp.content

    def load_lines(self):
        """Load Line data: maps Contract_Line_No -> Service_Line_No."""
        url = f"{S3_BASE}/Base_Version_{self.base_version}/Line_{self.base_version}.zip"
        data = self.cached_download(url, f"Line_{self.base_version}.zip")
        z = zipfile.ZipFile(io.BytesIO(data))
        xml_data = z.read(f"Line_{self.base_version}.xml")
        root = ET.fromstring(xml_data)

        lookup = {}
        for line in root.findall("Line"):
            contract_no = line.get("aContract_Line_No")
            service_no = line.find("Service_Line_No")
            if contract_no and service_no is not None:
                lookup[contract_no] = service_no.text
        return lookup

    def load_patterns(self):
        """Load Pattern data for all routes.

        Returns {pattern_idx: (service_line_no, direction)}.
        """
        # List available pattern files from S3
        url = (
            f"{S3_BASE}/?prefix=Base_Version_{self.base_version}/Pattern_data_"
            f"&delimiter=/"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        # S3 uses default namespace
        s3ns = "http://s3.amazonaws.com/doc/2006-03-01/"
        keys = []
        for content in root.iter(f"{{{s3ns}}}Key"):
            key = content.text
            if key.endswith(".zip"):
                keys.append(key)

        self.stdout.write(f"  Found {len(keys)} pattern files to download")

        lookup = {}
        for i, key in enumerate(keys):
            # Extract route from filename: Pattern_data_24_20261024.zip -> 24
            fname = key.split("/")[-1]
            route_part = fname.replace("Pattern_data_", "").replace(
                f"_{self.base_version}.zip", ""
            )

            if self.single_route and route_part != self.single_route:
                continue

            # Get the Service_Line_No for this contract line
            service_line = self.line_lookup.get(route_part, route_part)

            try:
                pattern_url = f"{S3_BASE}/{key}"
                data = self.cached_download(pattern_url, fname)
                z = zipfile.ZipFile(io.BytesIO(data))
                xml_name = f"Pattern_{route_part}_{self.base_version}.xml"
                xml_data = z.read(xml_name)
                proot = ET.fromstring(xml_data)

                for pattern in proot.findall("Pattern"):
                    idx = pattern.get("aPattern_Idx")
                    direction = pattern.find("Direction")
                    if idx and direction is not None:
                        lookup[idx] = (service_line, direction.text)
            except Exception as e:
                logger.warning(f"Error loading pattern {route_part}: {e}")

            if (i + 1) % 100 == 0:
                self.stdout.write(f"  Loaded {i + 1}/{len(keys)} pattern files...")

        return lookup

    def get_garages(self):
        """Get list of garage codes from S3 bucket."""
        url = (
            f"{S3_BASE}/?prefix=Base_Version_{self.base_version}/&delimiter=/"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        s3ns = "http://s3.amazonaws.com/doc/2006-03-01/"
        garages = []
        for prefix in root.iter(f"{{{s3ns}}}Prefix"):
            text = prefix.text
            if text:
                parts = text.strip("/").split("/")
                if len(parts) == 2:
                    code = parts[1]
                    if len(code) <= 3 and code.isalpha():
                        garages.append(code)

        return sorted(garages)

    def process_garage(self, garage_code):
        """Process a single garage's schedule data."""
        self.stdout.write(f"\nProcessing garage {garage_code}...")

        url = (
            f"{S3_BASE}/Base_Version_{self.base_version}/"
            f"{garage_code}/schedule_{garage_code}_{self.base_version}.zip"
        )
        try:
            data = self.cached_download(
                url, f"schedule_{garage_code}_{self.base_version}.zip"
            )
            z = zipfile.ZipFile(io.BytesIO(data))
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"  Could not download {garage_code}: {e}")
            )
            return 0, 0, 0

        # Load blocks: block_idx -> Running_No
        blocks = {}
        block_files = [
            n for n in z.namelist()
            if n.startswith(f"Block_{garage_code}") and "Calendar" not in n
        ]
        if block_files:
            xml_data = z.read(block_files[0])
            if len(xml_data) > 100:
                root = ET.fromstring(xml_data)
                for block in root.findall("Block"):
                    idx = block.get("aBlock_Idx")
                    block_no = block.find("Block_No")
                    if idx and block_no is not None and block_no.text:
                        blocks[idx] = block_no.text

        if not blocks:
            self.stdout.write(f"  No block data for {garage_code}")
            return 0, 0, 0

        self.stdout.write(f"  {len(blocks)} blocks loaded")

        # Load journeys
        journey_files = [
            n for n in z.namelist()
            if n.startswith(f"Journey_{garage_code}")
        ]
        if not journey_files:
            return 0, 0, 0

        xml_data = z.read(journey_files[0])
        if len(xml_data) < 100:
            return 0, 0, 0

        jroot = ET.fromstring(xml_data)

        # Group journeys by route for efficient DB querying
        route_journeys = {}
        for journey in jroot.findall("Journey"):
            pattern_idx = journey.get("aPattern_Idx")
            block_idx = journey.get("aBlock_Idx")

            if pattern_idx not in self.pattern_lookup:
                continue
            if block_idx not in blocks:
                continue

            service_line, direction = self.pattern_lookup[pattern_idx]
            running_no = blocks[block_idx]
            start_el = journey.find("Start_Time")
            type_el = journey.find("Type")

            if start_el is None or not start_el.text:
                continue

            # Skip dead runs (Type 4)
            if type_el is not None and type_el.text == "4":
                continue

            start_secs = int(start_el.text)

            if service_line not in route_journeys:
                route_journeys[service_line] = []
            route_journeys[service_line].append(
                (start_secs, direction, running_no)
            )

        self.stdout.write(
            f"  {sum(len(v) for v in route_journeys.values())} journeys "
            f"across {len(route_journeys)} routes"
        )

        # Match to existing trips
        matched = 0
        unmatched = 0
        trips_to_update = []

        for service_line, journeys in route_journeys.items():
            if self.single_route and service_line != self.single_route:
                continue

            # Find routes for this line in the London data source (source_id=7)
            routes = Route.objects.filter(
                source_id=7,
                service__line_name__iexact=service_line,
            )

            if not routes.exists():
                unmatched += len(journeys)
                continue

            # Get all trips for these routes
            route_ids = list(routes.values_list("id", flat=True))
            trips = Trip.objects.filter(route_id__in=route_ids).only(
                "id", "start", "inbound", "block", "route_id"
            )

            # Build lookup: (start_seconds, inbound) -> [trips]
            trip_lookup = {}
            for trip in trips:
                start_secs = int(trip.start.total_seconds())
                key = (start_secs, trip.inbound)
                if key not in trip_lookup:
                    trip_lookup[key] = []
                trip_lookup[key].append(trip)

            for start_secs, direction, running_no in journeys:
                # iBus Direction 1 = outbound (inbound=False)
                # iBus Direction 2 = inbound (inbound=True)
                inbound = direction == "2"

                matching_trips = trip_lookup.get((start_secs, inbound), [])

                if not matching_trips:
                    # Try opposite direction
                    matching_trips = trip_lookup.get(
                        (start_secs, not inbound), []
                    )

                if not matching_trips:
                    # Try 60-second tolerance either way
                    for offset in (-60, 60, -120, 120):
                        matching_trips = trip_lookup.get(
                            (start_secs + offset, inbound), []
                        )
                        if matching_trips:
                            break
                        matching_trips = trip_lookup.get(
                            (start_secs + offset, not inbound), []
                        )
                        if matching_trips:
                            break

                if matching_trips:
                    for trip in matching_trips:
                        if trip.block != running_no:
                            trip.block = running_no
                            trips_to_update.append(trip)
                    matched += 1
                else:
                    unmatched += 1

        updated = len(trips_to_update)
        if trips_to_update and not self.dry_run:
            Trip.objects.bulk_update(
                trips_to_update, ["block"], batch_size=1000
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Updated {updated} trips for {garage_code}"
                )
            )
        elif trips_to_update:
            self.stdout.write(
                f"  Would update {updated} trips for {garage_code}"
            )
        else:
            self.stdout.write(f"  No trips to update for {garage_code}")

        return matched, unmatched, updated
