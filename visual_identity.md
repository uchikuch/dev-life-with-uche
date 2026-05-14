# Dev Life with Uche — Visual Identity System v2

---

## 1. CHARACTER SPEC

### Identity

- **Role:** CTO / Developer / Founder
- **Vibe:** Calm, observant, slightly amused, never chaotic
- **Archetype:** "The only sane person in tech chaos"

---

### Face (LOCKED — DO NOT CHANGE)

- **Skin tone:** Rich dark brown (consistent tone across all frames)
- **Face shape:** Slightly elongated oval
- **Hair:** Very low cut
- **Facial hair:** Light mustache + short goatee
- **Eyes:** Medium, slightly narrow
- **Signature expression:** One eyebrow slightly raised

---

### Outfit (Brand Anchor — NEVER CHANGES)

- **Hoodie:** Neon Purple (#7B3FE4 to #9B5CFF range)
- **Cap:** Matte black
- **Logo on hoodie:** `</>` (white, left chest area)
- **Pants:** Dark / black
- **Shoes:** White sneakers

Reference image: `character_sheet.png` (front + back view) — passed with every Gemini generation call

---

### Expression System (Reusable Set — Use ONLY These)

| # | Expression | Use Case |
|---|-----------|----------|
| 1 | 😐 Neutral | Default / narration |
| 2 | 🤨 Raised eyebrow | Signature / reacting to absurdity |
| 3 | 😑 Deadpan | Comedy beats / dry humour |
| 4 | 😏 Slight smirk | Dropping knowledge / "told you so" |
| 5 | 😤 Mild frustration | Tech debt, scope creep, broken deploys |
| 6 | 😴 Tired founder | Late nights, wearing too many hats |

Repetition = brand recognition. Do not invent new expressions.

---

### Body Language

- Relaxed posture at all times
- Minimal exaggerated gestures
- Hands used sparingly (pointing, chin-rest thinking pose, arms crossed)
- Calm = authority. Never frantic, never panicked.

---

## 2. STYLE SPEC

### Primary Style: Minimalist Flat + Soft Glow

- Clean vector lines
- Minimal shading (flat colour fills, no heavy gradients on character)
- Soft lighting with subtle purple accents where appropriate
- Character is always the most vivid, saturated element in the frame

---

### Lighting

- **Primary source:** Natural or ambient lighting appropriate to the scene (office daylight, laptop glow, meeting room overhead)
- **Purple accent:** Subtle purple rim lighting or glow can be added for night/solo scenes, but is not required in every frame
- **Face:** Softly lit, clearly visible, never harsh or overly dramatic
- **Consistency rule:** Lighting should feel natural to the environment. The character's purple hoodie provides brand colour presence regardless of lighting setup.

---

### Colour System (LOCKED)

| Role | Colour | Hex |
|------|--------|-----|
| Primary / Brand | Neon Purple | #8A4FFF (range #7B3FE4 to #9B5CFF) |
| Text (primary) | White | #FFFFFF |
| Text (secondary) | Light purple | #C4A1FF |
| Accent (rare, highlights only) | Cyan | #4ECDC4 |
| Accent (rare, warnings/alerts) | Amber | #FFB830 |
| Thumbnail text | White with purple outer glow | — |

### Background Palette (Flexible)

| Setting | Tone | Notes |
|---------|------|-------|
| Late night / solo coding | Dark navy-charcoal (#1A1A2E to #16213E) | Purple neon rim lighting |
| Office / meeting room | Light grey, soft white, muted blue | Clean, professional |
| Casual / coffee shop | Warm neutrals, soft beige | Relaxed, reflective scenes |
| Neutral / versatile | Mid-grey, desaturated blue | Works for any pillar |

**Rule:** The character's purple hoodie is always the most saturated element in the frame. Backgrounds should be simpler and less saturated than the character, whether light or dark. Never introduce new brand colours. If a prop or UI element needs colour, pull from the colour system table above.

---

## 3. ENVIRONMENT SYSTEM

Every scene should feel like it exists in the same universe. The character is the focal point, the environment supports but never competes.

### Background Rule

**Backgrounds should always be simpler and less saturated than the character.** Whether light or dark, the character is the most vivid thing in the frame. Backgrounds suggest a setting with soft blur and reduced detail rather than illustrating environments in full. The purple hoodie is the visual anchor, not the background colour.

---

### Core Elements (reuse frequently)

- Laptop (dark mode UI on screen)
- Coffee mug
- Sticky notes with dev humour ("works on my machine", "TODO: fix later", "sprint 47")
- Minimal desk setup (clean, not cluttered)
- Office environments (light or dark depending on scene mood)
- City skyline through window (blurred, distant — optional)

---

### Optional Props (rotate per pillar, max 2 per scene)

- Whiteboard with messy sprint board / architecture diagram
- Books on desk (spines reading "Clean Code", "System Design", "The Lean Startup")
- Slack/Jira-like UI on screen (simplified, not branded)
- Phone with notification badges
- Second monitor with terminal / code
- Meeting room table (for PM vs Engineer scenes)

---

## 4. SCENE SYSTEM

### Scene Formula

**Character + Problem + Environment + Expression**

Every scene follows this structure. The problem is communicated through a combination of the environment detail (sticky note text, screen content, whiteboard) and the character's expression.

---

### Scene Templates by Pillar

**1. Startup Realities**
Scene: Late night, laptop glow, empty office (dark)
Expression: 😐 Neutral
Detail: Sticky note reading "This wasn't in the pitch deck"

**2. Sprint & Agile Dysfunction**
Scene: Bright office, whiteboard with messy/overloaded sprint board
Expression: 😑 Deadpan
Detail: Column labelled "Refactor (maybe)" / "Blocked: waiting on feedback"

**3. The Customer Reality**
Scene: Clean office desk, laptop showing confused UI mockup or analytics dashboard
Expression: 🤨 Raised eyebrow
Detail: Sticky note: "Users don't care about your roadmap"

**4. Career Navigation**
Scene: Coffee shop or quiet workspace, thinking pose, warm tones
Expression: 😏 Slight smirk
Detail: Two browser tabs visible: "Current Job" vs "Offer Letter.pdf"

**5. Tech Debt & Code Culture**
Scene: Dark room, tired posture, multiple screens with legacy code
Expression: 😤 Mild frustration
Detail: Floating text or sticky note: "We'll fix it later"

**6. PM vs Engineer Dynamics**
Scene: Well-lit meeting room, simplified PM figure opposite
Expression: 😑 Deadpan
Detail: PM pointing at roadmap while Uche sits calmly

**7. Founder/CTO Life**
Scene: Home office or co-working space, multiple screens, organized chaos
Expression: 😐 Neutral (calm in chaos)
Detail: Floating labels around screens: "Hiring" / "Product" / "Investor Call" / "Deploy"

---

## 5. MASTER AI PROMPTS

### Base Prompt (Long-Form — 16:9)

```
A minimalist flat cartoon illustration, 16:9 cinematic composition, of a Black male CTO
with a slim oval face, short low haircut, subtle mustache and goatee, wearing a neon purple
hoodie with a small white </> logo on the left chest, matte black cap, dark pants, and
white sneakers. [EXPRESSION]. [BACKGROUND SETTING — e.g. modern office, meeting room, late
night desk, coffee shop]. Clean vector art style, minimal shading, flat colour fills.
Background is simpler and less saturated than the character — the purple hoodie is the most
vivid element. Consistent character design matching reference image. [SCENE DESCRIPTION].
[PROPS].
```

### Base Prompt (Shorts — 9:16)

```
A minimalist flat cartoon illustration, 9:16 vertical composition, close-up framing, of a
Black male CTO with a slim oval face, short low haircut, subtle mustache and goatee, wearing
a neon purple hoodie with a small white </> logo on the left chest and a matte black cap.
[EXPRESSION]. [BACKGROUND SETTING — simplified, soft blur]. Clean vector art style, minimal
shading, flat colour fills. Character fills 60% of frame — tight crop, face and upper body
prominent. Background is simpler and less saturated than the character. [SCENE DESCRIPTION].
[PROPS].
```

### Base Prompt (Thumbnail)

```
A minimalist flat cartoon illustration, 16:9 composition optimised for YouTube thumbnail, of
a Black male CTO with a slim oval face, short low haircut, subtle mustache and goatee,
wearing a neon purple hoodie with a small white </> logo on the left chest and a matte black
cap. [EXPRESSION — exaggerated for thumbnail]. [BACKGROUND — dark preferred for thumbnail
contrast, strong purple neon glow, high contrast]. Character positioned left or right third
of frame, leaving space for text overlay. Clean vector art, bold lines, face clearly visible
and expressive.
```

### Prompt Assembly Rule

For every image generation call, construct the prompt as:

1. Start with the appropriate base prompt (16:9, 9:16, or thumbnail)
2. Replace `[EXPRESSION]` with one from the expression system
3. Replace `[SCENE DESCRIPTION]` with the specific scene context
4. Replace `[PROPS]` with max 2 props from the optional props list
5. Append the character reference image for Gemini consistency

---

## 6. THUMBNAIL RULES

### Every Thumbnail Must Have:

- Character clearly visible (face + expression readable at mobile size)
- High contrast background (dark preferred for thumbnails, but not mandatory)
- One clear emotion from the expression system (slightly exaggerated for thumbnail)
- **4-6 words of text** — white, bold, uppercase
- Text positioned on the opposite side of the character (character left = text right, or vice versa)
- Purple outer glow or subtle drop shadow on text for readability

### Thumbnail Text Style:

- Font: Bold sans-serif (Impact, Bebas Neue, or similar high-impact typeface)
- Colour: White (#FFFFFF)
- Effect: Subtle purple outer glow
- One or two words in the accent colour (Cyan #4ECDC4 or Amber #FFB830) for emphasis
- No more than 2 lines of text

### Thumbnail Don'ts:

- No cluttered backgrounds
- No more than 6 words
- No small or thin fonts
- No text overlapping the character's face
- No additional characters competing for attention

---

## 7. SHORTS-SPECIFIC RULES

### Framing

- 9:16 vertical, character fills 60% of frame
- Tighter crop than long-form (face and upper torso)
- Background simplified (soft blur, minimal detail — can be light or dark)

### Structure

- **Hook frame (0-2s):** Bold text overlay on screen, no character — just the provocative statement
- **Content frames:** Character + scene as normal
- **CTA frame (last 3s):** "Full breakdown on the channel" or "Link in bio" with channel name and subscribe prompt

### Captions

- Larger font than long-form (readable on mobile without fullscreen)
- Centered in lower third
- Word-by-word highlight style (matching Narrow Path karaoke system)
- Purple highlight colour on active word

---

## 8. BRAND POSITIONING

Every visual output should communicate:

- "This is not tutorial content"
- "This is real dev life"
- "This person understands what I'm going through"
- "Calm authority, not rage-bait"

The tone is a developer who has earned the right to speak — through years of building, shipping, breaking things, and learning. Never preachy, never panicked. Just honest.
