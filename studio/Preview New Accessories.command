#!/bin/zsh
# Quick test of the new accessories (sun hat, beret, bunny ears, glasses, bow, star clip):
# one picture with each hair style. They go in "preview_frames" - Digi's real frames aren't touched.
cd ~/Downloads/"DigiPal Studio"
BL=$(find ~/Library/Application\ Support/Steam/steamapps/common -type f -name Blender -path "*MacOS*" 2>/dev/null | head -1)
"$BL" -b ~/Downloads/"DigiPal Studio"/pet.blend -P ~/Downloads/"DigiPal Studio"/animate_pet.py -- idle outfits preview ${@:-sunhat beret bunny glasses bow star}
echo ""
echo "All done! You can close this window."
