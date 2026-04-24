# Building Catalog

Map size: 140x100 tiles (32 px per tile)

## Buildings
- B01 | Isabella Rodriguez's apartment | center(tile)=(77.57, 14.7) | entry(tile)=(78, 19) | inside(tile)=(78, 18) | size=14x6 tiles
- B02 | Arthur Burton's apartment | center(tile)=(57.5, 15.22) | entry(tile)=(58, 20) | inside(tile)=(58, 19) | size=12x7 tiles
- B03 | Giorgio Rossi's apartment | center(tile)=(88.0, 18.5) | entry(tile)=(88, 26) | inside(tile)=(88, 25) | size=7x14 tiles
- B04 | Carlos Gomez's apartment | center(tile)=(95.0, 18.5) | entry(tile)=(95, 26) | inside(tile)=(95, 25) | size=7x14 tiles
- B05 | Ryan Park's apartment | center(tile)=(67.0, 19.5) | entry(tile)=(67, 27) | inside(tile)=(67, 26) | size=7x14 tiles
- B06 | Hobbs Cafe | center(tile)=(77.47, 21.62) | entry(tile)=(77, 27) | inside(tile)=(77, 26) | size=14x10 tiles
- B07 | The Rose and Crown Pub | center(tile)=(57.5, 22.13) | entry(tile)=(57, 27) | inside(tile)=(57, 26) | size=12x9 tiles
- B08 | artist's co-living space | center(tile)=(28.47, 25.1) | entry(tile)=(28, 36) | inside(tile)=(40, 34) | size=30x19 tiles
- B09 | Oak Hill College | center(tile)=(116.42, 26.17) | entry(tile)=(116, 36) | inside(tile)=(111, 34) | size=19x16 tiles
- B10 | Johnson Park | center(tile)=(27.5, 46.0) | entry(tile)=(28, 52) | inside(tile)=(28, 46) | size=16x11 tiles
- B11 | The Willows Market and Pharmacy | center(tile)=(84.04, 47.59) | entry(tile)=(84, 53) | inside(tile)=(84, 53) | size=21x12 tiles
- B12 | Harvey Oak Supply Store | center(tile)=(63.5, 47.62) | entry(tile)=(64, 53) | inside(tile)=(64, 53) | size=16x12 tiles
- B13 | Dorm for Oak Hill College | center(tile)=(120.15, 50.05) | entry(tile)=(121, 63) | inside(tile)=(120, 50) | size=29x32 tiles
- B14 | Adam Smith's house | center(tile)=(21.99, 64.13) | entry(tile)=(22, 72) | inside(tile)=(22, 64) | size=7x13 tiles
- B15 | Yuriko Yamamoto's house | center(tile)=(29.99, 64.13) | entry(tile)=(30, 72) | inside(tile)=(30, 64) | size=7x13 tiles
- B16 | Moore family's house | center(tile)=(37.99, 64.13) | entry(tile)=(38, 72) | inside(tile)=(38, 64) | size=7x13 tiles
- B17 | Moreno family's house | center(tile)=(74.51, 72.42) | entry(tile)=(75, 84) | inside(tile)=(77, 72) | size=14x19 tiles
- B18 | Lin family's house | center(tile)=(92.51, 72.42) | entry(tile)=(93, 83) | inside(tile)=(96, 75) | size=14x19 tiles
- B19 | Tamara Taylor and Carmen Ortiz's house | center(tile)=(56.46, 72.46) | entry(tile)=(56, 84) | inside(tile)=(61, 75) | size=14x19 tiles

## Step Distance Notes
- `entry_path_steps` is shortest path steps between building entry points using walkable tiles.
- `center_euclidean_tiles` and `center_manhattan_tiles` are geometric center distances.

Pairwise data is stored in `backend/store/building_catalog.json` under `pairwise_steps`.

