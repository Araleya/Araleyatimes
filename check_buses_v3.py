from vehicles.models import Vehicle
import requests, time, sys, json

london_ops = ['LONC','LGEN','MBGA','ABLO','AVLO','ELBG','MTLN','BTRI','FLON','DLBU','UNOL']
london_ops_plus = london_ops + ['GAHL','TFLO']

vehicles = list(Vehicle.objects.filter(operator_id__in=london_ops, withdrawn=False).select_related('operator', 'vehicle_type').order_by('operator_id', 'fleet_code'))

total = len(vehicles)
print(f'Checking {total} London vehicles against bustimes.org...')
print(f'Rate: 0.3s per request')
print(f'Estimated time: {total * 0.3 / 60:.0f} minutes\n')

mismatches = {'operator': [], 'type': [], 'reg': []}
not_found_list = []
error_list = []
checked = 0
correct = 0
errors = 0
not_found = 0
start_time = time.time()

def normalise_type(t):
    t = t.strip().lower()
    t = t.replace('adl enviro', 'enviro').replace('adl ', '')
    t = ' '.join(t.split())
    return t

for i, v in enumerate(vehicles):
    fc = v.fleet_code
    our_reg = (v.reg or '').replace(' ', '').upper()
    if not fc:
        continue

    try:
        r = requests.get(f'https://bustimes.org/api/vehicles/?search={fc}&limit=10', timeout=15)
        if not r.ok:
            errors += 1
            error_list.append(f'{fc} ({our_reg}): HTTP {r.status_code}')
            continue
        data = r.json()

        bt_vehicle = None
        for bv in data.get('results', []):
            if bv.get('fleet_code') != fc:
                continue
            bt_reg = (bv.get('reg', '') or '').replace(' ', '').upper()
            bt_op = bv.get('operator', {}).get('id', '')
            if our_reg and bt_reg == our_reg:
                bt_vehicle = bv
                break
            if bt_op in london_ops_plus and not bt_vehicle:
                bt_vehicle = bv

        if not bt_vehicle:
            not_found += 1
            not_found_list.append(f'{fc} ({our_reg}) op={v.operator_id}')
            checked += 1
            continue

        all_match = True

        bt_op = bt_vehicle.get('operator', {}).get('id', '')
        if bt_op and bt_op != v.operator_id and bt_op not in ['GAHL','TFLO']:
            bt_op_name = bt_vehicle.get('operator', {}).get('name', '')
            mismatches['operator'].append(f'{fc} ({our_reg}): ours={v.operator_id} bt={bt_op} ({bt_op_name})')
            all_match = False

        bt_reg = (bt_vehicle.get('reg', '') or '').replace(' ', '').upper()
        if bt_reg and our_reg and bt_reg != our_reg:
            mismatches['reg'].append(f'{fc}: ours={our_reg} bt={bt_reg} op={v.operator_id}')
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
    pct = done / total * 100
    bar_len = 40
    filled = int(bar_len * done / total)
    bar = '\u2588' * filled + '\u2591' * (bar_len - filled)
    elapsed = time.time() - start_time
    if done > 5:
        rate = done / elapsed
        remaining = (total - done) / rate
        mins_left = int(remaining // 60)
        secs_left = int(remaining % 60)
        eta = f'ETA {mins_left}m{secs_left:02d}s'
    else:
        eta = '...'
    sys.stdout.write(f'\r  [{bar}] {done}/{total} ({pct:.1f}%) \u2713{correct} \u2717{checked-correct} nf={not_found} err={errors} | {eta}  ')
    sys.stdout.flush()
    if done % 250 == 0 and checked > 0:
        acc = correct / checked * 100
        sys.stdout.write(f'\n  \u2500\u2500 {done}: {correct}/{checked} ({acc:.1f}%) | reg={len(mismatches["reg"])} op={len(mismatches["operator"])} type={len(mismatches["type"])} nf={not_found}\n')
        sys.stdout.flush()
    time.sleep(0.3)

elapsed = time.time() - start_time
print(f'\n\n=== FINAL RESULTS === (took {elapsed/60:.1f} minutes)')
print(f'Checked: {checked}/{total}')
if checked:
    print(f'Correct: {correct} ({correct/checked*100:.1f}%)')
print(f'Not found: {not_found} | Errors: {errors}')
print(f'\nNot found on bustimes ({not_found}):')
for m in not_found_list:
    print(f'  {m}')
print(f'\nErrors ({errors}):')
for m in error_list:
    print(f'  {m}')
print(f'\nReg mismatches ({len(mismatches["reg"])}):')
for m in mismatches['reg']:
    print(f'  {m}')
print(f'\nOperator mismatches ({len(mismatches["operator"])}):')
for m in mismatches['operator']:
    print(f'  {m}')
print(f'\nType mismatches ({len(mismatches["type"])}):')
for m in mismatches['type']:
    print(f'  {m}')

with open('/tmp/bus_check_v3.json', 'w') as f:
    json.dump({'checked': checked, 'correct': correct, 'errors': errors, 'not_found': not_found, 'not_found_list': not_found_list, 'error_list': error_list, 'mismatches': mismatches}, f, indent=2)
print('\nSaved to /tmp/bus_check_v3.json')
