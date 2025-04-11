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
        if value == 0:
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

            # Calculate actual point value for initial meld check
            point_value = 0

            # Process each set to identify type and calculate values
            labeled_sets = []

            for set_tiles in readable_sets:
                # For each set, identify if it's a run or a group
                is_run = False
                colors = set()
                numbers = []

                # Extract numbers and colors to determine set type
                for tile in set_tiles:
                    if tile != 'j':  # Skip jokers for now
                        colors.add(tile[0])  # First character is color
                        try:
                            numbers.append(int(tile[1:]))  # Rest is the number
                        except ValueError:
                            pass

                # Determine if it's a run or group
                if len(colors) <= 1:
                    # If all tiles have the same color (or would with jokers), it's likely a run
                    is_run = True
                    set_type = 'r'  # 'r' for run
                elif len(set(numbers)) <= 1 and numbers:
                    # If all tiles have different colors, it could be a group (same number)
                    is_run = False
                    set_type = 'g'  # 'g' for group
                else:
                    # Default to run if we can't determine
                    is_run = True
                    set_type = 'r'

                # Create a new set with type label at the beginning
                labeled_set = [set_type] + set_tiles
                labeled_sets.append(labeled_set)

                # Calculate values for each tile in the set
                for tile in set_tiles:
                    if tile == 'j':  # Joker handling
                        if is_run and numbers:
                            # For runs, joker value is the missing number
                            sorted_numbers = sorted(numbers)
                            if len(sorted_numbers) > 1:
                                # Find gaps in the sequence
                                for i in range(len(sorted_numbers) - 1):
                                    if sorted_numbers[i + 1] - sorted_numbers[i] > 1:
                                        # Joker represents a value in the gap
                                        joker_value = sorted_numbers[i] + 1
                                        point_value += joker_value
                                        break
                                else:
                                    # No gaps, joker is at beginning or end
                                    if min(sorted_numbers) > 1:
                                        point_value += min(sorted_numbers) - 1  # Joker before min
                                    else:
                                        point_value += max(sorted_numbers) + 1  # Joker after max
                            else:
                                # Only one number in the run, assume joker is adjacent
                                point_value += numbers[0]  # Simple approximation
                        elif not is_run and numbers:
                            # For groups, joker value is the same as other tiles
                            point_value += numbers[0]
                        else:
                            # Default case if we can't determine
                            point_value += 0
                    else:
                        # Regular tile - add its face value
                        try:
                            point_value += int(tile[1:])
                        except ValueError:
                            pass

            # Check if initial meld meets point requirement
            if initial_meld and point_value < 30:
                return Move(
                    tiles_to_play=[],
                    sets_to_make=[],
                    value=float(value),
                    success=False,
                    message=f"Initial meld requires 30+ points. Current play: {point_value} points."
                )

            # Include the actual point value in the response
            return Move(
                tiles_to_play=readable_tiles,
                sets_to_make=labeled_sets,  # Use the labeled sets instead
                value=float(value),
                actual_points=point_value,  # Add this to your Move model
                success=True,
                message=f"Valid move found. Point value: {point_value}"
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