# The AI in VS Digital Pro, in plain language

This page is for anyone, no coding needed. It explains what "AI" means in
this app, each AI model it uses, what each one does for your photos, and what
it can't do.

## First, what is an "AI model"?

An AI model is a program that learned a skill by studying a huge number of
examples, instead of being given rules by a person. A model that has seen
millions of photos of people learns what a person looks like, so it can find
the people in your photo, even ones it has never seen.

Two kinds show up in this app:

- **Models that look** (most of them). They study your photo and answer a
  question: *where are the players? where is the ball? which pixels are the
  player and which are the background? is this the same face?* They don't
  change your photo. The app uses their answers to edit it precisely.
- **Models that draw.** They make new pixels: the illustration looks, filling
  in where a removed object was, and sharpening an enlarged crop. The app
  keeps these on a short leash (see "The rules the AI follows" below).

A model is a big file (from 40 MB to a few GB) that the app downloads **once**
and keeps on your Mac. After that it works without the internet.

## Where it runs, and what it costs

**Almost everything runs on your Mac, for free.** Your Mac's chip (the M5)
has parts built for exactly this kind of maths, which is why a model can trace
a player in about a second. Your photos never leave your computer for these.

The **one exception is Gemini** (Google's AI), and it is **off unless you ask
for it**. It is used only in Culling, to rate a shortlist of keepers or to
suggest edits. The app shows the cost before it runs, and it never uses
Google's image-making models (they are too expensive). Gemini only looks and
gives advice; it never draws on your photos.

## Every model, and what it does for you

### Understanding the photo (models that look)

| What you see in the app | The model | What it does |
|---|---|---|
| Looks know where the players, heads, feet and ball are | **YOLO** (pose and outline versions) | Finds every person and their body points (head, shoulders, feet) and outlines them. Used for framing, keeping effects off faces, and putting smoke at a player's feet. |
| Player-only and background-only settings, Color Pop, background blur, posters with the player in front of the title | **BiRefNet** | Makes the precise cut-out of the players, down to hair and fingers. It separates "the player" from "everything behind them". |
| Fix the cut-out, Adjust a part, Remove (click) | **SAM 2.1** (Meta's "Segment Anything") | You click something and it traces exactly that thing: a teammate, the sky, a cone, a face. |
| Find a player | **YuNet** and **SFace** | YuNet finds faces; SFace turns each face into a kind of fingerprint, so the same child's face can be matched across hundreds of photos. Close calls are asked, never guessed. |
| Jersey numbers read off shirts; no made-up text in drawings | **Apple Vision** (built into your Mac) | Reads text in photos. Also judges face quality (eyes open, in focus) for Culling. |
| Culling learns your taste | **A small "taste" model**, trained on your Mac | Learns from your own keep and reject choices which measurements matter to you, so the next event's first pass is closer to how you'd choose. |

### Changing the photo (models that draw)

| What you see in the app | The model | What it does |
|---|---|---|
| Remove (a bag, a pole, a parent on the sideline) | **LaMa** | Fills the hole with what would plausibly be behind it: grass, fence, sky. The app then matches the light and borrows real grass texture from right around it. |
| The 20 illustration looks (anime, oil, comic, pencil, watercolor) | **Stable Diffusion 1.5 (DreamShaper 8) with ControlNet line art** | Redraws the players in a style, following the outlines of your actual photo, so the pose and shape stay true. |
| Illustration looks at full size | **Real-ESRGAN, illustration version** | Enlarges the drawing 4 times with clean lines. |
| Tight crops that stay sharp when exported | **Real-ESRGAN, photo version** | See the next section. |

### The AI detail enlarger (sharp tight crops)

When you crop in tight, the crop may have fewer pixels than the size you
export. An Instagram post needs 1,080 pixels across, and a print needs even
more. Normal enlarging just stretches the pixels, which looks soft and smeary.

The enlarger was trained on millions of pairs of sharp photos and their
blurry, shrunk copies, so it learned what fine detail usually looks like:
the edge of hair, the weave of a shirt, the edge of a number. When it
enlarges your crop 4 times, it rebuilds those edges cleanly instead of
smearing them. The app then:

- mixes back a little of the plain enlargement, so skin keeps its real
  texture and doesn't look plastic;
- only uses it when a crop is actually enlarged (about 7 seconds a photo);
- sharpens faces like the rest of the picture, but it isn't a face generator:
  it rebuilds fine detail from what's there and never invents a different face.

**What it can't do:** it can't recover a photo that was out of focus or
blurred by motion. It sharpens detail that is faintly there; it can't
invent a sharp face from a blurry one, and you wouldn't want it to. The best
crops still start with a sharp photo.

**Tip from the pros:** with your 33-megapixel Sony, a crop a quarter of the
photo's width is still about 1,750 pixels across. That's more than Instagram
shows, so it needs no enlarging at all. Enlarging only comes in on tighter
crops or big prints.

## The rules the AI follows in this app

Drawing models can make mistakes that would be embarrassing on a real child's
photo, so the app has rules built in:

1. **Faces are always the child's own.** In illustration looks, the real head
   (face, hair, ears) is kept from the photo and only painted in the look's
   style. The AI never draws a new face. (The enlarger sharpens faces with the
   rest of the picture, from what's there; it doesn't invent features.)
2. **No made-up text.** Drawing models can't write: they invent jersey
   numbers and garble sponsor names. After every drawing, Apple Vision
   compares the text with the photo. Invented text is painted out, and the
   real text is put back.
3. **Effects stay off faces.** Textures, grain, glows and overlays fade away
   from heads.
4. **Skin keeps its color.** Color looks and grades leave skin tones natural,
   whatever skin color the player has.
5. **Your originals are never changed.** Everything is saved as a new file.
6. **When unsure, ask.** Find a player asks "Is this your player?" instead of
   guessing, and Culling shows how sure it is and why.

## What is not AI

A lot of the app is ordinary, predictable photo maths written by hand, not
AI: the looks and color grades, the sliders (exposure, clarity, vibrance,
color mixer and so on), the posters and fonts, the watercolor and pencil
effects, export sizes and the Check tab. Given the same photo and the same
settings, they always give exactly the same result.

## Where the models live

| Folder | What's in it |
|---|---|
| `~/.cache/photo-crops` | YOLO, SAM 2.1, YuNet, SFace, LaMa (or reused from `~/.cache/ai-versions`), both Real-ESRGAN models |
| `~/.rembg` | BiRefNet (the cut-out) |
| `~/.cache/huggingface` | Stable Diffusion and ControlNet (about 5 GB, only if you use the illustration looks) |

Each downloads the first time it's needed. Deleting one is safe: the app
downloads it again when it next needs it.

For how the rest of the software is built, see
[Architecture in the README](README.md#architecture).
