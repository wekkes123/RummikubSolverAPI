from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins - for development only
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
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


def sum_group(tile_set):
    tiles = tile_set[1:]
    joker_count = tiles.count('j')
    real_tiles = [tile for tile in tiles if tile != 'j']

    numbers = [int(tile[1:]) for tile in real_tiles]
    base_value = numbers[0]

    total = base_value * len(real_tiles) + base_value * joker_count
    return tile_set, total


def place_joker_in_run(tile_set):
    if not tile_set or tile_set[0] != 'r' or 'j' not in tile_set:
        total = sum(int(tile[1:]) for tile in tile_set[1:] if tile != 'j')
        return tile_set, total

    tiles = [tile for tile in tile_set[1:] if tile != 'j']
    joker_count = tile_set.count('j')

    numbers = sorted([int(tile[1:]) for tile in tiles])
    filled_numbers = []
    inserted_jokers = 0
    i = 0

    while i < len(numbers) - 1:
        filled_numbers.append(numbers[i])
        gap = numbers[i + 1] - numbers[i]
        if gap == 1:
            i += 1
            continue
        elif gap > 1:
            missing = gap - 1
            if inserted_jokers + missing <= joker_count:
                for j in range(1, gap):
                    filled_numbers.append(numbers[i] + j)
                inserted_jokers += missing
            else:
                break
        i += 1

    filled_numbers.append(numbers[-1])

    while inserted_jokers < joker_count:
        if filled_numbers[-1] < 13:
            filled_numbers.append(filled_numbers[-1] + 1)
        elif filled_numbers[0] > 1:
            filled_numbers.insert(0, filled_numbers[0] - 1)
        else:
            break
        inserted_jokers += 1

    filled_numbers.sort()

    new_set = ['r']
    total_sum = 0
    tiles_copy = tiles.copy()

    for num in filled_numbers:
        if tiles_copy and int(tiles_copy[0][1:]) == num:
            tile = tiles_copy.pop(0)
            new_set.append(tile)
            total_sum += num
        else:
            new_set.append('j')
            total_sum += num

    return new_set, total_sum

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
    joker_value: Optional[int] = None


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
        if value == 0:
            return Move(
                tiles_to_play=[],
                sets_to_make=[],
                value=0,
                success=False,
                message="No valid move found - should pick up a tile.",
                joker_value=None
            )
        else:
            tile_list = [solver.tiles[i] for i in range(len(tiles)) for _ in range(int(tiles[i])) if tiles[i] > 0]
            set_list = [solver.sets[i] for i in range(len(sets)) for _ in range(int(sets[i])) if sets[i] > 0]

            readable_tiles = [custom_r_tile_map[t] for t in tile_list]
            readable_sets = [[custom_r_tile_map[t] for t in s] for s in set_list]

            point_value = 0
            labeled_sets = []

            def identify(tile_set):
                jokers = 0
                colors = []
                numbers = []
                for tile in tile_set:
                    if tile == "j":
                        jokers += 1
                        numbers.append(tile)
                    else:
                        colors.append(tile[0])
                        numbers.append(tile[1:])
                number_of_colors = len(set(colors));
                if jokers == 0:
                    if number_of_colors == 1:
                        tile_set = ["r"] + tile_set
                        return place_joker_in_run(tile_set)
                    else:
                        tile_set = ["g"] + tile_set
                        return sum_group(tile_set)
                elif jokers == 1:
                    if number_of_colors == 1:
                        tile_set = ["r"] + tile_set
                        return place_joker_in_run(tile_set)
                    else:
                        tile_set = ["g"] + tile_set
                        return sum_group(tile_set)
                else:
                    if number_of_colors == 1 and len(
                            tile_set) == 3:  # this special combination means that the set could be a run or a group, and the best option needs to be chosen
                        tile_set_g, grp_sum = sum_group(["g"] + tile_set)
                        tile_set_r, run_sum = place_joker_in_run(["r"] + tile_set)
                        if initial_meld:
                            if run_sum > grp_sum:
                                return tile_set_r, run_sum
                            else:
                                return tile_set_g, grp_sum
                        else:
                            return sum_group(["g"] + tile_set)
                    elif number_of_colors == 1 and len(tile_set) > 3:
                        return place_joker_in_run(["r"] + tile_set)
                    else:
                        return sum_group(["g"] + tile_set)

            for lset in readable_sets:
                try:
                    set_to_add, value_to_add = identify(lset)
                    point_value += value_to_add
                    labeled_sets.append(lset)
                except Exception as e:
                    print("parse error", e)

            if initial_meld and point_value < 30:
                return Move(
                    tiles_to_play=[],
                    sets_to_make=[],
                    value=float(value),
                    success=False,
                    message=f"Initial meld requires 30+ points. Current play: {point_value} points.",
                )

            return Move(
                tiles_to_play=readable_tiles,
                extra=readable_sets,
                sets_to_make=labeled_sets,
                value=float(value),
                success=True,
                message=f"Valid move found. Point value: {point_value}",
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

@app.get("/")
def read_root():
    return {"message": "Hello, World! The API is running!, add /docs to the end of this URL to learn how to use it."}



if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)