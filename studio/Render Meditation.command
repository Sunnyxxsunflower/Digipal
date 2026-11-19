#!/bin/zsh
# Renders Digi meditating on her zafu (every hair style, skirt/shorts and outfit),
# then copies the new pictures into DigiPal.app. The Mac won't fall asleep meanwhile.
cd ~/Downloads/"DigiPal Studio"
BL=$(find ~/Library/Application\ Support/Steam/steamapps/common -type f -name Blender -path "*MacOS*" 2>/dev/null | head -1)
caffeinate -i "$BL" -b ~/Downloads/"DigiPal Studio"/pet.blend -P ~/Downloads/"DigiPal Studio"/animate_pet.py -- outfits meditate 2>&1 | tee ~/Downloads/"DigiPal Studio"/render_log.txt
echo ""
if grep -q "ALL FRAMES DONE" ~/Downloads/"DigiPal Studio"/render_log.txt; then
  rsync -a ~/Downloads/"DigiPal Studio"/pet_frames/ /Applications/DigiPal.app/Contents/Resources/pet_frames/
  echo "All done! Quit Digi and open her again to see her meditate. You can close this window."
else
  echo "Hmm, the render didn't finish, so Digi's app was NOT changed. Tell Claude - details are in render_log.txt."
fi
