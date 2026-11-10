# **DESIGN.md v2.2**
**Version:** 2.2
**Name:** FlowlyStack DesignSystem
**Description:** A dual‑mode, modern, engineered design system for FlowlyStack, built on plain HTML/CSS/JS. Light Mode uses a mint‑navy palette with clean surfaces; Dark Mode uses a deep-tech blue‑cyan palette with a premium dark canvas. Typography is built on Google Sans Flex (display), Roboto Condensed (body/UI), and JetBrains Mono (code). The system is token‑driven, component‑first, and agent‑ready.

---

## 🎨 **Colors**

Each mode has two layers:
- **Palette tokens**: the raw brand colors.
- **Role tokens**: what a color is *for*. Components reference role tokens first. Both modes define the same role names (dual‑mode parity).

### **Light Mode (`colors-light`)**
```yaml
colors-light:
  # Palette
  primary-mint: "#36ECDE"
  primary-mint-soft: "#7DE2DF"
  navy: "#00203F"
  gray-soft: "#E6E9EC"
  graphite: "#2F2F2F"
  canvas: "#FFFFFF"
  canvas-soft: "#F9FAFB"
  text-primary: "#2F2F2F"
  text-secondary: "#3F3F3F"
  text-muted: "#4F4F4F"
  hairline: "#D9D9D9"
  hairline-strong: "#C3C3C3"

  # Roles
  accent: "{colors-light.primary-mint}"            # fills only: buttons, pills, highlights
  accent-hover: "{colors-light.primary-mint-soft}"
  on-accent: "{colors-light.text-primary}"         # text on accent fills (9.06:1)
  link: "{colors-light.navy}"                      # accent-colored text, links (16.43:1)
  focus-ring: "{colors-light.navy}"
  surface-muted: "{colors-light.gray-soft}"        # code blocks, secondary hover
  code-text: "{colors-light.graphite}"
  disabled-bg: "{colors-light.gray-soft}"
  disabled-text: "{colors-light.text-muted}"
```

### **Dark Mode (`colors-dark`)**
```yaml
colors-dark:
  # Palette
  primary-coldblue: "#7DE2DF"
  primary-laguna: "#35ACBE"
  canvas: "#1A1D2E"
  canvas-soft: "#12141F"
  surface-muted: "#22263A"                         # NEW v2.2: Dark counterpart of light gray-soft
  text-primary: "#F9FAFB"
  text-secondary: "#E0E4EE"
  text-muted: "#BCC1D3"
  hairline: "#2A2D3C"
  hairline-strong: "#3A3D4E"

  # Roles
  accent: "{colors-dark.primary-laguna}"           # fills only: buttons, pills, highlights
  accent-hover: "{colors-dark.primary-coldblue}"
  on-accent: "{colors-dark.canvas}"                # text on accent fills (6.19:1; 10.97:1 on hover)
  link: "{colors-dark.primary-coldblue}"           # accent-colored text, links (10.97:1)
  focus-ring: "{colors-dark.primary-coldblue}"
  code-text: "{colors-dark.text-secondary}"        # 11.73:1 on surface-muted
  disabled-bg: "{colors-dark.hairline-strong}"
  disabled-text: "{colors-dark.text-muted}"
```

### **Mode mapping (parity reference)**
| Role | Light | Dark |
|---|---|---|
| Brand deep / emphasis | `navy` | `text-primary` |
| Muted surface | `gray-soft` | `surface-muted` |
| Code text | `graphite` | `text-secondary` |
| Accent fill | `primary-mint` | `primary-laguna` |
| Accent hover | `primary-mint-soft` | `primary-coldblue` |

### **Linkshell canvas**
Block tiles on the Linkshell canvas use role tokens defined in all three `tokens.css` blocks (light, dark via media query, `data-theme="dark"`):

| Role | Token | Light | Dark |
|---|---|---|---|
| Spec and Note tile / sticky note | `--tile-amber-bg`, `--tile-amber-ink` | `#FAEEDA` / `#854F0B` | `#3a2f17` / `#FAC775` |
| Reference tile | `--tile-violet-bg`, `--tile-violet-ink` | `#EEEDFE` / `#534AB7` | `#2a2750` / `#AFA9EC` |
| Frame tint | `--canvas-frame` | `rgba(0,32,63,.03)` | `rgba(53,172,190,.05)` |
| Grid dot | `--canvas-dot` | `hairline` | `hairline` |

Prompt tiles use the accent, Start tiles the `ok` green, links `--link` (order, solid) and `--text-muted` (context, dashed). These are canvas roles only; do not use them for page chrome.

Canvas patterns (`.lk-*` classes in `app.css`, sizes from `--fs-*` tokens only):
- **Cards are HTML in one transformed layer** (`translate()` and `scale()` from d3-zoom); links are SVG paths in a layer beneath with the same transform; the grid is a CSS background that follows pan and zoom. Colours come from CSS variables, so a theme switch needs no redraw.
- **Block tile:** a 24px rounded icon tile (`.lk-tile`), the title, then small chips (agent, "N ctx"). Status shows as a round dot: empty (To do), play (Ready), tick (Done), minus (Skipped).
- **Frames (phases)** are tinted rectangles with a title and a done count; blocks move with them. **Ports** are the dots on a card's edge: drag from one to link, drop on empty canvas for the quick-add menu.
- **Toolbars float over the canvas** (`.lk-ctl`): add tools left, zoom bar bottom left, minimap bottom right. The block panel opens on the right and follows the selection.
- **Views share one plan:** Canvas, Follow and Outline sit in one segmented control in the header and edit the same graph. Header actions are bordered icon buttons; Export opens a `pr-more` menu (Export Markdown, Export JSON).
- **Outline rows** are 40px, indented 26px per level; the page never scrolls, only the list.

### **Contrast rules (WCAG AA)**
- Body text on its background: ≥ **4.5:1**. Large text (≥ 24px, or ≥ 18.66px bold) and UI outlines/focus rings: ≥ **3:1**.
- **Never** use `primary-mint` or `primary-mint-soft` as text on Light surfaces (1.48:1). Use `link` (navy) instead.
- **Never** use `text-primary` on Dark `accent` (2.58:1). Use `on-accent`.
- Small text is the weakest link: `text-muted` is about **8:1** on Light and **9.3:1** on Dark, `text-secondary` about 10.5:1 and 13:1 (raised 2026-11-08 so small descriptions stay clear). Do not lighten them again.
- Disabled elements are exempt from WCAG contrast, but must still be readable (≥ 3:1 target).

---

## 🧩 **Typography**

### **Font loading**
- **Google Sans Flex**: load the variable font (Google Fonts, or self-hosted in `/fonts`).
- **Roboto Condensed**: load the **variable** font with the weight axis (`wght@100..900`). Weight `360` needs it. If only static weights are available, `360` falls back to `400`.
- **JetBrains Mono**: weight `400`.
- Use `font-display: swap` for all faces.

```yaml
typography:
  families:
    display: "Google Sans Flex, sans-serif"
    body: "Roboto Condensed, sans-serif"
    code: "JetBrains Mono, monospace"

  # Display scale (Google Sans Flex)
  display-xxl:
    fontFamily: "{typography.families.display}"
    fontSize: 48px
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: -1.2px

  display-xl:
    fontFamily: "{typography.families.display}"
    fontSize: 36px
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: -0.8px

  display-lg:
    fontFamily: "{typography.families.display}"
    fontSize: 28px
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: -0.5px

  display-md:
    fontFamily: "{typography.families.display}"
    fontSize: 22px
    fontWeight: 400
    lineHeight: 1.25
    letterSpacing: -0.3px

  display-sm:
    fontFamily: "{typography.families.display}"
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: -0.2px

  # Body scale (Roboto Condensed)
  body-lg:
    fontFamily: "{typography.families.body}"
    fontSize: 18px
    fontWeight: 360
    lineHeight: 1.55

  body-md:
    fontFamily: "{typography.families.body}"
    fontSize: 16px
    fontWeight: 360
    lineHeight: 1.5

  body-sm:
    fontFamily: "{typography.families.body}"
    fontSize: 14px
    fontWeight: 360
    lineHeight: 1.45

  # Button text (Google Sans Flex)
  button-text:
    fontFamily: "{typography.families.display}"
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: -0.2px

  button-text-sm:
    fontFamily: "{typography.families.display}"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: -0.1px

  # Code scale (JetBrains Mono)
  code-lg:
    fontFamily: "{typography.families.code}"
    fontSize: 20px
    fontWeight: 400
    lineHeight: 1.5

  code-md:
    fontFamily: "{typography.families.code}"
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.5

  code-sm:
    fontFamily: "{typography.families.code}"
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.45
```

### **Display step-down by breakpoint**
| Token used on desktop | Large tablet | Small tablet | Mobile |
|---|---|---|---|
| `display-xxl` | `display-xl` | `display-lg` | `display-md` |
| `display-xl` | `display-lg` | `display-md` | `display-sm` |
| `display-lg` | `display-md` | `display-md` | `display-sm` |
| `button-text` | `button-text` | `button-text-sm` | `button-text-sm` |

---

### **Workspace type scale (the FlowlyStack app)**

Approved on the Prompt Library and Trash pages, and used app-wide. These are CSS tokens in `frontend/css/tokens.css`
(`--fs-*`, the same in light and dark). **Never write a bare `px` font size in `app.css`; pick a role below.** If a new
screen needs a size that is not here, add a role here and in `tokens.css` first.

| Token | px | Used for |
|---|---|---|
| `--fs-nano` | 10 | Sidebar group labels, live-card titles |
| `--fs-micro` | 11 | Tags, table headers, footer, badges, chart axis text |
| `--fs-caption` | 12 | Mono captions: pills, counts, legends, field labels, chips |
| `--fs-label` | 13 | Mono labels: card headings, sort headers, status lines, clock, breadcrumbs |
| `--fs-meta` | 14 | Row meta line, small body, notes, tables, tooltips, secondary buttons |
| `--fs-control` | 15 | Inputs, pager, toolbar titles, Trash buttons, toasts, code blocks |
| `--fs-body` | 16 | Row preview and note, menu items, dialog text, buttons |
| `--fs-intro` | 17 | Page intro paragraph |
| `--fs-card-title` | 17 | Card headings (mono, uppercase): Usage Limits, Sessions, Capture setup |
| `--fs-lead` | 18 | Brand name |
| `--fs-row-title` | 20 | List row title (Prompt Library, Trash) |
| `--fs-title-sm` / `--fs-title-md` | 22 / 28 | Mobile h1 / prompt title on the detail page |
| `--fs-page-title` | 36 | Page h1 |
| `--fs-kpi` | 38 | Dashboard KPI numbers |

**Letter spacing (tracking) at small sizes.** Roboto Condensed is a narrow face, so at 10 to 16 px it reads tight with no spacing.
Every small role has a matching `--track-*` token in `tokens.css`, and the rule that sets `font-size: var(--fs-X)` on body-font
text also sets `letter-spacing: var(--track-X)`. Approved in `mockup/letter_spacing_mockup.html` (option C, graded: the smaller
the text, the more air).

| Token | Tracking | Token | Tracking |
|---|---|---|---|
| `--track-nano` (10 px) | +0.04em | `--track-meta` (14 px) | +0.02em |
| `--track-micro` (11 px) | +0.035em | `--track-control` (15 px) | +0.012em |
| `--track-caption` (12 px) | +0.03em | `--track-body` (16 px) | +0.006em |
| `--track-label` (13 px) | +0.025em | 17 px and larger | none (titles keep their own tracking) |

- Rules that use the code font (JetBrains Mono) or the display font, or that already set their own `letter-spacing` (mono labels, pills, kbd badges, headings), are left alone.
- A new rule that sets a small `--fs-*` size on body-font text adds the matching `--track-*`. Never write a bare `em` tracking value in `app.css`.
- The body carries `--track-body`, so plain 16 px text inherits it.

**Page patterns**
- **Width:** every page uses the same column (`--container-max`, 1760px) and gutter, so the Dashboard, Prompt Library and
  Trash line up with the panel edges. Do not give one page its own max width.
- **List rows** (`.pr-row`): title `--fs-row-title`, meta line `--fs-meta` in mono, preview and note `--fs-body`; hover
  shows the edge glow. The Trash page reuses these classes unchanged, so the two pages cannot drift apart.
- **⋯ menus** (`.pr-menu`): a rounded `--canvas` panel, items at `--fs-body`, a mono `--fs-caption` header, hover glow.
  Destructive items turn `--crit` on hover. They are `<details>` dropdowns that close on an outside click or Esc.
- **Status chip** (`.st-status`, Prompt Studio): a small bordered label in `--fs-caption` mono with a dot: Draft `--text-muted`, Refined `--link`, Final `--ok`. The dot carries the colour, never the text. The status control on the detail page is the existing `.seg` group.
- **Cards that fill in** (Studio Documentation, Fill variables): `.card` with `.pl-label` field labels and `.pl-input`; a variable's own label (`.st-var`) is mono and never uppercased, because the name is data.
- **Prompt text boxes** (`.pr-text`, `.pr-view`, `.pl-area`, Trash preview): the body font, because a prompt is prose. The code font (JetBrains Mono) stays for code, labels, meta lines and the diff.
- **Sidebar (auto-hide):** it always lands as the 68px icon strip (`.app.collapsed`). Pointer on the strip (120 ms) or keyboard focus adds `.peek`, which opens the full 248px sidebar as an **overlay** over the page (`z-index` 30, opaque `--canvas-soft`, `--shadow-lg`); leaving closes it after 300 ms. A negative right margin keeps its layout footprint at 68px, so the page never shifts and charts never redraw. It stays open while the account menu, a dialog (⌘K) or keyboard focus is inside, and never opens while a mouse button is held. The top-bar button pins it open for the visit only (nothing is saved; a pinned sidebar takes its 248px). Under 768px a pinned sidebar is an overlay too and closes on a tap outside or on a page link. Rules that hide labels in the strip use `.app.collapsed:not(.peek)`. While it is open a faint layer (`--scrim`, token in all three blocks of `tokens.css`, `.app::after`, ignores the pointer) dims the page so the covered content reads as behind the sidebar, and the icon links' `title` tooltips are set aside (`labelsShown` in `main.js`).
- **Settings page** (`#/settings/<section>`): a two-column shell like Open WebUI's: a left column with Back, a search box and grouped section links (`.set-navitem`), and a right pane with the section title, rows of label, one-line description and control (`.set-row`), and a sticky Save bar. Rows of one run can sit under a mono uppercase heading (`.set-groupname`, `--fs-label`, muted): Keyboard uses Global, Prompt editor and Assistant. A value set by an environment variable or the config file carries a small tag (`.set-tag`). The account button at the bottom of the sidebar opens a small ⋯-style menu (Settings, day or night mode). **Connection cards** (`.set-conn`, Connections > Other runtimes): a `--canvas-soft` card with a hairline border, the name, mono `.set-tag` chips (kind, Local or Remote, Key set), the address in mono `--fs-label`, a status line (`.set-ok` / `.set-bad` / muted) and compact buttons (`--ctl-compact-h` + 6px, `--fs-caption`, quiet `--hairline-strong` border, `--edge` on hover). Add connection opens a `formDialog` with a Runtime list that fills in the name and address (a centred dialog never runs off the screen as a drop-down menu can); Add and Edit save at once.
- **Shortcut badges** (`.kbd`, `--fs-micro` mono, hairline border): shown on every button that has a shortcut and inside every search bar (`.srch`, `--fs-label`, hidden once something is typed). On a pressed (teal) button the label and badge use `--on-accent-strong` (black in both modes) for contrast.
- **Editor footer row** (`.pr-foot`): under the text box, the word count and save message on the left (`.pr-footl`) and the buttons on the right (`.pr-footr`), Save last. Dialogs (`formDialog`, `.cb-dialog`) are used for Save ("Describe what changed"), Properties, the Library's + Note and Fill variables; Properties rows are `.st-prop` (name cell, value cell, delete).
- **Fitted pages:** the Studio and Library prompt pages fill the window on wide and tall screens so only the text box scrolls; narrower or shorter windows scroll as before.
- **Assistant panel** (`.as-*`, Studio detail page, beside the editor, under it below 1100px): header with a Local or Remote badge and a ⋯ menu, the model picker, a compact **Prompt text** Auto / On / Off segment (`.as-incl`, `--fs-micro`), the chat, and a message box with Send or Stop. Answers carry Use as prompt, Copy and Delete; a Proposed edit card reuses the compare styling.
- **Collections** (`.co-*`, `#/collections`; every size from the `--fs-*` roles, every colour from tokens, both modes):
  - **Home** reuses the Prompt Library list: `.pr-row` rows (`.co-link` grid: icon, name and mono meta line, state column), the **status pill** `.co-pill` (`--fs-caption` mono with a dot: Ready `--ok`, Preparing `--link` with a thin `.co-bar`, Waiting for a model and Add documents muted, Failed `--crit`) and a mono `.co-chip` ("built in") on My prompts, which has no ⋯ menu.
  - **Setup card** (`.co-setup`, the Capture setup card pattern): three steps (`.co-step`, a tick in `--ok` once done), a copyable command (`.co-cmd`, code font) and Check again. It never blocks anything and disappears when finished.
  - **Collection page:** a top bar (`.co-top`) with Back, breadcrumb, name at `--fs-title-md`, mono meta line, and tabs `.co-tab` (mono `--fs-label`, 2px `--accent` underline when on). **Documents tab:** a dashed drop zone (`.co-drop`, `--edge` on hover and drag), an index status strip (`.co-index`, progress `.co-bar.wide`, Cancel), document rows with the same pill.
  - **Chat tab** (`.co-chat`): three columns from 1280px (conversations 200px, thread taking the rest, Sources 260px, gap `--spacing-xl`; the side columns stay narrow so the conversation is the widest), two to 800px (Sources hidden or toggled with its key), one below. The question is a bubble (`.as-user`), the answer plain body text with numbered **citation chips** (`.co-cite`, `.co-chipn`, the same chip in the Sources card; a passage not sent has the muted `.off` chip). Under an answer: Copy, Use as prompt and "N sources". The composer footer holds the model picker (with Local or Remote), the Auto / On / Off segment (`.seg`), the scope chip (`<details class="pr-more">`) and Send, which turns into a red Stop while streaming; a status line states what was sent. A **proposed edit** reuses the Assistant's compare card (`.as-prop`, `.as-diff`). Delete of a conversation asks first (no Undo).
- **Document viewer (`.co-view`, Collections > Documents > a document):** a 260px file list (`.co-vlist`, sticky under the top bar; above the document below 900px) and the document on the right; Preview, Indexed text and Edit are the shared `.seg` at 26px, and while editing `Cancel | Save` replace it (Save is `.btn-primary`). The reading surface (`.co-vbody`, `.co-md`) uses `--fs-body` and tokens only; the editor is a `--fs-label` monospace textarea with a muted line-number gutter and the edge colour as its focus border.
- **Compact controls on the Collections page:** buttons, the model select and the Auto / On / Off segment are 26 to 28px tall (`--fs-label` or `--fs-micro` text), not the 32 to 44px of the shared `.btn`. A page with its own top block (`.co-top`) gets the same top clearance as the Studio and Library detail pages so the 10px fade under the top bar never touches the title; grid blocks that hold wide children need `grid-template-columns: minmax(0, 1fr)`.
- **Both modes:** check every new surface in day and night before calling it done.

### **Firm text (small text on a thin body font)**
Say "use Firm text" and this is what is meant. Added 2026-11-08 after a review of every page in day and night mode.

- **Why.** The body font (Roboto Condensed) is set at weight `360`, so small descriptions look faint even in a strong grey. The grey values (Colors, Contrast rules) are only half of the fix; the other half is weight and size.
- **The recipe**, with tokens in `tokens.css` (same in both modes):
  - `--fw-firm` (**500**): descriptions, hints, counts, notes, status words, captions: anything small that explains something.
  - `--fw-reading` (**450**): text people read at length: document text, chat answers, passage excerpts, list previews, table cells, file names in lists.
  - **Hint lines** that were 14px go to `--fs-control` (15px). Captions and counts that were 12 to 13px go one step up (`--fs-meta` / `--fs-label`).
  - Letter spacing follows the new size (`--track-*` of that size), as always.
- **Never on:** mono labels and headings (`.pl-label`, `.lat-h`, eyebrows), display headings, buttons, chart text and colours (D3 and canvas code set their own), the Dashboard colour tiles' own colours, or text inside prompt or note editors (those keep their own weight).
- **How to apply it to a page.** Add one block at the end of `tokens.css` under the FIRM TEXT banner, scoped to that page (`#page-x` or the page's class): never a global `.muted` or `.small` rule. Match what the page really uses: list the small text first (computed size, weight, family), then pick the selectors. Rules inside `.set-shell`, `.co-page` and the like must beat the shared rule's specificity, because `tokens.css` loads before `app.css`.
- **Done on:** Settings, Collections (home, collection page, document viewer, chat), Lattice (text panels only), Prompt Library and Prompt Studio (including the shared editor and the Assistant panel), Linkshell (side panel, Follow, Outline, and the Reference Note dialog), Dashboard, Trash, Gallery. Also: the four Linkshell file icons (Rename, Note, Open, Remove: 26px button, 18px icon, stroke 2.2, strong grey), and **placeholders** (one global rule: 85% of `--text-muted` over the canvas, about 5.7:1 in day and 7:1 at night, always lighter than typed text).
- **Not done yet:** most dialogs, the command palette, chart axis and legend text, and the small mono labels (10 to 12px). Leave them until the user asks.
- **Checks.** Look at the page in day and night, at 1180x620, and confirm nothing wrapped into a clipped layout. A page that would get taller must still fit its dialog or panel.

## 📐 **Spacing**

The spacing scale is built on a **4px base grid**. `xxs` (2px) is the only exception and is reserved for micro offsets (pill padding, icon nudges).

```yaml
spacing:
  xxs: 2px     # micro offsets only
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  xxxl: 48px   # NEW v2.2: mobile section spacing
  huge: 64px   # tablet/desktop section spacing
```

### **Spacing roles**
| Role | Mobile | Tablet | Desktop |
|---|---|---|---|
| Between sections | `xxxl` | `huge` | `huge` |
| Within a section (block gaps) | `lg` | `xl` | `xl` |
| Inside components (tight / comfortable) | `xs` / `sm` / `md` | `sm` / `md` | `sm` / `md` |

### **Raw pixel rule**
Raw pixel values appear **only** in token definitions (spacing, radius, typography, layout, shadow, focus). Components and generated CSS must reference tokens (as CSS custom properties).

---

## 🟣 **Border Radius**
```yaml
rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  full: 9999px
```

---

## 📏 **Layout**
```yaml
layout:
  container-max: 1200px      # main page content width
  content-max: 720px         # long-form reading width (blog, about)
  gutter:
    mobile: "{spacing.lg}"   # 16px
    tablet: "{spacing.xl}"   # 24px
    desktop: "{spacing.xxl}" # 32px
```
- Containers are `width: 100%`, capped at `container-max`, centered, with `gutter` padding on both sides.

---

## 🌫️ **Elevation (Shadows)**
Shadow colors are derived from each mode's own palette: Light uses `navy`, Dark uses `canvas-soft`.

```yaml
shadow-light:
  sm: "0 1px 2px rgba(0, 32, 63, 0.06)"
  md: "0 4px 12px rgba(0, 32, 63, 0.08)"
  lg: "0 12px 32px rgba(0, 32, 63, 0.12)"

shadow-dark:
  sm: "0 1px 2px rgba(18, 20, 31, 0.40)"
  md: "0 4px 12px rgba(18, 20, 31, 0.50)"
  lg: "0 12px 32px rgba(18, 20, 31, 0.60)"
```
- `sm`: resting cards. `md`: hovered cards, dropdowns. `lg`: overlays, mobile menu.
- In Dark Mode, always pair a shadow with the `hairline` border, because shadows read weakly on dark canvases.

---

## 🎞️ **Motion**
```yaml
motion:
  duration:
    instant: 0ms
    fast: 120ms      # hover, tap feedback, focus
    base: 200ms      # buttons, cards, color changes
    slow: 320ms      # menus, section reveals
  easing:
    standard: "cubic-bezier(0.2, 0, 0, 1)"
    enter: "cubic-bezier(0, 0, 0, 1)"
    exit: "cubic-bezier(0.3, 0, 1, 1)"
  typing:
    char-delay: 50ms     # Hero typing effect, per character
    caret-blink: 1000ms
  scroll:
    behavior: smooth
```
- Animate only `transform`, `opacity` and colors. Never animate layout properties.
- **Reduced motion** (`prefers-reduced-motion: reduce`): all durations become `instant`, the typing effect shows the full text immediately, and `scroll.behavior` becomes `auto`.

---

## 🎯 **Interaction States & Focus**
```yaml
focus-ring:
  width: 2px
  offset: 2px
  style: solid
  color-light: "{colors-light.focus-ring}"
  color-dark: "{colors-dark.focus-ring}"

states:
  hover: "color/shadow change using motion.duration.fast"
  active: "transform: scale(0.98)"           # also the mobile tap animation
  disabled: "disabled-bg + disabled-text, cursor: not-allowed, no hover/active"
```
- Use `:focus-visible` for the focus ring. Never remove focus outlines without replacing them.
- Every interactive element defines **hover, active, focus-visible and disabled** states.
- Hover is never the only way to reveal content (touch devices have no hover).

---

## 🧱 **Components**
Padding values reference spacing tokens.

### **Buttons**
```yaml
button-primary-light:
  backgroundColor: "{colors-light.accent}"
  textColor: "{colors-light.on-accent}"
  typography: "{typography.button-text}"
  rounded: "{rounded.sm}"
  padding: "{spacing.sm} {spacing.lg}"
  hover:
    backgroundColor: "{colors-light.accent-hover}"
  active:
    transform: "scale(0.98)"
  focus: "{focus-ring} with color-light"
  disabled:
    backgroundColor: "{colors-light.disabled-bg}"
    textColor: "{colors-light.disabled-text}"

button-primary-dark:
  backgroundColor: "{colors-dark.accent}"
  textColor: "{colors-dark.on-accent}"
  typography: "{typography.button-text}"
  rounded: "{rounded.sm}"
  padding: "{spacing.sm} {spacing.lg}"
  hover:
    backgroundColor: "{colors-dark.accent-hover}"
  active:
    transform: "scale(0.98)"
  focus: "{focus-ring} with color-dark"
  disabled:
    backgroundColor: "{colors-dark.disabled-bg}"
    textColor: "{colors-dark.disabled-text}"

button-secondary-light:
  backgroundColor: "transparent"
  textColor: "{colors-light.text-primary}"
  border: "1px solid {colors-light.text-primary}"
  typography: "{typography.button-text}"
  rounded: "{rounded.sm}"
  padding: "{spacing.sm} {spacing.lg}"
  hover:
    backgroundColor: "{colors-light.surface-muted}"
  active:
    transform: "scale(0.98)"
  focus: "{focus-ring} with color-light"
  disabled:
    textColor: "{colors-light.disabled-text}"
    border: "1px solid {colors-light.hairline}"

button-secondary-dark:
  backgroundColor: "transparent"
  textColor: "{colors-dark.text-primary}"
  border: "1px solid {colors-dark.text-primary}"
  typography: "{typography.button-text}"
  rounded: "{rounded.sm}"
  padding: "{spacing.sm} {spacing.lg}"
  hover:
    backgroundColor: "{colors-dark.surface-muted}"
  active:
    transform: "scale(0.98)"
  focus: "{focus-ring} with color-dark"
  disabled:
    textColor: "{colors-dark.disabled-text}"
    border: "1px solid {colors-dark.hairline}"
```

### **Kind colour chips (Lattice kinds manager)**

A kind has two colours, one per mode. They are shown as two small square chips side by side (36px, `--radius-md`): the **light chip** has a white surface and the **dark chip** the dark canvas colour, written out as literals because the chip must look the same in both modes (it previews the other mode). Inside is a triangle in the kind's colour; a click opens the app's own picker (`.kp-pop`, `colour-picker.js`, theme tokens only: never the browser's `<input type="color">` popup, which shows an unstyleable white edge on the dark theme). Focus and hover use the standard 3px edge ring. The user's colours are data, never tokens. Code: `.kd-chip` in `app.css`, `frontend/js/lattice/kinds-dialog.js`.

### **Section header with its action (Lattice controls)**

A panel section's label sits on the left and its one action on the right of the SAME line (`.lat-head`, the label keeps `.lat-h`): Filters with Deselect all, Layout with the current layout's name (a button that opens a choice dialog), Show with Edit colours, Entity kinds with Edit kinds. It saves a row per section and keeps every section's action in the same place. The action is a Glow button. A section with a long explanation gets it as one muted line under the header, shown only when it applies.

### **Choice dialog (one choice, a picture per option)**

`choiceDialog()` in `frontend/js/dialog.js`: the standard dialog frame, a radio group of rows (picture 132 x 88, name in `--fs-body`, one explanation line in `--fs-label`, a tick on the current one), Close at the bottom right. **It follows the window (the rule for EVERY dialog):** never taller than the window (`max-height: calc(100dvh - 24px)`, so browser zoom in, which shrinks the window in CSS pixels, never pushes Close off screen), the list scrolls inside while the title and Close stay put, and the pictures shrink with the height (`--opt-h: clamp(52px, 11dvh, 88px)`). Choosing closes it at once (no Done). Hover, focus and the chosen row use the Glow button look (edge border, tint, glow). Arrow keys move, Enter or Space and the number keys choose.

### **Glow button (the named button style: call it out, never reinvent it)**

**Name: Glow button.** Approved by the user on the Gallery's Open / Tag / Promote buttons and the Settings page (2026-11-05). It is the button of every new feature unless the user names another. In code: `class="btn btn-sm btn-glow"` (`frontend/css/app.css`, end of file). Do not write a new button style, a per-page override, or a resting glow.

| State | What you see |
|---|---|
| Rest | 20px tall (`--ctl-compact-h`), 12px text (`--fs-caption`, `--track-caption`), quiet `--hairline-strong` border, `--radius-xs`, **no glow, no shadow, no teal** |
| Hover (pointer over it) | **All three together:** border becomes `--edge`, a soft tint (`--edge` at 14%), and the glow (`0 0 16px var(--edge-soft)`). This is the "light up"; never only the border, never only the glow |
| Chosen (`aria-pressed="true"` or `.on`) | `--edge` border and `--edge-soft` fill, **normal text colour** (never the global teal fill with black text: it is unreadable on dark) |
| Keyboard focus | `:focus-visible` outline ring only; a mouse click leaves no ring |
| Disabled | 45% opacity, no hover effect |
| Copy failed (`.fail`) | `--crit` border and text |

**Sizes.** Default 20px. **Medium: add `btn-glow-md`** (`class="btn btn-sm btn-glow btn-glow-md"`): the same look at 28px with 13px text (`--fs-label`), for a control that stands alone and carries its own label (first use: the Dashboard agent picker, 2026-11-05). A larger size is not built.

Where it applies: row and card actions, toolbar and form-side buttons, Settings (all sections), segmented toggles. **The Glow button is the app's default button; only its size changes with where it sits** (default 20px for rows, cards and dense toolbars; `btn-glow-md` 28px for standalone controls). The Glow sweep (2026-11-07) moved Library, Studio, Linkshell, Trash and Collections to it: the prompt page's Back, version picker, tool buttons, Copy, ⋯, Save, Compare and Edit as new version; "+ New prompt", "+ New project", Import, Tags; every Collections button; the Live sync switches (`.pl-switch`, same look). This replaces the older rule that Save, Done and "New ..." stay `.btn-primary`. Not converted yet (not decided, not a rule): star toggles, the round Stop button, menu items, tabs, sort headers and citation chips. **Settings is converted (2026-11-08):** every button in every Settings section, and the sticky Save bar (`btn-glow-md`), is `btn btn-sm btn-glow`; the old per-page override in `app.css` and the teal `btn-primary` Save are gone. Back keeps its own page-level size. **Dialog buttons are converted (2026-11-08):** every dialog built with `confirmDialog`, `formDialog` and `choiceDialog` in `dialog.js` uses `btn btn-sm btn-glow btn-glow-md` for Cancel, Done and the main action (no filled teal button, no resting glow); a danger confirm adds `btn-danger`. An icon inside is 14px. Checklist when a feature adds a button: (1) the class above, (2) hover shows border + tint + glow, (3) nothing glows at rest, (4) a chosen state is readable in both themes, (5) text is larger than the control looks (see below).

### **Rule for every new page: all labelled buttons are Glow buttons (2026-11-09)**

The Glow sweep is finished: every labelled button in the app (Settings and its Save bar, the dialogs, Studio, Linkshell Follow, Outline and panel, Gallery, the Dashboard Table toggle, the Assistant proposal bar) is `class="btn btn-sm btn-glow"` (add `btn-glow-md` for a standalone control, `btn-danger` for a destructive one). A new page or dialog **must not** use the older styles: `btn-primary` (the filled teal button), a bare `btn btn-sm`, or a per-page override that sizes or colours buttons by hand (`#page-x .btn-sm {...}`). If a rule like that is needed, the Glow rules at the end of `app.css` are what to change, once, for the whole app.

What stays outside it on purpose: icon-only buttons (`icon-btn`: stars, the ⋯ menus, trash, copy, close, arrows, the sidebar, day/night and sign-out buttons in the top bar), the round Stop/Send button, menu items, tabs, sort headers, citation chips, the segmented `.seg` toggles, switches, and Settings' page-level Back button.

**Quick check before committing a page:** search for `class="btn` without `btn-glow` and for `btn-primary` in the files you touched; the only hits should be `icon-btn` and the Settings Back button.

### **Destructive Glow button**

`.btn-glow.btn-danger` (and `.btn-glow.pr-del`): red text (`--crit`) at rest, and on hover a red border, a 14% red tint and a red glow instead of the edge colour. One shared rule at the end of `app.css`. Used by Trash (Delete forever, Empty trash) and Collections Delete. Never a red fill; nothing glows at rest.

### **Status light (flashing dot)**

A small dot that says whether something is connected or ready, and **flashes** (the `flash` keyframe, `--c` sets the glow colour; `prefers-reduced-motion` already stops it, leaving a solid dot). Green (`--ok`, 1.8 s) = connected / ready; red (`--crit`, 1.1 s, a little quicker) = disconnected / failed; Remote models keep a steady amber (`--warn`) dot. Where: the Studio Assistant badge (`.as-badge`: "Local" green; **"Disconnected" in red when no model server answers, the badge never disappears then**), and the Collections pills (`.co-pill.ok i` Ready, `.co-pill.bad i` Failed) on the list and on document rows. Working / waiting pills (`work`, `wait`) stay still. **A light that shows a live connection must follow it without a page refresh** (the Assistant badge checks every 5 s). Add a new status light by reusing these rules, not a new animation.

### **Icon-only Glow button**

For a repeated row action whose meaning is clear from the icon (delete, add, restore): `class="btn btn-sm btn-glow btn-glow-md btn-glow-icon"`, 28px square, a 14px stroke icon, and **always an `aria-label` and a `title`** (the words stay for screen readers and on hover). First use: the Entity kinds manager (trash, plus, undo arrow; a lock for "Other", which is kept). Text buttons stay for actions that need a word (Reset to defaults, Edit colours, Done).

### **Compact controls (buttons, chips) and the text-versus-control rule**

Approved on the Gallery (2026-11-04). **The text is always a little larger than the control looks; the control is never bigger than its text suggests.** Never small text with a large button. Tokens are in `frontend/css/tokens.css` (same in light and dark); use them, never a bare `px` height.

| Token | px | Used for | Text inside |
|---|---|---|---|
| `--ctl-compact-h` | 20 | Row and card action buttons (Open, Tag, Promote, Select), segmented toggles (Topic / Type, Documents / Passages), the Gallery mode switch (Prompts / Documents: two chips right-aligned above the numbers, the active one `.on`, a disabled one at half opacity) | `--fs-caption` (12) with `--track-caption` |
| `--ctl-chip-h` | 22 | Filter chips (agent, active-filter and Clear all pills) | `--fs-caption` (12) with `--track-caption` |

Rules for a compact control:
- Height from the token above, horizontal padding `--spacing-sm` (buttons) or `--spacing-md` (chips), `line-height: 1`, radius `--radius-xs` for buttons and `--radius-full` for chips.
- Text is `--fs-caption`, smaller than the text it sits beside (rows use `--fs-meta`, 14). Standard buttons (`.btn`, 44px; `.btn-sm`, 32px) stay for page-level actions, forms and dialogs.
- **Rest:** quiet border `--hairline-strong`, no glow, no shadow. **Hover:** the border becomes `--edge` (chips also get the `--glow-r` glow); nothing glows until the pointer is over it. **Pressed or chosen** (`.on`, `aria-pressed`): `--edge` border with the `--edge-soft` fill.
- **Settings (every section):** all `.btn-sm` buttons in `#page-settings` use this control (20px, 12px text, quiet border at rest; on hover the edge border, a soft tint and the glow, exactly like the Gallery Open / Tag / Promote buttons, `--edge-soft` fill with normal text when `aria-pressed`), as do the `.seg` buttons and the shortcut recorders; Back keeps its size but rests quiet; the Save bar button and dialogs keep the standard size. The global teal "pressed" fill (black text) is not used there.
- The keyboard `:focus-visible` ring stays (see "Interaction States & Focus"); this rule only removes the resting glow.
- Compact does not mean a small hit area on touch: below 1100px keep the same size but leave at least 8px between controls.

### **Links**
```yaml
link-light:
  textColor: "{colors-light.link}"
  textDecoration: "underline on hover and focus"
  focus: "{focus-ring} with color-light"

link-dark:
  textColor: "{colors-dark.link}"
  textDecoration: "underline on hover and focus"
  focus: "{focus-ring} with color-dark"
```

### **Cards**
```yaml
card-light:
  backgroundColor: "{colors-light.canvas-soft}"
  textColor: "{colors-light.text-primary}"
  rounded: "{rounded.lg}"
  padding: "{spacing.xxl}"           # mobile: "{spacing.lg}"
  border: "1px solid {colors-light.hairline}"
  shadow: "{shadow-light.sm}"
  hover:
    shadow: "{shadow-light.md}"
    border: "1px solid {colors-light.hairline-strong}"

card-dark:
  backgroundColor: "{colors-dark.canvas-soft}"
  textColor: "{colors-dark.text-primary}"
  rounded: "{rounded.lg}"
  padding: "{spacing.xxl}"           # mobile: "{spacing.lg}"
  border: "1px solid {colors-dark.hairline}"
  shadow: "{shadow-dark.sm}"
  hover:
    shadow: "{shadow-dark.md}"
    border: "1px solid {colors-dark.hairline-strong}"
```

### **Inputs**
```yaml
text-input-light:
  backgroundColor: "{colors-light.canvas}"
  textColor: "{colors-light.text-primary}"
  border: "1px solid {colors-light.hairline}"
  rounded: "{rounded.sm}"
  padding: "{spacing.sm} {spacing.md}"
  hover:
    border: "1px solid {colors-light.hairline-strong}"
  focus: "{focus-ring} with color-light"
  disabled:
    backgroundColor: "{colors-light.disabled-bg}"
    textColor: "{colors-light.disabled-text}"

text-input-dark:
  backgroundColor: "{colors-dark.canvas-soft}"
  textColor: "{colors-dark.text-primary}"
  border: "1px solid {colors-dark.hairline}"
  rounded: "{rounded.sm}"
  padding: "{spacing.sm} {spacing.md}"
  hover:
    border: "1px solid {colors-dark.hairline-strong}"
  focus: "{focus-ring} with color-dark"
  disabled:
    backgroundColor: "{colors-dark.disabled-bg}"
    textColor: "{colors-dark.disabled-text}"
```

### **Navigation**
```yaml
nav-light:
  backgroundColor: "{colors-light.canvas}"
  textColor: "{colors-light.text-primary}"
  padding: "{spacing.lg} {spacing.xl}"
  typography: "{typography.body-md}"
  hover:
    textColor: "{colors-light.link}"

nav-dark:
  backgroundColor: "{colors-dark.canvas}"
  textColor: "{colors-dark.text-primary}"
  padding: "{spacing.lg} {spacing.xl}"
  typography: "{typography.body-md}"
  hover:
    textColor: "{colors-dark.link}"
```

### **Code Blocks**
```yaml
code-block-light:
  backgroundColor: "{colors-light.surface-muted}"
  textColor: "{colors-light.code-text}"
  typography: "{typography.code-md}"   # mobile: "{typography.code-sm}"
  rounded: "{rounded.sm}"
  padding: "{spacing.lg}"

code-block-dark:
  backgroundColor: "{colors-dark.surface-muted}"
  textColor: "{colors-dark.code-text}"
  typography: "{typography.code-md}"   # mobile: "{typography.code-sm}"
  rounded: "{rounded.sm}"
  padding: "{spacing.lg}"
```

### **Pills / Tags**
```yaml
pill-accent-light:
  backgroundColor: "{colors-light.accent}"
  textColor: "{colors-light.on-accent}"
  typography: "{typography.body-sm}"
  rounded: "{rounded.full}"
  padding: "{spacing.xxs} {spacing.sm}"

pill-accent-dark:
  backgroundColor: "{colors-dark.accent}"
  textColor: "{colors-dark.on-accent}"
  typography: "{typography.body-sm}"
  rounded: "{rounded.full}"
  padding: "{spacing.xxs} {spacing.sm}"
```

---

## 📱 **Responsive Behavior**

### **Breakpoints (single source of truth)**
```yaml
breakpoints:
  mobile: "0–480px"
  small-tablet: "481–768px"
  large-tablet: "769–1024px"
  desktop: "1025–1440px"
  wide: "1441px+"
```
Implement these with CSS media queries. Use `max-width: 480px`, `max-width: 768px`, `max-width: 1024px` and `min-width: 1441px`.

### **Global rules**
- Display sizes step down according to the **Display step-down** table (Typography).
- Navigation collapses to a hamburger menu at **≤ 768px**. Above 768px, nav items stay inline and may wrap if needed.
- Cards stack 1‑up at **≤ 768px**.
- Code blocks scroll horizontally on mobile. They are the only element allowed to scroll horizontally.
- Light/Dark tokens swap at system level via `prefers-color-scheme`.

---

## 📱 **Mobile Optimization**

All components, layouts and sections must support mobile, tablet and desktop. These rules apply globally to every page, section and component.

### **Global mobile behavior (0–480px)**
- All layouts collapse into a **single-column** flow.
- Horizontal spacing converts into **vertical spacing**.
- Typography scales down per the **Display step-down** table.
- No horizontal overflow. No horizontal scrolling for text.
- Cards fit the viewport width.
- Images scale proportionally.

### **Mobile layout rules**
- **Hero:**
  - Title → `display-sm` or `display-md`
  - Subtitle → `body-md` or `body-sm`
  - Typing effect must not overflow
  - Header stays fixed
- **Lab Preview:**
  - Cards stack vertically
  - Gaps between cards use `md` or `lg`
  - Icons scale down
  - CTA becomes full-width (`100%`)
- **Back to Top icon:**
  - Moves inward slightly for thumb reach
  - Minimum tap target: `44px × 44px`
- **Navigation:**
  - Hamburger menu (see Responsive Behavior)
  - Menu items remain readable at `body-md`
- **Footer:**
  - Content stacks vertically
  - Typography uses `body-sm` or `body-md`
  - Spacing uses `md` or `lg`

### **Mobile spacing rules**
- `xs`: tight (icon to label)
- `sm`: small (inside components)
- `md`: comfortable (between related items)
- `lg`: block gaps inside a section
- `xxxl`: between sections

Use tokens only. Never use raw pixel values (see **Raw pixel rule**).

### **Mobile typography rules**
- Titles → `display-sm`, `display-md`
- Subtitles → `body-md`, `body-sm`
- Card titles → `body-lg`, `body-md`
- Card descriptions → `body-md`, `body-sm`
- CTA → `button-text-sm`

### **Mobile component rules**
All components must:
- scale proportionally
- keep padding on spacing tokens
- avoid fixed widths/heights
- avoid absolute positioning unless necessary
- avoid overlapping content
- maintain hierarchy

### **Mobile interaction rules**
- Tap targets ≥ `44px × 44px`
- The CTA hover animation becomes the `active` tap animation (`scale(0.98)`, `motion.duration.fast`)
- Back to Top icon responds instantly (`motion.duration.fast`)
- No component relies solely on hover

### **Mobile performance rules**
- Avoid large background images; serve responsive sizes
- Use optimized assets
- Avoid heavy animations; respect reduced motion
- Ensure smooth scrolling
- Ensure fast load times

---

## ✔️ **Do’s / Don’ts**
```yaml
Do:
  - Use mint/laguna accents sparingly, as fills
  - Use role tokens (accent, on-accent, link, focus-ring) in components
  - Keep display tracking subtle
  - Pair every small body-font size (`--fs-nano` to `--fs-body`) with its `--track-*` token
  - Use Roboto Condensed for all body/UI
  - Use JetBrains Mono for code
  - Maintain dual‑mode parity (same role names in both modes)
  - Keep spacing on the 4px base grid
  - Define hover, active, focus-visible and disabled states

Don’t:
  - Mix light/dark tokens in one component
  - Overuse mint or laguna
  - Use mint as text on light surfaces, or near-white text on laguna
  - Increase display weight above 400
  - Use overly rounded buttons (> 6px)
  - Use raw pixel values outside token definitions
  - Remove focus outlines without a replacement
```

---

## Iteration guide

1. Add new components using existing tokens
2. Keep typography tiers consistent
3. Maintain color harmony and role parity between modes
4. Expand spacing only if necessary
5. Keep DESIGN.md as the single source of truth
6. Use this document as the reference for any agent or generator
7. Accept changes or modifications to this DESIGN.md only if the user asks for them

---

## Changelog

### v2.2
- **Breakpoints:** merged two conflicting sets into one (mobile / small-tablet / large-tablet / desktop / wide). The hamburger menu and the 1‑up card stack trigger at ≤ 768px.
- **Raw pixels:** component padding now references spacing tokens. Raw px is allowed only in token definitions.
- **Grid:** restated as a 4px base grid; `xxs` (2px) is reserved for micro offsets.
- **Spacing:** added `xxxl` (48px). Defined section spacing roles: mobile `xxxl`, tablet/desktop `huge`. `lg` is now block spacing inside a section.
- **Typography:** nested the scale under `typography:` with `families` so `{typography.*}` references resolve. Added `button-text` and `button-text-sm`. Added a display step-down table and font-loading notes (variable Roboto Condensed for weight 360).
- **Colors:** added role tokens to both modes (`accent`, `accent-hover`, `on-accent`, `link`, `focus-ring`, `surface-muted`, `code-text`, `disabled-bg`, `disabled-text`). Added Dark `surface-muted` (#22263A). Added a mode mapping table and contrast rules.
- **Contrast:** Dark primary button and pill text changed from `text-primary` (2.58:1) to `on-accent` = Dark `canvas` (6.19:1). Banned mint as text on Light surfaces (1.48:1).
- **New sections:** Layout (max widths, gutters), Elevation (shadows), Motion (durations, easing, typing, reduced motion), Interaction States & Focus.
- **Components:** added hover/active/focus/disabled states, split `button-secondary` into Light and Dark versions, added Links, and moved Dark code blocks to `surface-muted` so they differ from Dark cards.
- **Cleanup:** removed the "Updated for v2.0" label, the stray editing note and the stray leading rule.

### v2.1
- Previous version.
