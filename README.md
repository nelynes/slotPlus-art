# slotPlus art

Cart labels and logos for [Cart Studio+](https://nelynes.github.io/slotPlus-studio/), hosted at
[nelynes.github.io/slotPlus-art](https://nelynes.github.io/slotPlus-art/). Cart Studio+ looks here
first, before slot's art set and libretro, so anything in this set is what a cart wears by default.

The set is laid out the way slot's own art set is:

- `<platform>/support-texture/<CRC32>.png`: a whole label, shown as the cart's **Real Label**.
- `<platform>/wheel/<CRC32>.png`: a logo with a transparent background, shown as **Logo Only**, on a
  colour taken from the game's box art.
- `index.json`: each rom checksum, upper case hex, with the files the set has for it.

`<platform>` is the card folder slotPlus files the game under: `GBA`, `GB`, `GBC`, `WS`, `Lynx`,
`GG`, `NGP` or `TG16`. A file is named by checksum rather than by game, so it reaches every copy
of the game, whatever the rom is called on someone's card.

## Adding art

Name the image after the game, as slotPlus names a label on the card, and run:

    tools/add.py GBA "Oriental Blue - Ao no Tengai (Japan).png"

It finds the game in libretro's No-Intro database, files the image under the checksum of every
dump of it, and updates `index.json`. `--game` gives the database name when the file's own is not
it, and `--crc` files it under a checksum directly. An image with transparency is taken as a
logo, an opaque one as a whole label; `--logo` or `--label` overrides that. It needs Python 3 with
Pillow.

## License

The tools in this repository are GPL-3.0-or-later, as slotPlus is. See [LICENSE](LICENSE). The
licence covers the code, not the label art, which belongs to each game's publisher.

## Credits

Labels and logos here were made or scanned by slotPlus's contributors. Game names and checksums
come from [libretro-database](https://github.com/libretro/libretro-database) (CC BY-SA 4.0).
Game names, logos and label art belong to their publishers; they are here so players can label
the carts of games they own. slotPlus is not affiliated with any of them.
