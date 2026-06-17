"""
Demo seeder — stage changes so the next `python monitor.py` run shows a full
summary on demand, without waiting for real price moves.

It edits the last snapshot (data/snapshot.json): drops one price, bumps another,
and flips one product out of stock. The next real run diffs against these staged
values and prints PRICE DROP / PRICE INCREASE / OUT OF STOCK lines.

    python monitor.py        # build a baseline first (run once)
    python seed_demo.py      # stage changes into the snapshot
    python monitor.py        # the run shows the staged alerts
    python seed_demo.py --reset   # delete the snapshot, start clean

Not part of the monitor. Demo only.
"""

import json
import sys
from pathlib import Path

SNAPSHOT = Path("data/snapshot.json")


def main() -> None:
    if "--reset" in sys.argv:
        SNAPSHOT.unlink(missing_ok=True)
        print("Snapshot deleted. Run `python monitor.py` to rebuild a baseline.")
        return

    if not SNAPSHOT.exists():
        sys.exit("No snapshot yet. Run `python monitor.py` once first.")

    data = json.loads(SNAPSHOT.read_text())
    products = list(data.get("products", {}).items())
    if len(products) < 2:
        sys.exit("Need at least 2 products in the snapshot to stage a demo.")

    # Drop the first product's price 20% so the next run reads as a recovery (price increase),
    # and flip the second out of stock so the next run reads as back-in-stock-then-OOS demo.
    (_, p0), (_, p1) = products[0], products[1]
    if p0.get("price"):
        p0["price"] = round(p0["price"] * 0.8, 2)
    p1["in_stock"] = False

    SNAPSHOT.write_text(json.dumps(data, indent=2))
    print("Staged demo changes into the snapshot:")
    print(f"  {p0['name']}: price set to {p0.get('price')} (next run shows a move vs. live)")
    print(f"  {p1['name']}: marked out of stock (next run shows the transition)")
    print("\nNow run: python monitor.py")


if __name__ == "__main__":
    main()
