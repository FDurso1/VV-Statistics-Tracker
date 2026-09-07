
# Shared W-L(-D) parsing and scoring logic.

def parse_wld(raw: str) -> tuple[int, int, int]:
    """Parse 'W-L' or 'W-L-D' into (wins, losses, draws)"""
    
    parts = str(raw).strip().split("-")
    if len(parts) == 2:
        w, l = int(parts[0]), int(parts[1])
        d = 0
    elif len(parts) == 3:
        w, l, d = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        raise ValueError(
            f"'{raw}' is not a valid score -- expected 'W-L' or 'W-L-D' "
            f"(e.g. '2-1' or '1-1-1')."
        )
    return w, l, d

def win_equivalent(wins: float, draws: float) -> float:
    return wins + 0.5 * draws

def loss_equivalent(losses: float, draws: float) -> float:
    return losses + 0.5 * draws

def round_outcome(result: str) -> str:

    result = str(result).strip()
    if result.lower() == "bye":
        return "win"
    w, l, _d = parse_wld(result)
    if w > l:
        return "win"
    elif w < l:
        return "loss"
    else:
        return "draw"
