#!/bin/zsh
# Renders every pose wearing the party hat and the heart clip, then copies them into DigiPal.app.
# Takes a while - the Mac won't fall asleep meanwhile.
cd ~/Downloads/"DigiPal Studio"
BL=$(find ~/Library/Application\ Support/Steam/steamapps/common -type f -name Blender -path "*MacOS*" 2>/dev/null | head -1)
caffeinate -i "$BL" -b ~/Downloads/"DigiPal Studio"/pet.blend -P ~/Downloads/"DigiPal Studio"/animate_pet.py -- outfits party heart 2>&1 | tee ~/Downloads/"DigiPal Studio"/render_log.txt
echo ""
if grep -q "ALL FRAMES DONE" ~/Downloads/"DigiPal Studio"/render_log.txt; then
  rsync -a ~/Downloads/"DigiPal Studio"/pet_frames/ /Applications/DigiPal.app/Contents/Resources/pet_frames/
  echo "All done! Quit Digi and open her again to see the new outfits. You can close this window."
else
  echo "Hmm, the render didn't finish, so Digi's app was NOT changed. Tell Claude - details are in render_log.txt."
fi
