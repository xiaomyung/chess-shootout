# Emoji source font (build-time only)

`NotoColorEmoji.ttf` is **not shipped**. It is the source from which
`packaging/render_emoji.py` pre-renders the PNG sprites under
`assets/emoji_png/` (flags + UI emoji) that the app actually loads.

Why pre-render: pygame's Windows `SDL2_ttf` wheel bundles a FreeType built
without libpng, so it cannot decode Noto Color Emoji's PNG-compressed CBDT
bitmaps — color glyphs render blank on Windows. Rendering once here (on a
libpng-enabled platform) and shipping the PNGs sidesteps that entirely.

Regenerate after changing the emoji set or the country list:

    python packaging/render_emoji.py

License: Noto Color Emoji is licensed under the SIL Open Font License v1.1.
The full license and copyright notice are in `assets/fonts/OFL.txt`.
"Noto" is a trademark of Google Inc.
