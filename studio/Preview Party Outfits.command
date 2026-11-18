#!/bin/zsh
# Quick test of the new party hat + heart clip: one picture per hair style.
# They go in "preview_frames" - Digi's real frames aren't touched.
cd ~/Downloads/"DigiPal Studio"
BL=$(find ~/Library/Application\ Support/Steam/steamapps/common -type f -name Blender -path "*MacOS*" 2>/dev/null | head -1)
"$BL" -b ~/Downloads/"DigiPal Studio"/pet.blend -P ~/Downloads/"DigiPal Studio"/animate_pet.py -- idle outfits preview party heart
echo ""
echo "All done! You can close this window."
