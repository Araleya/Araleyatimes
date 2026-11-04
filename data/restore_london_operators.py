"""
Restore London bus operator mappings from backup CSV.
Run after TNDS import with: python manage.py shell < data/restore_london_operators.py
"""
import csv
from busstops.models import Service, Operator

with open('data/london_service_operators_backup.csv') as f:
    reader = csv.DictReader(f)
    fixed = 0
    unchanged = 0
    missing = 0
    for row in reader:
        # Try exact service_code match first
        svcs = Service.objects.filter(service_code=row['service_code'])
        if not svcs.exists():
            # Fall back to line_name in London region
            svcs = Service.objects.filter(line_name=row['line_name'], region='L')
        if not svcs.exists():
            missing += 1
            print(f'MISSING {row["line_name"]} ({row["service_code"]})')
            continue

        backup_nocs = set(row['operators'].split(','))
        for svc in svcs:
            current_nocs = set(svc.operator.values_list('noc', flat=True))
            if current_nocs != backup_nocs:
                ops = list(Operator.objects.filter(noc__in=backup_nocs))
                if len(ops) == len(backup_nocs):
                    svc.operator.set(ops)
                    fixed += 1
                else:
                    found = {o.noc for o in ops}
                    print(f'SKIP {svc.line_name}: missing operators {backup_nocs - found}')
            else:
                unchanged += 1

print(f'\nDone: {fixed} fixed, {unchanged} unchanged, {missing} not found')
