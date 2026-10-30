"""Community chess for the profile README: visitors play White, my engine plays Black.

A visitor clicks a move link in the README, which opens a pre-filled issue titled
    chess|move|<uci>|<ply>
The `chess` workflow runs this script, which validates the move, lets the engine
reply, then re-renders the board SVG and the README section.

    python scripts/chess_game.py move e2e4 0 <github-login>
    python scripts/chess_game.py new <github-login>
    python scripts/chess_game.py render

Exit codes: 0 = state changed (commit it), 2 = move rejected (just reply).
The text to post back on the issue is written to $REPLY_FILE (or stdout).
"""

import json
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import chess
import chess.svg

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "chess" / "state.json"
SQUARES = ROOT / "assets" / "chess" / "sq"
TILE = 52          # drawing size of one square tile
TILE_SHOWN = 34    # display size: 8 x 34 = 272px still fits a 360px-wide phone
README = ROOT / "README.md"
REPO = os.environ.get("GITHUB_REPOSITORY", "MuhammadMaheem/MuhammadMaheem")
START, END = "<!-- CHESS:START -->", "<!-- CHESS:END -->"

# ---------------------------------------------------------------- engine ----

VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
          chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}

# Piece-square tables from White's point of view, rank 8 first
# (Tomasz Michniewski's "Simplified Evaluation Function").
PST = {
    chess.PAWN: [
        0, 0, 0, 0, 0, 0, 0, 0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
        5, 5, 10, 25, 25, 10, 5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, -5, -10, 0, 0, -10, -5, 5,
        5, 10, 10, -20, -20, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0],
    chess.KNIGHT: [
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20, 0, 0, 0, 0, -20, -40,
        -30, 0, 10, 15, 15, 10, 0, -30,
        -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30,
        -30, 5, 10, 15, 15, 10, 5, -30,
        -40, -20, 0, 5, 5, 0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50],
    chess.BISHOP: [
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 10, 10, 5, 0, -10,
        -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 10, 10, 10, 10, 0, -10,
        -10, 10, 10, 10, 10, 10, 10, -10,
        -10, 5, 0, 0, 0, 0, 5, -10,
        -20, -10, -10, -10, -10, -10, -10, -20],
    chess.ROOK: [
        0, 0, 0, 0, 0, 0, 0, 0,
        5, 10, 10, 10, 10, 10, 10, 5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        0, 0, 0, 5, 5, 0, 0, 0],
    chess.QUEEN: [
        -20, -10, -10, -5, -5, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 5, 5, 5, 0, -10,
        -5, 0, 5, 5, 5, 5, 0, -5,
        0, 0, 5, 5, 5, 5, 0, -5,
        -10, 5, 5, 5, 5, 5, 0, -10,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -20, -10, -10, -5, -5, -10, -10, -20],
    chess.KING: [
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -20, -30, -30, -40, -40, -30, -30, -20,
        -10, -20, -20, -20, -20, -20, -20, -10,
        20, 20, 0, 0, 0, 0, 20, 20,
        20, 30, 10, 0, 0, 10, 30, 20],
}

MATE = 100_000


def evaluate(board: chess.Board) -> int:
    """Static score in centipawns from the side to move's point of view."""
    score = 0
    for sq, piece in board.piece_map().items():
        idx = chess.square_mirror(sq) if piece.color == chess.WHITE else sq
        v = VALUES[piece.piece_type] + PST[piece.piece_type][idx]
        score += v if piece.color == chess.WHITE else -v
    return score if board.turn == chess.WHITE else -score


def ordered(board: chess.Board, captures_only: bool = False) -> list[chess.Move]:
    def key(m: chess.Move) -> int:
        k = 0
        if board.is_capture(m):
            victim = board.piece_type_at(m.to_square) or chess.PAWN  # en passant
            k += 10 * VALUES[victim] - VALUES[board.piece_type_at(m.from_square)]
        if m.promotion:
            k += VALUES[m.promotion]
        return -k
    moves = board.generate_legal_captures() if captures_only else board.legal_moves
    return sorted(moves, key=key)


def quiesce(board: chess.Board, alpha: int, beta: int, depth: int = 4) -> int:
    stand = evaluate(board)
    if stand >= beta or depth == 0:
        return stand
    alpha = max(alpha, stand)
    for m in ordered(board, captures_only=True):
        board.push(m)
        score = -quiesce(board, -beta, -alpha, depth - 1)
        board.pop()
        if score >= beta:
            return score
        alpha = max(alpha, score)
    return alpha


def negamax(board: chess.Board, depth: int, alpha: int, beta: int, ply: int) -> int:
    if board.is_checkmate():
        return -MATE + ply
    if board.is_stalemate() or board.is_insufficient_material() or board.is_repetition(2):
        return 0
    if depth == 0:
        return quiesce(board, alpha, beta)
    best = -MATE
    for m in ordered(board):
        board.push(m)
        score = -negamax(board, depth - 1, -beta, -alpha, ply + 1)
        board.pop()
        best = max(best, score)
        alpha = max(alpha, score)
        if alpha >= beta:
            break
    return best


def engine_move(board: chess.Board, depth: int = 3, budget: float = 25.0) -> chess.Move:
    """Iterative deepening; picks randomly among near-equal root moves for variety."""
    deadline = time.monotonic() + budget
    choice = next(iter(board.legal_moves))
    for d in range(1, depth + 1):
        scored = []
        for m in ordered(board):
            board.push(m)
            scored.append((-negamax(board, d - 1, -MATE, MATE, 1), m))
            board.pop()
            if time.monotonic() > deadline:
                break
        else:
            top = max(s for s, _ in scored)
            choice = random.choice([m for s, m in scored if s >= top - 15])
            continue
        break  # ran out of time mid-depth: keep the last complete result
    return choice

# ----------------------------------------------------------------- state ----


def load() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"game": 1, "moves": [], "players": {}, "results": {"humans": 0, "engine": 0, "draws": 0},
            "last": None, "finished": None}


def save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + "\n")


def board_of(state: dict) -> chess.Board:
    board = chess.Board()
    for m in state["moves"]:
        board.push_uci(m["uci"])
    return board


def outcome_text(board: chess.Board) -> tuple[str, str] | None:
    """(bucket, sentence) if the game is over."""
    o = board.outcome(claim_draw=True)
    if o is None:
        return None
    if o.winner is chess.WHITE:
        return "humans", "♔ **Checkmate — the humans win!** The engine has been defeated."
    if o.winner is chess.BLACK:
        return "engine", "♚ **Checkmate — the engine wins.** Better luck next game."
    return "draws", f"🤝 **Draw** ({o.termination.name.replace('_', ' ').lower()})."

# ---------------------------------------------------------------- render ----


def issue_link(title: str) -> str:
    body = "Just press **Submit new issue** — no need to write anything. The engine replies in about a minute."
    return f"https://github.com/{REPO}/issues/new?title={quote(title)}&body={quote(body)}"


PIECE_NAMES = {chess.PAWN: "♙ Pawn", chess.KNIGHT: "♘ Knight", chess.BISHOP: "♗ Bishop",
               chess.ROOK: "♖ Rook", chess.QUEEN: "♕ Queen", chess.KING: "♔ King"}


def tile(board: chess.Board, sq: int, last: chess.Move | None, movable: bool) -> str:
    """One board square as a standalone SVG, so every square can carry its own link."""
    light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
    highlighted = last is not None and sq in (last.from_square, last.to_square)
    fill = ("#c3d888" if light else "#92b166") if highlighted else ("#dee3e6" if light else "#8ca2ad")
    ink = "#8ca2ad" if light else "#dee3e6"
    parts = [f'<rect width="{TILE}" height="{TILE}" fill="{fill}"/>']
    piece = board.piece_at(sq)
    if piece and piece.piece_type == chess.KING and board.is_check() and piece.color == board.turn:
        parts.append('<radialGradient id="c"><stop offset="0" stop-color="#ff0000"/>'
                     '<stop offset="1" stop-color="#ff0000" stop-opacity="0"/></radialGradient>'
                     f'<rect width="{TILE}" height="{TILE}" fill="url(#c)"/>')
    if chess.square_file(sq) == 0:
        parts.append(f'<text x="3" y="11" font-size="10" font-family="sans-serif" font-weight="700" fill="{ink}">'
                     f'{chess.square_rank(sq) + 1}</text>')
    if chess.square_rank(sq) == 0:
        parts.append(f'<text x="{TILE - 3}" y="{TILE - 3}" text-anchor="end" font-size="10" font-family="sans-serif" '
                     f'font-weight="700" fill="{ink}">{chess.FILE_NAMES[chess.square_file(sq)]}</text>')
    if piece:
        off = (TILE - 45) / 2
        parts.append(chess.svg.piece(piece).replace("<svg ", f'<svg x="{off}" y="{off}" ', 1))
    if movable:
        parts.append(f'<circle cx="{TILE - 7}" cy="7" r="4" fill="#3fb950" stroke="#ffffff" stroke-width="1.2"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {TILE} {TILE}" width="{TILE}" height="{TILE}">{"".join(parts)}</svg>')


def render(state: dict) -> None:
    board = board_of(state)
    last = board.peek() if board.move_stack else None
    over = outcome_text(board)
    ply = len(state["moves"])

    moves_from: dict[int, list[chess.Move]] = {}
    if not over:
        for m in board.legal_moves:
            if m.promotion and m.promotion != chess.QUEEN:
                continue
            moves_from.setdefault(m.from_square, []).append(m)

    SQUARES.mkdir(parents=True, exist_ok=True)
    rows = []
    for rank in range(7, -1, -1):
        cells = []
        for file in range(8):
            sq = chess.square(file, rank)
            name = chess.square_name(sq)
            (SQUARES / f"{name}.svg").write_text(tile(board, sq, last, sq in moves_from))
            piece = board.piece_at(sq)
            alt = f"{name} {chess.COLOR_NAMES[piece.color]} {chess.piece_name(piece.piece_type)}" if piece else name
            href = f"#pick-{name}" if sq in moves_from else "#your-move"
            cells.append(f'<a href="{href}"><img src="assets/chess/sq/{name}.svg?ply={ply}" '
                         f'width="{TILE_SHOWN}" height="{TILE_SHOWN}" align="top" alt="{alt}"></a>')
        rows.append("".join(cells) + "<br>")

    r = state["results"]
    lines = [START, '<div align="center">', "",
             f"**Game #{state['game']}** · move {board.fullmove_number} · "
             f"Humans **{r['humans']}** – **{r['engine']}** Engine · {r['draws']} draws", "",
             '<p align="center">', *rows, "</p>", "",
             "</div>", ""]

    if state["last"]:
        lines += [state["last"], ""]

    lines.append('<a name="your-move"></a>')
    if over:
        lines += ["", over[1], "", f"**[♟️ Start a new game]({issue_link('chess|new')})**", ""]
    else:
        lines += ["", "**How to play (you're White):** click one of your pieces with a green dot ▸ "
                  "click where to move it ▸ GitHub opens a pre-filled issue, press **Submit**. "
                  "My engine answers as Black within a minute.", "",
                  "| Your piece | Click where to move it |", "| :-- | :-- |"]
        order = sorted(moves_from, key=lambda sq: (board.piece_type_at(sq), chess.square_file(sq), sq))
        for sq in order:
            name = chess.square_name(sq)
            targets = sorted(moves_from[sq], key=lambda m: board.san(m))
            links = " ".join(f"[`{board.san(m)}`]({issue_link(f'chess|move|{m.uci()}|{ply}')})" for m in targets)
            lines.append(f'| <a name="pick-{name}"></a>{PIECE_NAMES[board.piece_type_at(sq)]} on **{name}** | {links} |')
        lines.append("")

    recent = state["moves"][-10:]
    if recent or state["players"]:
        lines += ["<details><summary><b>Move log & top players</b></summary>", "", "| # | Move | By |", "| --: | :-- | :-- |"]
        start = len(state["moves"]) - len(recent)
        for i, m in enumerate(recent, start + 1):
            who = "🤖 engine" if m["by"] == "engine" else f"[@{m['by']}](https://github.com/{m['by']})"
            lines.append(f"| {i} | `{m['san']}` | {who} |")
        top = sorted(state["players"].items(), key=lambda kv: -kv[1])[:5]
        if top:
            lines += ["", "**Top players:** " + " · ".join(
                f"[@{u}](https://github.com/{u}) ({n})" for u, n in top)]
        lines += ["", "</details>"]

    lines.append(END)
    text = README.read_text()
    a, b = text.index(START), text.index(END) + len(END)
    README.write_text(text[:a] + "\n".join(lines) + text[b:])

# --------------------------------------------------------------- actions ----


def reply(msg: str) -> None:
    path = os.environ.get("REPLY_FILE")
    if path:
        Path(path).write_text(msg)
    else:
        print(msg)


def finish_if_over(state: dict, board: chess.Board) -> str | None:
    over = outcome_text(board)
    if over and state["finished"] != state["game"]:
        state["results"][over[0]] += 1
        state["finished"] = state["game"]
    return over[1] if over else None


def cmd_move(uci: str, ply: str, user: str) -> int:
    state = load()
    board = board_of(state)
    readme = f"https://github.com/{REPO}#-play-chess-against-my-engine"

    if board.is_game_over(claim_draw=True):
        reply(f"This game is already over — [start a new one]({readme}).")
        return 2
    if not re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", uci) or not ply.isdigit():
        reply("I couldn't read that move. Use the links in the README.")
        return 2
    if int(ply) != len(state["moves"]):
        reply(f"Someone moved before you — the board has changed. [Pick a fresh move]({readme}).")
        return 2
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        reply(f"`{uci}` isn't legal in this position. [Back to the board]({readme}).")
        return 2

    san = board.san(move)
    board.push(move)
    state["moves"].append({"uci": uci, "san": san, "by": user})
    state["players"][user] = state["players"].get(user, 0) + 1
    msg = f"@{user} played **{san}**."

    if not board.is_game_over(claim_draw=True):
        t = time.monotonic()
        em = engine_move(board)
        esan = board.san(em)
        board.push(em)
        state["moves"].append({"uci": em.uci(), "san": esan, "by": "engine"})
        msg += f" The engine replied **{esan}** after {time.monotonic() - t:.1f}s of thought."

    end = finish_if_over(state, board)
    state["last"] = f"> {msg}" + (f"\n>\n> {end}" if end else "")
    save(state)
    render(state)
    reply(f"{msg}\n\n{end or ''}\n\n[See the board →]({readme})".replace("\n\n\n\n", "\n\n"))
    return 0


def cmd_new(user: str) -> int:
    state = load()
    board = board_of(state)
    readme = f"https://github.com/{REPO}#-play-chess-against-my-engine"
    if state["moves"] and not board.is_game_over(claim_draw=True):
        reply(f"A game is still in progress — [make a move]({readme}) instead!")
        return 2
    if state["moves"]:
        state["game"] += 1
    state.update(moves=[], last=f"> @{user} started a new game. White to move.", finished=None)
    save(state)
    render(state)
    reply(f"New game started. [Make the first move →]({readme})")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["move"] and len(argv) == 4:
        return cmd_move(argv[1].lower(), argv[2], argv[3])
    if argv[:1] == ["new"] and len(argv) == 2:
        return cmd_new(argv[1])
    if argv[:1] == ["render"]:
        render(load())
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
