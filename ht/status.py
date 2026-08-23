import os, sqlite3
DATA = os.environ.get("HT_DATA_ROOT", r"C:\Users\maram\ht_data")
c = sqlite3.connect(os.path.join(DATA, "ledger.db"))
st = dict(c.execute("SELECT state, COUNT(*) FROM slots GROUP BY state").fetchall())
r = c.execute("SELECT COUNT(*), SUM(parquet_bytes), SUM(orders), AVG(parquet_bytes), SUM(lz4_bytes) FROM slots WHERE state='done'").fetchone()
tot = sum(st.values())
done, pq_b, orders, avg, lz4_b = r[0], r[1] or 0, r[2] or 0, r[3] or 0, r[4] or 0
left = st.get("pending", 0) + st.get("deferred", 0)
print(f"etats      : {st}")
print(f"progression: {done}/{tot}  ({100*done/max(tot,1):.2f}%)  restant {left}")
print(f"volume     : {pq_b/1e9:.3f} Go parquet  (lz4 equivalent {lz4_b/1e9:.2f} Go, ratio {lz4_b/max(pq_b,1):.2f}x)")
print(f"moyenne    : {avg/1e6:.2f} Mo/snapshot -> projection totale {avg*tot/1e9:.1f} Go")
print(f"ordres     : {orders:,}")
q = c.execute("SELECT slot, error FROM slots WHERE state IN ('quarantine','absent') LIMIT 5").fetchall()
if q:
    print("anomalies  :")
    for s, e in q:
        print(f"   {s}  {(e or '')[:90]}")
