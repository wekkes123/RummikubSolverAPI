from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Tuple, Dict, Union
import uvicorn

from set_generator import SetGenerator
from solver import RummikubSolver

app = FastAPI(
    title="Rummikub Solver API",
    description="API for solving optimal Rummikub moves",
    version="1.0.0"
)

# Initialize the set generator with default rules
default_sg = SetGenerator()


# Create tile mappings (will be used for input/output conversion)
def create_number_maps(sg):
    colours = ['k', 'b', 'o', 'r']
    verbose_list = [f'{colours[c]}{n}' for c in range(sg.colours) for n in range(1, sg.numbers + 1)]
    verbose_list.append('j')
    tile_map = dict(zip(verbose_list, sg.tiles))
    r_tile_map = {v: k for k, v in tile_map.items()}
    return tile_map, r_tile_map


tile_map, r_tile_map = create_number_maps(default_sg)


# Pydantic models for request and response
class GameConfig(BaseModel):
    numbers: int = 13
    colours: int = 4
    jokers: int = 2
    min_len: int = 3


class GameState(BaseModel):
    rack: List[str]
    table: List[str]
    config: Optional[GameConfig] = None


class Move(BaseModel):
    tiles_to_play: List[str]
    sets_to_make: List[List[str]]
    value: float
    success: bool
    message: str = ""


@app.post("/solve", response_model=Move)
def solve_game(game_state: GameState, maximise: str = "tiles", initial_meld: bool = False):
    # Configure game with custom settings if provided
    if game_state.config:
        sg = SetGenerator(
            numbers=game_state.config.numbers,
            colours=game_state.config.colours,
            jokers=game_state.config.jokers,
            min_len=game_state.config.min_len
        )
        custom_tile_map, custom_r_tile_map = create_number_maps(sg)
    else:
        sg = default_sg
        custom_tile_map, custom_r_tile_map = tile_map, r_tile_map

    try:
        # Convert string tiles to internal number representation
        rack_tiles = [custom_tile_map[t] for t in game_state.rack if t in custom_tile_map]
        table_tiles = [custom_tile_map[t] for t in game_state.table if t in custom_tile_map]

        # Create solver instance
        solver = RummikubSolver(
            tiles=sg.tiles,
            sets=sg.sets,
            numbers=sg.numbers,
            colours=sg.colours,
            rack=rack_tiles,
            table=table_tiles
        )

        # Find solution
        value, tiles, sets = solver.solve(maximise=maximise, initial_meld=initial_meld)

        # Format the response
        if value == 0 or (initial_meld and value < 30):
            return Move(
                tiles_to_play=[],
                sets_to_make=[],
                value=0,
                success=False,
                message="No valid move found - should pick up a tile."
            )
        else:
            # Get the tiles to play from rack
            tile_list = [solver.tiles[i] for i in range(len(tiles)) if tiles[i] == 1]
            set_list = [solver.sets[i] for i in range(len(sets)) if sets[i] == 1]

            # Convert back to human-readable format
            readable_tiles = [custom_r_tile_map[t] for t in tile_list]
            readable_sets = [[custom_r_tile_map[t] for t in s] for s in set_list]

            return Move(
                tiles_to_play=readable_tiles,
                sets_to_make=readable_sets,
                value=float(value),
                success=True,
                message="Valid move found."
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error solving game: {str(e)}")


@app.get("/rules")
def get_default_rules():
    return {
        "numbers": default_sg.numbers,
        "colours": default_sg.colours,
        "jokers": default_sg.jokers,
        "min_len": default_sg.min_len
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)