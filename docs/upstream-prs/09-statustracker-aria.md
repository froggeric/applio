# PR 9 (gradio) — branch `a11y/statustracker-aria` @ d026117ac on froggeric/gradio — DRAFT, NOT SUBMITTED

Target repo: **gradio-app/gradio** (not IAHispano/Applio). Branch is off their
`main` @ 7e839990a, committed and pushed to the fork `froggeric/gradio`
(fork created 2026-09-02; nothing opened against upstream yet).

Two process flags before the texts:

1. **gradio requires an issue.** Their PR template: "PRs Should Target Issues…
   If not, please create an issue before you create this PR, unless the fix is
   very small. Not adhering to this guideline will result in the PR being
   closed." No existing issue covers the loading status (searched 2026-09-02).
   So the plan is: post the issue below first, then the PR says `Closes #NNN`
   with the real number filled in.
2. **gradio has a mandatory AI Disclosure section** in the PR template
   ("I used AI to investigate the root cause and implement the fix" /
   "I did not use AI"). Hysts's merged a11y PR #13542 checks the first box.
   This draft checks it too — AI did the investigating and implementing here.
   Your call whether that stays.

---

## Issue text

### Title

Accessibility issue: loading progress is not announced to screen readers

### Body

While a function runs, the loading status that covers a component (queue position, progress bar, iteration counts) is invisible to screen readers.

The progress bar is a plain `<div>` with no `role`, and the text next to it updates silently. A voiceover (macos) or windows nvda user who submits a form gets no feedback: they cannot tell a task started, how far along it is, or where they are in the queue. For long-running jobs this means sitting with no feedback at all, not knowing if anything is happening.

To reproduce, run a function that takes a few seconds and listen with a screen reader:

```python
import time
import gradio as gr

def slow():
    time.sleep(8)
    return "done"

gr.Interface(slow, inputs=None, outputs="text").launch()
```

Nothing about the run is announced at any point.

I checked `js/statustracker/static/index.svelte` on current `main`, there are no `role` or `aria-*` attributes anywhere in the component.

---

## PR text

### Title

Acessibility improvement: make the loading status accessible to screen readers

### Body

## Description

The status tracker that covers a component while a function runs is invisible to screen readers: the progress bar is a plain `div` with no role, and the
queue position and iteration counts update silently. A blind user who submits a form cannot tell the run started, how far along it is, or where they are in
the queue. For apps with long-running jobs this is the difference between usable and unusable.

This adds the missing accessibility semantics to `js/statustracker/static/index.svelte`:

- The bar now has `role="progressbar"` with `aria-valuemin`/`aria-valuemax`/ `aria-valuenow`/`aria-valuetext`. This means it reads like any native progress bar. The value text uses the last progress tuple when there is one (eg: "processing files: 3 / 4 steps") and falls back to a percentage.
- A visually hidden "polite" live region announces milestone changes (every 10%, but never more than one announcement every five seconds), the queue position while actually waiting in line, and "Processing" when nothing more specific is known. The rate limit matters because every live region update interrupts what the screen reader is currently saying: without it a short run restarts the same sentence several times a second and the numbers are never reached. Hidden trackers stay silent, so the inputs tracking the same run do not double the messages. The visible text itself cannot serve as the live region: it updates every animation frame because of the running timer.
- The validation error block gets `role="alert"` so component-level validation errors are spoken when they appear.

The visible markup is unchanged apart from the added attributes.

Closes: #NNN

## Testing

- New unit tests in `js/statustracker/StatusTracker.test.ts` (progressbar attributes in both progress forms, milestone announcement on crossing,
  queue and processing announcements, alert role on validation errors). They  fail on the unpatched component and pass with the fix.
- Manually verified with voiceover on macos: the progress of a `gr.Progress`-tracking function is announced as it crosses milestones.

## AI Disclosure

- [x] I used AI to investigate the root cause and implement the fix.
- [ ] I did not use AI

---

## Notes for the edit pass (not part of either text)

- The VoiceOver line in Testing needs a real pass before it stays — you are
  the better judge of that than I am (a demo app with a slow `gr.Progress`
  function + VoiceOver; I can prepare the demo script when you want it).
  Remove the line if you would rather not claim it.
- The "In queue: 2 of 3" / "Processing" strings are hardcoded English, same
  as the existing visible "queue:" and "processing" literals in the component.
  I did not add i18n keys; say the word if you prefer them translated and I
  will wire the keys before submission.
- Multi-output apps render one tracker per output, so each output announces
  independently. Single-output apps (the common case) are unaffected. I left
  this out of the text; add a known-limitations line if you want it in.
- Diff: `index.svelte` +75/−1, `StatusTracker.test.ts` +186, one changeset
  file (`.changeset/screen-reader-progress.md`, `@gradio/statustracker` patch).
  Prettier `format:check` passes; CI's exact vitest invocation (node 24,
  browser mode) passes 11/11 in the package.
