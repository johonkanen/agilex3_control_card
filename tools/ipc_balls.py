import sys, re, csv, collections
path, ref, out = sys.argv[1], sys.argv[2], sys.argv[3]
names = {}; rows = []
for line in open(path, encoding='latin-1'):
    if line.startswith('P  NNAME'):
        k, v = line[3:].split(None, 1); names[k] = v.strip()
    elif line.startswith('317') or line.startswith('327'):
        net = line[3:17].strip(); r = line[20:26].strip(); pin = line[27:31].strip()
        if r == ref:
            rows.append((pin, names.get(net, net)))
rows.sort(key=lambda x: (re.sub(r'\d','',x[0]), int(re.sub(r'\D','',x[0]) or 0)))
with open(out, 'w', newline='') as f:
    w = csv.writer(f); w.writerow(['ball', 'net']); w.writerows(rows)
c = collections.Counter(n for _, n in rows)
print(len(rows), 'pins'); print(c.most_common(25))
sig = [(p, n) for p, n in rows if c[n] == 1]
print(len(sig), 'single-pin nets:'); print(' '.join(f'{p}={n}' for p, n in sig))
