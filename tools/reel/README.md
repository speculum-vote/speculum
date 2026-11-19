# Reel builder

Turns checked figures into a 9:16 video for Instagram Reels and TikTok: 1080×1920, 30 fps, H.264 MP4, branded like the
carousels (seal, wordmark, gold on near-black). No tracking, no stock footage, no music: add a sound in the app.

```
python tools/reel/reel.py tools/reel/specs/kennedy-pac.json --out out/ --frames   # key frames only, to check
python tools/reel/reel.py tools/reel/specs/kennedy-pac.json --out out/            # the video (~1 min to render)
```

A spec is JSON: `{"name": ..., "scenes": [...]}`. Scene types (see the docstring in `reel.py` for fields):
`hook` (big numbers that count up), `statement` (words rise in; `<b>` for gold), `bars` (bars grow one after
another), `columns` (paired columns over time), `end` (closing card with the address). Each scene takes `seconds`
and a `source` line.

Rules:
- Every number in a spec comes from a checked record. Generate the spec from the same script that asserts the
  figures (see how `specs/kennedy-pac.json` was made from the carousel script), never by retyping.
- Run the pre-publish check before anything is posted.
- Keep a scene under ~40 words; aim for 25–40 seconds in all. The first scene carries the hook.
- Text stays in the area the apps leave clear: the builder warns when something falls outside it (`--frames`).
