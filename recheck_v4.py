from vehicles.models import Vehicle
import requests, time, sys, json

with open('/tmp/bus_check_v3.json') as f:
    prev = json.load(f)

# Collect all flagged fleet codes with their operators
flagged = set()
for cat in ['reg', 'operator', 'type']:
    for m in prev['mismatches'].get(cat, []):
        fc = m.split(':')[0].split(' ')[0]
        flagged.add(fc)
for m in prev.get('not_found_list', []):
    fc = m.split(' ')[0]
    flagged.add(fc)

london_ops = ['LONC','LGEN','MBGA','ABLO','AVLO','ELBG','MTLN','BTRI','FLON','DLBU','UNOL']

vehicles = {}
for v in Vehicle.objects.filter(fleet_code__in=flagged, operator_id__in=london_ops, withdrawn=False).select_related('operator', 'vehicle_type'):
    vehicles[v.fleet_code + '|' + v.operator_id] = v

total = len(vehicles)
print(f'Rechecking {total} flagged vehicles with operator filter...\n')

mismatches = {'operator': [], 'type': [], 'reg': []}
not_found_list = []
error_list = []
checked = 0
correct = 0
errors = 0
not_found = 0

def normalise_type(t):
    t = t.strip().lower()
    t = t.replace('adl enviro', 'enviro').replace('adl ', '')
    t = ' '.join(t.split())
    return t

for i, (key, v) in enumerate(sorted(vehicles.items())):
    fc = v.fleet_code
    our_reg = (v.reg or '').replace(' ', '').upper()
    our_op = v.operator_id

    try:
        r = requests.get(f'https://bustimes.org/api/vehicles/?operator={our_op}&search={fc}&limit=5', timeout=15)
        if not r.ok:
            errors += 1
            error_list.append(f'{fc} ({our_reg}) op={our_op}: HTTP {r.status_code}')
            continue
        data = r.json()

        bt_vehicle = None
        for bv in data.get('results', []):
            if bv.get('fleet_code') == fc:
                bt_vehicle = bv
                break

        if not bt_vehicle:
            not_found += 1
            not_found_list.append(f'{fc} ({our_reg}) op={our_op}')
            checked += 1
            continue

        all_match = True

        bt_reg = (bt_vehicle.get('reg', '') or '').replace(' ', '').upper()
        if bt_reg and our_reg and bt_reg != our_reg:
            mismatches['reg'].append(f'{fc}: ours={our_reg} bt={bt_reg} op={our_op}')
            all_match = False

        bt_op = bt_vehicle.get('operator', {}).get('id', '')
        if bt_op and bt_op != our_op:
            bt_op_name = bt_vehicle.get('operator', {}).get('name', '')
            mismatches['operator'].append(f'{fc} ({our_reg}): ours={our_op} bt={bt_op} ({bt_op_name})')
            all_match = False

        bt_type = bt_vehicle.get('vehicle_type', {}).get('name', '') if bt_vehicle.get('vehicle_type') else ''
        our_type = v.vehicle_type.name if v.vehicle_type else ''
        if bt_type and our_type and normalise_type(bt_type) != normalise_type(our_type):
            mismatches['type'].append(f'{fc} ({our_reg}): ours={our_type} bt={bt_type}')
            all_match = False

        if all_match:
            correct += 1
        checked += 1

    except Exception as e:
        errors += 1
        error_list.append(f'{fc} ({our_reg}): {str(e)}')

    done = i + 1
    sys.stdout.write(f'\r  {done}/{total} \u2713{correct} \u2717{checked-correct} nf={not_found} err={errors}')
    sys.stdout.flush()
    time.sleep(0.5)

print(f'\n\n=== RECHECK RESULTS ===')
print(f'Checked: {checked}/{total}')
if checked:
    print(f'Correct: {correct} ({correct/checked*100:.1f}%)')
    print(f'Were false positives: {correct}')
print(f'Not found: {not_found} | Errors: {errors}')
print(f'\nNot found ({not_found}):')
for m in not_found_list:
    print(f'  {m}')
print(f'\nErrors ({errors}):')
for m in error_list:
    print(f'  {m}')
print(f'\nReal reg mismatches ({len(mismatches["reg"])}):')
for m in mismatches['reg']:
    print(f'  {m}')
print(f'\nReal operator mismatches ({len(mismatches["operator"])}):')
for m in mismatches['operator']:
    print(f'  {m}')
print(f'\nReal type mismatches ({len(mismatches["type"])}):')
for m in mismatches['type']:
    print(f'  {m}')

with open('/tmp/bus_recheck_v4.json', 'w') as f:
    json.dump({'checked': checked, 'correct': correct, 'errors': errors, 'not_found': not_found, 'not_found_list': not_found_list, 'error_list': error_list, 'mismatches': mismatches}, f, indent=2)
print('\nSaved to /tmp/bus_recheck_v4.json')
