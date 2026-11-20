#!/bin/zsh
# Quick test of the sword: a few poses with twin tails and drill tails.
# They go in "preview_frames" - Digi's real frames aren't touched.
cd ~/Downloads/"DigiPal Studio"
BL=$(find ~/Library/Application\ Support/Steam/steamapps/common -type f -name Blender -path "*MacOS*" 2>/dev/null | head -1)
"$BL" -b ~/Downloads/"DigiPal Studio"/pet.blend -P ~/Downloads/"DigiPal Studio"/animate_pet.py -- outfits preview sword twintails drills 2>&1 | tee ~/Downloads/"DigiPal Studio"/preview_log.txt
echo ""
echo "All done! You can close this window."
