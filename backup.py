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


tile_map, r_tile_map = create_number_maps(default_sg)

def place_joker_in_run(tile_set):
    if not tile_set or tile_set[0] != 'r' or 'j' not in tile_set:
        return tile_set

    tiles = [tile for tile in tile_set[1:] if tile != 'j']

    numbers = sorted([int(tile[1:]) for tile in tiles])

    joker_insert_value = None
    for i in range(len(numbers) - 1):
        if numbers[i + 1] - numbers[i] > 1:
            joker_insert_value = numbers[i] + 1
            break

    if joker_insert_value is None:
        if len(numbers) >= 2 and numbers[-2] == 13:
            insert_index = 1
        else:
            insert_index = len(tile_set) - 1
        new_set = [tile for tile in tile_set if tile != 'j']
        new_set.insert(insert_index, 'j')
        return new_set

    new_set = ['r']
    inserted = False
    for tile in sorted(tiles, key=lambda x: int(x[1:])):
        value = int(tile[1:])
        if not inserted and value > joker_insert_value:
            new_set.append('j')
            inserted = True
        new_set.append(tile)

    if not inserted:
        new_set.append('j')

    return new_set

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
            joker_value = None

            labeled_sets = []

            for set_tiles in readable_sets:
                is_run = False
                colors = set()
                numbers = []


                for tile in set_tiles:
                    if tile != 'j':
                        colors.add(tile[0])
                        try:
                            numbers.append(int(tile[1:]))
                        except ValueError:
                            pass

                if len(colors) <= 1:
                    is_run = True
                    set_type = 'r'  # 'r' for run
                elif len(set(numbers)) <= 1 and numbers:
                    is_run = False
                    set_type = 'g'  # 'g' for group
                else:
                    is_run = True
                    set_type = 'r'

                labeled_set = [set_type] + set_tiles
                labeled_sets.append(labeled_set)

                for tile in set_tiles:
                    if tile == 'j':
                        if is_run and numbers:
                            sorted_numbers = sorted(numbers)
                            if len(sorted_numbers) > 1:
                                for i in range(len(sorted_numbers) - 1):
                                    if sorted_numbers[i + 1] - sorted_numbers[i] > 1:
                                        joker_value = sorted_numbers[i] + 1
                                        point_value += joker_value
                                        break
                                else:
                                    if min(sorted_numbers) > 1:
                                        joker_value = min(sorted_numbers) - 1  # Joker before min
                                        point_value += joker_value
                                    else:
                                        joker_value = max(sorted_numbers) + 1  # Joker after max
                                        point_value += joker_value
                            else:
                                joker_value = numbers[0]
                                point_value += joker_value
                        elif not is_run and numbers:
                            joker_value = numbers[0]
                            point_value += joker_value
                        else:
                            joker_value = 0
                            point_value += 0
                    else:
                        try:
                            point_value += int(tile[1:])
                        except ValueError:
                            pass

            for i, lset in enumerate(labeled_sets):
                try:
                    labeled_sets[i] = place_joker_in_run(lset)
                except Exception as e:
                    print("parse error", e)

            if initial_meld and point_value < 30:
                return Move(
                    tiles_to_play=[],
                    sets_to_make=[],
                    value=float(value),
                    success=False,
                    message=f"Initial meld requires 30+ points. Current play: {point_value} points.",
                    joker_value=None
                )

            return Move(
                tiles_to_play=readable_tiles,
                sets_to_make=labeled_sets,
                value=float(value),
                success=True,
                message=f"Valid move found. Point value: {point_value}",
                joker_value=joker_value
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