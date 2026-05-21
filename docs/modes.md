# Modes

## Local engine mode

Human moves physical pieces. Host detects legal move, asks Stockfish, then robot executes engine response.

## Lichess board mode

Human plays on the physical board against a remote human. Remote moves are streamed from Lichess and executed by robot.

## Lichess bot mode

Bot account mode. Engine assistance must use the bot flow, not the ordinary human board API.

## Cloud relay mode

External app sends moves through a relay server. Useful for demonstrations and classroom use.
