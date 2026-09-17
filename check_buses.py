from vehicles.models import Vehicle, Livery
import requests, time, sys, re

london_ops = ['LONC','LGEN','MBGA','ABLO','AVLO','ELBG','MTLN','BTRI','FLON','GAHL','DLBU','UNOL','TFLO']

superloop_livery = Livery.objects.filter(name__icontains='superloop').first()
sl_id = superloop_livery.id if superloop_livery else None

def plate_year(reg):
    r = reg.replace(' ', '').upper()
    if len(r) != 7:
        return None
    mid = r[2:4]
    if not mid.isdigit():
        return None
    num = int(mid)
    if num <= 50:
        return 2000 + num
    else:
        return 2000 + num - 50

vehicles = list(Vehicle.objects.filter(operator_id__in=london_ops).select_related('operator', 'vehicle_type', 'livery').order_by('fleet_code'))

filtered = []
for v in vehicles:
    yr = plate_year(v.reg or '')
    if yr and yr >= 2016:
        filtered.append(v)

total = len(filtered)
est_mins = total * 0.5 / 60
print(f'Checking {total} London vehicles (16 plate+) against bustimes.org...')
print(f'(Filtered from {len(vehicles)} total)')
print(f'Estimated time: {est_mins:.0f} minutes\n')

mismatches = {'operator': [], 'type': [], 'fleet': [], 'livery': []}
checked = 0
correct = 0
errors = 0
start_time = time.time()

for i, v in enumerate(filtered):
    fc = v.fleet_code
    if not fc:
        continue

    try:
        r = requests.get(f'https://bustimes.org/api/vehicles/?search={fc}&limit=5', timeout=15)
        if not r.ok:
            errors += 1
            continue
        data = r.json()

        bt_vehicle = None
        for bv in data.get('results', []):
            if bv.get('fleet_code') == fc:
                bt_op = bv.get('operator', {}).get('id', '')
                if bt_op == v.operator_id:
                    bt_vehicle = bv
                    break
        if not bt_vehicle:
            for bv in data.get('results', []):
                if bv.get('fleet_code') == fc:
                    bt_vehicle = bv
                    break

        if not bt_vehicle:
            checked += 1
            continue

        all_match = True

        # 1. Fleet number
        bt_fleet = bt_vehicle.get('fleet_code', '')
        if bt_fleet and fc and bt_fleet != fc:
            mismatches['fleet'].append(f'{fc}: ours={fc} bt={bt_fleet}')
            all_match = False

        # 2. Operator
        bt_op = bt_vehicle.get('operator', {}).get('id', '')
        if bt_op and bt_op != v.operator_id:
            mismatches['operator'].append(f'{fc}: ours={v.operator_id} bt={bt_op}')
            all_match = False

        # 3. Vehicle type
        bt_type = bt_vehicle.get('vehicle_type', {}).get('name', '') if bt_vehicle.get('vehicle_type') else ''
        our_type = v.vehicle_type.name if v.vehicle_type else ''
        if bt_type and our_type and bt_type != our_type:
            mismatches['type'].append(f'{fc}: ours={our_type} bt={bt_type}')
            all_match = False

        # 4. Superloop livery
        bt_livery = bt_vehicle.get('livery', {})
        bt_livery_name = bt_livery.get('name', '') if isinstance(bt_livery, dict) else ''
        our_is_superloop = v.livery_id == sl_id if sl_id else False
        bt_is_superloop = 'superloop' in bt_livery_name.lower() if bt_livery_name else False
        if our_is_superloop != bt_is_superloop:
            mismatches['livery'].append(f'{fc}: ours_sl={our_is_superloop} bt_sl={bt_is_superloop} bt_livery={bt_livery_name}')
            all_match = False

        if all_match:
            correct += 1
        checked += 1

    except Exception as e:
        errors += 1

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
        eta = 'calculating...'

    sys.stdout.write(f'\r  [{bar}] {done}/{total} ({pct:.1f}%) \u2713{correct} \u2717{checked-correct} err={errors} | {eta}  ')
    sys.stdout.flush()

    if done % 250 == 0 and checked > 0:
        acc = correct / checked * 100
        sys.stdout.write(f'\n  \u2500\u2500 {done}: {correct}/{checked} accurate ({acc:.1f}%) | fleet={len(mismatches["fleet"])} op={len(mismatches["operator"])} type={len(mismatches["type"])} livery={len(mismatches["livery"])}\n')
        sys.stdout.flush()

    time.sleep(0.5)

elapsed = time.time() - start_time
print(f'\n\n=== FINAL RESULTS === (took {elapsed/60:.1f} minutes)')
print(f'Checked: {checked}/{total}')
if checked:
    print(f'Correct: {correct} ({correct/checked*100:.1f}%)')
print(f'Errors: {errors}')
print(f'\nFleet mismatches ({len(mismatches["fleet"])}):')
for m in mismatches['fleet'][:30]:
    print(f'  {m}')
print(f'\nOperator mismatches ({len(mismatches["operator"])}):')
for m in mismatches['operator'][:30]:
    print(f'  {m}')
print(f'\nType mismatches ({len(mismatches["type"])}):')
for m in mismatches['type'][:30]:
    print(f'  {m}')
print(f'\nLivery mismatches ({len(mismatches["livery"])}):')
for m in mismatches['livery'][:30]:
    print(f'  {m}')

import json
with open('/tmp/bus_check_results.json', 'w') as f:
    json.dump({'checked': checked, 'correct': correct, 'errors': errors, 'mismatches': mismatches}, f, indent=2)
print('\nFull results saved to /tmp/bus_check_results.json')
