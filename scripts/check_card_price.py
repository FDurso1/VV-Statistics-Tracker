
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.scryfall import cheapest_vintage_legal_prices

def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/check_card_price.py "Card Name" ["Another Card" ...]')
        sys.exit(1)

    names = sys.argv[1:]
    print(f"Checking Scryfall for {len(names)} card(s)... ")

    prices = cheapest_vintage_legal_prices(set(names))

    print()
    for name in names:
        price = prices.get(name)
        if price is None:
            print(f"  {name}: no Vintage-legal printing with a price found")
        else:
            print(f"  {name}: ${price:.2f}")

if __name__ == "__main__":
    main()
