# Things to do on the Mac (DigiPal Studio)

These need Blender on the Mac. Copy the files in this `studio` folder into
`~/Downloads/DigiPal Studio` first (replace the old `animate_pet.py`).

1. **Preview the party hat + heart clip**: double-click `Preview Party Outfits.command`,
   then show Claude the pictures in `preview_frames/outfit_party` and `outfit_heart`.
2. **Render them for real** once they look right: `Render Party Outfits.command`.
3. **Share the new frames with everyone**: Claude zips the new outfit folders into a new
   GitHub release and bumps `frames_version` so every Digi downloads them.
   (Until then everyone sees a hand-drawn party hat / heart instead.)
4. **Update the Mac app** to the newest Digi from GitHub (it's a few versions behind),
   plus `personal_defaults.json`. The Mac's own updater hasn't been tested yet.
5. Peek frames: future renders skip the skirt/shorts layer while peeking (already fixed in
   the app, so nothing to re-render unless you want smaller files).
